#!/usr/bin/env bash
# Starts the compute backend, the administrative interface, and the GUI server.
#
#   ./run.sh          build the SPA if needed, then run all three services
#   ./run.sh --dev     backend + admin + Vite dev server (hot reload, HTTP only)
#   ./run.sh --build   rebuild the SPA and exit
#
# Ports (override with PMW_* env vars):
#   compute backend   8000 (HTTPS, internal self-signed cert — loopback only)
#   admin interface   8090 (HTTP)  8453 (HTTPS)
#   GUI (HTTP)        8080     GUI (HTTPS)  8443   — TLS mode is set in the admin UI
#   (both the GUI and the admin follow the same TLS mode + active certificate)

set -euo pipefail
cd "$(dirname "$0")"

VENV="./.venv/bin"
WEB="frontend/web"

if [[ ! -x "$VENV/python" ]]; then
  echo "error: virtualenv missing — create it with:" >&2
  echo "  python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 1
fi

build_web() {
  if [[ ! -d "$WEB/node_modules" ]]; then
    echo "→ installing frontend dependencies"
    (cd "$WEB" && npm install)
  fi
  echo "→ building the SPA"
  (cd "$WEB" && npm run build)
}

case "${1:-}" in
  --build)
    build_web
    exit 0
    ;;
esac

pids=()
cleanup() {
  for pid in "${pids[@]:-}"; do
    [[ -n "$pid" ]] && kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

# In --dev the Vite dev server proxies straight to the backend (no GUI proxy in
# between), so the backend can't require the proxy-auth secret. Everything is
# loopback in dev anyway.
if [[ "${1:-}" == "--dev" ]]; then
  export PMW_REQUIRE_PROXY_AUTH=0
fi

# TLS on loopback (internal self-signed cert) so the GUI→backend proxy hop is
# always encrypted — see backend/app/services/internal_tls.py.
echo "→ compute backend on https://127.0.0.1:${PMW_BACKEND_PORT:-8000} (TLS, internal cert)"
"$VENV/python" backend/launch.py &
pids+=($!)

# The admin interface uses the same TLS-aware launcher as the GUI, so it follows
# the same TLS mode + active certificate (HTTP and/or HTTPS per the plan).
echo "→ admin interface (HTTP ${PMW_ADMIN_PORT:-8090} / HTTPS ${PMW_ADMIN_HTTPS_PORT:-8453}, per TLS mode)"
"$VENV/python" admin/launch.py &
pids+=($!)

if [[ "${1:-}" == "--dev" ]]; then
  if [[ ! -d "$WEB/node_modules" ]]; then
    (cd "$WEB" && npm install)
  fi
  echo "→ Vite dev server on http://localhost:5173"
  (cd "$WEB" && npm run dev) &
  pids+=($!)
else
  if [[ ! -f "$WEB/dist/index.html" ]]; then
    build_web
  fi
  # The launcher reads the TLS plan from the admin store and binds HTTP and/or HTTPS.
  echo "→ GUI server (HTTP ${PMW_FRONTEND_PORT:-8080} / HTTPS ${PMW_FRONTEND_HTTPS_PORT:-8443}, per TLS mode)"
  "$VENV/python" frontend/launch.py &
  pids+=($!)

  # The integration / data-source console — a fourth surface on the admin port + 10,
  # for power users, developers and admins. Follows the same TLS plan; disable it in
  # the admin panel's Integration tab.
  echo "→ integration console (HTTP ${PMW_INTEGRATION_PORT:-8100} / HTTPS ${PMW_INTEGRATION_HTTPS_PORT:-8463}, per TLS mode)"
  "$VENV/python" integration/launch.py &
  pids+=($!)

  # The Actions authoring surface — a fifth surface on the admin port + 20, for
  # developers and admins. Follows the same TLS plan; enable it in the admin panel's
  # Actions tab (it serves a disabled page until then).
  echo "→ actions surface (HTTP ${PMW_ACTIONS_PORT:-8110} / HTTPS ${PMW_ACTIONS_HTTPS_PORT:-8473}, per TLS mode)"
  "$VENV/python" actions/launch.py &
  pids+=($!)

  # The API Server - Event Receiver supervisor — runs one HTTP/HTTPS ingestion server per
  # configured sink, each on its own port from the pool (admin port + 30 onwards).
  # Follows the same TLS plan; enable the module in the admin panel's Event Receiver tab.
  echo "→ API Server - Event Receiver supervisor (HTTP ${PMW_SINK_PORT_BASE:-8120}.. / HTTPS ${PMW_SINK_HTTPS_PORT_BASE:-8483}.., per TLS mode)"
  "$VENV/python" sink/launch.py &
  pids+=($!)

  # The MCP server — a seventh surface on the admin port + 40, letting AI clients query
  # the process data over the Model Context Protocol (OAuth via Authentik). Follows the
  # same TLS plan; enable it in the admin panel's MCP Server tab (it 503s until then).
  echo "→ MCP server (HTTP ${PMW_MCP_PORT:-8130} / HTTPS ${PMW_MCP_HTTPS_PORT:-8493}, per TLS mode)"
  "$VENV/python" mcp/launch.py &
  pids+=($!)
fi

wait
