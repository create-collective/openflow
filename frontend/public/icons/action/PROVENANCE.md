# NayaFlow action icons

Every `.svg` in this directory is copied unchanged from NayaFlow 1.25.1
(`asar/dist/renderer/assets/icons/action/`), the icon set the vendor's app draws on its keycaps.
They are Naya's artwork. The project owner chose on 2026-09-10 to ship them in OpenFlow, on the
grounds that Naya is defunct and these serve the community it left behind. No licence for them
was granted to this project, and none is claimed here.

Regenerate with `python tools/import_nayaflow_icons.py`; `--check` reports drift.
The UI paints them through a CSS mask (`.naya-icon`), so the white fills take the theme's text
colour and the files themselves stay untouched.
