"""Module firmware as a PROCEDURE, in the order NayaFlow runs it, with the same audit log as a
keyboard flash (device/flash_procedure.py).

MEASURED, not inferred: NayaFlow 1.25.1 updating a Touch 2.1.2 -> 2.3.3 on a 3.41.0 left half,
captured with USBPcap and NayaCore's own log on 2026-09-23 (device/out/module-fw-touch1-20260923*,
docs in nayaHistory FLASHING-PROCEDURE.md). NayaCore v6.11.0 does this:

  1. MODULE_FILE_FW_VERSION: which bundle the left half already holds. If it is the one being
     installed, the upload is SKIPPED.
  2. Otherwise MCU_BOOT reset, then the bundle over SMP to upload id 4 in 512-byte chunks (about
     65 s for 1 MiB). NayaCore sends NOTHING after the last chunk; the half restarts itself.
  3. With the half back: MODULE_FWUP (0xDE/0x1005) to dest 0x50 with ONE byte, the module type
     (01 for a Touch -- the plain type number, not the side-dependent dock address). It gets NO
     reply. The module's lights go out for 10-15 s while the keyboard programs it from the bundle,
     then the whole keyboard restarts about 32 s after the command.
  4. With the half back: GET_MODULE_FW_VERSION must equal the bundle's version.

THE CABLE REPLUG. After both self-restarts on the measured board, the left half passed through
its bootloader for a few milliseconds and then never came back on USB until its cable was
unplugged and plugged in again (it runs on its battery throughout, so this is not a power cycle).
NayaFlow gives the half 300 s per step but only looks at the clock when a device event happens,
so a run that nobody replugged sat for 21 minutes and then failed. Whether every board does this
is not yet known. So the procedure watches for the half, and if it has not been seen anywhere for
REPLUG_AFTER seconds it asks the user, once, as an `action` event, and keeps waiting.

PRECONDITIONS, the vendor's own: "Module Firmware can only be updated if the only Naya Device
connected is a single up-to-date Create Left with the docked module." The right half off USB, the
module in the LEFT bay, and the bundle one whose keyboard range holds the firmware the left half
runs (firmware_upload.require_module_pairing; the ranges come from every official and beta
release, see tools/build_firmware_catalog.py). A right-bay module is moved to the left bay.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from . import firmware_upload as fw
from . import flash_procedure as fp
from . import recovery as rec

# MODULE_FWUP's one payload byte, by the type the dock address decodes to. Touch = 01 is on the
# wire (2026-09-23); Track and Tune follow nayactl's MODULE_TYPES numbering, which the Touch
# capture agrees with, and are confirmed the first time each is run.
FWUP_TYPES = {"Touch": 1, "Track": 2, "Tune": 3}

REPLUG_AFTER = 30.0        # the half unseen this long after a restart: ask for a cable replug
RETURN_WAIT = 600.0        # how long to wait for it at all, prompt included
DROP_WAIT = 120.0          # MODULE_FWUP -> keyboard restart was 32.6 s measured
MODULE_FIND_WAIT = 90.0    # "allow up to 7 seconds", a Tune "up to a minute" the first time
BOOT_RESET_AFTER = 60.0    # a half still in its bootloader this long after the upload gets a reset
POLL = 1.0


class ModuleRefused(fw.UploadRefused):
    """A precondition failed before anything was written."""


# --- reading the left half --------------------------------------------------------------------- #

def _present(svc, side: str) -> bool:
    """Is this half on USB in the application? Enumeration only, no port is opened."""
    try:
        return any(d.get("side") == side for d in svc.list_devices())
    except Exception:                               # noqa: BLE001 -- unknown reads as absent
        return False


def read_module(svc) -> dict | None:
    """What is docked in the LEFT bay, read the way the live status reads it: presence from
    MODULE_DETECT, type and side from the dock address, then the module's own firmware."""
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
    return svc._with_transport("left", go)


def _find_module(svc, timeout: float, *, want_version: bool = True) -> dict | None:
    """The docked module, retried: after a restart it takes seconds to be found, and its version
    can lag its presence."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            m = read_module(svc)
            if m and (m.get("firmwareVersion") or not want_version):
                return m
        except Exception:                           # noqa: BLE001 -- retried until the deadline
            pass
        if time.monotonic() >= deadline:
            return None
        time.sleep(2.0)


def _stored_bundle(svc) -> str | None:
    try:
        return svc.module_file_fw_version("left").get("version")
    except Exception:                               # noqa: BLE001 -- recorded as unknown
        return None


# --- waiting for the half ---------------------------------------------------------------------- #

def await_left(svc, log: fp.RunLog, step: str, *, prompt_after: float | None = None,
               timeout: float | None = None) -> str | None:
    """Wait for the left half to be back in the application and answering; its firmware version,
    or None if it never came back.

    Three places it can be: in its bootloader (it restarts through it every time, for a moment),
    in the application, or nowhere. "Nowhere" for longer than `prompt_after` is the measured case
    that needs a cable replug, and the user is asked once. A half that sits in the BOOTLOADER is
    different: that one is reset from here, on the port that answers SMP, as the keyboard
    procedure does.
    """
    prompt_after = REPLUG_AFTER if prompt_after is None else prompt_after
    timeout = RETURN_WAIT if timeout is None else timeout
    start = time.monotonic()
    deadline = start + timeout
    last_seen = start
    next_reset = start + BOOT_RESET_AFTER
    prompted = forgot = False
    while True:
        now = time.monotonic()
        in_boot = [d for d in rec.find_recovery_ports() if d.side == "left"]
        if in_boot:
            last_seen = now
            forgot = False
            if now >= next_reset:
                next_reset = now + BOOT_RESET_AFTER
                try:
                    port = fp._answering_recovery_port("left", timeout=10.0)
                    try:
                        rec.os_reset(port)
                    except Exception:               # noqa: BLE001 -- it reboots mid-reply
                        pass
                    log.event(step, "note", side="left",
                              detail=f"still in its bootloader; reset sent on {port}")
                except Exception:                   # noqa: BLE001 -- try again next time round
                    pass
        elif _present(svc, "left"):
            last_seen = now
            if not forgot:
                fp._forget_cached_transports(svc)   # it may be back on a different port
                forgot = True
            try:
                got = fp._identity(svc, "left").get("firmwareVersion")
                if prompted:
                    log.event("replug", "ok", side="left", detail="the left half is back")
                return got
            except Exception:                       # noqa: BLE001 -- still enumerating
                pass
        else:
            forgot = False
            if not prompted and now - last_seen >= prompt_after:
                prompted = True
                log.event("replug", "action", side="left",
                          detail="The left half restarted and has not come back on USB. Unplug "
                                 "its USB cable and plug it back in. It stays powered on its "
                                 "battery, so this is not a power cycle, and nothing being "
                                 "written is interrupted.")
        if now >= deadline:
            return None
        time.sleep(POLL)


def await_drop(svc, timeout: float | None = None) -> bool:
    """Wait for the keyboard to restart after MODULE_FWUP: True once the left half has left USB."""
    timeout = DROP_WAIT if timeout is None else timeout
    deadline = time.monotonic() + timeout
    while True:
        if not _present(svc, "left") or [d for d in rec.find_recovery_ports() if d.side == "left"]:
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(POLL)


# --- choosing the bundle ---------------------------------------------------------------------- #

def choose_bundle(catalog: list, keyboard_version: str | None, version: str | None) -> dict:
    """The catalogue entry to install. With no `version`, the bundle whose keyboard range holds
    the firmware the left half runs -- which is what NayaFlow does, since it carries exactly one."""
    bundles = [e for e in catalog if e.get("type") == "littlefs" and e.get("target") == "module"]
    if version:
        entry = next((e for e in bundles if e.get("moduleFirmware") == version), None)
        if entry is None:
            raise ModuleRefused(f"no module firmware {version} in the catalogue. Nothing was written.")
        if not entry.get("flashable"):
            why = "; ".join(entry.get("withheldBecause") or ["it is not marked flashable"])
            raise ModuleRefused(f"module firmware {version} is withheld: {why}")
        fw.require_module_pairing(entry, keyboard_version, catalog)
        return entry
    fits = [e for e in bundles if e.get("flashable") and fw.module_bundle_fits(e, keyboard_version)]
    if not fits:
        raise ModuleRefused(
            f"no module firmware we hold goes with keyboard firmware {keyboard_version}, so "
            "there is nothing that is known to belong on this keyboard. Nothing was written.")
    return max(fits, key=lambda e: fw._version_tuple(e.get("moduleFirmware")) or ())


def bundle_path(entry: dict, firmware_root: Path | None) -> Path:
    rel = entry.get("historyPath")
    if not firmware_root or not rel:
        raise ModuleRefused("there is no firmware folder to read the bundle from. Nothing was written.")
    p = Path(firmware_root) / rel
    if not p.is_file():
        raise ModuleRefused(
            f"module firmware {entry.get('moduleFirmware')} is not downloaded yet ({rel}). Fetch it "
            "from the firmware library first. Nothing was written.")
    return p


# --- the procedure ----------------------------------------------------------------------------- #

def _preflight(svc, log: fp.RunLog, catalog: list, version: str | None, allow_older: bool,
               force_upload: bool, firmware_root: Path | None) -> dict:
    """Every precondition, before anything is written. Returns what the run needs."""
    if not _present(svc, "left"):
        raise ModuleRefused("the left half is not connected. Plug in the LEFT half's USB cable.")
    if _present(svc, "right"):
        raise ModuleRefused(
            "the right half is connected. Unplug the right half's USB cable: module firmware is "
            "updated with only the LEFT half connected, as NayaFlow requires. Nothing was written.")
    ident = fp._identity(svc, "left")
    kb = ident.get("firmwareVersion")
    module = _find_module(svc, 10.0)
    if module is None:
        raise ModuleRefused(
            "no module is docked on the left half, or it is switched off. Dock the module you want "
            "to update in the LEFT bay and switch it on; it can take a few seconds to be found, "
            "and a Tune up to a minute the first time. Nothing was written.")
    if module.get("docked") not in (None, "left"):
        raise ModuleRefused(f"the module reports the {module.get('docked')} bay; it must be in the "
                            "LEFT bay. Nothing was written.")
    if module.get("type") not in FWUP_TYPES:
        raise ModuleRefused(f"the docked module reads as {module.get('type')}; only a Touch, Track "
                            "or Tune can be updated. Nothing was written.")
    entry = choose_bundle(catalog, kb, version)
    target = entry.get("moduleFirmware")
    path = bundle_path(entry, firmware_root)
    stored = _stored_bundle(svc)
    running = module.get("firmwareVersion")
    have, want = fw._version_tuple(running), fw._version_tuple(target)
    if have and want and want < have and not allow_older:
        raise ModuleRefused(
            f"module firmware {target} is older than the {running} this {module['type']} runs. "
            "Pass allow_older to say you meant it. Nothing was written.")
    upload = force_upload or stored != target
    program = running != target
    log.event("preflight.check", "ok", side="left", keyboard=kb, module=module, storedBundle=stored,
              target=target, keyboardRange=entry.get("keyboardRange"), upload=upload,
              program=program, forceUpload=force_upload,
              detail=(f"left half {kb}, {module['type']} on {running or 'unknown'}, keyboard holds "
                      f"module firmware {stored or 'unknown'}, installing {target}"))
    return {"ident": ident, "keyboard": kb, "module": module, "entry": entry, "target": target,
            "path": path, "stored": stored, "upload": upload, "program": program}


def _capture(svc, log: fp.RunLog, run_dir: Path, pre: dict) -> dict:
    cap = {"at": datetime.now().isoformat(timespec="seconds"),
           "halves": {"left": pre["ident"]}, "module": pre["module"],
           "storedBundle": pre["stored"]}
    try:
        cap["keymap"] = fp._keymap(svc)
    except Exception as e:                          # noqa: BLE001 -- recorded, compared as such
        cap["keymap"] = {"error": f"{type(e).__name__}: {e}"}
        log.event("preflight.capture", "fail", side="left", detail=cap["keymap"]["error"])
    path = run_dir / "preflight.json"
    path.write_text(json.dumps(cap, indent=1, default=str), encoding="utf-8")
    log.event("preflight.capture", "ok", detail=f"saved {path.name}", artifact=str(path),
              sha256=fp._sha_file(path))
    return cap


SLOT_MAP_TRIES = 3          # extra reads of `image slot info` when identify's own read failed


def _slot_map(state: dict, log: fp.RunLog) -> tuple[dict | None, bool]:
    """The bootloader's slot map, read again if the identify read did not get one, and whether
    the upload must fall back to NayaCore's constant because it never answered.

    The first hardware run (2026-09-23 13:32) died here: identify's own map read failed, and the
    guard refused, correctly, before a byte was sent. The map answered on 2026-09-16 and NayaFlow
    never asks for it, so a failed read is retried after a pause (Windows can refuse a port
    reopened milliseconds after the last close), and only then does the upload fall back to 4.
    Every outcome is logged, so a run that falls back says so.
    """
    info = state.get("slotInfo")
    tries = 0
    while not (info and info.get("supported")) and tries < SLOT_MAP_TRIES and state.get("port"):
        tries += 1
        time.sleep(2.0)
        try:
            info = rec.slot_info(state["port"])
        except Exception as e:                      # noqa: BLE001 -- recorded below
            info = {"supported": None, "error": f"{type(e).__name__}: {e}", "slots": []}
    answered = bool(info and info.get("supported"))
    if answered:
        log.event("identify", "note", side="left", slotMap=info.get("slots"), retries=tries,
                  detail="the bootloader reported its slot map" + (f" (after {tries} retries)"
                                                                     if tries else ""))
    else:
        why = (info or {}).get("error") or (info or {}).get("rc") or "no answer"
        log.advise(f"the bootloader did not report its slot map after {tries + 1} tries ({why}); "
                   "writing to NayaCore's modules slot 4, as NayaFlow does without asking",
                   step="identify")
        # What it DID send, for the record: the map answered on 2026-09-16 and not since.
        log.event("identify", "note", side="left", slotMapReply=repr((info or {}).get("raw"))[:400])
    return info, not answered


def _upload(svc, log: fp.RunLog, catalog: list, pre: dict, allow_older: bool, upload_fn,
            track: dict) -> None:
    from .._vendor.nayactl import constants as C

    track["in_boot"] = True        # from here a failure must bring the half back
    with log.step("mcuboot.enter", side="left",
                  detail="the half's LEDs will go off; that is expected"):
        def go(t, dest, dev):
            try:
                t.send_command(dest, C.CAT_RESET, C.RESET_MCU_BOOT, timeout=1.5,
                               allow_dangerous=True)
            except Exception:                       # noqa: BLE001 -- it reboots mid-reply
                pass
            return True
        svc._with_transport("left", go)

    with log.step("identify", side="left"):
        state = fp._identify_in_bootloader("left", catalog)
        running = next((i for i in state.get("images") or [] if i.get("slot") == 0), {})
        log.event("identify", "ok", side="left", running=running.get("createFirmware"),
                  port=state.get("port"), armToken=running.get("hash"))
        slot_info, unmapped = _slot_map(state, log)

    erase = {"done": False}
    last_pct = {"v": -1}

    def progress(sent: int, total: int) -> None:
        if not erase["done"]:
            erase["done"] = True
            log.event("slot.erase", "ok", side="left",
                      detail="the bootloader erased the modules partition and took the first block")
        pct = int(sent * 100 / total) if total else 0
        if pct != last_pct["v"] and pct % 5 == 0:
            last_pct["v"] = pct
            log.event("upload", "progress", side="left", percent=pct, sent=sent, total=total)

    log.event("slot.erase", "start", side="left")
    t0 = time.monotonic()
    result = upload_fn(pre["path"], catalog, arm=running.get("hash") or "",
                       installed_version=pre["stored"], allow_older=allow_older,
                       progress=progress, state=state, slot_info=slot_info,
                       allow_unmapped=unmapped)
    log.event("upload", "ok", side="left", took_ms=int((time.monotonic() - t0) * 1000),
              written=result.get("written"), target=pre["target"],
              detail="the bundle is written; the half restarts on its own")

    with log.step("bundle.restart", side="left"):
        got = await_left(svc, log, "bundle.restart")
        track["in_boot"] = got is None
        if got is None:
            raise fw.UploadRefused(
                "the left half did not come back after the upload. The bundle was written in "
                "full; unplug and replug the left half's USB cable, then run the update again "
                "(it will skip the upload if the keyboard holds the bundle).")
    with log.step("bundle.verify", side="left"):
        now = _stored_bundle(svc)
        log.event("bundle.verify", "ok" if now == pre["target"] else "fail", side="left",
                  expected=pre["target"], got=now)
        if now != pre["target"]:
            raise fw.UploadRefused(
                f"the keyboard reports module firmware {now} after the upload, not "
                f"{pre['target']}. Its keyboard firmware is untouched; run the update again.")


def _recover_left(svc, log: fp.RunLog) -> None:
    """After a failure that happened with the half sent into its bootloader: get it back.

    Not the keyboard procedure's recovery, which assumes a half it cannot see is still in the
    bootloader. On 2026-09-23 the half left the bootloader after the first reset and simply never
    came back on USB; that recovery waited five minutes and then blamed the bootloader. This one
    resets a half that IS in the bootloader (on the port that answers SMP) and otherwise waits
    with the same replug prompt as every other restart in this procedure.
    """
    if [d for d in rec.find_recovery_ports() if d.side == "left"]:
        try:
            port = fp._answering_recovery_port("left", timeout=30.0)
            try:
                rec.os_reset(port)
            except Exception:                       # noqa: BLE001 -- it reboots mid-reply
                pass
            log.event("mcuboot.exit", "start", side="left",
                      detail=f"the run failed with the half in its bootloader; reset sent on {port}")
        except Exception as e:                      # noqa: BLE001 -- the wait below still runs
            log.event("mcuboot.exit", "note", side="left",
                      detail=f"could not reach the bootloader to reset it ({type(e).__name__}: {e})")
    got = await_left(svc, log, "mcuboot.exit", timeout=fp.RECOVERY_WAIT)
    if got is not None:
        log.event("mcuboot.exit", "ok", side="left", detail=f"back in the application, running {got}")
    elif [d for d in rec.find_recovery_ports() if d.side == "left"]:
        log.event("mcuboot.exit", "fail", side="left",
                  detail="the half is still in its bootloader. Its keyboard firmware is untouched; "
                         "a power cycle brings it back.")
    else:
        log.event("mcuboot.exit", "fail", side="left",
                  detail="the half left its bootloader but has not come back on USB. Unplug its "
                         "USB cable and plug it back in; it runs on its battery, so this is not "
                         "a power cycle.")


def _program(svc, log: fp.RunLog, pre: dict) -> None:
    from .._vendor.nayactl import constants as C

    with log.step("module.program", side="left"):
        module = _find_module(svc, MODULE_FIND_WAIT, want_version=False)
        if module is None:
            raise fw.UploadRefused("the module was not found after the keyboard restarted. Check it "
                                   "is docked in the LEFT bay and switched on, then run the update "
                                   "again; the keyboard already holds the bundle.")
        code = FWUP_TYPES.get(module.get("type"))
        if code is None:
            raise fw.UploadRefused(f"the docked module reads as {module.get('type')}, which cannot "
                                   "be programmed.")

        def go(t, dest, dev):
            try:
                t.send_command(dest, C.CAT_MODULE, C.MOD_FWUP, bytes([code]), timeout=2.0)
            except Exception:                       # noqa: BLE001 -- it answers nothing (measured)
                pass
            return True
        svc._with_transport("left", go)
        log.event("module.program", "note", side="left", module=module.get("type"), code=code,
                  detail=f"MODULE_FWUP sent ({module.get('type')}, {code:02X}). The module's lights "
                         "go out for 10-15 s while the keyboard programs it, then the keyboard "
                         "restarts. Keep the module docked.")

    with log.step("module.restart", side="left"):
        if await_drop(svc):
            got = await_left(svc, log, "module.restart")
            if got is None:
                raise fw.UploadRefused(
                    "the left half did not come back after programming the module. Unplug and "
                    "replug its USB cable; the module's version is checked on the next run.")
        else:
            log.event("module.restart", "note", side="left",
                      detail=f"the keyboard did not restart within {DROP_WAIT:.0f} s; checking "
                             "the module anyway")

    with log.step("module.verify", side="left"):
        module = _find_module(svc, MODULE_FIND_WAIT)
        got = module.get("firmwareVersion") if module else None
        log.event("module.verify", "ok" if got == pre["target"] else "fail", side="left",
                  expected=pre["target"], got=got, module=(module or {}).get("type"))
        if got != pre["target"]:
            raise fw.UploadRefused(
                f"the module reports {got or 'nothing'} after programming, not {pre['target']}.")


def run(svc, catalog: list, *, version: str | None = None, allow_older: bool = False,
        force_upload: bool = False, firmware_root: Path | None = None,
        log_dir: Path | None = None, upload_fn=None, on_event=None) -> dict:
    """Update the module docked on the left half. `version` defaults to the bundle that shipped
    with the left half's firmware. `force_upload` writes the bundle even when the keyboard
    already holds it (the upload is otherwise skipped, as NayaFlow skips it)."""
    upload_fn = upload_fn or fw.flash_module_bundle
    from ..config import logs_dir
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = Path(log_dir) if log_dir else (logs_dir() / f"module-{stamp}")
    run_dir.mkdir(parents=True, exist_ok=True)
    log = fp.RunLog(run_dir / "run.log",
                    {"kind": "module", "sides": ["left"], "version": version,
                     "allowOlder": allow_older, "forceUpload": force_upload},
                    on_event=on_event)

    # The service lock for the whole run, as the keyboard procedure holds it: nothing else may
    # talk to the left half between Go and the verdict. The live tick polls the module bay every
    # few seconds, and NayaFlow sent nothing at all between MODULE_FWUP and the restart.
    lock = getattr(svc, "_lock", None)
    held = lock.acquire() is not False if lock is not None else False
    track = {"in_boot": False}
    try:
        with log.step("preflight.check", side="left"):
            pre = _preflight(svc, log, catalog, version, allow_older, force_upload, firmware_root)
        if not pre["upload"] and not pre["program"]:
            return log.finish(True, f"the {pre['module']['type']} already runs {pre['target']} and "
                                    "the keyboard holds that bundle; nothing to do")
        with log.step("preflight.capture"):
            before = _capture(svc, log, run_dir, pre)
        with log.step("preflight.verify"):
            saved = json.loads((run_dir / "preflight.json").read_text(encoding="utf-8"))
            if saved != json.loads(json.dumps(before, default=str)):
                raise fw.UploadRefused("the backup did not read back identical to what was "
                                       "captured. Nothing was written.")

        with log.step("bundle.check", side="left"):
            log.event("bundle.check", "note", side="left",
                      detail=(f"uploading module firmware {pre['target']}"
                              + (" (forced; the keyboard already holds it)" if pre["stored"] == pre["target"]
                                 else f" over the {pre['stored'] or 'unknown'} it holds"))
                      if pre["upload"] else
                      f"the keyboard already holds module firmware {pre['target']}; no upload")
        if pre["upload"]:
            _upload(svc, log, catalog, pre, allow_older, upload_fn, track)
        if pre["program"]:
            _program(svc, log, pre)

        with log.step("verify.compare"):
            after = {"halves": {}, "keymap": {}}
            try:
                after["halves"]["left"] = fp._identity(svc, "left")
            except Exception as e:                  # noqa: BLE001
                after["halves"]["left"] = {"error": f"{type(e).__name__}: {e}"}
            try:
                after["keymap"] = fp._keymap(svc)
            except Exception as e:                  # noqa: BLE001
                after["keymap"] = {"error": f"{type(e).__name__}: {e}"}
            (run_dir / "postflight.json").write_text(
                json.dumps(after, indent=1, default=str), encoding="utf-8")
            fp.compare_preflight(before, after, version_changed=False, log=log)
    except Exception as e:                          # noqa: BLE001 -- the verdict is the product
        if track["in_boot"]:
            _recover_left(svc, log)
        return log.finish(False, f"{type(e).__name__}: {e}")
    finally:
        # Whatever happened to the module, what the app believes it runs is now stale: the live
        # status caches a module's firmware per docking, and this module never left the bay.
        forget = getattr(svc, "forget_module_firmware", None)
        if forget is not None:
            try:
                forget()
            except Exception:                       # noqa: BLE001 -- a stale label, not a failure
                pass
        if held:
            lock.release()

    if log.failures:
        return log.finish(False, f"module firmware {pre['target']} is installed, but "
                                 f"{len(log.failures)} thing(s) on the keyboard do not match "
                                 "the backup")
    return log.finish(True, f"the {pre['module']['type']} runs module firmware {pre['target']}; "
                            "the keyboard matches its backup")
