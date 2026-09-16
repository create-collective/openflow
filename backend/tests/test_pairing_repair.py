"""The guided split-link repair: the order is the safety property, and it is gated twice.

Nothing here touches hardware. The plan is pure over a deep status read; the executor is given a
fake service and a fake store so that what it sends, and in what order, and what it refuses, is
asserted exactly.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import pairing_repair as pr        # noqa: E402
from openflow_backend.device import recovery_ops as ro          # noqa: E402

LEFT_ADDR, RIGHT_ADDR = "C5:F4:36:95:3D:3B", "F3:69:F2:DE:F6:9C"     # the owner's pair, 2026-09-07


def half(side, own, pair, fw="3.41.0", ble_fw="2.0.0", connected=True, **extra):
    h = {"side": side, "port": "COM6" if side == "left" else "COM9", "connected": connected,
         "firmwareVersion": fw, "bleAddress": own,
         "ble": {"pairAddress": pair, "firmwareVersion": ble_fw, "name": f"NayaCreate {side}"}}
    h.update(extra)
    return h


def healthy():
    return [half("left", LEFT_ADDR, RIGHT_ADDR), half("right", RIGHT_ADDR, LEFT_ADDR)]


def broken():
    """The case the repair exists for: the right half still points at an old partner."""
    return [half("left", LEFT_ADDR, RIGHT_ADDR), half("right", RIGHT_ADDR, "11:22:33:44:55:66")]


# --- the plan --------------------------------------------------------------------------------- #

def test_the_partner_address_is_stored_before_anything_is_written():
    p = pr.plan(broken())
    kinds = [s.kind for s in p.steps]
    assert kinds.index("store") < kinds.index("write"), "store first, then clear -- never the reverse"
    assert p.record["left"]["pairAddress"] == RIGHT_ADDR
    assert p.record["right"]["pairAddress"] == "11:22:33:44:55:66"
    assert p.record["willSet"] == {"left": RIGHT_ADDR, "right": LEFT_ADDR}


def test_the_sequence_is_nayacores_in_nayacores_order():
    """set pair address -> wait 300 -> clear split links -> unpair all -> wait 1000 -> wait for
    the peer -> normal reset, then the two verifies."""
    p = pr.plan(broken())
    writes = [(s.side, s.op) for s in p.steps if s.kind == "write"]
    assert writes == [
        ("left", "ble_set_pair_address"), ("right", "ble_set_pair_address"),
        ("left", "ble_clear_all_split_links"), ("right", "ble_clear_all_split_links"),
        ("left", "ble_unpair_all"), ("right", "ble_unpair_all"),
        ("left", "reset_normal"), ("right", "reset_normal"),
    ]
    names = [s.name for s in p.steps]
    assert names.index("wait_300ms") < names.index("ClearConnections")
    assert names.index("wait_1000ms") < names.index("WaitForPairingPeerBeforeNormalReset") < names.index("Respawn")
    assert names[-2:] == ["VerifyBLEAddresses", "RecheckBLEStatus"]
    waits = [s.ms for s in p.steps if s.kind == "wait" and s.ms]
    assert waits == [300, 1000]


def test_each_half_is_pointed_at_the_others_own_address_with_the_pinned_frame():
    p = pr.plan(broken())
    sets = {s.side: s for s in p.steps if s.op == "ble_set_pair_address"}
    assert sets["left"].opts == {"mac": RIGHT_ADDR} and sets["right"].opts == {"mac": LEFT_ADDR}
    assert sets["left"].frame == (0xBE, 0x1001, bytes.fromhex("f369f2def69c"))
    assert sets["right"].frame == (0xBE, 0x1001, bytes.fromhex("c5f436953d3b"))
    for s in p.steps:
        if s.kind == "write":
            assert s.frame == ro.frame_for(s.op, s.opts), s.name


def test_the_arm_token_is_tied_to_the_four_addresses():
    a = pr.plan(broken()).arm_token
    assert a == pr.plan(broken()).arm_token and len(a) == 16
    assert a != pr.plan(healthy()).arm_token, "the right half's pair address differs"
    other = [half("left", "AA:AA:AA:AA:AA:AA", RIGHT_ADDR), half("right", RIGHT_ADDR, LEFT_ADDR)]
    assert a != pr.plan(other).arm_token


def test_a_healthy_pair_still_plans_and_says_the_partner_would_be_unchanged():
    p = pr.plan(healthy())
    assert p.record["willSet"] == {"left": RIGHT_ADDR, "right": LEFT_ADDR}
    assert p.public()["opsDisabled"] == sorted(p.ops), "every op it needs ships disabled"


def test_refusals_use_nayacores_own_words():
    with pytest.raises(pr.PairingRefused, match=r"missing device\(s\) \(left=True, right=False\)"):
        pr.plan([half("left", LEFT_ADDR, RIGHT_ADDR)])
    with pytest.raises(pr.PairingRefused, match="missing device"):
        pr.plan([half("left", LEFT_ADDR, RIGHT_ADDR), half("right", RIGHT_ADDR, LEFT_ADDR, connected=False)])
    with pytest.raises(pr.PairingRefused, match="different firmware versions"):
        pr.plan([half("left", LEFT_ADDR, RIGHT_ADDR), half("right", RIGHT_ADDR, LEFT_ADDR, fw="3.35.4")])
    with pytest.raises(pr.PairingRefused, match="different BLE firmware"):
        pr.plan([half("left", LEFT_ADDR, RIGHT_ADDR), half("right", RIGHT_ADDR, LEFT_ADDR, ble_fw="1.9.0")])


def test_no_address_means_nothing_to_exchange_and_nothing_is_cleared():
    with pytest.raises(pr.PairingRefused, match="did not report its own BLE address"):
        pr.plan([half("left", None, RIGHT_ADDR), half("right", RIGHT_ADDR, LEFT_ADDR)])
    with pytest.raises(pr.PairingRefused, match="same BLE address"):
        pr.plan([half("left", LEFT_ADDR, RIGHT_ADDR), half("right", LEFT_ADDR, LEFT_ADDR)])


def test_a_missing_pair_address_is_recorded_as_none_not_refused():
    p = pr.plan([half("left", LEFT_ADDR, None), half("right", RIGHT_ADDR, None)])
    assert p.record["left"]["pairAddress"] is None and any("no pair address" in n for n in p.notes)


def test_public_shape_carries_the_commands_for_the_ui():
    pub = pr.plan(broken()).public()
    assert pub["enabled"] is False and pub["record"]["willSet"]["left"] == RIGHT_ADDR
    cmds = [s["command"] for s in pub["steps"] if s["kind"] == "write"]
    assert cmds[0] == "0xbe/0x1001 f369f2def69c" and cmds[-1] == "0xee/0x10ce (empty)"


# --- the executor: gates first, store next, frames last --------------------------------------- #

class FakeService:
    def __init__(self):
        self.calls = []

    def run_recovery_op(self, side, op_id, opts=None, *, force=False):
        self.calls.append((side, op_id, dict(opts or {}), force))
        return {"ok": True}


def _fake_store(box):
    def store(record):
        box.append(record)
        return {"file": "fake", "key": pr.RECORD_KEY}
    return store


def test_the_module_gate_refuses_before_anything_at_all():
    svc, box = FakeService(), []
    p = pr.plan(broken())
    with pytest.raises(pr.PairingRefused, match="disabled"):
        pr.execute(svc, p, arm=p.arm_token, force=True, store=_fake_store(box), sleep=lambda s: None)
    assert svc.calls == [] and box == []


def test_wrong_arm_token_and_missing_force_refuse_before_storing(monkeypatch):
    monkeypatch.setattr(pr, "PAIRING_REPAIR_ENABLED", True)
    svc, box = FakeService(), []
    p = pr.plan(broken())
    with pytest.raises(pr.PairingRefused, match="not armed"):
        pr.execute(svc, p, arm="stale", force=True, store=_fake_store(box), sleep=lambda s: None)
    with pytest.raises(pr.PairingRefused, match="explicit confirmation"):
        pr.execute(svc, p, arm=p.arm_token, force=False, store=_fake_store(box), sleep=lambda s: None)
    assert svc.calls == [] and box == []


def test_a_sequence_with_any_op_still_disabled_never_starts(monkeypatch):
    """Half-enabled is the dangerous case: addresses exchanged, then a refusal before the clear."""
    monkeypatch.setattr(pr, "PAIRING_REPAIR_ENABLED", True)
    svc, box = FakeService(), []
    p = pr.plan(broken())
    with pytest.raises(pr.PairingRefused, match="needs these recovery ops enabled"):
        pr.execute(svc, p, arm=p.arm_token, force=True, store=_fake_store(box), sleep=lambda s: None)
    assert svc.calls == [] and box == []


def _enable_all(monkeypatch):
    import dataclasses
    monkeypatch.setattr(pr, "PAIRING_REPAIR_ENABLED", True)
    enabled = {k: dataclasses.replace(v, enabled=True) for k, v in ro.BY_ID.items()}
    monkeypatch.setattr(ro, "BY_ID", enabled)


def test_when_everything_is_enabled_it_stores_then_sends_in_order(monkeypatch):
    _enable_all(monkeypatch)
    svc, box, slept = FakeService(), [], []
    p = pr.plan(broken())
    r = pr.execute(svc, p, arm=p.arm_token, force=True, store=_fake_store(box), sleep=slept.append)
    assert box == [p.record], "the record is stored exactly once, before the first frame"
    assert [(s, o) for s, o, _opts, _f in svc.calls] == [
        ("left", "ble_set_pair_address"), ("right", "ble_set_pair_address"),
        ("left", "ble_clear_all_split_links"), ("right", "ble_clear_all_split_links"),
        ("left", "ble_unpair_all"), ("right", "ble_unpair_all"),
        ("left", "reset_normal"), ("right", "reset_normal")]
    assert svc.calls[0][2] == {"mac": RIGHT_ADDR} and svc.calls[1][2] == {"mac": LEFT_ADDR}
    assert all(f is True for *_x, f in svc.calls)
    assert slept == [0.3, 1.0]
    assert r["ok"] and r["expect"] == {"left": RIGHT_ADDR, "right": LEFT_ADDR}


def test_a_store_failure_sends_nothing(monkeypatch):
    _enable_all(monkeypatch)
    svc = FakeService()
    p = pr.plan(broken())

    def bad_store(record):
        raise OSError("disk full")
    with pytest.raises(OSError):
        pr.execute(svc, p, arm=p.arm_token, force=True, store=bad_store, sleep=lambda s: None)
    assert svc.calls == []


# --- verify ----------------------------------------------------------------------------------- #

def test_verify_reports_the_bond_and_whether_the_plan_took():
    plan = pr.plan(broken())
    v = pr.verify(healthy(), plan.record["willSet"])
    assert v["state"] == "paired" and v["matchesPlan"] == {"left": True, "right": True}
    v = pr.verify(broken(), plan.record["willSet"])
    assert v["state"] == "half-paired" and v["matchesPlan"] == {"left": True, "right": False}
    assert pr.verify([half("left", LEFT_ADDR, RIGHT_ADDR)])["state"] == "incomplete"
