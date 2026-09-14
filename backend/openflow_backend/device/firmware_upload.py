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

    def describe(self) -> str:
        t, r = self.target, self.running
        return (f"{self.image_path.name} -> slot {self.slot} on {self.port}\n"
                f"  running : {r.get('file')} ({r.get('side')}/gen {r.get('generation')}, "
                f"fw {r.get('createFirmware')})\n"
                f"  writing : {t.get('file')} ({t.get('side')}/gen {t.get('generation')}, "
                f"fw {t.get('createFirmware')})\n"
                f"  {self.total_bytes} bytes in {self.chunks} chunks\n"
                f"  arm token: {self.arm_token}")


def _version_tuple(v):
    try:
        return tuple(int(x) for x in str(v).split("."))
    except (TypeError, ValueError):
        return ()


def plan(image_path: str | Path, catalog: list, *, slot: int = 1,
         chunk: int = DEFAULT_CHUNK, allow_older: bool = False,
         state: dict | None = None) -> UploadPlan:
    """Run every interlock and return what an upload would do. Writes nothing.

    `state` is a recovery.read_running_image() result; it is read from the device when omitted.
    Raises UploadRefused with a reason a user can act on.
    """
    path = Path(image_path)
    if not path.is_file():
        raise UploadRefused(f"no such image: {path}")

    target = next((e for e in catalog or [] if e.get("file") == path.name), None)
    if target is None:
        raise UploadRefused(
            f"{path.name} is not in the firmware catalogue. Only catalogued images may be "
            "written, because the catalogue is what says which side and flash generation an "
            "image is for.")
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

    have, want = _version_tuple(active.get("createFirmware")), _version_tuple(target.get("createFirmware"))
    if have and want and want < have and not allow_older:
        raise UploadRefused(
            f"{target.get('createFirmware')} is older than the {active.get('createFirmware')} "
            "this half runs. Downgrading is a legitimate repair — it is how two halves that no "
            "longer talk to each other are brought back to a common version — so pass "
            "allow_older=True to say you meant it.")

    raw = path.read_bytes()
    return UploadPlan(
        image_path=path, slot=slot, total_bytes=len(raw),
        chunks=max(1, -(-len(raw) // chunk)),
        image_sha256=hashlib.sha256(raw).hexdigest(),
        running=active, target=target, port=state.get("port", ""),
        # The arming token is the DEVICE's own reported hash. A caller cannot arm this in
        # advance, or reuse an arming decision made about a different half.
        arm_token=active.get("hash") or "",
    )


def build_chunk_request(slot: int, offset: int, data: bytes, *, total: int | None = None,
                        sha: bytes | None = None, seq: int = 0) -> bytes:
    """One `image upload` frame. Pure; builds bytes and sends nothing.

    The first chunk carries the total length and the image hash; later chunks carry only their
    offset, which is how the bootloader tracks progress and how a resumed upload finds its place.
    """
    body: dict = {"image": slot, "off": offset, "data": data}
    if offset == 0:
        if total is None or sha is None:
            raise ValueError("the first chunk must carry the total length and the image hash")
        body["len"] = total
        body["sha"] = sha
    payload = _cbor_encode(body)
    return rec.encode_request(SMP_OP_WRITE, rec.SMP_GROUP_IMAGE, SMP_ID_IMAGE_UPLOAD,
                              payload=payload, seq=seq)


def upload(image_path: str | Path, catalog: list, *, arm: str, slot: int = 1,
           chunk: int = DEFAULT_CHUNK, allow_older: bool = False, progress=None,
           state: dict | None = None) -> dict:
    """Write an image to a half in recovery. Called only by flash(); on its own it leaves an
    image in the secondary slot that never boots.

    `arm` must equal the hash the device reports for its running image -- see plan().arm_token.
    That is deliberately not a boolean: an arming flag can be left switched on, and a token tied
    to one device's current state cannot be reused on the next one by accident.

    Never run against hardware. The read path it sits on is proven; this request shape is not.
    """
    p = plan(image_path, catalog, slot=slot, chunk=chunk, allow_older=allow_older,
             state=state)
    if arm != p.arm_token:
        raise UploadRefused(
            "not armed. Pass arm= the hash this half reports for its running image "
            f"({p.arm_token or 'unavailable'}); it is printed by the plan.")

    raw = Path(image_path).read_bytes()
    sha = hashlib.sha256(raw).digest()
    sent, seq = 0, 0
    while sent < len(raw):
        piece = raw[sent:sent + chunk]
        frame = build_chunk_request(slot, sent, piece,
                                    total=len(raw) if sent == 0 else None,
                                    sha=sha if sent == 0 else None, seq=seq & 0xFF)
        reply = rec._talk(p.port, frame, timeout=5.0)
        rc = reply.get("rc", 0)
        if rc:
            raise UploadRefused(f"the bootloader rejected the chunk at offset {sent} (rc={rc}). "
                                "Nothing further is sent; the primary image is untouched.")
        # The device says where it wants the next byte. Trusting our own counter instead is how
        # an upload silently writes a corrupt image after one dropped frame.
        sent = reply.get("off", sent + len(piece))
        seq += 1
        if progress:
            progress(sent, len(raw))
    return {"ok": True, "written": sent, "slot": slot, "image": Path(image_path).name,
            "port": p.port}


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


def flash(image_path: str | Path, catalog: list, *, arm: str, slot: int = 1,
          chunk: int = DEFAULT_CHUNK, allow_older: bool = False, confirm: bool = False,
          progress=None, state: dict | None = None) -> dict:
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
    result = upload(image_path, catalog, arm=arm, slot=slot, chunk=chunk,
                    allow_older=allow_older, progress=progress, state=state)
    p = plan(image_path, catalog, slot=slot, chunk=chunk, allow_older=allow_older, state=state)

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
