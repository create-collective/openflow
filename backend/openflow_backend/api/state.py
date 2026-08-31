"""Process-wide singletons shared across routers."""

from __future__ import annotations

from ..device.service import DeviceService

_service: DeviceService | None = None


def get_service() -> DeviceService:
    global _service
    if _service is None:
        _service = DeviceService()
    return _service


def shutdown_service() -> None:
    global _service
    if _service is not None:
        _service.shutdown()
        _service = None
