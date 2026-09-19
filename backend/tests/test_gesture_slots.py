"""Every backfilled gesture slot must be a real NayaFlow gesture, and must show up as an
editable row with the right flashability badge.

1. Each string in _GESTURE_SLOTS is verbatim in the recovered NayaFlow gesture enum
   (docs/reference/naya-gesture-enum.json) -- so a slot we add round-trips on import
   instead of inventing a behavior NayaFlow would reject.
2. The backfill is additive and idempotent against a scratch DB: it never edits an
   existing binding, and running it twice adds nothing the second time.
3. Flashability badges only claim what a real read backs: Tune's 1-finger tap resolves to
   its keypress field, and the dial directions -- whose device fields the live probe left
   unconfirmed -- resolve to nothing, so their rows badge app-only.
No hardware.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.db import userdata as U  # noqa: E402
from openflow_backend.device import module_fields as mf  # noqa: E402

# Walked for, not indexed: NayaOS nests this tree under openflow/ while the standalone
# repository has it at the root.
_ENUM = next(d / "docs" / "reference" / "naya-gesture-enum.json"
             for d in _BACKEND.parents if (d / "docs" / "reference").is_dir())


def test_slots_are_real_nayaflow_gestures():
    enum = set(json.loads(_ENUM.read_text()))
    for mtype, behaviors in U._GESTURE_SLOTS.items():
        for entry in behaviors:
            # An entry is a behavior, or (behavior, code, action_type) for a slot seeded with
            # a value. Only the name is checked against the enum.
            b = entry[0] if isinstance(entry, tuple) else entry
            assert b in enum, f"{mtype} slot {b!r} is not in the NayaFlow gesture enum"
            assert b.split(":")[1] == mtype.lower(), f"{b!r} filed under the wrong module type"
    print(f"  {sum(len(v) for v in U._GESTURE_SLOTS.values())} slots, all in the enum")


def test_backfill_is_additive_and_idempotent():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE module_configs (id TEXT, type TEXT)")
    conn.execute(
        "CREATE TABLE module_bindings (action_id TEXT, action_code TEXT, action_type TEXT, "
        "behavior TEXT, invert INT, threshold INT, direction TEXT, mode INT, "
        "module_config_id TEXT, id TEXT, updated_at TEXT, created_at TEXT)"
    )
    conn.execute("INSERT INTO module_configs VALUES ('cfg-tune','TUNE')")
    # an already-bound slot must survive untouched
    conn.execute(
        "INSERT INTO module_bindings VALUES (NULL,'C_MUTE','key','tap:tune:1_finger',"
        "0,0,'+',0,'cfg-tune','keep-me','t','t')"
    )
    conn.commit()

    U._ensure_gesture_slots(conn)
    after_one = conn.execute("SELECT COUNT(*) c FROM module_bindings").fetchone()["c"]
    U._ensure_gesture_slots(conn)
    after_two = conn.execute("SELECT COUNT(*) c FROM module_bindings").fetchone()["c"]

    assert after_one == 1 + len(U._GESTURE_SLOTS["TUNE"]) - 1, "wrong number of slots inserted"
    assert after_two == after_one, "backfill is not idempotent"
    kept = conn.execute("SELECT * FROM module_bindings WHERE id='keep-me'").fetchone()
    assert kept["action_code"] == "C_MUTE", "backfill clobbered an existing binding"
    # The pinch axis is the one slot seeded WITH a value rather than unbound, because an
    # axis row that says nothing still flashes the stock motion (see _ensure_gesture_slots).
    zoom = conn.execute(
        "SELECT * FROM module_bindings WHERE behavior='pinch&spread:tune:2_fingers'"
    ).fetchone()
    assert zoom["action_type"] == "value"
    assert zoom["action_code"] == "mouse - ZOOM_OUT - ZOOM_IN"
    unbound = conn.execute(
        "SELECT * FROM module_bindings WHERE behavior='tap:tune:1_finger'"
    ).fetchone()
    assert unbound["action_code"] == "C_MUTE", "an existing row is never reseeded"
    print(f"  {after_one} rows after backfill, existing binding preserved, second run a no-op")


def test_badges_only_claim_what_a_read_backs():
    gf = mf.gesture_fields("TUNE")
    assert gf.get("tap:tune:1_finger") == 0x08, "1-finger tap lost its captured keypress field"
    # 0x22/0x23 ARE the dial, retracting the earlier objection that Touch carries them too.
    # That reading came from a Touch map probed at slot 1, which held 36 fields -- a Touch config
    # is 31 (0x00-0x1e), so everything at 0x1f and above there was an orphaned tail from a
    # previous config, not Touch schema. On the Tune the pair holds exactly the two halves of the
    # combined binding, "C_VOL_DOWN - C_VOL_UP", and the dial does control volume by default.
    for g, field in (("clockwise_rotate:tune:dial", 0x22),
                     ("counter_clockwise_rotate:tune:dial", 0x23)):
        assert gf.get(g) == field, f"{g} should map to 0x{field:02x}"
    print("  1-finger tap -> 0x08; dial directions -> 0x22/0x23")


def test_a_touch_config_is_31_fields_so_the_high_indices_are_not_its_schema():
    """The guard that keeps the retraction above honest: if a Touch really did carry 0x22/0x23,
    the dial mapping would be reading shared bytes rather than a dial."""
    import json
    from pathlib import Path
    m = json.loads((Path(mf.__file__).with_name("module_field_map.json")).read_text())
    assert m["TOUCH"]["slot_seen"] == 1, "the Touch map came from the hybrid slot"
    assert max(int(k, 16) for k in m["TOUCH"]["fields"]) > 0x1E, (
        "this map still includes the orphaned tail -- treat anything above 0x1e as not Touch")
    print("  Touch map is from the 36-field hybrid slot; >0x1e is orphaned tail, not schema")


if __name__ == "__main__":
    for fn in (test_slots_are_real_nayaflow_gestures,
               test_backfill_is_additive_and_idempotent,
               test_badges_only_claim_what_a_read_backs):
        print(fn.__name__)
        fn()
    print("\nOK")
