"""The FastAPI app for one API Server - Event Receiver instance.

Each configured sink gets its own app (and its own HTTP/HTTPS listener — see
``app.sink_launcher``). It exposes:

  POST /ingest   — bearer-token-authenticated; a JSON object or array of journey
                   entries written to the sink's connection/project (unknown steps
                   are created). 401 without a valid token; 503 when the module is
                   disabled in the admin interface; 413 when the body or entry count
                   exceeds the configured limits.
  GET  /health   — unauthenticated liveness (module-enabled flag only; deliberately
                   no identifying detail, since anyone who can reach the port sees it).

The connection is opened lazily and cached for the life of the process; a failed
write drops it so the next post reopens. Writes are serialised (one connection).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .config import SINK_IDLE_RECONNECT_SECS, SINK_MAX_BODY_BYTES, SINK_MAX_ENTRIES
from .integration.backends import SqlIngestBackend
from .integration.contract import IngestError
from .integration.destinations import open_stored_connection
from .integration.sink_ingest import ensure_schema, ingest_entries, verify_sink_token
from .store.security import store

log = logging.getLogger("sink")


def build_sink_app(*, name: str, title_short: str, token_hash: str, connection) -> FastAPI:
    """Build the ingestion app for one sink. ``connection`` is a Connection WITH secrets."""
    app = FastAPI(title=f"API Server - Event Receiver — {name}", docs_url=None, redoc_url=None)
    schema = (connection.schema or "").strip()
    # One cached connection, reused across posts. `last` tracks when it was last used so a
    # long-idle (possibly network/server-dropped) connection is refreshed before reuse.
    state: dict = {"raw": None, "run_sql": None, "ensured": False, "last": 0.0}
    lock = asyncio.Lock()

    def _open() -> None:
        raw, run_sql = open_stored_connection(connection)
        state["raw"], state["run_sql"], state["ensured"], state["last"] = (
            raw, run_sql, False, time.monotonic(),
        )

    def _drop() -> None:
        raw, state["raw"], state["run_sql"], state["ensured"] = (
            state["raw"], None, None, False,
        )
        for step in ("rollback", "close"):
            try:
                getattr(raw, step)()
            except Exception:  # noqa: BLE001 — already going away
                pass

    def _write(entries: list[dict]) -> dict:
        # Runs off the event loop. Pool-style validity handling: refresh a connection that
        # has been idle too long (it may have been dropped by the host.docker.internal NAT
        # or the server), and on any DB error reconnect and retry ONCE — so a stale socket
        # is transparently replaced instead of surfacing a timeout. Bad-data errors
        # (IngestError) are never retried; they surface as 400.
        if state["run_sql"] is not None and (time.monotonic() - state["last"]) > SINK_IDLE_RECONNECT_SECS:
            _drop()
        last_exc: Exception | None = None
        for attempt in (1, 2):
            if state["run_sql"] is None:
                _open()
            try:
                if not state["ensured"]:
                    ensure_schema(state["run_sql"], schema)  # canonical DDL (DISTRIBUTE/PARTITION)
                    state["ensured"] = True
                backend = SqlIngestBackend(run_sql=state["run_sql"])
                result = ingest_entries(
                    backend, state["raw"].commit,
                    schema=schema, title_short=title_short, entries=entries,
                )
                state["last"] = time.monotonic()
                return result
            except IngestError:
                raise  # bad payload — the connection is fine, don't retry
            except Exception as exc:  # noqa: BLE001 — assume a dead/stale connection
                last_exc = exc
                if attempt == 1:
                    log.info("sink %r: write failed (%s) — reconnecting and retrying", name, exc)
                _drop()
        assert last_exc is not None
        raise last_exc

    @app.get("/health")
    def health() -> dict:
        # Unauthenticated — return only whether the module is on, never the sink's name
        # or any other identifying/config detail (anyone who reaches the port sees this).
        return {"ok": True, "enabled": store.sink_enabled}

    @app.post("/ingest")
    async def ingest(request: Request):
        if not store.sink_enabled:
            return JSONResponse(
                {"detail": "The API Server - Event Receiver module is disabled."}, status_code=503
            )
        auth = request.headers.get("authorization", "")
        token = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
        if not verify_sink_token(token, token_hash):
            return JSONResponse(
                {"detail": "Invalid or missing bearer token."}, status_code=401
            )
        # Refuse an oversized body BEFORE reading/parsing it, so a huge or entry-flooded
        # post can't exhaust memory or the destination DB. Trust the declared
        # Content-Length when present; otherwise cap the bytes actually read.
        declared = request.headers.get("content-length")
        if declared is not None:
            try:
                if int(declared) > SINK_MAX_BODY_BYTES:
                    return JSONResponse({"detail": "Request body is too large."}, status_code=413)
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length header."}, status_code=400)
        body = await request.body()
        if len(body) > SINK_MAX_BODY_BYTES:  # covers chunked/absent Content-Length
            return JSONResponse({"detail": "Request body is too large."}, status_code=413)
        try:
            payload = json.loads(body)
        except Exception:  # noqa: BLE001
            return JSONResponse({"detail": "Request body must be JSON."}, status_code=400)
        entries = payload if isinstance(payload, list) else [payload]
        if len(entries) > SINK_MAX_ENTRIES:
            return JSONResponse(
                {"detail": f"Too many entries (max {SINK_MAX_ENTRIES} per request)."},
                status_code=413,
            )
        if not schema:
            return JSONResponse(
                {"detail": "The sink's connection has no schema."}, status_code=500
            )
        async with lock:
            try:
                result = await asyncio.to_thread(_write, entries)
            except IngestError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=400)
            except Exception as exc:  # noqa: BLE001
                # Log the real cause server-side; never return it — the DB exception text
                # carries the internal DSN, DB user and schema (an information leak to any
                # token-holding caller).
                log.warning("sink %r ingest failed: %s", name, exc)
                return JSONResponse(
                    {"detail": "Ingest failed; the destination database is temporarily unavailable."},
                    status_code=502,
                )
        return result

    return app
