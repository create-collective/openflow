# OpenFlow backend API contract

Reconstructed from the NayaFlow 1.25.1 renderer
(`extracted/NayaFlow-1.25.1/asar/dist/renderer/assets/index-mihUmo_8.js`). This is
the localhost HTTP/SSE surface the original renderer expected from
`flow-bg-server.exe`. OpenFlow reimplements the subset needed for Phases 1–2 and
adds a few explicit routes; unimplemented original routes are noted.

## Base URL

The renderer computes `http://localhost:${window.EXPOSED.bgServerPort}` and falls
back to `3001`. The Electron preload sets `window.EXPOSED.bgServerPort` from argv
(second-to-last, after `/prefetch:1` is filtered) — OpenFlow keeps this contract.

## Implemented (OpenFlow Phase 1)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness probe (OpenFlow-added). |
| GET | `/api/info/system` | App + OS info. |
| GET | `/api/ui/state` | UI readiness + device count. |
| GET | `/api/devices` | USB enumeration (fast, no serial I/O). |
| GET | `/api/status` | Full per-half status (fw, hw id, battery, BLE, module). |
| GET | `/api/diagnostics/report` | Diagnostics bundle. |
| POST | `/rpc/send-nayacore-zmq-message` | The original single device-control entry point (`{messages:[topic,event,...frames]}`). |
| POST | `/rpc/led` | LED on/off/toggle/brightness/effect (OpenFlow-added convenience). |
| POST | `/rpc/text-command` | ASCII text protocol passthrough. |
| POST | `/rpc/dump-settings` | `dump_settings` text command. |

### `/rpc/send-nayacore-zmq-message` command events

The renderer's only device-control path. Body `{messages:[topic, event, ...frames], side?, force?}`.
Observed events and current handling:

| event | Phase | Handling |
|---|---|---|
| `repair_flash` | 1 | Read-only SPI flash self-test (`0xFA/0x1001`). Destructive repair requires force (not yet wired). |
| `clear_ble_devices` | 1 | `clear_bonds` text command (force-gated). |
| `clear_data` | 2 | REMAP `CLEAR_ALL_DATA` (`0x30/0x10CA`) — not yet implemented. |
| `create_pairing_start` | 2 | Pairing workflow — not yet implemented. |
| `update_create_fw` | 3 | Blocked on obtaining a firmware image. |
| `update_module_fw` | 3 | Blocked on obtaining a firmware image. |

## SSE — `GET /sse`

One `EventSource`; named events (renderer uses `addEventListener`):

| event name | Phase | Payload |
|---|---|---|
| `sse:ui-state-change` | 1 | `{ready}` |
| `sse:naya-devices-stream` | 1 | `{devices:[...]}` — emitted on change (2s USB poll). |
| `sse:flash-keymap-state` | not sent | NayaFlow's keymap flash progress; a keymap flash answers its own request here. |
| `sse:flash-progress` | — | Ours, not NayaFlow's: a firmware run's steps as they happen (SCRUM-102). `{id, running, sides, seq, events:[...], verdict}`, with only the events after the last `seq` sent. While a run is going the device poll is suspended — it would queue behind the run's service lock — and the tick becomes this one. |
| `sse:device-operation-options` | not sent | NayaFlow's device op options; nothing here uses them. |
| `sse:main-process-quit` | not sent | NayaFlow's shell shutdown; the shell stops the backend over `/rpc/shutdown`. |

## Original routes not yet implemented

From the recovered renderer, deferred until needed:
`/api/userdata`, `/api/actions`, `/api/actions/{id}`, `/api/templates`,
`/api/ui/module-settings`, `/api/ui/settings`, `/api/list-userdata-backups`,
`/api/components/{type}`, `/api/i18n/ui`, and the `/rpc/*` user-data/backup/log/
template/import-export routes. These map onto the SQLite store (Phase 1/2) and the
template system (later).
