"""The committed firmware catalogue keeps the promises the flasher relies on.

docs/reference/firmware-catalog.json is built by tools/build_firmware_catalog.py from the
nayaHistory manifests, and firmware_upload.plan() trusts what it says about side, flash generation
and hashes. These tests pin the invariants a regenerated catalogue must keep: nothing here reads
hardware or the (private) image files, only the committed metadata.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

HEX64 = re.compile(r"^[0-9a-f]{64}$")


def _catalog() -> dict:
    for parent in Path(__file__).resolve().parents:
        cand = parent / "docs" / "reference" / "firmware-catalog.json"
        if cand.is_file():
            return json.loads(cand.read_text(encoding="utf-8"))
    pytest.skip("docs/reference/firmware-catalog.json not in this checkout")


@pytest.fixture(scope="module")
def cat() -> dict:
    return _catalog()


@pytest.fixture(scope="module")
def images(cat) -> list[dict]:
    return cat["images"]


def test_it_covers_every_nayaflow_release(cat):
    tags = [r["tag"] for r in cat["releases"]]
    assert len(tags) == 25 and tags[0] == "v0.0.1" and tags[-1] == "v1.25.1"
    assert [r["order"] for r in cat["releases"]] == list(range(25)), "chronological, 0-based"


def test_every_distinct_keyboard_image_appears_once(images):
    kb = [e for e in images if e["target"] == "keyboard"]
    hashes = [e["plaintextSha256"] for e in kb]
    assert len(kb) == 26 and len(set(hashes)) == 26, "12 releases changed firmware; 1.25.x has 4 images"
    assert all(HEX64.match(h) for h in hashes)
    assert all(HEX64.match(e["blobSha256"]) for e in kb)


def test_a_flashable_keyboard_image_says_side_generation_and_hash(images):
    for e in images:
        if e["target"] != "keyboard" or not e["flashable"]:
            continue
        assert e["side"] in ("left", "right") and e["component"] == e["side"], e["file"]
        assert e["generation"] in ("A", "B"), e["file"]
        assert e["sideConfidence"] == "confirmed", e["file"]
        assert HEX64.match(e["plaintextSha256"]) and HEX64.match(e["blobSha256"]), e["file"]
        assert e["withheldBecause"] == [], e["file"]
        assert isinstance(e["releaseOrder"], int) and e["bundles"], e["file"]


def test_the_generation_split_is_1_25_only(images):
    gen_b = [e for e in images if e.get("generation") == "B"]
    assert {e["firstSeen"] for e in gen_b} == {"v1.25.0"} and len(gen_b) == 2
    assert all(e["file"].endswith("_64.bin") for e in gen_b)
    for e in images:
        if e["target"] == "keyboard":
            assert e["generationConfidence"] == ("declared" if e["era"] == "gen-split" else "pre-split")


def test_the_running_image_of_the_owners_board_is_present_and_flashable(images):
    """The left half reported this hash on 2026-09-08 (test_firmware_upload_guards.RUNNING_HASH)."""
    e = next(e for e in images
             if e.get("plaintextSha256") == "479e89ba6c92ead9c46d1228d5033437caf63d72db89364081b9b0a321b31283")
    assert (e["file"], e["side"], e["generation"], e["createFirmware"]) == ("kb_fwl.bin", "left", "A", "3.41.0")
    assert e["bundles"] == ["v1.25.0", "v1.25.1"] and e["bundle"] == "NayaFlow 1.25.1"
    assert e["flashable"] and e["versionConfidence"] == "declared"


def test_versions_come_from_the_changelogs_and_the_drift_is_normalised(images):
    """1.14.5's notes say `0.3.28.7`, 1.15.0's say `3.29.1`: the same numbering. Nothing keeps
    the four-part form."""
    declared = {e["createFirmware"] for e in images if e["target"] == "keyboard" and e["createFirmware"]}
    assert declared == {"3.28.7", "3.29.1", "3.31.1", "3.35.4", "3.41.0"}
    assert not any(v.startswith("0.") for v in declared)
    for e in images:
        if e["target"] == "keyboard":
            if e["createFirmware"]:
                assert e["versionConfidence"] == "declared" and e["versionLabel"] == e["createFirmware"]
            else:
                assert e["versionConfidence"] == "unknown" and e["versionLabel"].startswith("NayaFlow ")


def test_the_dvt_era_images_are_catalogued_but_withheld(images):
    dvt = [e for e in images if e.get("era") == "dvt"]
    assert {e["file"] for e in dvt} == {"fwl.bin", "fwr.bin"}
    assert all(not e["flashable"] and e["withheldBecause"] for e in dvt)


def test_no_module_image_is_offerable_until_the_module_path_is_tested(images):
    mods = [e for e in images if e["target"] == "module"]
    assert mods and all(not e["flashable"] for e in mods)
    assert all(any("module flash path" in w for w in e["withheldBecause"]) for e in mods)
    bundles = [e for e in images if e["file"] == "FlashMemory.bin"]
    assert len(bundles) == 6 and len({e["blobSha256"] for e in bundles}) == 6
    # every bundle since 1.14.3 names its own version in a VERSION file; 1.11.x has none
    assert {e["moduleFirmware"] for e in bundles if e["moduleFirmware"]} == {"2.1.1", "2.1.2", "2.2.0", "2.3.2", "2.3.3"}
    apps = {f"{n}_UserApp.sfb" for n in ("Touch", "Track", "Tune", "Float", "Query")}
    for b in bundles:
        assert b["type"] == "littlefs" and set(b["contents"]) == apps, b["bundle"]
        if b["moduleFirmware"]:
            assert b["versionSource"] == "VERSION file inside FlashMemory.bin"
        else:
            assert b["versionLabel"].startswith("NayaFlow 1.11.0")


def test_every_bundle_lists_its_userapps_by_the_hash_the_create_reports(images):
    apps = [e for e in images if e.get("type") == "sfb"]
    assert len(apps) == 30                              # 6 bundles x 5 apps
    per_bundle: dict[str, set] = {}
    for a in apps:
        assert HEX64.match(a["sha256"]) and a["container"] == "FlashMemory.bin", a
        bundle = next(b for b in images if b.get("blobSha256") == a["containerBlobSha256"])
        assert bundle["contents"][a["file"]]["sha256"] == a["sha256"]
        assert a["moduleFirmware"] == bundle["moduleFirmware"] and a["bundles"] == bundle["bundles"]
        assert a["hashSidecar"] == (bundle["firstSeen"] not in ("v1.11.0", "v1.14.3", "v1.14.5")), a
        per_bundle.setdefault(a["containerBlobSha256"], set()).add(a["component"])
    assert all(v == {"touch", "track", "tune", "float", "query"} for v in per_bundle.values())
    assert {a["component"] for a in apps if "not a shipping module" in a["withheldBecause"]} == {"float", "query"}
    assert len({a["sha256"] for a in apps}) == 30, "every app changed in every bundle"


def test_the_uncertain_1_17_3_carves_are_gone(images):
    """Their hashes turned out to be the 1.17.2/1.17.3 mac images and the 1.14.5 images, which the
    manifests describe properly (side confirmed, generation known)."""
    assert not any("NayaCore" in e["file"] for e in images)
    assert all(e["sideConfidence"] == "confirmed" for e in images if e["target"] == "keyboard")


def test_one_signing_key_across_every_release(cat, images):
    assert len(cat["signingKeys"]) == 1
    keyed = [e for e in images if e.get("type") == "mcuboot"]
    assert keyed and all(e["signingKeyHash"] == cat["signingKeys"][0] for e in keyed)


def test_the_linux_builds_that_shipped_older_images_are_recorded(images):
    e = next(e for e in images if e["createFirmware"] == "3.28.7" and e["side"] == "left")
    assert e["bundles"] == ["v1.14.5"]
    assert e["linuxBundles"] == ["v1.15.0", "v1.15.1", "v1.17.2", "v1.17.3"]
