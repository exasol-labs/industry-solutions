"""Supervisor for the API Server - Event Receiver module.

Reads every configured sink (across owners) and runs ONE uvicorn server per sink on
its chosen port from the pre-exposed pool, under the shared TLS plan (the same mode +
active certificate as the app/admin). Writes one PID file for the whole supervisor and
rebinds on SIGHUP — so adding, editing, removing a sink, or a TLS change, takes effect
without touching the terminal (the integration API and the admin restart both SIGHUP
this PID). SIGTERM/SIGINT stop it.

Enable/disable is a live per-request gate inside each sink app (``store.sink_enabled``),
so toggling the module needs no rebind — the ports stay open and return 503 while off.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal

import uvicorn

from .config import SINK_HOST, SINK_HTTP_PORTS, SINK_PID_PATH, sink_https_port_for
from .sink_server import build_sink_app
from .store.security import store


def _sink_descriptors() -> list[dict]:
    """Resolve every stored sink into a bindable descriptor, skipping broken ones
    (missing/unassigned connection, invalid or duplicate port)."""
    log = logging.getLogger("sink-launcher")
    out: list[dict] = []
    used_ports: set[int] = set()
    for src in store.list_all_sinks():
        try:
            cfg = json.loads(src.config) if src.config else {}
        except json.JSONDecodeError:
            cfg = {}
        port = int(cfg.get("port") or 0)
        conn_id = (cfg.get("connectionId") or "").strip()
        title_short = (cfg.get("titleShort") or "").strip()
        token_hash = (cfg.get("tokenHash") or "").strip()
        if port not in SINK_HTTP_PORTS:
            log.warning("sink %r: port %s not in the pool — skipping", src.name, port)
            continue
        if port in used_ports:
            log.warning("sink %r: port %s already used by another sink — skipping", src.name, port)
            continue
        connection = store.get_connection(conn_id, with_secrets=True) if conn_id else None
        if connection is None:
            log.warning("sink %r: connection %r not found — skipping", src.name, conn_id)
            continue
        if not title_short:
            log.warning("sink %r: no project code — skipping", src.name)
            continue
        used_ports.add(port)
        out.append({
            "name": src.name, "port": port, "title_short": title_short,
            "token_hash": token_hash, "connection": connection,
        })
    return out


def _build_servers(log: logging.Logger) -> list[uvicorn.Server]:
    """One (or two, http+https) uvicorn Server(s) per sink, per the current TLS plan."""
    plan = store.tls_plan()
    servers: list[uvicorn.Server] = []
    descriptors = _sink_descriptors()
    for d in descriptors:
        app = build_sink_app(
            name=d["name"], title_short=d["title_short"],
            token_hash=d["token_hash"], connection=d["connection"],
        )
        http_port = d["port"]
        https_port = sink_https_port_for(http_port)
        bound = False
        if plan["http"]:
            servers.append(uvicorn.Server(uvicorn.Config(app, host=SINK_HOST, port=http_port, log_level="info")))
            log.info("sink %r HTTP on %s:%s", d["name"], SINK_HOST, http_port)
            bound = True
        if plan["https"]:
            servers.append(uvicorn.Server(uvicorn.Config(
                app, host=SINK_HOST, port=https_port,
                ssl_certfile=plan["certPath"], ssl_keyfile=plan["keyPath"], log_level="info",
            )))
            log.info("sink %r HTTPS on %s:%s", d["name"], SINK_HOST, https_port)
            bound = True
        if not bound:  # mode needs a cert but none active — never leave a sink unreachable
            servers.append(uvicorn.Server(uvicorn.Config(app, host=SINK_HOST, port=http_port)))
            log.warning("sink %r: no TLS cert active — serving plain HTTP on %s", d["name"], http_port)
    if not descriptors:
        log.info("no sinks configured — supervisor idle (SIGHUP to rebind)")
    return servers


async def _serve_cycle(log, restart_event: asyncio.Event, stop_event: asyncio.Event) -> bool:
    servers = _build_servers(log)
    for server in servers:
        server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    serve_tasks = [asyncio.create_task(s.serve()) for s in servers]
    restart_wait = asyncio.create_task(restart_event.wait())
    stop_wait = asyncio.create_task(stop_event.wait())
    # With no sinks there are no serve tasks — still wait for a restart/stop signal.
    await asyncio.wait({restart_wait, stop_wait, *serve_tasks}, return_when=asyncio.FIRST_COMPLETED)
    for server in servers:
        server.should_exit = True
    await asyncio.gather(*serve_tasks, return_exceptions=True)
    for waiter in (restart_wait, stop_wait):
        waiter.cancel()
    return stop_event.is_set()


async def _main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s"
    )
    log = logging.getLogger("sink-launcher")
    loop = asyncio.get_running_loop()
    restart_event = asyncio.Event()
    stop_event = asyncio.Event()
    loop.add_signal_handler(signal.SIGHUP, restart_event.set)
    loop.add_signal_handler(signal.SIGTERM, stop_event.set)
    loop.add_signal_handler(signal.SIGINT, stop_event.set)

    SINK_PID_PATH.write_text(str(os.getpid()), encoding="utf-8")
    log.info("sink supervisor pid %s — SIGHUP rebinds all sink listeners", os.getpid())
    try:
        while True:
            if await _serve_cycle(log, restart_event, stop_event):
                break
            restart_event.clear()
            log.info("↻ rebinding sink listeners")
    finally:
        try:
            SINK_PID_PATH.unlink(missing_ok=True)
        except OSError:
            pass
        log.info("sink supervisor stopped")


def run() -> None:
    """Serve every configured sink, rebinding on SIGHUP. Blocks until stopped."""
    asyncio.run(_main())
