"""A read brings a module's SETTINGS back, not only its gestures.

Until 2026-09-11 "Read from keyboard" captured a slot's gesture bindings and nothing else: the
speed, acceleration and tick fields were never decoded, a captured profile carried no settings
rows, and the Modules page showed the app's defaults whatever the board held. The bytes below
are the reference board's own slots, read that morning: every module at pointer speed 10, accel
50, accel on; a Touch at scroll speed 50 where a Track or Tune holds 10; the Tune adding tick
strength 75 and ticks on. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.api import rest                                   # noqa: E402
from openflow_backend.db import module_profiles as mp                   # noqa: E402
from openflow_backend.device import module_fields as MF, module_layout as ML  # noqa: E402
from test_module_capture import KeepOpen, _db, _fields                  # noqa: E402
from test_module_content_match import _read                             # noqa: E402

ONE = 0x01
# slot 4, the docked Touch (fields 0x00-0x04); 0x05-0x07 are its locked one-finger axes, empty
TOUCH = {0: (ONE, b"\x0a"), 1: (ONE, b"\x32"), 2: (ONE, b"\x32"), 3: (ONE, b"\x01"), 4: (ONE, b"\x00"),
         5: (0x07, b""), 6: (0x07, b""), 7: (0x07, b"")}
# slot 1, the docked Tune: tick spacing 5 at 0x05 (identity uncertain, not a setting we write),
# tick strength 75 at 0x06, ticks on at 0x07
TUNE = {0: (ONE, b"\x0a"), 1: (ONE, b"\x0a"), 2: (ONE, b"\x32"), 3: (ONE, b"\x01"), 4: (ONE, b"\x00"),
        5: (ONE, b"\x05"), 6: (ONE, b"\x4b"), 7: (ONE, b"\x01")}
# slot 2, a Track: 0x05-0x07 hold axis two-word records, which are NOT settings
TRACK = {0: (ONE, b"\x0a"), 1: (ONE, b"\x0a"), 2: (ONE, b"\x32"), 3: (ONE, b"\x01"), 4: (ONE, b"\x00"),
         5: (0x0F, bytes.fromhex("01000000ffffffff")), 6: (0x0F, bytes.fromhex("0100000001000000")),
         7: (0x0F, bytes.fromhex("00000000ffffffff"))}


def test_the_boards_own_slots_decode_to_the_apps_setting_values():
    assert MF.decode_settings("TOUCH", TOUCH) == {"pointer_speed": 10, "scroll_speed": 50,
                                                  "pointer_accel": 50, "pointer_accel_on": True}
    assert MF.decode_settings("TUNE", TUNE) == {"pointer_speed": 10, "scroll_speed": 10,
                                                "pointer_accel": 50, "pointer_accel_on": True,
                                                "tick_strength": 75, "toggle_ticks": True}
    assert MF.decode_settings("TRACK", TRACK) == {"pointer_speed": 10, "scroll_speed": 10,
                                                  "pointer_accel": 50, "pointer_accel_on": True}


def test_only_a_one_byte_record_counts_as_a_setting():
    """A Track's axis two-words sit in 0x05-0x07 and an undocked Touch leaves them empty;
    neither is a value, and neither may be reported as one."""
    assert "tick_strength" not in MF.decode_settings("TRACK", TRACK)
    assert MF.decode_settings("TOUCH", {}) == {}
    assert MF.decode_settings("TOUCH", {0: (ONE, b"\x0a\x00")}) == {}, "two bytes is not a setting"


def test_decode_is_the_inverse_of_the_flash_encoder():
    for mtype, fields in (("TOUCH", TOUCH), ("TUNE", TUNE), ("TRACK", TRACK)):
        idx = MF.setting_fields(mtype)
        for sid, value in MF.decode_settings(mtype, fields).items():
            assert ML.encode_setting(value) == fields[idx[sid]], (mtype, sid)


def test_drift_is_reported_against_the_profile_or_its_default():
    rows = {r["id"]: r for r in rest._settings_rows("TUNE", TUNE, stored={})}
    # The app's default scroll speed is 50; this Tune holds 10.
    assert rows["scroll_speed"]["device"] == 10 and rows["scroll_speed"]["app"] == 50
    assert rows["scroll_speed"]["differs"] is True
    assert rows["pointer_speed"]["differs"] is False and rows["toggle_ticks"]["differs"] is False
    assert rows["tick_strength"]["app"] == 75 and rows["tick_strength"]["differs"] is False
    # A stored value is compared as the app stores it (a string), typed like the device's.
    rows = {r["id"]: r for r in rest._settings_rows("TUNE", TUNE, stored={"scroll_speed": "10",
                                                                          "toggle_ticks": "false"})}
    assert rows["scroll_speed"]["differs"] is False
    assert rows["toggle_ticks"]["differs"] is True and rows["toggle_ticks"]["app"] is False


def _read_with_settings(extra_fields):
    read = _read()
    slot = next(iter(read["slots"]))
    read["slots"][slot] = list(_fields()) + [
        {"field": i, "type": t, "value": v.hex()} for i, (t, v) in extra_fields.items()]
    return read


def test_the_read_entry_carries_the_settings_beside_the_gestures():
    from test_module_capture import _DEVICE
    conn = _db(dict(_DEVICE))
    with mock.patch.object(rest, "db_connect", lambda: KeepOpen(conn)):
        e = rest._build_entries(_read_with_settings(TRACK))[0]
    got = {r["id"]: r["device"] for r in e["settings"]}
    assert got == {"pointer_speed": 10, "scroll_speed": 10, "pointer_accel": 50, "pointer_accel_on": True}
    assert e["settingsDiffer"] == 1, "scroll speed 10 against the default 50"
    assert e["differs"] == 0, "settings do not take part in the content match"


def test_a_capture_imports_the_devices_setting_values():
    """A slot whose gestures match no profile is captured -- and now its settings come along."""
    from test_module_capture import _DEVICE
    app = dict(_DEVICE)
    app["tap:track:button_1"], app["tap:track:button_2"] = app["tap:track:button_2"], app["tap:track:button_1"]
    conn = _db(app)                                    # the app's profile differs -> capture
    with mock.patch.object(rest, "db_connect", lambda: KeepOpen(conn)), \
         mock.patch.object(mp, "connect", lambda: KeepOpen(conn)):
        out = rest._module_diff(_read_with_settings(TRACK), None)
    captured = [m for m in out["modules"] if m.get("matched")]
    assert captured, out["modules"]
    cid = captured[0]["matched"]
    rows = {r["correlation_id"]: r["value"] for r in conn.execute(
        "SELECT correlation_id, value FROM module_settings WHERE module_config_id=?", (cid,))}
    assert rows == {"pointer_speed": "10", "scroll_speed": "10", "pointer_accel": "50",
                    "pointer_accel_on": "true"}
