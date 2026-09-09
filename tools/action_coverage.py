#!/usr/bin/env python3
"""Does OpenFlow cover EVERY key action NayaFlow can bind? Prove it, or list the gaps.

    python tools/action_coverage.py                 # report; exit 1 if any NayaFlow action is uncovered
    python tools/action_coverage.py --json out.json # also write the machine-readable result

Three sources define "what NayaFlow can bind", and every action from all three is checked:

    docs/reference/nayaflow-key-palette.json      the renderer's key palette, scraped from the
                                                  unpacked 1.25.1 bundle (every actionType/actionCode
                                                  a user can pick for a key)
    docs/reference/nayacore-action-vocabulary.json what NayaCore can serialise (its name tables and
                                                  record types), so a palette entry the core cannot
                                                  flash is classified rather than counted against us
    NayaFlow databases                            every (action_type, action_code) actually stored in
                                                  the fresh install, the Sep 7 snapshot and the Aug 28
                                                  stock snapshot -- ground truth for what NayaFlow's
                                                  own profiles contain

For each action, three questions, in order:

    palette   is it in OpenFlow's own palette (actions_catalog), in the key context?
    encode    does flash._binding_rows_to_record turn it into a device record?
    decode    does keymap_read.translate turn that record back into the same action?

"Covered" means all three. Layer switches are checked once per type with a synthetic layer id;
shortcut chords are checked through the encoder with the modifier tokens NayaFlow offers.

Read-only: files only, never the keyboard.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "openflow" / "backend"))
sys.path.insert(0, str(ROOT / "openflow" / "backend" / "openflow_backend" / "_vendor"))

from openflow_backend.device import actions_catalog as AC   # noqa: E402
from openflow_backend.device import flash as F              # noqa: E402
from openflow_backend.device import keymap_read as kr       # noqa: E402
from openflow_backend.device import remap as R              # noqa: E402

PALETTE = ROOT / "docs" / "reference" / "nayaflow-key-palette.json"
CORE = ROOT / "docs" / "reference" / "nayacore-action-vocabulary.json"
DBS = [
    ("fresh 1.25.1 install", Path(os.path.expandvars(r"%APPDATA%\NayaFlow\user-data.db"))),
    ("Sep 7 snapshot", ROOT / "device" / "out" / "nayaflow-user-data-20260907-105009.db"),
    ("Aug 28 stock snapshot", ROOT / "device" / "userdata-snapshot" / "user-data-2026-08-28.db"),
]
LAYER_ORDER = {"L0": 0, "L1": 1, "L2": 2}
SYNTH_LAYER = "L1"


# --------------------------------------------------------------------------- #
# the NayaFlow side                                                            #
# --------------------------------------------------------------------------- #

def _normalise(action_type: str, code: str) -> tuple[str, str]:
    """Layer switches carry a uuid; compare them by type with one synthetic target."""
    for at, spec in AC.LAYER_ACTION_TYPES.items():
        if action_type == at or (code or "").startswith(spec["prefix"]):
            return at, spec["prefix"] + SYNTH_LAYER
    return action_type, code


def nayaflow_actions() -> dict[tuple[str, str], set[str]]:
    """{(action_type, code): {sources}} from the palette scrape and every database we hold."""
    found: dict[tuple[str, str], set[str]] = defaultdict(set)
    if PALETTE.is_file():
        pal = json.loads(PALETTE.read_text(encoding="utf-8"))
        for a in pal.get("key_actions", []):
            # `gated` entries are OS-gated (the Mac VS Code presets show on macOS), not hidden
            # for good -- a Mac user binds them, so they count. Feature-flagged groups (macros)
            # are not in key_actions at all.
            found[_normalise(a["actionType"], a["actionCode"])].add(
                "palette (os-gated)" if a.get("gated") else "palette")
        for lt in pal.get("layer_action_types", []):
            found[_normalise(lt["actionType"], lt["prefix"] + SYNTH_LAYER)].add("palette")
    for label, path in DBS:
        if not path.is_file():
            continue
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            for at, ac in conn.execute("SELECT DISTINCT action_type, action_code FROM key_bindings"):
                found[_normalise(at, ac)].add(f"db:{label}")
        finally:
            conn.close()
    return found


def core_flashable_types() -> set[str] | None:
    """Action types NayaCore can serialise, or None if the vocabulary file is absent."""
    if not CORE.is_file():
        return None
    core = json.loads(CORE.read_text(encoding="utf-8"))
    out = set()
    for e in core.get("flashable_action_types") or []:
        # entries are {"type": "combo (modifiers + key, ...)", ...}; the first word is the type
        t = e["type"] if isinstance(e, dict) else str(e)
        out.add(t.split(" ")[0].split("(")[0])
    return out


# --------------------------------------------------------------------------- #
# the OpenFlow side                                                            #
# --------------------------------------------------------------------------- #

def openflow_palette() -> dict[tuple[str, str], dict]:
    out = {}
    for tab in AC.get_catalog()["tabs"]:
        if tab.get("contexts") and "key" not in tab["contexts"]:
            continue
        for cat in tab["categories"]:
            for e in cat["actions"]:
                out[_normalise(e["actionType"], e["code"])] = {"tab": tab["id"], "category": cat["name"],
                                                                "comingSoon": e.get("comingSoon", False)}
    for at, spec in AC.LAYER_ACTION_TYPES.items():
        out[(at, spec["prefix"] + SYNTH_LAYER)] = {"tab": "layers", "category": spec["label"]}
    return out


def encode(action_type: str, code: str):
    """(type_byte, param) or a string saying why not."""
    try:
        rec = F._binding_rows_to_record([{"beh": "press", "at": action_type, "ac": code}],
                                        200, 0, LAYER_ORDER)
    except Exception as e:                                # noqa: BLE001 -- report, never crash
        return f"raises {type(e).__name__}: {e}"
    if rec is None:
        return "dropped: " + F._drop_reason(action_type, code)
    return rec


def decodes_back(action_type: str, code: str, rec) -> bool:
    typ, param = rec
    try:
        slots = kr.translate(typ, param, {v: k for k, v in LAYER_ORDER.items()})
    except Exception:                                     # noqa: BLE001
        return False
    if action_type in ("none", "trans"):
        return slots == []                                # the empty records decode to nothing, by design
    if action_type in AC.LAYER_ACTION_TYPES:
        return any(at == action_type for _b, at, _c in slots)
    # key / modifier / shortcut_alias / combo are one family on the wire (all KEY_PRESS): a
    # preset spelled "F5" as a shortcut_alias reads back as key F5, and a recorded "combo" reads
    # back as a shortcut_alias. What must survive is the CHORD, not the label of its type.
    family = {"key", "modifier", "shortcut_alias", "combo"}
    want = _chord(code)
    for _b, at, c in slots:
        if _chord(c) != want:
            continue
        if at == action_type or (at in family and action_type in family):
            return True
    return False


def _chord(code) -> str:
    """The chord as the DEVICE holds it, so two spellings of one binding compare equal.

    NayaFlow stores a chord in the order the user built it ("LGUI + LCTRL + D") and the decoder
    spells it in HID bit order; modifier tokens have aliases (CTRL, LSHFT); bracketed modifiers
    are not stored at all ("[LALT] + TAB" is TAB on the wire); and a base with no HID usage
    (CLICK) leaves only the modifiers. rest._same_action makes the same allowances."""
    if not code:
        return str(code)
    toks = [t.strip() for t in str(code).split(" + ")]
    toks = [R.MOD_TOKEN_ALIASES.get(t, t) for t in toks if not (t.startswith("[") and t.endswith("]"))]
    toks = [R.CODE_ALIASES.get(t, t) for t in toks]
    mods = sorted(t for t in toks if t in R.MOD_BIT)
    base = [t for t in toks if t not in R.MOD_BIT and t not in R.MODIFIER_ONLY_BASES]
    return " + ".join(mods + base)


# --------------------------------------------------------------------------- #
# report                                                                       #
# --------------------------------------------------------------------------- #

def run() -> dict:
    nf = nayaflow_actions()
    core_types = core_flashable_types()
    of = openflow_palette()
    rows = []
    for (at, code), sources in sorted(nf.items()):
        in_palette = (at, code) in of
        rec = encode(at, code)
        encoded = not isinstance(rec, str)
        decoded = encoded and decodes_back(at, code, rec)
        core_ok = None if core_types is None else (at in core_types)
        rows.append({"actionType": at, "code": code, "sources": sorted(sources),
                     "palette": in_palette, "encode": encoded, "decode": decoded,
                     "detail": rec if isinstance(rec, str) else f"{rec[0]:#04x} {rec[1].hex()}",
                     "coreFlashable": core_ok,
                     "comingSoon": bool(of.get((at, code), {}).get("comingSoon"))})
    covered = [r for r in rows if r["palette"] and r["encode"] and r["decode"]]
    gaps = [r for r in rows if not (r["palette"] and r["encode"] and r["decode"])]
    # A gap NayaCore itself cannot flash is a different kind of gap: NayaFlow shows it, no one
    # can write it. Reported separately so the count of things NayaFlow can do and we cannot
    # stays honest.
    vendor_only = [g for g in gaps if g["coreFlashable"] is False]
    real = [g for g in gaps if g["coreFlashable"] is not False]
    extras = sorted(set(of) - set(nf))
    return {"nayaflow_actions": len(rows), "covered": len(covered), "gaps": real,
            "not_flashable_by_vendor_either": vendor_only, "openflow_extras": len(extras),
            "openflow_extras_unencodable": [
                {"actionType": at, "code": c, "detail": encode(at, c)}
                for at, c in extras if isinstance(encode(at, c), str)],
            "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", help="write the full result here")
    ap.add_argument("--all", action="store_true", help="print every action, not just the gaps")
    a = ap.parse_args()
    res = run()
    print(f"NayaFlow key actions found: {res['nayaflow_actions']}"
          + ("" if PALETTE.is_file() else "   (palette scrape missing -- databases only)"))
    print(f"covered by OpenFlow (palette + encode + decode): {res['covered']}")
    print(f"\nGAPS -- NayaFlow can bind it, OpenFlow cannot: {len(res['gaps'])}")
    for g in res["gaps"]:
        why = []
        if not g["palette"]:
            why.append("not in OpenFlow's palette")
        if not g["encode"]:
            why.append(g["detail"])
        elif not g["decode"]:
            why.append("encodes but does not decode back to the same action")
        print(f"   {g['actionType']:22} {g['code']:36} {'; '.join(why)}   [{', '.join(g['sources'])}]")
    if res["not_flashable_by_vendor_either"]:
        print(f"\nshown by NayaFlow but NayaCore cannot flash it either: {len(res['not_flashable_by_vendor_either'])}")
        for g in res["not_flashable_by_vendor_either"]:
            print(f"   {g['actionType']:22} {g['code']:36} {g['detail']}")
    print(f"\nOpenFlow palette entries NayaFlow does not have: {res['openflow_extras']}")
    if res["openflow_extras_unencodable"]:
        print(f"   ...of which OpenFlow's own encoder cannot write: {len(res['openflow_extras_unencodable'])}")
        for x in res["openflow_extras_unencodable"]:
            print(f"      {x['actionType']:22} {x['code']:36} {x['detail']}")
    if a.all:
        print("\nevery NayaFlow action:")
        for r in res["rows"]:
            flag = "ok " if (r["palette"] and r["encode"] and r["decode"]) else "GAP"
            print(f"   {flag} {r['actionType']:22} {r['code']:36} {r['detail']}")
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1, default=str), encoding="utf-8")
        print(f"\nwrote {a.json}")
    return 1 if res["gaps"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
