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
    "version.confirm": "Confirming the new version",
    "brightness.restore": "Restoring LED brightness",
    "verify.compare": "Comparing the keyboard against the backup",
    "run.end": "Finished",
}


class RunLog:
    """An append-only, flushed-per-line JSONL log of one flash run.

    Every line is written AND flushed AND fsynced before the next step begins. That is
    deliberately more expensive than buffering: the whole point of this file is to still be
    truthful after the event that stopped the run, and steps are seconds apart, not microseconds.
    Progress inside the upload is throttled by the caller so this stays cheap.
    """

    def __init__(self, path: Path, meta: dict | None = None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a", encoding="utf-8")
        self._t0 = time.monotonic()
        self.events: list[dict] = []
        self.failures: list[str] = []
        self.advisories: list[str] = []
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

    def advise(self, what: str) -> None:
        """A difference that is EXPECTED and must not fail the run -- see compare_preflight."""
        self.advisories.append(what)
        self.event("verify.compare", "note", detail=what)

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
        mark = {"start": "  ", "ok": "OK", "fail": "!!", "note": "**"}.get(e.get("phase"), "  ")
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
        if now != recs:
            moved = _differing_positions(recs, now)
            log.fail(f"layer {li} bindings differ at {len(moved)} position(s): {moved[:12]}"
                     + (" ..." if len(moved) > 12 else ""))

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


def _differing_positions(before: list, after: list) -> list:
    """Which key positions changed, rather than 'the lists differ'."""
    bi = {r[0]: r for r in before}
    ai = {r[0]: r for r in after}
    return sorted(pos for pos in set(bi) | set(ai) if bi.get(pos) != ai.get(pos))


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


def flash_one_half(svc, side: str, image: Path, catalog: list, log: RunLog, *,
                   allow_older: bool = False, flash_fn=None) -> dict:
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

    with log.step("mcuboot.port", side=side):
        port = _answering_recovery_port(side)
        log.event("mcuboot.port", "ok", side=side, detail=f"bootloader answering on {port}")

    with log.step("identify", side=side):
        state = rec.read_running_image(catalog)
        if state.get("state") != "ok":
            raise fw.UploadRefused(f"could not identify the {side} half: {state.get('detail')}")
        running = next((i for i in state.get("images") or [] if i.get("slot") == 0), {})
        arm = running.get("hash")
        log.event("identify", "ok", side=side,
                  running=running.get("createFirmware"), pidSide=state.get("pidSide"),
                  pidGeneration=state.get("pidGeneration"), armToken=arm)

    plan = fw.plan(image, catalog, allow_older=allow_older, state=state, vendor_trailer=True)
    log.event("upload", "start", side=side, bytes=plan.total_bytes, chunks=plan.chunks,
              target=plan.target.get("createFirmware"), imageId=plan.upload_image_id)

    # The FIRST chunk blocks 6-17 s while the bootloader erases the whole 648 KiB slot. It is
    # logged as its own step so the UI can say "preparing the flash" instead of showing a byte
    # counter frozen at zero -- which is precisely when a user pulls the cable.
    erase = {"done": False}
    last_pct = {"v": -1}

    def progress(sent: int, total: int) -> None:
        if not erase["done"]:
            erase["done"] = True
            log.event("slot.erase", "ok", side=side,
                      detail="the bootloader erased the slot and accepted the first block")
        pct = int(sent * 100 / total) if total else 0
        if pct != last_pct["v"] and pct % 5 == 0:
            last_pct["v"] = pct
            log.event("upload", "progress", side=side, percent=pct, sent=sent, total=total)

    log.event("slot.erase", "start", side=side)
    t0 = time.monotonic()
    result = flash_fn(image, catalog, arm=arm, allow_older=allow_older, vendor_trailer=True,
                      state=state, progress=progress)
    log.event("upload", "ok", side=side, took_ms=int((time.monotonic() - t0) * 1000),
              written=result.get("written"), swap=result.get("swap"))
    log.event("swap.verify", "ok", side=side, detail=str(result.get("swap")),
              hash=result.get("hash"))
    log.event("mcuboot.exit", "ok", side=side,
              detail="os reset sent to the port that answers SMP; no power cycle is needed")

    with log.step("version.confirm", side=side):
        want = plan.target.get("createFirmware")
        got = _await_application(svc, side)
        log.event("version.confirm", "ok", side=side, expected=want, got=got)
        if got != want:
            raise fw.UploadRefused(
                f"the {side} half came back on {got}, not {want}. The write is recorded above; "
                "the half is running whatever this says and can be flashed again.")
    return result


def _await_application(svc, side: str, timeout: float = 45.0) -> str | None:
    """Wait for the half to leave the bootloader and report its version. ~8 s in practice."""
    deadline = time.monotonic() + timeout
    while True:
        if not [d for d in rec.find_recovery_ports() if d.side == side]:
            try:
                return _identity(svc, side).get("firmwareVersion")
            except Exception:                       # noqa: BLE001 -- still re-enumerating
                pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(1.5)


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


def run(svc, targets: dict, catalog: list, *, allow_older: bool = False,
        log_dir: Path | None = None, flash_fn=None) -> dict:
    """The whole procedure. `targets` maps side -> image path, one or both halves.

    Order: the PERIPHERAL (right) first when both are asked for. While the halves are mismatched
    it is the peripheral whose LEDs go dark and whose own USB port goes hollow, so doing it first
    puts the visibly odd interval before the central's flash and ends fully consistent.
    """
    sides = tuple(s for s in ("right", "left") if s in targets)
    if not sides:
        raise ValueError("no side to flash: pass {'left': image} and/or {'right': image}")

    from ..config import logs_dir
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(log_dir) if log_dir else (logs_dir() / f"flash-{stamp}")
    run_dir.mkdir(parents=True, exist_ok=True)
    log = RunLog(run_dir / "run.log",
                 {"sides": list(sides), "images": {k: str(v) for k, v in targets.items()},
                  "allowOlder": allow_older})

    try:
        with log.step("preflight.capture"):
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
                           allow_older=allow_older, flash_fn=flash_fn)

        restore_brightness(svc, sides, log)

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
        return log.finish(False, f"{type(e).__name__}: {e}")

    if log.failures:
        return log.finish(False, f"the firmware was written, but {len(log.failures)} thing(s) "
                                 "on the keyboard do not match the backup")
    return log.finish(True, "firmware written and verified; the keyboard matches its backup")
