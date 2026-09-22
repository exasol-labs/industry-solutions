"""Launcher for the API Server - Event Receiver supervisor.

Runs one HTTP/HTTPS ingestion server per configured sink (see app.sink_launcher),
following the same shared TLS plan as the app + admin and rebinding on SIGHUP.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.sink_launcher import run  # noqa: E402

if __name__ == "__main__":
    run()
