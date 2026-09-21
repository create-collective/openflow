"""Fetching catalogued firmware images onto this machine.

OpenFlow ships the CATALOGUE -- versions, sides, flash generations, hashes -- and not the images.
They are Naya's binaries, they are 648 KiB each, and an installer carrying fifteen megabytes of
someone else's copyrighted material is a decision nobody should make by accident. So a fresh
install knows about every firmware version and holds none of them, and this is how it gets one.

THE HASH IS THE WHOLE SAFETY ARGUMENT. Every catalogue entry carries `blobSha256`, the digest of
the file exactly as Naya shipped it, recorded when the image was dumped from a NayaFlow release.
A download is written nowhere until its bytes hash to that. This is what makes fetching an image
over the network acceptable at all: the source could be wrong, stale, truncated or hostile, and
the only thing that reaches the firmware directory is a byte-for-byte match for something we
already identified. Nothing uncatalogued can be fetched -- the path comes from the catalogue, not
from the caller -- so this is not a general-purpose downloader and must not become one.

WHERE FROM. `OPENFLOW_FIRMWARE_SOURCE`, defaulting to the nayaHistory archive, which is where
every NayaFlow installer this project has unpacked was kept. The layout there is exactly the
catalogue's `historyPath`: <source>/v1.25.1/kb_fwl.bin.

That archive is PRIVATE as of 2026-09-21, so an unauthenticated fetch gets a 404 dressed up as
"not found" rather than "not allowed" -- GitHub hides private repositories rather than admitting
to them. `OPENFLOW_FIRMWARE_TOKEN` (or GITHUB_TOKEN) is sent as a bearer token when set, which is
how the owner fetches from it today. Until the source is public, or a public mirror exists, this
does nothing for anybody else, and the UI says so rather than reporting a mysterious 404. Nothing
here reads or stores a token beyond passing it to the one host it was configured for.

CUSTOM FIRMWARE, LATER. The plan is a community-signed bootloader and an open firmware, and at
that point "fetch from a source" and "flash an image" both need to accept something that is not
in Naya's catalogue. That is deliberately not possible today: `firmware_upload.plan` refuses an
image whose hash it does not know, and the device's bootloader refuses anything not signed with
Naya's key, so an uncatalogued image could not boot even if we wrote it. When the bootloader
changes, the seam is here and in plan(): a second trust root, with its own provenance, alongside
the catalogue -- not a switch that turns the checks off.
"""
from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.request
from pathlib import Path

SOURCE_DEFAULT = "https://raw.githubusercontent.com/traviswye/nayaHistory/main/firmware-history"
TIMEOUT_S = 30.0
# An image is 663552 bytes. The ceiling is a sanity bound on a source that answers with something
# else entirely -- an HTML error page, or a redirect to one -- not a real limit on image size.
MAX_BYTES = 8 * 1024 * 1024


class FetchRefused(RuntimeError):
    """The fetch did not happen, and the reason is something the user can act on."""


def source_url() -> str:
    return (os.environ.get("OPENFLOW_FIRMWARE_SOURCE") or SOURCE_DEFAULT).rstrip("/")


def _token() -> str | None:
    return os.environ.get("OPENFLOW_FIRMWARE_TOKEN") or os.environ.get("GITHUB_TOKEN") or None


def source_info() -> dict:
    """Where images come from, and whether this process has a credential for it.

    There is deliberately no "is it private" guess here. The archive went public on 2026-09-21
    and a hardcoded assumption about one URL would have gone stale that day, warning every user
    about a token nobody needs. Whether a source will answer is a fact about the moment the
    request is made, so it is reported by the failure that actually happens, not predicted.
    """
    return {"url": source_url(), "authenticated": _token() is not None}


def _entry_path(entry: dict) -> str | None:
    """Where an image sits in the archive, straight from the catalogue."""
    rel = entry.get("historyPath") or ""
    # Nothing clever: a catalogue entry with an absolute or climbing path is a corrupt catalogue,
    # and this is the one place a path from a file turns into a write on disk.
    if not rel or rel.startswith(("/", "\\")) or ".." in rel.replace("\\", "/").split("/"):
        return None
    return rel.replace("\\", "/")


def holdings(catalog: list, dest: Path) -> list[dict]:
    """Every catalogued image that IS a file, and whether this machine has it.

    Downloadable is not the same question as flashable, and conflating them was wrong twice over.
    The module bundles and the dongle image are withheld from FLASHING until the path is proven on
    a donor unit -- that is a statement about writing to a keyboard, not about keeping a copy of a
    file -- and two pre-production keyboard images are withheld because nobody can say which side
    or generation they are. All of them are part of the archive this library exists to mirror, and
    refusing to download them left "a ton of firmware history" on screen with nine of its files
    unobtainable and no reason given. `flashable` is carried per row instead, so the page can say
    which is which.

    `label` is how a version is NAMED, and it is not always a version number: images from before
    1.14.5 shipped in releases that declared none, and the catalogue labels those by the release
    span that carried them ("NayaFlow 1.3.8 to 1.6.10"). Keying on the version number alone
    dropped every one of them -- the second half of the same bug.

    Entries with no file of their own are not here at all: the .sfb userapps live INSIDE
    FlashMemory.bin and are extracted from it, so there is nothing to download for them
    separately, and offering one would be a button that could not work.
    """
    out = []
    for im in catalog:
        rel = _entry_path(im)
        if not rel:
            continue
        p = dest / rel
        version = im.get("createFirmware") or im.get("moduleFirmware")
        out.append({
            "path": rel,
            "file": im.get("file"),
            "target": im.get("target"),
            "side": im.get("side"),
            "generation": im.get("generation"),
            "version": version,
            "label": im.get("versionLabel") or version or im.get("bundle"),
            "bundle": im.get("bundle"),
            "flashable": bool(im.get("flashable")),
            "bytes": im.get("resourceSize") or im.get("imageSize") or im.get("blobSize"),
            "present": p.is_file(),
        })
    return out


def _fetch_bytes(url: str, opener=None) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "OpenFlow"})
    token = _token()
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    get = opener or urllib.request.urlopen
    try:
        with get(req, timeout=TIMEOUT_S) as r:                  # noqa: S310 -- fixed https source
            return r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise FetchRefused(
                f"the firmware archive refused the request ({e.code}). It is private; set "
                "OPENFLOW_FIRMWARE_TOKEN to a token that can read it.") from e
        if e.code == 404:
            raise FetchRefused(
                "the archive has no such image, or it is private and this request was not "
                "authenticated -- GitHub answers 404 for both. If the archive is private, set "
                "OPENFLOW_FIRMWARE_TOKEN.") from e
        raise FetchRefused(f"the firmware archive answered {e.code}.") from e
    except (urllib.error.URLError, OSError) as e:
        raise FetchRefused(f"could not reach the firmware archive: {e}") from e


def fetch_one(entry: dict, dest: Path, *, opener=None, force: bool = False) -> dict:
    """Fetch ONE catalogued image and verify it before it is kept.

    Returns a row saying what happened: kept, already held, or refused with a reason. It never
    raises for one image's failure -- a batch of twenty should report twenty outcomes rather than
    stopping at the first one and leaving the user to guess what landed.
    """
    rel = _entry_path(entry)
    row = {"path": rel, "file": entry.get("file"),
           "version": entry.get("createFirmware") or entry.get("moduleFirmware")}
    if not rel:
        return {**row, "ok": False, "reason": "this catalogue entry has no usable path"}
    want = (entry.get("blobSha256") or "").lower()
    if len(want) != 64:
        # Without a digest there is nothing to check a download against, and an unverified
        # firmware image is exactly what this module exists to avoid.
        return {**row, "ok": False,
                "reason": "the catalogue has no sha256 for this image, so a download could not "
                          "be verified and is not attempted"}

    out = dest / rel
    if out.is_file() and not force:
        return {**row, "ok": True, "kept": False, "reason": "already held"}

    try:
        raw = _fetch_bytes(f"{source_url()}/{rel}", opener=opener)
    except FetchRefused as e:
        return {**row, "ok": False, "reason": str(e)}
    if len(raw) > MAX_BYTES:
        return {**row, "ok": False, "reason": "the source answered with more than 8 MB; that is "
                                              "not one of these images"}

    got = hashlib.sha256(raw).hexdigest()
    if got != want:
        # The one outcome that must never be written to disk. Truncation, a redirect to an HTML
        # page, a mirror holding a different build: all arrive here, and all are refused the same
        # way, because from the flasher's point of view they are the same thing -- bytes we
        # cannot identify.
        return {**row, "ok": False, "bytes": len(raw),
                "reason": f"what arrived does not match the catalogue (expected {want[:12]}…, "
                          f"got {got[:12]}…). Nothing was written."}

    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    tmp.write_bytes(raw)
    tmp.replace(out)            # atomic: a half-written image must never look like a held one
    return {**row, "ok": True, "kept": True, "bytes": len(raw), "sha256": got}


def fetch(catalog: list, dest: Path, *, versions: list | None = None, paths: list | None = None,
          opener=None, force: bool = False) -> dict:
    """Fetch a set of catalogued images: whole versions, or named catalogue paths.

    `versions` names firmware versions ("3.35.4") or the labels the catalogue uses for images
    whose release declared no number ("NayaFlow 1.3.8 to 1.6.10"), and takes every image under
    each -- both sides, both flash generations, because which one a half needs is decided from
    its product id at flash time and holding three of the four is how that decision fails later.
    `paths` names catalogue paths outright, which is what a page that already listed them sends.
    """
    wanted = []
    for im in catalog:
        rel = _entry_path(im)
        if not rel:
            continue
        if paths is not None and rel in paths:
            wanted.append(im)
        elif versions is not None and (
                (im.get("createFirmware") or im.get("moduleFirmware")) in versions
                or im.get("versionLabel") in versions):
            wanted.append(im)
    if not wanted:
        raise FetchRefused("nothing in the catalogue matches that request")

    rows = [fetch_one(im, dest, opener=opener, force=force) for im in wanted]
    kept = [r for r in rows if r.get("kept")]
    failed = [r for r in rows if not r.get("ok")]
    return {"dir": str(dest), "source": source_url(), "requested": len(rows),
            "fetched": len(kept), "failed": len(failed), "images": rows,
            "bytes": sum(r.get("bytes") or 0 for r in kept)}
