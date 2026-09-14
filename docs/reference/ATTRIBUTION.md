# Third-party data

## ShortcutMapper

`docs/reference/app-shortcuts.json` is derived from **ShortcutMapper** by Waldo Bronchart and
contributors, MIT licensed.

    https://github.com/waldobronchart/ShortcutMapper

The shortcut data -- application names, action labels, key combinations and per-OS variants -- is
theirs. What is ours is the transposition into single chord strings and the device byte encoding
alongside each one.

Covers 20 creative and IDE applications (Photoshop, After Effects, Illustrator, Lightroom,
Blender, Maya, 3ds Max, Houdini, Unity, SketchUp, Nuke, Sublime Text and the JetBrains family),
5,311 distinct actions, per OS.

MIT requires the copyright notice and permission notice be retained; the upstream LICENSE applies
to the data in that file.

## NayaFlow key geometry

`docs/reference/create-key-geometry.json` and `.svg` (written by `tools/export_key_geometry.js`)
hold the keycap silhouettes NayaFlow 1.25.1 draws -- 34 inline SVG paths copied verbatim from its
renderer bundle -- and where its board component places each of the 74 keys, the two module
slots and the 14 side LED bars, measured by rendering that component against the app's own
compiled CSS. The artwork and layout are Naya's; the extraction, the measurement and the file
shape are ours. The same silhouettes already drive OpenFlow's board
(`openflow/frontend/src/lib/keyshapes.js`). Naya wound down in 2026 and the assets are used to
keep the hardware serviceable; see `openflow/frontend/public/icons/action/PROVENANCE.md` for the
same decision on the icon set.

## Not included

**NayaFlow's icon assets, originally.** `docs/reference/nayaflow-action-names.json` records the
NAMES from NayaFlow's action icon set, which we use as a canonical vocabulary. The icons
themselves were held back until 2026-09-10, when the owner decided to ship them for the
community the vendor abandoned; they now live under `openflow/frontend/public/icons/action/`
with their own PROVENANCE.md.

**VS Code default keybindings.** Convenience mirrors of these exist on GitHub but at least one
carries no LICENSE file, which under default copyright means all rights reserved regardless of
how the accompanying extension is distributed. VS Code itself is MIT, so its defaults should be
taken from the product or from `microsoft/vscode`, not from an unlicensed third-party copy.

## app-shortcuts.json (regenerated 2026-09-06)

150 applications, 19,853 chords. A MERGE of two sources, not a replacement -- the second is
broader, the first is deeper on what they share:

* **ShortcutMapper** (waldobronchart, MIT) -- the original 20-application import, which remains
  the deepest source for the applications it covers (Blender alone contributes 741).
* **CreateCompanion's curated catalog** -- 134 further applications with per-app `sources` and
  hand-authored defaults, plus a category for each, which is what makes 150 applications
  navigable.

Regenerate with `tools/import_companion_catalog.py --write`. It merges into whatever is already
in the file and keeps the existing chord where both sources name the same action.

Every chord is translated from human notation into the device vocabulary and validated through
`remap.encode_keypress`. Dropped rather than shipped: multi-step `sequence` entries (one binding
is one record; a sequence is a macro) and anything using `Fn` (not a HID modifier). A palette
entry that cannot be flashed is worse than a missing one, because it looks bound.
