"""The module firmware procedure: NayaFlow's order (measured 2026-09-23), the pairing rule, and the
cable-replug prompt.

No hardware. The keyboard is a fake that answers identity and module reads, records every command
sent, and plays the two self-restarts the capture showed: after the upload, and ~32 s after
MODULE_FWUP. A fake clock drives the waits, so a ten-minute timeout costs nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend._vendor.nayactl import constants as C       # noqa: E402
from openflow_backend.device import firmware_upload as fw         # noqa: E402
from openflow_backend.device import module_procedure as mp        # noqa: E402


def _bundle(version, rng, *, flashable=True, path=None):
    return {"type": "littlefs", "target": "module", "file": "FlashMemory.bin",
            "moduleFirmware": version, "versionLabel": version, "flashable": flashable,
            "keyboardRange": {"from": rng[0], "below": rng[1]} if rng else None,
            "withheldBecause": [] if flashable else ["withheld"],
            "historyPath": path or f"v-{version}/module/FlashMemory.bin"}


# What the warranty board's bootloader answered for `image slot info` on 2026-09-16.
BOARD_MAP = {"supported": True, "rc": 0, "slots": [{"image": 0, "slot": 0, "size": 663552, "uploadImageId": 1}, {"image": 0, "slot": 1, "size": 663552, "uploadImageId": 2}]}

# The ranges the catalogue builds from every official and beta release (2026-09-23).
CATALOG = [_bundle("2.3.3", ("3.40.0", None)), _bundle("2.3.2", ("3.31.1", "3.40.0")),
           _bundle("2.2.0", ("3.29.1", "3.31.1")), _bundle("2.1.2", ("3.28.7", "3.29.1")),
           _bundle("2.1.1", None, flashable=False)]


class _Frame:
    def __init__(self, payload):
        self.valid, self.payload = True, payload


class _Dev:
    def __init__(self, side):
        self.port = {"left": "COM30", "right": "COM29"}[side]
        self.serial_number = "LEFTSERIAL"
        self.side = side


class Clock:
    def __init__(self):
        self.t = 1000.0

    def monotonic(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeKeyboard:
    """A left half with a module in its bay. `absent_for` is how many presence checks the half
    stays off USB after each self-restart (None = until replugged by the test)."""

    def __init__(self, *, kb="3.41.0", module=("Touch", 0x10, "2.1.2"), stored="2.3.2",
                 right=False, absent_for=3):
        self.kb, self.stored, self.right = kb, stored, right
        self.module = dict(zip(("type", "address", "version"), module)) if module else None
        self.sent: list[tuple] = []
        self.absent = 0
        self.absent_for = absent_for
        self.keymap = {"layers": {0: [(1, 4, b"\x01")]}, "led": {0: [(0, 1, 2)]},
                       "layer_uuids": {0: "u"}, "layer_animations": {0: "solid"}}

    # --- what the procedure asks the service -------------------------------------------------- #
    def list_devices(self):
        out = []
        if self.absent:
            if self.absent_for is not None:
                self.absent -= 1
        else:
            out.append({"side": "left"})
        if self.right:
            out.append({"side": "right"})
        return out

    def module_file_fw_version(self, side="left"):
        return {"version": self.stored}

    def read_keymap(self, side="left", serial=None):
        return self.keymap

    def _with_transport(self, side, fn, serial=None):
        kb = self

        class T:
            def send_command(self, dest, cat, sub, payload=b"", timeout=1.0, **kw):
                kb.sent.append((cat, sub, bytes(payload)))
                m = kb.module
                if (cat, sub) == (C.CAT_SYSTEM, C.SYS_GET_FW_VERSION):
                    return [_Frame(bytes([0, *map(int, kb.kb.split("."))]))]
                if cat == C.CAT_BLE:
                    return [_Frame(bytes([1, 1, 2, 3, 4, 5, 6]) if sub == C.BLE_GET_ALL_PAIRS
                                   else bytes([1, 2, 3, 4, 5, 6]))]
                if (cat, sub) == (C.CAT_MODULE, C.MOD_SEND_HANDSHAKE):
                    return [_Frame(bytes([1, m["address"]]) if m else bytes([0]))]
                if (cat, sub) == (C.CAT_MODULE, C.MOD_DETECT):
                    return [_Frame(bytes([1 if m else 0]))]
                if (cat, sub) == (C.CAT_MODULE, C.MOD_GET_FW_VERSION):
                    return [_Frame(bytes([0x10, 0, 0, *map(int, m["version"].split("."))]))] if m else []
                if (cat, sub) == (C.CAT_MODULE, C.MOD_FWUP):
                    # Programs from the bundle it holds, answers nothing, then restarts.
                    m["version"] = kb.stored
                    kb.absent = kb.absent_for if kb.absent_for is not None else 1
                    return []
                return [_Frame(b"")]
        return fn(T(), 0x50, _Dev(side))

    def fwup_bytes(self):
        return [p for c, s, p in self.sent if (c, s) == (C.CAT_MODULE, C.MOD_FWUP)]

    def entered_bootloader(self):
        return any((c, s) == (C.CAT_RESET, C.RESET_MCU_BOOT) for c, s, _ in self.sent)


@pytest.fixture()
def rig(monkeypatch, tmp_path):
    clock = Clock()
    monkeypatch.setattr(mp, "time", clock)
    monkeypatch.setattr(mp.rec, "find_recovery_ports", lambda: [])
    monkeypatch.setattr(mp.rec, "os_reset", lambda port: None)
    monkeypatch.setattr(mp.fp, "RECOVERY_WAIT", 0.0)
    monkeypatch.setattr(mp.fp, "_identify_in_bootloader", lambda side, catalog: {
        "state": "ok", "port": "COM26", "slotInfo": BOARD_MAP,
        "images": [{"slot": 0, "hash": "arm", "createFirmware": "3.41.0"}]})
    monkeypatch.setattr(mp.rec, "slot_info", lambda port: BOARD_MAP)
    for e in CATALOG:
        p = tmp_path / "fw" / e["historyPath"]
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\xff" * 16)
    return {"clock": clock, "root": tmp_path / "fw", "logs": tmp_path / "logs"}


def _upload_that_restarts(kb, calls):
    def upload(path, catalog, *, arm, installed_version=None, allow_older=False, progress=None,
               state=None, slot_info=None, allow_unmapped=False):
        calls.append({"path": Path(path), "arm": arm, "installed": installed_version,
                      "slot_info": slot_info, "allow_unmapped": allow_unmapped})
        progress(512, 1024)
        progress(1024, 1024)
        kb.stored = next(e["moduleFirmware"] for e in catalog
                         if e.get("historyPath") and Path(path).as_posix().endswith(e["historyPath"]))
        kb.absent = kb.absent_for if kb.absent_for is not None else 1     # restarts on its own
        return {"ok": True, "written": 1024, "reset": False}
    return upload


def _run(rig, kb, **kw):
    calls: list = []
    verdict = mp.run(kb, CATALOG, firmware_root=rig["root"], log_dir=rig["logs"],
                     upload_fn=_upload_that_restarts(kb, calls), **kw)
    events = [line for line in (rig["logs"] / "run.log").read_text(encoding="utf-8").splitlines()]
    return verdict, calls, "\n".join(events)


# --- the sequence -------------------------------------------------------------------------------- #

def test_the_keyboard_already_holding_the_bundle_skips_the_upload_and_programs(rig):
    """Run 2 of the capture: stored bundle == target, so straight to MODULE_FWUP."""
    kb = FakeKeyboard(stored="2.3.3")
    verdict, calls, log = _run(rig, kb)
    assert verdict["ok"], verdict
    assert calls == [] and not kb.entered_bootloader()
    assert kb.fwup_bytes() == [b"\x01"]                       # Touch = 01, measured
    assert kb.module["version"] == "2.3.3"
    assert '"step": "module.verify", "label": "Confirming the module\'s new version", "phase": "ok"' in log


def test_the_apps_cached_module_version_is_dropped_when_the_run_ends(rig):
    """2026-09-23: verified on 2.3.3, and the status bar still said 2.1.2 -- the live status
    reads a module's firmware once per docking, and the module never left the bay."""
    kb = FakeKeyboard(stored="2.3.3")
    kb.forgot = 0
    kb.forget_module_firmware = lambda: setattr(kb, "forgot", kb.forgot + 1)
    verdict, _, _ = _run(rig, kb)
    assert verdict["ok"] and kb.forgot == 1


def test_a_different_stored_bundle_is_uploaded_first_then_the_module_programmed(rig):
    """Run 1 + run 2 of the capture in one: 2.3.2 stored, 2.3.3 installed."""
    kb = FakeKeyboard(stored="2.3.2")
    verdict, calls, _ = _run(rig, kb)
    assert verdict["ok"], verdict
    assert kb.entered_bootloader() and len(calls) == 1
    assert calls[0]["arm"] == "arm" and calls[0]["installed"] == "2.3.2"
    assert kb.stored == "2.3.3" and kb.module["version"] == "2.3.3"
    assert kb.fwup_bytes() == [b"\x01"]


def test_force_upload_rewrites_a_bundle_the_keyboard_already_holds(rig):
    kb = FakeKeyboard(stored="2.3.3")
    verdict, calls, log = _run(rig, kb, force_upload=True)
    assert verdict["ok"], verdict
    assert len(calls) == 1 and kb.entered_bootloader()
    assert "forced; the keyboard already holds it" in log


def test_nothing_to_do_writes_nothing(rig):
    kb = FakeKeyboard(stored="2.3.3", module=("Touch", 0x10, "2.3.3"))
    verdict, calls, _ = _run(rig, kb)
    assert verdict["ok"] and "nothing to do" in verdict["summary"]
    assert calls == [] and kb.fwup_bytes() == [] and not kb.entered_bootloader()


@pytest.mark.parametrize("module,code", [(("Track", 0x20, "2.1.2"), b"\x02"),
                                         (("Tune", 0x40, "2.1.2"), b"\x03")])
def test_the_fwup_byte_is_the_type_number_not_the_dock_address(rig, module, code):
    kb = FakeKeyboard(stored="2.3.3", module=module)
    verdict, _, _ = _run(rig, kb)
    assert verdict["ok"], verdict
    assert kb.fwup_bytes() == [code]


# --- preconditions: refused before anything is written ------------------------------------------- #

def test_the_right_half_on_usb_is_refused(rig):
    kb = FakeKeyboard(right=True)
    verdict, calls, _ = _run(rig, kb)
    assert not verdict["ok"] and "right half is connected" in verdict["summary"]
    assert calls == [] and kb.fwup_bytes() == [] and not kb.entered_bootloader()


def test_no_module_docked_is_refused(rig):
    kb = FakeKeyboard(module=None)
    verdict, calls, _ = _run(rig, kb)
    assert not verdict["ok"] and "no module is docked" in verdict["summary"]
    assert calls == [] and not kb.entered_bootloader()


def test_a_bundle_the_keyboard_firmware_did_not_ship_with_is_refused_and_the_right_one_named(rig):
    kb = FakeKeyboard(kb="3.35.4")
    verdict, calls, _ = _run(rig, kb, version="2.3.3")
    assert not verdict["ok"]
    assert "goes with keyboard firmware 3.40.0 and later; this left half runs 3.35.4" in verdict["summary"]
    assert "2.3.2 is the one for 3.35.4" in verdict["summary"]
    assert calls == [] and kb.fwup_bytes() == []


@pytest.mark.parametrize("kb_version,chosen", [("3.36.2", "2.3.2"), ("3.39.9", "2.3.2"),
                                               ("3.40.0", "2.3.3"), ("3.40.4", "2.3.3"),
                                               ("3.41.0", "2.3.3"), ("3.30.0", "2.2.0")])
def test_a_keyboard_version_nobody_catalogued_still_gets_the_bundle_whose_range_holds_it(kb_version, chosen):
    """The owner's rule: a bundle goes with every keyboard version from the first it shipped with
    up to the next bundle's first, not only the handful of versions we have seen."""
    assert mp.choose_bundle(CATALOG, kb_version, None)["moduleFirmware"] == chosen


def test_below_the_oldest_range_there_is_nothing_to_offer():
    with pytest.raises(mp.ModuleRefused, match="no module firmware we hold goes with keyboard firmware 3.27.0"):
        mp.choose_bundle(CATALOG, "3.27.0", None)


def test_with_no_version_the_paired_bundle_is_chosen(rig):
    kb = FakeKeyboard(kb="3.35.4", stored="2.3.2")
    verdict, calls, _ = _run(rig, kb)
    assert verdict["ok"], verdict
    assert calls == [] and kb.module["version"] == "2.3.2"


def test_a_downgrade_needs_allow_older(rig):
    kb = FakeKeyboard(kb="3.35.4", stored="2.3.2", module=("Touch", 0x10, "2.3.3"))
    verdict, _, _ = _run(rig, kb)
    assert not verdict["ok"] and "older than the 2.3.3" in verdict["summary"]
    kb = FakeKeyboard(kb="3.35.4", stored="2.3.2", module=("Touch", 0x10, "2.3.3"))
    verdict, _, _ = _run(rig, kb, allow_older=True)
    assert verdict["ok"], verdict
    assert kb.module["version"] == "2.3.2"


def test_a_withheld_bundle_is_refused(rig):
    kb = FakeKeyboard()
    verdict, _, _ = _run(rig, kb, version="2.1.1")
    assert not verdict["ok"] and "withheld" in verdict["summary"]


# --- the cable replug ---------------------------------------------------------------------------- #

def test_a_half_that_does_not_come_back_is_asked_for_a_replug_once(rig):
    """The measured case: after a self-restart the half never re-enumerates on its own."""
    kb = FakeKeyboard(stored="2.3.3", absent_for=None)        # gone until "replugged"

    def replug_after_prompt(event):
        if event.get("step") == "replug" and event.get("phase") == "action":
            kb.absent = 0                                    # the user replugs
    calls: list = []
    verdict = mp.run(kb, CATALOG, firmware_root=rig["root"], log_dir=rig["logs"],
                     upload_fn=_upload_that_restarts(kb, calls), on_event=replug_after_prompt)
    log = (rig["logs"] / "run.log").read_text(encoding="utf-8")
    assert verdict["ok"], verdict
    assert log.count('"step": "replug", "label": "Unplug the left half\'s USB cable and plug it back in", "phase": "action"') == 1
    assert '"step": "replug"' in log and '"phase": "ok"' in log


def test_a_half_that_never_comes_back_fails_with_what_to_do(rig):
    kb = FakeKeyboard(stored="2.3.3", absent_for=None)
    verdict, _, log = _run(rig, kb)
    assert not verdict["ok"]
    assert "did not come back after programming" in verdict["summary"]
    assert '"phase": "action"' in log


# --- the slot map (first hardware run, 2026-09-23 13:32) ---------------------------------------- #

def _no_map_at_identify(monkeypatch):
    monkeypatch.setattr(mp.fp, "_identify_in_bootloader", lambda side, catalog: {
        "state": "ok", "port": "COM26",
        "slotInfo": {"supported": None, "error": "SerialException: could not open port", "slots": []},
        "images": [{"slot": 0, "hash": "arm", "createFirmware": "3.41.0"}]})


def test_a_slot_map_identify_missed_is_read_again_and_used(rig, monkeypatch):
    _no_map_at_identify(monkeypatch)
    reads = []
    monkeypatch.setattr(mp.rec, "slot_info", lambda port: reads.append(port) or BOARD_MAP)
    kb = FakeKeyboard(stored="2.3.3")
    verdict, calls, log = _run(rig, kb, force_upload=True)
    assert verdict["ok"], verdict
    assert reads == ["COM26"]
    assert calls[0]["slot_info"] == BOARD_MAP and calls[0]["allow_unmapped"] is False
    assert "the bootloader reported its slot map (after 1 retries)" in log


def test_a_slot_map_that_never_answers_falls_back_to_slot_4_and_says_so(rig, monkeypatch):
    _no_map_at_identify(monkeypatch)
    reads = []

    def refuse(port):
        reads.append(port)
        raise OSError("could not open port")
    monkeypatch.setattr(mp.rec, "slot_info", refuse)
    kb = FakeKeyboard(stored="2.3.3")
    verdict, calls, log = _run(rig, kb, force_upload=True)
    assert verdict["ok"], verdict
    assert len(reads) == mp.SLOT_MAP_TRIES
    assert calls[0]["allow_unmapped"] is True
    assert any("modules slot 4, as NayaFlow does" in a for a in verdict["advisories"])


def test_an_empty_slot_map_reply_is_retried_then_falls_back(rig, monkeypatch):
    """Attempt 2 of 2026-09-23: the map read ANSWERED, rc 0, with no slots in it."""
    _no_map_at_identify(monkeypatch)
    empty = {"supported": None, "rc": 0, "slots": [], "raw": {}, "error": "the reply carried no slot list"}
    monkeypatch.setattr(mp.rec, "slot_info", lambda port: empty)
    kb = FakeKeyboard(stored="2.3.3")
    verdict, calls, log = _run(rig, kb, force_upload=True)
    assert verdict["ok"], verdict
    assert calls[0]["allow_unmapped"] is True
    assert "no slot list" in " ".join(verdict["advisories"])
    assert '"slotMapReply"' in log


# --- recovery after a failure in the bootloader -------------------------------------------------- #

def test_a_failure_in_the_bootloader_waits_for_the_half_with_the_replug_prompt(rig, monkeypatch):
    """What actually happened at 13:32: the half left the bootloader after the reset and never
    came back on USB. The old recovery blamed the bootloader after five minutes."""
    monkeypatch.setattr(mp.fp, "RECOVERY_WAIT", 120.0)
    kb = FakeKeyboard(stored="2.3.3", absent_for=None)

    def failing_upload(path, catalog, **kw):
        kb.absent = 1                                        # restarts, never comes back
        raise fw.UploadRefused("the bootloader rejected the chunk at offset 0")

    verdict = mp.run(kb, CATALOG, firmware_root=rig["root"], log_dir=rig["logs"],
                     upload_fn=failing_upload, force_upload=True)
    log = (rig["logs"] / "run.log").read_text(encoding="utf-8")
    assert not verdict["ok"] and "rejected the chunk" in verdict["summary"]
    assert '"phase": "action"' in log                        # asked for the replug
    assert "has not come back on USB" in log
    assert "still in its bootloader" not in log


def test_a_refusal_before_the_bootloader_does_not_wait_for_anything(rig):
    kb = FakeKeyboard(right=True)
    verdict, _, log = _run(rig, kb)
    assert not verdict["ok"]
    assert "mcuboot.exit" not in log and '"phase": "action"' not in log


# --- the upload primitive ------------------------------------------------------------------------ #

def test_require_module_pairing_accepts_the_shipped_pair_only():
    fw.require_module_pairing(CATALOG[0], "3.41.0", CATALOG)
    fw.require_module_pairing(CATALOG[0], "3.40.4", CATALOG)              # a beta keyboard
    with pytest.raises(fw.UploadRefused, match="2.1.2 is the one for 3.28.7"):
        fw.require_module_pairing(CATALOG[0], "3.28.7", CATALOG)
    with pytest.raises(fw.UploadRefused, match="3.31.1 up to 3.40.0; this left half runs 3.40.0"):
        fw.require_module_pairing(CATALOG[1], "3.40.0", CATALOG)          # the bound is exclusive
    with pytest.raises(fw.UploadRefused, match="could not be read"):
        fw.require_module_pairing(CATALOG[0], None, CATALOG)
