"""A flash run can be watched while it runs, and watching it never blocks the app (SCRUM-102).

Three claims are under test, and each of them is a thing that was actually wrong or would have
been the moment a UI existed:

  * the run starts and the caller is answered IMMEDIATELY -- a request held open for the four to
    ten minutes a real run takes is a screen with nothing on it, which is when a user pulls the
    cable;
  * every line the procedure writes to its log also reaches the watcher, so the browser and the
    file cannot tell different stories;
  * the stream does not touch the service while a run holds the service lock. `svc.snapshot()`
    takes that lock, the run holds it for its whole duration, and the call used to sit on the
    event loop -- which would have frozen every route in the backend for the length of a flash.

No hardware, and no sockets: the stream is driven directly as the async generator it is.
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.api import sse                            # noqa: E402
from openflow_backend.device import flash_procedure as P        # noqa: E402
from openflow_backend.device import flash_runs as R             # noqa: E402


@pytest.fixture(autouse=True)
def _clean_registry():
    R.reset_for_tests()
    yield
    R.reset_for_tests()


def _wait_until(pred, timeout=5.0):
    end = __import__("time").monotonic() + timeout
    while __import__("time").monotonic() < end:
        if pred():
            return True
        __import__("time").sleep(0.01)
    return False


# --- the registry ------------------------------------------------------------------------------ #

def test_the_caller_is_answered_before_the_run_is_anywhere_near_finished(tmp_path):
    """start() returns the opening snapshot; the work goes on without it."""
    release = threading.Event()
    saw = []

    def work(on_event):
        on_event({"step": "preflight.capture", "phase": "start"})
        saw.append("running")
        release.wait(5)
        on_event({"step": "upload", "phase": "progress", "percent": 50})
        return {"ok": True, "summary": "done", "failures": [], "advisories": []}

    run = R.start("flash-1", ["left"], {"left": "kb_fwl.bin"}, tmp_path, work)

    # Answered while the work is still blocked: the verdict is not in yet.
    assert run.snapshot()["running"] is True
    assert run.snapshot()["verdict"] is None
    assert R.active() is True
    assert _wait_until(lambda: saw == ["running"])

    release.set()
    assert _wait_until(lambda: R.active() is False)
    final = run.snapshot()
    assert final["verdict"]["ok"] is True
    assert final["running"] is False
    assert [e["step"] for e in final["events"]] == ["preflight.capture", "upload"]


def test_a_client_asks_for_what_it_has_not_seen(tmp_path):
    """Events carry a sequence number so a reload, or a reconnected stream, misses nothing."""
    run = R.start("flash-2", ["left"], {}, tmp_path,
                  lambda on_event: [on_event({"step": f"s{i}", "phase": "ok"}) for i in range(4)]
                  and {"ok": True, "summary": "", "failures": [], "advisories": []})
    assert _wait_until(lambda: R.active() is False)

    first = run.snapshot()
    assert [e["seq"] for e in first["events"]] == [1, 2, 3, 4]
    later = run.snapshot(since=2)
    assert [e["step"] for e in later["events"]] == ["s2", "s3"]
    assert later["seq"] == 4                        # the client learns where it now stands
    assert run.snapshot(since=4)["events"] == []


def test_a_second_run_is_refused_while_one_is_going(tmp_path):
    """Two flashes at once would fight over the keyboard and over the service lock."""
    release = threading.Event()
    R.start("flash-3", ["left"], {}, tmp_path,
            lambda on_event: release.wait(5) and {"ok": True, "summary": "",
                                                  "failures": [], "advisories": []})
    with pytest.raises(R.RunBusy):
        R.start("flash-4", ["right"], {}, tmp_path, lambda on_event: None)
    release.set()
    assert _wait_until(lambda: R.active() is False)


def test_a_run_that_dies_still_produces_a_verdict(tmp_path):
    """A thread that raises must not leave the UI waiting on a run that is already over."""
    def work(on_event):
        on_event({"step": "identify", "phase": "start"})
        raise RuntimeError("the bootloader did not answer")

    run = R.start("flash-5", ["left"], {}, tmp_path, work)
    assert _wait_until(lambda: R.active() is False)
    v = run.snapshot()["verdict"]
    assert v["ok"] is False
    assert "the bootloader did not answer" in v["summary"]


# --- the procedure's log and the watcher agree -------------------------------------------------- #

def test_every_line_written_to_the_log_also_reaches_the_watcher(tmp_path):
    """The file is the evidence; the stream must be the same evidence, live."""
    seen = []
    log = P.RunLog(tmp_path / "run.log", {"sides": ["left"]}, on_event=seen.append)
    log.event("upload", "progress", side="left", percent=25)
    log.finish(True, "firmware written and verified")

    on_disk = [json.loads(line) for line in
               (tmp_path / "run.log").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert [e["step"] for e in on_disk] == ["run.start", "upload", "run.end"]
    assert [e["step"] for e in seen] == [e["step"] for e in on_disk]
    assert [e.get("percent") for e in seen] == [None, 25, None]


def test_a_watcher_that_throws_cannot_cost_the_log_a_line(tmp_path):
    """Nothing a subscriber does may interfere with a flash that is mid-write."""
    def angry(_e):
        raise ValueError("no")

    log = P.RunLog(tmp_path / "run.log", {}, on_event=angry)
    log.event("upload", "ok", side="left")
    lines = (tmp_path / "run.log").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["step"] for x in lines if x.strip()] == ["run.start", "upload"]


# --- the stream --------------------------------------------------------------------------------- #

class Svc:
    """A service whose status read is the thing a flash makes unavailable."""

    def __init__(self):
        self.snapshots = 0

    def list_devices(self):
        return [{"port": "COM30", "side": "left"}]

    def snapshot(self):
        self.snapshots += 1
        return {"halves": [{"side": "left", "firmwareVersion": "3.35.4", "at": "now"}],
                "released": False}


async def _drain(svc, ticks):
    """Pull `ticks` events out of the stream, then let it end."""
    left = {"n": ticks}

    async def disconnected():
        left["n"] -= 1
        return left["n"] < 0

    out = []
    async for e in sse.event_stream(svc, disconnected):
        out.append(e)
    return out


def test_while_a_run_is_going_the_stream_reports_it_and_leaves_the_service_alone(monkeypatch,
                                                                                tmp_path):
    """The claim that makes a progress UI possible at all.

    svc.snapshot() takes the service lock, which the run holds for its whole duration. If the
    stream asked for it here it would block the event loop -- the whole backend -- until the
    flash finished.
    """
    monkeypatch.setattr(sse, "FLASH_INTERVAL_S", 0)
    monkeypatch.setattr(sse, "POLL_INTERVAL_S", 0)
    svc = Svc()
    release = threading.Event()

    def work(on_event):
        on_event({"step": "upload", "phase": "progress", "percent": 5, "label": "Writing"})
        release.wait(5)
        return {"ok": True, "summary": "done", "failures": [], "advisories": []}

    R.start("flash-6", ["left"], {}, tmp_path, work)
    try:
        events = asyncio.run(_drain(svc, ticks=2))
    finally:
        release.set()
        _wait_until(lambda: R.active() is False)

    assert [e["event"] for e in events] == ["sse:ui-state-change",
                                            "sse:flash-progress", "sse:flash-progress"]
    assert svc.snapshots == 0
    first = json.loads(events[1]["data"])
    assert first["running"] is True
    assert first["events"][0]["step"] == "upload"
    # The second tick carries only what the first did not.
    assert json.loads(events[2]["data"])["events"] == []


def test_the_end_of_a_run_sends_the_verdict_and_then_a_fresh_device_state(monkeypatch, tmp_path):
    """The versions on screen just changed, so the device signature must not be trusted."""
    monkeypatch.setattr(sse, "FLASH_INTERVAL_S", 0)
    monkeypatch.setattr(sse, "POLL_INTERVAL_S", 0)
    svc = Svc()
    release = threading.Event()

    R.start("flash-7", ["left"], {}, tmp_path,
            lambda on_event: (on_event({"step": "run.start", "phase": "ok"}),
                              release.wait(5))
            and {"ok": True, "summary": "firmware written and verified",
                 "failures": [], "advisories": []})

    async def drive():
        left = {"n": 4}

        async def disconnected():
            left["n"] -= 1
            return left["n"] < 0

        out = []
        async for e in sse.event_stream(svc, disconnected):
            out.append(e)
            if len(out) == 2:                       # one progress tick seen: let the run finish
                release.set()
                _wait_until(lambda: R.active() is False)
        return out

    events = asyncio.run(drive())
    kinds = [e["event"] for e in events]
    assert kinds[:2] == ["sse:ui-state-change", "sse:flash-progress"]
    # The tick after the run ends: the verdict, then the devices, in that order.
    assert kinds[2:4] == ["sse:flash-progress", "sse:naya-devices-stream"]
    ending = json.loads(events[2]["data"])
    assert ending["running"] is False
    assert ending["verdict"]["summary"] == "firmware written and verified"
    assert svc.snapshots >= 1                       # only once the run was over


def test_the_route_answers_with_a_run_id_long_before_the_flash_is_done(monkeypatch, tmp_path):
    """POST /rpc/flash-procedure starts the run and returns; it does not hold the request open.

    The gate is reloaded open here, but nothing reaches a device: the procedure itself is
    replaced. What is under test is the endpoint's shape, not the flash.
    """
    import importlib

    from fastapi.testclient import TestClient

    from openflow_backend.api import rest
    from openflow_backend.app import create_app

    monkeypatch.setenv("OPENFLOW_ENABLE_FIRMWARE_FLASH", "1")
    monkeypatch.setattr(P, "logs_dir", lambda: tmp_path, raising=False)
    mod = importlib.reload(rest)
    assert mod.FIRMWARE_FLASH_ENABLED is True

    release = threading.Event()
    started = threading.Event()

    def fake_run(svc, targets, catalog, *, allow_older=False, log_dir=None, on_event=None,
                 flash_fn=None):
        started.set()
        on_event({"step": "preflight.capture", "phase": "start", "label": "Backing up"})
        release.wait(5)
        return {"ok": True, "summary": "firmware written and verified",
                "failures": [], "advisories": [], "log": str(log_dir)}

    monkeypatch.setattr(P, "run", fake_run)
    try:
        with TestClient(create_app()) as c:
            r = c.post("/rpc/flash-procedure", json={"targets": {"left": "kb_fwl.bin"}})
            assert r.status_code == 200
            body = r.json()
            assert body["running"] is True and body["verdict"] is None
            assert body["id"].startswith("flash-")          # the id is the log directory's name
            assert body["sides"] == ["left"]
            assert started.wait(5)

            # A second run, while the first is going, is refused rather than queued.
            again = c.post("/rpc/flash-procedure", json={"targets": {"left": "kb_fwl.bin"}})
            assert again.status_code == 409
            assert "already running" in again.json()["detail"]

            # And a client that missed the start can still catch up.
            live = c.get("/api/flash-runs/current").json()["run"]
            assert live["id"] == body["id"]
            assert [e["step"] for e in live["events"]] == ["preflight.capture"]
            assert c.get(f"/api/flash-runs/{body['id']}?since=1").json()["run"]["events"] == []

            release.set()
            assert _wait_until(lambda: R.active() is False)
            done = c.get("/api/flash-runs/current").json()["run"]
            assert done["running"] is False
            assert done["verdict"]["ok"] is True
    finally:
        release.set()
        monkeypatch.delenv("OPENFLOW_ENABLE_FIRMWARE_FLASH", raising=False)
        importlib.reload(rest)


def test_with_no_run_the_stream_polls_devices_off_the_event_loop(monkeypatch):
    """The poll is one threadpool hop (sse._poll), not a lock taken on the event loop."""
    monkeypatch.setattr(sse, "POLL_INTERVAL_S", 0)
    calls = []

    def fake_poll(svc):
        calls.append(svc)
        return "sig", {"devices": [], "status": {}}

    monkeypatch.setattr(sse, "_poll", fake_poll)
    svc = Svc()
    events = asyncio.run(_drain(svc, ticks=2))
    assert calls == [svc, svc]                      # both ticks went through the helper
    # The signature did not change on the second tick, so only one device event was sent.
    assert [e["event"] for e in events] == ["sse:ui-state-change", "sse:naya-devices-stream"]
    assert svc.snapshots == 0                       # the real poll was replaced; nothing inline
