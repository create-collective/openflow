"""Entry point.

Electron spawns this the way NayaFlow spawned flow-bg-server.exe: passing the
port on argv. Standalone, it defaults to 3001 (the renderer's own fallback).

    python -m openflow_backend [port]
"""

from __future__ import annotations

import sys

import uvicorn

from .config import DEFAULT_PORT


def main() -> None:
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    uvicorn.run("openflow_backend.app:app", host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
