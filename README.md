# OpenFlow

An open-source configurator for the **Naya Create** keyboard — an independent rebuild of Naya's
own NayaFlow app, talking to the keyboard over USB CDC.

Naya has shut down, so the vendor software is unmaintained and the keyboards outlive it. This
exists so the hardware stays configurable.

## Layout

```
backend/     Python (FastAPI). Device protocol, flash planning, the action catalogue.
frontend/    React + Vite. The renderer -- this is the part to look at for styling.
electron/    Desktop shell. Spawns the backend, hosts the renderer.
docs/        Reference data the backend loads at runtime, plus notes.
device/      A few captured device reads, used as test fixtures.
```

No TypeScript; the renderer is plain JSX.

## Running it

```bash
# backend  (needs Python 3.12+)
cd backend
python -m venv .venv && .venv/Scripts/activate      # or source .venv/bin/activate
pip install -e ".[dev]"

python -m openflow_backend 3001                      # the port is POSITIONAL, not --port
# A first run seeds itself from the captured stock profile that ships in device/, so the app
# never opens empty. To start over, delete the database (see below) or re-seed by hand:
#   python -m openflow_backend.seed --force

# frontend
cd frontend
npm install
npm run dev                                          # http://localhost:5173
```

`npm run build` runs `tools/check-undefined.mjs` first — it catches undefined hooks, components
and state setters, which render as a blank page rather than a build error.

The backend test suite runs without a keyboard attached:

```bash
cd backend && python -m pytest -q          # 746 pass; runs against a temporary data dir
```

The frontend has its own gates: `npm run verify` (undefined-reference check, the style budget in
`tools/style-budget.json`, the vitest unit tests including the api-contract test against
`backend/tests/route-manifest.json`, then the build) and `npm run e2e` (a Playwright walk of every
page in both themes against a backend of its own on port 3011, seeded from the snapshot; it
leaves a screenshot per page under `tests/e2e/shots/`).

Nothing here talks to the keyboard unless you explicitly flash; the app is read-only until then,
and it runs perfectly well with no keyboard attached -- which is the expected setup for design
work.

## Building the desktop app

The app is the Electron shell in `electron/` around the backend frozen with PyInstaller
(`backend/openflow_backend.spec`) and the built renderer, which the frozen backend serves itself
at `http://127.0.0.1:<port>/` so page and API share one origin. The root `package.json` drives it:

```bash
# once: Node 22+, the backend venv with the build extra, the shell's dependencies
cd backend && pip install -e ".[dev,build]" && cd ..
npm install

npm run build:win            # frontend -> sidecar -> sidecar smoke test -> NSIS installer + portable exe
npm run build:mac            # dmg (unsigned: right-click > Open the first time)
npm run build:linux          # AppImage (the serial port needs your user in the dialout group)
```

Artefacts land in `release/` as `OpenFlow-<version>-win-x64-setup.exe`,
`OpenFlow-<version>-win-x64-portable.exe`, and so on. `npm run smoke:sidecar` starts the frozen
backend on a free port with a scratch data dir and checks every bundled resource; it runs inside
`build:app` so a broken bundle never reaches an installer. `npm run start:dev` runs the shell
against the Vite dev server and the venv backend (OPENFLOW_DEV=1).

The one version number is `__version__` in `backend/openflow_backend/__init__.py`; `npm run
version:sync` stamps it into the two `package.json` files and `version:check` (part of
`build:app` and CI) refuses to build when they drift. Builds are unsigned for now, so Windows
SmartScreen shows its "unknown publisher" prompt on first launch.

## Where your data lives

The database is **not** in the repository. It goes to `%APPDATA%/OpenFlow` on Windows,
`~/Library/Application Support/OpenFlow` on macOS, `$XDG_DATA_HOME/OpenFlow` on Linux, or
wherever `OPENFLOW_DATA_DIR` points if you set it. So you can throw it away and re-seed freely:

```bash
OPENFLOW_DATA_DIR=/tmp/openflow-scratch python -m openflow_backend 3001   # seeds itself on first run
```

Next to `user-data.db` you will find `backups/` (the automatic and manual backups),
`logs/backend.log` (the backend's own log, rotated) and, when run as the desktop app,
`logs/sidecar.log` (what the shell captured from the backend process) and `shell/` (Chromium's
cache and preferences, kept apart from your data on purpose). Uninstalling leaves all of it in
place.

## Where the styling lives

- `frontend/src/styles/` — `app.css` (shell, buttons, tokens) and `editor.css` (the keyboard
  board, palette, LED views)
- `frontend/src/components/KeymapBoard.jsx` — the virtual keyboard, drawn as SVG key shapes
- `frontend/src/pages/` — Bindings, Color, Modules, Macros, Troubleshooting

Colours come from CSS custom properties (`--neutral*`, `--accent`, `--text`, `--border-strong`),
so a theme is mostly a matter of redefining those.

## Third-party data

`docs/reference/app-shortcuts.json` is derived from ShortcutMapper (MIT) — see
`docs/reference/ATTRIBUTION.md`, which must travel with it.

`backend/openflow_backend/_vendor/nayactl` is a vendored copy of nayactl.
