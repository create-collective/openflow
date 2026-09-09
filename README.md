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

# Seed a starting profile. WITHOUT THIS THE APP OPENS EMPTY -- no profiles, no keys,
# nothing to look at. This copies the captured stock profile that ships in device/.
python -m openflow_backend.seed

python -m openflow_backend 3001                      # the port is POSITIONAL, not --port

# frontend
cd frontend
npm install
npm run dev                                          # http://localhost:5173
```

`npm run build` runs `tools/check-undefined.mjs` first — it catches undefined hooks, components
and state setters, which render as a blank page rather than a build error.

The backend test suite runs without a keyboard attached:

```bash
cd backend && python -m pytest -q          # 429 pass, 8 skip without device captures
```

Nothing here talks to the keyboard unless you explicitly flash; the app is read-only until then,
and it runs perfectly well with no keyboard attached -- which is the expected setup for design
work.

## Where your data lives

The database is **not** in the repository. It goes to `%APPDATA%/OpenFlow` on Windows,
`~/Library/Application Support/OpenFlow` on macOS, `$XDG_DATA_HOME/OpenFlow` on Linux, or
wherever `OPENFLOW_DATA_DIR` points if you set it. So you can throw it away and re-seed freely:

```bash
OPENFLOW_DATA_DIR=/tmp/openflow-scratch python -m openflow_backend.seed
OPENFLOW_DATA_DIR=/tmp/openflow-scratch python -m openflow_backend 3001
```

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
