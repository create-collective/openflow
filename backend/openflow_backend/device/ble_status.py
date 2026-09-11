"""Decode the BLE_GET_STATUS blob.

`service._query_half` has always sent BLE_GET_STATUS and stored the answer as `statusRaw` hex,
with a comment saying we had no capture telling us what the bytes meant. We do now.

WHERE THE LAYOUT COMES FROM. NayaCore's string table (extracted/NayaFlow-1.25.1/strings/
core-strings.txt:5380-5417) carries the field names of the JSON it builds, in construction
order. That gives names but not offsets, so every offset below is pinned against the two real
239-byte captures in device/out/ rather than assumed from the name order -- the name list has
more entries than the header has bytes, so reading it as a straight sequence WOULD BE WRONG.

WHAT IS ACTUALLY CONFIRMED, and why each one is not a guess:

  * The 15 / 5x37 / 39 split is self-validating: each profile block begins with its own index,
    and they read 0,1,2,3,4 in order. A wrong stride would not produce that.
  * `profileCount` = 5 and there are exactly 5 profile blocks.
  * `activeProfile` = 2 and profile 2 is the ONLY block that differs from the other four.
  * `localAddress` is cross-checked against an independent command: the LEFT half's status
    reports C5:F4:36:95:3D:3B, which is exactly what the RIGHT half answers to
    BLE_GET_PAIR_ADDRESS. The split-link `peerAddress` mirrors it -- F3:69:F2:DE:F6:9C, which is
    what the LEFT answers to the same command. Each half's own address is the other's pair
    address, which is what a working split link should look like.
  * Big-endian, and the three timing fields, are settled together: read big-endian they are
    interval 6 (7.5 ms), latency 0, timeout 400 (4000 ms) -- all textbook-valid BLE values.
    Little-endian gives 1536, 0 and 36865, which are not.

WHAT IS NOT CONFIRMED stays raw and is reported that way. Three header bytes and most of the
split-link block have no discriminating variation across the two captures, and every profile is
unbonded (all zero past the flags byte), so there is nothing to solve them against. Naming them
from the string order alone is exactly the mistake that made 0x08 "LAYER_SW" for months.

DO NOT VALIDATE THIS AGAINST NAYACORE'S DISPLAY. An earlier read of its parser suggested it has
its own indexing bugs (per-profile fields read at absolute rather than block-relative offsets,
and a signed-byte assembly that corrupts wide fields). That is unverified and deliberately not
relied on here, but it does mean "NayaCore shows the same number" is not evidence of a correct
decode. The device's own answers are.

`statusRaw` MUST stay in the payload alongside this, so a wrong decode can always be checked
against the bytes. No hardware.
"""
from __future__ import annotations

LAYOUT_LENGTH = 239
_HEADER, _PROFILE_SIZE, _PROFILE_COUNT = 15, 37, 5
_PROFILES_AT = _HEADER
_SPLIT_AT = _HEADER + _PROFILE_SIZE * _PROFILE_COUNT       # 200

# Per-field confidence, using the same vocabulary as the settings provenance badges so the UI can
# render it without a second scheme. VERIFIED = cross-checked against something independent.
PROVENANCE = {
    "profileCount":         "VERIFIED",
    "activeProfile":        "VERIFIED",
    "localAddress":         "VERIFIED",
    "profileIndex":         "VERIFIED",
    "peerAddress":          "VERIFIED",
    "connectionIntervalMs": "VERIFIED",
    "connectionLatency":    "VERIFIED",
    "supervisionTimeoutMs": "VERIFIED",
    # Named from NayaCore's string table, consistent with both captures, but nothing independent
    # pins them. `revision` behaves like a counter that resets on a power cycle (78703 before a
    # reboot, 14 after) rather than a firmware revision, so the vendor's name may itself mislead.
    "revision":             "EXPERIMENTAL",
    "activeFlags":          "EXPERIMENTAL",
    # 2026-09-11, the first capture with a host bonded (device/out/ble-status-paired-20260911.txt):
    # the bonded slot's flags byte went 0x08 -> 0x7f and header byte 6 went 0x04 -> 0x06 while
    # everything else held. `active` (0x08) was already pinned by activeProfile; `hostConnected`
    # (header 0x02) is pinned by that capture; the other six profile bits all flipped together,
    # so their individual names follow NayaCore's own parser (as nayactl carries it) and stay
    # EXPERIMENTAL until a bonded-but-disconnected capture separates them.
    "hostConnected":        "VERIFIED",
    "flags.active":         "VERIFIED",
    "flags.bonded":         "EXPERIMENTAL",
    "flags.connected":      "EXPERIMENTAL",
    "peerAddress(profile)": "VERIFIED",
}

# Profile flags byte, bit by bit. Names from NayaCore's parser; see the confidence table.
PROFILE_FLAG_BITS = {
    "configured": 0x01, "bonded": 0x02, "connected": 0x04, "active": 0x08,
    "hasPeerAddr": 0x10, "encrypted": 0x20, "authenticated": 0x40,
}


def _mac(b: bytes) -> str:
    return ":".join(f"{x:02X}" for x in b)


def decode(raw) -> dict:
    """statusRaw (hex str or bytes) -> a decoded view, or a raw one if the layout is unfamiliar.

    Never raises: this sits on a diagnostics page, and a half that answers oddly must still render.
    """
    if isinstance(raw, str):
        try:
            raw = bytes.fromhex(raw)
        except ValueError:
            return {"length": 0, "layout": None, "note": "statusRaw is not hex"}
    raw = bytes(raw or b"")
    if not raw:
        return {"length": 0, "layout": None, "note": "the half returned no BLE status"}
    if len(raw) != LAYOUT_LENGTH:
        # Firmware changed the struct, or this is a different device. Do not guess at a layout we
        # have never seen -- say so and hand back the bytes.
        return {"length": len(raw), "layout": None, "raw": raw.hex(),
                "note": f"unrecognised BLE status layout ({len(raw)} bytes, expected "
                        f"{LAYOUT_LENGTH}); reported raw"}

    out: dict = {"length": len(raw), "layout": f"{LAYOUT_LENGTH}-byte", "raw": raw.hex()}

    # --- header ------------------------------------------------------------------------- #
    out["revision"] = int.from_bytes(raw[0:4], "big")
    out["profileCount"] = raw[4]
    out["activeProfile"] = raw[5]
    # Byte 6 is a bitfield: 0x04 on every capture without a host, 0x06 once a host was bonded and
    # connected (2026-09-11) -- so bit 1 is hostConnected, bit 2 the local-address-valid flag that
    # is always set, and bit 0 (advertising, per NayaCore) has not yet been seen set. Bytes 7-8
    # (02 01 on every capture) stay raw.
    out["advertising"] = bool(raw[6] & 0x01)
    out["hostConnected"] = bool(raw[6] & 0x02)
    out["localAddrValid"] = bool(raw[6] & 0x04)
    out["headerUnknown"] = raw[6:9].hex()
    out["localAddress"] = _mac(raw[9:15])

    # --- profiles ----------------------------------------------------------------------- #
    profiles = []
    for i in range(_PROFILE_COUNT):
        off = _PROFILES_AT + i * _PROFILE_SIZE
        blk = raw[off:off + _PROFILE_SIZE]
        profiles.append({
            "index": blk[0],
            "activeFlags": blk[1],
            "isActive": blk[0] == out["activeProfile"],
            # Every profile on the reference board is unbonded, so `configured`, `bonded`,
            # `hasPeerAddr`, `securityLevel` and the rest have no variation to be solved
            # against. Report whether there is ANY content rather than inventing bit meanings.
            #
            # From byte 5, NOT byte 2: bytes 2-4 read `00 01 02` in all five profiles of both
            # captures, so they are a constant prefix (static capability, most likely) and cannot
            # indicate per-profile state. Including them made every profile look populated.
            "hasPeerData": any(blk[5:]),
            # The bits, now that a bond has been seen to set them (0x7f on the bonded, connected,
            # active slot; 0x08 on an active unbonded one; 0x00 on the rest).
            "flags": {name: bool(blk[1] & bit) for name, bit in PROFILE_FLAG_BITS.items()},
            "bonded": bool(blk[1] & PROFILE_FLAG_BITS["bonded"]),
            "connected": bool(blk[1] & PROFILE_FLAG_BITS["connected"]),
            "securityLevel": blk[2],
            # The host's address, at +6, as NayaCore reads it: 4C:82:A9:7F:44:24 on the bonded
            # capture, the owner's PC adapter. Zero and reported as None when no peer is stored.
            "peerAddress": _mac(blk[6:12]) if blk[1] & PROFILE_FLAG_BITS["hasPeerAddr"] else None,
            "raw": blk.hex(),
        })
    out["profiles"] = profiles
    out["bondedProfileCount"] = sum(1 for p in profiles if p["hasPeerData"])

    # --- split link (this half <-> the other half) ---------------------------------------- #
    d = raw[_SPLIT_AT:]
    interval = int.from_bytes(d[10:12], "big")
    out["splitLink"] = {
        "peerAddress": _mac(d[4:10]),
        # BLE units: interval is 1.25 ms, supervision timeout is 10 ms.
        "connectionIntervalMs": round(interval * 1.25, 2),
        "connectionLatency": int.from_bytes(d[12:14], "big"),
        "supervisionTimeoutMs": int.from_bytes(d[14:16], "big") * 10,
        "leadingUnknown": d[0:4].hex(),
        "trailingUnknown": d[16:].hex(),
        "raw": d.hex(),
    }
    return out


def link_summary(decoded: dict, expected_peer_address: str | None = None) -> dict:
    """A plain-language verdict for the Information page.

    This is the check that actually matters for the "my right half stopped working" reports: it
    distinguishes a half linked to its partner from one linked to nothing, or -- the case nobody
    can currently diagnose -- linked to the WRONG partner.

    MIND WHICH ADDRESS YOU PASS. A half's `pairAddress` (BLE_GET_PAIR_ADDRESS) is the address of
    its PEER, while `localAddress` in its own status blob is its OWN. So the left half reports
    pairAddress F3:69:... and localAddress C5:F4:..., and the right half reports the two the
    other way round. Passing the partner's pairAddress here compares the peer against ourselves
    and reports a mismatch on a perfectly healthy keyboard -- which is exactly what the first
    version of this function did.

    `expected_peer_address` should therefore be, in order of preference:
      1. the PARTNER half's `localAddress` from its own decoded status -- fully independent, and
         the only form that can catch a half bonded to some other keyboard;
      2. failing that (a half that will not answer BLE_GET_STATUS returns an empty blob, as the
         right half does today), THIS half's own `pairAddress`. Same device, so it is a weaker
         check, but it still catches a split link pointing at nothing.
    """
    if not decoded or not decoded.get("layout"):
        return {"state": "unknown", "detail": (decoded or {}).get("note")}

    link = decoded.get("splitLink") or {}
    peer = link.get("peerAddress")
    if not peer or peer == "00:00:00:00:00:00":
        return {"state": "no-peer",
                "detail": "This half has no split-link partner address stored."}

    if expected_peer_address:
        want = expected_peer_address.upper()
        if peer.upper() != want:
            return {"state": "mismatched", "peerAddress": peer, "expected": want,
                    "detail": f"This half is linked to {peer}, but {want} was expected."}

    return {
        "state": "linked",
        "peerAddress": peer,
        "detail": (f"Linked at {link.get('connectionIntervalMs')} ms intervals, "
                   f"{link.get('supervisionTimeoutMs')} ms supervision timeout."),
    }
