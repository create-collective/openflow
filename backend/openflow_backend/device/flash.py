"""Flash orchestration for the Naya Create — build a write plan and (optionally) send it.

The inverse of the read path, one level up from `remap.py`'s encoders. Turns a desired
board state (from the OpenFlow DB, or from a device read for round-trip testing) into the
ordered WRITE sequence NayaCore uses, chunk-framed and ready to send — or, in dry-run,
just the frames + a diff summary and nothing on the wire.

Write order (from the captured flashes, docs/write-protocol-spec.md), all to dest 0x50:
  WRITE_LAYER_LIST (only if layers added/removed)
  -> WRITE_LAYER_DATA per changed layer
  -> WRITE_MODULE_CONFIG_DATA per changed slot
  -> WRITE_LED_MAP per changed layer
  -> SYSTEM SET_TIMEOUTS (only if timeouts changed)
  -> verification reads + diff

Everything here is dry unless `flash(..., dry_run=False)` is called with a live transport.
Module GESTURE bindings are intentionally NOT written — see MODULE CONFIDENCE below.
"""
from __future__ import annotations

import colorsys
from dataclasses import dataclass, field

from .._vendor.nayactl.constants import CAT_SYSTEM
from . import remap as R

FULL_LAYER_POSITIONS = range(0x00, 0x52)     # 82 positions = whole board + module slots
LED_COUNT = 88                                # 0x00..0x57 (observed full LED map = 136? see note)
SYS_SET_TIMEOUTS = 0x100A

# ---- MODULE CONFIDENCE ------------------------------------------------------------------
# Captured WRITE evidence exists only for these module-config fields, so only these are
# safe to encode/flash. Everything else (the type-0x0f (axis,direction) gesture fields, the
# 0x03/0x04 flags) is passed through UNCHANGED and never rewritten. Multi-finger gesture ->
# action bindings are NOT written: their device encoding is unconfirmed (read-only, no
# captured write; NayaFlow's own gesture editor is incomplete). See flash notes / the plan.
MODULE_SAFE_FIELDS = {
    0x00: ("pointer_speed", "u8"),
    0x01: ("scroll_speed", "u8"),
    0x02: ("pointer_accel", "u8"),
    0x08: ("one_finger_tap", "keypress"),
}


# --------------------------------------------------------------------------- #
# desired state                                                               #
# --------------------------------------------------------------------------- #

@dataclass
class DesiredState:
    """Everything a flash can set. `layers`/`leds` are keyed by device layer index."""
    layers: dict[int, dict[int, tuple[int, bytes]]] = field(default_factory=dict)   # idx -> {pos: (type, param)}
    leds: dict[int, dict[int, tuple[int, int]]] = field(default_factory=dict)        # idx -> {led: (hue, value)}
    modules: dict[int, dict[int, tuple[int, bytes]]] = field(default_factory=dict)   # slot -> {field: (type, value)}
    timeouts: tuple[int, int, int] | None = None                                     # (idle, sleep, sleep_batt) ms
    layer_uuids: dict[int, bytes] = field(default_factory=dict)                       # idx -> 16-byte id (add/delete)


def desired_from_read(read_json: dict) -> DesiredState:
    """Build the desired state from a device read (raw_records + led). Faithful: uses the
    exact bytes the board returned, so a re-flash round-trips (Phase B / round-trip test)."""
    d = DesiredState()
    for k, recs in read_json["raw_records"].items():
        idx = int(k)
        d.layers[idx] = {}
        for pos, typ, param_hex in recs:
            if pos in FULL_LAYER_POSITIONS:
                d.layers[idx][pos] = (typ, bytes.fromhex(param_hex))
    led = read_json.get("led") or {}
    for k, entries in led.items():
        idx = int(k)
        d.leds[idx] = {int(i): (int(h), int(v)) for i, h, v in entries}
    return d


def _hex_to_hue_val(hex_color: str) -> tuple[int, int]:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    h, _s, v = colorsys.rgb_to_hsv(r, g, b)
    return round(h * 360) % 360, round(v * 100)


def desired_from_db(conn) -> DesiredState:
    """Build the desired state from the OpenFlow DB (the DB->device mapping).

    Layers/keys/key_bindings -> binding records; keys.color_hex -> LED map; module_configs +
    the SAFE module fields; settings (correlation ids) -> timeouts + tapping term/flavour.
    Gesture bindings are deliberately skipped (see MODULE CONFIDENCE)."""
    d = DesiredState()
    term, flavour = _read_term_flavour(conn)
    layer_order = {row["id"]: row["order_id"] for row in conn.execute("SELECT id, order_id FROM layers")}
    for lrow in conn.execute("SELECT id, order_id FROM layers ORDER BY order_id"):
        idx = lrow["order_id"]
        d.layers[idx], d.leds[idx] = {}, {}
        q = conn.execute(
            "SELECT k.position_id p, k.color_hex, b.action_type at, b.action_code ac, b.behavior beh "
            "FROM keys k LEFT JOIN key_bindings b ON b.key_id = k.id WHERE k.layer_id = ? ORDER BY k.position_id",
            (lrow["id"],))
        # group multiple binding rows per position (tap+hold)
        by_pos: dict[int, list] = {}
        colors: dict[int, str] = {}
        for r in q:
            if r["p"] is None or r["p"] not in FULL_LAYER_POSITIONS:
                continue
            if r["color_hex"]:
                colors[r["p"]] = r["color_hex"]
            if r["at"] is not None:
                by_pos.setdefault(r["p"], []).append(r)
        for pos, rows in by_pos.items():
            rec = _binding_rows_to_record(rows, term, flavour, layer_order)
            if rec is not None:
                d.layers[idx][pos] = rec
        for pos, hexc in colors.items():
            if len(hexc) == 7 and hexc[0] == "#" and all(c in "0123456789abcdefABCDEF" for c in hexc[1:]):
                d.leds[idx][pos] = _hex_to_hue_val(hexc)
    d.timeouts = _read_timeouts(conn)
    d.modules = _read_module_safe_fields(conn)
    return d


# --- DB -> record helpers (semantic; the interesting mapping) --------------- #

def _binding_rows_to_record(rows: list, term: int, flavour: int, layer_order: dict) -> tuple[int, bytes] | None:
    """One position's binding row(s) -> (type, param). Handles key/modifier/shortcut, layer
    switches, bluetooth, and tap+hold (a 'press' row + a 'hold' row)."""
    press = next((r for r in rows if r["beh"] in ("press", "tap", None)), rows[0])
    hold = next((r for r in rows if r["beh"] == "hold"), None)
    at, code = press["at"], press["ac"]

    if hold is not None:   # tap + hold -> hold-tap record (home-row 0x03 form)
        tap_kp = R.encode_keypress(at, code)
        hold_kp = R.encode_keypress(hold["at"], hold["ac"])
        return R.HOLD_TAP_HOME, R.encode_holdtap_param(R.HOLD_TAP_HOME, flavour, term, hold_kp, tap_kp)

    if at in ("key", "modifier", "shortcut_alias"):
        return R.KEY_PRESS, R.encode_keypress(at, code)
    if at == "bluetooth":
        prof = R.BT_PROFILE_REV.get(code)
        if prof is not None:
            return R.TWO_PARAM, R.encode_twoparam(3, prof)
        return None
    if at in ("layer_polite_hold",):
        return R.LAYER_HOLD, R.encode_layer_param(_target_order(code, layer_order))
    if at in ("layer_rude_toggle",):
        return R.LAYER_TO, R.encode_layer_param(_target_order(code, layer_order))
    if at in ("layer_polite_toggle",):
        return R.LAYER_TOGGLE, R.encode_layer_param(_target_order(code, layer_order))
    return None   # macros, LED-system, mouse, unknown -> not encoded here (see plan)


def _target_order(code: str, layer_order: dict) -> int:
    """'TO_LAYER_<uuid>' / 'TOGGLE_LAYER_<uuid>' / 'MO_LAYER_<uuid>' -> device layer index."""
    uuid = code.split("_LAYER_", 1)[-1]
    return layer_order.get(uuid, 0)


def _read_term_flavour(conn) -> tuple[int, int]:
    TERM = "8fe34f61-df0c-48c9-b0f7-ee9bfbaa2a05"
    FLAV = "24de8555-1a56-4e02-a1c3-3641603a5ac9"
    FLAVOUR_ENUM = {"hold-preferred": 0, "balanced": 1, "tap-preferred": 2, "tap-unless-interrupted": 3}
    term, flavour = 200, 0
    for r in conn.execute("SELECT value, correlation_id FROM settings WHERE correlation_id IN (?,?)", (TERM, FLAV)):
        if r["correlation_id"] == TERM:
            term = int(r["value"])
        else:
            flavour = FLAVOUR_ENUM.get(r["value"], 0)
    return term, flavour


def _read_timeouts(conn) -> tuple[int, int, int] | None:
    IDLE = "ded8e734-b10b-48c9-9ab1-536904e2c3de"
    SLEEP = "f198f968-2c42-4df6-8fdd-97de148cad1a"
    vals = {r["correlation_id"]: r["value"] for r in
            conn.execute("SELECT value, correlation_id FROM settings WHERE correlation_id IN (?,?)", (IDLE, SLEEP))}
    if IDLE not in vals or SLEEP not in vals:
        return None
    return int(vals[IDLE]) * 1000, int(vals[SLEEP]) * 1000, 30000   # sleep_batt default 30s (never captured changing)


def _read_module_safe_fields(conn) -> dict[int, dict[int, tuple[int, bytes]]]:
    """Only the captured-safe module fields (speeds + 1-finger tap). Gesture fields skipped."""
    # Slot numbering is device-assigned (Track/Tune order); left to the flash caller to map
    # module_config_id -> slot. Returned empty here until the slot map is wired in Phase C.
    return {}


# --------------------------------------------------------------------------- #
# plan + frames                                                               #
# --------------------------------------------------------------------------- #

@dataclass
class WriteOp:
    sub: int
    payload: bytes
    label: str
    cat: int = R.CAT_REMAP


def _full_layer_payload(idx: int, poss: dict[int, tuple[int, bytes]]) -> bytes:
    recs = []
    for pos in FULL_LAYER_POSITIONS:
        typ, param = poss.get(pos, (R.NONE_BEH, b""))
        recs.append(R.record(pos, typ, param))
    return R.encode_layer_data(idx, recs)


def _led_payload(idx: int, leds: dict[int, tuple[int, int]]) -> bytes:
    recs = [R.encode_led_record(i, *leds.get(i, (0, 0))) for i in range(max(leds) + 1 if leds else 0)]
    return R.encode_led_map(idx, recs)


def compute_plan(desired: DesiredState, current: DesiredState | None = None, *, full: bool | None = None) -> list[WriteOp]:
    """Ordered write ops. full=True (or current=None) => rewrite everything; otherwise diff and
    emit only changed layers/leds (sparse per-record diffs are a Phase-C refinement)."""
    full = full if full is not None else current is None
    ops: list[WriteOp] = []
    for idx in sorted(desired.layers):
        if full or current is None or desired.layers[idx] != current.layers.get(idx):
            ops.append(WriteOp(R.WRITE_LAYER_DATA, _full_layer_payload(idx, desired.layers[idx]), f"layer {idx}"))
    for idx in sorted(desired.leds):
        if desired.leds[idx] and (full or current is None or desired.leds[idx] != current.leds.get(idx)):
            ops.append(WriteOp(R.WRITE_LED_MAP_DATA, _led_payload(idx, desired.leds[idx]), f"led {idx}"))
    for slot in sorted(desired.modules):
        recs = [R.encode_module_field(f, v, t) for f, (t, v) in sorted(desired.modules[slot].items())]
        ops.append(WriteOp(R.WRITE_MODULE_CONFIG_DATA, R.encode_module_config(slot, recs), f"module slot {slot}"))
    if desired.timeouts and (full or current is None or desired.timeouts != current.timeouts):
        ops.append(WriteOp(SYS_SET_TIMEOUTS, R.encode_timeouts(*desired.timeouts), "timeouts", cat=CAT_SYSTEM))
    return ops


def render_frames(plan: list[WriteOp], dest: int = 0x50) -> list[tuple[str, list[bytes]]]:
    return [(op.label, R.frames_for(dest, op.sub, op.payload, cat=op.cat)) for op in plan]


def module_gesture_write(slot: int, module_type: str,
                         changes: dict[str, tuple[str, str]]) -> WriteOp | None:
    """Build a sparse WRITE_MODULE_CONFIG_DATA that rebinds gesture key-actions.

    `changes` maps a gesture string to (action_type, action_code), e.g.
    {"tap:tune:2_fingers": ("key", "C_MUTE"), "swipe_up:tune:2_fingers": ("key", "A")}.
    Each gesture is resolved to its device field via module_fields and encoded as a keypress;
    only the changed fields are sent (read-modify-write — the rest of the slot is left as-is).
    Raises if a gesture has no writable keypress field (e.g. an axis/LED gesture, or an
    unmapped module type). Pairs with a prior read so the caller only edits fields it saw."""
    from . import module_fields as mf
    gf = mf.gesture_fields(module_type)
    recs = []
    for gesture, (atype, acode) in sorted(changes.items()):
        field = gf.get(gesture)
        if field is None:
            raise R.RemapEncodeError(
                f"{module_type} gesture {gesture!r} has no writable keypress field "
                f"(axis/LED gesture, or unmapped module)")
        recs.append(R.encode_module_field(field, R.encode_keypress(atype, acode)))
    if not recs:
        return None
    return WriteOp(R.WRITE_MODULE_CONFIG_DATA, R.encode_module_config(slot, recs),
                   f"module {module_type} slot {slot} ({len(recs)} gesture(s))")


# --------------------------------------------------------------------------- #
# flash (dry by default)                                                       #
# --------------------------------------------------------------------------- #

def flash(desired: DesiredState, *, transport=None, dest: int = 0x50, current: DesiredState | None = None,
          full: bool | None = None, dry_run: bool = True, reader=None) -> dict:
    """Compute + (optionally) send. dry_run=True (default) sends NOTHING — returns the plan,
    the rendered frames, and a summary. dry_run=False requires a connected transport and is the
    only path that touches the device (ack-checked per frame, then verified via `reader`, a
    callable returning a fresh device read as a DesiredState)."""
    plan = compute_plan(desired, current, full=full)
    rendered = render_frames(plan, dest)
    summary = {
        "dest": f"0x{dest:02x}",
        "ops": [{"label": op.label, "sub": f"0x{op.sub:04x}", "payload_bytes": len(op.payload),
                 "frames": len(frames)} for op, (_, frames) in zip(plan, rendered)],
        "total_frames": sum(len(f) for _, f in rendered),
        "total_bytes": sum(len(op.payload) for op in plan),
    }
    if dry_run:
        return {"dry_run": True, "summary": summary,
                "frames": [f.hex() for _, frames in rendered for f in frames]}

    if transport is None:
        raise ValueError("dry_run=False requires a connected transport")
    return _apply(plan, rendered, transport, desired, reader)


def diff_desired(a: "DesiredState", b: "DesiredState") -> list[dict]:
    """Records/leds in `a` (desired) that differ from `b` (device read-back). Empty = verified.
    Only the positions/leds `a` sets are checked — a full re-read has extra padding we ignore."""
    out = []
    for idx, poss in a.layers.items():
        for pos, rec in poss.items():
            if b.layers.get(idx, {}).get(pos) != rec:
                out.append({"kind": "layer", "layer": idx, "pos": pos,
                            "want": [rec[0], rec[1].hex()],
                            "got": _fmt_rec(b.layers.get(idx, {}).get(pos))})
    for idx, leds in a.leds.items():
        for i, hv in leds.items():
            if b.leds.get(idx, {}).get(i) != hv:
                out.append({"kind": "led", "layer": idx, "led": i,
                            "want": hv, "got": b.leds.get(idx, {}).get(i)})
    return out


def _fmt_rec(rec):
    return None if rec is None else [rec[0], rec[1].hex()]


def _apply(plan, rendered, transport, desired, reader) -> dict:
    """WET write: send each frame, check the ack, then verify by read-back. Aborts on the first
    bad ack (never blind-continues), and reports a verify diff if `reader` is provided. The caller
    is responsible for taking a backup first and restoring on failure."""
    sent = []
    for _op, (label, frames) in zip(plan, rendered):
        for i, frame in enumerate(frames):
            resp = transport._send_raw(frame, 2.0)
            acks = [r for r in resp if getattr(r, "valid", False)]
            flags = acks[0].flags if acks else None
            sent.append({"op": label, "frame": i, "ack_flags": flags})
            if flags != 0x00:   # 0x00 = OK; anything else (e.g. 0xEA) or no ack = stop
                return {"status": "aborted", "op": label, "frame": i, "ack_flags": flags,
                        "sent": sent, "reason": "bad or missing ack — not continuing"}
    result = {"status": "sent", "ops": len(plan), "frames": len(sent), "sent": sent}
    if reader is not None:
        readback = reader()                       # a fresh device read as a DesiredState
        mism = diff_desired(desired, readback)
        result["verify"] = mism
        result["status"] = "verified" if not mism else "verify-failed"
    else:
        result["status"] = "sent-unverified"
    return result
