"""Is the right half dead, or just not bonded to the left one?

Those two failures look identical to a user -- "my right half stopped working" -- and they need
opposite repairs. NayaFlow cannot tell them apart: a half that does not enumerate simply never
appears in its Target Devices list and the update button stays disabled, and it ships no
per-half recovery at all (its own "one half connected" warning strings exist but are
Japanese-only and not wired into the renderer).

The check is a CROSS-comparison rather than a flag we trust the device to set: each half reports
its own BLE address and the address it is bonded TO, so a healthy pair is exactly
    left.pairAddress == right.bleAddress  AND  right.pairAddress == left.bleAddress

The addresses below are a real reading from a working pair, 2026-09-07:
    left  address C5:F4:36:95:3D:3B, paired to F3:69:F2:DE:F6:9C
    right address F3:69:F2:DE:F6:9C, paired to C5:F4:36:95:3D:3B
which cross-check exactly. The broken states are constructed, since a working keyboard cannot
produce them on demand.
No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device.service import pairing_report   # noqa: E402

L_ADDR = "C5:F4:36:95:3D:3B"
R_ADDR = "F3:69:F2:DE:F6:9C"
OTHER = "11:22:33:44:55:66"


def half(side, addr, paired_to, connected=True):
    return {"side": side, "connected": connected, "bleAddress": addr,
            "ble": {"pairAddress": paired_to} if paired_to is not None else {}}


def test_a_real_working_pair_reads_as_paired():
    got = pairing_report([half("left", L_ADDR, R_ADDR), half("right", R_ADDR, L_ADDR)])
    assert got["state"] == "paired", got


def test_case_does_not_decide_the_verdict():
    """Addresses are formatted by us but compared as text; a lowercase source must still match."""
    got = pairing_report([half("left", L_ADDR.lower(), R_ADDR.lower()),
                          half("right", R_ADDR, L_ADDR)])
    assert got["state"] == "paired", got


def test_neither_pointing_at_the_other_is_not_paired():
    got = pairing_report([half("left", L_ADDR, OTHER), half("right", R_ADDR, OTHER)])
    assert got["state"] == "not-paired", got
    assert OTHER in got["detail"]


def test_one_directional_bond_is_called_out_not_rounded():
    """A half re-paired while the other still points at an old partner is a REAL state, and
    rounding it to paired or not-paired sends someone down the wrong repair path."""
    got = pairing_report([half("left", L_ADDR, R_ADDR), half("right", R_ADDR, OTHER)])
    assert got["state"] == "half-paired", got
    assert "left" in got["detail"]


def test_one_half_missing_is_incomplete_not_a_pairing_failure():
    """The commonest real report -- 'my right side is gone'. Calling that 'not paired' would
    send the user to re-pair when the actual problem is that it never enumerated."""
    got = pairing_report([half("left", L_ADDR, R_ADDR)])
    assert got["state"] == "incomplete", got
    assert "left" in got["detail"]


def test_a_disconnected_half_does_not_count_as_present():
    got = pairing_report([half("left", L_ADDR, R_ADDR),
                          half("right", R_ADDR, L_ADDR, connected=False)])
    assert got["state"] == "incomplete", got


def test_no_pair_address_reported_is_unknown_not_a_failure():
    """A plain (non-verbose) status has no BLE block at all. Claiming 'not paired' from missing
    data would be inventing a fault."""
    got = pairing_report([half("left", L_ADDR, None), half("right", R_ADDR, None)])
    assert got["state"] == "unknown", got


def test_nothing_connected():
    assert pairing_report([])["state"] == "incomplete"


def deep(side, addr, paired_to, peers, fw="3.41.0"):
    h = half(side, addr, paired_to)
    h["ble"]["pairedPeers"] = peers
    h["firmwareVersion"] = fw
    return h


def test_pointing_at_each_other_with_an_empty_bond_table_is_not_paired():
    """A user's left half pointed at its partner with an EMPTY bond table and the link down
    (2026-09-25); the address cross-check alone called that paired."""
    got = pairing_report([deep("left", L_ADDR, R_ADDR, []), deep("right", R_ADDR, L_ADDR, [L_ADDR])])
    assert got["state"] == "bond-missing", got
    assert got["missing"] == ["left"]
    assert "is empty" in got["detail"]


def test_bond_tables_holding_the_partner_are_paired():
    got = pairing_report([deep("left", L_ADDR, R_ADDR, [R_ADDR.lower()]),
                          deep("right", R_ADDR, L_ADDR, [OTHER, L_ADDR])])
    assert got["state"] == "paired", got


def test_no_bond_table_read_is_not_a_failure():
    """Poll data carries no bond table; that must not turn a working pair into a broken one."""
    got = pairing_report([half("left", L_ADDR, R_ADDR), half("right", R_ADDR, L_ADDR)])
    assert got["state"] == "paired", got


# --- split_link_verdict --------------------------------------------------------------------

from openflow_backend.device.service import split_link_verdict   # noqa: E402


def verdict(left, right, partner):
    halves = [h for h in (left, right) if h is not None]
    return split_link_verdict(halves, pairing_report(halves), partner)


def test_split_link_ok_when_bonded_and_the_right_answers_through_the_left():
    v = verdict(deep("left", L_ADDR, R_ADDR, [R_ADDR]), deep("right", R_ADDR, L_ADDR, [L_ADDR]),
                {"reached": True, "firmwareVersion": "3.41.0"})
    assert v["state"] == "ok" and v["action"] is None


def test_split_link_needs_both_halves_on_usb():
    v = verdict(deep("left", L_ADDR, R_ADDR, [R_ADDR]), None, None)
    assert v["state"] == "connect-both"
    assert "left half is on USB" in v["detail"]


def test_firmware_mismatch_comes_before_pairing_and_compares_numerically():
    """The pairing repair refuses while firmware differs, so that is the first fix. 3.9 is
    older than 3.10, which a text comparison gets backwards."""
    v = verdict(deep("left", L_ADDR, R_ADDR, [], fw="3.10.0"),
                deep("right", R_ADDR, L_ADDR, [], fw="3.9.0"), None)
    assert v["state"] == "firmware-mismatch" and v["action"] == "update-firmware"
    assert "update the right half" in v["detail"]


def test_a_missing_bond_sends_you_to_the_pairing_repair():
    v = verdict(deep("left", L_ADDR, R_ADDR, []), deep("right", R_ADDR, L_ADDR, [L_ADDR]),
                {"reached": False, "firmwareVersion": None})
    assert v["state"] == "re-pair" and v["action"] == "pairing-repair"


def test_bonded_but_unreachable_is_a_link_down():
    v = verdict(deep("left", L_ADDR, R_ADDR, [R_ADDR]), deep("right", R_ADDR, L_ADDR, [L_ADDR]),
                {"reached": False, "firmwareVersion": None})
    assert v["state"] == "link-down" and v["action"] == "restart"
