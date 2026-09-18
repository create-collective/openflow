"""The in-app report: what it strips, what it renders, and that it never needs a sink to work.

The rule being pinned is that NO credential ships with OpenFlow: with nothing configured the
report must still come back rendered, so the app can offer it to be copied. The other rule is
that identifiers (hardware IDs, BLE addresses, serial numbers) leave only when asked for.
No hardware, no network.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / "openflow_backend" / "_vendor"))

from openflow_backend import report  # noqa: E402

# Cleared before every test: on a machine that is actually configured for reporting, these
# would otherwise leak in and the no-sink cases would pass for the wrong reason.
_ENV = ("OPENFLOW_JIRA_EMAIL", "OPENFLOW_JIRA_TOKEN", "OPENFLOW_JIRA_URL",
        "OPENFLOW_JIRA_PROJECT", "OPENFLOW_JIRA_PARENT", "OPENFLOW_JIRA_SPRINT",
        "OPENFLOW_JIRA_WEBHOOK")


class _Svc:
    def list_devices(self):
        return [{"port": "COM6", "serialNumber": "B1C99009C51D9403", "description": "Create Left"}]


def _clean(monkeypatch, tmp_path):
    for key in _ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENFLOW_DATA_DIR", str(tmp_path))


def test_redact_removes_identifiers_and_keeps_the_rest():
    got = report.redact({
        "hardwareId": "B1C99009C51D9403",
        "bleAddress": "C5:F4:36:95:3D:3B",
        "serialNumber": "0123",
        "instance": "abc",
        "firmwareVersion": "3.41.0",
        "port": "COM6",
        "module": {"type": "Tune", "uuid": "6451", "batteryPercent": 98},
        "halves": [{"pairAddress": "F3:69", "connected": True}],
    })
    for gone in ("hardwareId", "bleAddress", "serialNumber", "instance"):
        assert got[gone] == "(removed)", f"{gone} survived redaction"
    assert got["module"]["uuid"] == "(removed)"
    assert got["halves"][0]["pairAddress"] == "(removed)"
    # Everything that is not an identifier is untouched, including inside the nesting.
    assert got["firmwareVersion"] == "3.41.0" and got["port"] == "COM6"
    assert got["module"] == {"type": "Tune", "uuid": "(removed)", "batteryPercent": 98}
    assert got["halves"][0]["connected"] is True
    print("  identifiers removed at every depth; other fields untouched")


def test_empty_values_are_left_alone():
    """A missing address is already telling nothing; marking it '(removed)' would read as if
    something had been hidden."""
    got = report.redact({"bleAddress": None, "hardwareId": "", "uuids": []})
    assert got == {"bleAddress": None, "hardwareId": "", "uuids": []}
    print("  empty identifier fields are not marked as removed")


def test_render_carries_the_users_words_and_the_environment():
    ctx = report.collect_context(_Svc(), [], {"halves": [
        {"description": "Create Left", "connected": True, "firmwareVersion": "3.41.0",
         "port": "COM6", "module": {"type": "Tune", "firmwareVersion": "2.3.3"}},
    ]})
    text = report.render({"title": "Flash fails", "happened": "it went bang",
                          "expected": "no bang", "steps": "1. press flash",
                          "page": "/layer-management"}, ctx)
    for fragment in ("it went bang", "no bang", "1. press flash", "/layer-management",
                     "Create Left", "fw 3.41.0", "module Tune"):
        assert fragment in text, f"missing from the report: {fragment}"
    print("  report carries the user's text, the page and the halves")


def test_no_credentials_means_no_sink_but_still_a_report(monkeypatch, tmp_path):
    _clean(monkeypatch, tmp_path)
    assert report.jira_config() is None, "a build with no credentials must have no sink"
    out = report.file_report(_Svc(), {"title": "x", "happened": "y"}, {"app": {"version": "0.1.0"}})
    assert out["ok"] is False and out["configured"] is False and out["reason"] == "no-sink"
    assert "y" in out["description"] and out["summary"] == "x"
    print("  no credentials: no sink, and the rendered report still comes back")


def test_credentials_are_read_from_the_environment_and_never_from_the_repo(monkeypatch, tmp_path):
    _clean(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENFLOW_JIRA_EMAIL", "someone@example.com")
    monkeypatch.setenv("OPENFLOW_JIRA_TOKEN", "not-a-real-token")
    cfg = report.jira_config()
    assert cfg is not None
    assert cfg["email"] == "someone@example.com" and cfg["token"] == "not-a-real-token"
    # The non-secret half has defaults so a configured machine needs only the two secrets.
    assert cfg["project"] == "SCRUM" and cfg["parent"] == "SCRUM-79" and cfg["sprint"] == 9
    print("  the two secrets come from the environment; the queue has defaults")


def test_a_title_is_never_empty_and_never_multiline():
    out = report.file_report(_Svc(), {"title": "  a\n b  ", "happened": "z"}, {"app": {}})
    assert out["summary"] == "a b"
    out = report.file_report(_Svc(), {"title": "   ", "happened": "z"}, {"app": {}})
    assert out["summary"] == "OpenFlow report (no title given)"
    print("  the summary is always one line and never blank")


def test_a_webhook_alone_is_a_sink_and_is_preferred_over_a_token(monkeypatch, tmp_path):
    """The webhook can only create, so a machine with one never reaches for the account token."""
    _clean(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENFLOW_JIRA_WEBHOOK", "https://automation.atlassian.com/pro/hooks/abc")
    cfg = report.jira_config()
    assert cfg is not None and cfg["webhook"].endswith("/abc")

    sent = {}
    def fake_hook(url, summary, description, form):
        sent.update(url=url, summary=summary, description=description, form=form)
        return {"status": 200}
    def fail(*a, **k):
        raise AssertionError("the account token path must not run when a webhook is configured")
    monkeypatch.setattr(report, "submit_to_webhook", fake_hook)
    monkeypatch.setattr(report, "submit_to_jira", fail)

    monkeypatch.setenv("OPENFLOW_JIRA_EMAIL", "someone@example.com")
    monkeypatch.setenv("OPENFLOW_JIRA_TOKEN", "not-a-real-token")
    out = report.file_report(_Svc(), {"title": "t", "happened": "h", "page": "/macro"},
                             {"app": {"version": "0.1.0"}})
    assert out["ok"] is True and out["sink"] == "webhook"
    # Automation answers before its rule runs, so there is no key to claim.
    assert out["key"] is None and out["url"] is None
    assert sent["summary"] == "t" and "h" in sent["description"] and sent["form"]["page"] == "/macro"
    print("  a webhook wins over a token, and no issue key is invented")


def test_a_failing_webhook_still_hands_the_report_back(monkeypatch, tmp_path):
    _clean(monkeypatch, tmp_path)
    monkeypatch.setenv("OPENFLOW_JIRA_WEBHOOK", "https://automation.atlassian.com/pro/hooks/abc")
    monkeypatch.setattr(report, "submit_to_webhook",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("network is down")))
    out = report.file_report(_Svc(), {"title": "t", "happened": "h"}, {"app": {}})
    assert out["ok"] is False and out["configured"] is True
    assert "network is down" in out["reason"] and "h" in out["description"]
    print("  a failed send returns the written report rather than losing it")


def test_a_build_can_ship_its_own_sink(monkeypatch, tmp_path):
    """The point of choosing a webhook: an installed copy files reports with no setup."""
    _clean(monkeypatch, tmp_path)
    res = tmp_path / "resources"
    res.mkdir()
    (res / report.SINK_FILE).write_text(
        json.dumps({"webhook": "https://automation.atlassian.com/pro/hooks/shipped"}), encoding="utf-8")
    monkeypatch.setenv("OPENFLOW_RESOURCES_DIR", str(res))
    cfg = report.jira_config()
    assert cfg is not None and cfg["webhook"].endswith("/shipped")
    print("  a bundled report-sink.json is a working sink on its own")


def test_the_machine_and_the_environment_both_beat_what_was_shipped(monkeypatch, tmp_path):
    _clean(monkeypatch, tmp_path)
    res = tmp_path / "resources"
    res.mkdir()
    (res / report.SINK_FILE).write_text(
        json.dumps({"webhook": "https://automation.atlassian.com/pro/hooks/shipped"}), encoding="utf-8")
    monkeypatch.setenv("OPENFLOW_RESOURCES_DIR", str(res))

    # This machine's own config overrides the build's.
    (tmp_path / report.JIRA_FILE).write_text(
        json.dumps({"webhook": "https://automation.atlassian.com/pro/hooks/machine"}), encoding="utf-8")
    assert report.jira_config()["webhook"].endswith("/machine")

    # And the environment overrides that.
    monkeypatch.setenv("OPENFLOW_JIRA_WEBHOOK", "https://automation.atlassian.com/pro/hooks/env")
    assert report.jira_config()["webhook"].endswith("/env")
    print("  precedence: environment > this machine > what the build shipped")


def test_a_malformed_config_is_ignored_rather_than_fatal(monkeypatch, tmp_path):
    _clean(monkeypatch, tmp_path)
    (tmp_path / report.JIRA_FILE).write_text("{not json at all", encoding="utf-8")
    assert report.jira_config() is None      # no sink, but no exception either
    print("  a broken config file leaves no sink rather than breaking the page")
