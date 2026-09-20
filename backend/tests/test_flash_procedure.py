"""The flash procedure: its ordering, its audit log, and what it calls a failure.

The point of this module is that a user can read one log top to bottom and know what happened,
and that a difference which is EXPECTED never gets reported as a broken flash. Both are asserted
here. No hardware: the service, the bootloader and the upload are all stubbed, because what is
under test is the procedure, not the wire.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend._vendor.nayactl import constants as C       # noqa: E402
from openflow_backend.device import flash_procedure as P          # noqa: E402


class _Frame:
    def __init__(self, payload):
        self.valid, self.payload = True, payload


class _Dev:
    def __init__(self, side):
        self.port = {"left": "COM30", "right": "COM29"}[side]
        self.serial_number = {"left": "LEFTSERIAL", "right": "RIGHTSERIAL"}[side]
        self.side = side


def _mac_bytes(mac):
    return bytes(int(b, 16) for b in mac.split(":"))


class FakeSvc:
    """A keyboard that answers identity reads and holds a keymap, with mutable firmware."""

    def __init__(self, halves, keymap):
        self.halves = halves            # side -> {firmwareVersion, bleAddress, pairAddress, allPairs}
        self.keymap = keymap
        self.brightness = []

    def _with_transport(self, side, fn, serial=None):
        svc = self

        class T:
            def send_command(self, dest, cat, sub, payload=b"", timeout=1.0, **kw):
                h = svc.halves[side]
                if (cat, sub) == (C.CAT_SYSTEM, C.SYS_GET_FW_VERSION):
                    a, b, c = (int(x) for x in h["firmwareVersion"].split("."))
                    return [_Frame(bytes([0, a, b, c]))]
                if (cat, sub) == (C.CAT_BLE, C.BLE_GET_ADDRESS):
                    return [_Frame(_mac_bytes(h["bleAddress"]))]
                if (cat, sub) == (C.CAT_BLE, C.BLE_GET_PAIR_ADDRESS):
                    return [_Frame(_mac_bytes(h["pairAddress"]))]
                if (cat, sub) == (C.CAT_BLE, C.BLE_GET_ALL_PAIRS):
                    peers = h["allPairs"]
                    return [_Frame(bytes([len(peers)]) + b"".join(_mac_bytes(m) for m in peers))]
                return [_Frame(b"")]
        return fn(T(), 0x50, _Dev(side))

    def read_keymap(self, side="left", serial=None):
        return self.keymap

    def led_setting(self, side, setting, value):
        self.brightness.append((side, setting, value))
        return {"ok": True}


def _keymap(led_rows=None):
    return {"layers": {0: [(1, 4, b"\x01\x02"), (2, 4, b"\x03\x04")]},
            "led": {0: led_rows if led_rows is not None else [(0, 120, 255), (1, 200, 255)]},
            "layer_uuids": {0: "uuid-0"}, "layer_animations": {0: "solid"}}


def _halves(left_fw="3.35.4", right_fw="3.35.4"):
    return {"left": {"firmwareVersion": left_fw, "bleAddress": "FA:4A:56:71:5F:51",
                     "pairAddress": "DD:DB:65:D1:46:CA", "allPairs": ["DD:DB:65:D1:46:CA"]},
            "right": {"firmwareVersion": right_fw, "bleAddress": "DD:DB:65:D1:46:CA",
                      "pairAddress": "FA:4A:56:71:5F:51", "allPairs": ["FA:4A:56:71:5F:51"]}}


class _Plan:
    total_bytes, chunks, upload_image_id = 663552, 1296, 2
    target = {"createFirmware": "3.41.0"}


@pytest.fixture()
def wired(monkeypatch, tmp_path):
    """Stub the bootloader and the upload. `state` drives what the halves report."""
    svc = FakeSvc(_halves(), _keymap())
    in_boot = {"side": None}

    monkeypatch.setattr(P.rec, "find_recovery_ports",
                        lambda: ([_Dev(in_boot["side"])] if in_boot["side"] else []))
    monkeypatch.setattr(P.rec, "image_state", lambda port: {"images": [{"slot": 0}]})
    monkeypatch.setattr(P.rec, "read_running_image", lambda cat=None: {
        "state": "ok", "pidSide": in_boot["side"], "pidGeneration": "A",
        "images": [{"slot": 0, "hash": "arm-token", "createFirmware": "3.35.4"}]})
    monkeypatch.setattr(P.fw, "plan", lambda *a, **k: _Plan())

    # Entering the bootloader is a send_command the FakeSvc swallows, so the side is tracked here.
    orig = FakeSvc._with_transport

    def tracking(self, side, fn, serial=None):
        return orig(self, side, fn, serial)
    monkeypatch.setattr(FakeSvc, "_with_transport", tracking)

    def fake_flash(image, catalog, *, arm, progress=None, **kw):
        side = in_boot["side"]
        progress(512, 663552)
        progress(663552, 663552)
        svc.halves[side]["firmwareVersion"] = "3.41.0"     # the swap took
        in_boot["side"] = None                              # os reset -> application
        return {"written": 663552, "swap": "permanent", "hash": "target-hash"}

    return {"svc": svc, "in_boot": in_boot, "flash": fake_flash, "dir": tmp_path}


def _run(wired, targets, **kw):
    # `mcuboot.enter` is what puts a half into recovery; the stub mirrors that by setting in_boot
    # just before the port lookup, via a patched enter step.
    real_flash_one = P.flash_one_half

    def flash_one(svc, side, image, catalog, log, **kwargs):
        wired["in_boot"]["side"] = side
        return real_flash_one(svc, side, image, catalog, log, **kwargs)

    import openflow_backend.device.flash_procedure as mod
    orig = mod.flash_one_half
    mod.flash_one_half = flash_one
    try:
        return mod.run(wired["svc"], targets, [], log_dir=wired["dir"],
                       flash_fn=wired["flash"], **kw)
    finally:
        mod.flash_one_half = orig


def test_a_clean_both_halves_run_succeeds_and_writes_one_readable_log(wired):
    r = _run(wired, {"left": "kb_fwl.bin", "right": "kb_fwr.bin"})
    assert r["ok"] is True and not r["failures"]
    log = Path(r["log"])
    lines = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    assert lines[0]["step"] == "run.start" and lines[-1]["step"] == "run.end"
    assert lines[-1]["phase"] == "ok"
    steps = [x["step"] for x in lines]
    for required in ("preflight.capture", "preflight.verify", "mcuboot.enter", "identify",
                     "slot.erase", "upload", "swap.verify", "mcuboot.exit", "version.confirm",
                     "verify.compare"):
        assert required in steps, f"{required} missing from the log"
    assert "power cycle" not in log.read_text(encoding="utf-8").lower().replace(
        "no power cycle is needed", "")


def test_the_central_is_flashed_before_the_peripheral(wired):
    """Between the two flashes one half is verified on its OWN port, and the only mismatched
    configuration anyone has measured is a newer central with an older peripheral -- there the
    central reads perfectly and the peripheral's port goes hollow (SCRUM-107). Central-first
    verifies the half we know answers; peripheral-first would verify one nobody has observed."""
    r = _run(wired, {"left": "kb_fwl.bin", "right": "kb_fwr.bin"})
    lines = [json.loads(x) for x in Path(r["log"]).read_text(encoding="utf-8").splitlines() if x]
    order = [x["side"] for x in lines if x["step"] == "mcuboot.enter" and x["phase"] == "start"]
    assert order == ["left", "right"]


def test_the_preflight_backup_is_written_and_verified_before_anything_is_sent(wired):
    r = _run(wired, {"left": "kb_fwl.bin"})
    saved = json.loads((wired["dir"] / "preflight.json").read_text(encoding="utf-8"))
    assert saved["halves"]["left"]["allPairs"] == ["DD:DB:65:D1:46:CA"]
    assert saved["keymap"]["layers"]["0"], "the keymap must be in the backup"
    lines = [json.loads(x) for x in Path(r["log"]).read_text(encoding="utf-8").splitlines() if x]
    first_write = next(i for i, x in enumerate(lines) if x["step"] == "mcuboot.enter")
    verified = next(i for i, x in enumerate(lines)
                    if x["step"] == "preflight.verify" and x["phase"] == "ok")
    assert verified < first_write, "nothing may be sent before the backup is verified"


def test_a_changed_bond_table_is_a_failure_and_says_what_changed(wired):
    real = P._identity
    calls = {"n": 0}

    def drifting(svc, side):
        got = real(svc, side)
        calls["n"] += 1
        if calls["n"] > 2 and side == "left":        # after the flash, the bond is gone
            got["allPairs"] = []
        return got
    P._identity = drifting
    try:
        r = _run(wired, {"left": "kb_fwl.bin"})
    finally:
        P._identity = real
    assert r["ok"] is False
    assert any("bond table" in f for f in r["failures"])
    assert any("split-link repair" in f for f in r["failures"])


def test_an_led_difference_across_a_version_change_is_a_NOTE_not_a_failure(wired):
    """The LED payload changed in 3.41. A map captured on 3.35.4 and re-read on 3.41.0 differs
    because the FORMAT changed. Calling that corruption declares a perfect flash broken."""
    svc = wired["svc"]
    original = svc.read_keymap

    def shifting(side="left", serial=None):
        if svc.halves["left"]["firmwareVersion"] == "3.41.0":
            return _keymap(led_rows=[(0, 300, 128), (1, 20, 64)])     # re-encoded, not lost
        return original(side, serial)
    svc.read_keymap = shifting

    r = _run(wired, {"left": "kb_fwl.bin"})
    assert r["ok"] is True, "a format change must not fail the run"
    assert not r["failures"]
    assert any("LED" in a and "NOT" in a for a in r["advisories"]), r["advisories"]


def test_an_led_difference_WITHOUT_a_version_change_is_a_real_failure(wired):
    """Same version in and out: nothing should have moved, so a difference is real."""
    svc = wired["svc"]
    svc.halves["left"]["firmwareVersion"] = "3.41.0"
    svc.halves["right"]["firmwareVersion"] = "3.41.0"
    original = svc.read_keymap
    seen = {"n": 0}

    def shifting(side="left", serial=None):
        seen["n"] += 1
        if seen["n"] > 1:
            return _keymap(led_rows=[(0, 999, 1)])
        return original(side, serial)
    svc.read_keymap = shifting

    r = _run(wired, {"left": "kb_fwl.bin"})
    assert r["ok"] is False
    assert any("LED map differs" in f for f in r["failures"])


def test_changed_bindings_are_reported_by_position(wired):
    svc = wired["svc"]
    original = svc.read_keymap
    seen = {"n": 0}

    def shifting(side="left", serial=None):
        seen["n"] += 1
        if seen["n"] > 1:
            km = _keymap()
            km["layers"] = {0: [(1, 4, b"\x01\x02"), (2, 4, b"\xff\xff")]}
            return km
        return original(side, serial)
    svc.read_keymap = shifting

    r = _run(wired, {"left": "kb_fwl.bin"})
    assert r["ok"] is False
    assert any("position" in f and "[2]" in f for f in r["failures"]), r["failures"]


def test_a_failure_mid_run_still_leaves_a_log_that_ends_where_it_stopped(wired):
    def exploding(image, catalog, *, arm, progress=None, **kw):
        progress(512, 663552)
        raise OSError("the cable was pulled")
    wired["flash"] = exploding

    r = _run(wired, {"left": "kb_fwl.bin"})
    assert r["ok"] is False and "cable was pulled" in r["summary"]
    lines = [json.loads(x) for x in Path(r["log"]).read_text(encoding="utf-8").splitlines() if x]
    assert lines[-1]["step"] == "run.end" and lines[-1]["phase"] == "fail"
    steps = [x["step"] for x in lines]
    assert "slot.erase" in steps, "the erase completed and must be recorded"
    assert "version.confirm" not in steps, "nothing after the failure may claim to have run"


def test_brightness_is_restored_so_dim_leds_are_not_mistaken_for_dead_ones(wired):
    r = _run(wired, {"left": "kb_fwl.bin", "right": "kb_fwr.bin"})
    assert r["ok"] is True
    assert ("left", "max_brightness", 100) in wired["svc"].brightness
    assert ("right", "max_brightness", 100) in wired["svc"].brightness


def test_the_rendered_log_is_readable_text_with_no_json(wired):
    log = P.RunLog(wired["dir"] / "r.log", {"sides": ["left"]})
    log.event("upload", "ok", side="left", took_ms=57600)
    log.advise("an expected difference")
    text = log.render()
    assert "Writing the firmware [left]" in text and "(57600 ms)" in text
    assert "an expected difference" in text and "{" not in text


def test_a_log_read_back_off_disk_renders_identically_to_the_live_run(wired):
    """The user's evidence is the FILE. If the on-disk log rendered differently from what they
    saw on screen, the evidence and the experience would disagree."""
    r = _run(wired, {"left": "kb_fwl.bin"})
    lines = [json.loads(x) for x in Path(r["log"]).read_text(encoding="utf-8").splitlines() if x]
    text = P.render_events(lines)
    assert "Backing up what is on the keyboard" in text
    assert "Writing the firmware [left]" in text
    # The log ends with "Finished" and then the verdict indented beneath it, so the verdict is
    # the last thing the user reads.
    tail = text.splitlines()[-2:]
    assert tail[0].endswith("Finished")
    assert tail[1].strip() == "firmware written and verified; the keyboard matches its backup"
    assert "{" not in text and "}" not in text


def test_every_line_is_flushed_as_it_is_written(tmp_path):
    """The log exists for the moment the process dies. Nothing may sit in a buffer."""
    log = P.RunLog(tmp_path / "r.log", {"sides": ["left"]})
    log.event("upload", "start", side="left")
    on_disk = [json.loads(x) for x in (tmp_path / "r.log").read_text(encoding="utf-8").splitlines() if x]
    assert [e["step"] for e in on_disk] == ["run.start", "upload"], (
        "the events must already be on disk before the next one is written")


def test_the_service_lock_is_held_for_the_whole_run(wired):
    """The live-status tick runs under this lock. If it can take it mid-procedure it can put
    commands on a port between our frames, which is what cost a keymap flash an ack in 2026-09.
    """
    import threading
    svc = wired["svc"]
    svc._lock = threading.RLock()
    taken_by_other_thread = []

    def watcher():
        # A different thread, as the tick is. It must NOT get the lock while the run is going.
        if svc._lock.acquire(blocking=False):
            taken_by_other_thread.append(True)
            svc._lock.release()

    original = P.capture_preflight

    def capture_then_probe(*a, **k):
        t = threading.Thread(target=watcher)
        t.start()
        t.join()
        return original(*a, **k)

    P.capture_preflight = capture_then_probe
    try:
        r = _run(wired, {"left": "kb_fwl.bin"})
    finally:
        P.capture_preflight = original
    assert r["ok"] is True
    assert not taken_by_other_thread, "another thread took the service lock during the procedure"


def test_cached_transports_are_dropped_when_a_half_comes_back(wired):
    """A half that has been through the bootloader re-enumerates and may return on a different
    COM port. A stale cached handle is the likeliest reason a run would need a restart to see
    the board again, which would count as going off-script."""
    svc = wired["svc"]
    svc._transports = {"COM30": object(), "COM29": object()}
    dropped = []
    svc._drop = lambda port: dropped.append(port)
    r = _run(wired, {"left": "kb_fwl.bin"})
    assert r["ok"] is True
    assert "COM30" in dropped and "COM29" in dropped


def test_identify_retries_instead_of_probing_the_port_twice(monkeypatch):
    """The first real run died here. A separate port probe followed by read_running_image opened
    the bootloader's port twice within milliseconds, and Windows refuses the second open right
    after the bootloader enumerates. One mechanism, retried."""
    calls = {"n": 0}

    def flaky(catalog=None):
        calls["n"] += 1
        if calls["n"] < 3:
            return {"state": "error", "detail": "neither port answered SMP"}
        return {"state": "ok", "pidSide": "left", "port": "COM27",
                "images": [{"slot": 0, "hash": "arm"}]}

    monkeypatch.setattr(P.rec, "read_running_image", flaky)
    monkeypatch.setattr(P.time, "sleep", lambda _s: None)
    state = P._identify_in_bootloader("left", [])
    assert state["port"] == "COM27" and calls["n"] == 3


def test_identify_refuses_when_the_bootloader_reports_the_other_side(monkeypatch):
    monkeypatch.setattr(P.rec, "read_running_image",
                        lambda catalog=None: {"state": "ok", "pidSide": "right", "port": "COM27"})
    monkeypatch.setattr(P.time, "sleep", lambda _s: None)
    with pytest.raises(P.fw.UploadRefused, match="reports itself as right"):
        P._identify_in_bootloader("left", [])


def test_a_failed_run_does_not_leave_a_half_stranded_in_the_bootloader(wired, monkeypatch):
    """A half left in MCUboot does not type and shows no lights, which to a user looks exactly
    like a brick. The first real run left one there and it had to be recovered by hand."""
    reset = []
    monkeypatch.setattr(P.rec, "os_reset", lambda port: reset.append(port))
    monkeypatch.setattr(P, "_answering_recovery_port", lambda side, timeout=30.0: "COM27")
    # Still in the bootloader when the failure lands.
    monkeypatch.setattr(P.rec, "find_recovery_ports", lambda: [_Dev("left")])

    def exploding(image, catalog, *, arm, progress=None, **kw):
        raise OSError("something went wrong mid-write")
    wired["flash"] = exploding

    r = _run(wired, {"left": "kb_fwl.bin"})
    assert r["ok"] is False
    assert reset == ["COM27"], "the stranded half must be reset back to the application"
    text = Path(r["log"]).read_text(encoding="utf-8")
    assert "should return to normal on its own" in text


def test_the_wait_for_the_half_to_come_back_re_sends_the_reset(monkeypatch):
    """A reset sent right after an upload often does not take -- the bootloader is still busy
    with what the trailer armed. Measured on a real downgrade: the half ignored the first reset,
    was still in MCUboot 45 s later, and returned minutes after a second one, running the new
    firmware correctly the whole time. Waiting passively on one reset is what turned that perfect
    flash into a reported failure.

    Real clock, tiny values: patching time.monotonic would patch it for the whole process.
    """
    resets = []
    monkeypatch.setattr(P.rec, "find_recovery_ports",
                        lambda: ([] if resets else [_Dev("left")]))
    monkeypatch.setattr(P, "_answering_recovery_port", lambda side, timeout=10.0: "COM27")
    monkeypatch.setattr(P.rec, "os_reset", lambda port: resets.append(port))
    monkeypatch.setattr(P, "_identity", lambda svc, side: {"firmwareVersion": "3.35.4"})

    got = P._await_application(object(), "left", None, timeout=30.0, resend_every=0.0)
    assert got == "3.35.4"
    assert resets == ["COM27"], "the reset must be re-sent, not merely waited on"


def test_the_wait_gives_up_eventually_rather_than_hanging(monkeypatch):
    """Patience is not credulity. It must return None, not spin forever."""
    monkeypatch.setattr(P.rec, "find_recovery_ports", lambda: [_Dev("left")])
    monkeypatch.setattr(P, "_answering_recovery_port",
                        lambda side, timeout=10.0: (_ for _ in ()).throw(OSError("no port")))
    assert P._await_application(object(), "left", None, timeout=0.1) is None
