"""A manual run picks its destination connection explicitly.

The Run dialog offers every connection assigned to the developer, and the backend opens
the chosen one with its *stored* credentials — the caller no longer has to connect to it
in the main app first. That is also what makes the run triggerable without a signed-in
session at all (a remote push or scheduler names the connection the same way).

The connection open is stubbed, so no database is needed; the generated SQL is captured
to prove the rows went to the picked connection's schema.
"""

from __future__ import annotations

import importlib
import json

import pytest
from fastapi.testclient import TestClient

FIELDS = [
    {"name": "timestamp", "role": "timestamp",
     "regex": r"\[(\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4})\]"},
    {"name": "event_id", "role": "id", "regex": r"userId=(\d+)"},
    {"name": "step", "role": "step", "regex": r'"[A-Z]+ /shop/([a-z]+)'},
]
LINE = ('10.0.0.1 - - [09/Jan/2015:19:12:14 +0000] 15233 '
        '"GET /shop/view?userId=20253471 HTTP/1.1" 200 8241 "-" "UA"')


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PMW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PMW_INTEGRATION_FILES_DIR", str(tmp_path / "files"))
    monkeypatch.delenv("PMW_INTEGRATION_ALLOW_ANY_PATH", raising=False)

    import app.config as config
    importlib.reload(config)
    import app.store.crypto as crypto
    importlib.reload(crypto)
    import app.services.certs  # noqa: F401 — reloaded transitively by security
    import app.store.security as security_mod
    importlib.reload(security_mod)
    import app.integration.files as files_mod
    importlib.reload(files_mod)
    import app.integration.extractors as extractors_mod
    importlib.reload(extractors_mod)
    import app.api.integration as integration_api
    importlib.reload(integration_api)
    import app.main as main
    importlib.reload(main)

    return config, security_mod.store, integration_api, main.app


def _seed(config, store, *, assign=("dev",)):
    """A developer, a File source with a source type, and two stored connections."""
    store.create_user("dev", "pw", is_admin=False)
    store.set_developer("dev", True)
    prod = store.upsert_connection({
        "name": "Prod", "host": "db1", "port": 8563, "username": "svc",
        "schema": "MINING", "password": "s3cret", "owner": "dev", "assignments": list(assign),
    })
    staging = store.upsert_connection({
        "name": "Staging", "host": "db2", "port": 8563, "username": "svc",
        "schema": "SANDBOX", "password": "s3cret", "owner": "dev", "assignments": list(assign),
    })
    st = store.add_source_type(
        "dev", name="Apache", config=json.dumps({"sample": "", "fields": FIELDS})
    )
    (config.INTEGRATION_FILES_DIR / "access.log").write_text(LINE + "\n")
    source = store.add_source("dev", name="Access log", kind="file", config=json.dumps({
        "path": "access.log", "encoding": "utf-8", "sourceTypeId": st.id,
    }))
    return source, prod, staging


class _Raw:
    def __init__(self) -> None:
        self.closed = False

    def commit(self) -> None: pass
    def rollback(self) -> None: pass
    def close(self) -> None: self.closed = True


def _stub_open(integration_api, monkeypatch, captured: list[str], opened: list):
    def fake(conn):
        raw = _Raw()
        opened.append((conn, raw))

        def run_sql(sql: str):
            captured.append(sql)
            return []  # existing keys → none; DDL/INSERT → no rows

        return raw, run_sql

    monkeypatch.setattr(integration_api, "open_stored_connection", fake)


def test_run_uses_the_picked_connection_without_an_active_session(env, monkeypatch):
    config, store, integration_api, app = env
    source, _prod, staging = _seed(config, store)
    captured: list[str] = []
    opened: list = []
    _stub_open(integration_api, monkeypatch, captured, opened)

    resp = TestClient(app).post(
        f"/api/integration/sources/{source.id}/run",
        headers={"X-PMW-User": "dev"},
        json={"titleShort": "P1", "connectionId": staging.id},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["records"] == 1
    # Opened the connection we named, not the (absent) active one …
    assert [c.name for c, _ in opened] == ["Staging"]
    # … and wrote into that connection's schema.
    assert any('"SANDBOX"."JOURNEYS"' in sql for sql in captured), captured
    assert not any('"MINING"' in sql for sql in captured), captured


def test_run_never_touches_the_live_session_connection(env, monkeypatch):
    """Regression: a run into the connection the app is already connected to must open its
    OWN connection, never toggle autocommit (or commit/rollback) on the shared live
    session — doing so would leave it in manual-commit mode, causing stale reads and held
    locks for the user's later app queries."""
    config, store, integration_api, app = env
    source, _prod, staging = _seed(config, store)

    class _LiveConn:
        def __init__(self):
            self.autocommit_calls = []

        def set_autocommit(self, value):
            self.autocommit_calls.append(value)

        def commit(self):
            raise AssertionError("the live session connection must not be committed")

        def rollback(self):
            raise AssertionError("the live session connection must not be rolled back")

    live = _LiveConn()

    class _FakeMgr:
        # Exactly the state the old code reused: connected to the very connection we run into.
        is_connected = True
        active_profile_id = staging.id
        _conn = live

    monkeypatch.setattr(integration_api, "current_db", lambda: _FakeMgr())

    captured: list[str] = []
    opened: list = []
    _stub_open(integration_api, monkeypatch, captured, opened)

    resp = _run(TestClient(app), source, staging)

    assert resp.status_code == 200, resp.text
    assert resp.json()["records"] == 1
    # A dedicated connection was opened and used …
    assert [c.name for c, _ in opened] == ["Staging"]
    # … and the live session connection was never touched.
    assert live.autocommit_calls == []


def test_the_run_closes_the_connection_it_opened(env, monkeypatch):
    """A run must not leak the connection it opened — including when it fails."""
    config, store, integration_api, app = env
    source, _prod, staging = _seed(config, store)
    opened: list = []

    def fake(conn):
        raw = _Raw()
        opened.append((conn, raw))

        def run_sql(sql: str):
            raise RuntimeError("schema is read-only")

        return raw, run_sql

    monkeypatch.setattr(integration_api, "open_stored_connection", fake)

    resp = TestClient(app).post(
        f"/api/integration/sources/{source.id}/run",
        headers={"X-PMW-User": "dev"},
        json={"titleShort": "P1", "connectionId": staging.id},
    )

    assert resp.status_code == 400
    assert opened and opened[0][1].closed is True


def test_a_connection_not_assigned_to_the_caller_is_refused(env, monkeypatch):
    """Assignment is the gate, re-checked server-side — knowing a connection's id must
    not be enough to write into it with credentials the caller never had."""
    config, store, integration_api, app = env
    source, _prod, staging = _seed(config, store)
    store.set_assignments(staging.id, [])  # revoke
    captured: list[str] = []
    opened: list = []
    _stub_open(integration_api, monkeypatch, captured, opened)

    resp = TestClient(app).post(
        f"/api/integration/sources/{source.id}/run",
        headers={"X-PMW-User": "dev"},
        json={"titleShort": "P1", "connectionId": staging.id},
    )

    assert resp.status_code == 404
    assert opened == []  # refused before any connection was opened


def _run(client, source, staging, **body):
    return client.post(
        f"/api/integration/sources/{source.id}/run",
        headers={"X-PMW-User": "dev"},
        json={"titleShort": "P1", "connectionId": staging.id, **body},
    )


def _inserts(captured: list[str]) -> list[str]:
    return [s for s in captured if s.startswith('INSERT INTO "SANDBOX"."JOURNEYS"')]


def test_a_manual_run_is_a_delta_upload_by_default(env, monkeypatch):
    """Running the same source twice must not store the file twice: the first run reads
    the whole file and checkpoints it, the second finds nothing new."""
    config, store, integration_api, app = env
    source, _prod, staging = _seed(config, store)
    captured: list[str] = []
    _stub_open(integration_api, monkeypatch, captured, [])
    client = TestClient(app)

    first = _run(client, source, staging)
    assert first.status_code == 200, first.text
    assert first.json()["records"] == 1
    assert len(_inserts(captured)) == 1

    captured.clear()
    second = _run(client, source, staging)
    assert second.status_code == 200
    assert second.json()["records"] == 0
    assert second.json()["linesRead"] == 0
    assert "not grown" in second.json()["detail"]
    assert _inserts(captured) == []  # nothing written the second time

    # A line appended after the first run is the only thing the third run imports.
    log = config.INTEGRATION_FILES_DIR / "access.log"
    log.write_text(log.read_text() + LINE.replace("userId=20253471", "userId=999") + "\n")
    captured.clear()
    third = _run(client, source, staging)
    assert third.json()["records"] == 1
    assert len(_inserts(captured)) == 1


def test_a_large_file_is_imported_in_one_run(env, monkeypatch):
    """A file bigger than the 8 MB per-read cap must import fully in ONE run — the manual
    run drains the whole file, it does not stop after the first chunk and leave a backlog."""
    config, store, integration_api, app = env
    source, _prod, staging = _seed(config, store)

    # Rewrite the source's file with enough lines to exceed the chunk cap.
    import app.integration.files as files_mod
    log = config.INTEGRATION_FILES_DIR / "access.log"
    line = (
        "10.0.0.1 - - [09/Jan/2015:19:12:14 +0000] 15233 "
        '"GET /shop/view?userId={} HTTP/1.1" 200 8241 "-" "UA"\n'
    )
    # ~120 bytes/line; enough lines to clear 8 MB with headroom.
    n = int(files_mod._MAX_CHUNK_BYTES / 110) + 5000
    with log.open("w") as fh:
        for i in range(n):
            fh.write(line.format(20000000 + i))
    assert log.stat().st_size > files_mod._MAX_CHUNK_BYTES  # genuinely over the cap

    captured: list[str] = []
    _stub_open(integration_api, monkeypatch, captured, [])

    resp = _run(TestClient(app), source, staging)
    assert resp.status_code == 200, resp.text
    # Every line imported in this single run (all userIds are unique → all parse).
    assert resp.json()["records"] == n
    assert resp.json()["linesRead"] == n

    # The checkpoint reached EOF, so a second run finds nothing new.
    cp = TestClient(app).get(
        f"/api/integration/sources/{source.id}/checkpoint", headers={"X-PMW-User": "dev"}
    ).json()
    assert cp["byteOffset"] == log.stat().st_size
    captured.clear()
    again = _run(TestClient(app), source, staging)
    assert again.json()["records"] == 0 and again.json()["linesRead"] == 0


def test_delta_off_re_reads_the_whole_file(env, monkeypatch):
    config, store, integration_api, app = env
    source, _prod, staging = _seed(config, store)
    captured: list[str] = []
    _stub_open(integration_api, monkeypatch, captured, [])
    client = TestClient(app)

    assert _run(client, source, staging).json()["records"] == 1
    captured.clear()
    again = _run(client, source, staging, delta=False)
    assert again.json()["records"] == 1  # read from the top again, duplicates and all
    assert len(_inserts(captured)) == 1


def test_an_empty_log_file_imports_nothing_without_failing(env, monkeypatch):
    """A source pointed at an empty (or not-yet-written) file is a normal state — the run
    reports nothing to import rather than erroring."""
    config, store, integration_api, app = env
    source, _prod, staging = _seed(config, store)
    (config.INTEGRATION_FILES_DIR / "access.log").write_text("")
    captured: list[str] = []
    _stub_open(integration_api, monkeypatch, captured, [])

    resp = _run(TestClient(app), source, staging)
    assert resp.status_code == 200, resp.text
    assert resp.json()["records"] == 0
    assert resp.json()["linesRead"] == 0
    assert "empty" in resp.json()["detail"]
    assert _inserts(captured) == []


def test_resetting_the_checkpoint_makes_the_next_run_re_read(env, monkeypatch):
    config, store, integration_api, app = env
    source, _prod, staging = _seed(config, store)
    captured: list[str] = []
    _stub_open(integration_api, monkeypatch, captured, [])
    client = TestClient(app)

    assert _run(client, source, staging).json()["records"] == 1
    assert client.get(
        f"/api/integration/sources/{source.id}/checkpoint", headers={"X-PMW-User": "dev"}
    ).json()["records"] == 1

    reset = client.post(
        f"/api/integration/sources/{source.id}/checkpoint/reset", headers={"X-PMW-User": "dev"}
    )
    assert reset.status_code == 200
    cp = client.get(
        f"/api/integration/sources/{source.id}/checkpoint", headers={"X-PMW-User": "dev"}
    ).json()
    assert cp["byteOffset"] == 0 and cp["records"] == 0

    captured.clear()
    assert _run(client, source, staging).json()["records"] == 1  # read from the top again
    assert len(_inserts(captured)) == 1


def test_a_failed_run_leaves_the_checkpoint_where_it_was(env, monkeypatch):
    """Advancing on failure would silently skip the lines that were never written."""
    config, store, integration_api, app = env
    source, _prod, staging = _seed(config, store)

    def boom(conn):
        def run_sql(sql: str):
            raise RuntimeError("schema is read-only")

        return _Raw(), run_sql

    monkeypatch.setattr(integration_api, "open_stored_connection", boom)
    client = TestClient(app)
    assert _run(client, source, staging).status_code == 400

    cp = client.get(
        f"/api/integration/sources/{source.id}/checkpoint", headers={"X-PMW-User": "dev"}
    ).json()
    assert cp["byteOffset"] == 0 and cp["records"] == 0

    # The line is still pending, so a working retry imports it.
    captured: list[str] = []
    _stub_open(integration_api, monkeypatch, captured, [])
    assert _run(client, source, staging).json()["records"] == 1


def test_a_run_remembers_its_destination_on_the_source(env, monkeypatch):
    """The Run dialog reopens on the connection + project last imported into, so a
    repeated import is one click rather than two pickers."""
    config, store, integration_api, app = env
    source, _prod, staging = _seed(config, store)
    _stub_open(integration_api, monkeypatch, [], [])
    client = TestClient(app)

    assert _run(client, source, staging).status_code == 200
    cfg = next(s for s in store.list_sources("dev") if s.id == source.id).public()["config"]
    assert cfg["lastRun"] == {"connectionId": staging.id, "titleShort": "P1"}

    # It follows the latest run, not the first.
    assert _run(client, source, staging, titleShort="P2", delta=False).status_code == 200
    cfg = next(s for s in store.list_sources("dev") if s.id == source.id).public()["config"]
    assert cfg["lastRun"]["titleShort"] == "P2"


def test_editing_a_source_keeps_its_remembered_destination(env, monkeypatch):
    """The wizard never sends `lastRun`, so a plain save must not wipe it."""
    config, store, integration_api, app = env
    source, _prod, staging = _seed(config, store)
    _stub_open(integration_api, monkeypatch, [], [])
    client = TestClient(app)
    assert _run(client, source, staging).status_code == 200

    cfg = next(s for s in store.list_sources("dev") if s.id == source.id).public()["config"]
    resp = client.put(
        f"/api/integration/sources/{source.id}",
        headers={"X-PMW-User": "dev"},
        json={
            "name": "Access log (renamed)", "kind": "file",
            # exactly what the wizard sends — no lastRun
            "config": {"path": cfg["path"], "encoding": "utf-8",
                       "sourceTypeId": cfg["sourceTypeId"]},
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["config"]["lastRun"] == {"connectionId": staging.id, "titleShort": "P1"}


def test_remembering_the_destination_never_fails_the_import(env, monkeypatch):
    """Bookkeeping runs after the rows are committed — it must not turn a successful
    import into an error for the caller."""
    config, store, integration_api, app = env
    source, _prod, staging = _seed(config, store)
    _stub_open(integration_api, monkeypatch, [], [])
    monkeypatch.setattr(
        integration_api.security_store, "update_source",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("store is locked")),
    )

    resp = _run(TestClient(app), source, staging)
    assert resp.status_code == 200
    assert resp.json()["records"] == 1


def test_the_project_list_is_gated_on_assignment_not_management(env, monkeypatch):
    """The Run dialog fills its project dropdown from the destination schema. A developer
    is only *assigned* a connection (never its manager), so this must not reuse the
    manager-gated /api/connections/{id}/projects — but it must still refuse a connection
    the caller has no assignment to."""
    config, store, integration_api, app = env
    _source, _prod, staging = _seed(config, store)
    seen: list[str] = []

    async def fake_list(**kwargs):
        seen.append(kwargs["schema"])
        return {"ok": True, "error": None,
                "projects": [{"projectId": "P1", "title": "", "journeys": 2, "events": 9}]}

    import app.db.schema_ddl as schema_ddl
    monkeypatch.setattr(schema_ddl, "list_projects_with_counts", fake_list)
    client = TestClient(app)

    resp = client.get(
        f"/api/integration/connections/{staging.id}/projects",
        headers={"X-PMW-User": "dev"},
    )
    assert resp.status_code == 200, resp.text
    assert [p["projectId"] for p in resp.json()["projects"]] == ["P1"]
    assert seen == ["SANDBOX"]  # read from the picked connection's own schema

    store.set_assignments(staging.id, [])  # revoke
    resp = client.get(
        f"/api/integration/connections/{staging.id}/projects",
        headers={"X-PMW-User": "dev"},
    )
    assert resp.status_code == 404
    assert seen == ["SANDBOX"]  # nothing was opened on the refused call


def test_a_connection_without_a_schema_is_rejected_by_name(env, monkeypatch):
    config, store, integration_api, app = env
    source, _prod, staging = _seed(config, store)
    store.upsert_connection({
        "id": staging.id, "name": "Staging", "host": "db2", "port": 8563,
        "username": "svc", "schema": "", "owner": "dev", "assignments": ["dev"],
    })
    opened: list = []
    _stub_open(integration_api, monkeypatch, [], opened)

    resp = TestClient(app).post(
        f"/api/integration/sources/{source.id}/run",
        headers={"X-PMW-User": "dev"},
        json={"titleShort": "P1", "connectionId": staging.id},
    )

    assert resp.status_code == 400
    assert "Staging" in resp.json()["detail"]
    assert opened == []
