"""Fetching firmware images, and refusing to keep anything we cannot identify.

OpenFlow ships the catalogue and not the images, so the app has to be able to go and get one.
That means a network download ending up in the directory the flasher writes from, which is only
acceptable because of one rule: the bytes must hash to the digest the catalogue recorded when the
image was dumped from its NayaFlow release. A truncated transfer, a redirect to an HTML error
page, a mirror holding a different build and an outright hostile answer all fail the same check
and none of them reach the disk.

No network here: the fetch is driven through an injected opener.
"""
from __future__ import annotations

import hashlib
import sys
import urllib.error
from pathlib import Path

import pytest

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend.device import firmware_fetch as F      # noqa: E402

IMAGE = b"\x5a" * 4096
SHA = hashlib.sha256(IMAGE).hexdigest()


def entry(**kw):
    e = {"file": "kb_fwl.bin", "historyPath": "v1.21.0/kb_fwl.bin", "side": "left",
         "generation": "A", "createFirmware": "3.35.4", "blobSha256": SHA, "flashable": True,
         "target": "keyboard", "resourceSize": len(IMAGE)}
    e.update(kw)
    return e


class _Answer:
    def __init__(self, body):
        self.body = body

    def read(self, n=None):
        return self.body[:n] if n else self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_for(body=IMAGE, calls=None):
    def opener(req, timeout=None):
        if calls is not None:
            calls.append({"url": req.full_url, "auth": req.get_header("Authorization")})
        if isinstance(body, Exception):
            raise body
        return _Answer(body)
    return opener


def test_a_verified_image_is_written_where_the_flasher_looks(tmp_path):
    calls = []
    row = F.fetch_one(entry(), tmp_path, opener=opener_for(calls=calls))
    assert row["ok"] is True and row["kept"] is True and row["sha256"] == SHA
    out = tmp_path / "v1.21.0" / "kb_fwl.bin"
    assert out.read_bytes() == IMAGE
    assert calls[0]["url"].endswith("/v1.21.0/kb_fwl.bin")
    assert not list(tmp_path.rglob("*.part")), "the temporary file must not survive"


def test_bytes_that_do_not_match_the_catalogue_are_not_kept(tmp_path):
    """The whole safety argument. What arrived is not what we catalogued, so it is not an image
    we can identify, so it does not become a file the flasher could later pick up."""
    row = F.fetch_one(entry(), tmp_path, opener=opener_for(b"an html error page"))
    assert row["ok"] is False
    assert "does not match the catalog" in row["reason"]
    assert "Nothing was written" in row["reason"]
    assert list(tmp_path.rglob("*")) == [], "not even a partial file"


def test_an_image_with_no_digest_is_not_even_requested(tmp_path):
    """Without a digest there is nothing to check a download against, and an unverified firmware
    image is exactly what this module exists to avoid."""
    calls = []
    row = F.fetch_one(entry(blobSha256=None), tmp_path, opener=opener_for(calls=calls))
    assert row["ok"] is False and "no sha256" in row["reason"]
    assert calls == [], "it must not go to the network to fetch something it cannot verify"


def test_a_catalogue_path_that_climbs_out_of_the_directory_is_refused(tmp_path):
    calls = []
    for bad in ("../../etc/passwd", "/etc/passwd", "v1.21.0/../../x.bin", ""):
        row = F.fetch_one(entry(historyPath=bad), tmp_path, opener=opener_for(calls=calls))
        assert row["ok"] is False, bad
    assert calls == []
    assert list(tmp_path.rglob("*")) == []


def test_what_is_already_held_is_not_fetched_again_unless_forced(tmp_path):
    calls = []
    F.fetch_one(entry(), tmp_path, opener=opener_for(calls=calls))
    again = F.fetch_one(entry(), tmp_path, opener=opener_for(calls=calls))
    assert again["ok"] is True and again["kept"] is False and again["reason"] == "already held"
    assert len(calls) == 1

    forced = F.fetch_one(entry(), tmp_path, opener=opener_for(calls=calls), force=True)
    assert forced["kept"] is True and len(calls) == 2


def test_a_version_pulls_every_image_that_version_needs(tmp_path):
    """Both sides and both flash generations. Which of the four a half takes is decided from its
    product id at flash time, and holding three of them is how that decision fails later."""
    catalog = [
        entry(file="kb_fwl.bin", historyPath="v1.21.0/kb_fwl.bin", side="left", generation="A"),
        entry(file="kb_fwl_64.bin", historyPath="v1.21.0/kb_fwl_64.bin", side="left", generation="B"),
        entry(file="kb_fwr.bin", historyPath="v1.21.0/kb_fwr.bin", side="right", generation="A"),
        entry(file="kb_fwr_64.bin", historyPath="v1.21.0/kb_fwr_64.bin", side="right", generation="B"),
        entry(file="kb_fwl.bin", historyPath="v1.25.1/kb_fwl.bin", createFirmware="3.41.0"),
        # Another version entirely, and withheld from flashing besides: neither is asked for
        # here. Whether a withheld image can be DOWNLOADED has its own test below.
        entry(file="kb_fwl.bin", historyPath="v1.17.3/kb_fwl.bin", createFirmware="3.31.1",
              flashable=False),
    ]
    r = F.fetch(catalog, tmp_path, versions=["3.35.4"], opener=opener_for())
    assert r["requested"] == 4 and r["fetched"] == 4 and r["failed"] == 0
    assert sorted(p.name for p in (tmp_path / "v1.21.0").iterdir()) == [
        "kb_fwl.bin", "kb_fwl_64.bin", "kb_fwr.bin", "kb_fwr_64.bin"]
    assert not (tmp_path / "v1.25.1").exists(), "another version was not asked for"
    assert r["bytes"] == 4 * len(IMAGE)


def test_nothing_outside_the_catalogue_can_be_named(tmp_path):
    """The caller chooses WHICH catalogued images, never where they come from."""
    with pytest.raises(F.FetchRefused, match="nothing in the catalog"):
        F.fetch([entry()], tmp_path, paths=["../../../secrets.bin"], opener=opener_for())
    with pytest.raises(F.FetchRefused, match="nothing in the catalog"):
        F.fetch([entry()], tmp_path, versions=["9.9.9"], opener=opener_for())


def test_a_batch_reports_every_image_rather_than_stopping_at_the_first_failure(tmp_path):
    good = entry(historyPath="v1.21.0/kb_fwl.bin")
    bad = entry(historyPath="v1.21.0/kb_fwr.bin", blobSha256="00" * 32)
    r = F.fetch([good, bad], tmp_path, versions=["3.35.4"], opener=opener_for())
    assert r["requested"] == 2 and r["fetched"] == 1 and r["failed"] == 1
    assert (tmp_path / "v1.21.0" / "kb_fwl.bin").is_file()
    assert not (tmp_path / "v1.21.0" / "kb_fwr.bin").exists()


def test_a_private_archive_says_what_to_do_about_it(tmp_path):
    """GitHub answers 404 for a private repository rather than admitting it exists, so the
    message has to name the possibility the user can act on."""
    err = urllib.error.HTTPError("http://x/y", 404, "Not Found", {}, None)
    row = F.fetch_one(entry(), tmp_path, opener=opener_for(err))
    assert row["ok"] is False and "OPENFLOW_FIRMWARE_TOKEN" in row["reason"]

    denied = urllib.error.HTTPError("http://x/y", 403, "Forbidden", {}, None)
    row = F.fetch_one(entry(), tmp_path, opener=opener_for(denied))
    assert "private" in row["reason"] and "OPENFLOW_FIRMWARE_TOKEN" in row["reason"]


def test_a_token_is_sent_only_when_one_is_configured(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENFLOW_FIRMWARE_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    calls = []
    F.fetch_one(entry(), tmp_path, opener=opener_for(calls=calls))
    assert calls[0]["auth"] is None
    assert F.source_info() == {"url": F.SOURCE_DEFAULT, "authenticated": False}

    # The archive is public, so no token is needed or shipped. The capability stays for a source
    # that is not -- a private repository of custom firmware, say -- and is read from the
    # environment, never bundled.
    monkeypatch.setenv("OPENFLOW_FIRMWARE_TOKEN", "a-token")
    F.fetch_one(entry(), tmp_path, opener=opener_for(calls=calls), force=True)
    assert calls[1]["auth"] == "Bearer a-token"
    assert F.source_info() == {"url": F.SOURCE_DEFAULT, "authenticated": True}


def test_the_source_is_configurable(tmp_path, monkeypatch):
    """So the day a public mirror exists, or an open firmware has its own home, nothing here
    changes but an environment variable."""
    monkeypatch.setenv("OPENFLOW_FIRMWARE_SOURCE", "https://example.invalid/fw/")
    calls = []
    F.fetch_one(entry(), tmp_path, opener=opener_for(calls=calls))
    assert calls[0]["url"] == "https://example.invalid/fw/v1.21.0/kb_fwl.bin"


def test_holdings_says_what_this_machine_has(tmp_path):
    catalog = [entry(), entry(historyPath="v1.25.1/kb_fwl.bin", createFirmware="3.41.0")]
    F.fetch_one(catalog[0], tmp_path, opener=opener_for())
    rows = F.holdings(catalog, tmp_path)
    assert [r["present"] for r in rows] == [True, False]
    assert rows[0]["version"] == "3.35.4" and rows[0]["bytes"] == len(IMAGE)


def test_an_image_withheld_from_FLASHING_can_still_be_downloaded(tmp_path):
    """Two different questions, and they were answered with one flag.

    The module bundles and the dongle image are withheld until the write path is proven on a
    donor unit; two pre-production keyboard images are withheld because nobody can say which side
    they are. None of that is a reason to refuse someone a copy of a file. Filtering the library
    on `flashable` left nine of the archive's files unobtainable with no explanation on screen.
    """
    bundle = entry(file="FlashMemory.bin", historyPath="v1.21.0/module/FlashMemory.bin",
                   target="module", flashable=False, moduleFirmware="2.3.3", createFirmware=None)
    rows = F.holdings([bundle], tmp_path)
    assert len(rows) == 1 and rows[0]["flashable"] is False
    r = F.fetch([bundle], tmp_path, versions=["2.3.3"], opener=opener_for())
    assert r["fetched"] == 1
    assert (tmp_path / "v1.21.0" / "module" / "FlashMemory.bin").is_file()


def test_an_image_whose_release_declared_no_version_is_still_offered(tmp_path):
    """Everything before 1.14.5 shipped in releases that declared no firmware version, so the
    catalogue labels those by the release span that carried them. Keying on the version number
    alone silently dropped every one of them from the library."""
    old_image = entry(createFirmware=None, versionLabel="NayaFlow 1.3.8 to 1.6.10",
                      historyPath="v1.6.10/kb_fwl.bin")
    rows = F.holdings([old_image], tmp_path)
    assert rows[0]["version"] is None
    assert rows[0]["label"] == "NayaFlow 1.3.8 to 1.6.10", "it must still have a name"

    r = F.fetch([old_image], tmp_path, versions=["NayaFlow 1.3.8 to 1.6.10"], opener=opener_for())
    assert r["fetched"] == 1
    assert (tmp_path / "v1.6.10" / "kb_fwl.bin").is_file()


def test_an_entry_with_no_file_of_its_own_is_never_offered(tmp_path):
    """The .sfb userapps live inside FlashMemory.bin and are extracted from it. Offering one
    would be a button that could not work."""
    inside = {"file": "touch.sfb", "container": "FlashMemory.bin", "target": "module",
              "blobSha256": SHA, "flashable": False}
    assert F.holdings([inside], tmp_path) == []
