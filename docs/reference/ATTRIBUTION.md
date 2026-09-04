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
