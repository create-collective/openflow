"""The backend serves the built renderer at /, behind every API route.

In the desktop app the page and the API share one origin (http://127.0.0.1:<port>), which is
what makes CORS, file:// module blocking and absolute asset paths non-issues. index.html is
served with Cache-Control: no-cache so an upgrade never leaves the browser holding a stale page
that points at hashed assets which no longer exist; the hashed assets themselves are cacheable.
With no built renderer (a backend-only checkout) nothing is mounted and / is a plain 404.
No lifespan is entered, so no data dir, database or device is touched.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from fastapi.testclient import TestClient          # noqa: E402

from openflow_backend import app as app_mod        # noqa: E402


def _renderer(tmp_path: Path) -> Path:
    (tmp_path / "index.html").write_text('<!doctype html><div id="root"></div><script type="module" src="/assets/app-abc.js"></script>', encoding="utf-8")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-abc.js").write_text("console.log(1)", encoding="utf-8")
    return tmp_path


def test_the_renderer_is_served_at_root_and_the_api_still_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(app_mod, "renderer_dir", lambda: _renderer(tmp_path))
    client = TestClient(app_mod.create_app())
    r = client.get("/")
    assert r.status_code == 200 and 'id="root"' in r.text
    assert r.headers["cache-control"] == "no-cache", "index.html must never be cached across upgrades"
    r = client.get("/assets/app-abc.js")
    assert r.status_code == 200 and r.headers.get("cache-control") != "no-cache"
    assert client.get("/api/info/system").json()["app"] == "OpenFlow"
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/api/does-not-exist").status_code == 404
    print("  / serves index.html (no-cache), /assets are cacheable, /api and /health unaffected")


def test_without_a_built_renderer_nothing_is_mounted(monkeypatch):
    monkeypatch.setattr(app_mod, "renderer_dir", lambda: None)
    client = TestClient(app_mod.create_app())
    assert client.get("/").status_code == 404
    assert client.get("/health").status_code == 200
    print("  no renderer dir: / is 404, the API is up")
