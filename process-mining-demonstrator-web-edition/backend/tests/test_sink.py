"""API Server - Event Receiver — the JSON→JOURNEYS write path, token hashing, the port pool
and admin gate. The ingestion write is exercised against the in-memory backend."""

from __future__ import annotations

import importlib

import pytest

from app.integration.backends import InMemoryIngestBackend
from app.integration.contract import IngestError
from app.integration import sink_ingest as si


def _rows(backend: InMemoryIngestBackend, schema: str, table: str) -> list[dict]:
    tbl = backend.tables.get(schema, {}).get(table)
    return list(tbl["rows"]) if tbl else []


def test_ingest_writes_journeys_and_creates_unknown_steps():
    backend = InMemoryIngestBackend()
    commits = {"n": 0}

    res = si.ingest_entries(
        backend, lambda: commits.__setitem__("n", commits["n"] + 1),
        schema="MINING", title_short="AGENTLOG",
        entries=[
            {"eventId": "case-1", "step": "ENTER Security Check", "eventTime": "2026-09-13T10:00:00"},
            {"eventId": "case-1", "step": "BOARD Aircraft", "eventTime": "2026-09-13T10:20:00"},
        ],
    )
    assert res["ingested"] == 2
    assert sorted(res["newSteps"]) == ["BOARD Aircraft", "ENTER Security Check"]
    assert commits["n"] == 1  # one commit for the batch

    journeys = _rows(backend, "MINING", "JOURNEYS")
    assert len(journeys) == 2
    # Distinct activity ids for the two steps; EVENT_ID pseudonymised to a 32-char hex.
    assert {r["STEP_ID"] for r in journeys} == {1, 2}
    assert all(len(str(r["EVENT_ID"])) == 32 for r in journeys)
    assert {r["SAMPLE_SET"] for r in journeys} == {"ORIGINAL"}
    # PROJECTS + STEPS rows were created for the new project/steps.
    assert _rows(backend, "MINING", "PROJECTS")[0]["TITLE_SHORT"] == "AGENTLOG"
    assert len(_rows(backend, "MINING", "STEPS")) == 2


def test_action_client_user_map_to_titled_meta_columns():
    backend = InMemoryIngestBackend()
    si.ingest_entries(
        backend, lambda: None, schema="S", title_short="APP",
        entries=[
            {"eventId": "r1", "step": "SKILL", "description": "Summarize sales",
             "client": "Claude", "user": "alice"},
            {"eventId": "r1", "step": "DATABASE", "description": "Query sales table",
             "client": "Claude"},  # user omitted
        ],
    )
    j = {r["STEP"]: r for r in _rows(backend, "S", "JOURNEYS")}
    # description → META_1 (Action), client → META_2 (Client), user → META_3 (User).
    assert j["SKILL"]["META_1"] == "Summarize sales"
    assert j["SKILL"]["META_2"] == "Claude"
    assert j["SKILL"]["META_3"] == "alice"
    assert j["DATABASE"]["META_1"] == "Query sales table"
    assert j["DATABASE"]["META_3"] == ""  # user omitted → blank

    # The description is NOT written onto the STEP record any more.
    steps = {r["STEP"]: r for r in _rows(backend, "S", "STEPS")}
    assert steps["SKILL"]["DESCRIPTION"] == ""

    # A single METAS row titles the three columns Action / Client / User for the UI.
    metas = _rows(backend, "S", "METAS")
    assert len(metas) == 1
    assert metas[0]["META_1_TITLE"] == "Action"
    assert metas[0]["META_2_TITLE"] == "Client"
    assert metas[0]["META_3_TITLE"] == "User"


def test_meta1_action_detail_is_capped_at_256_chars():
    backend = InMemoryIngestBackend()
    si.ingest_entries(
        backend, lambda: None, schema="S", title_short="APP",
        entries=[{"eventId": "r1", "step": "DATABASE:sales_db", "description": "x" * 400}],
    )
    row = _rows(backend, "S", "JOURNEYS")[0]
    assert len(row["META_1"]) == 256  # long detail is truncated, not rejected
    assert row["STEP"] == "DATABASE:sales_db"  # qualified step stored verbatim


def test_ingest_reuses_ids_and_appends_to_existing_project():
    backend = InMemoryIngestBackend()
    noop = lambda: None
    si.ingest_entries(backend, noop, schema="S", title_short="APP",
                      entries=[{"eventId": "a", "step": "Login"}])
    first_pid = _rows(backend, "S", "PROJECTS")[0]["PROJECT_ID"]
    first_step_id = _rows(backend, "S", "STEPS")[0]["STEP_ID"]

    # A second post reuses the same project id and the same step id for "Login",
    # and allocates a new id for the unseen "Logout".
    res = si.ingest_entries(backend, noop, schema="S", title_short="APP",
                            entries=[{"eventId": "b", "step": "Login"},
                                     {"eventId": "b", "step": "Logout"}])
    assert res["newSteps"] == ["Logout"]
    assert len(_rows(backend, "S", "PROJECTS")) == 1  # not re-created
    logout = next(r for r in _rows(backend, "S", "JOURNEYS") if r["STEP"] == "Logout")
    login = next(r for r in _rows(backend, "S", "JOURNEYS") if r["STEP"] == "Login")
    assert login["STEP_ID"] == first_step_id
    assert logout["STEP_ID"] != first_step_id
    assert {r["PROJECT_ID"] for r in _rows(backend, "S", "JOURNEYS")} == {first_pid}


def test_ingest_rejects_entries_without_event_or_step():
    backend = InMemoryIngestBackend()
    with pytest.raises(IngestError):
        si.ingest_entries(backend, lambda: None, schema="S", title_short="APP",
                          entries=[{"eventId": "a"}])  # no step
    with pytest.raises(IngestError):
        si.ingest_entries(backend, lambda: None, schema="S", title_short="APP",
                          entries=[{"step": "X"}])  # no eventId


def test_token_hash_roundtrip():
    token = "s3cret-token"
    digest = si.hash_sink_token(token)
    assert si.verify_sink_token(token, digest)
    assert not si.verify_sink_token("wrong", digest)
    assert not si.verify_sink_token("", digest)
    assert not si.verify_sink_token(token, "")


def test_sink_kind_registered_and_port_pool():
    import app.api.integration as integ
    import app.config as config

    assert config.SINK_SOURCE_KIND in integ.SOURCE_KINDS
    assert len(config.SINK_HTTP_PORTS) == config.SINK_POOL_SIZE
    # HTTP port maps to a distinct HTTPS peer at the same pool offset.
    assert config.sink_https_port_for(config.SINK_HTTP_PORTS[0]) == config.SINK_HTTPS_PORT_BASE
    assert config.sink_https_port_for(config.SINK_HTTP_PORTS[2]) == config.SINK_HTTPS_PORT_BASE + 2


def test_store_sink_enabled_toggles(tmp_path, monkeypatch):
    monkeypatch.setenv("PMW_DATA_DIR", str(tmp_path))
    import app.config as config
    importlib.reload(config)
    import app.store.crypto as crypto
    importlib.reload(crypto)
    import app.store.security as security_mod
    importlib.reload(security_mod)
    store = security_mod.store

    assert store.sink_enabled is False  # opt-in, off by default
    store.set_sink_enabled(True)
    assert store.sink_enabled is True
    assert store.list_all_sinks() == []  # no sinks configured yet


@pytest.fixture
def api_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("PMW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PMW_INTEGRATION_FILES_DIR", str(tmp_path / "files"))
    import app.config as config
    importlib.reload(config)
    import app.store.crypto as crypto
    importlib.reload(crypto)
    import app.services.certs  # noqa: F401
    import app.store.security as security_mod
    importlib.reload(security_mod)
    import app.integration.files as files_mod
    importlib.reload(files_mod)
    import app.api.integration as integration_api
    importlib.reload(integration_api)
    import app.main as main
    importlib.reload(main)
    return main.app, security_mod.store, config


def _conn(store, user):
    return store.upsert_connection({
        "name": "Dest", "host": "db", "port": 8563, "username": "u", "schema": "MINING",
        "password": "p", "llmURL": "", "llmModel": "", "llmKey": "", "assignments": [user],
    }).id


def test_create_sink_returns_token_once_and_validates(api_backend):
    from fastapi.testclient import TestClient

    app, store, config = api_backend
    store.create_user("dev", "pw", is_admin=False)
    store.set_developer("dev", True)
    cid = _conn(store, "dev")
    client = TestClient(app)
    hdr = {"X-PMW-User": "dev"}
    port = config.SINK_HTTP_PORTS[0]
    body = {
        "name": "Agent sink", "kind": config.SINK_SOURCE_KIND,
        "config": {"connectionId": cid, "titleShort": "AGENTLOG", "port": port},
    }

    r = client.post("/api/integration/sources", json=body, headers=hdr)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["token"]  # plaintext shown once
    assert data["config"].get("tokenHash") and "token" not in data["config"]  # only the hash is stored

    # The port now shows as taken, and a second sink on it is refused.
    used = client.get("/api/integration/sink-ports", headers=hdr).json()["used"]
    assert str(port) in used
    assert client.post("/api/integration/sources", json={**body, "name": "Dup"}, headers=hdr).status_code == 400

    # A port outside the pool, and an unassigned connection, are refused.
    bad_port = {**body, "name": "BadPort", "config": {**body["config"], "port": 1}}
    assert client.post("/api/integration/sources", json=bad_port, headers=hdr).status_code == 400
    bad_conn = {**body, "name": "BadConn",
                "config": {"connectionId": "nope", "titleShort": "X", "port": config.SINK_HTTP_PORTS[1]}}
    assert client.post("/api/integration/sources", json=bad_conn, headers=hdr).status_code == 400


def test_regenerate_sink_token(api_backend):
    import json as _json
    from fastapi.testclient import TestClient

    app, store, config = api_backend
    store.create_user("dev", "pw", is_admin=False)
    store.set_developer("dev", True)
    cid = _conn(store, "dev")
    client = TestClient(app)
    hdr = {"X-PMW-User": "dev"}

    r = client.post("/api/integration/sources", json={
        "name": "S", "kind": config.SINK_SOURCE_KIND,
        "config": {"connectionId": cid, "titleShort": "AGENTLOG", "port": config.SINK_HTTP_PORTS[0]},
    }, headers=hdr)
    sid, tok1 = r.json()["id"], r.json()["token"]

    r2 = client.post(f"/api/integration/sources/{sid}/regenerate-token", headers=hdr)
    assert r2.status_code == 200
    tok2 = r2.json()["token"]
    assert tok2 and tok2 != tok1
    # The stored hash now matches the NEW token only.
    src = next(s for s in store.list_all_sinks() if s.id == sid)
    assert _json.loads(src.config)["tokenHash"] == si.hash_sink_token(tok2)
    assert not si.verify_sink_token(tok1, _json.loads(src.config)["tokenHash"])

    # A file source has no token to regenerate.
    fr = client.post("/api/integration/sources", json={
        "name": "F", "kind": "file", "config": {"path": "x.log"},
    }, headers=hdr)
    fid = fr.json()["id"]
    assert client.post(f"/api/integration/sources/{fid}/regenerate-token", headers=hdr).status_code == 400


def test_sink_ingest_info(api_backend):
    from fastapi.testclient import TestClient

    app, store, config = api_backend
    store.create_user("dev", "pw", is_admin=False)
    store.set_developer("dev", True)
    cid = _conn(store, "dev")
    client = TestClient(app)
    hdr = {"X-PMW-User": "dev"}
    port = config.SINK_HTTP_PORTS[0]
    sid = client.post("/api/integration/sources", json={
        "name": "S", "kind": config.SINK_SOURCE_KIND,
        "config": {"connectionId": cid, "titleShort": "AGENTLOG", "port": port},
    }, headers=hdr).json()["id"]

    info = client.get(f"/api/integration/sources/{sid}/ingest-info", headers=hdr).json()
    assert info["path"] == "/ingest" and info["titleShort"] == "AGENTLOG"
    assert info["httpPort"] == port and info["httpsPort"] == config.sink_https_port_for(port)
    assert info["consoleHttpPort"] == config.INTEGRATION_PORT
    assert info["consoleHttpsPort"] == config.INTEGRATION_HTTPS_PORT
    # Default TLS mode is off → the live endpoint is plain HTTP on the http port.
    assert info["tlsMode"] == "off"
    assert info["activeScheme"] == "http" and info["activeContainerPort"] == port


def test_sink_endpoint_url_override_saves_and_surfaces(api_backend):
    from fastapi.testclient import TestClient

    app, store, config = api_backend
    store.create_user("dev", "pw", is_admin=False)
    store.set_developer("dev", True)
    cid = _conn(store, "dev")
    client = TestClient(app)
    hdr = {"X-PMW-User": "dev"}
    sid = client.post("/api/integration/sources", json={
        "name": "S", "kind": config.SINK_SOURCE_KIND,
        "config": {"connectionId": cid, "titleShort": "AGENTLOG", "port": config.SINK_HTTP_PORTS[0]},
    }, headers=hdr).json()["id"]

    # Save a public URL override → it comes back on ingest-info.
    r = client.post(f"/api/integration/sources/{sid}/sink-endpoint",
                    json={"url": "https://pm.example.com/ingest"}, headers=hdr)
    assert r.status_code == 200 and r.json()["endpointUrl"] == "https://pm.example.com/ingest"
    info = client.get(f"/api/integration/sources/{sid}/ingest-info", headers=hdr).json()
    assert info["endpointUrl"] == "https://pm.example.com/ingest"

    # A non-URL is rejected; an empty string clears the override.
    assert client.post(f"/api/integration/sources/{sid}/sink-endpoint",
                       json={"url": "not a url"}, headers=hdr).status_code == 400
    assert client.post(f"/api/integration/sources/{sid}/sink-endpoint",
                       json={"url": ""}, headers=hdr).json()["endpointUrl"] == ""
    # The override survives a wizard edit (carried through _prepare_sink_config).
    client.post(f"/api/integration/sources/{sid}/sink-endpoint",
                json={"url": "https://pm.example.com/ingest"}, headers=hdr)
    client.put(f"/api/integration/sources/{sid}", json={
        "name": "S2", "kind": config.SINK_SOURCE_KIND,
        "config": {"connectionId": cid, "titleShort": "AGENTLOG",
                   "port": config.SINK_HTTP_PORTS[0], "endpointUrl": "https://pm.example.com/ingest"},
    }, headers=hdr)
    info2 = client.get(f"/api/integration/sources/{sid}/ingest-info", headers=hdr).json()
    assert info2["endpointUrl"] == "https://pm.example.com/ingest"


def test_sink_ports_lists_the_https_peer_of_each_slot(api_backend):
    from fastapi.testclient import TestClient

    app, store, config = api_backend
    store.create_user("dev", "pw", is_admin=False)
    store.set_developer("dev", True)
    client = TestClient(app)
    data = client.get("/api/integration/sink-ports", headers={"X-PMW-User": "dev"}).json()
    assert data["pool"] == list(config.SINK_HTTP_PORTS)
    # Each pool (HTTP) port maps to its paired HTTPS port, for the wizard's dropdown.
    p0 = config.SINK_HTTP_PORTS[0]
    assert data["https"][str(p0)] == config.sink_https_port_for(p0)


def test_sink_tls_preference_drives_shown_scheme(api_backend, monkeypatch):
    """With the deployment able to serve BOTH schemes (TLS optional + cert), the per-sink
    TLS checkbox decides which endpoint ingest-info advertises."""
    from fastapi.testclient import TestClient
    import app.api.integration as integration_api

    app, store, config = api_backend
    store.create_user("dev", "pw", is_admin=False)
    store.set_developer("dev", True)
    cid = _conn(store, "dev")
    client = TestClient(app)
    hdr = {"X-PMW-User": "dev"}
    port = config.SINK_HTTP_PORTS[0]

    # Pretend the deployment serves http AND https (TLS 'optional' with an active cert).
    monkeypatch.setattr(
        integration_api.security_store, "tls_plan",
        lambda: {"mode": "optional", "hasActiveCert": True, "https": True, "http": True},
    )

    def make(name, port_, tls):
        return client.post("/api/integration/sources", json={
            "name": name, "kind": config.SINK_SOURCE_KIND,
            "config": {"connectionId": cid, "titleShort": "AGENTLOG", "port": port_, "tls": tls},
        }, headers=hdr).json()["id"]

    sid_tls = make("TLS sink", port, True)
    sid_plain = make("Plain sink", config.SINK_HTTP_PORTS[1], False)

    tls_info = client.get(f"/api/integration/sources/{sid_tls}/ingest-info", headers=hdr).json()
    assert tls_info["activeScheme"] == "https"
    assert tls_info["activeContainerPort"] == config.sink_https_port_for(port)

    plain_info = client.get(f"/api/integration/sources/{sid_plain}/ingest-info", headers=hdr).json()
    assert plain_info["activeScheme"] == "http"
    assert plain_info["activeContainerPort"] == config.SINK_HTTP_PORTS[1]


def test_sink_app_ingest_requires_token_and_honours_the_gate(monkeypatch):
    import types
    from fastapi.testclient import TestClient

    import app.sink_server as ss

    fake_store = types.SimpleNamespace(sink_enabled=True)
    monkeypatch.setattr(ss, "store", fake_store)
    monkeypatch.setattr(ss, "open_stored_connection", lambda conn: (
        types.SimpleNamespace(commit=lambda: None, rollback=lambda: None, close=lambda: None),
        lambda sql: [],
    ))
    monkeypatch.setattr(ss, "ensure_schema", lambda run_sql, schema: None)
    monkeypatch.setattr(ss, "ingest_entries", lambda backend, commit, *, schema, title_short, entries: {
        "ingested": len(list(entries)), "newSteps": [],
    })

    token = "tok-123"
    app = ss.build_sink_app(
        name="s", title_short="APP", token_hash=si.hash_sink_token(token),
        connection=types.SimpleNamespace(schema="MINING"),
    )
    client = TestClient(app)
    entry = [{"eventId": "a", "step": "X"}]

    assert client.get("/health").json()["enabled"] is True
    assert client.post("/ingest", json=entry).status_code == 401  # no token
    assert client.post("/ingest", json=entry, headers={"Authorization": "Bearer nope"}).status_code == 401
    ok = client.post("/ingest", json=entry, headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200 and ok.json()["ingested"] == 1

    fake_store.sink_enabled = False  # module disabled → 503 even with a valid token
    assert client.post("/ingest", json=entry, headers={"Authorization": f"Bearer {token}"}).status_code == 503


def _sink_client(monkeypatch, ingest_fn):
    """Build a sink app + client with the DB fully stubbed; `ingest_fn` stands in for
    ingest_entries. Returns (client, token, opens, calls) counters."""
    import types
    from fastapi.testclient import TestClient
    import app.sink_server as ss

    monkeypatch.setattr(ss, "store", types.SimpleNamespace(sink_enabled=True))
    opens = {"n": 0}

    def fake_open(conn):
        opens["n"] += 1
        return (
            types.SimpleNamespace(commit=lambda: None, rollback=lambda: None, close=lambda: None),
            lambda sql: [],
        )

    monkeypatch.setattr(ss, "open_stored_connection", fake_open)
    monkeypatch.setattr(ss, "ensure_schema", lambda run_sql, schema: None)
    calls = {"n": 0}

    def wrapped(backend, commit, *, schema, title_short, entries):
        calls["n"] += 1
        return ingest_fn(list(entries), calls["n"])

    monkeypatch.setattr(ss, "ingest_entries", wrapped)
    token = "tok"
    app = ss.build_sink_app(
        name="s", title_short="APP", token_hash=si.hash_sink_token(token),
        connection=types.SimpleNamespace(schema="MINING"),
    )
    return TestClient(app), token, opens, calls


def test_sink_reconnects_and_retries_once_on_stale_connection(monkeypatch):
    # First write hits a dead socket (Exasol error 110); the sink must reconnect and
    # retry, so the client sees success rather than a 502.
    def ingest(entries, n):
        if n == 1:
            raise RuntimeError("message => 110, dsn => host.docker.internal:8563, user => sys")
        return {"ingested": len(entries), "newSteps": []}

    client, token, opens, calls = _sink_client(monkeypatch, ingest)
    r = client.post("/ingest", json=[{"eventId": "a", "step": "X"}],
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200 and r.json()["ingested"] == 1
    assert opens["n"] == 2 and calls["n"] == 2  # reconnected + retried exactly once


def test_sink_gives_up_after_one_retry(monkeypatch):
    # A persistent connection failure surfaces as 502 after a single retry (no infinite loop).
    def always_fail(entries, n):
        raise RuntimeError("message => 110")

    client, token, opens, calls = _sink_client(monkeypatch, always_fail)
    r = client.post("/ingest", json=[{"eventId": "a", "step": "X"}],
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 502
    assert opens["n"] == 2 and calls["n"] == 2


def test_sink_does_not_retry_bad_payload(monkeypatch):
    # Validation errors are deterministic — surface as 400 without a reconnect/retry.
    def bad(entries, n):
        raise IngestError("Each entry needs a non-empty 'eventId' and 'step'.")

    client, token, opens, calls = _sink_client(monkeypatch, bad)
    r = client.post("/ingest", json=[{"eventId": "a"}],
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400
    assert opens["n"] == 1 and calls["n"] == 1


def test_sink_502_does_not_leak_internal_db_details(monkeypatch):
    # A DB failure carries the internal DSN/user/schema in its text — the client must get
    # a GENERIC message, and the write must never have been attempted-and-echoed back.
    leak = "message => 110, dsn => host.docker.internal:8563, user => sys, schema => PM_Sandbox"

    def boom(entries, n):
        raise RuntimeError(leak)

    client, token, _opens, _calls = _sink_client(monkeypatch, boom)
    r = client.post("/ingest", json=[{"eventId": "a", "step": "X"}],
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "host.docker.internal" not in detail and "sys" not in detail and "PM_Sandbox" not in detail
    assert detail == "Ingest failed; the destination database is temporarily unavailable."


def test_sink_rejects_oversized_body_and_entry_flood(monkeypatch):
    import app.config as config

    calls = {"n": 0}
    client, token, _opens, call_counter = _sink_client(
        monkeypatch, lambda entries, n: {"ingested": len(entries), "newSteps": []}
    )
    hdr = {"Authorization": f"Bearer {token}"}

    # A body past the byte ceiling is refused with 413 before any DB work.
    big = b"x" * (config.SINK_MAX_BODY_BYTES + 1)
    r = client.post("/ingest", content=big, headers={**hdr, "Content-Type": "application/json"})
    assert r.status_code == 413
    assert call_counter["n"] == 0  # never reached the write path

    # Too many entries (small bodies each) is also refused with 413.
    flood = [{"eventId": str(i), "step": "X"} for i in range(config.SINK_MAX_ENTRIES + 1)]
    r2 = client.post("/ingest", json=flood, headers=hdr)
    assert r2.status_code == 413
    assert call_counter["n"] == 0


def test_sink_health_reveals_no_identifying_detail(monkeypatch):
    client, _token, _opens, _calls = _sink_client(monkeypatch, lambda entries, n: {})
    body = client.get("/health").json()
    assert body == {"ok": True, "enabled": True}  # no sink name / config leaked


# ── /sinks/monitor — the live, node-based monitor view ─────────────────────────

def _patch_monitor(monkeypatch, *, projects, ok=True, error=None, live=True):
    """Stub the monitor's two external touchpoints: the destination-DB read
    (``list_projects_with_counts``) and the per-sink /health probe."""
    import app.db.schema_ddl as schema_ddl
    import app.api.integration as integration_api

    async def fake_counts(**_kwargs):
        return {"ok": ok, "error": error, "projects": projects}

    async def fake_probe(entries):
        for e in entries:
            e["live"] = live

    monkeypatch.setattr(schema_ddl, "list_projects_with_counts", fake_counts)
    monkeypatch.setattr(integration_api, "_probe_sink_liveness", fake_probe)


def test_sinks_monitor_reports_config_liveness_and_db_counts(api_backend, monkeypatch):
    from fastapi.testclient import TestClient

    app, store, config = api_backend
    store.create_user("dev", "pw", is_admin=False)
    store.set_developer("dev", True)
    store.set_sink_enabled(True)
    cid = _conn(store, "dev")
    client = TestClient(app)
    hdr = {"X-PMW-User": "dev"}
    port = config.SINK_HTTP_PORTS[0]
    client.post("/api/integration/sources", json={
        "name": "Agent sink", "kind": config.SINK_SOURCE_KIND,
        "config": {"connectionId": cid, "titleShort": "AGENTLOG", "port": port},
    }, headers=hdr)

    _patch_monitor(monkeypatch, projects=[
        {"projectId": 1, "title": "Agent log", "titleShort": "AGENTLOG",
         "journeys": 3, "events": 12, "lastEventAt": "2026-09-14T10:00:00"},
        {"projectId": 2, "title": "Other", "titleShort": "OTHER",
         "journeys": 9, "events": 99, "lastEventAt": "2026-01-01T00:00:00"},
    ], live=True)

    r = client.get("/api/integration/sinks/monitor", headers=hdr)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["moduleEnabled"] is True
    assert data["supervisorRunning"] is False  # no pid file in the test data dir
    assert len(data["sinks"]) == 1
    s = data["sinks"][0]
    assert s["name"] == "Agent sink" and s["port"] == port
    assert s["connectionName"] == "Dest" and s["schema"] == "MINING"
    assert s["live"] is True and s["error"] is None
    # Counts matched to the sink's OWN titleShort, not another project's.
    assert s["events"] == 12 and s["journeys"] == 3
    assert s["lastEventAt"] == "2026-09-14T10:00:00"
    # The internal container port is not leaked to host clients.
    assert "activeContainerPort" not in s


def test_sinks_monitor_only_shows_the_callers_sinks(api_backend, monkeypatch):
    from fastapi.testclient import TestClient

    app, store, config = api_backend
    for u in ("dev", "other"):
        store.create_user(u, "pw", is_admin=False)
        store.set_developer(u, True)
    client = TestClient(app)
    dev_conn = _conn(store, "dev")
    # A sink owned by 'other' (their own connection) must not appear for 'dev'.
    other_conn = store.upsert_connection({
        "name": "Other", "host": "db", "port": 8563, "username": "u", "schema": "OTH",
        "password": "p", "llmURL": "", "llmModel": "", "llmKey": "", "assignments": ["other"],
    }).id
    client.post("/api/integration/sources", json={
        "name": "Dev sink", "kind": config.SINK_SOURCE_KIND,
        "config": {"connectionId": dev_conn, "titleShort": "DEV", "port": config.SINK_HTTP_PORTS[0]},
    }, headers={"X-PMW-User": "dev"})
    client.post("/api/integration/sources", json={
        "name": "Other sink", "kind": config.SINK_SOURCE_KIND,
        "config": {"connectionId": other_conn, "titleShort": "OTH", "port": config.SINK_HTTP_PORTS[1]},
    }, headers={"X-PMW-User": "other"})

    _patch_monitor(monkeypatch, projects=[], live=False)
    data = client.get("/api/integration/sinks/monitor", headers={"X-PMW-User": "dev"}).json()
    assert [s["name"] for s in data["sinks"]] == ["Dev sink"]


def test_sinks_monitor_db_failure_is_per_sink_never_500(api_backend, monkeypatch):
    from fastapi.testclient import TestClient

    app, store, config = api_backend
    store.create_user("dev", "pw", is_admin=False)
    store.set_developer("dev", True)
    cid = _conn(store, "dev")
    client = TestClient(app)
    hdr = {"X-PMW-User": "dev"}
    client.post("/api/integration/sources", json={
        "name": "S", "kind": config.SINK_SOURCE_KIND,
        "config": {"connectionId": cid, "titleShort": "AGENTLOG", "port": config.SINK_HTTP_PORTS[0]},
    }, headers=hdr)

    _patch_monitor(monkeypatch, projects=[], ok=False, error="Connection refused", live=False)
    r = client.get("/api/integration/sinks/monitor", headers=hdr)
    assert r.status_code == 200  # a dead destination never 500s the monitor
    s = r.json()["sinks"][0]
    assert s["error"] == "Connection refused"
    assert s["events"] is None and s["journeys"] is None and s["live"] is False
