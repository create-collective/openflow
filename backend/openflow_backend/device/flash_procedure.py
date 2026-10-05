"""Firmware flashing as a PROCEDURE: preflight capture, ordered steps, an audit log, and a
comparison of what is on the board afterwards against what was there before.

Owner requirement, 2026-09-20 (SCRUM-108). A flash is not "upload bytes and hope". The user picks
one side or both, picks a version, clicks Go, and from that moment every step is written to disk:
what was captured, what was sent, how long it took, what came back, and finally an explicit
verdict. Two reasons, both learned the hard way:

  * the user must never be in doubt about what is happening, because the one thing that turns a
    working flash into a brick is unplugging in the middle of it, and the upload's FIRST chunk
    blocks for 6-17 s while the bootloader erases 648 KiB -- the exact moment a frozen progress
    bar invites a cable pull;
  * if something does go wrong the user must hold definitive evidence to hand to us or to Naya.
    NayaFlow once reported failure on this owner's board when the flash had actually landed, and
    only its own log said what was really happening.

The log is append-only and flushed on every line. A log buffered in memory is worthless for
exactly the cases it exists for: a crash, a power loss, a cable pulled.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
**No mid-run verification of the half that has not been flashed yet.** Between the two flashes of
a two-half upgrade the halves are on different firmware, and in that state the un-flashed half
answers the handshake and then returns EMPTY payloads on its own port (SCRUM-107). Reading it
there would log a false failure on a flash that is going perfectly. So each half is verified
immediately after ITS OWN flash (which reads correctly), and the full both-halves comparison is
deferred until both are on the target version. Nothing in this module needs SCRUM-107 fixed.

**No power cycle.** `os reset` on the port that answers SMP returns a half to the application in
about 8 seconds (measured, both halves, 2026-09-20). Earlier claims that a power cycle was
required came from sending the reset to the bootloader's log port, which accepts the open,
swallows the frame and reports nothing.

**Halves are flashed ONE AT A TIME.** Not a technical limit -- each half has its own port and its
own bootloader, and `find_recovery_ports` tags each by side from its USB product id, so they could
run concurrently. Sequential costs about a minute and buys a failure confined to one half with the
other known-good, plus a log that reads as one clear narrative instead of two interleaved ones.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import firmware_upload as fw
from . import recovery as rec
from .keymap_read import NONE_BEH, SECOND_BANK

# The steps, in order, with the words the user sees. Named here rather than inline so the UI and
# the log agree and neither drifts.
STEP_LABELS = {
    "run.start": "Starting",
    "preflight.capture": "Backing up what is on the keyboard",
    "preflight.verify": "Checking the backup reads back",
    "mcuboot.enter": "Putting the half into its bootloader",
    "mcuboot.port": "Finding the bootloader",
    "identify": "Confirming which half this is and what it runs",
    "slot.erase": "Preparing the flash (this takes a few seconds)",
    "upload": "Writing the firmware",
    "swap.verify": "Checking what landed",
    "mcuboot.exit": "Restarting the half",
    "version.confirm": "Restarting and confirming the new version (can take a few minutes)",
    "halves.settle": "Waiting for both halves to re-link",
    "brightness.restore": "Restoring LED brightness",
    "lighting.restore": "Putting the lights back to their stored colors",
    "verify.compare": "Comparing the keyboard against the backup",
    "run.end": "Finished",
    # The module firmware procedure (device/module_procedure.py) writes to the same kind of log.
    "preflight.check": "Checking the keyboard is ready for a module update",
    "bundle.check": "Checking which module firmware the keyboard holds",
    "bundle.restart": "Waiting for the keyboard to restart after the upload",
    "bundle.verify": "Checking the module firmware the keyboard now holds",
    "module.program": "Programming the module (its lights go out for a few seconds)",
    "module.restart": "Waiting for the keyboard to restart after programming",
    "module.verify": "Confirming the module's new version",
    "replug": "Unplug the left half's USB cable and plug it back in",
}


class RunLog:
    """An append-only, flushed-per-line JSONL log of one flash run.

    Every line is written AND flushed AND fsynced before the next step begins. That is
    deliberately more expensive than buffering: the whole point of this file is to still be
    truthful after the event that stopped the run, and steps are seconds apart, not microseconds.
    Progress inside the upload is throttled by the caller so this stays cheap.
    """

    def __init__(self, path: Path, meta: dict | None = None, on_event=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        self._t0 = time.monotonic()
        self.events: list[dict] = []
        self.failures: list[str] = []
        self.advisories: list[str] = []
        # A live subscriber (device/flash_runs.Run.publish) gets every event as it is written, so
        # the browser and the file cannot tell different stories about the same run. It is handed
        # the event AFTER the line is on disk: the file is the evidence, and a subscriber that
        # throws must not be able to cost us a log line.
        self._on_event = on_event
        self.event("run.start", "ok", **(meta or {}))

    def event(self, step: str, phase: str, side: str | None = None,
              detail: str | None = None, **extra) -> dict:
        e = {"ts": datetime.now().isoformat(timespec="milliseconds"),
             "elapsed_ms": int((time.monotonic() - self._t0) * 1000),
             "step": step, "label": STEP_LABELS.get(step, step), "phase": phase}
        if side:
            e["side"] = side
        if detail:
            e["detail"] = detail
        e.update(extra)
        self.events.append(e)
        self._write(e)
        if self._on_event is not None:
            try:
                self._on_event(e)
            except Exception:                       # noqa: BLE001 -- a watcher never stops a flash
                pass
        return e

    def _write(self, e: dict) -> None:
        self._fh.write(json.dumps(e, default=str) + "\n")
        self._fh.flush()
        try:
            os.fsync(self._fh.fileno())
        except OSError:
            pass           # a filesystem that cannot fsync is not a reason to abort a flash

    @contextmanager
    def step(self, step: str, side: str | None = None, **extra):
        """Log start/ok/fail around a step, with its duration, and never swallow the error."""
        self.event(step, "start", side=side, **extra)
        t0 = time.monotonic()
        try:
            yield
        except Exception as e:                      # noqa: BLE001 -- logged, then re-raised
            self.event(step, "fail", side=side, detail=f"{type(e).__name__}: {e}",
                       took_ms=int((time.monotonic() - t0) * 1000))
            raise
        self.event(step, "ok", side=side, took_ms=int((time.monotonic() - t0) * 1000))

    def fail(self, what: str) -> None:
        self.failures.append(what)
        self.event("verify.compare", "fail", detail=what)

    def advise(self, what: str, step: str = "verify.compare") -> None:
        """Something the user should be told that must NOT fail the run -- see compare_preflight.

        `step` is which line of the procedure it belongs to. It was fixed at verify.compare,
        which was right while comparisons were the only source of advisories and wrong as soon
        as another step had something to say that is not a failure.
        """
        self.advisories.append(what)
        self.event(step, "note", detail=what)

    def finish(self, ok: bool, summary: str) -> dict:
        verdict = {"ok": ok, "summary": summary, "failures": list(self.failures),
                   "advisories": list(self.advisories), "log": str(self.path)}
        self.event("run.end", "ok" if ok else "fail", detail=summary,
                   failures=self.failures, advisories=self.advisories)
        try:
            self._fh.close()
        except Exception:
            pass
        return verdict

    def render(self) -> str:
        """The log as text a user can read, and paste to us. Same content, no JSON."""
        return render_events(self.events)


def render_events(events: list[dict]) -> str:
    """Structured events as text a user can read and paste to us. No JSON.

    A module-level function, not just a method, because the user's evidence is the FILE. A log
    read back off disk must render identically to the live run that wrote it, and the only way to
    guarantee that is for both to go through here.
    """
    out = []
    for e in events:
        # `action` is a step only the user can do (the module procedure's cable replug).
        mark = {"start": "  ", "ok": "OK", "fail": "!!", "note": "**",
                "action": ">>"}.get(e.get("phase"), "  ")
        side = f" [{e['side']}]" if e.get("side") else ""
        took = f" ({e['took_ms']} ms)" if e.get("took_ms") is not None else ""
        label = e.get("label") or e.get("step", "")
        line = f"{e.get('ts', '')}  {mark} {label}{side}{took}"
        if e.get("detail"):
            line += "\n" + " " * 26 + str(e["detail"])
        out.append(line)
    return "\n".join(out)


# --- preflight ------------------------------------------------------------------------------ #

def capture_preflight(svc, sides: tuple[str, ...], log: RunLog, run_dir: Path) -> dict:
    """Read and persist everything worth comparing afterwards, BEFORE anything is written.

    The LEFT half owns the whole board's keymap and LED map -- a read goes to dest 0x50 and the
    right half has none of its own -- so those are captured once, from the left, regardless of
    which side is being flashed.
    """
    cap: dict = {"at": datetime.now().isoformat(timespec="seconds"), "halves": {}}

    for side in ("left", "right"):
        try:
            cap["halves"][side] = _identity(svc, side)
        except Exception as e:                      # noqa: BLE001 -- recorded, not fatal
            cap["halves"][side] = {"error": f"{type(e).__name__}: {e}"}
        log.event("preflight.capture", "ok", side=side, captured=cap["halves"][side])

    try:
        cap["keymap"] = _keymap(svc)
        log.event("preflight.capture", "ok", side="left",
                  detail="keymap and LED map",
                  layers={str(k): len(v) for k, v in cap["keymap"]["layers"].items()})
    except Exception as e:                          # noqa: BLE001
        cap["keymap"] = {"error": f"{type(e).__name__}: {e}"}
        log.event("preflight.capture", "fail", side="left", detail=str(cap["keymap"]["error"]))

    path = run_dir / "preflight.json"
    path.write_text(json.dumps(cap, indent=1, default=str), encoding="utf-8")
    log.event("preflight.capture", "ok", detail=f"saved {path.name}",
              artifact=str(path), sha256=_sha_file(path))
    return cap


def _identity(svc, side: str) -> dict:
    """Firmware, serial, and the BLE identity of one half. `allPairs` is the bond table and is
    the ONLY one of these that tells the truth about the split link: on the warranty board both
    halves reported mutually correct pair ADDRESSES through a completely dead link."""
    from .._vendor.nayactl import constants as C

    def go(t, dest, dev):
        def payload(cat, sub):
            got = [f for f in t.send_command(dest, cat, sub, timeout=3.0) if f.valid]
            raw = bytes(got[0].payload or b"") if got else None
            # An EMPTY payload is not a value. A mismatched peripheral answers the handshake and
            # then returns empty frames (SCRUM-107); rendering that as None reads as "the half is
            # gone" when it is typing normally.
            return raw if raw else None

        def mac(p):
            return ":".join(f"{b:02X}" for b in p[:6]) if p and len(p) >= 6 else None

        allp = payload(C.CAT_BLE, C.BLE_GET_ALL_PAIRS)
        peers = []
        if allp and allp[0] <= 8 and len(allp) >= 1 + allp[0] * 6:
            peers = [m for m in (mac(allp[1 + k * 6:7 + k * 6]) for k in range(allp[0])) if m]
        fwv = payload(C.CAT_SYSTEM, C.SYS_GET_FW_VERSION)
        return {"port": dev.port, "serialNumber": dev.serial_number,
                "firmwareVersion": f"{fwv[1]}.{fwv[2]}.{fwv[3]}" if fwv and len(fwv) >= 4 else None,
                "bleAddress": mac(payload(C.CAT_BLE, C.BLE_GET_ADDRESS)),
                "pairAddress": mac(payload(C.CAT_BLE, C.BLE_GET_PAIR_ADDRESS)),
                "allPairs": peers}

    return svc._with_transport(side, go)


def docked_module(svc, side: str) -> dict | None:
    """What is docked in this half's bay, read the way the live status reads it: presence from
    MODULE_DETECT, type and side from the dock address, then the module's own firmware. None
    when the bay is empty. Used by both procedures: the module procedure needs exactly one module
    in the LEFT bay, and a keyboard flash needs none in either (SCRUM-114)."""
    from .._vendor.nayactl import constants as C
    from .._vendor.nayactl.util import format_fw_version
    from .service import _first_payload

    def go(t, dest, dev):
        hs = _first_payload(t.send_command(dest, C.CAT_MODULE, C.MOD_SEND_HANDSHAKE, timeout=1.5))
        det = _first_payload(t.send_command(dest, C.CAT_MODULE, C.MOD_DETECT))
        if det is None or len(det) < 1 or det[0] == 0:
            return None
        addr = hs[1] if hs is not None and len(hs) >= 2 else None
        if addr is None:
            ap = _first_payload(t.send_command(dest, C.CAT_MODULE, C.MOD_GET_ADDRESS))
            addr = ap[0] if ap is not None and len(ap) >= 1 else None
        fwp = _first_payload(t.send_command(dest, C.CAT_MODULE, C.MOD_GET_FW_VERSION))
        return {"address": addr, "type": C.module_type_from_address(addr),
                "docked": C.module_side_from_address(addr),
                "firmwareVersion": format_fw_version(fwp) if fwp else None}
    return svc._with_transport(side, go)


def refuse_docked_modules(svc, sides: tuple[str, ...], log: RunLog | None = None) -> None:
    """SCRUM-114: keyboard firmware is written with NO module docked on either half, as NayaFlow
    requires ("Please ensure NO modules are connected to both of your Create halves"). Every
    keyboard flash before 2026-09-23 happened to run with empty bays, by coincidence; the rule
    had never been written down, so it is enforced here rather than trusted to luck."""
    for side in sides:
        try:
            m = docked_module(svc, side)
        except Exception:                           # noqa: BLE001 -- an unreadable bay is not a refusal
            continue
        if m:
            raise fw.UploadRefused(
                f"a {m.get('type') or 'module'} is docked on the {side} half. Keyboard firmware is "
                "updated with no modules docked on either half, as NayaFlow requires: undock it "
                "and start again. Nothing was written.")
    if log is not None:
        log.event("preflight.capture", "note", detail="no module docked on " + " or ".join(sides))


def _keymap(svc) -> dict:
    """The board's keymap and LED map, as JSON-comparable structures."""
    got = svc.read_keymap("left")
    return {"layers": {str(li): [[p, ty, bytes(prm).hex()] for p, ty, prm in recs]
                       for li, recs in got["layers"].items()},
            "led": {str(li): [list(x) for x in rows] for li, rows in (got.get("led") or {}).items()},
            "layer_uuids": {str(k): v for k, v in (got.get("layer_uuids") or {}).items()},
            "layer_animations": {str(k): v for k, v in (got.get("layer_animations") or {}).items()}}


def _sha_file(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


# --- comparison ----------------------------------------------------------------------------- #

def compare_preflight(before: dict, after: dict, *, version_changed: bool, log: RunLog) -> None:
    """Compare the board against its preflight backup, and be honest about what a difference means.

    The subtlety, and the reason this is not a byte comparison: **the LED payload changed in
    3.41**. A LED map captured on 3.35.4 and re-read after flashing to 3.41.0 legitimately differs
    because the format changed, not because anything was lost. Reporting that as corruption would
    declare a perfect flash broken. So across a version boundary an LED difference is an ADVISORY
    -- recorded in the log so we can study it, never a failure. Within one version it is a real
    failure, because then nothing should have moved.

    Bindings, bond tables and versions are compared strictly either way.
    """
    for side in ("left", "right"):
        b, a = (before.get("halves") or {}).get(side), (after.get("halves") or {}).get(side)
        if not isinstance(b, dict) or not isinstance(a, dict) or "error" in b or "error" in a:
            continue
        for field in ("bleAddress", "pairAddress"):
            if b.get(field) != a.get(field):
                log.fail(f"{side} {field}: was {b.get(field)}, now {a.get(field)}")
        if set(b.get("allPairs") or []) != set(a.get("allPairs") or []):
            log.fail(f"{side} bond table (allPairs): was {b.get('allPairs')}, "
                     f"now {a.get('allPairs')}. The halves may need a split-link repair.")

    kb, ka = before.get("keymap") or {}, after.get("keymap") or {}
    if "error" in kb or "error" in ka:
        log.advise("the keymap could not be compared: it was not captured on both sides of the flash")
        return

    for li, recs in (kb.get("layers") or {}).items():
        now = (ka.get("layers") or {}).get(li)
        if now is None:
            log.fail(f"layer {li}: {len(recs)} records before, the layer is missing now")
            continue
        moved = _differing_positions(recs, now)
        # Two banks, two rules. The PRIMARY bank (0x00-0x51) is the keys the user sees; every
        # firmware we have read reports it the same way, so a difference there is a real change
        # whatever the versions. The SECOND bank (0x52 up, double-tap and tap+hold) is only
        # REPORTED by newer firmware: 3.35.4 stops its read at 0x51, 3.41.0 returns the whole
        # bank. Measured 2026-09-22 -- a double-tap key was on the board throughout an upgrade,
        # invisible to the read before it and present after, and the comparison called that
        # 74 changed bindings. Across a version change a second-bank difference is therefore an
        # advisory; within one version it is as real as any other.
        primary = [p for p in moved if p < SECOND_BANK]
        shadow = [p for p in moved if p >= SECOND_BANK]
        if primary:
            log.fail(f"layer {li} bindings differ at {len(primary)} position(s): {primary[:12]}"
                     + (" ..." if len(primary) > 12 else ""))
        if shadow and version_changed:
            log.advise(f"layer {li}: {len(shadow)} double-tap / tap+hold slot(s) read differently "
                       f"({shadow[:8]}{' ...' if len(shadow) > 8 else ''}). The firmware version "
                       "changed, and older firmware does not report these slots at all, so this "
                       "is what the new version can now show rather than a changed key.")
        elif shadow:
            log.fail(f"layer {li} double-tap / tap+hold bindings differ at {len(shadow)} "
                     f"position(s): {shadow[:12]}" + (" ..." if len(shadow) > 12 else ""))

    for li, rows in (kb.get("led") or {}).items():
        now = (ka.get("led") or {}).get(li)
        if now == rows:
            continue
        where = "missing" if now is None else f"{len(rows)} entries before, {len(now)} now"
        if version_changed:
            log.advise(f"layer {li} LED map differs ({where}). The firmware version changed and "
                       "the LED payload format changed in 3.41, so this is expected and is NOT "
                       "a failed flash.")
        else:
            log.fail(f"layer {li} LED map differs ({where})")


_NONE_RECORD = [NONE_BEH, ""]


def _differing_positions(before: list, after: list) -> list:
    """Which key positions changed, rather than 'the lists differ'.

    A position absent from one read counts as NONE, the same rule the flash's write diff and
    verify use (SCRUM-112): the device pads every unbound position with `07 00` when it reports
    a bank at all, and omits the bank entirely when nothing in it is bound. Absent and empty
    are the same record on the wire, and comparing them as different reported 73 phantom
    changes on 2026-09-22.
    """
    bi = {r[0]: [r[1], r[2]] for r in before}
    ai = {r[0]: [r[1], r[2]] for r in after}
    return sorted(pos for pos in set(bi) | set(ai)
                  if bi.get(pos, _NONE_RECORD) != ai.get(pos, _NONE_RECORD))


# --- the procedure -------------------------------------------------------------------------- #

def _answering_recovery_port(side: str, timeout: float = 30.0) -> str:
    """The bootloader port for `side` that ANSWERS SMP.

    Each half in recovery presents two CDC ports and only one of them speaks SMP; the other is a
    log port that accepts the open, swallows the frame and reports nothing. Addressing that one is
    how a reset comes to look like it needs a power cycle. There is no hurry: a half left in
    MCUboot was still answering minutes later, so this polls rather than racing a window.
    """
    deadline = time.monotonic() + timeout
    while True:
        for d in rec.find_recovery_ports():
            if d.side != side:
                continue
            try:
                rec.image_state(d.port)
                return d.port
            except Exception:                       # noqa: BLE001 -- the log port, or not ready
                pass
        if time.monotonic() >= deadline:
            raise fw.UploadRefused(
                f"the {side} half did not present a bootloader port that answers within "
                f"{timeout:.0f}s. Nothing was written.")
        time.sleep(0.5)


def _identify_in_bootloader(side: str, catalog: list, timeout: float = 90.0) -> dict:
    """Find the half in recovery and read what it runs. ONE discovery mechanism, retried.

    This used to be a port probe followed by `read_running_image`, which does its own discovery --
    so the bootloader's port was opened twice within milliseconds. The second open is refused:
    `_talk`'s own header records that Windows can refuse the port for a moment right after the
    bootloader enumerates. The first real run of this procedure died exactly there, having just
    logged "bootloader answering on COM27" and then been told a moment later that neither port
    answered. One mechanism, retried patiently. There is no hurry: a half sits in MCUboot
    indefinitely and was measured still answering minutes later.
    """
    deadline = time.monotonic() + timeout
    last: str | None = None
    while True:
        try:
            state = rec.read_running_image(catalog)
            if state.get("state") == "ok":
                seen = state.get("pidSide")
                if seen not in (None, side):
                    raise fw.UploadRefused(
                        f"the half in the bootloader reports itself as {seen}, not {side}. "
                        "Nothing was written.")
                return state
            last = str(state.get("detail"))
        except fw.UploadRefused:
            raise
        except Exception as e:                      # noqa: BLE001 -- retried until the deadline
            last = f"{type(e).__name__}: {e}"
        if time.monotonic() >= deadline:
            raise fw.UploadRefused(
                f"could not identify the {side} half within {timeout:.0f}s ({last}). "
                "Nothing was written.")
        time.sleep(2.0)



def image_only_mode() -> bool:
    """OPENFLOW_FIRMWARE_IMAGE_ONLY=1: upload the MCUboot image alone and have the bootloader
    schedule the swap (firmware_upload.flash(vendor_trailer=False, confirm=True)), instead of the
    vendor resource whose trailer arms the swap as the last chunk lands.

    For one kind of half: the one that took the whole vendor resource, rebooted, and dropped it.
    Image-only keeps the half in its bootloader after the upload, so the bootloader is asked
    whether slot 1 holds a valid image BEFORE anything is scheduled, and its console can be read
    if it does not. A session setting, like the other gates, never the default: the vendor path
    is the one every successful flash has taken."""
    return os.environ.get("OPENFLOW_FIRMWARE_IMAGE_ONLY") == "1"


def chunk_size() -> int:
    """OPENFLOW_FIRMWARE_CHUNK: bytes per upload frame for this session, 32 to 4096. Unset or
    out of range is NayaCore's own 512 (firmware_upload.DEFAULT_CHUNK). A diagnostic setting, for
    a half whose bootloader takes every chunk and then rejects what it stored."""
    try:
        n = int(os.environ.get("OPENFLOW_FIRMWARE_CHUNK") or 0)
    except ValueError:
        n = 0
    return n if 32 <= n <= fw.MAX_CHUNK else fw.DEFAULT_CHUNK


class _ConsoleTap:
    """Hold a half's bootloader LOG port open for the whole upload and keep what it prints.

    Read afterwards, the console is gone: on a user's right half the bootloader reset the moment
    the last chunk landed and booted its application, and a read five minutes later found nothing
    (2026-10-01). Held open from before the first chunk, whatever the bootloader says up to the
    reset is kept, and if it comes back into the bootloader the port is reopened and followed for
    `follow_s` more seconds. Best effort and read-only: it sends nothing."""

    def __init__(self, side: str, smp_port: str | None, follow_s: float = 60.0):
        import threading
        self.side, self.smp_port, self.follow_s = side, smp_port, follow_s
        self._stop = threading.Event()
        self._buf = bytearray()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> "_ConsoleTap":
        self._thread.start()
        return self

    def _note(self, text: str) -> None:
        self._buf += f"\n[{datetime.now().strftime('%H:%M:%S')} {text}]\n".encode()

    def _run(self) -> None:
        import serial
        gone_at = None
        while not self._stop.is_set():
            port = next((d.port for d in rec.find_recovery_ports()
                         if d.side == self.side and d.port != self.smp_port), None)
            if port is None:
                if gone_at is None:
                    gone_at = time.monotonic()
                    self._note("bootloader log port gone")
                if time.monotonic() - gone_at > self.follow_s:
                    return
                time.sleep(0.2)
                continue
            gone_at = None
            try:
                with serial.Serial(port, 115200, timeout=0.2) as s:
                    s.dtr = True
                    s.rts = True
                    self._note(f"listening on {port}")
                    while not self._stop.is_set():
                        self._buf += s.read(4096)
            except Exception as e:                  # noqa: BLE001 -- the port vanishing is data
                self._note(f"{port} closed: {type(e).__name__}")
                time.sleep(0.2)

    def stop(self) -> str:
        self._stop.set()
        self._thread.join(timeout=5.0)
        return bytes(self._buf).decode("utf-8", "replace").strip()


def _console_tap(side: str, smp_port: str | None) -> "_ConsoleTap":
    return _ConsoleTap(side, smp_port).start()


def _bootloader_console(side: str, seconds: float = 4.0) -> str:
    """Whatever a half's bootloader has printed, from every recovery port of that side (the log
    port streams it; the SMP port says nothing). Best effort: an empty string when there is no
    bootloader left to ask."""
    import serial
    out = []
    for d in rec.find_recovery_ports():
        if d.side != side:
            continue
        try:
            with serial.Serial(d.port, 115200, timeout=0.2) as s:
                s.dtr = True
                s.rts = True
                buf, end = b"", time.monotonic() + seconds
                while time.monotonic() < end:
                    buf += s.read(4096)
            if buf.strip():
                out.append(f"[{d.port}] " + buf.decode("utf-8", "replace").strip())
        except Exception:                           # noqa: BLE001 -- best effort by design
            continue
    return "\n".join(out)


def flash_one_half(svc, side: str, image: Path, catalog: list, log: RunLog, *,
                   allow_older: bool = False, accept_unknown_running: bool = False,
                   flash_fn=None) -> dict:
    """Enter the bootloader, write, come back, confirm. One half, fully logged.

    Verification here is of THIS half only. The other half is deliberately not read: mid-upgrade
    it is on different firmware and its own port returns empty payloads (SCRUM-107).
    """
    from .._vendor.nayactl import constants as C
    flash_fn = flash_fn or fw.flash

    with log.step("mcuboot.enter", side=side,
                  detail="the half's LEDs will go off; that is expected"):
        def go(t, dest, dev):
            try:
                t.send_command(dest, C.CAT_RESET, C.RESET_MCU_BOOT, timeout=1.5,
                               allow_dangerous=True)
            except Exception:                       # noqa: BLE001 -- it reboots mid-reply
                pass
            return True
        svc._with_transport(side, go)

    with log.step("identify", side=side):
        state = _identify_in_bootloader(side, catalog)
        log.event("mcuboot.port", "ok", side=side,
                  detail=f"bootloader answering on {state.get('port')}")
        running = next((i for i in state.get("images") or [] if i.get("slot") == 0), {})
        arm = running.get("hash")
        log.event("identify", "ok", side=side,
                  running=running.get("createFirmware"), pidSide=state.get("pidSide"),
                  pidGeneration=state.get("pidGeneration"), armToken=arm)

    image_only = image_only_mode()
    if image_only:
        log.event("upload", "note", side=side,
                  detail="image-only upload (OPENFLOW_FIRMWARE_IMAGE_ONLY): the image alone is "
                         "written, the bootloader is asked whether slot 1 holds a valid image, and "
                         "only then is a permanent swap scheduled")
    chunk = chunk_size()
    if chunk != fw.DEFAULT_CHUNK:
        log.event("upload", "note", side=side,
                  detail=f"{chunk}-byte chunks (OPENFLOW_FIRMWARE_CHUNK), not NayaCore's "
                         f"{fw.DEFAULT_CHUNK}")
    plan = fw.plan(image, catalog, allow_older=allow_older, state=state, chunk=chunk,
                   vendor_trailer=not image_only, accept_unknown_running=accept_unknown_running)
    replaced = getattr(plan, "running", None) or {}
    if replaced.get("identifiedBy"):
        # Said in the log in so many words: this is the one run where the image being replaced
        # is not in the catalogue and cannot be put back by OpenFlow.
        log.event("identify", "note", side=side,
                  detail=f"the running image ({replaced.get('hash')}) is not one OpenFlow "
                         f"holds; side {replaced.get('side')} and flash generation "
                         f"{replaced.get('generation')} come from the USB product id, and "
                         "the user confirmed it may be replaced without a way back")
    log.event("upload", "start", side=side, bytes=plan.total_bytes, chunks=plan.chunks,
              target=plan.target.get("createFirmware"), imageId=plan.upload_image_id)

    # The FIRST chunk blocks 6-17 s while the bootloader erases the whole 648 KiB slot. It is
    # logged as its own step so the UI can say "preparing the flash" instead of showing a byte
    # counter frozen at zero -- which is precisely when a user pulls the cable.
    erase = {"done": False}
    last_pct = {"v": -1}
    # Per-chunk timing, kept in memory and logged ONCE as a summary when the upload ends.
    #
    # The first supervised runs took 206 s and 124 s to upload halves that had been measured by
    # hand at 57 s and 78 s. The wider per-chunk timeout is not the cause -- a ceiling costs
    # nothing on a chunk that answers in 40 ms -- so the extra time is the device stalling, and
    # before the ceiling was raised a stall past 5 s simply aborted the run. What we do NOT know
    # is the shape of it: a few long stalls, or everything uniformly slower. Those need different
    # explanations, and the answer is a measurement rather than a rewrite. Summarised rather than
    # logged per chunk: 1296 lines would bury the log the user is meant to be able to read.
    timing: dict = {"at": None, "ms": [], "slowest": [], "over": 0, "stallMs": 0.0}
    STALL_MS = 1000.0            # a chunk this slow is not a round trip, it is the flash pausing

    def progress(sent: int, total: int) -> None:
        now = time.monotonic()
        if not erase["done"]:
            erase["done"] = True
            # The erase is its own step and its own number; chunk timing starts after it, or
            # every summary would carry one 6-17 s outlier that is not a stall at all.
            timing["at"] = now
            log.event("slot.erase", "ok", side=side,
                      detail="the bootloader erased the slot and accepted the first block")
        else:
            took = (now - timing["at"]) * 1000
            timing["at"] = now
            timing["ms"].append(took)
            if took >= STALL_MS:
                timing["over"] += 1
                timing["stallMs"] += took
                if len(timing["slowest"]) < 20:
                    timing["slowest"].append({"offset": sent, "ms": int(took)})
        pct = int(sent * 100 / total) if total else 0
        if pct != last_pct["v"] and pct % 5 == 0:
            last_pct["v"] = pct
            log.event("upload", "progress", side=side, percent=pct, sent=sent, total=total)
        if sent >= total and not timing.get("done"):
            # The last chunk is acknowledged and the bootloader goes quiet: the resource's
            # trailer armed a permanent swap and MCUboot carries it out before it answers
            # anything -- measured at 100 s on 2026-09-22. Without a step here the UI showed
            # "100%" and then nothing for two minutes, which is the other moment a user pulls
            # the cable. Logged from the callback so it lands the instant the upload is done,
            # not after the wait that follows it.
            timing["done"] = True
            _log_chunk_timing(log, side, timing, STALL_MS)
            log.event("swap.verify", "start", side=side,
                      detail=("the image is written; checking that the bootloader accepts it "
                              "before anything is scheduled") if image_only else
                             ("the image is written; the bootloader is carrying out the swap "
                              "and answers nothing until it is done. This can take a couple "
                              "of minutes."))

    log.event("slot.erase", "start", side=side)
    t0 = time.monotonic()
    # Whatever the bootloader prints is the one account of WHY an image was not taken (a user's
    # right half dropped two complete uploads and booted 3.30.1, 2026-09-29 and 10-01, and nothing
    # said why), so its log port is held open for the whole upload.
    tap = _console_tap(side, state.get("port"))
    try:
        result = flash_fn(image, catalog, arm=arm, allow_older=allow_older, chunk=chunk,
                          vendor_trailer=not image_only, confirm=image_only,
                          state=state, progress=progress,
                          accept_unknown_running=accept_unknown_running)
    except Exception:
        # Read before the failure path resets stranded halves out of the bootloader.
        text = tap.stop() or _bootloader_console(side)
        log.event("bootloader.console", "note", side=side,
                  detail=text or "the bootloader's console had nothing to say (or was gone)")
        raise
    said = tap.stop()
    if said:
        log.event("bootloader.console", "note", side=side, detail=said)
    log.event("upload", "ok", side=side, took_ms=int((time.monotonic() - t0) * 1000),
              written=result.get("written"), swap=result.get("swap"))
    if not timing.get("done"):
        _log_chunk_timing(log, side, timing, STALL_MS)   # an upload that never reached 100%
    log.event("swap.verify", "ok", side=side, detail=str(result.get("swap")),
              hash=result.get("hash"))
    log.event("mcuboot.exit", "ok", side=side,
              detail="os reset sent to the port that answers SMP; no power cycle is needed")

    with log.step("version.confirm", side=side):
        want = plan.target.get("createFirmware")
        got = _await_application(svc, side, log)
        log.event("version.confirm", "ok", side=side, expected=want, got=got,
                  label=plan.target.get("versionLabel"))
        if want and got != want:
            raise fw.UploadRefused(
                f"the {side} half came back on {got}, not {want}. The write is recorded above; "
                "the half is running whatever this says and can be flashed again.")
        if not want:
            # The image's release never declared a firmware version, which is true of everything
            # before NayaFlow 1.14.5. There is nothing to compare against, and comparing anyway
            # would fail EVERY such flash at the last step, after a write already verified by
            # hash -- reporting failure on a keyboard that is running the new firmware perfectly
            # is the exact thing this procedure exists to prevent. What can be checked has been:
            # the slot's hash matched the catalogue before the swap, and the half came back to
            # the application on its own. What it reports now is recorded rather than judged.
            log.advise(f"the {side} half came back on {got}. "
                       f"{plan.target.get('versionLabel') or 'This image'} shipped in a release "
                       "that declared no firmware version, so there is no expected number to "
                       "check that against; the write itself was verified by hash.",
                       step="version.confirm")
    return result


def _log_chunk_timing(log: RunLog, side: str, timing: dict, stall_ms: float) -> None:
    """One line that says whether an upload was uniformly slow or stalled in a few places.

    Written after every upload, so the question the first runs raised -- where did the extra two
    and a half minutes go -- is answered by the next run rather than argued about. A healthy
    chunk answers in tens of milliseconds; the median says whether that still holds, and the
    stall total says how much of the wall clock was the device pausing.
    """
    ms = sorted(timing["ms"])
    if not ms:
        return
    at = lambda q: round(ms[min(len(ms) - 1, int(len(ms) * q))])        # noqa: E731
    stall_s = timing["stallMs"] / 1000
    log.event(
        "upload", "note", side=side,
        detail=(f"{len(ms)} chunks: median {at(0.5)} ms, p90 {at(0.9)} ms, slowest "
                f"{round(ms[-1])} ms. {timing['over']} over {stall_ms / 1000:g} s, "
                f"{stall_s:.0f} s of the upload spent waiting on them."),
        chunks=len(ms), medianMs=at(0.5), p90Ms=at(0.9), maxMs=round(ms[-1]),
        over=timing["over"], stallMs=round(timing["stallMs"]), slowest=timing["slowest"])


def _forget_cached_transports(svc) -> None:
    """Drop the service's cached handles, and what it believes the halves are.

    A half that has been through the bootloader re-enumerates, and may come back on a different
    COM port. The service caches an open transport per port and only reopens when a failure is
    recognisable as a dead handle; anything else propagates and would abort the run at
    `version.confirm` on a flash that worked. Dropping the cache costs one reconnect and removes
    a whole class of "it needed a restart to see the board again".

    The identity cache goes with it. Firmware version is read once per port and kept, on the
    grounds that it does not change while a half is plugged in -- which is true of everything
    except the operation happening right here. Without this the app reports the old version
    after a successful update until the keyboard is next unplugged: the flash worked and the
    screen says it did not.
    """
    for port in list(getattr(svc, "_transports", {}) or {}):
        try:
            svc._drop(port)
        except Exception:                           # noqa: BLE001 -- best effort by design
            pass
    try:
        svc.forget_identity()
    except Exception:                               # noqa: BLE001 -- best effort by design
        pass


def _await_application(svc, side: str, log: RunLog | None = None,
                       timeout: float = 300.0, resend_every: float = 30.0) -> str | None:
    """Wait for the half to leave the bootloader and report its version, re-sending the reset.

    This is slow and it is not a fault. A reset sent immediately after an upload often does not
    take: the bootloader is still busy with what the resource's trailer armed. Measured on a real
    downgrade, 2026-09-20 -- the half ignored the reset that followed the upload, was still in
    MCUboot 45 s later, and came back to the application minutes after a second reset. It was
    running the new firmware correctly the whole time; only our patience was wrong, and a 45 s
    limit turned a perfect flash into a reported failure.

    So: wait minutes, not seconds, and re-send the reset periodically rather than waiting on one
    that may have been dropped. The reset must go to the port that ANSWERS SMP; the other accepts
    the open and reports nothing.
    """
    deadline = time.monotonic() + timeout
    next_resend = time.monotonic() + resend_every
    forgotten = False
    while True:
        still = [d for d in rec.find_recovery_ports() if d.side == side]
        if not still:
            if not forgotten:
                _forget_cached_transports(svc)      # it may be back on a different port
                forgotten = True
            try:
                return _identity(svc, side).get("firmwareVersion")
            except Exception:                       # noqa: BLE001 -- still re-enumerating
                pass
        elif time.monotonic() >= next_resend:
            next_resend = time.monotonic() + resend_every
            forgotten = False
            try:
                port = _answering_recovery_port(side, timeout=10.0)
                try:
                    rec.os_reset(port)
                except Exception:                   # noqa: BLE001 -- it reboots mid-reply
                    pass
                if log:
                    log.event("mcuboot.exit", "start", side=side,
                              detail=f"still in the bootloader; reset re-sent on {port}. "
                                     "This can take a few minutes after a write.")
            except Exception:                       # noqa: BLE001 -- try again next time round
                pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(2.0)


SETTLE_WAIT = 90.0


def await_halves(svc, log: RunLog, timeout: float | None = None) -> None:
    """Wait until every half answers again before anything is done to the keyboard as a whole.

    When the second half comes back on matching firmware the two re-link, and the central half
    drops off USB for a moment while they do -- on 2026-09-22 the left disappeared at the exact
    second the right was confirmed on 3.41.0, its lights went out, and it was back two seconds
    later. Three steps ran in that gap and reported the left half missing: brightness, the
    lighting restore, and the comparison's identity read. None of them had failed; they had
    been early. So the procedure now waits here, for both halves, and says why.
    """
    timeout = SETTLE_WAIT if timeout is None else timeout
    deadline = time.monotonic() + timeout
    missing: list[str] = []
    while True:
        missing = []
        for side in ("left", "right"):
            try:
                _identity(svc, side)
            except Exception:                       # noqa: BLE001 -- absent or re-enumerating
                missing.append(side)
        if not missing:
            log.event("halves.settle", "ok",
                      detail="both halves answering; the keyboard has re-linked")
            return
        if time.monotonic() >= deadline:
            log.event("halves.settle", "fail",
                      detail=f"{', '.join(missing)} half not answering after {timeout:.0f}s; "
                             "continuing, and what follows may report it missing")
            return
        _forget_cached_transports(svc)
        time.sleep(2.0)


def restore_brightness(svc, sides: tuple[str, ...], log: RunLog) -> None:
    """Put LED brightness back where the user had it.

    After the 3.41.0 upgrade both halves came up very dim and the owner reasonably read that as
    "the LEDs are off". Brightness is a persistent device setting that survives a reboot, so an
    upgrade that leaves it low looks like a fault. The app's own stored value wins when there is
    one, so a user who deliberately dimmed their board keeps their choice; otherwise full.
    """
    value = 100
    source = "default"
    try:
        from ..db import settings as S
        for g in S.get_settings().get("groups", []):
            for f in g.get("fields", []):
                if f.get("id") == "led_max_brightness" and f.get("value"):
                    value, source = int(f["value"]), "your saved setting"
    except Exception:                               # noqa: BLE001 -- the default is fine
        pass
    for side in sides:
        try:
            svc.led_setting(side, "max_brightness", value)
            log.event("brightness.restore", "ok", side=side, value=value, source=source)
        except Exception as e:                      # noqa: BLE001 -- cosmetic, never fatal
            log.event("brightness.restore", "fail", side=side,
                      detail=f"{type(e).__name__}: {e} (the flash itself is unaffected)")


# How long a failed run keeps re-sending the reset to a half it left in the bootloader before
# giving up and telling the user to power cycle. The same five minutes version.confirm allows.
RECOVERY_WAIT = 300.0


def _recover_stranded_halves(svc, log: RunLog) -> None:
    """Put any half still sitting in the bootloader back into the application.

    Called only after a failure. A half left in MCUboot does not type and shows no lights, which
    to a user is indistinguishable from a brick -- and the primary image is untouched, so it is
    nothing of the sort. `os reset` must go to the port that ANSWERS SMP; the other one accepts
    the open, swallows the frame and reports nothing.
    """
    for side in ("left", "right"):
        if not [d for d in rec.find_recovery_ports() if d.side == side]:
            continue
        try:
            port = _answering_recovery_port(side, timeout=30.0)
            try:
                rec.os_reset(port)
            except Exception:                       # noqa: BLE001 -- it reboots mid-reply
                pass
            log.event("mcuboot.exit", "start", side=side,
                      detail=f"the run failed with this half in the bootloader; reset sent on "
                             f"{port}, waiting for it to come back")
            # One reset is not enough. The first one after an upload often does not take --
            # the bootloader is busy with the swap the trailer armed -- and on 2026-09-22 a
            # single reset here left the half dark, with the user looking at a keyboard whose
            # lights were off, until it was reset again by hand. So this waits the way
            # version.confirm does: re-sending until the half is back in the application.
            got = _await_application(svc, side, log, timeout=RECOVERY_WAIT)
            if got is not None:
                log.event("mcuboot.exit", "ok", side=side,
                          detail=f"back in the application, running {got}")
            elif [d for d in rec.find_recovery_ports() if d.side == side]:
                log.event("mcuboot.exit", "fail", side=side,
                          detail="this half is still in the bootloader after five minutes of "
                                 "resets. Its firmware is untouched; a power cycle will bring "
                                 "it back.")
            else:
                # Measured 2026-09-23: a reset took the half out of the bootloader and it never
                # came back on USB until its cable was replugged. Blaming the bootloader there
                # sent the reader after the wrong thing.
                log.event("mcuboot.exit", "fail", side=side,
                          detail="this half left the bootloader but has not come back on USB. "
                                 "Unplug its USB cable and plug it back in; it runs on its "
                                 "battery, so this is not a power cycle.")
        except Exception as e:                      # noqa: BLE001 -- say so, never hide it
            log.event("mcuboot.exit", "fail", side=side,
                      detail=f"this half is still in the bootloader and could not be reset "
                             f"({type(e).__name__}: {e}). Its firmware is untouched; a power "
                             "cycle will bring it back.")


def restore_lighting(svc, log: RunLog) -> None:
    """Put both halves' LEDs back to the stored colours after the flash.

    A half that has been through the bootloader comes back with a RUNTIME lighting state that
    is not what it stores: on 2026-09-20 "darker amber", on 2026-09-22 one half plain white while
    the other stayed orange -- with the stored LED maps byte-identical before and after, as the
    comparison proved. To a user that is a flash that changed their lights. Rewriting the layer
    list is the one write measured to clear a runtime effect on both halves without a power
    cycle (service.restore_lighting), and it put the white half back to orange the moment it was
    sent. It writes the same bytes the board already holds, so the comparison after it still
    measures the flash and not this.
    """
    try:
        r = svc.restore_lighting("left")             # the central half drives both halves' LEDs
        log.event("lighting.restore", "ok", layers=r.get("layers") if isinstance(r, dict) else None,
                  detail="stored colors and animations re-sent to both halves")
    except Exception as e:                          # noqa: BLE001 -- cosmetic, never fatal
        log.event("lighting.restore", "fail",
                  detail=f"{type(e).__name__}: {e} (the flash itself is unaffected; a power "
                         "cycle also restores the lights)")


def run(svc, targets: dict, catalog: list, *, allow_older: bool = False,
        accept_unknown_running: bool = False,
        log_dir: Path | None = None, flash_fn=None, on_event=None) -> dict:
    """The whole procedure. `targets` maps side -> image path, one or both halves.

    Order: the CENTRAL (left) first when both are asked for, so the run only ever passes through
    a state we have measured.

    The tempting alternative is peripheral-first, on the grounds that the peripheral is the half
    that goes dark while the versions differ, so doing it first gets the ugly interval over with.
    That reasoning optimises cosmetics and ignores the thing that can actually derail a run.
    Between the two flashes one half is verified on its own port, and what we measured on
    2026-09-20 is a NEWER CENTRAL with an older peripheral: there the central reads perfectly and
    it is the peripheral's port that goes hollow (SCRUM-107). Peripheral-first would instead
    produce a newer peripheral with an older central and then read the peripheral -- a
    configuration nobody has observed. Central-first verifies the half we know answers.
    """
    sides = tuple(s for s in ("left", "right") if s in targets)
    if not sides:
        raise ValueError("no side to flash: pass {'left': image} and/or {'right': image}")

    from ..config import logs_dir
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(log_dir) if log_dir else (logs_dir() / f"flash-{stamp}")
    run_dir.mkdir(parents=True, exist_ok=True)
    log = RunLog(run_dir / "run.log",
                 {"sides": list(sides), "images": {k: str(v) for k, v in targets.items()},
                  "allowOlder": allow_older, "acceptUnknownRunning": accept_unknown_running},
                 on_event=on_event)

    # Hold the service lock for the WHOLE procedure, not just the reads inside it.
    #
    # The live-status tick runs under this lock every few seconds per half. On 2026-09-16 a tick
    # slipped four commands onto a port between two frames of a chunked keymap write and cost it
    # an ack (see test_flash_holds_the_service_lock). The upload itself is safe from that -- a
    # half in MCUboot enumerates as an unrecognised product id and the poll loop cannot see it --
    # but the entry, the identity reads and the post-flash comparison all talk to a half the tick
    # IS watching. Taking the lock once, for the duration, means nothing else touches either port
    # between "Go" and the verdict. It is an RLock and _with_transport re-enters it on this same
    # thread, so the steps below still work normally.
    lock = getattr(svc, "_lock", None)
    held = lock.acquire() is not False if lock is not None else False
    try:
        with log.step("preflight.capture"):
            refuse_docked_modules(svc, ("left", "right"), log)
            before = capture_preflight(svc, sides, log, run_dir)
        with log.step("preflight.verify"):
            saved = json.loads((run_dir / "preflight.json").read_text(encoding="utf-8"))
            if saved != before:
                raise fw.UploadRefused("the backup did not read back identical to what was "
                                       "captured. Nothing was written.")

        versions_before = {s: ((before.get("halves") or {}).get(s) or {}).get("firmwareVersion")
                           for s in ("left", "right")}

        for side in sides:
            flash_one_half(svc, side, Path(targets[side]), catalog, log,
                           allow_older=allow_older, flash_fn=flash_fn,
                           accept_unknown_running=accept_unknown_running)

        await_halves(svc, log)
        restore_brightness(svc, sides, log)
        restore_lighting(svc, log)

        with log.step("verify.compare"):
            after = {"halves": {}, "keymap": {}}
            for side in ("left", "right"):
                try:
                    after["halves"][side] = _identity(svc, side)
                except Exception as e:              # noqa: BLE001
                    after["halves"][side] = {"error": f"{type(e).__name__}: {e}"}
            try:
                after["keymap"] = _keymap(svc)
            except Exception as e:                  # noqa: BLE001
                after["keymap"] = {"error": f"{type(e).__name__}: {e}"}
            (run_dir / "postflight.json").write_text(
                json.dumps(after, indent=1, default=str), encoding="utf-8")
            changed = any(versions_before.get(s) !=
                          ((after.get("halves") or {}).get(s) or {}).get("firmwareVersion")
                          for s in ("left", "right"))
            compare_preflight(before, after, version_changed=changed, log=log)
    except Exception as e:                          # noqa: BLE001 -- the verdict is the product
        # A failed run must not walk away leaving a half dark. Whatever went wrong, if a half is
        # still in the bootloader it is not a keyboard, and the user is left with hardware that
        # looks bricked. Put it back before reporting. The first real run failed at identify and
        # left the left half in MCUboot; recovering it by hand is exactly the off-script step
        # this procedure exists to make unnecessary.
        _recover_stranded_halves(svc, log)
        return log.finish(False, f"{type(e).__name__}: {e}")
    finally:
        if held:
            lock.release()                          # the tick may resume, whatever happened

    if log.failures:
        return log.finish(False, f"the firmware was written, but {len(log.failures)} thing(s) "
                                 "on the keyboard do not match the backup")
    return log.finish(True, "firmware written and verified; the keyboard matches its backup")
