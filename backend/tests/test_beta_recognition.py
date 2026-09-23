"""A half running a NayaFlow BETA image is recognised, and what follows from that.

Against the committed catalogue, through the same code the flasher uses: recovery.identify is what
turns the hash MCUboot reports into "this is the 3.40.4 left image", and an unrecognised hash is
"not one we hold", after which every write refuses. Before the beta channel was catalogued, a
board a tester left on 3.40.4 could be neither updated nor have its modules matched.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import firmware_upload as fw         # noqa: E402
from openflow_backend.device import module_procedure as mp        # noqa: E402
from openflow_backend.device import recovery as rec               # noqa: E402


@pytest.fixture(scope="module")
def catalog() -> list[dict]:
    for parent in Path(__file__).resolve().parents:
        cand = parent / "docs" / "reference" / "firmware-catalog.json"
        if cand.is_file():
            return json.loads(cand.read_text(encoding="utf-8"))["images"]
    pytest.skip("docs/reference/firmware-catalog.json not in this checkout")


def _beta(catalog, version, side):
    return next(e for e in catalog if e.get("channel") == "beta"
                and e.get("createFirmware") == version and e.get("side") == side)


@pytest.mark.parametrize("version", ["3.39.4", "3.40.0", "3.40.4"])
def test_a_beta_image_is_identified_by_its_hash(catalog, version):
    e = _beta(catalog, version, "left")
    got = rec.identify(e["plaintextSha256"], catalog)
    assert got["identified"] and got["channel"] == "beta"
    assert (got["side"], got["generation"], got["createFirmware"]) == ("left", "A", version)
    assert got["flashable"] is False             # recognised, never a target


def test_moving_a_beta_half_up_to_the_official_release_is_not_a_downgrade(catalog):
    running = rec.identify(_beta(catalog, "3.40.4", "left")["plaintextSha256"], catalog)
    official = next(e for e in catalog if e.get("channel") == "official"
                    and e.get("createFirmware") == "3.41.0" and e.get("side") == "left"
                    and e.get("generation") == "A")
    assert official["flashable"]
    assert fw._is_downgrade(running, official) is None
    older = next(e for e in catalog if e.get("createFirmware") == "3.35.4" and e.get("side") == "left")
    assert "older than" in fw._is_downgrade(running, older)


@pytest.mark.parametrize("version,module", [("3.39.4", "2.3.2"), ("3.40.0", "2.3.3"),
                                            ("3.40.4", "2.3.3")])
def test_a_beta_keyboard_is_matched_to_its_module_firmware(catalog, version, module):
    assert mp.choose_bundle(catalog, version, None)["moduleFirmware"] == module


def test_a_beta_image_is_never_offered_as_a_target(catalog, tmp_path):
    """Even holding the file, plan() refuses it for the beta reason. The stand-in file's hash is
    put on the beta entry so the refusal is about the channel, not an unknown file."""
    import hashlib
    f = tmp_path / "kb_fwl.bin"
    f.write_bytes(b"\x00" * 16)
    e = dict(_beta(catalog, "3.40.4", "left"), blobSha256=hashlib.sha256(f.read_bytes()).hexdigest())
    cat = [e if x is _beta(catalog, "3.40.4", "left") else x for x in catalog]
    with pytest.raises(fw.UploadRefused, match="withheld: beta-channel image"):
        fw.plan(f, cat, state={"state": "ok", "port": "COM4", "images": [
            {"slot": 0, "hash": e["plaintextSha256"], **rec.identify(e["plaintextSha256"], cat)}]})
