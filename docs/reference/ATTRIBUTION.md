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

## Not included

**NayaFlow's icon assets.** `docs/reference/nayaflow-action-names.json` records the NAMES from
NayaFlow's action icon set, which we use as a canonical vocabulary. No SVG from that application
is copied into this repository -- the artwork is Naya's own work and is not ours to redistribute.

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
