"""PyInstaller entry point for the desktop sidecar: openflow-backend[.exe] <port>.

openflow_backend/__main__.py uses relative imports, which do not work as a top-level script, so
this is what the frozen executable runs. Everything else (the port on argv, logging to the data
dir, uvicorn on the app object) is __main__.main(), the same code path as
`python -m openflow_backend`. See openflow_backend.spec for what goes into the bundle.
"""
import multiprocessing

from openflow_backend.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()   # required on Windows for any spawned process; harmless elsewhere
    main()
