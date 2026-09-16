"""Writing a firmware image to a half in MCUboot recovery.

NEVER RUN ON HARDWARE. The only route here is /rpc/flash-firmware, which refuses at a
module-level gate (FIRMWARE_FLASH_ENABLED, ships False) before this file is even imported; and
`flash()` refuses to run unless the caller passes an explicit arming token that has to be
computed from the device's own reported state. It exists so the procedure is written down,
reviewed and interlocked BEFORE the day it is needed, rather than improvised against a keyboard
that is already broken.

THE SEQUENCE is NayaCore's, and it is stock MCUboot/SMP in every release the company shipped
(nayaHistory/FLASHING-PROCEDURE.md): upload the image to the secondary slot, mark it pending,
reset so the bootloader swaps. `upload()` is the first step only; `flash()` is all three, with
a slot re-read between upload and mark so a wrong image is never marked bootable.

It has never been run against hardware. The read path in recovery.py has (2026-09-08, both slot
hashes matched the catalogue), so the framing, transport and CBOR decoding underneath are
proven; the upload request shape is not. Treat every claim about it as design, not observation.

WHY IT IS SAFE-ISH BY CONSTRUCTION, and where that stops being true.

MCUboot writes an uploaded image into the SECONDARY slot and only swaps on the next boot after
the image is marked for it. An interrupted upload therefore leaves the primary image untouched,
and the realistic failure is "nothing changed", not "bricked". That is MCUboot's documented
design plus what this device's own bootloader log shows (`Primary image: magic=good ...`,
`Scratch: magic=unset`) -- it is NOT something we have watched fail and recover here. The first
real upload belongs on a donor unit.

THE INTERLOCKS, and why each exists.

  * The device must be in recovery and must ANSWER `image state`. A half that will not say what
    it is running does not get written to.
  * The running image must be in the catalogue. This is the whole point of hashing: it is how a
    half identifies itself when we have no PID table, and an unrecognised image means we cannot
    say which side or flash generation it is.
  * Side and generation must match. NayaCore refuses to flash across generations and so do we;
    the four images are not interchangeable and left/right are different binaries.
  * The chosen image must be catalogued `flashable`. The older 1.17.3 set is deliberately not,
    because its side is inferred from file size and its generation is unknown.
  * The caller must pass `arm=` equal to the hash the DEVICE just reported. An arming flag that
    is just `True` can be left on; one that has to be the device's current state cannot be
    reused on the next device by accident.

A DOWNGRADE IS A DELIBERATE, SUPPORTED CASE. The recovery route people describe -- go back a
version so the two halves speak to each other again, then upgrade both -- needs older images to
be offerable. All eight images we hold share ONE signing key, so an older image is signed by the
key the bootloader already trusts. `allow_older=True` exists for exactly that and still requires
every other interlock to pass.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field
from pathlib import Path

from . import recovery as rec

SMP_OP_WRITE = 2
SMP_ID_IMAGE_UPLOAD = 1
# Standard mcumgr ids (Zephyr and mynewt agree, and NayaCore speaks stock SMP in every release --
# nayaHistory/FLASHING-PROCEDURE.md). `image state` WRITE marks an uploaded image pending;
# `os reset` makes MCUboot swap to it on the boot that follows.
SMP_ID_IMAGE_STATE = rec.SMP_ID_IMAGE_STATE      # 0: read lists slots, write sets pending
SMP_ID_OS_RESET = 5
# Conservative. The transport fragments anything larger across continuation frames, and a
# smaller chunk costs throughput on an operation that runs once, while a too-large one is
# rejected by a bootloader whose buffer we are guessing at.
DEFAULT_CHUNK = 128
# Hard cap on what one frame may carry. The SMP header's length field is 16 bits and the
# bootloader's receive buffer (MCUBOOT_SERIAL_MAX_RECEIVE_SIZE, 512 by default) is the real limit
# below that; a chunk the bootloader will not take is refused with an rc and the upload stops
# before anything is marked. This cap only turns an impossible frame into a clear error.
MAX_CHUNK = 4096

# HOW THE BOOTLOADER NUMBERS UPLOAD TARGETS (MCUboot boot/boot_serial/src/boot_serial.c and
# boot/zephyr/flash_map_extended.c, read 2026-09-15). The `image` field of an `image upload` is
# NOT the application-side mcumgr image index, where "image 0" always means "the secondary slot
# of image 0". In serial recovery it is one of two things, decided at the bootloader's build:
#   * default: the image NUMBER, and the PRIMARY slot of that image is written
#     (flash_area_id_from_multi_image_slot(img_num, 0));
#   * with MCUBOOT_SERIAL_DIRECT_IMAGE_UPLOAD: a direct slot id -- 0 and 1 -> slot0_partition
#     (primary), 2 -> slot1_partition (secondary), 3 -> slot2_partition, 4 -> slot3_partition.
# Neither reading makes `image: 1` the secondary slot, which is what this file assumed before
# 2026-09-15. The Create's images are encrypted, an encrypted image cannot execute from the
# primary slot, and the owner's board holds its PREVIOUS firmware (3.35.4) in the secondary slot
# under the running 3.41.0 -- the footprint of upload-to-secondary + swap. So the direct scheme
# is the working assumption: secondary slot = `image: 2`. It stays an assumption until the
# device says otherwise, and it can: MCUboot's `image slot info` read (id 6) reports each slot's
# `upload_image_id` when the direct scheme is on, and whenever the device answers that read, ITS
# number is used and the assumption is not. The module bundle goes further: its slot is taken
# from that read only (the one slot that is exactly the bundle's size), never assumed.
# bs_upload does no header check and refuses an image larger than the slot BEFORE erasing it;
# every other first-chunk failure returns EINVAL (3), indistinguishable from "no such slot".
#
# SETTLED ON THE OWNER'S BOARD, 2026-09-16, from two independent sources that agree:
#   * the bootloader's `image slot info` answer: image 0 slot 0 = 663552 bytes, upload id 1;
#     slot 1 = 663552 bytes, upload id 2 -- the direct scheme, confirmed by the device;
#   * NayaCore 6.11.0 itself (mac x86_64 and arm64 builds disassembled, tools/../scratch):
#     uploadImageToCreateSlot(path) is uploadImageToSlot(path, 2) and
#     uploadImageToModulesSlot(path) is uploadImageToSlot(path, 4).
# So the keyboard image goes to 2 (= the secondary slot, which is what the map says) and the
# module bundle to 4 (= slot3_partition, the 1 MiB modules partition). The map cannot list the
# modules slot -- it is not an MCUboot image slot -- so for it the vendor's constant is used,
# and only once the device's own map has shown it numbers slot 1 as 2, i.e. that it and NayaCore
# count the same way.
DIRECT_UPLOAD_ID_OFFSET = 1
CREATE_UPLOAD_IMAGE_ID = 2         # NayaCore: uploadImageToCreateSlot -> uploadImageToSlot(_, 2)
MODULES_UPLOAD_IMAGE_ID = 4        # NayaCore: uploadImageToModulesSlot -> uploadImageToSlot(_, 4)
MODULE_BUNDLE_SIZE = 1048576       # every FlashMemory.bin since 1.11.0; the partition's size
SMP_ID_IMAGE_SLOT_INFO = rec.SMP_ID_IMAGE_SLOT_INFO


class UploadRefused(RuntimeError):
    """An interlock said no. The message is the reason, verbatim, for showing to a user."""


# --- CBOR encoding, only the shapes an upload request uses ---------------------------------- #

def _cbor_uint(major: int, n: int) -> bytes:
    if n < 24:
        return bytes([(major << 5) | n])
    if n < 0x100:
        return bytes([(major << 5) | 24, n])
    if n < 0x10000:
        return bytes([(major << 5) | 25]) + struct.pack(">H", n)
    if n < 0x100000000:
        return bytes([(major << 5) | 26]) + struct.pack(">I", n)
    return bytes([(major << 5) | 27]) + struct.pack(">Q", n)


def _cbor_encode(value) -> bytes:
    if isinstance(value, bool):
        return b"\xf5" if value else b"\xf4"
    if isinstance(value, int):
        if value < 0:
            return _cbor_uint(1, -1 - value)
        return _cbor_uint(0, value)
    if isinstance(value, (bytes, bytearray)):
        return _cbor_uint(2, len(value)) + bytes(value)
    if isinstance(value, str):
        raw = value.encode("utf-8")
        return _cbor_uint(3, len(raw)) + raw
    if isinstance(value, dict):
        # Sorted so a request is byte-stable and diffable between runs.
        out = _cbor_uint(5, len(value))
        for k in sorted(value):
            out += _cbor_encode(k) + _cbor_encode(value[k])
        return out
    raise TypeError(f"cannot CBOR-encode {type(value).__name__}")


# --- the plan -------------------------------------------------------------------------------- #

@dataclass
class UploadPlan:
    """What an upload WOULD do. Produced without writing anything."""
    image_path: Path
    slot: int
    total_bytes: int
    chunks: int
    image_sha256: str
    running: dict = field(default_factory=dict)
    target: dict = field(default_factory=dict)
    port: str = ""
    arm_token: str = ""
    upload_image_id: int = 0          # the `image` value on the wire -- see the note at the top
    upload_id_source: str = ""        # "device slot info" or the assumption, spelled out

    def describe(self) -> str:
        t, r = self.target, self.running
        return (f"{self.image_path.name} -> slot {self.slot} on {self.port} "
                f"(upload image id {self.upload_image_id}: {self.upload_id_source})\n"
                f"  running : {r.get('file')} ({r.get('side')}/gen {r.get('generation')}, "
                f"fw {r.get('versionLabel') or r.get('createFirmware')})\n"
                f"  writing : {t.get('file')} ({t.get('side')}/gen {t.get('generation')}, "
                f"fw {t.get('versionLabel') or t.get('createFirmware')}, {t.get('bundle')})\n"
                f"  {self.total_bytes} bytes in {self.chunks} chunks\n"
                f"  arm token: {self.arm_token}")


def _version_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except (TypeError, ValueError):
        return ()


ASSUMED_DIRECT = ("assumed: MCUboot direct-upload scheme (slot + 1), not confirmed by the device's "
                  "slot map")


def upload_image_id(slot: int, slot_info: dict | None = None, *, image: int = 0) -> tuple[int, str]:
    """The `image` value that addresses MCUboot slot `slot` of image `image`, and where the number
    came from. The device's own slot map (recovery.slot_info) wins; the direct-upload scheme is
    the fallback and is labelled as an assumption so a plan never hides that it is one."""
    for s in (slot_info or {}).get("slots") or []:
        if (s.get("image") or 0) == image and s.get("slot") == slot and s.get("uploadImageId") is not None:
            return int(s["uploadImageId"]), "device slot info"
    return 2 * image + slot + DIRECT_UPLOAD_ID_OFFSET, ASSUMED_DIRECT


def _slot_size(slot_info: dict | None, image: int, slot: int) -> int | None:
    for s in (slot_info or {}).get("slots") or []:
        if (s.get("image") or 0) == image and s.get("slot") == slot:
            return s.get("size")
    return None


def _numbering_is_understood(slot_info: dict | None) -> None:
    """Refuse unless the device's own map says it numbers upload targets the way NayaCore's
    constants assume: image 0's secondary slot has upload id CREATE_UPLOAD_IMAGE_ID (2). Without
    that answer the vendor constants are numbers under an unverified scheme."""
    if not slot_info or not slot_info.get("supported"):
        raise UploadRefused(
            "the bootloader did not report its slot map (`image slot info`), so it is not known "
            "whether it numbers upload targets the way NayaCore's constants assume. Nothing is "
            "written into a partition addressed by a number that has not been checked.")
    got = _slot_upload_id(slot_info, 0, 1)
    if got != CREATE_UPLOAD_IMAGE_ID:
        raise UploadRefused(
            f"the bootloader's map gives image 0 slot 1 the upload id {got}, but NayaCore writes "
            f"the Create image with {CREATE_UPLOAD_IMAGE_ID}. The numbering is not understood, so "
            "no constant taken from NayaCore can be trusted on this bootloader. Refusing.")


def _slot_upload_id(slot_info: dict | None, image: int, slot: int):
    for s in (slot_info or {}).get("slots") or []:
        if (s.get("image") or 0) == image and s.get("slot") == slot:
            return s.get("uploadImageId")
    return None


def modules_slot(slot_info: dict | None, bundle_size: int) -> tuple[int, dict]:
    """Which upload id addresses the modules partition, and the slot-map row it rests on.

    The partition is a filesystem, not an MCUboot image slot, so the bootloader's map never
    lists it (confirmed on the owner's board: the map has image 0's two slots and nothing else).
    The number therefore comes from NayaCore -- uploadImageToModulesSlot is uploadImageToSlot(_, 4)
    -- and it is used only after the map has shown that this bootloader and NayaCore count the
    same way (_numbering_is_understood). Should a map ever list a slot of exactly the bundle's
    size with an upload id, the device's own row wins over the constant."""
    _numbering_is_understood(slot_info)
    listed = [s for s in slot_info.get("slots") or []
              if s.get("size") == bundle_size and not ((s.get("image") or 0) == 0 and s.get("slot") in (0, 1))
              and s.get("uploadImageId") is not None]
    if len(listed) > 1:
        raise UploadRefused(
            f"{len(listed)} slots in the bootloader's map are exactly {bundle_size} bytes outside "
            f"the keyboard's own two; refusing to choose. Map: {slot_info.get('slots')}")
    if listed:
        return int(listed[0]["uploadImageId"]), {**listed[0], "source": "device slot info"}
    if bundle_size != MODULE_BUNDLE_SIZE:
        raise UploadRefused(
            f"a module bundle is {MODULE_BUNDLE_SIZE} bytes (the partition's size); this file is "
            f"{bundle_size}. Not written.")
    return MODULES_UPLOAD_IMAGE_ID, {"image": None, "slot": "modules", "size": MODULE_BUNDLE_SIZE,
                                     "uploadImageId": MODULES_UPLOAD_IMAGE_ID,
                                     "source": "NayaCore constant (uploadImageToModulesSlot -> 4), "
                                               "numbering confirmed by the device's map"}


def _match_catalog(path: Path, raw: bytes, catalog: list) -> dict:
    """The catalogue entry these BYTES are. Every NayaFlow release since 0.1.0 names its left
    image kb_fwl.bin, so the catalogue built from all 25 releases holds a dozen entries with that
    name and the name alone cannot say which one a file is. The hash of the file decides; the name
    is a fallback only for a catalogue that carries no blob hashes at all (hand-written ones, and
    the test fixtures), and then only when it is unambiguous."""
    blob = hashlib.sha256(raw).hexdigest()
    by_hash = [e for e in catalog or [] if e.get("blobSha256") == blob]
    if len(by_hash) == 1:
        return by_hash[0]
    if by_hash:
        raise UploadRefused(
            f"{len(by_hash)} catalogue entries share this file's hash; the catalogue is "
            "inconsistent and nothing is chosen from it.")
    by_name = [e for e in catalog or [] if e.get("file") == path.name]
    if not by_name:
        raise UploadRefused(
            f"{path.name} is not in the firmware catalogue. Only catalogued images may be "
            "written, because the catalogue is what says which side and flash generation an "
            "image is for.")
    if any(e.get("blobSha256") for e in by_name):
        raise UploadRefused(
            f"{path.name} is a catalogued name, but this file's bytes match none of the "
            f"{len(by_name)} catalogued image(s) of that name (sha256 {blob[:16]}...). A known "
            "name with unknown contents is exactly what must not be written.")
    if len(by_name) > 1:
        raise UploadRefused(
            f"{path.name} is ambiguous: {len(by_name)} catalogue entries carry that name and none "
            "has a blob hash to tell them apart.")
    return by_name[0]


def _is_downgrade(active: dict, target: dict) -> str | None:
    """Why writing `target` over `active` would be a downgrade, or None if it is not one.

    Version numbers when both are declared; otherwise the chronological order of the releases
    that first shipped each image, which is all the catalogue knows for most images before
    1.14.5 (no release declared their number). Unknown both ways is not a downgrade: it is
    simply not checkable, and the other interlocks still apply."""
    have, want = _version_tuple(active.get("createFirmware")), _version_tuple(target.get("createFirmware"))
    if have and want:
        if want < have:
            return (f"{target.get('createFirmware')} is older than the "
                    f"{active.get('createFirmware')} this half runs")
        return None
    ho, to = active.get("releaseOrder"), target.get("releaseOrder")
    if isinstance(ho, int) and isinstance(to, int) and to < ho:
        return (f"{target.get('versionLabel') or target.get('file')} first shipped before the "
                f"{active.get('versionLabel') or 'image'} this half runs, and release order is the "
                "only guide because no release declared its version number")
    return None


def plan(image_path: str | Path, catalog: list, *, slot: int = 1,
         chunk: int = DEFAULT_CHUNK, allow_older: bool = False,
         state: dict | None = None, slot_info: dict | None = None) -> UploadPlan:
    """Run every interlock and return what an upload would do. Writes nothing.

    `state` is a recovery.read_running_image() result; it is read from the device when omitted.
    `slot_info` is a recovery.slot_info() result; when omitted the one carried by `state` is used,
    and when there is none the upload id is the documented assumption, labelled as such.
    Raises UploadRefused with a reason a user can act on.
    """
    path = Path(image_path)
    if not path.is_file():
        raise UploadRefused(f"no such image: {path}")

    raw = path.read_bytes()
    target = _match_catalog(path, raw, catalog)
    if target.get("type") == "littlefs" or target.get("container"):
        raise UploadRefused(
            f"{path.name} is module firmware, not a keyboard image. The module bundle has its "
            "own path (flash_module_bundle) because it is not an MCUboot image and goes to a "
            "different slot.")
    if not target.get("flashable"):
        why = "; ".join(target.get("withheldBecause") or ["it is not marked flashable"])
        raise UploadRefused(f"{path.name} is catalogued but withheld: {why}")

    state = state if state is not None else rec.read_running_image(catalog)
    if state.get("state") != "ok":
        raise UploadRefused(
            "the half did not report its image state, so there is nothing to check the image "
            f"against. {state.get('detail') or ''}".strip())

    active = next((i for i in state.get("images") or [] if i.get("slot") == 0), None)
    if active is None:
        raise UploadRefused("the half reported no primary slot.")
    if not active.get("identified"):
        raise UploadRefused(
            "the image this half is running is not one we hold, so we cannot tell which side or "
            "flash generation it is. Writing on that basis is exactly the mistake the catalogue "
            f"exists to prevent. Its hash is {active.get('hash')}.")

    if active.get("side") != target.get("side"):
        raise UploadRefused(
            f"this is the {active.get('side')} half and {path.name} is the "
            f"{target.get('side')} image. Left and right are different binaries.")
    if active.get("generation") != target.get("generation"):
        raise UploadRefused(
            f"this half runs flash generation {active.get('generation')} and {path.name} is "
            f"generation {target.get('generation')}. The generations are not interchangeable — "
            "NayaCore refuses this too.")

    why_older = _is_downgrade(active, target)
    if why_older and not allow_older:
        raise UploadRefused(
            f"{why_older}. Downgrading is a legitimate repair — it is how two halves that no "
            "longer talk to each other are brought back to a common version — so pass "
            "allow_older=True to say you meant it.")

    if slot_info is None:
        slot_info = state.get("slotInfo")
    image_id, id_source = upload_image_id(slot, slot_info)
    size = _slot_size(slot_info, 0, slot)
    if size is not None and len(raw) > size:
        raise UploadRefused(
            f"{path.name} is {len(raw)} bytes and slot {slot} is {size}; the bootloader would "
            "refuse it too.")

    return UploadPlan(
        image_path=path, slot=slot, total_bytes=len(raw),
        chunks=max(1, -(-len(raw) // chunk)),
        image_sha256=hashlib.sha256(raw).hexdigest(),
        running=active, target=target, port=state.get("port", ""),
        # The arming token is the DEVICE's own reported hash. A caller cannot arm this in
        # advance, or reuse an arming decision made about a different half.
        arm_token=active.get("hash") or "",
        upload_image_id=image_id, upload_id_source=id_source,
    )


def build_chunk_request(image_id: int, offset: int, data: bytes, *, total: int | None = None,
                        sha: bytes | None = None, seq: int = 0) -> bytes:
    """One `image upload` frame. Pure; builds bytes and sends nothing.

    `image_id` is the value on the wire (see the note at the top of the file: it addresses a
    slot, and which slot depends on the bootloader's build), NOT an MCUboot slot number. The
    first chunk carries the total length and the image hash; later chunks carry only their
    offset, which is how the bootloader tracks progress and how a resumed upload finds its place.
    """
    if not 0 < len(data) <= MAX_CHUNK:
        raise ValueError(f"a chunk is 1 to {MAX_CHUNK} bytes, not {len(data)}: one SMP frame "
                         "carries a 16-bit length and the bootloader's buffer is far smaller")
    body: dict = {"image": image_id, "off": offset, "data": data}
    if offset == 0:
        if total is None or sha is None:
            raise ValueError("the first chunk must carry the total length and the image hash")
        body["len"] = total
        body["sha"] = sha
    payload = _cbor_encode(body)
    return rec.encode_request(SMP_OP_WRITE, rec.SMP_GROUP_IMAGE, SMP_ID_IMAGE_UPLOAD,
                              payload=payload, seq=seq)


def _send_chunks(port: str, image_id: int, raw: bytes, *, chunk: int, progress=None,
                 untouched: str = "the primary image is untouched") -> int:
    """Stream one image to the bootloader, chunk by chunk, stopping on the first refusal. Returns
    the number of bytes the DEVICE acknowledged."""
    sha = hashlib.sha256(raw).digest()
    sent, seq = 0, 0
    while sent < len(raw):
        piece = raw[sent:sent + chunk]
        frame = build_chunk_request(image_id, sent, piece,
                                    total=len(raw) if sent == 0 else None,
                                    sha=sha if sent == 0 else None, seq=seq & 0xFF)
        reply = rec._talk(port, frame, timeout=5.0)
        rc = reply.get("rc", 0)
        if rc:
            raise UploadRefused(f"the bootloader rejected the chunk at offset {sent} (rc={rc}). "
                                f"Nothing further is sent; {untouched}.")
        # The device says where it wants the next byte. Trusting our own counter instead is how
        # an upload silently writes a corrupt image after one dropped frame.
        sent = reply.get("off", sent + len(piece))
        seq += 1
        if progress:
            progress(sent, len(raw))
    return sent


def upload(image_path: str | Path, catalog: list, *, arm: str, slot: int = 1,
           chunk: int = DEFAULT_CHUNK, allow_older: bool = False, progress=None,
           state: dict | None = None, slot_info: dict | None = None) -> dict:
    """Write an image to a half in recovery. Called only by flash(); on its own it leaves an
    image in the secondary slot that never boots.

    `arm` must equal the hash the device reports for its running image -- see plan().arm_token.
    That is deliberately not a boolean: an arming flag can be left switched on, and a token tied
    to one device's current state cannot be reused on the next one by accident.

    Never run against hardware. The read path it sits on is proven; this request shape is not.
    """
    p = plan(image_path, catalog, slot=slot, chunk=chunk, allow_older=allow_older,
             state=state, slot_info=slot_info)
    if arm != p.arm_token:
        raise UploadRefused(
            "not armed. Pass arm= the hash this half reports for its running image "
            f"({p.arm_token or 'unavailable'}); it is printed by the plan.")

    raw = Path(image_path).read_bytes()
    sent = _send_chunks(p.port, p.upload_image_id, raw, chunk=chunk, progress=progress)
    return {"ok": True, "written": sent, "slot": slot, "uploadImageId": p.upload_image_id,
            "uploadIdSource": p.upload_id_source, "image": Path(image_path).name, "port": p.port}


# --- activating the uploaded image: the two steps upload() stops short of ------------------- #

def build_set_pending_request(image_hash: bytes | None, *, confirm: bool = False,
                              seq: int = 0) -> bytes:
    """`image state` WRITE: mark the image with this hash for the next boot. Pure; sends nothing.

    `confirm=False` is MCUboot's TEST mode: the bootloader swaps the image in for ONE boot and
    swaps back if that image never confirms itself -- the safety net a first flash on a donor
    unit wants. `confirm=True` makes the swap permanent at once. With `confirm=True` and no hash
    the request confirms whatever is currently running (mcumgr's `image confirm`), which is the
    follow-up a test-booted image needs before its next reset.

    The hash is the one the DEVICE reports for the slot (`image state` read): the SHA-256 of the
    decrypted image, i.e. the catalogue's plaintextSha256 -- not the hash of the encrypted file.
    """
    if image_hash is None:
        if not confirm:
            raise ValueError("marking an image pending needs its hash; only confirm may omit it")
        body: dict = {"confirm": True}
    else:
        if len(image_hash) != 32:
            raise ValueError("an image hash is 32 bytes")
        body = {"hash": bytes(image_hash), "confirm": bool(confirm)}
    return rec.encode_request(SMP_OP_WRITE, rec.SMP_GROUP_IMAGE, SMP_ID_IMAGE_STATE,
                              payload=_cbor_encode(body), seq=seq)


def build_reset_request(*, seq: int = 0) -> bytes:
    """`os reset`: reboot so MCUboot performs the swap. Empty CBOR map payload. Pure."""
    return rec.encode_request(SMP_OP_WRITE, rec.SMP_GROUP_OS, SMP_ID_OS_RESET, seq=seq)


def _hex(h) -> str:
    return h.hex() if isinstance(h, (bytes, bytearray)) else str(h or "").lower()


def _live_slot_info(state: dict) -> dict | None:
    """The slot map for the port `state` was read on, read now if the state read did not carry
    one. A failure here is not a refusal: the plan then labels its upload id as assumed."""
    if state.get("slotInfo") is not None:
        return state["slotInfo"]
    if not state.get("port"):
        return None
    try:
        return rec.slot_info(state["port"])
    except Exception:      # noqa: BLE001 -- ENOTSUP or a closed window; the plan says "assumed"
        return None


def flash(image_path: str | Path, catalog: list, *, arm: str, slot: int = 1,
          chunk: int = DEFAULT_CHUNK, allow_older: bool = False, confirm: bool = False,
          progress=None, state: dict | None = None, slot_info: dict | None = None) -> dict:
    """The whole NayaCore sequence: upload -> re-read the slot -> mark pending -> reset.

    Every upload() interlock applies (it runs first, on one device read shared with the plan).
    Then one more: the slot is re-read and its hash must be the catalogued plaintext hash of the
    image we meant to write. If it is not, nothing further is sent, nothing is marked bootable
    and the primary image is untouched -- the failure mode stays "nothing changed".

    Default `confirm=False` boots the new image in MCUboot test mode; it reverts on the following
    reset unless confirmed (build_set_pending_request(None, confirm=True) once it is up). That
    confirm is deliberately a separate, later decision.

    GATED: reached only through the FIRMWARE_FLASH_ENABLED endpoint. Never run on hardware.
    """
    if state is None:
        state = rec.read_running_image(catalog)      # one read, shared by plan() and upload()
    if slot_info is None:
        slot_info = _live_slot_info(state)
    result = upload(image_path, catalog, arm=arm, slot=slot, chunk=chunk,
                    allow_older=allow_older, progress=progress, state=state, slot_info=slot_info)
    p = plan(image_path, catalog, slot=slot, chunk=chunk, allow_older=allow_older, state=state,
             slot_info=slot_info)

    want = _hex(p.target.get("plaintextSha256"))
    if len(want) != 64:
        raise UploadRefused(
            f"{p.image_path.name} has no catalogued plaintext hash, so the slot it landed in "
            "cannot be checked before it is marked bootable. Not marking anything; the primary "
            "image is untouched.")
    after = rec.image_state(p.port)
    landed = next((i for i in after.get("images") or [] if i.get("slot") == slot), None)
    got = _hex(landed.get("hash")) if landed else ""
    if got != want:
        raise UploadRefused(
            f"after upload, slot {slot} reports {got or 'no image'} but {p.image_path.name} "
            f"should read {want}. It is NOT marked bootable; the primary image is untouched.")

    reply = rec._talk(p.port, build_set_pending_request(bytes.fromhex(want), confirm=confirm,
                                                        seq=1), timeout=5.0)
    if reply.get("rc", 0):
        raise UploadRefused(
            f"the bootloader refused to mark slot {slot} pending (rc={reply['rc']}). Nothing "
            "was reset; the primary image is untouched.")
    # The device reboots while answering this, so a short or missing reply is the expected
    # outcome of a reset that worked, not an error to surface.
    try:
        rec._talk(p.port, build_reset_request(seq=2), timeout=2.0)
    except Exception:      # noqa: BLE001 -- see above
        pass
    result.update({"marked": "confirm" if confirm else "test", "hash": want, "reset": True})
    return result


# --- the module bundle: FlashMemory.bin into the modules slot -------------------------------- #
# NayaCore's UpdateModule sequence (Naya_DeviceManager_ModuleFwUpdate.cpp, from its strings):
#   ModuleFW_FileVerification -> [LEFT half into MCUboot; MCUBootWorker_CreateLeft_Modules uploads
#   the bundle with uploadImageToSlot] -> ModuleFW_FileVerificationPostUpload -> [reboot] ->
#   ModuleFW_Update (MODULE_FWUP with the docked module's type; the Create programs the module
#   from the bundle it now holds) -> ModuleFW_VersionCheck (the module's GET_MODULE_FW_VERSION
#   against the bundle's VERSION).
# Only a LEFT worker exists in NayaCore, so the module store is the left half's. The bundle is a
# LittleFS image, not an MCUboot image: nothing is marked pending, MCUboot does not swap it, and
# there is no hash to read back through `image state`. The post-upload check is therefore an
# app-mode read after the reboot -- MODULE_FILE_FW_VERSION (DeviceService.module_file_fw_version)
# must equal the bundle's VERSION -- and the third step is the gated recovery op `module_fwup`.

@dataclass
class ModuleBundlePlan:
    """What a module bundle upload WOULD do. Produced without writing anything."""
    image_path: Path
    total_bytes: int
    chunks: int
    image_sha256: str
    upload_image_id: int
    slot: dict = field(default_factory=dict)          # the slot-map entry chosen
    running: dict = field(default_factory=dict)
    target: dict = field(default_factory=dict)
    port: str = ""
    arm_token: str = ""

    @property
    def expected_version(self) -> str | None:
        return self.target.get("moduleFirmware")

    def describe(self) -> str:
        r, t = self.running, self.target
        return (f"{self.image_path.name} -> modules slot (upload image id {self.upload_image_id}: "
                f"{self.slot.get('source')}) on {self.port}\n"
                f"  left half runs {r.get('file')} (fw {r.get('versionLabel') or r.get('createFirmware')})\n"
                f"  writing module firmware {t.get('versionLabel')} ({t.get('bundle')}), "
                f"{len(t.get('contents') or {})} userapps\n"
                f"  {self.total_bytes} bytes in {self.chunks} chunks\n"
                f"  after reboot expect MODULE_FILE_FW_VERSION = {self.expected_version}\n"
                f"  arm token: {self.arm_token}")


def plan_module_bundle(image_path: str | Path, catalog: list, *, chunk: int = DEFAULT_CHUNK,
                       state: dict | None = None, slot_info: dict | None = None,
                       installed_version: str | None = None,
                       allow_older: bool = False) -> ModuleBundlePlan:
    """Every interlock for a module bundle upload. Writes nothing.

    `installed_version` is what MODULE_FILE_FW_VERSION reported before the half was rebooted into
    recovery (the app-mode read); with it, going back a version needs allow_older, as for a
    keyboard image. Without it the version guard cannot run and says so in the plan.
    """
    path = Path(image_path)
    if not path.is_file():
        raise UploadRefused(f"no such image: {path}")
    raw = path.read_bytes()
    target = _match_catalog(path, raw, catalog)
    if target.get("type") != "littlefs" or target.get("target") != "module":
        raise UploadRefused(
            f"{path.name} is not a module bundle (a LittleFS FlashMemory.bin). A keyboard image "
            "goes through plan()/flash(); a single .sfb is never written on its own, the bundle "
            "that contains it is.")
    if not target.get("flashable"):
        why = "; ".join(target.get("withheldBecause") or ["it is not marked flashable"])
        raise UploadRefused(f"{path.name} is catalogued but withheld: {why}")

    state = state if state is not None else rec.read_running_image(catalog)
    if state.get("state") != "ok":
        raise UploadRefused(
            "the half did not report its image state, so there is nothing to check against. "
            f"{state.get('detail') or ''}".strip())
    active = next((i for i in state.get("images") or [] if i.get("slot") == 0), None)
    if active is None:
        raise UploadRefused("the half reported no primary slot.")
    if not active.get("identified"):
        raise UploadRefused(
            "the image this half is running is not one we hold, so it is not known to be a "
            f"Create in a known state. Its hash is {active.get('hash')}.")
    if active.get("side") != "left":
        raise UploadRefused(
            f"this is the {active.get('side')} half. The module firmware store is the LEFT "
            "half's: NayaCore uploads the bundle through the left half only.")

    have, want = _version_tuple(installed_version), _version_tuple(target.get("moduleFirmware"))
    if have and want and want < have and not allow_older:
        raise UploadRefused(
            f"module firmware {target.get('moduleFirmware')} is older than the "
            f"{installed_version} this keyboard holds. Pass allow_older=True to say you meant it.")

    if slot_info is None:
        slot_info = state.get("slotInfo")
    image_id, slot = modules_slot(slot_info, len(raw))
    return ModuleBundlePlan(
        image_path=path, total_bytes=len(raw), chunks=max(1, -(-len(raw) // chunk)),
        image_sha256=hashlib.sha256(raw).hexdigest(), upload_image_id=image_id, slot=slot,
        running=active, target=target, port=state.get("port", ""),
        arm_token=active.get("hash") or "",
    )


def flash_module_bundle(image_path: str | Path, catalog: list, *, arm: str,
                        chunk: int = DEFAULT_CHUNK, installed_version: str | None = None,
                        allow_older: bool = False, progress=None, state: dict | None = None,
                        slot_info: dict | None = None) -> dict:
    """Upload a module bundle into the modules slot of the left half and reboot it. The
    verification is NOT here: it is the app-mode MODULE_FILE_FW_VERSION read after the half is
    back, which the result spells out, followed by the `module_fwup` op with a module docked.

    No mark-pending: the bundle is a filesystem, MCUboot has nothing to swap. Interrupting the
    upload leaves the modules partition partly erased and the KEYBOARD firmware untouched -- the
    keyboard keeps working, module programming does not until a bundle is uploaded again.

    GATED: reached only through the FIRMWARE_FLASH_ENABLED endpoint. Never run on hardware.
    """
    if state is None:
        state = rec.read_running_image(catalog)
    if slot_info is None:
        slot_info = _live_slot_info(state)
    p = plan_module_bundle(image_path, catalog, chunk=chunk, state=state, slot_info=slot_info,
                           installed_version=installed_version, allow_older=allow_older)
    if arm != p.arm_token:
        raise UploadRefused(
            "not armed. Pass arm= the hash this half reports for its running image "
            f"({p.arm_token or 'unavailable'}); it is printed by the plan.")
    raw = p.image_path.read_bytes()
    sent = _send_chunks(p.port, p.upload_image_id, raw, chunk=chunk, progress=progress,
                        untouched="the keyboard firmware is untouched, the modules partition is "
                                  "partly written")
    if sent < len(raw):
        raise UploadRefused(
            f"the bootloader acknowledged {sent} of {len(raw)} bytes and stopped. Not resetting; "
            "upload the bundle again.")
    try:
        rec._talk(p.port, build_reset_request(seq=1), timeout=2.0)
    except Exception:      # noqa: BLE001 -- the device reboots while answering
        pass
    return {"ok": True, "written": sent, "uploadImageId": p.upload_image_id,
            "slot": p.slot, "image": p.image_path.name, "port": p.port, "reset": True,
            "verifyNext": {"read": "MODULE_FILE_FW_VERSION", "expect": p.expected_version,
                           "then": "module_fwup with the docked module's type, then "
                                   "GET_MODULE_FW_VERSION should report the same version"}}
