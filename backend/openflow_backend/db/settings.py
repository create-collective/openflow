"""App + device settings (key/value in the `settings` table).

Schema-driven so the UI can render generically. Device behavior + OneKey timing
values are stored offline and flashed to the keyboard later (they map to the
firmware's global tapping-term / hold-tap flavour + our OneKey timing model).
Interface settings are app-local.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .database import connect

# How much we actually know about a setting, shown in the UI and doubling as the work queue.
# This exists because seven settings were labelled "Flashed to the device" while none of them
# reached it: set_setting wrote correlation_id="tapping_term_ms" and the flash looked up
# "8fe34f61-...", so they never met. A label the code cannot back up is worse than no label.
VERIFIED = "verified"          # a capture or live probe proves this reaches the device
EXPERIMENTAL = "experimental"  # plausibly device-backed, unproven -> this is the probe queue
APP_ONLY = "app"               # intentionally local; not a gap
HOST_SIDE = "host"             # a host-side model (Create Companion), never flashed -- not a probe

# Grouped schema. kind: slider | toggle | select.
#
# Device-scoped fields persist under `device_key` -- NayaFlow's own correlation UUID -- not under
# `id`. That is deliberate: OpenFlow imports real NayaFlow databases (db/backup.py), so sharing
# the correlation id means an imported DB's settings are read correctly instead of silently
# ignored, which is this same bug in reverse. `device_values` maps our display label to the wire
# value the firmware/flash path expects, because matching the KEY is not enough if the VALUE
# still reads "Balanced" where flash._read_term_flavour wants "balanced".
SETTINGS_SCHEMA = [
    {
        "group": "Behavior",
        "scope": "device",
        "desc": "How keys resolve on the keyboard. Flashed to the device.",
        "fields": [
            {"id": "interrupt_flavor", "label": "Interrupt Flavor", "kind": "select",
             "desc": "How a hold-tap key resolves when interrupted.",
             "options": ["Balanced", "Hold-Preferred", "Tap-Preferred", "Tap-Unless-Interrupted"],
             "default": "Balanced", "provenance": VERIFIED,
             "device_key": "24de8555-1a56-4e02-a1c3-3641603a5ac9",
             # flash._read_term_flavour's FLAVOUR_ENUM keys, which are NayaFlow's own wire values.
             "device_values": {"Balanced": "balanced", "Hold-Preferred": "hold-preferred",
                               "Tap-Preferred": "tap-preferred",
                               "Tap-Unless-Interrupted": "tap-unless-interrupted"}},
            {"id": "tapping_term_ms", "label": "Tapping Term (ms)", "kind": "slider",
             "desc": "How long the keyboard waits before deciding a key is held.",
             "min": 10, "max": 1000, "default": 200, "unit": "ms", "provenance": VERIFIED,
             "device_key": "8fe34f61-df0c-48c9-b0f7-ee9bfbaa2a05"},
            # `min_nonzero`: the firmware refuses 1-29 s (measured 2026-09-11, ack 0xEA, value
            # unchanged) and takes 0 as off. The writer enforces it; the description says it.
            {"id": "idle_timeout_s", "label": "Idle Timeout (s)", "kind": "slider",
             "desc": "Wait before disabling LEDs to save battery. 0 = off; otherwise at least 30 s.",
             "min": 0, "max": 6000, "default": 90, "unit": "s", "provenance": VERIFIED,
             "min_nonzero": 30,
             "device_key": "ded8e734-b10b-48c9-9ab1-536904e2c3de"},
            {"id": "sleep_timeout_s", "label": "Sleep Timeout (s)", "kind": "slider",
             "desc": "Idle before deep sleep (lighting, BT, memory). 0 = off; otherwise at least 30 s.",
             "min": 0, "max": 6000, "default": 300, "unit": "s", "provenance": VERIFIED,
             "min_nonzero": 30,
             "device_key": "f198f968-2c42-4df6-8fdd-97de148cad1a"},
            # The three LED settings below have known correlation ids but OpenFlow emits no write
            # for them -- the flash only sends SYS_SET_TIMEOUTS and folds term/flavour into
            # hold-tap records. Storing them under the right key is necessary but not sufficient.
            {"id": "led_action_override", "label": "LED Action Override", "kind": "select",
             "desc": "How long an LED action overrides the colourmap.",
             "options": ["until keyboard restart", "until next layer change"],
             "default": "until keyboard restart", "provenance": EXPERIMENTAL,
             "device_key": "385426f7-e454-4174-babe-4ca4a670cbe2",
             "device_values": {"until keyboard restart": "until_keyboard_restart",
                               "until next layer change": "until_layer_change"}},
            {"id": "led_max_brightness", "label": "LED Maximum Brightness", "kind": "slider",
             "desc": "Cap LED brightness. Lowering it improves battery life.",
             "min": 0, "max": 100, "default": 100, "unit": "%", "provenance": EXPERIMENTAL,
             "device_key": "321fe22c-74e0-48cf-a954-326bf4391fd7"},
            {"id": "led_scan_mode", "label": "LED Scan Mode", "kind": "toggle",
             "desc": "PWM scanning to cut power / extend LED life. Disable when filming.",
             "default": True, "provenance": EXPERIMENTAL,
             "device_key": "66770f52-e917-4f17-b775-6308b1e4281a"},
        ],
    },
    {
        "group": "OneKey Timing",
        "scope": "device",
        # No correlation id exists for these anywhere -- they are OUR model, not one we have seen
        # NayaFlow or the firmware carry, and nothing in the flash path reads them. They are the
        # host-side OneKey timing model, Create Companion's territory -- hence provenance HOST_SIDE,
        # not EXPERIMENTAL, which would wrongly imply a firmware setting waiting to be probed.
        "desc": "Global timing for multi-behavior keys (Dygma-style model). Applied host-side by "
                "Create Companion, not flashed to the keyboard -- the firmware has no setting for these.",
        "fields": [
            {"id": "onekey_tap_timeout_ms", "label": "Tap Timeout (ms)", "kind": "slider",
             "desc": "Window to register a second tap (double-tap detection).",
             "min": 50, "max": 500, "default": 200, "unit": "ms", "provenance": HOST_SIDE},
            {"id": "onekey_holdstart_ms", "label": "Hold Start (ms)", "kind": "slider",
             "desc": "Minimum time from keydown before a hold triggers.",
             "min": 50, "max": 500, "default": 200, "unit": "ms", "provenance": HOST_SIDE},
            {"id": "onekey_waitfor_ms", "label": "Wait For Release (ms)", "kind": "slider",
             "desc": "Delay before a held action repeats (release for a single output).",
             "min": 0, "max": 1000, "default": 500, "unit": "ms", "provenance": HOST_SIDE},
            {"id": "onekey_overlap_pct", "label": "Overlap (%)", "kind": "slider",
             "desc": "Overlap tolerated during fast typing before a hold triggers.",
             "min": 0, "max": 100, "default": 20, "unit": "%", "provenance": HOST_SIDE},
        ],
    },
    {
        "group": "Interface",
        "scope": "app",
        "desc": "OpenFlow application preferences.",
        "fields": [
            {"id": "language", "label": "Language", "kind": "select",
             "desc": "Application language.", "options": ["English"], "default": "English",
             "provenance": APP_ONLY},
            # Input Source (keyboard-legend layout) moved to a dropdown on the virtual keyboard
            # itself, where it is actually applied -- it did nothing as a global preference here.
            {"id": "tray_battery", "label": "Show Battery in Tray", "kind": "toggle",
             "desc": "Show battery status in the system tray / menu bar. Available in the desktop "
                     "app; the tray does not exist in the browser build.", "default": False,
             "provenance": APP_ONLY,
             "deferred": "Ships with the desktop (Electron) app -- there is no system tray to draw "
                         "into from the browser dev build.", "deferred_badge": "desktop app"},
            {"id": "interface_scaling", "label": "Interface Scaling", "kind": "slider",
             "desc": "Zoom the interface. 0 = default.",
             "min": -500, "max": 500, "default": 0, "unit": "", "provenance": APP_ONLY},
        ],
    },
]

_FIELD_BY_ID = {f["id"]: f for g in SETTINGS_SCHEMA for f in g["fields"]}


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _coerce(field, raw):
    if field["kind"] == "toggle":
        if isinstance(raw, bool):
            return raw
        return str(raw).lower() == "true"
    if field["kind"] == "slider":
        try:
            return int(raw)
        except (TypeError, ValueError):
            return field["default"]
    return raw  # select / string


def storage_key(field) -> str:
    """The `settings.correlation_id` a field lives under.

    Device fields use NayaFlow's UUID so the flash path and an imported NayaFlow database both
    find them; app-only fields keep the readable id, since nothing else ever reads those.
    """
    return field.get("device_key") or field["id"]


def _to_wire(field, value):
    """Display value -> the string stored in the DB (and read by the flash path)."""
    mapping = field.get("device_values")
    if mapping:
        return mapping.get(value, value)
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)


def _from_wire(field, raw):
    """Stored string -> display value. Inverse of _to_wire for mapped selects."""
    mapping = field.get("device_values")
    if mapping:
        for label, wire in mapping.items():
            if wire == raw:
                return label
        return raw          # an unrecognised wire value shows as-is rather than silently
    return raw              # becoming the default and hiding that the DB holds something odd


def migrate_legacy_setting_keys(conn) -> int:
    """Move device settings written under the plain id onto their correlation UUID.

    Before this, `set_setting("tapping_term_ms", 250)` wrote correlation_id="tapping_term_ms"
    while flash._read_term_flavour looked up "8fe34f61-...", so every device setting a user had
    ever changed was inert. Those rows are real user intent and are carried over rather than
    dropped -- including the value, which also has to be translated ("Balanced" -> "balanced").

    A row already present under the UUID wins: it came from a real NayaFlow database or from a
    write made after the fix, and either is more authoritative than the stale one.
    """
    moved = 0
    for f in _FIELD_BY_ID.values():
        key = f.get("device_key")
        if not key:
            continue
        legacy = conn.execute("SELECT value FROM settings WHERE correlation_id=?",
                              (f["id"],)).fetchone()
        if legacy is None:
            continue
        current = conn.execute("SELECT 1 FROM settings WHERE correlation_id=?", (key,)).fetchone()
        if current is None:
            conn.execute(
                "INSERT INTO settings (value, correlation_id, type, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (_to_wire(f, _coerce(f, legacy["value"])), key, f["kind"], _now(), _now()))
            moved += 1
        conn.execute("DELETE FROM settings WHERE correlation_id=?", (f["id"],))
    return moved


def get_settings() -> dict:
    """Return the schema with each field's current (stored-or-default) value."""
    conn = connect()
    try:
        stored = {
            r["correlation_id"]: r["value"]
            for r in conn.execute("SELECT correlation_id, value FROM settings")
        }
        groups = []
        for g in SETTINGS_SCHEMA:
            fields = []
            for f in g["fields"]:
                raw = stored.get(storage_key(f))
                value = f["default"] if raw is None else _from_wire(f, raw)
                fields.append({**f, "value": _coerce(f, value)})
            groups.append({**g, "fields": fields})
        return {"groups": groups}
    finally:
        conn.close()


def set_setting(key: str, value) -> dict:
    field = _FIELD_BY_ID.get(key)
    if field is None:
        raise ValueError(f"unknown setting: {key}")
    val = _coerce(field, value)
    floor = field.get("min_nonzero")
    if floor and 0 < val < floor:
        raise ValueError(f"{field['label']}: the keyboard refuses values under {floor} s "
                         f"(0 turns it off); {val} would not be stored")
    # The row is keyed by the correlation UUID for device fields, and holds the WIRE value --
    # both halves matter. Writing "tapping_term_ms"/"Balanced" instead of the UUID/"balanced" is
    # what made every device setting inert; matching only one of the two would still be inert.
    row_key = storage_key(field)
    stored = _to_wire(field, val)
    conn = connect()
    try:
        now = _now()
        existing = conn.execute(
            "SELECT 1 FROM settings WHERE correlation_id=?", (row_key,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE settings SET value=?, type=?, updated_at=? WHERE correlation_id=?",
                (stored, field["kind"], now, row_key),
            )
        else:
            conn.execute(
                "INSERT INTO settings (value, correlation_id, type, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (stored, row_key, field["kind"], now, now),
            )
        conn.commit()
        return {"ok": True, "key": key, "value": val}
    finally:
        conn.close()
