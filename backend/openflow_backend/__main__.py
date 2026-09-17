"""Entry point.

Electron spawns this the way NayaFlow spawned flow-bg-server.exe: passing the
port on argv. Standalone, it defaults to 3001 (the renderer's own fallback).

    python -m openflow_backend [port]
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

import uvicorn

from .config import DEFAULT_PORT, logs_dir


def _configure_logging() -> None:
    """Everything (ours and uvicorn's) to stderr and to <data dir>/logs/backend.log, rotated.
    The desktop shell captures stderr into its own sidecar.log; the file here survives even when
    that pipe is gone, and is what the user sends with a bug report."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(fmt)
    root.addHandler(stream)
    try:
        file_handler = RotatingFileHandler(logs_dir() / "backend.log", maxBytes=2_000_000,
                                           backupCount=3, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as e:  # an unwritable data dir must not stop the server from starting
        root.warning("backend.log unavailable: %s", e)


def main() -> None:
    port = DEFAULT_PORT
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    _configure_logging()
    from .app import app   # after logging, so the import-time messages land in the file too

    # The app OBJECT, not an import string: one code path for `python -m openflow_backend` and
    # the frozen sidecar (PyInstaller cannot resolve an import string it never saw). The explicit
    # loop/http/ws choices are what uvicorn picks here anyway; naming them keeps uvloop,
    # httptools, websockets and watchfiles out of the frozen bundle entirely.
    config = uvicorn.Config(app, host="127.0.0.1", port=port, loop="asyncio", http="h11",
                            ws="none", lifespan="on", log_config=None, access_log=False)
    server = uvicorn.Server(config)
    app.state.server = server     # /rpc/shutdown sets server.should_exit
    logging.getLogger("openflow").info("OpenFlow backend on http://127.0.0.1:%d", port)
    server.run()


if __name__ == "__main__":
    main()
