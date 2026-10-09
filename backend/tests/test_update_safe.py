"""The shell asks /api/update-safe before closing OpenFlow to install an update of itself.

Quitting ends the backend, and a keyboard or module flash cut off that way can leave a half that
will not boot. Both kinds of flash run through flash_runs, so its flag is the whole answer.
"""
import asyncio

from openflow_backend.api import rest
from openflow_backend.device import flash_runs


def ask():
    return asyncio.run(rest.update_safe())


def test_safe_when_nothing_is_flashing(monkeypatch):
    monkeypatch.setattr(flash_runs, "_active", False)
    assert ask() == {"safe": True, "reason": None}


def test_not_safe_while_a_flash_runs(monkeypatch):
    monkeypatch.setattr(flash_runs, "_active", True)
    answer = ask()
    assert answer["safe"] is False
    assert "flash" in answer["reason"]
