"""Decode the SPIFLASH_TEST (0xFA/0x1001) self-test response.

`DeviceService.spi_flash_test` has always returned `{"ok", "side", "raw"}` -- the bytes and
nothing else. NayaCore decodes the same bytes into a per-partition diagnosis, and the string
table gives us its exact output format, which is what pins the layout:

    %1 Partition (%2): Status=%3 (%4), Open RC=0x%5 (%6), Mount RC=0x%7 (%8),
                       File Open RC=0x%9 (%10), File Read RC=0x%11 (%12), File Write RC=0x%13 (%14)

That is one status plus FIVE return codes per partition, in that order -- six bytes -- and
6 divides both known response lengths exactly:

    32 bytes = 2 + 5 x 6      (CreateLeft / Dongle, five partitions)
    20 bytes = 2 + 3 x 6      (CreateRight, three partitions)

Supporting strings, all from extracted/NayaFlow-1.25.1/strings/core-strings.txt:
  * status enum 0-4, in order (5859-5863): Not Detected, Detected, Formatted, Mounted, Erased
  * return codes are SIGNED (5852-5855): LFS_ERR_CORRUPT (-84), EINVAL (-22), Generic Error (-1),
    Success (0), and an "Error (%1)" fallback for anything else
  * "Invalid data length received. Expected %1 bytes, got %2 bytes" and "Unknown device type for
    SPIFLASH_TEST" -- the expected length is chosen by device type, so a length we do not
    recognise must be refused rather than parsed as far as it goes
  * "Slot1 Partition (Secondary Image - RAW): Status=%1 (%2)" -- the MCUboot secondary slot is
    reported with a status and NO return codes, which is very likely one of the two leading bytes

WHAT IS DELIBERATELY NOT DECODED. Two things, and both would be guesses:

  * THE TWO LEADING BYTES. Their order and meaning are unpinned -- the candidates are the Slot1
    status and a partition count or device type. Reported as `headerUnknown`.
  * PARTITION NAMES. The vendor's contiguous name list is `Battery, USB_Qi, Layout, Setting,
    Reserve, M_Firmware` (core-strings.txt:5259-5264) -- SIX names for a five- or three-partition
    response, with no evidence of which are used or in what order. Partitions are therefore
    reported by index. (An earlier note in this project claimed the set was
    "Layout/Log/Reserve/Setting/M_Firmware"; there is no "Log" string in the binary at all, which
    is a good illustration of why the names are not being asserted here.)

STATUS: NOT YET VALIDATED AGAINST A DEVICE. Unlike ble_status.py, there is no captured response
on disk to check this against, so nothing here is cross-validated -- the structure follows from
the format string and the two lengths, but the byte ORDER within a partition is inferred from
the order NayaCore prints them in. One live capture settles the leading bytes and confirms the
ordering. Until then `decode` keeps `raw` and every caller should show it.

This module is DIAGNOSIS ONLY. FORMAT_PARTITION stays refused in commands.py: the destructive
repair is the dangerous half and the useful half carries no risk. No hardware.
"""
from __future__ import annotations

# Response length -> number of LittleFS partitions described. Anything else is refused, following
# NayaCore's own "Invalid data length received" behaviour rather than parsing what fits.
LAYOUTS = {32: 5, 20: 3}
_HEADER = 2
_PARTITION_SIZE = 6

STATUS_NAMES = {
    0: "Not Detected",
    1: "Detected",
    2: "Formatted",
    3: "Mounted",
    4: "Erased",
}

# Named return codes. Signed, so they are read as int8.
RC_NAMES = {
    0: "Success",
    -1: "Generic Error",
    -22: "EINVAL",
    -84: "LFS_ERR_CORRUPT",
}

# The order NayaCore prints them, which is the order they are assumed to sit in.
RC_FIELDS = ("open", "mount", "fileOpen", "fileRead", "fileWrite")

# A mounted filesystem is the healthy resting state; the others are all reportable.
HEALTHY_STATUS = 3


def _rc(value: int) -> dict:
    return {"value": value, "name": RC_NAMES.get(value, f"Error ({value})"), "ok": value == 0}


def decode(raw) -> dict:
    """The SPIFLASH_TEST payload -> a per-partition diagnosis. Never raises."""
    if isinstance(raw, str):
        try:
            raw = bytes.fromhex(raw)
        except ValueError:
            return {"length": 0, "layout": None, "note": "response is not hex"}
    raw = bytes(raw or b"")
    if not raw:
        return {"length": 0, "layout": None, "note": "the half returned no flash self-test"}

    count = LAYOUTS.get(len(raw))
    if count is None:
        return {"length": len(raw), "layout": None, "raw": raw.hex(),
                "note": f"unrecognised SPI flash test layout ({len(raw)} bytes; known lengths "
                        f"are {', '.join(str(n) for n in sorted(LAYOUTS))}); reported raw"}

    out: dict = {
        "length": len(raw),
        "layout": f"{len(raw)}-byte",
        "partitionCount": count,
        "raw": raw.hex(),
        # See the module docstring: order and meaning unpinned, so it stays raw.
        "headerUnknown": raw[:_HEADER].hex(),
        "validated": False,
    }

    partitions = []
    for i in range(count):
        off = _HEADER + i * _PARTITION_SIZE
        blk = raw[off:off + _PARTITION_SIZE]
        status = blk[0]
        codes = {name: _rc(int.from_bytes(blk[1 + n:2 + n], "big", signed=True))
                 for n, name in enumerate(RC_FIELDS)}
        failing = sorted(k for k, v in codes.items() if not v["ok"])
        partitions.append({
            "index": i,
            "status": status,
            "statusName": STATUS_NAMES.get(status, f"Unknown (0x{status:02x})"),
            "returnCodes": codes,
            # NayaCore's rule: a partition is in error when any return code is non-zero. Status is
            # reported separately because "Not Detected" with clean return codes is a different
            # problem from a mounted partition that cannot be read.
            "errored": bool(failing),
            "failingOperations": failing,
            "mounted": status == HEALTHY_STATUS,
            "raw": blk.hex(),
        })

    out["partitions"] = partitions
    out["errored"] = any(p["errored"] for p in partitions)
    out["erroredPartitions"] = [p["index"] for p in partitions if p["errored"]]
    return out


def summary(decoded: dict) -> dict:
    """A one-line verdict for the Information page."""
    if not decoded or not decoded.get("layout"):
        return {"state": "unknown", "detail": (decoded or {}).get("note")}

    parts = decoded.get("partitions") or []
    bad = [p for p in parts if p["errored"]]
    if bad:
        which = ", ".join(f"#{p['index']} ({p['statusName']}: {', '.join(p['failingOperations'])})"
                          for p in bad)
        return {"state": "errors", "detail": f"{len(bad)} of {len(parts)} partitions report "
                                             f"errors: {which}."}

    unmounted = [p for p in parts if not p["mounted"]]
    if unmounted:
        which = ", ".join(f"#{p['index']} ({p['statusName']})" for p in unmounted)
        return {"state": "not-mounted",
                "detail": f"No errors, but {len(unmounted)} of {len(parts)} partitions are not "
                          f"mounted: {which}."}

    return {"state": "ok",
            "detail": f"All {len(parts)} partitions mounted with no errors."}
