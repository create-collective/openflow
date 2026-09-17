# Going back to NayaFlow after OpenFlow: multi-binding keys

## The short version

If you give a key more than one behaviour in OpenFlow (a hold, a double tap, or a tap + hold
on top of its tap) and you later flash that keyboard from NayaFlow, NayaFlow will finish the
flash and then report:

> Failed to verify written data.

**The flash worked.** The keyboard has what NayaFlow sent. NayaFlow just cannot confirm it,
because it cannot see or clean up the extra behaviours OpenFlow put there.

**If you want NayaFlow to flash cleanly again**, flash from OpenFlow once with no multi-binding
keys in the profile, i.e. every key tap-only. That clears the leftovers, and NayaFlow verifies
normally from then on.

## Why it happens

A key on the Create stores its behaviours in two places. The tap and the hold live at the key's
own position. The double tap and the tap + hold live in a **second bank**, at that position plus
0x52. Nothing in NayaFlow's interface can reach the second bank: it has no double-tap or
tap + hold editor, so as far as its profile is concerned those records do not exist.

NayaFlow flashes as a sparse diff. It writes only the records its own profile holds, then reads
the board back and compares. So when a key carries second-bank data that NayaFlow's profile does
not describe:

- it does not write that record, because it has nothing to write there;
- it cannot clear that record either, for the same reason;
- its read-back then finds a record its profile has no entry for, and the comparison fails.

This is not garbage collection that runs and gets it wrong. It is garbage collection that never
runs at all, because the leftover is invisible to the model doing the diffing.

OpenFlow does handle this. When a profile sets a key and gives it no double tap or tap + hold,
the flash explicitly writes an empty record into that key's second bank rather than leaving
whatever the board happens to hold. That rule is pinned by `backend/tests/test_second_bank_gc.py`.
Keys the profile does not mention keep both of their banks untouched, which is correct: a profile
with no opinion about a key must not have one about its double tap either.

## The fix, step by step

1. In OpenFlow, take the profile you want on the board and remove the extra behaviours, leaving
   each key with its tap only. (Or select a profile that never had any.)
2. Flash it. OpenFlow writes an empty second bank for every key it sets, which clears the
   leftovers.
3. Flash from NayaFlow. It will verify.

You only need this if you intend to go back to NayaFlow. Multi-binding keys work correctly on the
keyboard and in OpenFlow; the failure is only in NayaFlow's verification step.

## What the evidence looks like

From the 2026-09-17 run (`device/out/onekey-timing-20260917-analysis.txt`, capture and NayaCore
log), NayaFlow reported six differing positions on layer 0. Keys 53 and 73 (`0x35`, `0x49`) had
been given four behaviours in OpenFlow. Their second-bank records at `0x87` and `0x9b` survived
NayaFlow's flash untouched, and both the key and its leftover were reported as differences, which
is four of the six.

The same thing was diagnosed and proven on 2026-09-09: clearing those two records by hand made
NayaFlow's very next flash verify, with no other change. The run and its logs are in
`docs/nayaflow-verify-test-plan.md`.

## A second, unrelated NayaFlow quirk in the same report

The remaining two positions of those six were key 55 and its second bank, which NayaFlow fully
owns and did write. They were still reported as differences, and the reason is on NayaFlow's side.
Every record in its read-back is rendered with a tapping term of 200 and flavour 1, including
records the board demonstrably holds at term 180 flavour 0 (verified by reading the board directly
after NayaFlow closed). In other words its verification compares what it wrote against a
re-serialisation that uses default timing values rather than the board's actual bytes, so any key
with a hold will mismatch once the tapping term is moved off 200.

Nothing can be done about that from OpenFlow's side, and it has no effect on the keyboard. It is
recorded here so the two causes are not confused in future.
