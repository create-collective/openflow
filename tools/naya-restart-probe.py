#!/usr/bin/env python3
"""naya-restart-probe: after a plain restart, does a Create half come back on USB by itself?

WHAT IT DOES TO THE KEYBOARD: it restarts one half, several times -- the same restart the
keyboard does after a firmware or module update. Nothing is written: no keymap, no settings, no
firmware. The half runs on its battery throughout.

    pip install pyserial
    python naya-restart-probe.py                   # left half, 10 restarts
    python naya-restart-probe.py --side right --trials 5

Plug in ONLY the half you are testing. After each restart it watches the USB bus for up to 15 s.
If the half has not come back by then, it asks you to unplug that half's USB cable, count to
five, and plug it back in, then carries on. At the end it writes naya-restart-probe-<time>.json
next to this file. Send that file back.

Why: on the OpenFlow project's test board (flash generation A, Windows 11) the half came back
by itself after only 2 of 5 restarts. Every restart passes through the bootloader, which opens
its own USB connection for about a second and then hands over to the keyboard firmware; the
stuck restarts look identical up to that handover and then nothing appears on the bus until the
cable is replugged. Reports from other computers (macOS, Linux, other Windows PCs), other
cables and ports, and generation-B boards say whether that is this PC or the keyboard.

Facts this relies on, measured on real Creates by the OpenFlow project (traviswye/NayaOS):
  * Naya's USB vendor id is 0x37D1. pid & 0xEFFF: 0x064 left app, 0x06F left bootloader,
    0x0C8 right app, 0x0D3 right bootloader; bit 0x1000 set = flash generation B.
  * The keyboard's command channel wakes on MEDIA_ID_REQUEST (0xFE/0x1001) followed by
    GET_FW_VERSION (0xFE/0x1002); RESET/NORMAL is 0xEE/0x10CE. Frames are
    [0xAA, 0, dest, 0, category, size, sub_hi, sub_lo, flags, payload..., xor, 0x04], with
    dest 0x50 for the left half and 0x51 for the right.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import serial
    from serial.tools.list_ports import comports
except ImportError:                                   # pragma: no cover
    print("This needs pyserial:  pip install pyserial")
    sys.exit(2)

VERSION = "1"
NAYA_VID = 0x37D1
GEN_B = 0x1000
APP = {"left": 0x064, "right": 0x0C8}
BOOT = {"left": 0x06F, "right": 0x0D3}
DEST = {"left": 0x50, "right": 0x51}
BACK_WAIT = 15.0          # seconds to come back by itself
REPLUG_WAIT = 180.0       # seconds to wait for a replugged half


def frame(dest: int, category: int, sub: int, payload: bytes = b"") -> bytes:
    data = bytes([(sub >> 8) & 0xFF, sub & 0xFF, 0x00]) + payload
    x = 0
    for b in data:
        x ^= b
    return bytes([0xAA, 0x00, dest, 0x00, category, len(data)]) + data + bytes([x, 0x04])


def naya_ports():
    return [p for p in comports() if p.vid == NAYA_VID]


def where(side: str) -> tuple[str, object]:
    """'app', 'boot' or 'gone' for this half, with the port when it is in its application."""
    for p in naya_ports():
        fam = (p.pid or 0) & 0xEFFF
        if fam == APP[side]:
            return "app", p
    for p in naya_ports():
        if ((p.pid or 0) & 0xEFFF) == BOOT[side]:
            return "boot", p
    return "gone", None


def open_port(device: str):
    s = serial.Serial(port=device, baudrate=115200, bytesize=serial.EIGHTBITS,
                      parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, timeout=0.1,
                      dsrdtr=False, write_timeout=2.0)
    s.dtr = True
    s.rts = True
    time.sleep(0.1)
    s.read(4096)
    return s


def wake(s, dest: int) -> str | None:
    """The handshake the keyboard needs before it takes commands; returns its firmware version."""
    for wait in (0.3, 0.7, 1.0):
        s.write(frame(dest, 0xFE, 0x1001))
        time.sleep(wait)
        s.read(4096)
        s.write(frame(dest, 0xFE, 0x1002))
        time.sleep(0.5)
        raw = s.read(4096)
        i = raw.find(b"\xaa")
        if i >= 0 and len(raw) >= i + 13 and raw[i + 4] == 0xFE:
            p = raw[i + 9:i + 13]
            return f"{p[1]}.{p[2]}.{p[3]}"
    return None


def watch(side: str, seconds: float, t0: float, events: list) -> bool:
    last = events[-1][1] if events else None
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        s, _ = where(side)
        if s != last:
            events.append([round(time.monotonic() - t0, 2), s])
            last = s
            if s == "app" and any(e[1] != "app" for e in events):
                return True
        time.sleep(0.1)
    return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--side", choices=("left", "right"), default="left")
    ap.add_argument("--trials", type=int, default=10)
    ap.add_argument("--note", default="", help="anything worth recording: cable, port, hub")
    a = ap.parse_args()

    state, port = where(a.side)
    if state != "app":
        print(f"No {a.side} half running its application was found. Plug it in and try again.")
        print("Naya ports seen:", [(p.device, hex(p.pid or 0)) for p in naya_ports()] or "none")
        return 1
    others = [p for p in naya_ports() if p.device != port.device]
    report = {
        "tool": f"naya-restart-probe {VERSION}", "at": datetime.now().isoformat(timespec="seconds"),
        "host": {"os": platform.platform(), "python": platform.python_version(),
                 "pyserial": getattr(serial, "__version__", "?"), "machine": platform.machine()},
        "half": {"side": a.side, "port": port.device, "pid": hex(port.pid),
                 "generation": "B" if port.pid & GEN_B else "A",
                 "serialNumber": port.serial_number, "description": port.description,
                 "location": getattr(port, "location", None), "hwid": port.hwid},
        "otherNayaPorts": [(p.device, hex(p.pid or 0)) for p in others],
        "note": a.note, "trials": [],
    }
    print(f"{a.side} half on {port.device}, flash generation {report['half']['generation']}, "
          f"{a.trials} restarts. Leave it plugged in unless asked.\n")

    try:
        for i in range(1, a.trials + 1):
            for _ in range(120):                    # settled in its application first
                if where(a.side)[0] == "app":
                    break
                time.sleep(0.5)
            time.sleep(3.0)
            state, port = where(a.side)
            trial = {"trial": i, "at": datetime.now().strftime("%H:%M:%S")}
            try:
                s = open_port(port.device)
                trial["firmware"] = wake(s, DEST[a.side])
                s.write(frame(DEST[a.side], 0xEE, 0x10CE))
                s.flush()
                time.sleep(0.2)
                s.close()
            except Exception as e:                  # it restarts mid-write; recorded, not fatal
                trial["sendError"] = f"{type(e).__name__}: {e}"
            t0 = time.monotonic()
            events = [[0.0, "app"]]
            if watch(a.side, BACK_WAIT, t0, events):
                trial["result"] = "back by itself"
            else:
                print(f"  trial {i}: not back after {BACK_WAIT:.0f} s. Unplug the {a.side} half's "
                      "USB cable, count to five, plug it back in.")
                trial["result"] = ("back after replug" if watch(a.side, REPLUG_WAIT, t0, events)
                                   else "never came back")
            trial["events"] = events
            report["trials"].append(trial)
            print(f"  trial {i}: {trial['result']}   " +
                  " ".join(f"{t:>5}s {s}" for t, s in events[1:]))
            if trial["result"] == "never came back":
                break
    except KeyboardInterrupt:
        print("\nstopped; writing what was measured")

    n = len(report["trials"])
    back = sum(t["result"] == "back by itself" for t in report["trials"])
    report["summary"] = f"{back} of {n} restarts came back by themselves"
    out = Path(__file__).with_name(f"naya-restart-probe-{datetime.now():%Y%m%d-%H%M%S}.json")
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"\n{report['summary']}. Report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
