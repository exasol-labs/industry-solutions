"""Semi-structured (JSON + XML) integration sources.

Covers the path resolvers, format detection, the format-agnostic FileExtractor over a
JSON array / JSONL / XML document, the XXE and oversize safety rails, and the
import-once-by-signature run behaviour that whole-file structured sources use in place of
byte-offset delta.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import json
from datetime import datetime

import pytest


def _md5(value: str) -> str:
    return hashlib.md5(value.encode("utf-8")).hexdigest()


# ── resolvers (no filesystem needed) ──────────────────────────────────────────


def test_json_path_resolves_dots_and_indices():
    from app.integration.structured import json_path

    obj = {"user": {"id": 7}, "items": [{"sku": "A"}, {"sku": "B"}], "weird.key": 9}
    assert json_path(obj, "user.id") == 7
    assert json_path(obj, "items[1].sku") == "B"
    assert json_path(obj, "items[-1].sku") == "B"
    assert json_path(obj, '["weird.key"]') == 9
    assert json_path(obj, "$.user.id") == 7  # leading $ optional
    # Missing / out of range / wrong type → None (never raises).
    assert json_path(obj, "user.missing") is None
    assert json_path(obj, "items[9].sku") is None
    assert json_path(obj, "user.id.deeper") is None


def test_scalar_renders_only_single_values():
    from app.integration.structured import scalar

    assert scalar(True) == "true" and scalar(False) == "false"
    assert scalar(3) == "3" and scalar("x") == "x"
    # A path that lands on a container (or nothing) is not a single value.
    assert scalar({"a": 1}) is None and scalar([1, 2]) is None and scalar(None) is None


def test_xml_value_resolves_text_and_attributes():
    from app.integration.structured import parse_xml, xml_value

    el = parse_xml('<event id="1"><user name="ann"/><step>login</step></event>')
    assert xml_value(el, "@id") == "1"
    assert xml_value(el, "step") == "login"
    assert xml_value(el, "user@name") == "ann"
    assert xml_value(el, "missing") is None
    assert xml_value(el, "user@missing") is None


def test_iter_json_from_text_handles_array_and_jsonl():
    from app.integration.structured import iter_json_from_text

    assert list(iter_json_from_text('[{"a": 1}, {"a": 2}]')) == [{"a": 1}, {"a": 2}]
    assert list(iter_json_from_text('{"a": 1}\n{"a": 2}\n')) == [{"a": 1}, {"a": 2}]
    # A malformed JSONL line is skipped, not fatal.
    assert list(iter_json_from_text('{"a": 1}\nnot json\n{"a": 3}')) == [{"a": 1}, {"a": 3}]


def test_parse_xml_refuses_an_xxe_payload(tmp_path):
    """An external-entity payload must not be expanded or fetched — defusedxml turns it
    into a parse error instead of reading the referenced file."""
    from app.integration.structured import parse_xml

    secret = tmp_path / "secret.txt"
    secret.write_text("TOP-SECRET")
    xxe = (
        '<?xml version="1.0"?>'
        f'<!DOCTYPE root [<!ENTITY xxe SYSTEM "file://{secret}">]>'
        "<root><event>&xxe;</event></root>"
    )
    with pytest.raises(ValueError):
        parse_xml(xxe)


# ── detection + extraction over a sandboxed file ──────────────────────────────


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("PMW_INTEGRATION_FILES_DIR", str(tmp_path / "files"))
    monkeypatch.delenv("PMW_INTEGRATION_ALLOW_ANY_PATH", raising=False)
    import app.config as config

    importlib.reload(config)
    import app.integration.files as files_mod

    importlib.reload(files_mod)
    import app.integration.extractors as extractors_mod

    importlib.reload(extractors_mod)
    from app.integration import AbstractionLayer, InMemoryIngestBackend

    return config, files_mod, extractors_mod, AbstractionLayer, InMemoryIngestBackend


ARRAY = [
    {"caseId": "c1", "step": "login", "ts": "2026-08-03T14:05:09", "amount": 42},
    {"caseId": "c1", "step": "pay", "ts": "2026-08-03T14:06:00", "amount": 99},
    {"caseId": "c2", "step": "browse", "ts": "not-a-date"},  # unparseable timestamp → skipped
]
JSON_FIELDS = [
    {"name": "caseId", "role": "id", "path": "caseId"},
    {"name": "step", "role": "step", "path": "step"},
    {"name": "ts", "role": "timestamp", "path": "ts"},
    {"name": "amount", "role": "meta", "path": "amount", "title": "Amount"},
]
XML_DOC = (
    "<events>"
    '<event id="c1"><step>login</step><ts>2026-08-03T14:05:09</ts></event>'
    '<event id="c2"><step>pay</step><ts>2026-08-03T14:06:00</ts></event>'
    "</events>"
)
XML_FIELDS = [
    {"name": "id", "role": "id", "path": "@id"},
    {"name": "step", "role": "step", "path": "step"},
    {"name": "ts", "role": "timestamp", "path": "ts"},
]


def test_detect_structure_json_array_suggests_paths(env):
    config, files_mod, *_ = env
    (config.INTEGRATION_FILES_DIR).mkdir(parents=True, exist_ok=True)
    (config.INTEGRATION_FILES_DIR / "events.json").write_text(json.dumps(ARRAY))

    res = files_mod.detect_structure("events.json")
    assert res["format"] == "json" and res["shape"] == "array"
    assert len(res["records"]) == 3
    # Field NAMES are safe identifiers (lowercased); the PATH keeps the real key case.
    roles = {f["name"]: f["role"] for f in res["fields"]}
    assert roles["caseid"] == "id" and roles["step"] == "step" and roles["ts"] == "timestamp"
    paths = {f["name"]: f["path"] for f in res["fields"]}
    assert paths["caseid"] == "caseId" and paths["ts"] == "ts" and paths["amount"] == "amount"


def test_detect_structure_jsonl_shape(env):
    config, files_mod, *_ = env
    (config.INTEGRATION_FILES_DIR).mkdir(parents=True, exist_ok=True)
    (config.INTEGRATION_FILES_DIR / "events.jsonl").write_text(
        "\n".join(json.dumps(r) for r in ARRAY) + "\n"
    )
    res = files_mod.detect_structure("events.jsonl")
    assert res["format"] == "json" and res["shape"] == "jsonl"


def test_detect_structure_jsonl_reads_only_a_bounded_head(env, monkeypatch):
    """A JSONL file is streamed line by line at run time, so detection must preview it
    from a bounded head — never read the whole file, which may dwarf the whole-file cap."""
    config, files_mod, *_ = env
    (config.INTEGRATION_FILES_DIR).mkdir(parents=True, exist_ok=True)
    # 400 records; each is one line. Set the whole-file cap absurdly low: a JSONL preview
    # must still work (it doesn't parse the whole document), unlike a JSON array would.
    (config.INTEGRATION_FILES_DIR / "big.jsonl").write_text(
        "\n".join(json.dumps({"caseId": f"c{i}", "step": "s", "ts": "2026-08-03T00:00:00"})
                  for i in range(400)) + "\n"
    )
    monkeypatch.setattr(files_mod, "_MAX_STRUCTURED_BYTES", 64)
    res = files_mod.detect_structure("big.jsonl", limit=5)
    assert res["format"] == "json" and res["shape"] == "jsonl"
    assert len(res["records"]) == 5 and res["truncated"] is True


def test_detect_structure_xml_picks_record_path(env):
    config, files_mod, *_ = env
    (config.INTEGRATION_FILES_DIR).mkdir(parents=True, exist_ok=True)
    (config.INTEGRATION_FILES_DIR / "events.xml").write_text(XML_DOC)

    res = files_mod.detect_structure("events.xml")
    assert res["format"] == "xml" and res["recordPath"] == "event"
    paths = {f["name"]: f["path"] for f in res["fields"]}
    assert paths["id"] == "@id" and paths["step"] == "step"


def test_detect_structure_step_beats_a_status_attribute(env):
    """A real activity element/key (a STRONG step name) must win the step role over a
    ``status`` attribute (a WEAK one) that merely appears earlier in the record — otherwise
    the field the user thinks of as the step is only a meta and can't drive compound steps."""
    config, files_mod, *_ = env
    (config.INTEGRATION_FILES_DIR).mkdir(parents=True, exist_ok=True)
    (config.INTEGRATION_FILES_DIR / "s.xml").write_text(
        '<events><event user_id="1" status="200">'
        '<step>login</step><ts>2026-08-03T00:00:00</ts></event></events>'
    )
    res = files_mod.detect_structure("s.xml")
    role = {f["name"]: f["role"] for f in res["fields"]}
    assert role["step"] == "step"       # the <step> element, not…
    assert role["status"] == "meta"     # …the status attribute that came first


def test_detect_structure_text_delegates_to_records(env):
    config, files_mod, *_ = env
    (config.INTEGRATION_FILES_DIR).mkdir(parents=True, exist_ok=True)
    (config.INTEGRATION_FILES_DIR / "a.log").write_text("line one\nline two\n")
    res = files_mod.detect_structure("a.log")
    assert res["format"] == "text" and res["records"] == ["line one", "line two"]


def _run(layer, extractor, backend, schema="S"):
    return asyncio.run(layer.run(user="dev", extractor=extractor, backend=backend, schema=schema))


def test_extractor_over_json_array(env):
    config, files_mod, extractors_mod, AbstractionLayer, InMemoryIngestBackend = env
    from app.integration.structured import iter_json_from_text

    records = list(iter_json_from_text(json.dumps(ARRAY)))
    mem = InMemoryIngestBackend()
    ext = extractors_mod.FileExtractor(
        path="events.json", encoding="utf-8", fields=JSON_FIELDS, project_id="P",
        fmt="json", records=records,
    )
    result = _run(AbstractionLayer(), ext, mem)
    rows = mem.tables["S"]["JOURNEYS"]["rows"]
    assert result.records == 2  # the "not-a-date" record is skipped
    assert rows[0]["EVENT_ID"] == _md5("c1") and rows[0]["STEP"] == "login"
    assert rows[0]["META_1"] == "42"
    assert rows[0]["EVENT_TIME"] == datetime(2026, 8, 3, 14, 5, 9)
    # The meta business name lands in METAS.
    assert mem.tables["S"]["METAS"]["rows"][0]["META_1_TITLE"] == "Amount"


def test_extractor_over_jsonl_lines(env):
    config, files_mod, extractors_mod, AbstractionLayer, InMemoryIngestBackend = env
    lines = [json.dumps(r) for r in ARRAY] + ["not json at all"]
    mem = InMemoryIngestBackend()
    ext = extractors_mod.FileExtractor(
        path="events.jsonl", encoding="utf-8", fields=JSON_FIELDS, project_id="P",
        fmt="json", lines=lines,
    )
    result = _run(AbstractionLayer(), ext, mem)
    # Two good records; the bad timestamp and the unparseable line are both skipped.
    assert result.records == 2


def test_extractor_over_xml(env):
    config, files_mod, extractors_mod, AbstractionLayer, InMemoryIngestBackend = env
    from app.integration.structured import iter_xml_records, parse_xml

    root = parse_xml(XML_DOC)
    records = iter_xml_records(root, "event")
    mem = InMemoryIngestBackend()
    ext = extractors_mod.FileExtractor(
        path="events.xml", encoding="utf-8", fields=XML_FIELDS, project_id="P",
        fmt="xml", record_path="event", records=records,
    )
    result = _run(AbstractionLayer(), ext, mem)
    rows = mem.tables["S"]["JOURNEYS"]["rows"]
    assert result.records == 2
    assert rows[0]["EVENT_ID"] == _md5("c1") and rows[0]["STEP"] == "login"
    assert rows[1]["EVENT_ID"] == _md5("c2") and rows[1]["STEP"] == "pay"


def test_read_text_file_rejects_oversize(env):
    config, files_mod, *_ = env
    from app.integration.files import FileAccessError

    (config.INTEGRATION_FILES_DIR).mkdir(parents=True, exist_ok=True)
    big = config.INTEGRATION_FILES_DIR / "big.json"
    big.write_text("[]")
    with pytest.raises(FileAccessError):
        files_mod.read_text_file("big.json", cap=1)  # 1-byte cap → the 2-byte file fails


# ── import-once-by-signature through the run endpoint (whole-file structured) ──


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PMW_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PMW_INTEGRATION_FILES_DIR", str(tmp_path / "files"))
    monkeypatch.delenv("PMW_INTEGRATION_ALLOW_ANY_PATH", raising=False)

    import app.config as config
    importlib.reload(config)
    import app.store.crypto as crypto
    importlib.reload(crypto)
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


class _Raw:
    def commit(self): pass
    def rollback(self): pass
    def close(self): pass


def _stub_open(integration_api, monkeypatch, captured):
    def fake(conn):
        def run_sql(sql: str):
            captured.append(sql)
            return []

        return _Raw(), run_sql

    monkeypatch.setattr(integration_api, "open_stored_connection", fake)


def _seed_json_source(config, store):
    store.create_user("dev", "pw", is_admin=False)
    store.set_developer("dev", True)
    conn = store.upsert_connection({
        "name": "Prod", "host": "db1", "port": 8563, "username": "svc",
        "schema": "MINING", "password": "s3cret", "owner": "dev", "assignments": ["dev"],
    })
    st = store.add_source_type("dev", name="Events", config=json.dumps({
        "sample": "", "format": "json", "fields": JSON_FIELDS,
    }))
    (config.INTEGRATION_FILES_DIR).mkdir(parents=True, exist_ok=True)
    (config.INTEGRATION_FILES_DIR / "events.json").write_text(json.dumps(ARRAY))
    source = store.add_source("dev", name="Events", kind="file", config=json.dumps({
        "path": "events.json", "encoding": "utf-8", "sourceTypeId": st.id,
    }))
    return source, conn


def test_run_json_array_is_import_once_by_signature(app_env, monkeypatch):
    from fastapi.testclient import TestClient

    config, store, integration_api, app = app_env
    source, conn = _seed_json_source(config, store)
    captured: list[str] = []
    _stub_open(integration_api, monkeypatch, captured)
    client = TestClient(app)

    def run():
        return client.post(
            f"/api/integration/sources/{source.id}/run",
            headers={"X-PMW-User": "dev"},
            json={"titleShort": "P1", "connectionId": conn.id},
        )

    first = run()
    assert first.status_code == 200, first.text
    assert first.json()["records"] == 2  # two valid events; the bad-timestamp one skipped
    assert any('"MINING"."JOURNEYS"' in sql for sql in captured)

    # Re-running the UNCHANGED file imports nothing (import-once by content signature).
    second = run()
    assert second.status_code == 200, second.text
    assert second.json()["records"] == 0 and second.json()["linesRead"] == 0
    assert "unchanged" in second.json()["detail"].lower()

    # Changing the file re-imports it whole.
    bigger = ARRAY + [{"caseId": "c3", "step": "logout", "ts": "2026-08-03T14:07:00"}]
    (config.INTEGRATION_FILES_DIR / "events.json").write_text(json.dumps(bigger))
    third = run()
    assert third.status_code == 200, third.text
    assert third.json()["records"] == 3  # whole file re-imported (now three valid events)


def test_run_rejects_malformed_xml(app_env, monkeypatch):
    from fastapi.testclient import TestClient

    config, store, integration_api, app = app_env
    store.create_user("dev", "pw", is_admin=False)
    store.set_developer("dev", True)
    conn = store.upsert_connection({
        "name": "Prod", "host": "db1", "port": 8563, "username": "svc",
        "schema": "MINING", "password": "s3cret", "owner": "dev", "assignments": ["dev"],
    })
    st = store.add_source_type("dev", name="X", config=json.dumps({
        "sample": "", "format": "xml", "recordPath": "event", "fields": XML_FIELDS,
    }))
    (config.INTEGRATION_FILES_DIR).mkdir(parents=True, exist_ok=True)
    (config.INTEGRATION_FILES_DIR / "bad.xml").write_text("<events><event></broken>")
    source = store.add_source("dev", name="X", kind="file", config=json.dumps({
        "path": "bad.xml", "encoding": "utf-8", "sourceTypeId": st.id,
    }))
    _stub_open(integration_api, monkeypatch, [])

    resp = TestClient(app).post(
        f"/api/integration/sources/{source.id}/run",
        headers={"X-PMW-User": "dev"},
        json={"titleShort": "P1", "connectionId": conn.id},
    )
    assert resp.status_code == 400
    assert "xml" in resp.json()["detail"].lower()
