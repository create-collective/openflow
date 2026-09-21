"""A flash run you can watch while it is still running (SCRUM-102).

`flash_procedure.run` is a blocking call that takes four to ten minutes and writes every step to
disk. That is the right shape for the procedure and the wrong shape for a browser: an HTTP request
held open for ten minutes tells the user nothing while it is open, and the one thing that turns a
working flash into a brick is a user who pulls the cable because the screen looks frozen.

So the run happens on its own thread and everything it logs is ALSO published here, in memory, for
anyone who asks. This module is the seam between the two:

  * the procedure writes its log exactly as before -- the file on disk is still the evidence;
  * each event is handed to the run's `publish` as it is written, so the stream and the file
    cannot disagree about what happened;
  * readers get events by sequence number, so a page that reloads mid-run, or an SSE client that
    reconnects, asks for "everything after 47" and misses nothing.

WHY THIS HOLDS ITS OWN LOCK, AND ONLY ITS OWN
---------------------------------------------
The procedure holds the SERVICE lock for its whole duration so nothing touches either COM port
between Go and the verdict (see flash_procedure.run). Anything that wants to report progress must
therefore never take that lock, not even briefly -- it would block until the run it is reporting
on has finished, which is the one moment the report is worthless. The lock here guards a dict and
a list and is held for microseconds at a time. Nothing in this module does device I/O.

`active()` is deliberately a plain bool read with no lock at all: the SSE loop calls it on the
event loop thread on every tick, and it must never be able to block there.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from pathlib import Path

# How many finished runs stay in memory. The log on disk is the permanent record (/api/flash-logs);
# this is only so a user who walks away mid-run and comes back still finds the verdict on screen.
KEEP_RUNS = 8

_lock = threading.Lock()
_runs: dict[str, "Run"] = {}
_order: list[str] = []
_current: str | None = None
_active = False          # read without the lock, by the SSE loop, on every tick


class RunBusy(RuntimeError):
    """A second run was asked for while one was still going."""


class Run:
    """One run's live state: what it is doing, what it has said so far, and how it ended."""

    def __init__(self, run_id: str, sides: list[str], images: dict, log_dir: Path):
        self.id = run_id
        self.sides = list(sides)
        self.images = {k: str(v) for k, v in images.items()}
        self.log_dir = Path(log_dir)
        self.started_at = datetime.now().isoformat(timespec="seconds")
        self._t0 = time.monotonic()
        self.events: list[dict] = []
        self.seq = 0
        self.verdict: dict | None = None
        self.finished_at: str | None = None

    # --- writing ---------------------------------------------------------------------------- #

    def publish(self, event: dict) -> None:
        """Record one event from the procedure. Called on the flashing thread, per log line."""
        with _lock:
            self.seq += 1
            e = dict(event)
            e["seq"] = self.seq
            self.events.append(e)

    def finish(self, verdict: dict) -> None:
        global _active
        with _lock:
            self.verdict = dict(verdict)
            self.finished_at = datetime.now().isoformat(timespec="seconds")
            _active = False

    # --- reading ---------------------------------------------------------------------------- #

    def snapshot(self, since: int = 0) -> dict:
        """Everything a client needs, with only the events it has not seen.

        `since` is the last seq the client holds. 0 (the default) means "I have nothing", which is
        what a page that just loaded, or one that reconnected after a dropped stream, should send.
        """
        with _lock:
            events = [e for e in self.events if e["seq"] > since]
            running = self.verdict is None
            return {
                "id": self.id,
                "running": running,
                "sides": list(self.sides),
                "images": dict(self.images),
                "startedAt": self.started_at,
                "finishedAt": self.finished_at,
                "elapsedMs": int((time.monotonic() - self._t0) * 1000),
                "seq": self.seq,
                "events": events,
                "verdict": dict(self.verdict) if self.verdict else None,
            }


# --- the registry ----------------------------------------------------------------------------- #

def active() -> bool:
    """Is a run going right now? No lock: the SSE loop asks this on the event loop thread."""
    return _active


def current() -> Run | None:
    with _lock:
        return _runs.get(_current) if _current else None


def get(run_id: str) -> Run | None:
    with _lock:
        return _runs.get(run_id)


def _remember(run: Run) -> None:
    global _current, _active
    with _lock:
        _runs[run.id] = run
        _order.append(run.id)
        while len(_order) > KEEP_RUNS:
            _runs.pop(_order.pop(0), None)
        _current = run.id
        _active = True


def start(run_id: str, sides: list[str], images: dict, log_dir: Path, work) -> Run:
    """Register a run and drive `work(on_event)` on a thread of its own.

    `work` is handed the run's `publish` and must call it for every event it logs. Whatever it
    returns becomes the verdict; whatever it raises becomes a failed verdict, because a thread
    that dies silently would leave the UI waiting forever on a run that is already over.

    Refuses while another run is going. Two flashes at once would fight over the service lock and
    over the keyboard, and the second would sit holding a dead progress stream until the first
    finished -- a state with no good way to explain itself on screen.
    """
    if active():
        raise RunBusy("a firmware flash is already running; wait for it to finish")

    run = Run(run_id, sides, images, log_dir)
    _remember(run)

    def drive() -> None:
        try:
            verdict = work(run.publish)
        except BaseException as e:                  # noqa: BLE001 -- a dead thread must still report
            verdict = {"ok": False, "summary": f"{type(e).__name__}: {e}",
                       "failures": [str(e)], "advisories": [], "log": str(run.log_dir / "run.log")}
        run.finish(verdict or {"ok": False, "summary": "the run ended without a verdict",
                               "failures": [], "advisories": []})

    threading.Thread(target=drive, name=f"flash-{run_id}", daemon=True).start()
    return run


def reset_for_tests() -> None:
    """Forget every run. Tests only -- the registry is process-wide by design."""
    global _current, _active
    with _lock:
        _runs.clear()
        _order.clear()
        _current = None
        _active = False
