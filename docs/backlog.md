> **Superseded by [`docs/backlog.md`](../../docs/backlog.md) (2026-09-08).**
> Kept for history only. Several items below shipped: the REMAP flash codec,
> module gesture-binding editing, and richer macros. The items still open were
> imported into Jira on 2026-09-16 (project SCRUM); their keys are marked below.

# OpenFlow backlog

Deferred / future work, most valuable first. Device-blocked items wait on the
keyboard + firmware dump.

## Blocked on the keyboard / firmware dump
- **REMAP flash codec** — reverse-engineer Naya's `WRITE LAYER DATA` format so any
  edits (bindings, colors, OneKey slots) flash to the device. Everything the
  editor produces sits offline in the DB until this lands. See
  `openflow_backend/device/remap.py` and `D:\NayaOS\firmware\docs\naya-remap-notes.md`.
- **OneKey firmware prototype** — the open `&onekey` behavior (design in
  `D:\NayaOS\firmware\`). Explicitly *held*: building it now means guessing against
  firmware we can't see. Step 1 (resolve-and-invoke) can run on a generic ZMK dev
  board when we choose to start; the production build needs the board definition.
- **Validate Naya's Double Tap / Tap+Hold** against real hardware + Dygma's timing
  before trusting them (`naya-remap-notes.md` checklist).

## Features (buildable now, device-independent)
- **Smart Integrations** [SCRUM-30] — auto profile switching by detecting the active
  application (Naya advertised this "coming soon"; Dygma-style). Needs an OS
  foreground-app watcher in the Electron main + a per-app→profile mapping. Good
  candidate once profiles are solid (they now are).
- **Module gesture-binding editing** — the Modules bindings tab is display-only;
  make the gesture→action rows editable (settings already are).
- **Richer macros** — mouse/loop step types, "open a program" (really an OS
  shortcut macro, since the keyboard only sends keystrokes), true drag-reorder.
- **Module-slot assignment persistence** [SCRUM-34] — currently localStorage; move to the DB
  `module_config_bindings` table when device sync lands.
- **Shortcut icons** [SCRUM-32] — replace the combo glyphs with a real icon set mapped to
  upstream Material Symbols (clean-room), matching NayaFlow's look.
- **Tune dial** [SCRUM-33] — clockwise/counter-clockwise as separate actions + making the
  dial's Volume Control rebindable (Naya firmware-gated it).
- **Profile/layer import v2** [SCRUM-31] — include module configs + LED maps in the export
  (v1 covers layers, keys, bindings, and referenced macros).
- **Board cosmetics** — angled/beveled keycaps to match NayaFlow more exactly.

## Naming / provenance
- [SCRUM-32] Clean-reskin follow-ups in `docs/asset-provenance.md` (branding, action icons,
  module display art) before any public release.
