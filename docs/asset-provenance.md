# OpenFlow asset provenance & clean-reskin policy

OpenFlow is a **clean reskin** of NayaFlow: faithful layout, own identity. This
document records what may be reused, what must be recreated, and why. Naya B.V. is
bankrupt and its IP is under curator control; **trademark rights survive
bankruptcy**, so branding must not be copied even though the app code is not
copyleft.

## Safe to reuse verbatim (functional facts / permissive licenses)

- **Neutral tonal palette** — the `--color-neutral*` / `--color-neutral-variant*`
  values from NayaFlow's recovered CSS. A standard Material tonal system, not a
  creative asset. Copied into `frontend/src/styles/theme.css`.
- **DB schema, API field names, route paths, SSE event names** — functional
  interface facts. Reused so the door stays open to importing an existing
  NayaFlow `user-data.db`.
- **Device constants / keycode vocabulary / ZMK behaviour mapping** —
  `D:\NayaOS\docs\device-constants.txt`. Facts about the hardware.
- **Physical key layout** — 97 keys, position IDs 0–96.

## Re-source upstream (permissive, do NOT copy from Naya's build)

- **Material Symbols icons** (Apache-2.0) — pull from the upstream icon set, not
  from `.../assets/icons/external/`.
- **DM Sans** (SIL OFL) — bundle from the upstream font, not from Naya's `assets`.

## Must recreate or replace (Naya-original — redistribution/trademark risk)

- **Brand accent color** — Naya's `--naya-green: #1dd791` is **not** used.
  OpenFlow uses its own accent (`--accent`, currently placeholder `#19c3d4`).
- **860 `action` icons** (`.../assets/icons/action/`) — Naya-original. **Decision
  2026-09-10 (project owner): shipped as-is** in `frontend/public/icons/action/`, on the
  grounds that Naya is defunct and the icons serve the community it left behind. No
  licence is claimed; `frontend/public/icons/action/PROVENANCE.md` records the source.
  Painted through a CSS mask so the files stay untouched.
- **`internal/` + `ui` icon sets, all branding images** (logos, page
  backgrounds in `.../assets/images/`) — do not copy.
- **UI copy / i18n `expression` strings** — Naya-authored text; rewrite. (The
  recovered strings may be consulted to understand *what* a control does, but the
  wording is OpenFlow's own.)

## Module display images (`frontend/public/modules/*.png`)

The Track/Touch/Tune module images are outline depictions derived from NayaFlow's
module visuals (centers made transparent). They're functional hardware-shape
depictions used as UI placeholders. Before public release, confirm they're clean
(redraw from the FCC photos / hardware if needed) — treat as the same category as
other Naya-original imagery until then.

## Keycap shapes (`frontend/src/lib/keyshapes.js`)

The board's keycap silhouettes are the exact values from NayaFlow's renderer — inline
SVG `<path>` shapes indexed by position. They depict the physical Naya Create keyboard's
key outlines (a functional fact also derivable from the FCC teardown photos), but the
specific path data is Naya-drawn. **Treat as hardware-shape depiction to confirm/redraw
before public release** — same category as the module display art.

The PLACEMENT of every key, thumb, module slot and side LED bar (`frontend/src/lib/
keygeometry.json`, a checked copy of `docs/reference/create-key-geometry.json`) was
measured from NayaFlow's own rendered board (tools/export_key_geometry.js), not
transcribed: since 2026-09-16 the board draws from those coordinates at one scale
(`lib/boardgeom.js`), and `tools/board-parity.js` proves it in the browser (max deviation
0.07 px; the earlier flexbox mirror drifted up to 60 px). Coordinates are functional
layout fact and clean to keep.

## Open items

- Finalize the OpenFlow name, logo, and accent color (currently placeholders).
- Decide whether to bundle DM Sans or ship a system-font stack (Phase 1 uses the
  system fallback).
