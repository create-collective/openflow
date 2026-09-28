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

    def restore_lighting(self, side="left"):
        self.lighting_restored = getattr(self, "lighting_restored", 0) + 1
        return {"ok": True, "side": side, "layers": 1}


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
    # A failed run re-sends the reset to a stranded half for five minutes of wall clock, and the
    # reset itself opens a real COM port. Neither belongs in a unit test: the wait is zeroed and
    # the reset stubbed here, and the tests about recovery patch what they assert on.
    monkeypatch.setattr(P, "RECOVERY_WAIT", 0.0)
    monkeypatch.setattr(P.rec, "os_reset", lambda port: None)
    # A failed upload reads the bootloader's console, which opens real COM ports.
    monkeypatch.setattr(P, "_bootloader_console", lambda side, seconds=4.0: "")

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


def test_the_upload_records_how_its_chunks_behaved(wired, monkeypatch):
    """The first supervised runs uploaded in 206 s and 124 s what had been hand-measured at 57 s
    and 78 s. A wider per-chunk timeout cannot cost time on a chunk that answers quickly, so the
    difference is the device stalling -- but "a few long pauses" and "everything slower" want
    different explanations, and nothing in the log could tell them apart. One summary line per
    upload, so the next real run answers it instead of the next argument.
    """
    clock = {"t": 0.0}
    monkeypatch.setattr(P.time, "monotonic", lambda: clock["t"])

    def slow_flash(image, catalog, *, arm, progress=None, **kw):
        side = wired["in_boot"]["side"]
        clock["t"] += 9.0                               # the slot erase, before chunk one
        progress(512, 663552)
        for i in range(2, 12):                          # ten ordinary chunks at 40 ms
            clock["t"] += 0.04
            progress(512 * i, 663552)
        clock["t"] += 7.5                               # and one long stall
        progress(663552, 663552)
        wired["svc"].halves[side]["firmwareVersion"] = "3.41.0"
        wired["in_boot"]["side"] = None
        return {"written": 663552, "swap": "permanent", "hash": "target-hash"}

    wired["flash"] = slow_flash
    r = _run(wired, {"left": "kb_fwl.bin"})
    assert r["ok"] is True
    lines = [json.loads(x) for x in Path(r["log"]).read_text(encoding="utf-8").splitlines() if x]
    note = next(x for x in lines if x["step"] == "upload" and x["phase"] == "note")
    assert note["chunks"] == 11                         # the erase is not one of them
    assert note["medianMs"] == 40
    assert note["over"] == 1 and note["stallMs"] == 7500
    assert note["slowest"] == [{"offset": 663552, "ms": 7500}]
    assert "1 over 1 s, 8 s of the upload spent waiting on them" in note["detail"]


def test_an_image_whose_release_declared_no_version_still_finishes_clean(wired, monkeypatch):
    """Everything before NayaFlow 1.14.5 shipped without a declared firmware version.

    The final step compared what the half reports against the image's expected version number.
    With no expected number, that comparison failed for EVERY such image -- after a write already
    verified by hash -- and reported a failed run on a keyboard running the new firmware
    perfectly. Reporting failure on a flash that landed is the precise thing this procedure was
    built to stop doing, so there is nothing to compare against, it says so and the run passes.
    """
    class _Plan:
        target = {"createFirmware": None, "versionLabel": "NayaFlow 1.3.8 to 1.6.10"}
        total_bytes, chunks, upload_image_id = 663552, 1296, 1

    monkeypatch.setattr(P.fw, "plan", lambda *a, **k: _Plan())
    r = _run(wired, {"left": "kb_fwl.bin"})

    assert r["ok"] is True, r["summary"]
    assert not r["failures"]
    assert any("declared no firmware version" in a for a in r["advisories"])
    lines = [json.loads(x) for x in Path(r["log"]).read_text(encoding="utf-8").splitlines() if x]
    confirm = [x for x in lines if x["step"] == "version.confirm"]
    assert any(x["phase"] == "note" for x in confirm), "the note belongs on the step it is about"
    assert not any(x["phase"] == "fail" for x in confirm)


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


def test_the_cached_firmware_version_is_dropped_too(wired):
    """Identity is read once per port and kept, because none of it changes while a half is
    plugged in -- except across the one operation that changes exactly that. Without this the
    app quotes the OLD version after a successful update until the keyboard is unplugged: the
    flash worked and every screen says it did not."""
    svc = wired["svc"]
    forgotten = []
    svc.forget_identity = lambda port=None: forgotten.append(port)
    r = _run(wired, {"left": "kb_fwl.bin"})
    assert r["ok"] is True
    assert forgotten, "the service was never told its identity cache is now stale"


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
    # The recovery then waits the way version.confirm does, re-sending the reset; that loop is
    # tested on its own. Here it is stood in for, so this test stays about the recovery's
    # decision to reset and what it reports.
    waited = []
    monkeypatch.setattr(P, "_await_application",
                        lambda svc, side, log=None, **kw: (waited.append(side), "3.35.4")[1])

    def exploding(image, catalog, *, arm, progress=None, **kw):
        raise OSError("something went wrong mid-write")
    wired["flash"] = exploding

    r = _run(wired, {"left": "kb_fwl.bin"})
    assert r["ok"] is False
    assert reset[:1] == ["COM27"], "the stranded half must be reset back to the application"
    assert waited == ["left"], "and then waited for, re-sending, rather than left dark"
    text = Path(r["log"]).read_text(encoding="utf-8")
    assert "back in the application, running 3.35.4" in text


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


def test_the_stall_summary_and_the_swap_state_survive_a_post_upload_failure(wired, monkeypatch):
    """On 2026-09-22 an upload reached 100%, the bootloader then stayed silent for 100 s carrying
    out the swap, the post-upload read gave up at 90 s and raised -- and the run log had neither
    the chunk-timing summary nor any step after "100%", because both were written after
    flash() returned. The UI showed 100% and then nothing for two minutes. Both now land from
    the progress callback the instant the last chunk is acknowledged."""
    def uploads_then_dies(image, catalog, *, arm, progress=None, **kw):
        progress(512, 663552)                     # erase done
        for sent in range(1024, 663553, 512):     # the whole image, timed
            progress(sent, 663552)
        raise P.fw.UploadRefused("the upload completed but the bootloader did not answer")
    wired["flash"] = uploads_then_dies
    # The failure leaves the half "in the bootloader" as far as the stub is concerned, so the
    # recovery would wait on the real five-minute re-send loop; that loop has its own tests.
    monkeypatch.setattr(P, "_await_application", lambda svc, side, log=None, **kw: "3.35.4")

    r = _run(wired, {"left": "kb_fwl.bin"})
    assert r["ok"] is False
    lines = [json.loads(x) for x in Path(r["log"]).read_text(encoding="utf-8").splitlines() if x]
    summary = [e for e in lines if e["step"] == "upload" and e["phase"] == "note"]
    assert summary and summary[0]["chunks"] == 1295, "the stall summary must be in the log"
    started = [e for e in lines if e["step"] == "swap.verify" and e["phase"] == "start"]
    assert started and "carrying out the swap" in started[0]["detail"]
    order = [e["step"] + ":" + e["phase"] for e in lines]
    assert order.index("swap.verify:start") < order.index("run.end:fail")


def test_recovery_says_so_when_the_half_never_comes_back(wired, monkeypatch):
    monkeypatch.setattr(P.rec, "os_reset", lambda port: None)
    monkeypatch.setattr(P, "_answering_recovery_port", lambda side, timeout=30.0: "COM27")
    monkeypatch.setattr(P.rec, "find_recovery_ports", lambda: [_Dev("left")])
    monkeypatch.setattr(P, "_await_application", lambda svc, side, log=None, **kw: None)

    def exploding(image, catalog, *, arm, progress=None, **kw):
        raise OSError("mid-write")
    wired["flash"] = exploding

    r = _run(wired, {"left": "kb_fwl.bin"})
    text = Path(r["log"]).read_text(encoding="utf-8")
    assert "still in the bootloader after five minutes" in text
    assert "power cycle will bring it back" in text


def test_recovery_does_not_blame_the_bootloader_for_a_half_that_left_it(wired, monkeypatch):
    """2026-09-23: the reset took the half out of the bootloader and it never came back on USB.
    The message must say that, and ask for a cable replug, not a power cycle."""
    monkeypatch.setattr(P.rec, "os_reset", lambda port: None)
    monkeypatch.setattr(P, "_answering_recovery_port", lambda side, timeout=30.0: "COM27")
    looks = {"n": 0}

    def ports():
        looks["n"] += 1
        return [_Dev("left")] if looks["n"] == 1 else []      # in the bootloader, then gone
    monkeypatch.setattr(P.rec, "find_recovery_ports", ports)
    monkeypatch.setattr(P, "_await_application", lambda svc, side, log=None, **kw: None)

    def exploding(image, catalog, *, arm, progress=None, **kw):
        raise OSError("mid-write")
    wired["flash"] = exploding

    r = _run(wired, {"left": "kb_fwl.bin"})
    text = Path(r["log"]).read_text(encoding="utf-8")
    assert "left the bootloader but has not come back on USB" in text
    assert "still in the bootloader after five minutes" not in text


def test_a_keyboard_flash_refuses_while_a_module_is_docked(wired, monkeypatch):
    """SCRUM-114: NayaFlow's rule, 'Please ensure NO modules are connected to both of your Create
    halves'. Every earlier flash had empty bays by coincidence."""
    monkeypatch.setattr(P, "docked_module",
                        lambda svc, side: {"type": "Touch", "address": 0x11} if side == "right" else None)
    calls = []
    wired["flash"] = lambda *a, **k: calls.append(1)
    r = _run(wired, {"left": "kb_fwl.bin"})
    assert r["ok"] is False and "Touch is docked on the right half" in r["summary"]
    assert calls == []


def test_the_lights_are_put_back_after_the_flash(wired):
    """A half that has been through the bootloader comes back with a runtime lighting state
    that is not what it stores: on 2026-09-22 one half plain white while the other stayed orange,
    with the stored maps byte-identical before and after. Rewriting the layer list put it back
    the moment it was sent, so the procedure does that itself, after the halves are back and
    before the comparison."""
    r = _run(wired, {"left": "kb_fwl.bin", "right": "kb_fwr.bin"})
    assert r["ok"] is True
    assert wired["svc"].lighting_restored == 1
    lines = [json.loads(x) for x in Path(r["log"]).read_text(encoding="utf-8").splitlines() if x]
    steps = [(e["step"], e["phase"]) for e in lines]
    assert ("lighting.restore", "ok") in steps
    assert steps.index(("lighting.restore", "ok")) < steps.index(("verify.compare", "start"))


def test_a_lighting_restore_failure_does_not_fail_the_flash(wired):
    def boom(side="left"):
        raise OSError("port busy")
    wired["svc"].restore_lighting = boom
    r = _run(wired, {"left": "kb_fwl.bin"})
    assert r["ok"] is True, "cosmetic; the flash is verified regardless"
    assert "a power cycle also restores the lights" in Path(r["log"]).read_text(encoding="utf-8")


# --- what the first UI-driven UPGRADE taught the comparison, 2026-09-22 --------------------- #
# Both halves 3.35.4 -> 3.41.0. The primary bank was byte-identical before and after; the run
# still reported "layer 0 bindings differ at 74 positions". 3.35.4 does not report the second
# bank at all (its read stops at 0x51) and 3.41.0 returns the whole bank padded with NONE, so a
# double-tap key that was on the board throughout was invisible before and present after.

def _rows(*recs):
    return [[p, t, h] for p, t, h in recs]


def test_bindings_absent_from_one_read_count_as_none():
    before = _rows((1, 1, "04000700"))
    after = _rows((1, 1, "04000700"), (83, 7, ""), (84, 7, ""))     # the bank, padded
    assert P._differing_positions(before, after) == []


def _compare(before_layers, after_layers, *, version_changed, tmp_path):
    log = P.RunLog(tmp_path / "c.log")
    before = {"halves": {}, "keymap": {"layers": before_layers, "led": {}}}
    after = {"halves": {}, "keymap": {"layers": after_layers, "led": {}}}
    P.compare_preflight(before, after, version_changed=version_changed, log=log)
    return log


def test_a_second_bank_the_old_firmware_could_not_report_is_an_advisory_across_versions(tmp_path):
    dt = "c80003010101c80000000000000000000500070000000000"           # the double-tap record
    log = _compare({"0": _rows((1, 1, "04000700"))},
                   {"0": _rows((1, 1, "04000700"), (137, 16, dt))},
                   version_changed=True, tmp_path=tmp_path)
    assert log.failures == []
    assert log.advisories and "older firmware does not report these slots" in log.advisories[0]


def test_the_same_second_bank_difference_within_one_version_is_a_failure(tmp_path):
    dt = "c80003010101c80000000000000000000500070000000000"
    log = _compare({"0": _rows((1, 1, "04000700"))},
                   {"0": _rows((1, 1, "04000700"), (137, 16, dt))},
                   version_changed=False, tmp_path=tmp_path)
    assert log.failures and "double-tap / tap+hold" in log.failures[0]


def test_a_primary_bank_difference_is_a_failure_even_across_versions(tmp_path):
    log = _compare({"0": _rows((1, 1, "04000700"))},
                   {"0": _rows((1, 1, "05000700"))},
                   version_changed=True, tmp_path=tmp_path)
    assert log.failures and "[1]" in log.failures[0]


def test_the_procedure_waits_for_both_halves_to_re_link(wired, monkeypatch):
    """When the second half comes back on matching firmware the halves re-link and the central
    drops off USB for a moment. Three steps ran in that gap on 2026-09-22 and reported the left
    half missing. The procedure now waits for both before it touches the keyboard as a whole."""
    real = P._identity
    calls = {"n": 0}

    def flaky(svc, side):
        calls["n"] += 1
        if side == "left" and calls["n"] in (5, 6):      # the moment after the last flash
            raise RuntimeError("No left device found")
        return real(svc, side)
    monkeypatch.setattr(P, "_identity", flaky)
    monkeypatch.setattr(P, "SETTLE_WAIT", 20.0)

    r = _run(wired, {"left": "kb_fwl.bin", "right": "kb_fwr.bin"})
    assert r["ok"] is True, r
    text = Path(r["log"]).read_text(encoding="utf-8")
    assert "both halves answering; the keyboard has re-linked" in text
    assert "No left device found" not in text, "nothing after the settle may report it missing"


# --- a half whose bootloader dropped the vendor resource (2026-09-29) ------------------------ #

def _lines(r):
    return [json.loads(x) for x in Path(r["log"]).read_text(encoding="utf-8").splitlines()
            if x.strip()]


def test_image_only_mode_uploads_the_image_and_asks_for_a_permanent_swap(wired, monkeypatch):
    """OPENFLOW_FIRMWARE_IMAGE_ONLY=1: no vendor trailer, and the bootloader is asked to schedule
    a PERMANENT swap -- a test swap would revert on the next reset."""
    seen = {}
    real = wired["flash"]

    def spy(image, catalog, **kw):
        seen.update(kw)
        return real(image, catalog, **kw)
    wired["flash"] = spy
    monkeypatch.setenv("OPENFLOW_FIRMWARE_IMAGE_ONLY", "1")
    r = _run(wired, {"right": "kb_fwr.bin"})
    assert r["ok"] is True, r
    assert seen["vendor_trailer"] is False and seen["confirm"] is True
    assert any("image-only upload" in (x.get("detail") or "") for x in _lines(r))


def test_the_vendor_trailer_stays_the_default(wired, monkeypatch):
    seen = {}
    real = wired["flash"]

    def spy(image, catalog, **kw):
        seen.update(kw)
        return real(image, catalog, **kw)
    wired["flash"] = spy
    monkeypatch.delenv("OPENFLOW_FIRMWARE_IMAGE_ONLY", raising=False)
    r = _run(wired, {"right": "kb_fwr.bin"})
    assert r["ok"] is True
    assert seen["vendor_trailer"] is True and seen["confirm"] is False


def test_a_failed_upload_records_what_the_bootloader_said(wired, monkeypatch):
    """The bootloader's console is the only account of why an image was not taken, and it is
    read before the failure path resets the half out of the bootloader."""
    def refused(image, catalog, **kw):
        raise P.fw.UploadRefused("after upload, slot 1 reports no image")
    wired["flash"] = refused
    monkeypatch.setattr(P, "_bootloader_console",
                        lambda side, seconds=4.0: "[COM7] I: Image in the secondary slot is not valid!")
    r = _run(wired, {"right": "kb_fwr.bin"})
    assert r["ok"] is False
    said = [x for x in _lines(r) if x["step"] == "bootloader.console"]
    assert said and "secondary slot is not valid" in said[0]["detail"]
