# Vendored dependencies

## nayactl

Upstream: https://github.com/Qonfused/nayactl (Apache-2.0, (c) Cory Bennett)

| | |
|---|---|
| **Vendored at** | `72a6af2` — *Fix module type detection (reports every module as Touch) + Windows serial fixes (#2)* |
| **Synced** | 2026-09-07 |
| **Local modifications** | none — a byte-for-byte copy of `src/nayactl/` (plus `LICENSE`) |

`LICENSE` is added by us and has no upstream counterpart at that path; everything else must match
upstream exactly. Keeping it an unmodified copy is deliberate: fixes belong upstream, where the
rest of the ecosystem gets them, and a clean copy makes the next sync a file copy instead of a
merge.

### Why this file exists

There was no record of which upstream commit had been vendored, and the copy silently fell 
behind. `0x10: "Touch"` was missing from the module address→type map, so a docked Touch would 
not have been identified at all. Two other upstream fixes were also absent. Nothing detected 
this, because a stale vendored copy still imports and still passes every test.

### Re-syncing

```sh
cd /path/to/nayactl && git fetch origin && git archive origin/main src/nayactl | tar -x -C /tmp/up
cp -r /tmp/up/src/nayactl/. openflow/backend/openflow_backend/_vendor/nayactl/
```

Then update the table above, run `pytest`, and confirm a real device still reads:

```sh
python -c "from openflow_backend.device.service import DeviceService; \
           s=DeviceService(); print(s.status_all(True)); s.shutdown()"
```

Compare with `diff -r --strip-trailing-cr` — the working tree is CRLF while upstream is LF, so a
plain `diff -rq` reports every file as differing and tells you nothing.

### What OpenFlow actually uses

`constants`, `transport`, `discovery`, `protocol`, `util`, `types`. The `cli/` package is carried
for completeness but is not imported by the backend — OpenFlow reimplements that logic in
`device/service.py`, so **a fix landing in `cli/` does not reach OpenFlow by syncing.** The
module battery unit bug was exactly this shape: fixed upstream in `cli/status.py`, and separately
fixed here in `device/service.py::_to_millivolts` because the two code paths are independent.
