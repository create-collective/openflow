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
    kb = [e for e in images if e["target"] == "keyboard" and e["channel"] == "official"]
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
    official = [e for e in images if e["target"] == "keyboard" and e["channel"] == "official"]
    declared = {e["createFirmware"] for e in official if e["createFirmware"]}
    assert declared == {"3.28.7", "3.29.1", "3.31.1", "3.35.4", "3.41.0"}
    assert not any(v.startswith("0.") for v in declared)
    for e in official:
        if e["target"] == "keyboard":
            if e["createFirmware"]:
                assert e["versionConfidence"] == "declared" and e["versionLabel"] == e["createFirmware"]
            else:
                assert e["versionConfidence"] == "unknown" and e["versionLabel"].startswith("NayaFlow ")


def test_beta_channel_keyboard_images_are_recognised_but_never_offered(images):
    """A half on a beta must be identifiable, or every write refuses it as "not one we hold" and
    a board left on 3.40.4 could never be moved to 3.41.0. Recognised is not offered: none is
    flashable, none is downloadable, and none duplicates an official image."""
    beta = [e for e in images if e["channel"] == "beta"]
    assert {(e["createFirmware"], e["side"]) for e in beta} == {
        (v, s) for v in ("3.39.4", "3.40.0", "3.40.4") for s in ("left", "right")}
    official = {e.get("plaintextSha256") for e in images if e["channel"] == "official"}
    for e in beta:
        assert e["target"] == "keyboard" and HEX64.match(e["plaintextSha256"]), e["versionLabel"]
        assert e["plaintextSha256"] not in official
        assert not e["flashable"] and any("beta" in w for w in e["withheldBecause"])
        assert "historyPath" not in e and e["betaPath"].startswith("firmware-history-beta/")
        assert e["generation"] == "A" and all(t.startswith("beta v") for t in e["bundles"])
    # the 1.22.0 note says 3.39.3; the binaries say 3.39.4, and the conflict is kept, not hidden
    assert all(e["versionConflict"] for e in beta if e["createFirmware"] == "3.39.4")


def test_the_dvt_era_images_are_catalogued_but_withheld(images):
    dvt = [e for e in images if e.get("era") == "dvt"]
    assert {e["file"] for e in dvt} == {"fwl.bin", "fwr.bin"}
    assert all(not e["flashable"] and e["withheldBecause"] for e in dvt)


def test_a_module_bundle_is_offerable_only_with_a_version_and_a_versioned_pairing(images):
    """Watched end to end on NayaFlow 2026-09-23, so the path is no longer withheld as a whole.
    What still withholds a bundle is what a device cannot check: no version of its own, or a
    pairing with keyboard firmware that declares none."""
    bundles = [e for e in images if e["file"] == "FlashMemory.bin"]
    offered = {e["moduleFirmware"]: e["keyboardRange"] for e in bundles if e["flashable"]}
    # A RANGE per bundle, from the first keyboard version it shipped with (official or beta) up to
    # the next bundle's first. The beta channel moved one boundary: 2.3.3 first shipped with the
    # beta 3.40.0, and 2.3.2 was still shipping with the beta 3.39.4.
    assert offered == {"2.3.3": {"from": "3.40.0", "below": None},
                       "2.3.2": {"from": "3.31.1", "below": "3.40.0"},
                       "2.2.0": {"from": "3.29.1", "below": "3.31.1"},
                       "2.1.2": {"from": "3.28.7", "below": "3.29.1"}}
    seen = {e["moduleFirmware"]: e["pairedKeyboard"] for e in bundles if e["flashable"]}
    assert seen["2.3.2"] == ["3.31.1", "3.35.4", "3.39.4"]
    assert seen["2.3.3"] == ["3.40.0", "3.40.4", "3.41.0"]
    withheld = {e["versionLabel"]: e["withheldBecause"] for e in bundles if not e["flashable"]}
    assert set(withheld) == {"2.1.1", "NayaFlow 1.11.0 to 1.11.11"}
    assert all(withheld.values())
    # an app inside a bundle is offerable exactly when its bundle is and it is a shipping module
    for app in (e for e in images if e.get("type") == "sfb"):
        bundle = next(b for b in bundles if b["blobSha256"] == app["containerBlobSha256"])
        shipping = app["component"] in ("touch", "track", "tune")
        assert app["flashable"] == (bundle["flashable"] and shipping), app["file"]
    assert not any(e["flashable"] for e in images if e.get("component") == "dial")


def test_module_bundles_are_catalogued_whole(images):
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


def test_every_mcuboot_resource_is_a_whole_slot_with_a_permanent_swap_trailer(images):
    """image_ok = 0x01 and BOOT_MAGIC at the end of every resource: uploaded whole, it schedules a
    permanent swap by itself. The flasher must know, and does (firmware_upload.image_trailer)."""
    res = [e for e in images if e.get("type") == "mcuboot"]
    assert len([e for e in res if e["channel"] == "official"]) == 27   # 26 keyboard images + the dial
    assert len([e for e in res if e["channel"] == "beta"]) == 6        # 3.39.4, 3.40.0, 3.40.4 x 2
    for e in res:
        assert e["trailer"] == {"magic": "good", "imageOk": True, "swapOnUpload": "permanent"}, e["file"]
        assert e["mcubootImageLen"] < e["resourceSize"], e["file"]


def test_one_signing_key_across_every_release(cat, images):
    assert len(cat["signingKeys"]) == 1
    keyed = [e for e in images if e.get("type") == "mcuboot"]
    assert keyed and all(e["signingKeyHash"] == cat["signingKeys"][0] for e in keyed)


def test_the_linux_builds_that_shipped_older_images_are_recorded(images):
    e = next(e for e in images if e["createFirmware"] == "3.28.7" and e["side"] == "left")
    assert e["bundles"] == ["v1.14.5"]
    assert e["linuxBundles"] == ["v1.15.0", "v1.15.1", "v1.17.2", "v1.17.3"]
