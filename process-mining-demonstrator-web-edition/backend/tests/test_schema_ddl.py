"""Tests for the process-mining schema provisioner (app.db.schema_ddl).

No database is needed: DatabaseManager._open is stubbed with a fake connection
that records the SQL it is asked to run, so we can assert the full CREATE SCHEMA
→ OPEN SCHEMA → CREATE TABLE sequence and the idempotent IF NOT EXISTS clauses.
"""

from __future__ import annotations

import asyncio

from app.db import manager, schema_ddl


class _Res:
    def __init__(self, val=None, rows=None) -> None:
        self._val = val
        self._rows = rows or []

    def fetchval(self):
        return self._val

    def fetchall(self):
        return self._rows


class FakeConn:
    def __init__(self, journeys_has_dist_key: bool = True) -> None:
        self.calls: list[str] = []
        self.committed = False
        self.closed = False
        # Drives the provisioner's "is EVENT_ID already the distribution key?" probe.
        self.journeys_has_dist_key = journeys_has_dist_key

    def execute(self, sql: str) -> "_Res":
        self.calls.append(sql)
        if "COLUMN_IS_DISTRIBUTION_KEY" in sql:
            return _Res(val=1 if self.journeys_has_dist_key else 0)
        return _Res()

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


def _provision(monkeypatch, conn, **overrides):
    monkeypatch.setattr(manager.DatabaseManager, "_open", lambda self, server, pw: conn)
    kwargs = dict(host="h", port=8563, username="u", password="p", schema="PM")
    kwargs.update(overrides)
    return asyncio.run(schema_ddl.provision_process_mining_schema(**kwargs))


def test_ddl_covers_every_required_table_including_notes():
    assert schema_ddl.TABLE_NAMES == ["PROJECTS", "JOURNEYS", "STEPS", "METAS", "NOTES"]
    for name, ddl in schema_ddl.PROCESS_MINING_TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {name}" in ddl  # idempotent


def test_journeys_event_id_is_hashtype():
    # EVENT_ID holds a 32-char MD5 hash, stored as a 16-byte HASHTYPE so the DFG
    # pipeline (joins / GROUP BY / DISTRIBUTE BY / transition window) runs on
    # fixed-length binary rather than a VARCHAR. Guard against a silent revert.
    journeys_ddl = dict(schema_ddl.PROCESS_MINING_TABLES)["JOURNEYS"]
    assert "EVENT_ID   HASHTYPE(16 BYTE) NOT NULL" in journeys_ddl
    assert "DISTRIBUTE BY EVENT_ID" in journeys_ddl


def test_notes_ddl_is_shared_with_the_repository():
    # The repository's ensure_notes_table imports this exact constant, so a
    # provisioned NOTES table matches the one the app writes to.
    from app.db import repository  # noqa: F401 — importing proves the symbol resolves

    assert "CREATE TABLE IF NOT EXISTS NOTES" in schema_ddl.NOTES_DDL
    assert "FILTER_SNAPSHOT" in schema_ddl.NOTES_DDL


def test_provision_runs_the_full_sequence_and_commits(monkeypatch):
    conn = FakeConn()
    res = _provision(monkeypatch, conn, schema="PM")

    assert res["ok"] is True and res["error"] is None
    assert res["created"] == ["schema PM", "PROJECTS", "JOURNEYS", "STEPS", "METAS", "NOTES"]
    # Schema is created and opened first, with a quoted identifier.
    assert conn.calls[0] == 'CREATE SCHEMA IF NOT EXISTS "PM"'
    assert conn.calls[1] == 'OPEN SCHEMA "PM"'
    joined = "\n".join(conn.calls)
    for tbl in ("PROJECTS", "JOURNEYS", "STEPS", "METAS", "NOTES"):
        assert f"CREATE TABLE IF NOT EXISTS {tbl}" in joined
    assert conn.committed and conn.closed


def test_provision_distributes_an_existing_journeys_not_yet_keyed(monkeypatch):
    # CREATE TABLE IF NOT EXISTS won't re-key a pre-existing JOURNEYS, so provisioning
    # issues the ALTER when EVENT_ID isn't already the distribution key.
    conn = FakeConn(journeys_has_dist_key=False)
    res = _provision(monkeypatch, conn, schema="PM")
    assert res["ok"] is True
    assert schema_ddl._JOURNEYS_DISTRIBUTE_SQL in conn.calls
    assert "JOURNEYS distribution (EVENT_ID)" in res["created"]


def test_provision_skips_redistribute_when_already_keyed(monkeypatch):
    # A re-provision (or an ETL-loaded table already keyed on EVENT_ID) must NOT trigger a
    # needless, costly redistribution.
    conn = FakeConn(journeys_has_dist_key=True)
    res = _provision(monkeypatch, conn, schema="PM")
    assert res["ok"] is True
    assert schema_ddl._JOURNEYS_DISTRIBUTE_SQL not in conn.calls
    assert "JOURNEYS distribution (EVENT_ID)" not in res["created"]


def test_provision_quotes_schema_to_block_injection(monkeypatch):
    conn = FakeConn()
    _provision(monkeypatch, conn, schema='PM"; DROP SCHEMA X--')
    # The embedded quote is doubled, so the statement stays a single identifier.
    assert conn.calls[0] == 'CREATE SCHEMA IF NOT EXISTS "PM""; DROP SCHEMA X--"'


def test_provision_requires_a_schema_name(monkeypatch):
    conn = FakeConn()
    res = _provision(monkeypatch, conn, schema="   ")
    assert res["ok"] is False
    assert "schema name" in (res["error"] or "").lower()
    assert conn.calls == []  # never even connected


def test_provision_reports_friendly_error_and_partial_progress(monkeypatch):
    class BoomConn(FakeConn):
        def execute(self, sql: str) -> None:
            super().execute(sql)
            if "CREATE TABLE IF NOT EXISTS JOURNEYS" in sql:
                raise RuntimeError("insufficient privileges: CREATE TABLE denied")

    conn = BoomConn()
    res = _provision(monkeypatch, conn, schema="PM")

    assert res["ok"] is False
    assert "insufficient privileges" in res["error"]
    # Everything created before the failing statement is reported.
    assert res["created"] == ["schema PM", "PROJECTS"]
    assert conn.closed  # the connection is always closed
