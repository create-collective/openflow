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
npm run build:mac            # dmg (unsigned on a developer machine: right-click > Open the first time)
npm run build:linux          # AppImage + deb (see "Installing on Linux" below)
```

Artefacts land in `release/` as `OpenFlow-<version>-win-x64-setup.exe`,
`OpenFlow-<version>-win-x64-portable.exe`, and so on. `npm run smoke:sidecar` starts the frozen
backend on a free port with a scratch data dir and checks every bundled resource; it runs inside
`build:app` so a broken bundle never reaches an installer. `npm run start:dev` runs the shell
against the Vite dev server and the venv backend (OPENFLOW_DEV=1).

The one version number is `__version__` in `backend/openflow_backend/__init__.py`; `npm run
version:sync` stamps it into the two `package.json` files and `version:check` (part of
`build:app` and CI) refuses to build when they drift.

Local builds are unsigned. The release workflow signs when it is given the means to:
`scripts/ci-signing.mjs` runs before electron-builder and, with the Apple secrets present (a
Developer ID certificate and an App Store Connect key), turns on signing and notarization for
the two Mac rows; with the Azure Artifact Signing secrets present it signs the Windows
executables, the installer and the portable build. Without them the build is unsigned, as
before, and Windows shows its "unknown publisher" prompt on first launch. A partial set of
secrets fails the job rather than shipping something that only looks signed. The script's
header lists every secret and variable by name; they live at the organisation level so Create
Companion's release reads the same ones.

The release workflow builds Linux on the oldest Ubuntu runner on purpose: the frozen backend
needs a glibc at least as new as the build machine's, so the CI build runs on Ubuntu 22.04,
Debian 12, Fedora 36 and anything newer. A build from a newer machine only runs on that
machine's generation and newer; do not hand one to a tester.

## Installing on Linux

Each half of the keyboard is a USB serial port (`/dev/ttyACM*`) that belongs to root and the
`dialout` group, so a normal user cannot open it until OpenFlow's udev rule
(`build/linux/70-openflow.rules`) is installed. The rule also keeps ModemManager from probing the
keyboard, which otherwise collides with its protocol for several seconds after every plug-in.

- **Debian, Ubuntu, Mint, Pop!_OS: use the .deb.** It installs the rule and reloads udev:
  `sudo apt install ./OpenFlow-<version>-linux-amd64.deb`, then start OpenFlow from the menu.
- **Anything else: use the AppImage** (`OpenFlow-<version>-linux-x86_64.AppImage`). `chmod +x`
  it and run it. The first time, the Hub shows
  a warning with the three commands that install the rule, and a button to copy them. Run them
  once; the keyboard appears on the next poll (unplug and replug it if not). The same commands:

```bash
printf '%s\n' 'ACTION!="remove", SUBSYSTEMS=="usb", ATTRS{idVendor}=="37d1", ENV{ID_MM_DEVICE_IGNORE}="1"' 'ACTION!="remove", SUBSYSTEM=="tty", ATTRS{idVendor}=="37d1", TAG+="uaccess"' | sudo tee /etc/udev/rules.d/70-openflow.rules >/dev/null
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=tty
```

The rule grants access to whoever is logged in at the machine's own screen (systemd-logind's
`uaccess`). Over SSH or on a system without logind, add yourself to the group instead and log
in again: `sudo usermod -aG dialout $USER` (`uucp` on Arch).

An AppImage that will not start usually means one of two things. On Ubuntu 22.04 and later
without `libfuse2`, run it with `--appimage-extract-and-run` or install `libfuse2t64`
(`libfuse2` on 22.04). On Ubuntu 24.04 and later, AppArmor blocks Electron's sandbox for an
AppImage; the .deb installs the AppArmor profile that allows it, so prefer the .deb there.

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
