"""The app's DB manager transparently reopens a connection the network/DB dropped after
idle (raising 'Exasol connection was closed' mid-session) and retries once — so a refresh
or post-idle action no longer 500s and forces a manual reconnect."""

from __future__ import annotations

import threading

import pytest

from app.db import manager as m


class _Stmt:
    result_type = "resultSet"

    def column_names(self):
        return ["X"]

    def fetchall(self):
        return [[1]]


class _GoodConn:
    def execute(self, sql):
        return _Stmt()

    def close(self):
        pass


class _RaisingConn:
    def __init__(self, exc: Exception):
        self._exc = exc

    def execute(self, sql):
        raise self._exc

    def close(self):
        pass


def _bare_manager() -> m.DatabaseManager:
    mgr = m.DatabaseManager.__new__(m.DatabaseManager)  # skip __init__ (no store)
    mgr._lock = threading.Lock()
    mgr.is_connected = True
    mgr._active_db_server = object()
    mgr._reopen_server = object()  # non-None: a reconnect target exists
    mgr._active_password = "pw"
    mgr._conn = None
    return mgr


def test_reconnects_and_retries_once_on_dead_socket(monkeypatch):
    mgr = _bare_manager()
    mgr._conn = _RaisingConn(RuntimeError("Exasol connection was closed"))
    opens = {"n": 0}

    def fake_open(server, password):
        opens["n"] += 1
        return _GoodConn()

    monkeypatch.setattr(mgr, "_open", fake_open)
    result = mgr._execute_sync("SELECT 1")
    assert result.rows == [[1]] and result.columns == ["X"]
    assert opens["n"] == 1 and isinstance(mgr._conn, _GoodConn) and mgr.is_connected


def test_genuine_sql_error_is_not_retried(monkeypatch):
    mgr = _bare_manager()
    mgr._conn = _RaisingConn(RuntimeError("syntax error near 'FROM'"))
    opens = {"n": 0}
    monkeypatch.setattr(mgr, "_open", lambda s, p: opens.__setitem__("n", opens["n"] + 1))
    with pytest.raises(RuntimeError, match="syntax error"):
        mgr._execute_sync("bad sql")
    assert opens["n"] == 0  # never reopened — a real SQL error surfaces immediately


def test_failed_reopen_marks_disconnected(monkeypatch):
    mgr = _bare_manager()
    mgr._conn = _RaisingConn(RuntimeError("Exasol connection was closed"))

    def boom(server, password):
        raise OSError("connection refused")

    monkeypatch.setattr(mgr, "_open", boom)
    with pytest.raises(OSError):
        mgr._execute_sync("SELECT 1")
    assert mgr.is_connected is False  # next request gets a clean 'not connected'


def test_no_reconnect_target_reraises(monkeypatch):
    mgr = _bare_manager()
    mgr._reopen_server = None  # nothing to reopen with → keep old behaviour
    mgr._conn = _RaisingConn(RuntimeError("Exasol connection was closed"))
    monkeypatch.setattr(mgr, "_open", lambda s, p: pytest.fail("should not reopen"))
    with pytest.raises(RuntimeError, match="closed"):
        mgr._execute_sync("SELECT 1")


def test_self_heals_when_connection_is_none(monkeypatch):
    # A prior reopen failed (or an idle drop cleared the socket): _conn is None but the
    # reopen target is still known → the next query opens a fresh connection instead of
    # forcing a manual reconnect.
    mgr = _bare_manager()
    mgr.is_connected = False
    mgr._conn = None
    opens = {"n": 0}

    def fake_open(server, password):
        opens["n"] += 1
        return _GoodConn()

    monkeypatch.setattr(mgr, "_open", fake_open)
    result = mgr._execute_sync("SELECT 1")
    assert result.rows == [[1]]
    assert opens["n"] == 1 and mgr.is_connected is True


def test_not_connected_without_target_raises(monkeypatch):
    # No socket AND no reopen target (genuinely signed out) → a clean 'Not connected'.
    mgr = _bare_manager()
    mgr._conn = None
    mgr._reopen_server = None
    monkeypatch.setattr(mgr, "_open", lambda s, p: pytest.fail("should not open"))
    with pytest.raises(Exception):
        mgr._execute_sync("SELECT 1")


def test_dead_connection_detector():
    assert m._is_dead_connection(RuntimeError("Exasol connection was closed"))
    assert m._is_dead_connection(RuntimeError("Broken pipe"))
    # A dropped socket also surfaces as a bare OSError / EOF — both reconnectable.
    assert m._is_dead_connection(OSError("[Errno 32] Broken pipe"))
    assert m._is_dead_connection(EOFError())
    # A genuine SQL error is never reconnectable, even if its text mentions a connection.
    assert not m._is_dead_connection(RuntimeError("object DUAL not found"))
    q = getattr(m.pyexasol, "ExaQueryError", None)
    if q is not None:
        # Construct without invoking pyexasol's rich __init__ (it needs a connection).
        err = q.__new__(q)
        assert not m._is_dead_connection(err)
