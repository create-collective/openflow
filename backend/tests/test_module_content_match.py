"""A module slot is matched by CONTENT, never by uuid -- including a uuid the app has never seen.

Every NayaFlow install writes its own uuids into the board's module-config list. On 2026-09-08 a
fresh NayaFlow flashed the reference board and, from then on, not one slot uuid matched anything
in OpenFlow's database. The read reported all four slots as "unknown", imported nothing, and
showed no profile as live -- while the bindings on the board were byte for byte the app's own
stock profiles. The uuid must decide nothing: the list's type byte says what a slot IS, and the
content decides which profile it matches. If nothing matches, the board's config is captured,
templated from the closest profile of its type.

Reuses the Track fixture from test_module_capture so the two files describe the same board.
No hardware.
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

from openflow_backend.api import rest  # noqa: E402
from openflow_backend.db import module_profiles as mp  # noqa: E402
from openflow_backend.device import module_layout, remap as R  # noqa: E402
from test_module_capture import _DEVICE, KeepOpen, UUID as APP_UUID, _db, _fields, _names  # noqa: E402

# What a foreign NayaFlow install wrote into the list for this slot.
FOREIGN = "8e5650ef-7f03-4292-8781-6fd090783560"
SLOT = 3


def _list(type_code: int) -> str:
    """A one-entry module list naming the slot's type, as READ_MODULE_CONFIG_LIST returns it."""
    return R.encode_module_config_list([(SLOT, SLOT, type_code, R.layer_uuid_bytes(FOREIGN))]).hex()


def _read(type_code=module_layout.MODULE_TYPE_CODE["TRACK"], with_list=True):
    read = {"by_uuid": {FOREIGN: SLOT}, "slots": {SLOT: _fields()}}
    if with_list:
        read["list"] = _list(type_code)
    return read


def _run(conn, read, profile_id=None):
    with mock.patch.object(rest, "db_connect", lambda: KeepOpen(conn)), \
         mock.patch.object(mp, "connect", lambda: KeepOpen(conn)):
        return rest._module_diff(read, profile_id)


def _entries(conn, read):
    """The slot entries BEFORE any capture -- _module_diff rebuilds them after capturing."""
    with mock.patch.object(rest, "db_connect", lambda: KeepOpen(conn)):
        return rest._build_entries(read)


def test_the_list_byte_types_a_slot():
    assert rest._list_types(_list(1)) == {SLOT: "TRACK"}
    assert rest._list_types(_list(0)) == {SLOT: "TOUCH"}
    assert rest._list_types(None) == {}
    assert rest._list_types(_list(7)) == {}, "an unrecognised code must not be guessed at"
    print("  list byte -> type: 0 Touch, 1 Track; unknown codes ignored")


def test_a_foreign_uuid_with_identical_content_is_live_and_captures_nothing():
    conn = _db(dict(_DEVICE))
    out = _run(conn, _read())
    e = out["modules"][0]
    assert not e.get("unknown"), e
    assert e["foreign"] is True
    assert e["type"] == "TRACK" and e["name"] == "Naya Track Left"
    assert e["differs"] == 0
    assert e["matched"] == APP_UUID, "identical bindings under a different uuid ARE a match"
    assert e["matchedName"] == "Naya Track Left" and e["matchedGestures"]
    assert out["captured"] == []
    assert _names(conn) == ["Naya Track Left"]
    print("  foreign uuid, same bindings -> the stock profile is live, nothing minted")


def test_a_foreign_uuid_with_different_content_is_captured_from_the_closest_profile():
    conn = _db(dict(_DEVICE, **{"tap:track:button_1": "M2"}))     # app differs from the board
    before = _entries(conn, _read())[0]
    assert before["foreign"] is True and before["differs"] == 1 and before["matched"] is None
    assert before["templateId"] == APP_UUID, "the closest Track profile is the template"
    assert before["name"] == "Naya Track Left"

    out = _run(conn, _read())
    e = out["modules"][0]
    assert len(out["captured"]) == 1
    cap = out["captured"][0]
    assert cap["name"] == "Naya Track Left (on board)" and cap["type"] == "TRACK"
    assert cap["capturedFrom"] == FOREIGN, "provenance is the DEVICE uuid, for the flash to claim the slot"
    assert e["matched"] == cap["id"] and e["differs"] == 0, "after capture the entry is the capture"
    got = {r["behavior"]: r["action_code"] for r in conn.execute(
        "SELECT behavior, action_code FROM module_bindings WHERE module_config_id=?", (cap["id"],))}
    assert got["tap:track:button_1"] == "M1", got            # the board's value, not the app's
    # Templated from the closest profile: every gesture the template had is present, not just the
    # four the read can see.
    template_rows = {r[0] for r in conn.execute(
        "SELECT behavior FROM module_bindings WHERE module_config_id=?", (APP_UUID,))}
    assert template_rows <= set(got), "capture lost gestures the template carried"
    print(f"  foreign uuid, drifted -> captured {cap['name']!r} from the closest Track profile")


def test_reading_a_foreign_slot_twice_is_idempotent():
    conn = _db(dict(_DEVICE, **{"tap:track:button_1": "M2"}))
    first = _run(conn, _read())
    names = _names(conn)
    second = _run(conn, _read())
    assert len(first["captured"]) == 1 and second["captured"] == []
    assert _names(conn) == names
    assert second["modules"][0]["matched"] == first["captured"][0]["id"]
    print("  re-read matches the capture; the profile list does not grow")


def test_without_a_list_a_foreign_uuid_is_still_unknown():
    conn = _db(dict(_DEVICE))
    out = _run(conn, _read(with_list=False))
    assert out["modules"][0].get("unknown") is True
    assert out["captured"] == [] and _names(conn) == ["Naya Track Left"]
    print("  no list -> no type -> reported unknown, nothing guessed")


def test_an_unrecognised_type_code_is_unknown():
    conn = _db(dict(_DEVICE))
    out = _run(conn, _read(type_code=7))
    assert out["modules"][0].get("unknown") is True and out["captured"] == []
    print("  type byte 7 -> unknown")


def test_a_type_with_no_profile_in_the_app_is_captured_from_nothing():
    conn = _db(dict(_DEVICE))
    conn.execute("DELETE FROM module_bindings")
    conn.execute("DELETE FROM module_configs")
    conn.commit()
    before = _entries(conn, _read())[0]
    assert not before.get("unknown") and before["type"] == "TRACK" and before["name"] == "Track module"
    assert before["templateId"] is None and before["matched"] is None
    out = _run(conn, _read())
    cap = out["captured"][0]
    assert cap["name"] == "Track module (on board)"
    assert out["modules"][0]["matched"] == cap["id"]
    got = {r["behavior"]: r["action_code"] for r in conn.execute(
        "SELECT behavior, action_code FROM module_bindings WHERE module_config_id=?", (cap["id"],))}
    assert got["tap:track:button_1"] == "M1"
    print("  no Track profile at all -> 'Track module (on board)' holding the read values")


def test_a_content_match_stamps_provenance_so_a_flash_claims_the_slot():
    """The flash planner claims a slot through captured_from. A stock profile that the board
    turned out to be running must get that link, or the next flash allocates a new slot and
    strands the one NayaFlow wrote."""
    conn = _db(dict(_DEVICE))
    _run(conn, _read(), profile_id="p")
    got = conn.execute("SELECT captured_from FROM module_configs WHERE id=?", (APP_UUID,)).fetchone()[0]
    assert got == FOREIGN, got
    print("  matched stock profile now carries the device uuid as captured_from")


def test_a_known_uuid_behaves_exactly_as_before():
    """The regression guard: the original uuid path must be untouched by the foreign path."""
    conn = _db(dict(_DEVICE, **{"tap:track:button_1": "M2"}))
    read = {"by_uuid": {APP_UUID: 1}, "slots": {1: _fields()}}
    out = _run(conn, read)
    e = out["modules"][0]
    assert "foreign" not in e and e["name"] == "Naya Track Left" and e["differs"] == 1
    assert e["matched"] == out["captured"][0]["id"] and e["templateId"] == APP_UUID
    print("  known uuid: still named by its own profile, still captured on drift")


if __name__ == "__main__":
    for fn in (test_the_list_byte_types_a_slot,
               test_a_foreign_uuid_with_identical_content_is_live_and_captures_nothing,
               test_a_foreign_uuid_with_different_content_is_captured_from_the_closest_profile,
               test_reading_a_foreign_slot_twice_is_idempotent,
               test_without_a_list_a_foreign_uuid_is_still_unknown,
               test_an_unrecognised_type_code_is_unknown,
               test_a_type_with_no_profile_in_the_app_is_captured_from_nothing,
               test_a_content_match_stamps_provenance_so_a_flash_claims_the_slot,
               test_a_known_uuid_behaves_exactly_as_before):
        print(fn.__name__)
        fn()
    print("\nOK")
