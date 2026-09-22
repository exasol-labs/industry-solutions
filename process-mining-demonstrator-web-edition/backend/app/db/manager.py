"""Exasol connection management — the port of DatabaseManager.swift.

pyexasol is synchronous and a single `ExaConnection` is not safe for concurrent
statements, which mirrors the Swift `ExasolConnection` constraint. Every query is
therefore serialised through one lock and executed in a worker thread so the
event loop stays free.
"""

from __future__ import annotations

import asyncio
import logging
import re
import ssl
import threading
import time
from contextvars import ContextVar
from typing import Any

import pyexasol

from .. import log_events as logx
from ..models import ConnectionProfile, DatabaseServer, LLMServer
from ..store.settings import store

log = logging.getLogger(__name__)


def _short_sql(sql: str, limit: int = 300) -> str:
    """One-line, length-capped SQL for a log message."""
    flat = " ".join((sql or "").split())
    return flat if len(flat) <= limit else flat[:limit] + "…"

KEY_DB_SERVERS = "database_servers"
KEY_LLM_SERVERS = "llm_servers"
KEY_PROFILES = "connection_profiles"
KEY_ACTIVE_PROFILE = "active_profile_id"


def _pw_key(server_id: str) -> str:
    return f"conn_pw_{server_id}"


def _api_key_key(server_id: str) -> str:
    return f"llm_api_key_{server_id}"


class QueryResult:
    """Rows plus column names, mirroring the Swift `QueryResult`."""

    __slots__ = ("rows", "columns")

    def __init__(self, rows: list[list[Any]], columns: list[str]) -> None:
        self.rows = rows
        self.columns = columns


# A pinned fingerprint must be pure hex. pyexasol's DSN grammar also accepts the literal
# "nocertcheck", so an unvalidated value in this field could disable verification while
# the UI still reported the certificate as pinned.
_VALID_FINGERPRINT_RE = re.compile(r"^[0-9a-fA-F]{16,128}$")


class ExasolError(RuntimeError):
    pass


# Substrings that identify a dropped/dead connection (vs a genuine SQL error), so a query
# can reconnect and retry once. Kept to connection-loss wording — NOT timeouts, so a
# long-running statement is never silently re-run.
_DEAD_CONN_MARKERS = (
    "connection was closed",
    "connection is closed",
    "connection was lost",
    "not connected",
    "broken pipe",
    "connection reset",
    "reset by peer",
    "connection aborted",
    "eof occurred",
)


def _is_dead_connection(exc: BaseException) -> bool:
    """True when ``exc`` means the Exasol socket is gone (so reopening is worth a retry).

    A genuine SQL error (``ExaQueryError`` — a syntax error, a missing object, a
    constraint) is NEVER reconnectable: reopening would just re-run it. Everything else
    that can strike an *established* connection is treated as a dropped socket, because a
    connection the network/DB closed after idle surfaces in several shapes — most often
    ``ExaRuntimeError('Exasol connection was closed')``, but also communication/websocket
    errors or a bare OSError (broken pipe, reset). We would rather reopen-and-retry once
    for a false positive (harmless — the retry just re-raises) than miss a real drop and
    500 the user, which is the whole point of this path."""
    query_error = getattr(pyexasol, "ExaQueryError", None)
    if query_error is not None and isinstance(exc, query_error):
        return False
    reconnectable = tuple(
        cls
        for name in ("ExaConnectionError", "ExaCommunicationError", "ExaRuntimeError")
        if (cls := getattr(pyexasol, name, None)) is not None
    )
    if reconnectable and isinstance(exc, reconnectable):
        return True
    if isinstance(exc, (OSError, EOFError)):
        return True
    return any(marker in str(exc).lower() for marker in _DEAD_CONN_MARKERS)


class DatabaseManager:
    """Holds one live Exasol connection plus server definitions. One instance per
    signed-in user (see ConnectionRegistry) so users never share a connection."""

    def __init__(self, *, load_legacy_active: bool = True) -> None:
        self._conn: pyexasol.ExaConnection | None = None
        self._lock = threading.Lock()
        self.is_connected = False
        self.is_llm_reachable = False
        # Per-user managers start with a clean slate; only the legacy global keeps
        # the persisted single-user active profile.
        self.active_profile_id: str | None = (
            store.get(KEY_ACTIVE_PROFILE) if load_legacy_active else None
        )
        self.last_error: str | None = None
        # Set when connected via an admin-defined connection (the current model).
        self._active_db_server: DatabaseServer | None = None
        # The password for the active connection, kept so a socket dropped by the
        # network/DB after idle can be transparently reopened without a manual reconnect.
        self._active_password: str | None = None
        # The server to reopen with when the socket is found dead. Set by BOTH connect
        # paths (unlike `_active_db_server`, which stays None on the legacy path to keep
        # its admin-vs-legacy semantics), so reconnect works regardless of how the user
        # connected. Cleared only by an explicit disconnect.
        self._reopen_server: DatabaseServer | None = None
        # Whether the active connection opts into reading transitions from the
        # pre-materialised TRANSITIONS_RAW table (ProcessRepository reads this).
        self.use_materialized_transitions = False
        # Per-user cache of the (tiny, near-static) STEPS table, keyed by project id.
        # STEPS is read on every map reload / journey view; it only changes via
        # update_step (which invalidates it) and per connection (cleared on connect/
        # disconnect below). Lives here — not on ProcessRepository — because the repo
        # is recreated per request while this manager persists for the user's session.
        self._steps_cache: dict[str, Any] = {}

    def invalidate_steps(self, project_id: str | None = None) -> None:
        """Drop the cached STEPS for one project, or all of them (None)."""
        if project_id is None:
            self._steps_cache.clear()
        else:
            self._steps_cache.pop(project_id, None)

    # ── persisted definitions ────────────────────────────────────────────────

    @property
    def database_servers(self) -> list[DatabaseServer]:
        return [DatabaseServer(**d) for d in store.get(KEY_DB_SERVERS, [])]

    @database_servers.setter
    def database_servers(self, value: list[DatabaseServer]) -> None:
        store.set(KEY_DB_SERVERS, [s.model_dump(by_alias=True) for s in value])

    @property
    def llm_servers(self) -> list[LLMServer]:
        servers = []
        for d in store.get(KEY_LLM_SERVERS, []):
            s = LLMServer(**d)
            # API keys live in the encrypted vault, never in the kv table.
            s.apiKey = store.get_secret(_api_key_key(s.id))
            servers.append(s)
        return servers

    @llm_servers.setter
    def llm_servers(self, value: list[LLMServer]) -> None:
        stripped = []
        for s in value:
            store.set_secret(_api_key_key(s.id), s.apiKey or "")
            d = s.model_dump(by_alias=True)
            d["apiKey"] = ""
            stripped.append(d)
        store.set(KEY_LLM_SERVERS, stripped)

    @property
    def profiles(self) -> list[ConnectionProfile]:
        return [ConnectionProfile(**d) for d in store.get(KEY_PROFILES, [])]

    @profiles.setter
    def profiles(self, value: list[ConnectionProfile]) -> None:
        store.set(KEY_PROFILES, [p.model_dump(by_alias=True) for p in value])

    # ── resolvers ────────────────────────────────────────────────────────────

    def profile(self, profile_id: str | None) -> ConnectionProfile | None:
        if not profile_id:
            return None
        return next((p for p in self.profiles if p.id == profile_id), None)

    @property
    def active_profile(self) -> ConnectionProfile | None:
        return self.profile(self.active_profile_id)

    def database_server(self, profile: ConnectionProfile | None) -> DatabaseServer | None:
        if profile is None or not profile.databaseServerId:
            return None
        return next(
            (s for s in self.database_servers if s.id == profile.databaseServerId), None
        )

    def llm_server(self, profile: ConnectionProfile | None) -> LLMServer | None:
        if profile is None or not profile.llmServerId:
            return None
        return next((s for s in self.llm_servers if s.id == profile.llmServerId), None)

    @property
    def active_database_server(self) -> DatabaseServer | None:
        if self._active_db_server is not None:
            return self._active_db_server
        return self.database_server(self.active_profile)

    @property
    def active_llm_server(self) -> LLMServer | None:
        """The active connection's OWN LLM, read live (never a connect-time snapshot),
        so an admin edit lands on the next use without a reconnect. Admin-connection path
        reads the security store; the legacy path reads the profile's LLM server."""
        if self._active_db_server is not None:  # admin-connection path
            from ..services.llm_config import connection_llm_server

            return connection_llm_server(self.active_profile_id)
        return self.llm_server(self.active_profile)

    @property
    def username(self) -> str:
        server = self.active_database_server
        return server.username if server else ""

    # ── passwords ────────────────────────────────────────────────────────────

    def password(self, server_id: str) -> str:
        return store.get_secret(_pw_key(server_id))

    def set_password(self, server_id: str, password: str) -> None:
        store.set_secret(_pw_key(server_id), password)

    def delete_password(self, server_id: str) -> None:
        store.delete_secret(_pw_key(server_id))

    # ── connecting ───────────────────────────────────────────────────────────

    def _connect_kwargs(
        self, server: DatabaseServer, password: str, *, socket_timeout: int | None = None
    ) -> dict[str, Any]:
        dsn = f"{server.host}:{server.port}"
        # pyexasol arms the WebSocket read timeout ONCE at connect and never resets it
        # per statement, so this also caps how long a single statement may run. The
        # interactive default (300 s) suits map queries; long one-shot builds (in-DB
        # sampling, materialisation) pass a larger value so they aren't cut off mid-run.
        kwargs: dict[str, Any] = {
            "user": server.username,
            "password": password,
            "compression": True,
            "fetch_dict": False,
            "connection_timeout": 15,
            "socket_timeout": socket_timeout if socket_timeout is not None else 300,
        }
        if server.schema_:
            kwargs["schema"] = server.schema_

        if server.useTLS:
            kwargs["encryption"] = True
            # Whitespace-tolerant; anything unrecognised is treated as "verify" rather
            # than falling through to no verification. Previously ANY value that wasn't
            # exactly "verify" (a typo, a trailing space, a legacy/restored value)
            # silently disabled certificate checking — a fail-OPEN default.
            mode = (server.certModeRaw or "verify").strip().lower()
            fingerprint = (server.fingerprint or "").replace(":", "").strip()
            if mode == "fingerprint":
                # pyexasol pins the certificate when the DSN carries a fingerprint.
                # A blank/invalid fingerprint used to fall through to CERT_NONE while
                # the UI still said "pinned", so refuse instead of silently downgrading.
                if not _VALID_FINGERPRINT_RE.match(fingerprint):
                    raise ExasolError(
                        "This connection is set to pin a certificate fingerprint, but "
                        "the fingerprint is missing or not hexadecimal. Enter the "
                        "server's SHA-256 fingerprint, or change the certificate mode."
                    )
                dsn = f"{server.host}/{fingerprint}:{server.port}"
            elif mode == "insecure":
                kwargs["websocket_sslopt"] = {
                    "cert_reqs": ssl.CERT_NONE,
                    "check_hostname": False,
                }
        else:
            kwargs["encryption"] = False

        kwargs["dsn"] = dsn
        return kwargs

    def _open(
        self, server: DatabaseServer, password: str, *, socket_timeout: int | None = None
    ) -> pyexasol.ExaConnection:
        return pyexasol.connect(
            **self._connect_kwargs(server, password, socket_timeout=socket_timeout)
        )

    async def connect(self, profile: ConnectionProfile) -> str | None:
        """Connect and remember the profile. Returns an error message or None."""
        self.active_profile_id = profile.id
        store.set(KEY_ACTIVE_PROFILE, profile.id)
        self.last_error = None

        server = self.database_server(profile)
        if server is None:
            msg = (
                "This connection has no database server selected. "
                "Edit it and choose one."
            )
            self.last_error = msg
            self.is_connected = False
            return msg

        await self.disconnect()
        password = self.password(server.id)
        try:
            conn = await asyncio.to_thread(self._open, server, password)
        except Exception as exc:  # noqa: BLE001 — surfaced to the user verbatim
            msg = friendly_error(exc)
            self.last_error = msg
            self.is_connected = False
            return msg

        self._conn = conn
        self.is_connected = True
        self._active_db_server = None
        # Remember how to reopen this socket if it is later dropped (see _execute_sync).
        self._reopen_server = server
        self._active_password = password
        # Reachability reflects the EFFECTIVE LLM (own → global default), resolved live.
        from ..services.llm_config import resolve_llm

        self.is_llm_reachable = await check_llm_reachable(resolve_llm(self).as_server())
        return None

    async def connect_connection(self, conn_def) -> str | None:
        """Connect using an admin-defined `Connection` (from the security store).

        `conn_def` must carry its decrypted secrets. Returns an error or None.
        """
        server = DatabaseServer(
            id=conn_def.id,
            name=conn_def.name,
            host=conn_def.host,
            port=conn_def.port,
            username=conn_def.username,
            useTLS=conn_def.use_tls,
            certModeRaw=conn_def.cert_mode,
            fingerprint=conn_def.fingerprint,
            minRSAKeySizeBits=conn_def.min_rsa_bits,
            **{"schema": conn_def.schema},
        )

        await self.disconnect()
        self.active_profile_id = conn_def.id
        self.last_error = None
        try:
            exa = await asyncio.to_thread(self._open, server, conn_def.password)
        except Exception as exc:  # noqa: BLE001
            # A plain assigned user reaches this path, so return generic guidance;
            # the full driver detail goes to the server log only.
            client_msg = friendly_error(exc, detail=False)
            self.last_error = client_msg
            self.is_connected = False
            logx.error(
                f"Database connection failed for {conn_def.name!r} "
                f"({server.host}:{server.port}): {friendly_error(exc)}",
                operation="db-connect",
            )
            return client_msg

        self._conn = exa
        self.is_connected = True
        self._active_db_server = server
        self._active_password = conn_def.password
        self._reopen_server = server
        self.use_materialized_transitions = bool(
            getattr(conn_def, "use_materialized_transitions", False)
        )
        # Reachability reflects the EFFECTIVE LLM (this connection's own override, else the
        # global default), resolved live from the store — not a snapshot of conn_def.
        from ..services.llm_config import resolve_llm

        self.is_llm_reachable = await check_llm_reachable(resolve_llm(self).as_server())
        return None

    async def test_server(self, server: DatabaseServer, password: str) -> str | None:
        """Probe credentials without touching the active connection."""

        def _probe() -> None:
            conn = self._open(server, password)
            conn.close()

        try:
            await asyncio.to_thread(_probe)
        except Exception as exc:  # noqa: BLE001
            msg = friendly_error(exc)
            logx.warn(
                f"Database connection test failed for {server.host}:{server.port} "
                f"(user {server.username or '-'}): {msg}",
                operation="db-test",
            )
            return msg
        return None

    async def disconnect(self) -> None:
        # Swap out and close the connection under the same lock query execution
        # uses, in a worker thread: this waits for any in-flight statement to finish
        # instead of closing the socket mid-query, and doesn't block the event loop.
        def _close() -> None:
            with self._lock:
                conn, self._conn = self._conn, None
                self.is_connected = False
                self.is_llm_reachable = False
                self._active_db_server = None
                self._active_password = None
                self._reopen_server = None
                self.use_materialized_transitions = False
                # A different connection may have different STEPS for the same
                # project id — never carry the cache across connections.
                self._steps_cache.clear()
            if conn is not None:
                conn.close()

        try:
            await asyncio.to_thread(_close)
        except Exception:  # noqa: BLE001 — already going away
            log.debug("error while closing Exasol connection", exc_info=True)

    # ── query execution ──────────────────────────────────────────────────────

    @staticmethod
    def _stmt_result(conn: "pyexasol.ExaConnection", sql: str) -> QueryResult:
        stmt = conn.execute(sql)
        columns = list(stmt.column_names())
        rows = [list(r) for r in stmt.fetchall()] if stmt.result_type == "resultSet" else []
        return QueryResult(rows, columns)

    @property
    def can_reconnect(self) -> bool:
        """We hold everything needed to (re)open the socket on demand — so a dropped
        connection can self-heal on the next query rather than needing a manual reconnect."""
        return self._reopen_server is not None and self._active_password is not None

    def _reopen_locked(self) -> "pyexasol.ExaConnection":
        """Rebuild the connection in place. Caller holds ``self._lock``. Used both to
        replace a socket the network/DB closed while idle and to (re)open after a prior
        reopen failed, so a transient drop never requires a manual reconnect. On failure
        it marks the manager disconnected but KEEPS the reopen target, so the next request
        tries again."""
        old, self._conn = self._conn, None
        if old is not None:
            try:
                old.close()
            except Exception:  # noqa: BLE001 — already going away
                pass
        try:
            conn = self._open(self._reopen_server, self._active_password or "")
        except Exception:  # noqa: BLE001 — reopen failed; next request will retry
            self.is_connected = False
            raise
        self._conn = conn
        self.is_connected = True
        return conn

    def _execute_sync(self, sql: str) -> QueryResult:
        with self._lock:
            conn = self._conn
            if conn is None:
                # Not connected, or a previous reopen failed. If we know how to open the
                # socket, do it now so a transient drop self-heals on the next request
                # instead of leaving the user stuck until a manual reconnect.
                if not self.can_reconnect:
                    raise ExasolError("Not connected.")
                log.info("Exasol connection not open — opening before the query")
                conn = self._reopen_locked()
            try:
                return self._stmt_result(conn, sql)
            except Exception as exc:  # noqa: BLE001
                # A connection dropped by the network/DB after idle raises here while
                # is_connected is still True. If it's a dead connection (not a genuine SQL
                # error) and we know how to rebuild it, reopen and retry ONCE — so the user
                # never sees a 500 or has to reconnect by hand.
                if not self.can_reconnect or not _is_dead_connection(exc):
                    raise
                log.info("Exasol connection was dropped — reconnecting and retrying once")
                new = self._reopen_locked()  # marks disconnected + re-raises if it fails
                return self._stmt_result(new, sql)

    async def _run(
        self, sql: str, timeout: float | None, log_errors: bool
    ) -> QueryResult:
        started = time.perf_counter()
        coro = asyncio.to_thread(self._execute_sync, sql)
        try:
            if timeout is None:
                result = await coro
            else:
                result = await asyncio.wait_for(coro, timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            if log_errors:
                logx.error(
                    f"SQL execution timed out after {timeout}s: {_short_sql(sql)}",
                    operation="db-timeout", tag=logx.TAG_SQL,
                )
            raise
        except Exception as exc:  # noqa: BLE001
            if log_errors:
                logx.error(
                    f"SQL execution error: {friendly_error(exc)} — SQL: {_short_sql(sql)}",
                    operation="db-sql", tag=logx.TAG_SQL,
                )
            raise
        # Every executed statement, verbatim (filters are inlined in the WHERE
        # clause) with its execution time, at DEBUG under its own 'sql' operation
        # — only persisted when the admin raises the log level to DEBUG.
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logx.debug(f"SQL ({elapsed_ms:.1f} ms): {sql}", operation="sql", tag=logx.TAG_SQL)
        return result

    async def execute(self, sql: str, timeout: float | None = None) -> QueryResult:
        return await self._run(sql, timeout, log_errors=True)

    async def execute_quiet(self, sql: str) -> QueryResult | None:
        """Run a statement whose failure is acceptable (DDL migrations)."""
        try:
            return await self._run(sql, None, log_errors=False)
        except Exception:  # noqa: BLE001
            log.debug("ignored failing statement: %s", sql, exc_info=True)
            return None


def friendly_error(exc: Exception, *, detail: bool = True) -> str:
    """Port of DatabaseManager.friendlyError — turns driver noise into guidance.

    `detail=True` (the default) appends the raw driver text — appropriate for the
    power/admin connection-test flow, where the operator configuring the server
    needs it. `detail=False` returns only the categorised guidance for surfaces a
    plain assigned user can reach, so Exasol codes, internal hostnames and
    SQL-state fragments don't leak; the full text is still logged server-side.
    """
    text = str(exc) or exc.__class__.__name__
    lowered = text.lower()

    if isinstance(exc, pyexasol.ExaAuthError) or "authentication failed" in lowered:
        base = "Authentication failed — check your username and password."
        return f"{base} ({text})" if detail else base
    if isinstance(exc, pyexasol.ExaQueryError):
        if not detail:
            return "The database rejected the request."
        code = getattr(exc, "code", "") or ""
        message = getattr(exc, "message", "") or text
        return f"[{code}] {message}" if code else message
    if "timed out" in lowered or "timeout" in lowered:
        return "Connection timed out. Verify the host address, port, and network connectivity."
    if "refused" in lowered:
        return "Connection refused. No server is accepting connections at this host and port."
    if any(k in lowered for k in ("certificate", "trust", "ssl", "tls")):
        base = (
            "TLS certificate error. Try 'Skip verification' or configure a "
            "fingerprint in the server's security settings."
        )
        return f"{base} ({text})" if detail else base
    if any(
        k in lowered
        for k in ("no such host", "host not found", "nodename", "name or service")
    ):
        return "Host not found. Check the hostname spelling and your DNS / network connectivity."
    return f"Connection failed: {text}" if detail else "Connection failed. Check the host, port, and credentials."


async def test_db_connection(
    *,
    host: str,
    port: int,
    username: str,
    password: str,
    schema: str = "",
    use_tls: bool = False,
    cert_mode: str = "verify",
    fingerprint: str = "",
    min_rsa_bits: int = 2048,
) -> str | None:
    """Open and immediately close a throwaway Exasol connection. Returns a
    user-friendly error string, or None on success. Usable from any process."""
    server = DatabaseServer(
        id="test",
        host=host,
        port=port,
        username=username,
        useTLS=use_tls,
        certModeRaw=cert_mode,
        fingerprint=fingerprint,
        minRSAKeySizeBits=min_rsa_bits,
        **{"schema": schema},
    )
    mgr = DatabaseManager.__new__(DatabaseManager)  # no store side effects

    def _probe() -> None:
        conn = mgr._open(server, password)
        conn.close()

    try:
        await asyncio.to_thread(_probe)
    except Exception as exc:  # noqa: BLE001
        msg = friendly_error(exc)
        logx.warn(
            f"Database connection test failed for {host}:{port} "
            f"(user {username or '-'}): {msg}",
            operation="db-test",
        )
        return msg
    return None


async def check_llm_reachable(server: LLMServer | None) -> bool:
    """GET {base}/models — same reachability probe the Swift app used."""
    if server is None or not server.serverURL.strip():
        return False

    from ..services.net_guard import UrlNotAllowed, safe_async_client

    try:  # SSRF guard: validates the URL AND pins the connection to the vetted IP
        client = safe_async_client(server.serverURL, timeout=5.0)
    except UrlNotAllowed as exc:
        logx.warn(
            f"LLM server URL refused (SSRF guard): {server.serverURL} — {exc}",
            operation="llm-test",
        )
        return False

    url = server.serverURL.rstrip("/") + "/models"
    headers = {}
    if server.apiKey.strip():
        headers["Authorization"] = f"Bearer {server.apiKey.strip()}"
    try:
        async with client:
            response = await client.get(url, headers=headers)
        if response.status_code >= 500:
            logx.warn(
                f"LLM server not reachable: {server.serverURL} → HTTP {response.status_code}",
                operation="llm-test",
            )
            return False
        return True
    except Exception as exc:  # noqa: BLE001 — capture the real cause before swallowing
        logx.warn(
            f"LLM connection error: {server.serverURL} — {exc.__class__.__name__}: {exc}",
            operation="llm-test",
        )
        return False


# The legacy single-user profile store still backs the (unused) /servers & /profiles
# endpoints; the live per-user data path uses the registry below instead.
db = DatabaseManager()


# ── Per-user connections ──────────────────────────────────────────────────────
#
# Each signed-in user gets their own DatabaseManager (their own Exasol connection),
# reusing the same admin-defined connection *definitions* but keeping the live
# session independent — so one user's data can never leak to another. The active
# user is carried on a ContextVar set per request (see main.py middleware); it
# propagates into the request's worker threads via asyncio.to_thread.

_current_user_var: ContextVar[str | None] = ContextVar("pmw_current_user", default=None)


def set_current_user(username: str | None):
    return _current_user_var.set(username)


def reset_current_user(token) -> None:
    _current_user_var.reset(token)


def current_user() -> str | None:
    return _current_user_var.get()


class ConnectionRegistry:
    """Per-user DatabaseManager instances, created on demand."""

    def __init__(self) -> None:
        self._by_user: dict[str, DatabaseManager] = {}
        self._lock = threading.RLock()
        # Per-connection revocation counter, bumped whenever a definition is
        # edited/deleted, so a connect racing with that revocation can detect it.
        self._revocations: dict[str, int] = {}

    # ASCII-only lowercase — MUST match the security store's identity model, which
    # compares usernames with SQLite LOWER() (ASCII-only). A Unicode `.casefold()`/
    # `.lower()` would map two store-DISTINCT names onto one key (e.g. "ß"→"ss",
    # Kelvin-sign U+212A→"k"), collapsing two users onto ONE Exasol session =
    # cross-user data leak. ASCII-lower collapses only true case-variants of the
    # same account (the store treats them as one) and never merges distinct ones.
    _ASCII_LOWER = str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"
    )

    @classmethod
    def _key(cls, username: str | None) -> str:
        # A username arriving in varying case (LDAP "Alice" vs local "alice") maps to
        # ONE manager/Exasol session, consistent with the store's case-insensitive
        # identity. Anonymous (sign-in disabled) shares one bucket.
        return (username or "").translate(cls._ASCII_LOWER)

    def for_user(self, username: str | None) -> DatabaseManager:
        key = self._key(username)
        with self._lock:
            mgr = self._by_user.get(key)
            if mgr is None:
                mgr = DatabaseManager(load_legacy_active=False)
                self._by_user[key] = mgr
            return mgr

    async def connect(self, username: str | None, conn_def) -> str | None:
        """Connect a user to `conn_def`, closing the race with a concurrent
        `disconnect_connection`. `connect_connection` opens the Exasol session
        outside any lock (it's slow), so an admin edit/delete that fires during the
        open could snapshot the manager before its `active_profile_id`/live socket
        exist and thus fail to sever it. We capture the connection's revocation
        counter before opening and re-check it after: if it advanced, the definition
        changed mid-connect, so we drop the freshly-opened session."""
        mgr = self.for_user(username)
        with self._lock:
            gen = self._revocations.get(conn_def.id, 0)
        error = await mgr.connect_connection(conn_def)
        if error is None:
            with self._lock:
                revoked = self._revocations.get(conn_def.id, 0) != gen
            if revoked:
                await mgr.disconnect()
                return "This connection changed during sign-in. Please reconnect."
        return error

    async def disconnect_user(self, username: str | None) -> None:
        """Release a user's connection (e.g. on sign-out)."""
        with self._lock:
            mgr = self._by_user.pop(self._key(username), None)
        if mgr is not None:
            await mgr.disconnect()

    async def disconnect_connection(self, conn_id: str) -> None:
        """Drop every user whose live connection is `conn_id` — its definition was
        edited or deleted, so their session must not continue. Bumping the revocation
        counter also aborts any connect to `conn_id` that is opening right now."""
        with self._lock:
            self._revocations[conn_id] = self._revocations.get(conn_id, 0) + 1
            targets = [
                m for m in self._by_user.values() if m.active_profile_id == conn_id
            ]
        for mgr in targets:
            await mgr.disconnect()

    async def disconnect_all(self) -> None:
        with self._lock:
            managers = list(self._by_user.values())
            self._by_user.clear()
        for mgr in managers:
            await mgr.disconnect()


registry = ConnectionRegistry()


def current_db() -> DatabaseManager:
    """The DatabaseManager for the current request's user."""
    return registry.for_user(_current_user_var.get())
