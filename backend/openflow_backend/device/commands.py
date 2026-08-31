"""Maps NayaFlow's recovered ZMQ `command` events onto CDC operations.

The original renderer's only device-control path was:
    POST /rpc/send-nayacore-zmq-message  { messages: [topic, event, ...frames] }
with these events observed in the 1.25.1 renderer:
    update_create_fw, create_pairing_start, update_module_fw,
    clear_data, repair_flash, clear_ble_devices

We keep the same event names so the rebuilt renderer keeps the same call shape,
but dispatch them to the vendored nayactl protocol instead of NayaCore + ZMQ.
"""

from __future__ import annotations

from .service import DeviceService


class CommandError(Exception):
    pass


def dispatch(svc: DeviceService, event: str, frames: list, *, side: str = "left", force: bool = False) -> dict:
    if event == "repair_flash":
        # Phase 1: expose the read-only self-test. The destructive repair
        # (FORMAT_PARTITION/ERASE_CHIP) is gated behind an explicit force flow
        # because it can wipe staged firmware + on-device keymaps.
        if not force:
            return {"event": event, "status": "test-only", **svc.spi_flash_test(side)}
        raise CommandError("Destructive flash repair not yet wired (needs force + confirm flow)")

    if event == "clear_ble_devices":
        return {"event": event, **svc.clear_ble_devices(side, force=force)}

    if event == "clear_data":
        # REMAP CLEAR ALL DATA — Phase 2 (destructive keymap wipe).
        raise CommandError("clear_data (REMAP CLEAR_ALL_DATA) is Phase 2 work")

    if event == "create_pairing_start":
        raise CommandError("create_pairing_start (pairing workflow) is Phase 2 work")

    if event in ("update_create_fw", "update_module_fw"):
        # Phase 3 — blocked on obtaining a firmware image (NayaOS open problem).
        raise CommandError(f"{event} (firmware update) is blocked until a firmware image is obtained")

    raise CommandError(f"unknown command event: {event}")
