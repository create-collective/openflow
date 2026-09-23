"""Writing a firmware image to a half in MCUboot recovery.

GATED, and still gated. The only route here is /rpc/flash-firmware and the supervised procedure
above it, both of which refuse at a module-level gate (FIRMWARE_FLASH_ENABLED, ships False)
before this file is even imported; and `flash()` refuses to run unless the caller passes an
explicit arming token computed from the device's own reported state.

THE SEQUENCE is NayaCore's, and it is stock MCUboot/SMP in every release the company shipped
(nayaHistory/FLASHING-PROCEDURE.md): upload the image to the secondary slot, mark it pending,
reset so the bootloader swaps. `upload()` is the first step only; `flash()` is all three, with
a slot re-read between upload and mark so a wrong image is never marked bootable.

IT HAS NOW BEEN RUN ON HARDWARE (2026-09-20, SCRUM-108). Six full slot writes across both halves
of the reference board, 3.35.4 and 3.41.0 in both directions, ending in two clean supervised runs
with the keymap intact and the version confirmed. Every one of those uploads went up as the whole
vendor resource -- `vendor_trailer=True` -- which is why that is now the default; see the trailer
note below. The header used to say this file had never touched a board, and that sentence has
been wrong since Saturday.

WHY IT IS SAFE-ISH BY CONSTRUCTION, and where that stops being true.

MCUboot writes an uploaded image into the SECONDARY slot and only swaps on the next boot after
the image is marked for it. An interrupted upload therefore leaves the primary image untouched,
and the realistic failure is "nothing changed", not "bricked". That is MCUboot's documented
design plus what this device's own bootloader log shows (`Primary image: magic=good ...`,
`Scratch: magic=unset`) -- it is NOT something we have watched fail and recover here. The first
real upload belongs on a donor unit.

THE RESOURCE CARRIES ITS OWN TRAILER (review of 2026-09-16). Every keyboard image Naya ships is
the whole 663552-byte slot: header + image + TLVs, 0xFF, then an MCUboot swap trailer already
written -- `image_ok = 0x01` at 24 bytes from the end and BOOT_MAGIC in the last 16. By MCUboot's
swap table (secondary magic good + image_ok set) that schedules a PERMANENT swap the moment the
last chunk lands, before anything has been checked, and it makes a later "mark pending" a no-op
(boot_set_pending_multi returns 0 when the magic is already good). NayaCore uploads the whole
resource and simply resets. Uploading it that way means: no test mode, and the swap armed before
the hash check.

The alternative, which this file used to default to, is to upload ONLY the MCUboot image (the
part before the padding; `mcuboot_image_length`), leave the trailer area erased, verify the slot,
and then write the trailer ourselves through `image state` with the hash -- test or permanent,
our decision, after the check. On paper it is the better sequence, and on paper is where it has
stayed: every upload this project has ever put on a board used the vendor's bytes.

Its last step HAS met hardware, and failed. On 2026-09-20 an `image state` write on the
reference board's bootloader, arming a swap of an image already in the secondary slot, came back
rc=8 (MGMT_ERR_ENOTSUP): this bootloader does not implement the write at all. So on the Create,
`vendor_trailer=False` would upload the whole image, pass the slot check, and then fail at the
mark, leaving a written slot with nothing armed. The same finding means an image already sitting
in the secondary slot cannot be booted by marking it; it has to be uploaded again. And it is why
NayaCore's `testImage`/`confirmImage` exist in its binary and are never called: the vendor had
no other route either.

So the DEFAULT IS vendor_trailer=True (SCRUM-106): it is the path that has been run, and on this
bootloader the only one that can work. `vendor_trailer=False` remains, unchanged, for a
bootloader that does implement `image state`; do not re-derive the "safer" argument above and
make it the default again for the Create. What the vendor path costs is real and is not hidden: the swap is
armed by the last chunk, so there is no test mode and the hash check happens after the point of
no return -- MCUboot validates the signature before it swaps and refuses a corrupt image, which
is what makes that survivable, and the procedure above verifies the running version afterwards
either way.

WHAT "TEST MODE" MEANS HERE. With confirm=False the swap is a TEST swap: the new image boots once
and, unless it confirms itself from inside the application, MCUboot swaps back on the following
reset. There is NO way to confirm it afterwards from recovery: `image state` write without a hash
is not "confirm the running image" in MCUboot's serial recovery (that is the application-side
mcumgr meaning); it calls boot_set_pending_multi(0, confirm) on the SECONDARY slot, i.e. it
schedules a swap. Whether the Create's application self-confirms is not known. A permanent
flash is confirm=True, which is what NayaCore's trailer amounts to.

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
import time
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
# NayaCore's own chunk: uploadImageToSlot sends min(remaining, 0x200) bytes per frame (x86_64
# 0x100115e95: cmp eax, 0x200 / cmovge), so 512 is the one size this bootloader is known to take.
DEFAULT_CHUNK = 512
# Hard cap on what one frame may carry. The SMP header's length field is 16 bits and the
# bootloader's receive buffer (MCUBOOT_SERIAL_MAX_RECEIVE_SIZE) is the real limit below that; a
# chunk the bootloader will not take is refused with an rc and the upload stops before anything
# is marked. This cap only turns an impossible frame into a clear error.
MAX_CHUNK = 4096

# The MCUboot swap trailer, read from the END of a slot-sized resource (BOOT_MAX_ALIGN 8: the
# 16-byte magic last, then one 8-byte field each for image_ok, copy_done, swap_info).
BOOT_MAGIC = bytes.fromhex("77c295f360d2ef7f3552500f2cb67980")
TRAILER_LEN = 24                       # image_ok field + magic; what `image state` write would set
IMAGE_MAGIC = 0x96F3B83D
TLV_INFO_MAGIC, TLV_PROT_MAGIC = 0x6907, 0x6908


def image_trailer(raw: bytes) -> dict:
    """What the last 24 bytes of a resource say. `swap` is MCUboot's reading of them for a
    secondary slot: "permanent" (magic good, image_ok set), "test" (magic good, image_ok unset),
    or None (no magic: nothing scheduled by the bytes themselves)."""
    if len(raw) < 48:
        return {"magic": "none", "imageOk": False, "swap": None}
    magic = raw[-16:]
    image_ok = raw[-24]
    good = magic == BOOT_MAGIC
    unset = magic == b"\xff" * 16
    return {"magic": "good" if good else "unset" if unset else "other",
            "imageOk": image_ok == 0x01,
            "swap": ("permanent" if image_ok == 0x01 else "test") if good else None}


def mcuboot_image_length(raw: bytes) -> int | None:
    """Header + image + every TLV area: the bytes an MCUboot image actually is, without the
    padding and trailer a slot-sized resource carries after it. None when there is no header."""
    if len(raw) < 32:
        return None
    magic, _load, hdr_size, _pad, img_size, _flags = struct.unpack_from("<IIHHII", raw, 0)
    if magic != IMAGE_MAGIC:
        return None
    off = hdr_size + img_size
    areas = 0
    while off + 4 <= len(raw) and areas < 2:
        tmagic, total = struct.unpack_from("<HH", raw, off)
        if tmagic not in (TLV_INFO_MAGIC, TLV_PROT_MAGIC):
            break
        off += total
        areas += 1
    return off if areas else None

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
    file_bytes: int = 0               # the whole resource on disk
    trailer: dict = field(default_factory=dict)      # image_trailer() of the resource
    vendor_trailer: bool = True      # True: upload the whole resource, trailer included, no mark

    @property
    def arms_on_upload(self) -> bool:
        """True when the bytes being uploaded include a trailer that schedules a swap by
        themselves (the vendor's way); the flash then sends no `image state` write."""
        return self.vendor_trailer and self.trailer.get("swap") is not None

    def describe(self) -> str:
        t, r = self.target, self.running
        how = (f"whole resource incl. its trailer ({self.trailer.get('swap')} swap armed by the "
               f"upload, as NayaCore does)" if self.arms_on_upload else
               "MCUboot image only; the trailer is written by `image state` after the slot check")
        return (f"{self.image_path.name} -> slot {self.slot} on {self.port} "
                f"(upload image id {self.upload_image_id}: {self.upload_id_source})\n"
                f"  running : {r.get('file')} ({r.get('side')}/gen {r.get('generation')}, "
                f"fw {r.get('versionLabel') or r.get('createFirmware')})\n"
                f"  writing : {t.get('file')} ({t.get('side')}/gen {t.get('generation')}, "
                f"fw {t.get('versionLabel') or t.get('createFirmware')}, {t.get('bundle')})\n"
                f"  {self.total_bytes} of {self.file_bytes} bytes in {self.chunks} chunks: {how}\n"
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


def modules_slot(slot_info: dict | None, bundle_size: int, *,
                 allow_unmapped: bool = False) -> tuple[int, dict]:
    """Which upload id addresses the modules partition, and the slot-map row it rests on.

    The partition is a filesystem, not an MCUboot image slot, so the bootloader's map never
    lists it (confirmed on the owner's board: the map has image 0's two slots and nothing else).
    The number therefore comes from NayaCore -- uploadImageToModulesSlot is uploadImageToSlot(_, 4)
    -- and it is used only after the map has shown that this bootloader and NayaCore count the
    same way (_numbering_is_understood). Should a map ever list a slot of exactly the bundle's
    size with an upload id, the device's own row wins over the constant.

    `allow_unmapped` (owner, 2026-09-23): when the bootloader does not ANSWER the map at all, use
    NayaCore's constant anyway, because that is exactly what NayaFlow does -- it never reads the
    map (captured 2026-09-23) -- and 4 never addresses the running firmware. A map that answers
    and disagrees is still refused; that is the case the check exists for. The caller retries
    the read first and logs that it fell back."""
    if allow_unmapped and not (slot_info and slot_info.get("supported")):
        if bundle_size != MODULE_BUNDLE_SIZE:
            raise UploadRefused(
                f"a module bundle is {MODULE_BUNDLE_SIZE} bytes (the partition's size); this file "
                f"is {bundle_size}. Not written.")
        return MODULES_UPLOAD_IMAGE_ID, {
            "image": None, "slot": "modules", "size": MODULE_BUNDLE_SIZE,
            "uploadImageId": MODULES_UPLOAD_IMAGE_ID,
            "source": "NayaCore constant (uploadImageToModulesSlot -> 4); the bootloader did not "
                      "answer its slot map, and NayaFlow does not read it either"}
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
    the test fixtures), and then only when it is unambiguous.

    CUSTOM FIRMWARE. This is the check that stands between the flasher and an image nobody has
    identified, and it is why OpenFlow cannot be pointed at a firmware of your own today. That is
    not the real obstacle: the device's bootloader verifies Naya's signature, so an image built
    elsewhere is refused by MCUboot even if this function let it past, and writing one would
    achieve nothing but a wasted slot. The plan is a community-signed bootloader with an open
    firmware to go with it. What changes here when that exists is a SECOND trust root beside the
    catalogue -- a signature we can verify, with its own provenance -- not the removal of this
    one. An "allow unsigned" switch would make every protection in this file optional at exactly
    the moment a user is least able to judge the risk.
    """
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


def _pid_agrees_with_image(state: dict, active: dict) -> None:
    """The USB product id encodes the half's side and flash generation (NayaCore's own table,
    recovery.pid_info) and so does the running image's catalogue entry. They come from different
    places -- the hardware's descriptor and the bootloader's hash -- and a write proceeds only
    when both say the same thing. A state without a pid reading (older callers, fixtures) is not
    a disagreement."""
    for key, mine in (("pidSide", "side"), ("pidGeneration", "generation")):
        theirs = state.get(key)
        if theirs and active.get(mine) and theirs != active[mine]:
            raise UploadRefused(
                f"the USB product id {state.get('pid'):#06x} says this half is {key[3:].lower()} "
                f"{theirs}, but the image it runs is catalogued as {active[mine]}. Two sources "
                "disagree about what this half is, so nothing is written to it.")


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
         state: dict | None = None, slot_info: dict | None = None,
         vendor_trailer: bool = True) -> UploadPlan:
    """Run every interlock and return what an upload would do. Writes nothing.

    `state` is a recovery.read_running_image() result; it is read from the device when omitted.
    `slot_info` is a recovery.slot_info() result; when omitted the one carried by `state` is used,
    and when there is none the upload id is the documented assumption, labelled as such.
    `vendor_trailer=True` (the default, and the only path that has been run on hardware) uploads
    the whole resource as NayaCore does, trailer included, which arms the swap on upload; False
    uploads only the MCUboot image and marks the slot after checking it, which is the better
    sequence on paper and untried (see the note at the top). Raises UploadRefused with a reason a
    user can act on.
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

    _pid_agrees_with_image(state, active)
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

    if slot != 1:
        raise UploadRefused(
            f"slot {slot} is not a place this sequence writes. Slot 0 is the PRIMARY, the image "
            "the half boots from: writing it directly is exactly the failure MCUboot's swap "
            "exists to prevent. The sequence uploads to the secondary (1) and lets the "
            "bootloader swap.")
    if slot_info is None:
        slot_info = state.get("slotInfo")
    image_id, id_source = upload_image_id(slot, slot_info)
    size = _slot_size(slot_info, 0, slot)
    if size is not None and len(raw) > size:
        raise UploadRefused(
            f"{path.name} is {len(raw)} bytes and slot {slot} is {size}; the bootloader would "
            "refuse it too.")

    trailer = image_trailer(raw)
    image_len = mcuboot_image_length(raw)
    if vendor_trailer or image_len is None:
        upload_len = len(raw)          # the whole resource (or a file with no header to trim)
    else:
        upload_len = image_len
    if not 0 < chunk <= MAX_CHUNK:
        raise UploadRefused(f"chunk must be 1 to {MAX_CHUNK} bytes, not {chunk}")

    return UploadPlan(
        image_path=path, slot=slot, total_bytes=upload_len,
        chunks=max(1, -(-upload_len // chunk)),
        image_sha256=hashlib.sha256(raw[:upload_len]).hexdigest(),
        running=active, target=target, port=state.get("port", ""),
        # The arming token is the DEVICE's own reported hash. A caller cannot arm this in
        # advance, or reuse an arming decision made about a different half.
        arm_token=active.get("hash") or "",
        upload_image_id=image_id, upload_id_source=id_source,
        file_bytes=len(raw), trailer=trailer, vendor_trailer=vendor_trailer,
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


# A warm port answers a chunk in tens of milliseconds; these generous values are for a BUSY
# device, not a stalled one, and a genuinely dead device still fails -- just later.
#
# ERASE_TIMEOUT covers the secondary-slot erase the first chunk triggers. CHUNK_TIMEOUT was 5.0
# and that was too tight: the erase is NOT finished when the first chunk is acknowledged, and a
# chunk shortly afterwards can block for longer than five seconds while the bootloader catches
# up. A real downgrade run died exactly there on 2026-09-20, nineteen seconds into an upload that
# was working. The earlier upgrade survived the same behaviour only by luck -- its post-erase
# stall was seventeen seconds spread across a hundred and thirty chunks, so no single chunk
# exceeded the limit. Bounded patience is the whole trade: at ~11 KB/s a healthy upload is done
# in about a minute, so a twenty-second ceiling costs nothing when things are fine.
CHUNK_TIMEOUT = 20.0
ERASE_TIMEOUT = 90.0


def _send_chunks(port: str, image_id: int, raw: bytes, *, chunk: int, progress=None,
                 untouched: str = "the primary image is untouched", link=None) -> int:
    """Stream one image to the bootloader, chunk by chunk, stopping on the first refusal. Returns
    the number of bytes the DEVICE acknowledged. With `link` (recovery.BootloaderLink) the chunks
    go over the conversation the caller already holds -- the port that identified the half, with
    its console drained -- instead of a session opened here."""
    sha = hashlib.sha256(raw).digest()
    if link is not None:
        return _stream_chunks(link.send, image_id, raw, sha, chunk, progress, untouched)
    # ONE open port for the whole transfer, as NayaCore does ("Open the serial port ... chunked
    # via uploadImageChunk"). This used to call rec._talk per chunk, which reopens the port every
    # time -- and the bootloader's CDC endpoint needs a moment to settle after an open, so a
    # 1296-chunk upload paid that 1296 times. Measured: 5.06 s per chunk that way, 1h50 for an
    # image the vendor writes in about two minutes; a warm port answers in 78 ms.
    with rec.session(port, timeout=CHUNK_TIMEOUT) as send:
        return _stream_chunks(send, image_id, raw, sha, chunk, progress, untouched)


def _stream_chunks(send, image_id, raw, sha, chunk, progress, untouched) -> int:
    sent, seq = 0, 0
    while sent < len(raw):
        piece = raw[sent:sent + chunk]
        frame = build_chunk_request(image_id, sent, piece,
                                    total=len(raw) if sent == 0 else None,
                                    sha=sha if sent == 0 else None, seq=seq & 0xFF)
        # The FIRST chunk makes the bootloader erase the whole secondary slot before it answers,
        # and 648 KiB of internal flash takes far longer than a normal round trip -- measured on
        # 2026-09-20: the device went silent right after chunk one and was answering again, with
        # slot 1 gone, when probed later. A 5 s timeout called that a dead device and aborted an
        # upload that was working. Every later chunk writes into already-erased flash and comes
        # back in tens of milliseconds, so only offset 0 needs the long wait.
        reply = send(frame, ERASE_TIMEOUT if sent == 0 else CHUNK_TIMEOUT)
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
           state: dict | None = None, slot_info: dict | None = None,
           vendor_trailer: bool = True) -> dict:
    """Write an image to a half in recovery. Called only by flash(); on its own it leaves an
    image in the secondary slot that never boots (unless `vendor_trailer`, whose bytes arm the
    swap by themselves -- see the note at the top).

    `arm` must equal the hash the device reports for its running image -- see plan().arm_token.
    That is deliberately not a boolean: an arming flag can be left switched on, and a token tied
    to one device's current state cannot be reused on the next one by accident.

    Run on hardware since 2026-09-20, always with the vendor trailer. The other path through
    here -- image only, trailer written afterwards -- has not been.
    """
    p = plan(image_path, catalog, slot=slot, chunk=chunk, allow_older=allow_older,
             state=state, slot_info=slot_info, vendor_trailer=vendor_trailer)
    if arm != p.arm_token:
        raise UploadRefused(
            "not armed. Pass arm= the hash this half reports for its running image "
            f"({p.arm_token or 'unavailable'}); it is printed by the plan.")

    raw = Path(image_path).read_bytes()[:p.total_bytes]
    sent = _send_chunks(p.port, p.upload_image_id, raw, chunk=chunk, progress=progress)
    return {"ok": True, "written": sent, "ofFile": p.file_bytes, "slot": slot,
            "uploadImageId": p.upload_image_id, "uploadIdSource": p.upload_id_source,
            "image": Path(image_path).name, "port": p.port,
            "armedByUpload": p.arms_on_upload}


# --- activating the uploaded image: the two steps upload() stops short of ------------------- #

def build_set_pending_request(image_hash: bytes, *, confirm: bool = False, seq: int = 0) -> bytes:
    """`image state` WRITE: schedule the swap for the image with this hash. Pure; sends nothing.

    MCUboot's serial recovery (bs_set) finds the slot whose image has this hash and calls
    boot_set_pending_multi(image, confirm) on the SECONDARY slot: `confirm=False` writes the
    trailer magic only (a TEST swap: boots once, reverts on the following reset unless the
    application confirms itself), `confirm=True` also sets image_ok (a PERMANENT swap). If the
    trailer magic is already good the call changes nothing and returns 0.

    There is deliberately no hash-less form. In application-side mcumgr `{"confirm": true}` means
    "confirm the running image"; in MCUboot's serial recovery the same bytes mean
    boot_set_pending_multi(0, true), i.e. schedule a permanent swap of whatever sits in the
    secondary slot. Nothing here may send that by accident.

    The hash is the one the DEVICE reports for the slot (`image state` read): the SHA-256 of the
    decrypted image, i.e. the catalogue's plaintextSha256 -- not the hash of the encrypted file.
    """
    if image_hash is None:
        raise ValueError("an image state write needs the hash of the image to schedule; the "
                         "hash-less form is not 'confirm the running image' in serial recovery")
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


def _slot_flags(images: list | None, slot: int) -> dict | None:
    """The `pending` / `permanent` / `confirmed` flags the bootloader reports for a slot, when it
    reports them at all (MCUBOOT_SERIAL_IMG_GRP_IMAGE_STATE); None when the reply carries none,
    which is a valid build and not a failure."""
    row = next((i for i in images or [] if i.get("slot") == slot), None)
    if row is None or not any(k in row for k in ("pending", "permanent", "confirmed", "active")):
        return None
    return {k: bool(row.get(k)) for k in ("pending", "permanent", "confirmed", "active")}


# How long the bootloader may stay silent after the last chunk before the upload is called
# unverifiable. It is not idle in that window: the resource's trailer armed a permanent swap and
# MCUboot carries it out immediately -- 648 KiB moved through the scratch area -- and answers
# nothing until it is done. Measured 2026-09-22 on a UI-driven run: 100 s of silence, then the
# half answered and was running the new image. The ceiling was 90 s, so a flash that had
# succeeded was reported as one that could not be checked. Two earlier runs had simply come in
# under it. A genuinely dead device still fails here, five minutes later instead of one and a
# half; a working one is no longer failed for being busy.
SETTLED_TIMEOUT = 300.0


def _settled_image_state(port: str, side: str | None = None, timeout: float | None = None):
    """Read the slot table AFTER an upload, waiting out the bootloader's post-upload silence.

    Measured on both halves, 2026-09-20: the last chunk is acknowledged and the port then throws
    (`ClearCommError failed`) or times out for tens of seconds while MCUboot acts on the trailer
    the resource just armed. A single read here failed on both of two completely successful
    flashes, which raised UploadRefused and -- far worse -- skipped the reset, leaving the half
    stranded in the bootloader. The device also re-enumerates, so the answering port is looked up
    again rather than assumed. Returns (state, port_that_answered).
    """
    timeout = SETTLED_TIMEOUT if timeout is None else timeout
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while True:
        tried = {port}
        try:
            return rec.image_state(port), port
        except Exception as e:                       # noqa: BLE001 -- retried until the deadline
            last = e
        for d in rec.find_recovery_ports():
            if (side and d.side != side) or d.port in tried:
                continue
            tried.add(d.port)
            try:
                return rec.image_state(d.port), d.port
            except Exception as e:                   # noqa: BLE001 -- retried until the deadline
                last = e
        if time.monotonic() >= deadline:
            raise UploadRefused(
                f"the upload completed but the bootloader did not answer for {timeout:.0f}s "
                f"afterwards ({type(last).__name__ if last else 'no reply'}), so what landed "
                "could not be checked and no reset was sent. The half is still in the bootloader "
                "and can be read or re-uploaded.") from last
        time.sleep(2.0)


def flash(image_path: str | Path, catalog: list, *, arm: str, slot: int = 1,
          chunk: int = DEFAULT_CHUNK, allow_older: bool = False, confirm: bool = False,
          progress=None, state: dict | None = None, slot_info: dict | None = None,
          vendor_trailer: bool = True) -> dict:
    """The whole sequence: upload -> re-read the slot -> schedule the swap -> reset.

    Every upload() interlock applies (it runs first, on one device read shared with the plan).
    Then the slot is re-read and its hash must be the catalogued plaintext hash of the image we
    meant to write.

    Default (vendor_trailer=True): the whole resource went up, trailer included, and that trailer
    scheduled a permanent swap the moment the upload completed (as it does for NayaCore). No
    `image state` write is sent; `confirm` is ignored. A hash mismatch here can only mean a
    corrupt transfer; MCUboot validates the signature before it swaps and refuses a corrupt
    image, and the message says what is armed. This is the path every real flash has taken.

    vendor_trailer=False: only the MCUboot image is uploaded, so at this point nothing is
    scheduled yet; a mismatch means nothing further is sent and the primary is untouched. On a
    match the trailer is written by `image state` with the hash: `confirm=False` = TEST swap
    (boots once, reverts on the next reset unless the application confirms itself; there is no
    later confirm from recovery), `confirm=True` = PERMANENT, which is what NayaCore's resources
    amount to. Better on paper, and never yet run on a board.

    GATED: reached only through the FIRMWARE_FLASH_ENABLED endpoint.
    """
    if state is None:
        state = rec.read_running_image(catalog)      # one read, shared by plan() and upload()
    if slot_info is None:
        slot_info = _live_slot_info(state)
    result = upload(image_path, catalog, arm=arm, slot=slot, chunk=chunk,
                    allow_older=allow_older, progress=progress, state=state, slot_info=slot_info,
                    vendor_trailer=vendor_trailer)
    p = plan(image_path, catalog, slot=slot, chunk=chunk, allow_older=allow_older, state=state,
             slot_info=slot_info, vendor_trailer=vendor_trailer)
    armed = p.arms_on_upload

    want = _hex(p.target.get("plaintextSha256"))
    if len(want) != 64:
        raise UploadRefused(
            f"{p.image_path.name} has no catalogued plaintext hash, so the slot it landed in "
            "cannot be checked. " + ("The resource's own trailer has already scheduled a "
            f"{p.trailer.get('swap')} swap; MCUboot will validate the image before swapping."
            if armed else "Nothing is scheduled; the primary image is untouched."))
    after, read_port = _settled_image_state(p.port, side=(state or {}).get("pidSide"))
    images = after.get("images") or []
    landed = next((i for i in images if i.get("slot") == slot), None)
    got = _hex(landed.get("hash")) if landed else ""
    # A vendor resource arms a PERMANENT swap the instant its trailer lands, and MCUboot can have
    # carried that swap out before this read -- measured on both halves, 2026-09-20: the new image
    # was already in slot 0 with the OLD one moved down to slot 1. Checking only the secondary
    # slot then reads the image we replaced and calls a perfect flash corrupt. The half is still
    # in the bootloader either way, so the reset below is still what boots the new image.
    primary = next((i for i in images if i.get("slot") == 0), None)
    # The signature of a swap that has ALREADY happened is precise: the image we just wrote is in
    # the primary slot AND the one we replaced (the arm token, which is by definition what was
    # running) has been moved down into the secondary. Both halves, and only when the two differ
    # -- flashing the version already installed makes them identical, and then there is nothing
    # to tell apart and the ordinary check below passes anyway.
    swapped = bool(armed and primary is not None and _hex(arm) != want
                   and _hex(primary.get("hash")) == want and got == _hex(arm))
    if not swapped and got != want:
        raise UploadRefused(
            f"after upload, slot {slot} reports {got or 'no image'} but {p.image_path.name} "
            f"should read {want}. " + ("The bytes uploaded include the resource's trailer, so a "
            f"{p.trailer.get('swap')} swap IS scheduled for whatever landed; MCUboot validates "
            "the signature before swapping and refuses a corrupt image. Upload the image again "
            "to replace it." if armed else
            "Nothing is scheduled; the primary image is untouched."))

    if armed and swapped:
        marked = f"{p.trailer.get('swap')} (already carried out by the bootloader)"
    elif armed:
        flags = _slot_flags(after.get("images"), slot)
        if flags is not None and not flags["pending"]:
            raise UploadRefused(
                f"the resource's trailer should have scheduled a swap but the bootloader reports "
                f"slot {slot} not pending ({flags}). Not resetting.")
        marked = f"{p.trailer.get('swap')} (by the resource's own trailer)"
    else:
        reply = rec._talk(read_port, build_set_pending_request(bytes.fromhex(want),
                                                               confirm=confirm, seq=1),
                          timeout=5.0)
        if reply.get("rc", 0):
            raise UploadRefused(
                f"the bootloader refused to schedule slot {slot} (rc={reply['rc']}). Nothing "
                "was reset; the primary image is untouched and nothing is scheduled.")
        # bs_set answers with the updated image list; when it carries state flags, hold it to them.
        flags = _slot_flags(reply.get("images"), slot)
        if flags is not None and not flags["pending"]:
            raise UploadRefused(
                f"the bootloader took the image state write but reports slot {slot} not pending "
                f"({flags}). Not resetting.")
        marked = "permanent" if confirm else "test"
    # The device reboots while answering this, so a short or missing reply is the expected
    # outcome of a reset that worked, not an error to surface.
    # It must go to the port that ANSWERS SMP. Each half in recovery presents two CDC ports and
    # the other one is a log port: it accepts the open, swallows the frame and reports nothing,
    # so a reset addressed there looks sent and does nothing. Sending to the first port in the
    # list is what produced "a power cycle is required" -- on the answering port the half boots
    # into the application in about 8 seconds (measured 2026-09-20, both halves).
    try:
        rec._talk(read_port, build_reset_request(seq=2), timeout=2.0)
    except Exception:      # noqa: BLE001 -- see above
        pass
    result.update({"swap": marked, "hash": want, "reset": True, "trailer": p.trailer,
                   "port": read_port})
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
# must equal the bundle's VERSION. The whole sequence, measured on NayaFlow 2026-09-23, is driven
# by device/module_procedure.py.


def module_range_text(target: dict) -> str:
    """"3.40.0 or newer": the keyboard firmware a bundle needs."""
    r = target.get("keyboardRange") or {}
    return f"{r['from']} or newer" if r.get("from") else "a keyboard firmware we cannot name"


def module_bundle_fits(target: dict, keyboard_version: str | None) -> bool:
    """Can a keyboard on this firmware take this bundle? Only if it is at least as new as the
    first keyboard firmware the bundle shipped with (catalogue `keyboardRange.from`, built from
    the official and beta releases).

    ONE-SIDED, by the owner's rule of 2026-09-23: modules are backward compatible -- every module
    here ran 2.1.2 on 3.41.0 keyboards without trouble -- so an OLDER bundle on a NEWER keyboard
    is fine, and only a bundle newer than the keyboard is refused (2.3.3 first shipped with 3.40.0,
    so a 3.35.4 keyboard cannot take it). The range's upper end (`below`) stays in the catalogue
    as the record of where the next bundle took over, and it is what picks the DEFAULT bundle
    (choose_bundle takes the newest that fits); it no longer refuses anything.
    """
    r = target.get("keyboardRange") or {}
    have, lo = _version_tuple(keyboard_version), _version_tuple(r.get("from"))
    return bool(have and lo and have >= lo)


def require_module_pairing(target: dict, keyboard_version: str | None, catalog: list) -> None:
    """Refuse a module bundle NEWER than the left half's keyboard firmware can take.

    NayaFlow installs 2.3.3 only on an up-to-date Create Left; the first keyboard firmware each
    bundle shipped with is its minimum (module_bundle_fits). Older bundles on newer keyboards are
    allowed -- modules are backward compatible (owner, 2026-09-23). The refusal names what DOES
    fit, because "not this one" alone leaves the user guessing.
    """
    if module_bundle_fits(target, keyboard_version):
        return
    fits = sorted({e.get("moduleFirmware") for e in catalog
                   if e.get("type") == "littlefs" and e.get("flashable")
                   and module_bundle_fits(e, keyboard_version)} - {None},
                  key=lambda v: _version_tuple(v) or ())
    want = target.get("versionLabel") or target.get("moduleFirmware")
    goes = f"module firmware {want} needs keyboard firmware {module_range_text(target)}"
    if not keyboard_version:
        raise UploadRefused(
            f"{goes}, and this left half's firmware version could not be read, so the pairing "
            "cannot be checked. Nothing was written.")
    raise UploadRefused(
        f"{goes}; this left half runs {keyboard_version}. "
        + (f"Module firmware {', '.join(reversed(fits))} works on {keyboard_version}. "
           if fits else f"No module firmware we hold works on {keyboard_version}. ")
        + "Update the keyboard first to use this one. Nothing was written.")

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
                       allow_older: bool = False,
                       allow_unmapped: bool = False) -> ModuleBundlePlan:
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
    _pid_agrees_with_image(state, active)
    if active.get("side") != "left":
        raise UploadRefused(
            f"this is the {active.get('side')} half. The module firmware store is the LEFT "
            "half's: NayaCore uploads the bundle through the left half only.")
    # The running image was identified by its hash against the catalogue, so its version here is
    # the catalogue's, not a number the device could misreport.
    require_module_pairing(target, active.get("createFirmware"), catalog)

    have, want = _version_tuple(installed_version), _version_tuple(target.get("moduleFirmware"))
    if have and want and want < have and not allow_older:
        raise UploadRefused(
            f"module firmware {target.get('moduleFirmware')} is older than the "
            f"{installed_version} this keyboard holds. Pass allow_older=True to say you meant it.")

    if slot_info is None:
        slot_info = state.get("slotInfo")
    image_id, slot = modules_slot(slot_info, len(raw), allow_unmapped=allow_unmapped)
    return ModuleBundlePlan(
        image_path=path, total_bytes=len(raw), chunks=max(1, -(-len(raw) // chunk)),
        image_sha256=hashlib.sha256(raw).hexdigest(), upload_image_id=image_id, slot=slot,
        running=active, target=target, port=state.get("port", ""),
        arm_token=active.get("hash") or "",
    )


def flash_module_bundle(image_path: str | Path, catalog: list, *, arm: str,
                        chunk: int = DEFAULT_CHUNK, installed_version: str | None = None,
                        allow_older: bool = False, progress=None, state: dict | None = None,
                        slot_info: dict | None = None, allow_unmapped: bool = False,
                        link=None) -> dict:
    """Upload a module bundle into the modules slot of the left half. The verification is NOT
    here: it is the app-mode MODULE_FILE_FW_VERSION read after the half is back, which the result
    spells out, followed by MODULE_FWUP with a module docked (device/module_procedure.py).

    No mark-pending: the bundle is a filesystem, MCUboot has nothing to swap. Interrupting the
    upload leaves the modules partition partly erased and the KEYBOARD firmware untouched -- the
    keyboard keeps working, module programming does not until a bundle is uploaded again.

    NO RESET AFTERWARDS, and that is the vendor's shape, not an omission. NayaCore sends nothing
    after the last chunk: the half restarts on its own about a second later (captured 2026-09-23,
    NayaFlow 1.25.1, device/out/module-fw-touch1-20260923.pcap). A reset sent into that restart
    goes to a port that is already closing. A half that does stay in the bootloader is reset by
    the procedure's wait, which only ever resets a half it can see still sitting there.

    GATED: reached only through the FIRMWARE_FLASH_ENABLED endpoints. The upload shape matches the
    vendor's capture; this function itself has not yet run on hardware.
    """
    if state is None:
        state = rec.read_running_image(catalog)
    if slot_info is None:
        slot_info = _live_slot_info(state)
    p = plan_module_bundle(image_path, catalog, chunk=chunk, state=state, slot_info=slot_info,
                           installed_version=installed_version, allow_older=allow_older,
                           allow_unmapped=allow_unmapped)
    if arm != p.arm_token:
        raise UploadRefused(
            "not armed. Pass arm= the hash this half reports for its running image "
            f"({p.arm_token or 'unavailable'}); it is printed by the plan.")
    raw = p.image_path.read_bytes()
    if not 0 < chunk <= MAX_CHUNK:
        raise UploadRefused(f"chunk must be 1 to {MAX_CHUNK} bytes, not {chunk}")
    sent = _send_chunks(p.port, p.upload_image_id, raw, chunk=chunk, progress=progress,
                        untouched="the keyboard firmware is untouched, the modules partition is "
                                  "partly written", link=link)
    if sent < len(raw):
        raise UploadRefused(
            f"the bootloader acknowledged {sent} of {len(raw)} bytes and stopped. Not resetting; "
            "upload the bundle again.")
    return {"ok": True, "written": sent, "uploadImageId": p.upload_image_id,
            "slot": p.slot, "image": p.image_path.name, "port": p.port, "reset": False,
            "target": p.expected_version,
            "verifyNext": {"read": "MODULE_FILE_FW_VERSION", "expect": p.expected_version,
                           "then": "module_fwup with the docked module's type, then "
                                   "GET_MODULE_FW_VERSION should report the same version"}}
