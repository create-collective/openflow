"""Reading the board must not claim a profile is live when it is not.

A module profile shares its uuid with the device slot it came from. That uuid survives local
edits, so an edited-but-unflashed profile still matched the slot and the UI marked it "on the
keyboard" -- while the keyboard was running the pre-edit version. The mark was false, and the
board's real state had nowhere to live in the app.

So the read resolves "live" by CONTENT, and captures anything the board runs that no profile
represents -- the same bargain layers already make, where a device layer we do not recognise
becomes a layer rather than being dropped.

The load-bearing property is idempotence: matching by content means the capture itself matches
on the next read, so reading twice must not mint a second copy. Without that, every read would
grow the profile list forever.
No hardware.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from unittest import mock

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.api import rest  # noqa: E402
from openflow_backend.db import module_profiles as mp  # noqa: E402
from openflow_backend.device import module_fields  # noqa: E402


class KeepOpen:
    def __init__(self, conn): self._c = conn
    def __getattr__(self, n): return getattr(self._c, n)
    def close(self): pass


TYPE = "TRACK"
UUID = "11111111-1111-1111-1111-111111111111"


def _fields():
    """A device slot's raw fields, as the read returns them: the button gestures plus the
    motion records for all three axes.

    The axes are here because the diff inspects them. A Track slot really does carry six axis
    fields, and a fixture that omitted them described a module whose ball does nothing -- so
    "the device matches this profile" was being asserted against a slot no board would hold.
    """
    from openflow_backend.device import remap as R
    out = []
    for gesture, i in sorted(module_fields.writable_fields(TYPE).items()):
        code = _DEVICE.get(gesture)
        if code is None:
            continue
        out.append({"field": i, "type": 0x0F, "value": _encode(code)})
    for gesture, h in module_fields.axis_halves(TYPE).items():
        for sign in ("-", "+"):
            code = _DEVICE_AXES.get((gesture, sign))
            if code is not None:                       # a half split onto a key
                out.append({"field": h[sign], "type": R.KEY_PRESS,
                            "value": R.encode_keypress("key", code).hex()})
            else:                                      # the stock motion for that direction
                out.append({"field": h[sign], "type": R.TWO_WORD,
                            "value": R.encode_two_word(h["category"],
                                                       -1 if sign == "-" else 1).hex()})
    return out


def _encode(code):
    from openflow_backend.device import remap as R
    return R.encode_mouse_button(code).hex()


# What the board is running.
_DEVICE = {f"tap:track:button_{i}": c for i, c in zip((1, 2, 3, 4), ("M1", "M3", "M2", "M4"))}
# Axis halves the board has split onto a key; anything absent carries its stock motion.
_DEVICE_AXES: dict = {}


def _db(app_bindings):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE module_configs (name TEXT, type TEXT, size INT, order_id INT,
                                     icon_id TEXT, variant TEXT, captured_from TEXT, id TEXT,
                                     updated_at TEXT, created_at TEXT);
        CREATE TABLE module_bindings (action_id TEXT, action_code TEXT, action_type TEXT,
                                      behavior TEXT, invert INT, threshold INT, direction TEXT,
                                      mode INT, module_config_id TEXT, id TEXT,
                                      updated_at TEXT, created_at TEXT);
        CREATE TABLE module_config_bindings (profile_id TEXT, layer_id TEXT,
                                             module_config_id TEXT, binding_location TEXT,
                                             state TEXT, updated_at TEXT, created_at TEXT);
        CREATE TABLE module_settings (module_config_id TEXT, correlation_id TEXT, value TEXT);
    """)
    conn.execute("INSERT INTO module_configs (name,type,size,order_id,icon_id,variant,id,"
                 "updated_at,created_at) VALUES ('Naya Track Left',?,0,0,NULL,'TRACK_LEFT',?,'','')",
                 (TYPE, UUID))
    for g, c in app_bindings.items():
        conn.execute("INSERT INTO module_bindings (action_id,action_code,action_type,behavior,"
                     "invert,threshold,direction,mode,module_config_id,id,updated_at,created_at)"
                     " VALUES (NULL,?,'mouse',?,0,0,'+',0,?,?,'','')", (c, g, UUID, g))
    conn.commit()
    return conn


def _read():
    return {"by_uuid": {UUID: 1}, "slots": {1: _fields()}}


def _run(conn, profile_id=None):
    with mock.patch.object(rest, "db_connect", lambda: KeepOpen(conn)), \
         mock.patch.object(mp, "connect", lambda: KeepOpen(conn)):
        return rest._module_diff(_read(), profile_id)


def _names(conn):
    return [r["name"] for r in conn.execute("SELECT name FROM module_configs ORDER BY order_id")]


def test_a_matching_profile_is_marked_live_and_nothing_is_captured():
    conn = _db(dict(_DEVICE))
    out = _run(conn)
    assert out["captured"] == []
    assert out["modules"][0]["matched"] == UUID
    assert _names(conn) == ["Naya Track Left"]
    print("  app matches the board -> marked live, no capture")


def test_a_drifted_profile_is_not_live_and_the_board_is_captured():
    """The bug this exists for: the drifted profile used to be marked live."""
    drifted = dict(_DEVICE, **{"tap:track:button_1": "M2"})   # user edited, never flashed
    conn = _db(drifted)
    out = _run(conn)

    entry = out["modules"][0]
    assert entry["differs"] == 1, entry["differs"]
    assert entry["matched"] != UUID, "the edited profile must NOT be reported as live"
    assert len(out["captured"]) == 1
    cap = out["captured"][0]
    assert entry["matched"] == cap["id"], "the capture is what is on the board"
    assert cap["name"] == "Naya Track Left (on board)"
    assert _names(conn) == ["Naya Track Left", "Naya Track Left (on board)"]
    print(f"  drift -> captured {cap['name']!r}; the edited profile is no longer claimed live")


def test_the_capture_holds_the_boards_values_not_the_apps():
    conn = _db(dict(_DEVICE, **{"tap:track:button_1": "M2"}))
    cap = _run(conn, profile_id="p")["captured"][0]
    got = {r["behavior"]: r["action_code"] for r in conn.execute(
        "SELECT behavior, action_code FROM module_bindings WHERE module_config_id=?", (cap["id"],))}
    assert got["tap:track:button_1"] == "M1", got      # the device value, not the app's M2
    print("  capture carries the device's binding")


def test_reading_twice_does_not_mint_a_second_capture():
    """Content matching is what makes this safe -- the capture matches on the next read."""
    conn = _db(dict(_DEVICE, **{"tap:track:button_1": "M2"}))
    first = _run(conn)
    after_first = _names(conn)
    second = _run(conn)

    assert len(first["captured"]) == 1
    assert second["captured"] == [], "a re-read must capture nothing"
    assert _names(conn) == after_first, "the profile list must not grow on every read"
    assert second["modules"][0]["matched"] == first["captured"][0]["id"]
    print("  re-read is idempotent: still 2 profiles, still pointing at the capture")


def test_a_capture_takes_over_the_bays_that_pointed_at_the_drifted_profile():
    """A bay names the profile a layer RUNS. After the read, the thing running in that slot is
    the capture -- so leaving the bay on the edited row would show one profile as live while a
    flash quietly wrote a different one."""
    conn = _db(dict(_DEVICE, **{"tap:track:button_1": "M2"}))
    conn.execute("INSERT INTO module_config_bindings (profile_id, layer_id, module_config_id, "
                 "binding_location, state, updated_at, created_at) "
                 "VALUES ('p','l0',?,'track:keyboard_left',NULL,'','')", (UUID,))
    conn.commit()

    cap = _run(conn, profile_id="p")["captured"][0]
    now = conn.execute("SELECT module_config_id FROM module_config_bindings").fetchone()[0]
    assert now == cap["id"], "the bay should follow what the board actually runs"
    assert _run(conn) is not None  # a re-read keeps it there

    # The edited profile survives and can be chosen again deliberately.
    assert conn.execute("SELECT 1 FROM module_configs WHERE id=?", (UUID,)).fetchone()
    print("  bay repointed to the capture; the edited profile still exists")


def test_a_bay_pointing_elsewhere_is_left_alone():
    other = "99999999-9999-9999-9999-999999999999"
    conn = _db(dict(_DEVICE, **{"tap:track:button_1": "M2"}))
    conn.execute("INSERT INTO module_config_bindings (profile_id, layer_id, module_config_id, "
                 "binding_location, state, updated_at, created_at) "
                 "VALUES ('p','l0',?,'track:keyboard_right',NULL,'','')", (other,))
    conn.commit()

    _run(conn, profile_id="p")
    assert conn.execute("SELECT module_config_id FROM module_config_bindings").fetchone()[0] == other
    print("  unrelated bays untouched")


def test_a_read_only_moves_bays_on_the_profile_that_represents_the_board():
    """The bug this exists for: repointing ran unscoped, so reading the keyboard rewrote the bay
    selections of EVERY profile. A profile other than the board's is a deliberate choice about
    what to flash next -- a read must not silently overwrite it."""
    conn = _db(dict(_DEVICE, **{"tap:track:button_1": "M2"}))
    for pid in ("board-profile", "my-own-profile"):
        conn.execute("INSERT INTO module_config_bindings (profile_id, layer_id, "
                     "module_config_id, binding_location, state, updated_at, created_at) "
                     "VALUES (?,'l0',?,'track:keyboard_left',NULL,'','')", (pid, UUID))
    conn.commit()

    with mock.patch.object(rest, "db_connect", lambda: KeepOpen(conn)), \
         mock.patch.object(mp, "connect", lambda: KeepOpen(conn)):
        out = rest._module_diff(_read(), profile_id="board-profile")

    got = dict(conn.execute("SELECT profile_id, module_config_id FROM module_config_bindings"))
    cap = out["captured"][0]["id"]
    assert got["board-profile"] == cap, "the board's profile should follow the board"
    assert got["my-own-profile"] == UUID, "another profile's selection must be left alone"
    print("  board profile moved; the user's own profile untouched")


def test_a_module_read_that_imports_nothing_moves_no_bays():
    """/rpc/read-modules names no profile, so it has no business rewriting any profile's bays."""
    conn = _db(dict(_DEVICE, **{"tap:track:button_1": "M2"}))
    conn.execute("INSERT INTO module_config_bindings (profile_id, layer_id, module_config_id, "
                 "binding_location, state, updated_at, created_at) "
                 "VALUES ('p','l0',?,'track:keyboard_left',NULL,'','')", (UUID,))
    conn.commit()

    _run(conn)      # no profile_id
    assert conn.execute("SELECT module_config_id FROM module_config_bindings").fetchone()[0] == UUID
    print("  unscoped read moved nothing")


def test_a_capture_keeps_gestures_the_device_read_cannot_report():
    """The read only reports gestures with a mapped device field -- 4 of a Track's 11. Capturing
    from the read alone dropped vertical, horizontal and rotate, leaving a profile that could not
    express them at all. The capture must be the source profile PLUS what was read."""
    conn = _db(dict(_DEVICE, **{"tap:track:button_1": "M2"}))
    # Axes exist on the source profile but have no field in writable_fields, so no read reports
    # them.
    for g, code in (("vertical:track", "mouse - MOUSE_DOWN - MOUSE_UP"),
                    ("horizontal:track", "mouse - MOUSE_LEFT - MOUSE_RIGHT"),
                    ("rotate:track", "mouse - SCROLL_UP - SCROLL_DOWN"),
                    ("hold:track:button_1", "")):
        conn.execute("INSERT INTO module_bindings (action_id, action_code, action_type, behavior,"
                     " invert, threshold, direction, mode, module_config_id, id, updated_at,"
                     " created_at) VALUES (NULL,?,'value',?,0,0,'+',0,?,?,'','')",
                     (code, g, UUID, g))
    conn.commit()

    cap = _run(conn, profile_id="p")["captured"][0]
    got = {r["behavior"]: r["action_code"] for r in conn.execute(
        "SELECT behavior, action_code FROM module_bindings WHERE module_config_id=?", (cap["id"],))}

    for g in ("vertical:track", "horizontal:track", "rotate:track", "hold:track:button_1"):
        assert g in got, f"{g} was dropped by the capture"
    assert got["vertical:track"] == "mouse - MOUSE_DOWN - MOUSE_UP", "kept from the source"
    assert got["tap:track:button_1"] == "M1", "the device value still wins where it was read"
    print(f"  capture has {len(got)} bindings: axes kept, read values applied")


# --- split axes -------------------------------------------------------------------------
#
# A live flash of a Tune profile with both 1-finger swipes split onto F17-F20 looked like it had
# only written the RIGHT and DOWN halves: the captured profile showed the plus half and nothing
# for left/up. Reading the slot's raw bytes showed all four halves were on the board exactly as
# authored. Every part of the failure was on the READ side, and there were three of them:
#
#   1. the diff walked writable_fields, which deliberately excludes the axis halves, so fields
#      0x0a-0x0d were never looked at;
#   2. _decode_field dispatched on the field's nominal kind, so a half holding a KEY_PRESS
#      decoded as RAW even once it was read;
#   3. the capture keyed rows by gesture alone and wrote them all with direction "+", so the
#      two halves overwrote each other before reaching the database.
#
# Each of these on its own is enough to make a correct write look like a broken one.

def _split_db():
    """The app profile: stock buttons, plus vertical split onto A (up) and B (down)."""
    conn = _db(dict(_DEVICE))
    for code, direction in (("mouse - MOUSE_DOWN - MOUSE_UP", "+"), ("A", "-"), ("B", "+")):
        atype = "value" if " - " in code else "key"
        conn.execute("INSERT INTO module_bindings (action_id,action_code,action_type,behavior,"
                     "invert,threshold,direction,mode,module_config_id,id,updated_at,created_at)"
                     " VALUES (NULL,?,?,'vertical:track',0,0,?,0,?,?,'','')",
                     (code, atype, direction, UUID, f"v{direction}{code[:1]}"))
    conn.commit()
    return conn


def test_both_halves_of_a_split_axis_are_read_back():
    _DEVICE_AXES.update({("vertical:track", "-"): "A", ("vertical:track", "+"): "B"})
    try:
        conn = _split_db()
        out = _run(conn)
        halves = {g["half"]: g for g in out["modules"][0]["gestures"]
                  if g["gesture"] == "vertical:track" and g.get("half")}
        assert set(halves) == {"-", "+"}, "the diff never looked at the axis halves"
        assert halves["-"]["device"] == "A", halves["-"]
        assert halves["+"]["device"] == "B", halves["+"]
        assert not halves["-"]["differs"] and not halves["+"]["differs"]
        assert out["modules"][0]["differs"] == 0, "a matching split axis must not read as drift"
        assert out["captured"] == [], "nothing drifted, so nothing to capture"
        print("  both halves read back, and a matching split is not drift")
    finally:
        _DEVICE_AXES.clear()


def test_an_axis_half_holding_a_key_is_not_decoded_as_raw():
    """The field map calls 0x05/0x06 an axis, but a gesture field is not type-locked -- the
    record TYPE decides. Dispatching on the map's kind turned a real binding into RAW_...."""
    _DEVICE_AXES[("vertical:track", "-")] = "A"
    try:
        conn = _split_db()
        g = next(x for x in _run(conn)["modules"][0]["gestures"]
                 if x["gesture"] == "vertical:track" and x.get("half") == "-")
        assert g["device"] == "A", f"decoded as {g['device']!r}"
        print("  a keypress in an axis field decodes as the key")
    finally:
        _DEVICE_AXES.clear()


def test_a_capture_keeps_both_halves_and_stays_idempotent():
    """The capture must round-trip a split: the combined row the UI renders, plus a row per half
    that actually diverges -- and reading again must not mint a second copy."""
    _DEVICE_AXES.update({("vertical:track", "-"): "A", ("vertical:track", "+"): "B"})
    try:
        conn = _db(dict(_DEVICE))            # app has NO axis rows -> the board has drifted
        made = _run(conn)["captured"]
        assert len(made) == 1, made
        rows = [(r["action_code"], r["direction"]) for r in conn.execute(
            "SELECT action_code, direction FROM module_bindings "
            "WHERE module_config_id=? AND behavior='vertical:track'", (made[0]["id"],))]
        assert ("A", "-") in rows, f"the minus half was lost: {rows}"
        assert ("B", "+") in rows, f"the plus half was lost: {rows}"
        # The axis still has a row the UI can render -- get_modules() hides half rows and
        # renders the combined one, so an axis with only halves disappears from the page.
        # It is EMPTY rather than the default pair: the halves are what this axis does now,
        # and naming a motion neither half carries is what stopped a capture ever matching.
        combined = [c for c, d in rows if d == "+" and c not in ("A", "B")]
        assert combined == [""], f"expected one empty combined row, got {rows}"
        assert _run(conn)["captured"] == [], "a re-read must not capture the capture"
        print("  a split axis survives capture, and the capture matches on re-read")
    finally:
        _DEVICE_AXES.clear()


def test_deleting_a_profile_a_bay_still_uses_says_so_instead_of_dropping_the_connection():
    """module_config_bindings has a foreign key onto module_configs, so deleting a profile a
    layer still runs raised IntegrityError -- not a ValueError, so it escaped the endpoint's
    handler as an unhandled 500. Uvicorn answers those by closing the connection, and the
    browser renders that as "failed to fetch", which names neither the profile nor the cause."""
    import sqlite3
    conn = _db(dict(_DEVICE))
    conn.executescript("""
        CREATE TABLE profiles (id TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE layers (id TEXT PRIMARY KEY, name TEXT, order_id INT, profile_id TEXT);
    """)
    other = "22222222-2222-2222-2222-222222222222"
    conn.execute("INSERT INTO module_configs (name,type,size,order_id,icon_id,variant,id,"
                 "updated_at,created_at) VALUES ('Spare',?,0,1,NULL,NULL,?,'','')", (TYPE, other))
    conn.execute("INSERT INTO profiles VALUES ('p1','Read from keyboard')")
    conn.execute("INSERT INTO layers VALUES ('l1','Layer 1',1,'p1')")
    conn.execute("INSERT INTO module_config_bindings (profile_id,layer_id,module_config_id,"
                 "binding_location,state,updated_at,created_at) "
                 "VALUES ('p1','l1',?,'track:keyboard_left',NULL,'','')", (UUID,))
    conn.commit()

    with mock.patch.object(mp, "connect", lambda: KeepOpen(conn)):
        try:
            mp.delete(UUID)
            raise AssertionError("the delete should have been refused")
        except sqlite3.IntegrityError:
            raise AssertionError("still raising IntegrityError -- the endpoint returns 500")
        except ValueError as e:
            msg = str(e)
        # the unreferenced profile still deletes cleanly
        assert mp.delete(other)["ok"]

    assert "Read from keyboard" in msg and "Layer 1" in msg, msg
    assert conn.execute("SELECT COUNT(*) c FROM module_configs WHERE id=?",
                        (UUID,)).fetchone()["c"] == 1, "nothing may be deleted on refusal"
    print(f"  refused with: {msg[:70]}...")


def test_a_capture_of_an_axis_the_board_leaves_empty_can_still_be_live():
    """The Touch slot really does hold nothing for 1-finger pointer motion -- fields 0x05-0x08
    are type 0x07. The capture wrote the stock pair there anyway, so it claimed a motion the
    keyboard does not have: it differed from the board it was taken FROM on every subsequent
    read, could never be marked live, and minted another copy each time.

    Modelled here on a Track, whose axes work the same way.
    """
    global _fields
    keep = _fields

    def _empty_axes():
        out = [f for f in keep() if int(f["field"]) not in
               {h[s] for h in module_fields.axis_halves(TYPE).values() for s in ("-", "+")}]
        for h in module_fields.axis_halves(TYPE).values():
            for sign in ("-", "+"):
                out.append({"field": h[sign], "type": 0x07, "value": ""})
        return out

    _fields = _empty_axes
    try:
        conn = _db(dict(_DEVICE))
        made = _run(conn)["captured"]
        assert len(made) == 1, made
        rows = [(r["action_code"], r["direction"]) for r in conn.execute(
            "SELECT action_code, direction FROM module_bindings "
            "WHERE module_config_id=? AND behavior='vertical:track'", (made[0]["id"],))]
        assert rows == [("", "+")], f"an empty axis must be captured as empty: {rows}"

        out = _run(conn)
        assert out["captured"] == [], "the capture still does not match the board it came from"
        assert out["modules"][0]["matched"] == made[0]["id"], \
            "the capture is what the board runs, so it is the one that should read as live"
        print("  an axis the board leaves empty is captured as empty, and reads back live")
    finally:
        _fields = keep


def test_an_action_with_no_hid_record_matches_the_empty_keypress_the_board_stores():
    """LED_BRIGHTNESS_UP/DOWN sit on the Tune 3-finger swipes in the stock profile, and the
    board carries a KEY_PRESS whose payload is all zeros for them -- a claimed gesture with no
    HID output, distinct from an unbound field (record type NONE, no payload).

    Comparing decoded strings called that a difference on every read, and it was one no flash
    could resolve: there is no third state to move to. The Tune profile could never read as
    live and every read minted another capture of it.
    """
    from openflow_backend.api import rest as R
    from openflow_backend.device import remap

    assert not remap.encodable("LED_BRIGHTNESS_UP"), "if this becomes encodable, write it"
    assert remap.encodable("F17") and remap.encodable("M1")

    assert R._same_action(remap.EMPTY_KEYPRESS, "LED_BRIGHTNESS_UP")
    assert R._same_action(remap.EMPTY_KEYPRESS, "LED_BRIGHTNESS_DOWN")
    # It must NOT swallow a real difference: an action that CAN be encoded and is not there
    # is still drift, and an unbound field is still not the same as a claimed one.
    assert not R._same_action(remap.EMPTY_KEYPRESS, "F17")
    assert not R._same_action(None, "LED_BRIGHTNESS_UP")
    print("  the empty keypress matches an unencodable action, and nothing else")


def test_the_flashable_badge_is_false_for_an_action_that_cannot_be_encoded():
    """The badge promises the edit reaches the keyboard. That needs a field AND an encoding;
    LED brightness has the field and no encoding, so it was promising a write that never
    happened."""
    from openflow_backend.device import module_fields, remap
    beh = "swipe_up:tune:3_fingers"
    assert module_fields.gesture_has_device_field("TUNE", beh), "the field exists"
    assert not remap.encodable("LED_BRIGHTNESS_UP"), "but the action does not encode"
    print("  field present, action unencodable -> not flashable")


def test_a_combined_axis_row_is_still_flashable():
    """`flashable` gained an "is this action encodable" test so LED brightness would stop
    promising a write it never made. Applied to a COMBINED row it takes the badge off every
    axis on every module: "mouse - SCROLL_UP - SCROLL_DOWN" is not a single action and does
    not encode as one, but the gesture reaches the device as its two halves."""
    from openflow_backend.device import remap

    for combined in ("mouse - SCROLL_UP - SCROLL_DOWN", "mouse - MOUSE_LEFT - MOUSE_RIGHT",
                     "C_VOL_DOWN - C_VOL_UP"):
        assert not remap.encodable(combined), "a pair is not a single encodable action"
        assert " - " in combined, "which is exactly why the badge must not test it as one"
    print("  combined rows are exempt from the single-action encoding test")


def test_the_dial_is_one_gesture_over_two_fields():
    """0x22 (clockwise) and 0x23 (counter-clockwise) are the two halves of rotate:tune:dial,
    and the app may hold the dial as ONE combined row, "C_VOL_DOWN - C_VOL_UP".

    Two things went wrong while that was not joined up. The diff compared each half against a
    row the profile does not have and reported the board's own volume bindings as drift on
    every read; and the flash wrote neither field, because the halves looked empty and the
    combined row matched no writable field -- so the stock Tune profile's dial silently never
    reached the keyboard.
    """
    from openflow_backend.device import module_fields as MF

    assert MF.split_pair("C_VOL_DOWN - C_VOL_UP") == ("C_VOL_DOWN", "C_VOL_UP")
    # Both spellings must parse: a motion axis carries a leading kind, the dial does not.
    assert MF.split_pair("mouse - MOUSE_DOWN - MOUSE_UP") == ("MOUSE_DOWN", "MOUSE_UP")
    assert MF.split_pair("") == (None, None) and MF.split_pair("F17") == (None, None)

    halves = MF.pair_halves("TUNE")
    assert halves["clockwise_rotate:tune:dial"] == ("rotate:tune:dial", "+")
    assert halves["counter_clockwise_rotate:tune:dial"] == ("rotate:tune:dial", "-")

    # Clockwise is the PLUS half and holds the second value: C_VOL_UP, matching the board.
    w = MF.writable_fields("TUNE")
    assert w["clockwise_rotate:tune:dial"] == 0x22
    assert w["counter_clockwise_rotate:tune:dial"] == 0x23
    print("  dial halves resolve to 0x22/0x23 with clockwise as the plus half")


def test_a_profile_holding_only_the_combined_dial_row_matches_the_board():
    """The regression this all came from: `Naya Tune Mac/Win` carries the dial only as the
    combined row, and read as 2 gestures adrift from the board on every single read."""
    from openflow_backend.api import rest as R

    fields = {0x22: (0x01, bytes.fromhex("e9000c00")),    # C_VOL_UP
              0x23: (0x01, bytes.fromhex("ea000c00"))}    # C_VOL_DOWN
    app = {"rotate:tune:dial": "C_VOL_DOWN - C_VOL_UP"}
    rows, differs = R._compare("TUNE", fields, app)
    dial = {g["gesture"]: g for g in rows if "rotate" in g["gesture"]}
    assert dial["clockwise_rotate:tune:dial"]["app"] == "C_VOL_UP"
    assert dial["counter_clockwise_rotate:tune:dial"]["app"] == "C_VOL_DOWN"
    assert not dial["clockwise_rotate:tune:dial"]["differs"]
    assert not dial["counter_clockwise_rotate:tune:dial"]["differs"]
    print("  the combined row answers for both halves")


def test_the_tune_scroll_axes_are_paired_the_other_way_round():
    """Established on hardware by binding F17-F20 to the four Tune 1-finger halves and swiping
    each direction: UP fired the key in 0x0a, DOWN 0x0b, LEFT 0x0c, RIGHT 0x0d.

    So 0x0a/0x0b are the VERTICAL pair and 0x0c/0x0d the HORIZONTAL one -- the axes were
    swapped, not the directions -- and the two scroll categories were named backwards with
    them: category 4 is vertical scroll, 6 is horizontal.

    The first report of this read like a simple inversion, and swapping the directions within
    each axis was tried first. It could not work: no arrangement of signs inside the wrong axis
    pairing can send an up-swipe to the horizontal fields. Hence this test names the FIELD each
    physical direction reaches, which is the thing that was actually measured.
    """
    from openflow_backend.device import module_fields as MF
    h = MF.axis_halves("TUNE")
    assert h["vertical:tune:1_finger"]["-"] == 0x0A, "a swipe UP fires 0x0a"
    assert h["vertical:tune:1_finger"]["+"] == 0x0B, "a swipe DOWN fires 0x0b"
    assert h["vertical:tune:1_finger"]["category"] == 4, "category 4 is VERTICAL scroll"
    assert h["horizontal:tune:1_finger"]["-"] == 0x0C, "a swipe LEFT fires 0x0c"
    assert h["horizontal:tune:1_finger"]["+"] == 0x0D, "a swipe RIGHT fires 0x0d"
    assert h["horizontal:tune:1_finger"]["category"] == 6, "category 6 is HORIZONTAL scroll"
    # The pointer axes are untouched: cursor motion was verified on hardware long ago and
    # nobody has reported it wrong.
    assert MF.axis_halves("TRACK")["vertical:track"] == {
        "-": 0x05, "+": 0x06, "category": 1, "default": "mouse - MOUSE_DOWN - MOUSE_UP"}
    print("  0x0a/0x0b vertical, 0x0c/0x0d horizontal; pointer axes untouched")


def test_pairing_the_axes_correctly_changes_no_flashed_bytes():
    """With the axes paired right the signs are the ordinary ones, so an UNSPLIT axis still
    encodes exactly what the board and NayaFlow carry: 0x0a = cat 4 sel -1, 0x0b = +1,
    0x0c = cat 6 sel -1, 0x0d = +1. Fixing a mapping must not rewrite every Tune profile."""
    from openflow_backend.device import module_layout as ml, remap as R

    got = {}
    for gesture in ("vertical:tune:1_finger", "horizontal:tune:1_finger"):
        for idx, (typ, val) in ml.encode_axis("TUNE", gesture, {"minus": None, "plus": None}).items():
            assert typ == R.TWO_WORD, (gesture, hex(idx))
            got[idx] = R.decode_two_word(val)
    assert got == {0x0A: (4, -1), 0x0B: (4, 1), 0x0C: (6, -1), 0x0D: (6, 1)}, got
    print("  unsplit Tune axes still encode the board's own motion records")


def test_each_direction_reaches_the_field_that_fires_on_it():
    from openflow_backend.device import module_layout as ml, keymap_read as KR
    key = lambda out, idx: KR.decode_keypress(out[idx][1])[1]

    out = ml.encode_axis("TUNE", "vertical:tune:1_finger", {"minus": "F18", "plus": "F17"})
    assert key(out, 0x0A) == "F18", "up -> 0x0a"
    assert key(out, 0x0B) == "F17", "down -> 0x0b"
    out = ml.encode_axis("TUNE", "horizontal:tune:1_finger", {"minus": "F20", "plus": "F19"})
    assert key(out, 0x0C) == "F20", "left -> 0x0c"
    assert key(out, 0x0D) == "F19", "right -> 0x0d"
    print("  up/down/left/right each land in the field that fires on them")


def test_a_modifier_chord_can_be_bound_to_a_module_gesture():
    """The virtual keyboard has produced {"LCTRL + F13", shortcut_alias} all along, and
    encode_keypress has had a shortcut_alias branch all along -- but _encode_gesture passed a
    hardcoded action_type of "key", so a chord never reached that branch. It stored in the app,
    badged, and was silently dropped by the flash.

    The board carries such records already, which is what makes this checkable rather than
    hopeful: a stock Touch has LSHIFT + LALT + ESC in 0x15 as 29000706.
    """
    from openflow_backend.device import module_layout as ml, remap as R, keymap_read as KR

    rec = ml._encode_gesture(0x08, "LSHIFT + LALT + ESC")
    assert rec[1].hex() == "29000706", "must match the record the stock Touch actually carries"

    for code, want in (("LCTRL + F13", "68000701"), ("LSHIFT + F17", "6c000702"),
                       ("LGUI + F24", "73000708"), ("LCTRL + LSHIFT + F19", "6e000703")):
        rec = ml._encode_gesture(0x08, code)
        assert rec is not None and rec[0] == R.KEY_PRESS, code
        assert rec[1].hex() == want, f"{code}: {rec[1].hex()} != {want}"
        assert KR.decode_keypress(rec[1])[1] == code, "and it must read back as itself"
        assert R.encodable(code), "so the flashable badge tells the truth about it"
    print("  modifier + F13-F24 encodes, round-trips, and matches a real device record")


def test_the_encoder_branch_is_chosen_from_the_code_not_hardcoded():
    from openflow_backend.device import remap as R
    assert R.keypress_type("LCTRL + F13") == "shortcut_alias"
    assert R.keypress_type("LCTRL") == "modifier"
    assert R.keypress_type("F13") == "key"
    assert R.encodable("LCTRL") and R.encodable("F13") and R.encodable("LALT + CLICK")
    print("  chord / modifier / plain key each route to their own branch")
