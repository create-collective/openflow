"""Off-device smoke test: DB init, route inventory, and API responses via TestClient."""

import os
import tempfile

os.environ.setdefault("OPENFLOW_DATA_DIR", os.path.join(tempfile.gettempdir(), "openflow-smoke"))

from fastapi.testclient import TestClient  # noqa: E402

from openflow_backend.app import create_app  # noqa: E402
from openflow_backend.db.database import connect, init_db  # noqa: E402

init_db()
c = connect()
tables = sorted(r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'"))
print(f"DB tables ({len(tables)}):", tables)
c.close()

app = create_app()
print("Routes:", sorted(set(r.path for r in app.routes if hasattr(r, "path"))))

with TestClient(app) as client:
    for path in ["/health", "/api/info/system", "/api/ui/state", "/api/devices", "/api/status"]:
        r = client.get(path)
        print(f"GET {path} -> {r.status_code} {r.json()}")
    r = client.post("/rpc/check-for-updates")
    print(f"POST /rpc/check-for-updates -> {r.status_code} {r.json()}")
    r = client.post("/rpc/send-nayacore-zmq-message",
                    json={"messages": ["command", "update_create_fw"]})
    print(f"POST send-zmq update_create_fw -> {r.status_code} {r.json()}")

print("SMOKE OK")
