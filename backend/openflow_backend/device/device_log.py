"""A ring buffer of every exchange with a connected keyboard, for the Settings > Logging tab.

Why: when NayaFlow flashed this owner's board it reported failure while the flash had actually
landed, and only NayaFlow's own log said what was really failing. OpenFlow had no equivalent --
reads, writes and every nayactl round trip happened silently. This records them: what was sent
(category/subcommand or text or raw frame), to which port, how long it took, and what came back
(response count, validity, or the error).

It is device I/O only -- keymap bytes, LED bytes, status queries -- nothing user-identifying, so
it is kept in memory and shown on request. Bounded, so a long session cannot grow without limit.
The vendored nayactl transport is NOT modified; LoggingTransport wraps it at the OpenFlow layer.
"""
from __future__ import annotations

import time
from collections import deque
from datetime import datetime
from pathlib import Path
from threading import Lock

_MAX = 500                 # entries kept in memory for the tab's quick view
RETENTION_DAYS = 14        # days of daily log files kept on disk; older are pruned
_log: deque[dict] = deque(maxlen=_MAX)
_lock = Lock()
_seq = 0
_pruned = False


def _log_path(day: str | None = None) -> Path | None:
    """Today's device log file under the data dir's logs/, or None if the dir is unavailable."""
    try:
        from ..config import logs_dir
        day = day or datetime.now().strftime("%Y-%m-%d")
        return logs_dir() / f"device-{day}.log"
    except Exception:
        return None


def prune_old(days: int = RETENTION_DAYS) -> int:
    """Delete device-*.log files older than `days`. A keyboard can sit plugged in for years;
    the on-disk log must not grow without bound. Returns how many were removed."""
    try:
        from ..config import logs_dir
        d = logs_dir()
    except Exception:
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for f in d.glob("device-*.log"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1
        except OSError:
            pass
    return removed


def _append_to_file(entry: dict) -> None:
    """One line per exchange, appended to today's file. Best-effort: a logging failure must never
    break device I/O, so every error here is swallowed."""
    global _pruned
    p = _log_path()
    if p is None:
        return
    try:
        if not _pruned:            # prune once per process, lazily on first write
            _pruned = True
            prune_old()
        line = (f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  {entry['kind']:<8} "
                f"{entry['port']:<8} {'ok ' if entry['ok'] else 'ERR'} {entry['ms']:>7}ms  "
                f"{entry['detail']}\n")
        with p.open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def record(kind: str, port: str, detail: str, *, ok: bool, ms: float, extra: dict | None = None) -> None:
    global _seq
    with _lock:
        _seq += 1
        entry = {
            "seq": _seq,
            "at": time.strftime("%H:%M:%S", time.localtime()),
            "ts": round(time.time(), 3),
            "kind": kind,          # command | text | raw
            "port": port,
            "detail": detail,      # human-readable summary of what was sent
            "ok": ok,
            "ms": round(ms, 1),
            **(extra or {}),
        }
        _log.append(entry)
        _append_to_file(entry)


def entries(limit: int = 200) -> list[dict]:
    with _lock:
        items = list(_log)
    return items[-limit:]


def clear() -> None:
    with _lock:
        _log.clear()


def _summarise_responses(resp) -> tuple[bool, str]:
    """A one-line result: how many frames came back and whether they parsed/checksummed."""
    try:
        rs = list(resp or [])
    except TypeError:
        return True, "sent"
    if not rs:
        return True, "no response"
    valid = sum(1 for r in rs if getattr(r, "valid", False))
    csum = sum(1 for r in rs if getattr(r, "checksum_ok", False))
    return True, f"{len(rs)} frame(s), {valid} valid, {csum} checksum-ok"


class LoggingTransport:
    """Delegates everything to a real transport, but records each send and its outcome.

    Attribute access falls through to the wrapped transport (so `_ser`, `is_connected`,
    `connect`, `disconnect`, the liveness check and everything else behave unchanged); only the
    three send paths are intercepted. The wrapped transport's own internal `_send_raw` (the one
    send_command/send_text call inside themselves) is NOT seen here, so a command is logged once,
    not twice.
    """
    def __init__(self, inner, port: str):
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "_port", port)

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def __setattr__(self, name, value):
        setattr(self._inner, name, value)

    # human labels for the CDC categories, without importing the whole constants surface
    _CAT = {0x30: "REMAP", 0xBE: "BLE", 0xDE: "MODULE", 0xED: "LED", 0xEE: "RESET",
            0xF1: "FIRMWARE", 0xFA: "FLASH", 0xFE: "SYSTEM", 0xFF: "META", 0xCA: "CHARGER"}

    # Every send forwards *args/**kwargs VERBATIM to the wrapped transport, so a caller passing
    # four positionals reaches a four-positional signature unchanged -- the wrapper never widens
    # the call. Logging reads the leading args only, defensively.
    def send_command(self, *args, **kwargs):
        dest = args[0] if len(args) > 0 else kwargs.get("dest")
        category = args[1] if len(args) > 1 else kwargs.get("category")
        subcmd = args[2] if len(args) > 2 else kwargs.get("subcmd")
        payload = args[3] if len(args) > 3 else kwargs.get("payload", b"")
        cat = self._CAT.get(category, f"{category:#04x}" if isinstance(category, int) else str(category))
        sub = f"{subcmd:#06x}" if isinstance(subcmd, int) else str(subcmd)
        detail = f"{cat} sub={sub} payload[{len(payload or b'')}]={bytes(payload or b'').hex()[:24]}"
        return self._run("command", detail, lambda: self._inner.send_command(*args, **kwargs), _summarise_responses)

    def send_text(self, *args, **kwargs):
        command = args[0] if args else kwargs.get("command", "")
        return self._run("text", repr(command), lambda: self._inner.send_text(*args, **kwargs),
                         lambda r: (True, f"{len(r or '')} chars"))

    def send_raw(self, *args, **kwargs):
        data = args[0] if args else kwargs.get("data", b"")
        return self._run("raw", f"frame[{len(data)}]={bytes(data).hex()[:32]}",
                         lambda: self._inner.send_raw(*args, **kwargs), _summarise_responses)

    def _send_raw(self, *args, **kwargs):
        data = args[0] if args else kwargs.get("data", b"")
        return self._run("raw", f"frame[{len(data)}]={bytes(data).hex()[:32]}",
                         lambda: self._inner._send_raw(*args, **kwargs), _summarise_responses)

    def _run(self, kind, detail, call, summarise):
        t0 = time.perf_counter()
        try:
            resp = call()
            ok, summary = summarise(resp)
            record(kind, self._port, f"{detail} -> {summary}", ok=ok, ms=(time.perf_counter() - t0) * 1000)
            return resp
        except Exception as e:
            record(kind, self._port, f"{detail} -> ERROR {type(e).__name__}: {e}", ok=False,
                   ms=(time.perf_counter() - t0) * 1000)
            raise
