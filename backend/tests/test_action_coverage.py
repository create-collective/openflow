"""OpenFlow covers every key action NayaFlow can bind -- except the ones listed here by name.

tools/action_coverage.py is the probe: NayaFlow's full key palette (scraped from the unpacked
1.25.1 app, docs/reference/nayaflow-key-palette.json) plus every binding in the NayaFlow
databases we hold, each run through OpenFlow's palette, its flash encoder and its decoder.

This test pins the result. Any NEW gap fails it. Closing one of the listed gaps fails it too,
on purpose: the list is the honest statement of what is still missing, and it must be edited
when that changes. No hardware.
"""
from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_REPO = next(p for p in _BACKEND.parents if (p / "tools" / "action_coverage.py").is_file())
sys.path.insert(0, str(_REPO / "tools"))

import action_coverage as cov  # noqa: E402

# Actions NayaFlow can bind that OpenFlow knowingly cannot yet. Empty since 2026-09-09: the last
# five, the LED colours cyan/magenta/yellow/orange/pink, were closed from NayaCore.exe's own LED
# parameter table (docs/reference/nayacore-action-vocabulary.json), which the four colours
# captured from hardware reproduce byte for byte. Anything that lands here again must say why.
PENDING: set[tuple[str, str]] = set()


def test_the_palette_scrape_is_present():
    assert cov.PALETTE.is_file(), f"missing {cov.PALETTE}: the probe would silently shrink to the databases"


def test_every_nayaflow_key_action_is_covered_except_the_pending_list():
    res = cov.run()
    assert res["nayaflow_actions"] > 300, "the palette scrape did not load"
    gaps = {(g["actionType"], g["code"]) for g in res["gaps"]}
    new = gaps - PENDING
    closed = PENDING - gaps
    assert not new, "NayaFlow can bind these and OpenFlow cannot:\n  " + "\n  ".join(
        f"{at} {code}: {next(g['detail'] for g in res['gaps'] if (g['actionType'], g['code']) == (at, code))}"
        for at, code in sorted(new))
    assert not closed, f"these are covered now -- remove them from PENDING: {sorted(closed)}"
    print(f"  {res['covered']} of {res['nayaflow_actions']} covered; pending: {len(PENDING)}")


def test_openflow_can_write_everything_in_its_own_palette():
    res = cov.run()
    assert res["openflow_extras_unencodable"] == [], res["openflow_extras_unencodable"]
    print("  no palette entry the encoder refuses")


if __name__ == "__main__":
    for fn in (test_the_palette_scrape_is_present,
               test_every_nayaflow_key_action_is_covered_except_the_pending_list,
               test_openflow_can_write_everything_in_its_own_palette):
        print(fn.__name__)
        fn()
    print("\nOK")
