"""Which binary a half takes is decided before anything enters the bootloader (SCRUM-104).

Left and right are different images, and so are flash generations A and B. `plan()` refuses a
mismatch -- but by then the half is in MCUboot, where it does not type and shows no lights, which
to the person holding it is indistinguishable from a brick. The product id says both facts while
the half is still running the application, so the choice is made from the catalogue up front and
the UI is never asked to know that kb_fwl.bin and kb_fwl_64.bin both exist.

The other half of the endpoint is honesty about what is missing: the catalogue is committed, the
images are not, so a version can be offered and unobtainable. That has to be visible on the
screen that offers it.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from fastapi import FastAPI                        # noqa: E402
from fastapi.testclient import TestClient          # noqa: E402

from openflow_backend.api import rest              # noqa: E402

# NayaCore's product ids: the left half in the application, generation A and generation B
# (recovery.PID_FAMILY plus the 0x1000 generation bit).
PID_LEFT_A = 0x0064
PID_LEFT_B = 0x1064
PID_RIGHT_A = 0x00C8
PID_LEFT_MCUBOOT = 0x006F


class Svc:
    def __init__(self, devices, versions):
        self._devices = devices
        self._versions = versions

    def list_devices(self):
        return self._devices

    def snapshot(self):
        return {"halves": [{"port": p, "firmwareVersion": v, "connected": True}
                           for p, v in self._versions.items()], "released": False}


def _plan(svc, query=""):
    app = FastAPI()
    app.include_router(rest.router)
    with mock.patch.object(rest, "get_service", lambda: svc):
        with TestClient(app) as c:
            return c.get(f"/api/firmware-update-plan{query}").json()


@pytest.fixture
def images(tmp_path, monkeypatch):
    """An image tree holding only 3.35.4's generation-A pair, as a half-populated one would be."""
    for rel in ("v1.21.0/kb_fwl.bin", "v1.21.0/kb_fwr.bin"):
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\x00" * 16)
    monkeypatch.setenv("OPENFLOW_FIRMWARE_DIR", str(tmp_path))
    return tmp_path


def test_a_generation_a_half_is_offered_the_generation_a_binary(images):
    svc = Svc([{"port": "COM30", "pid": PID_LEFT_A, "side": "left"}],
              {"COM30": "3.41.0"})
    t = _plan(svc, "?version=3.35.4")["targets"]["left"]
    assert t["file"] == "kb_fwl.bin"                # not kb_fwl_64.bin
    assert t["generation"] == "A"
    assert t["image"] == "v1.21.0/kb_fwl.bin"       # the path the run is given
    assert t["present"] is True
    assert t["reason"] is None


def test_a_generation_b_half_is_not_handed_the_generation_a_binary(images):
    """The generations are not interchangeable; NayaCore refuses this too."""
    svc = Svc([{"port": "COM30", "pid": PID_LEFT_B, "side": "left"}], {"COM30": "3.41.0"})
    t = _plan(svc, "?version=3.35.4")["targets"]["left"]
    # 3.35.4 is catalogued for generation A only, so there is nothing to offer -- and the answer
    # says which combination was looked for rather than silently offering the A image.
    assert t.get("image") is None
    assert "generation B" in t["reason"]

    # 3.41.0 does have a generation-B image, and that is the one that comes back.
    t41 = _plan(svc, "?version=3.41.0")["targets"]["left"]
    assert t41["file"] == "kb_fwl_64.bin"
    assert t41["generation"] == "B"


def test_an_image_we_do_not_hold_is_reported_as_downloadable(images):
    """The catalogue is committed; the images are not shipped. 3.41.0 is listed and absent here.

    "We do not have it" is the ordinary state of a fresh install, not a failure, so the plan says
    it can be fetched and the dialog offers a button rather than an explanation.
    """
    svc = Svc([{"port": "COM30", "pid": PID_LEFT_A, "side": "left"}], {"COM30": "3.35.4"})
    t = _plan(svc, "?version=3.41.0")["targets"]["left"]
    assert t["image"] == "v1.25.1/kb_fwl.bin"
    assert t["present"] is False
    assert t["fetchable"] is True
    assert "has not been downloaded yet" in t["reason"]


def test_there_is_always_somewhere_for_an_image_to_be(monkeypatch):
    """With no OPENFLOW_FIRMWARE_DIR the plan used to report no directory at all, which left
    every version unobtainable with nothing the app could do about it. There is a default now,
    under the app's data directory, and the download writes there."""
    monkeypatch.delenv("OPENFLOW_FIRMWARE_DIR", raising=False)
    svc = Svc([{"port": "COM30", "pid": PID_LEFT_A, "side": "left"}], {"COM30": "3.35.4"})
    plan = _plan(svc, "?version=3.41.0")
    assert plan["imagesDir"], "the plan must name a directory even when nothing is configured"
    assert plan["imagesDir"].replace("\\", "/").endswith("/firmware")
    assert plan["targets"]["left"]["fetchable"] is True


def test_a_downgrade_is_named_as_one_and_an_unchanged_version_too(images):
    """Downgrading is a legitimate repair -- two halves brought back to a common version -- but
    it is never done without saying so."""
    svc = Svc([{"port": "COM30", "pid": PID_LEFT_A, "side": "left"},
               {"port": "COM29", "pid": PID_RIGHT_A, "side": "right"}],
              {"COM30": "3.41.0", "COM29": "3.35.4"})
    targets = _plan(svc, "?version=3.35.4")["targets"]
    assert targets["left"]["downgrade"] is True and targets["left"]["unchanged"] is False
    assert targets["right"]["downgrade"] is False and targets["right"]["unchanged"] is True


def test_a_half_already_in_the_bootloader_is_not_given_a_target(images):
    """It is mid-recovery. Starting a procedure on it would enter a bootloader it is already in."""
    svc = Svc([{"port": "COM30", "pid": PID_LEFT_MCUBOOT, "side": "left"}], {})
    plan = _plan(svc, "?version=3.35.4")
    assert plan["halves"][0]["mode"] == "mcuboot"
    assert plan["targets"] == {}


def test_the_versions_offered_are_flashable_keyboard_images_newest_first(images):
    plan = _plan(Svc([], {}))
    versions = [v["version"] for v in plan["versions"]]
    assert versions == sorted(versions, key=lambda s: tuple(int(x) for x in s.split(".")),
                              reverse=True)
    assert versions[0] == "3.41.0"
    # Every offered version can actually be written to a half of each side.
    for v in plan["versions"]:
        assert v["sides"] == ["left", "right"]


def test_the_gate_is_reported_so_the_page_can_say_wired_but_off(images):
    plan = _plan(Svc([], {}))
    assert plan["flashEnabled"] is rest.FIRMWARE_FLASH_ENABLED
