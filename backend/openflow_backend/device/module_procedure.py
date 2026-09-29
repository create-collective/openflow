"""Module firmware as a PROCEDURE, in the order NayaFlow runs it, with the same audit log as a
keyboard flash (device/flash_procedure.py).

MEASURED, not inferred: NayaFlow 1.25.1 updating a Touch 2.1.2 -> 2.3.3 on a 3.41.0 left half,
captured with USBPcap and NayaCore's own log on 2026-09-23 (device/out/module-fw-touch1-20260923*,
docs in create-legacy-firmware FLASHING-PROCEDURE.md). NayaCore v6.11.0 does this:

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
module in the LEFT bay, and a bundle no newer than the left half's firmware can take
(firmware_upload.require_module_pairing: each bundle's minimum keyboard firmware comes from every
official and beta release, see tools/build_firmware_catalog.py; older bundles on newer keyboards
are fine). A right-bay module is moved to the left bay.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from . import firmware_upload as fw
from . import flash_procedure as fp
from . import recovery as rec

# MODULE_FWUP's byte per module type: only values captured from NayaCore (see recovery_ops).
from .recovery_ops import FWUP_TYPES                   # noqa: E402

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
    """What is docked in the LEFT bay (flash_procedure.docked_module)."""
    return fp.docked_module(svc, "left")


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
    """The catalogue entry to install. With no `version`, the NEWEST bundle the left half's
    firmware can take -- on a current keyboard, the one NayaFlow carries."""
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
            f"no module firmware we hold works on keyboard firmware {keyboard_version}, so "
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
               force_upload: bool, firmware_root: Path | None,
               force_type: str | None = None) -> dict:
    """Every precondition, before anything is written. Returns what the run needs.

    `force_type` is NayaFlow's Danger Zone "Force Update" (captured 2026-09-23): the same
    sequence, with the type byte the user picked instead of the one read off the dock -- for a
    module that does not identify properly, which is exactly what it rescued (a Tune reporting
    0x4A after being given the wrong app). The module need not be recognised, or even detected;
    afterwards it must identify as the forced type."""
    if force_type is not None and force_type not in FWUP_TYPES:
        raise ModuleRefused(f"Force Update can program a {' or a '.join(FWUP_TYPES)} (the types "
                            f"whose byte has been captured), not {force_type}. Nothing was written.")
    if not _present(svc, "left"):
        raise ModuleRefused("the left half is not connected. Plug in the LEFT half's USB cable.")
    if _present(svc, "right"):
        raise ModuleRefused(
            "the right half is connected. Unplug the right half's USB cable: module firmware is "
            "updated with only the LEFT half connected, as NayaFlow requires. Nothing was written.")
    ident = fp._identity(svc, "left")
    kb = ident.get("firmwareVersion")
    module = _find_module(svc, 10.0, want_version=force_type is None)
    if force_type is not None:
        module = dict(module or {"type": None, "address": None, "docked": "left",
                                 "firmwareVersion": None})
    elif module is None:
        raise ModuleRefused(
            "no module is docked on the left half, or it is switched off. Dock the module you want "
            "to update in the LEFT bay and switch it on; it can take a few seconds to be found, "
            "and a Tune up to a minute the first time. Nothing was written.")
    if module.get("docked") not in (None, "left"):
        raise ModuleRefused(f"the module reports the {module.get('docked')} bay; it must be in the "
                            "LEFT bay. Nothing was written.")
    kind = force_type or module.get("type")
    # Forced: whatever the module reads as, the user named it (that is what Force Update is for).
    if force_type is None and module.get("type") not in FWUP_TYPES:
        raise ModuleRefused(f"the docked module reads as {module.get('type')}; OpenFlow can update "
                            "a Touch, a Tune or a Track, and Force Update can reprogram one that no "
                            "longer identifies. Nothing was written.")
    entry = choose_bundle(catalog, kb, version)
    target = entry.get("moduleFirmware")
    path = bundle_path(entry, firmware_root)
    stored = _stored_bundle(svc)
    running = module.get("firmwareVersion")
    have, want = fw._version_tuple(running), fw._version_tuple(target)
    if have and want and want < have and not allow_older and force_type is None:
        raise ModuleRefused(
            f"module firmware {target} is older than the {running} this {kind} runs. "
            "Pass allow_older to say you meant it. Nothing was written.")
    upload = force_upload or stored != target
    program = force_type is not None or running != target
    log.event("preflight.check", "ok", side="left", keyboard=kb, module=module, storedBundle=stored,
              target=target, keyboardRange=entry.get("keyboardRange"), upload=upload,
              program=program, forceUpload=force_upload, forceType=force_type,
              detail=(f"left half {kb}, {module.get('type') or 'no module identified'} on "
                      f"{running or 'unknown'}, keyboard holds module firmware "
                      f"{stored or 'unknown'}, installing {target}"
                      + (f" as a FORCED {force_type}" if force_type else "")))
    return {"ident": ident, "keyboard": kb, "module": module, "entry": entry, "target": target,
            "path": path, "stored": stored, "upload": upload, "program": program,
            "kind": kind, "forceType": force_type}


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


def _slot_map(state: dict, log: fp.RunLog, link=None) -> tuple[dict | None, bool]:
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
            info = link.slot_info() if link is not None else rec.slot_info(state["port"])
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


def _identify_linked(link, catalog: list, tries: int = 5) -> dict:
    """What the half in the bootloader runs, over the held link, retried on the SAME port (no
    reopen). Refuses a half whose product id names the other side."""
    last = None
    for _ in range(tries):
        try:
            state = rec.read_running_image_linked(link, catalog)
            seen = state.get("pidSide")
            if seen not in (None, "left"):
                raise fw.UploadRefused(f"the half in the bootloader reports itself as {seen}, "
                                       "not left. Nothing was written.")
            return state
        except fw.UploadRefused:
            raise
        except Exception as e:                      # noqa: BLE001 -- retried below
            last = e
            time.sleep(1.0)
    raise fw.UploadRefused(f"the left half's bootloader did not say what it runs ({last}). "
                           "Nothing was written.")


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

    # ONE conversation for the whole visit, as NayaCore holds it: both of the half's ports open,
    # the console drained, the data port kept for identify, the slot map and every chunk
    # (recovery.BootloaderLink). Reopening per request is what made the bootloader answer late.
    link = rec.BootloaderLink("left")
    with log.step("identify", side="left"):
        link.__enter__()
        try:
            state = _identify_linked(link, catalog)
        except Exception:
            link.__exit__(None, None, None)
            raise
        running = next((i for i in state.get("images") or [] if i.get("slot") == 0), {})
        log.event("identify", "ok", side="left", running=running.get("createFirmware"),
                  port=state.get("port"), armToken=running.get("hash"))
        slot_info, unmapped = _slot_map(state, log, link)

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
    try:
        result = upload_fn(pre["path"], catalog, arm=running.get("hash") or "",
                           installed_version=pre["stored"], allow_older=allow_older,
                           progress=progress, state=state, slot_info=slot_info,
                           allow_unmapped=unmapped, link=link)
    finally:
        console = link.console_text()
        link.__exit__(None, None, None)
        if console.strip():
            log.event("upload", "note", side="left", console=console,
                      detail="what the bootloader's console said during the visit")
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
        forced = pre.get("forceType")
        module = _find_module(svc, 10.0 if forced else MODULE_FIND_WAIT, want_version=False)
        if module is None and not forced:
            raise fw.UploadRefused("the module was not found after the keyboard restarted. Check it "
                                   "is docked in the LEFT bay and switched on, then run the update "
                                   "again; the keyboard already holds the bundle.")
        kind = forced or (module or {}).get("type")
        code = FWUP_TYPES.get(kind)
        if code is None:
            raise fw.UploadRefused(f"the docked module reads as {kind}, which cannot be programmed.")

        def go(t, dest, dev):
            try:
                t.send_command(dest, C.CAT_MODULE, C.MOD_FWUP, bytes([code]), timeout=2.0)
            except Exception:                       # noqa: BLE001 -- it answers nothing (measured)
                pass
            return True
        svc._with_transport("left", go)
        log.event("module.program", "note", side="left", module=kind, code=code, forced=bool(forced),
                  detail=f"MODULE_FWUP sent ({kind}{', forced' if forced else ''}, {code:02X}). The module's lights "
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
        # The version alone cannot catch a module programmed with the WRONG app: every app in a
        # bundle carries the bundle's version. On 2026-09-23 a Tune given nayactl's numbering's
        # 03 read 2.3.3 and passed, dark, reporting dock address 0x4A. So the module must also still
        # say it is the type it was -- given time, since a Tune's first update can take up to a
        # minute to settle.
        want_type = pre.get("kind") or pre["module"].get("type")
        deadline = time.monotonic() + MODULE_FIND_WAIT
        module = None
        while True:
            module = _find_module(svc, max(1.0, deadline - time.monotonic()))
            if module and module.get("type") == want_type and module.get("firmwareVersion"):
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(2.0)
        got = module.get("firmwareVersion") if module else None
        got_type = (module or {}).get("type")
        ok = got == pre["target"] and got_type == want_type
        log.event("module.verify", "ok" if ok else "fail", side="left", expected=pre["target"],
                  got=got, module=got_type, expectedModule=want_type,
                  address=(module or {}).get("address"))
        if got_type != want_type:
            raise fw.UploadRefused(
                f"the module no longer identifies as a {want_type}: it reports "
                f"{got_type or 'nothing'} (dock address "
                f"{hex((module or {}).get('address') or 0)}), firmware {got or 'unknown'}. It may "
                f"have been programmed with the wrong app. NayaFlow's Danger Zone Force Update -> "
                f"{want_type} restores it.")
        if got != pre["target"]:
            raise fw.UploadRefused(
                f"the module reports {got or 'nothing'} after programming, not {pre['target']}.")


# The blockers Force Update lifts: it exists for the module that does not identify (or is not
# detected at all). Nothing else is lifted: the right half must still be unplugged, and the
# version must still be one the keyboard can take.
FORCE_LIFTS = ("no-module", "unknown-module")


def plan(svc, catalog: list, firmware_root: Path | None, version: str | None = None) -> dict:
    """What an update WOULD do, for the dialog, and everything that would stop it. Reads only.

    Never raises for a board that is not ready: every precondition the run enforces is reported
    here as a `blockers` entry, {code, text}, the text in plain language so the screen can say
    what to do before anyone presses Go -- plug in the left half, unplug the right one, dock the
    module. The code lets the screen tell which ones Force Update lifts (FORCE_LIFTS).
    """
    out: dict = {"left": None, "rightConnected": _present(svc, "right"), "module": None,
                 "storedBundle": None, "keyboardFirmware": None, "versions": [], "target": None,
                 "blockers": [], "forceTypes": list(FWUP_TYPES), "forceLifts": list(FORCE_LIFTS)}
    blockers = out["blockers"]

    def block(code, text):
        blockers.append({"code": code, "text": text})

    if not _present(svc, "left"):
        block("left-missing", "Plug in the LEFT half's USB cable. Module firmware goes through the "
                              "left half.")
        return out
    if out["rightConnected"]:
        block("right-connected", "Unplug the RIGHT half's USB cable. Modules are updated with only "
                                 "the left half connected, as NayaFlow requires.")
    try:
        ident = fp._identity(svc, "left")
        out["left"] = {"firmwareVersion": ident.get("firmwareVersion"), "port": ident.get("port")}
        out["keyboardFirmware"] = ident.get("firmwareVersion")
    except Exception as e:                          # noqa: BLE001 -- reported, not raised
        block("left-silent", f"The left half did not answer ({type(e).__name__}). Replug it and "
                             "try again.")
        return out
    try:
        out["module"] = read_module(svc)
    except Exception:                               # noqa: BLE001
        out["module"] = None
    m = out["module"]
    if not m:
        block("no-module", "Dock the module you want to update in the LEFT bay and switch it on. "
                           "It can take a few seconds to be found, and a Tune up to a minute the "
                           "first time. A module that is docked but never shows up can be reached "
                           "with Force Update.")
    elif m.get("docked") not in (None, "left"):
        block("wrong-bay", f"The module reports the {m.get('docked')} bay; move it to the LEFT bay.")
    elif m.get("type") not in FWUP_TYPES:
        block("unknown-module", f"The docked module does not identify as a known type "
                                f"({m.get('type')}). Force update module can reprogram it as the "
                                "type you name.")
    out["storedBundle"] = _stored_bundle(svc)

    kb = out["keyboardFirmware"]
    bundles = sorted((e for e in catalog if e.get("type") == "littlefs"
                      and e.get("target") == "module" and e.get("flashable")),
                     key=lambda e: fw._version_tuple(e.get("moduleFirmware")) or (), reverse=True)
    for e in bundles:
        rel = e.get("historyPath")
        present = bool(firmware_root and rel and (Path(firmware_root) / rel).is_file())
        out["versions"].append({
            "version": e.get("moduleFirmware"), "fits": fw.module_bundle_fits(e, kb),
            "needsKeyboard": (e.get("keyboardRange") or {}).get("from"),
            "present": present, "historyPath": rel,
            "fetchable": not present and bool(rel and e.get("blobSha256"))})
    fitting = [v for v in out["versions"] if v["fits"]]
    chosen = next((v for v in out["versions"] if v["version"] == version), None) if version \
        else (fitting[0] if fitting else None)
    if chosen is None:
        block("no-version", f"No module firmware we hold works on keyboard firmware {kb}."
                            if not version else f"Module firmware {version} is not in the catalogue.")
        return out
    running = (m or {}).get("firmwareVersion")
    have, want = fw._version_tuple(running), fw._version_tuple(chosen["version"])
    out["target"] = {
        "version": chosen["version"], "present": chosen["present"],
        "fetchable": chosen["fetchable"], "historyPath": chosen["historyPath"],
        "upload": out["storedBundle"] != chosen["version"],
        "program": running != chosen["version"],
        "downgrade": bool(have and want and want < have),
        "unchanged": running == chosen["version"] and out["storedBundle"] == chosen["version"]}
    if not chosen["fits"]:
        block("too-new", f"Module firmware {chosen['version']} needs keyboard firmware "
                         f"{chosen['needsKeyboard']} or newer; this keyboard runs {kb}. Update the "
                         "keyboard first.")
    if not chosen["present"]:
        block("not-downloaded", f"Module firmware {chosen['version']} has not been downloaded yet.")
    return out


def run(svc, catalog: list, *, version: str | None = None, allow_older: bool = False,
        force_upload: bool = False, firmware_root: Path | None = None,
        log_dir: Path | None = None, upload_fn=None, on_event=None,
        force_type: str | None = None) -> dict:
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
                     "allowOlder": allow_older, "forceUpload": force_upload,
                     "forceType": force_type},
                    on_event=on_event)

    # The service lock for the whole run, as the keyboard procedure holds it: nothing else may
    # talk to the left half between Go and the verdict. The live tick polls the module bay every
    # few seconds, and NayaFlow sent nothing at all between MODULE_FWUP and the restart.
    lock = getattr(svc, "_lock", None)
    held = lock.acquire() is not False if lock is not None else False
    track = {"in_boot": False}
    try:
        with log.step("preflight.check", side="left"):
            pre = _preflight(svc, log, catalog, version, allow_older, force_upload, firmware_root,
                             force_type)
        if not pre["upload"] and not pre["program"]:
            return log.finish(True, f"the {pre['kind']} already runs {pre['target']} and "
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
    return log.finish(True, f"the {pre['kind']} runs module firmware {pre['target']}; "
                            "the keyboard matches its backup")
