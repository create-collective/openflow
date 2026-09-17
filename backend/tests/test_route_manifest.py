"""Every route the backend serves is listed in route-manifest.json, and nothing else is.

The frontend calls about 90 endpoints through src/lib/api.js, and until a page is opened nothing
checks that they still exist. The manifest is the contract between the two halves: the frontend's
api-contract test asserts every path it uses is in the manifest, and this test asserts the
manifest matches the FastAPI app. So a route cannot be renamed or removed without a visible diff
to a committed file, on either side. Building the app does not run the lifespan, so no data dir,
no database and no device are touched.

    UPDATE_ROUTE_MANIFEST=1 python -m pytest tests/test_route_manifest.py    (rewrite the file)
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from starlette.routing import Mount, Route          # noqa: E402

from openflow_backend import app as app_mod         # noqa: E402
from openflow_backend.app import create_app         # noqa: E402

MANIFEST = Path(__file__).with_name("route-manifest.json")


def served_routes() -> list[str]:
    """'METHOD /path' for every route, 'MOUNT /path' for every mount; HEAD is implied by GET."""
    out: set[str] = set()

    def walk(routes, prefix=""):
        for r in routes:
            if isinstance(r, Mount):
                out.add(f"MOUNT {prefix}{r.path or '/'}")
            elif isinstance(r, Route):
                for method in sorted(r.methods or ()):
                    if method != "HEAD":
                        out.add(f"{method} {prefix}{r.path}")
            elif hasattr(r, "original_router"):
                # FastAPI 0.14x includes a router lazily: app.routes holds a wrapper around the
                # APIRouter (original_router) and its include options (include_context.prefix).
                ctx = getattr(r, "include_context", None)
                walk(r.original_router.routes, prefix + (getattr(ctx, "prefix", "") or ""))
            else:  # pragma: no cover - a route type this walker does not know must not pass silently
                raise AssertionError(f"unknown route type {type(r).__name__}; teach served_routes() about it")

    walk(create_app().routes)
    return sorted(out)


def test_the_served_routes_match_the_manifest(tmp_path, monkeypatch):
    # The renderer mount exists only when a built renderer is found; pin one so the manifest
    # reads the same with or without frontend/dist on disk (CI's backend job has none).
    (tmp_path / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    monkeypatch.setattr(app_mod, "renderer_dir", lambda: tmp_path)
    routes = served_routes()
    if os.environ.get("UPDATE_ROUTE_MANIFEST"):
        MANIFEST.write_text(json.dumps(routes, indent=2) + "\n", encoding="utf-8")
    assert MANIFEST.exists(), f"{MANIFEST.name} is missing; create it with UPDATE_ROUTE_MANIFEST=1"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    gone = sorted(set(manifest) - set(routes))
    new = sorted(set(routes) - set(manifest))
    assert not gone and not new, (
        "route manifest is out of date."
        + (f" No longer served: {gone}." if gone else "")
        + (f" Not in the manifest: {new}." if new else "")
        + " If this is intended, rewrite it: UPDATE_ROUTE_MANIFEST=1 python -m pytest tests/test_route_manifest.py"
        + " and commit the diff (the frontend's api-contract test reads the same file)."
    )
    print(f"  {len(routes)} routes match {MANIFEST.name}")
