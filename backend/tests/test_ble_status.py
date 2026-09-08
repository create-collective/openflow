"""The BLE_GET_STATUS decode, pinned against the two real captures it was derived from.

We shipped `statusRaw` as an opaque hex string for months. The bytes were always meaningful --
NayaCore's string table names every field -- but names are not offsets, and the name list is
LONGER than the header, so anyone reading it as a straight sequence gets a plausible, wrong
answer. (That is precisely how 0x08 became "LAYER_SW".) These tests therefore assert the things
that are cross-checked against something independent, and assert that the rest stays raw.

The two captures are the same keyboard before and after a power cycle, which is what makes
`revision` legible as a counter rather than a firmware revision: 78703 -> 14.

Two bugs in the first version of this decoder are pinned below, because both looked correct on
inspection and only showed up when the thing was run on real bytes:
  * `hasPeerData` counted bytes 2-4, which are a constant `00 01 02` prefix in every profile, so
    all five unbonded profiles reported as populated.
  * `link_summary` compared a half's split-link peer against the PARTNER's pairAddress. A half's
    pairAddress names its peer, not itself, so that compares the peer to ourselves and calls a
    healthy keyboard mismatched.
No hardware.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = _BACKEND.parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import ble_status as B    # noqa: E402

# The left half, 2026-09-08. The right half answers this command with nothing, which is itself
# why link_summary has to cope with a missing partner.
LEFT = "0001336f0502040201c5f436953d3b000000010200000000000000000000000000000000000000000000000000000000000000000100000102000000000000000000000000000000000000000000000000000000000000000002080001020000000000000000000000000000000000000000000000000000000000000000030000010200000000000000000000000000000000000000000000000000000000000000000400000102000000000000000000000000000000000000000000000000000000000000000007000201f369f2def69c0006000001900202030000000000000600060000019000000000000000"
LEFT_OWN_ADDRESS = "C5:F4:36:95:3D:3B"      # == the RIGHT half's reported pairAddress
LEFT_PEER_ADDRESS = "F3:69:F2:DE:F6:9C"     # == the LEFT half's own reported pairAddress

CAPTURES = _REPO / "device" / "out"


def test_the_fixture_is_the_length_the_layout_assumes():
    assert len(bytes.fromhex(LEFT)) == B.LAYOUT_LENGTH == 239


def test_the_block_structure_validates_itself():
    """Each profile block starts with its own index. A wrong stride cannot produce 0,1,2,3,4."""
    d = B.decode(LEFT)
    assert [p["index"] for p in d["profiles"]] == [0, 1, 2, 3, 4]
    assert d["profileCount"] == 5 == len(d["profiles"])


def test_the_active_profile_is_the_one_that_differs():
    d = B.decode(LEFT)
    assert d["activeProfile"] == 2
    flags = [p["activeFlags"] for p in d["profiles"]]
    assert flags == [0, 0, 8, 0, 0], flags
    assert [p["isActive"] for p in d["profiles"]] == [False, False, True, False, False]


def test_the_addresses_are_the_two_halves_and_not_each_other():
    """The cross-check that makes this decode more than a guess: the left's own address is what
    the RIGHT answers to BLE_GET_PAIR_ADDRESS, and its split-link peer is what the LEFT does."""
    d = B.decode(LEFT)
    assert d["localAddress"] == LEFT_OWN_ADDRESS
    assert d["splitLink"]["peerAddress"] == LEFT_PEER_ADDRESS
    assert d["localAddress"] != d["splitLink"]["peerAddress"]


def test_the_link_timings_are_valid_ble_which_is_what_settles_endianness():
    """Big-endian gives 7.5 ms / 0 / 4000 ms. Little-endian gives 1536 / 0 / 36865, which are
    not legal BLE values -- so this test failing means someone flipped the byte order."""
    link = B.decode(LEFT)["splitLink"]
    assert link["connectionIntervalMs"] == 7.5
    assert link["connectionLatency"] == 0
    assert link["supervisionTimeoutMs"] == 4000


def test_no_profile_is_bonded_on_the_reference_board():
    """The regression: bytes 2-4 are a constant prefix, so counting them made all five profiles
    look populated on a board with nothing paired to it."""
    d = B.decode(LEFT)
    assert d["bondedProfileCount"] == 0
    assert not any(p["hasPeerData"] for p in d["profiles"])


def test_the_undecoded_regions_are_reported_rather_than_named():
    """Anything without independent evidence must stay raw. If a future change names one of
    these, it should delete the assertion deliberately, not discover it broke."""
    d = B.decode(LEFT)
    assert d["headerUnknown"] == "040201"
    assert d["splitLink"]["leadingUnknown"] == "07000201"
    assert d["splitLink"]["trailingUnknown"]
    assert d["raw"] == LEFT           # the bytes stay, so a wrong decode is always checkable


def test_a_half_that_says_nothing_decodes_to_a_statement_not_a_crash():
    for empty in ("", None, b""):
        d = B.decode(empty)
        assert d["layout"] is None and "no BLE status" in d["note"]


def test_an_unfamiliar_layout_is_never_guessed_at():
    d = B.decode("001122")
    assert d["layout"] is None
    assert d["raw"] == "001122"
    assert "unrecognised" in d["note"]


def test_garbage_does_not_raise():
    """This renders on a diagnostics page; a half answering oddly must not blank it."""
    assert B.decode("nothex")["layout"] is None


# --- link_summary ----------------------------------------------------------------------------- #

def test_a_healthy_link_reads_as_linked():
    d = B.decode(LEFT)
    s = B.link_summary(d, LEFT_PEER_ADDRESS)
    assert s["state"] == "linked"
    assert "7.5" in s["detail"] and "4000" in s["detail"]


def test_the_partners_pair_address_is_NOT_what_this_compares_against():
    """The inverted-argument bug, pinned. The right half's pairAddress is the LEFT's own address,
    so passing it here used to report a mismatch on a perfectly healthy keyboard."""
    d = B.decode(LEFT)
    assert B.link_summary(d, LEFT_OWN_ADDRESS)["state"] == "mismatched"
    assert B.link_summary(d, LEFT_PEER_ADDRESS)["state"] == "linked"


def test_a_link_to_a_different_keyboard_is_reported():
    s = B.link_summary(B.decode(LEFT), "AA:BB:CC:DD:EE:FF")
    assert s["state"] == "mismatched"
    assert s["peerAddress"] == LEFT_PEER_ADDRESS


def test_case_does_not_decide_the_verdict():
    assert B.link_summary(B.decode(LEFT), LEFT_PEER_ADDRESS.lower())["state"] == "linked"


def test_no_expectation_still_reports_the_link():
    assert B.link_summary(B.decode(LEFT))["state"] == "linked"


def test_a_half_with_no_peer_is_distinguished_from_one_we_could_not_read():
    """The distinction the pairing reports need: 'not bonded' is a different problem from
    'this half did not answer', and they need different advice."""
    b = bytearray(bytes.fromhex(LEFT))
    b[204:210] = b"\x00" * 6
    assert B.link_summary(B.decode(bytes(b)))["state"] == "no-peer"
    assert B.link_summary(B.decode(""))["state"] == "unknown"


# --- against the captures on disk --------------------------------------------------------------- #

def _captured_blobs():
    """Every statusRaw on disk. The capture files are not uniform -- some hold `status` as a list
    of halves, others use the key for something else entirely -- so this walks rather than
    indexes, and skips anything that is not shaped like a half."""
    out = []
    for f in sorted(CAPTURES.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue

        def walk(node):
            if isinstance(node, dict):
                ble = node.get("ble")
                if isinstance(ble, dict) and ble.get("statusRaw"):
                    out.append((f.name, ble["statusRaw"]))
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)

        walk(data)
    return out


def test_every_captured_blob_decodes():
    """Guards against a layout that only fits the one blob pasted into this file."""
    blobs = _captured_blobs()
    if not blobs:
        pytest.skip("no captured BLE status blobs on disk")
    for name, raw in blobs:
        d = B.decode(raw)
        assert d["layout"], f"{name}: {d.get('note')}"
        assert d["profileCount"] == len(d["profiles"]) == 5, name
        assert [p["index"] for p in d["profiles"]] == [0, 1, 2, 3, 4], name
        assert d["splitLink"]["peerAddress"] == LEFT_PEER_ADDRESS, name


def test_revision_moves_between_the_two_captures_and_the_rest_does_not():
    """What tells us `revision` is a counter and not a firmware revision: it is the ONLY thing
    that differs across a power cycle of the same keyboard."""
    blobs = {raw for _name, raw in _captured_blobs()}
    if len(blobs) < 2:
        pytest.skip("need two distinct captures to compare")
    decoded = [B.decode(b) for b in blobs]
    assert len({d["revision"] for d in decoded}) > 1, "revision did not move"
    for key in ("profileCount", "activeProfile", "localAddress", "headerUnknown"):
        assert len({d[key] for d in decoded}) == 1, f"{key} moved unexpectedly"
