"""App + device settings (key/value in the `settings` table).

Schema-driven so the UI can render generically. Device behavior + OneKey timing
values are stored offline and flashed to the keyboard later (they map to the
firmware's global tapping-term / hold-tap flavour + our OneKey timing model).
Interface settings are app-local.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .database import connect

# Grouped schema. kind: slider | toggle | select. Values persist by `id`.
SETTINGS_SCHEMA = [
    {
        "group": "Behavior",
        "scope": "device",
        "desc": "How keys resolve on the keyboard. Flashed to the device.",
        "fields": [
            {"id": "interrupt_flavor", "label": "Interrupt Flavor", "kind": "select",
             "desc": "How a hold-tap key resolves when interrupted.",
             "options": ["Balanced", "Hold-Preferred", "Tap-Preferred", "Tap-Unless-Interrupted"],
             "default": "Balanced"},
            {"id": "tapping_term_ms", "label": "Tapping Term (ms)", "kind": "slider",
             "desc": "How long the keyboard waits before deciding a key is held.",
             "min": 10, "max": 1000, "default": 200, "unit": "ms"},
            {"id": "idle_timeout_s", "label": "Idle Timeout (s)", "kind": "slider",
             "desc": "Wait before disabling LEDs to save battery. 0 = off.",
             "min": 0, "max": 6000, "default": 90, "unit": "s"},
            {"id": "sleep_timeout_s", "label": "Sleep Timeout (s)", "kind": "slider",
             "desc": "Idle before deep sleep (lighting, BT, memory). 0 = off.",
             "min": 0, "max": 6000, "default": 300, "unit": "s"},
            {"id": "led_action_override", "label": "LED Action Override", "kind": "select",
             "desc": "How long an LED action overrides the colourmap.",
             "options": ["until keyboard restart", "until next layer change"],
             "default": "until keyboard restart"},
            {"id": "led_max_brightness", "label": "LED Maximum Brightness", "kind": "slider",
             "desc": "Cap LED brightness. Lowering it improves battery life.",
             "min": 0, "max": 100, "default": 100, "unit": "%"},
            {"id": "led_scan_mode", "label": "LED Scan Mode", "kind": "toggle",
             "desc": "PWM scanning to cut power / extend LED life. Disable when filming.",
             "default": True},
        ],
    },
    {
        "group": "OneKey Timing",
        "scope": "device",
        "desc": "Global timing for multi-behavior keys (Dygma-style model). Flashed to the device.",
        "fields": [
            {"id": "onekey_tap_timeout_ms", "label": "Tap Timeout (ms)", "kind": "slider",
             "desc": "Window to register a second tap (double-tap detection).",
             "min": 50, "max": 500, "default": 200, "unit": "ms"},
            {"id": "onekey_holdstart_ms", "label": "Hold Start (ms)", "kind": "slider",
             "desc": "Minimum time from keydown before a hold triggers.",
             "min": 50, "max": 500, "default": 200, "unit": "ms"},
            {"id": "onekey_waitfor_ms", "label": "Wait For Release (ms)", "kind": "slider",
             "desc": "Delay before a held action repeats (release for a single output).",
             "min": 0, "max": 1000, "default": 500, "unit": "ms"},
            {"id": "onekey_overlap_pct", "label": "Overlap (%)", "kind": "slider",
             "desc": "Overlap tolerated during fast typing before a hold triggers.",
             "min": 0, "max": 100, "default": 20, "unit": "%"},
        ],
    },
    {
        "group": "Interface",
        "scope": "app",
        "desc": "OpenFlow application preferences.",
        "fields": [
            {"id": "language", "label": "Language", "kind": "select",
             "desc": "Application language.", "options": ["English"], "default": "English"},
            {"id": "input_source", "label": "Input Source", "kind": "select",
             "desc": "Keyboard layout used for legends.",
             "options": ["QWERTY", "AZERTY", "QWERTZ", "Dvorak", "Colemak"], "default": "QWERTY"},
            {"id": "tray_battery", "label": "Show Battery in Tray", "kind": "toggle",
             "desc": "Show battery status in the system tray / menu bar.", "default": False},
            {"id": "interface_scaling", "label": "Interface Scaling", "kind": "slider",
             "desc": "Zoom the interface. 0 = default.",
             "min": -500, "max": 500, "default": 0, "unit": ""},
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
                raw = stored.get(f["id"], f["default"])
                fields.append({**f, "value": _coerce(f, raw)})
            groups.append({**g, "fields": fields})
        return {"groups": groups}
    finally:
        conn.close()


def set_setting(key: str, value) -> dict:
    field = _FIELD_BY_ID.get(key)
    if field is None:
        raise ValueError(f"unknown setting: {key}")
    val = _coerce(field, value)
    stored = "true" if val is True else "false" if val is False else str(val)
    conn = connect()
    try:
        now = _now()
        existing = conn.execute(
            "SELECT 1 FROM settings WHERE correlation_id=?", (key,)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE settings SET value=?, type=?, updated_at=? WHERE correlation_id=?",
                (stored, field["kind"], now, key),
            )
        else:
            conn.execute(
                "INSERT INTO settings (value, correlation_id, type, created_at, updated_at) "
                "VALUES (?,?,?,?,?)",
                (stored, key, field["kind"], now, now),
            )
        conn.commit()
        return {"ok": True, "key": key, "value": val}
    finally:
        conn.close()
