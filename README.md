# OpenFlow

An open-source companion app for the Naya Create keyboard — a clean-room rebuild
of NayaFlow with **no cloud, no GitHub fetch, no external runtime dependencies**.
It drives the keyboard over USB CDC using the [nayactl](https://github.com/Qonfused/nayactl)
protocol layer (Apache-2.0) instead of the proprietary `NayaCore.exe` +
`flow-bg-server.exe`.

> Working name — final name/branding is a pending clean-reskin decision.
> Part of the [NayaOS](../README.md) preservation effort. See the design plan
> for context: Naya B.V. is bankrupt, so an app that depends on Naya's infra is a
> liability; OpenFlow removes that dependency.

## Architecture

```
React renderer (Vite)          frontend/   — faithful UI rebuilt from recovered CSS/assets
      |  localhost REST + SSE   (recovered flow-bg-server contract; see docs/api-contract.md)
Python backend (FastAPI)       backend/    — built on the vendored nayactl protocol
      |  USB CDC serial
Naya Create keyboard
Electron desktop shell         electron/   — spawns the backend, hosts the renderer
```

The renderer, backend, and shell are separable: the backend runs standalone and
is `curl`-testable without the UI.

## Status

- **Phase 0 — scaffold:** done. Backend, frontend, Electron shell, DB, docs.
- **Phase 1 — nayactl-backed features:** in progress. Device discovery, status
  (fw/hw/battery/BLE/module), LED control, diagnostics, SPI-flash self-test,
  clear-BLE, `dump_settings`. Verified off-device; on-device verification pending
  a connected keyboard.
- **Phase 2 — keymap editor:** not started. Requires the REMAP protocol
  (`device/remap.py`) — the main product. Opcodes documented, wire format TBD.
- **Phase 3 — firmware update:** blocked on obtaining a firmware image (the NayaOS
  open problem).

## Run it (dev)

Backend:

```powershell
cd backend
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m openflow_backend 3001   # http://localhost:3001
```

Frontend (separate terminal):

```powershell
cd frontend
npm install
npm run dev                                            # http://localhost:5173
```

Or the whole app in Electron (spawns the backend for you):

```powershell
cd electron
npm install
npm run start:dev
```

Off-device smoke test: `backend\.venv\Scripts\python.exe backend\tests\smoke.py`.

## Layout

| Path | What |
|---|---|
| `backend/openflow_backend/device/service.py` | Structured device ops (lifted from nayactl's CLI). |
| `backend/openflow_backend/device/remap.py` | Phase 2 REMAP scaffold (keymap/layer/macro). |
| `backend/openflow_backend/device/commands.py` | Maps recovered `command` events to CDC ops. |
| `backend/openflow_backend/api/` | REST + SSE (recovered contract). |
| `backend/openflow_backend/db/` | SQLite (schema from NayaFlow). |
| `backend/openflow_backend/_vendor/nayactl/` | Vendored nayactl (Apache-2.0). |
| `frontend/src/` | React renderer. |
| `docs/` | API contract, asset provenance. |

## License

Apache-2.0. Vendored nayactl retains its own Apache-2.0 license. See
`docs/asset-provenance.md` for the clean-reskin asset policy.
