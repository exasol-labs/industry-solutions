"""TLS-aware launcher for the MCP server surface.

Serves the MCP server over HTTP and/or HTTPS using the *same* TLS mode and the *same*
active certificate as the main application and admin interface (via the shared
`app.tls_launcher`), and rebinds on SIGHUP. See that module for the full behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # local `server` module
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.config import (  # noqa: E402
    MCP_HOST,
    MCP_HTTPS_PORT,
    MCP_PID_PATH,
    MCP_PORT,
)
from app.tls_launcher import run  # noqa: E402
from server import app  # noqa: E402  — the MCP application

if __name__ == "__main__":
    run(
        app,
        host=MCP_HOST,
        http_port=MCP_PORT,
        https_port=MCP_HTTPS_PORT,
        pid_path=MCP_PID_PATH,
        name="mcp",
    )
