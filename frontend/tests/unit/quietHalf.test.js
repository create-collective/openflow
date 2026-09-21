// A half that answers every command with an empty reply (SCRUM-107).
//
// It happens when the two halves are on different firmware -- the newer one reads perfectly and
// its partner's own port goes hollow -- which is exactly the state a half-finished update leaves
// behind. The old firmware-mismatch check could never see it: it required BOTH versions, and the
// half that would prove they differ is the one that has stopped saying its own. So the keyboard
// showed a card of blank fields and no explanation, which reads as damage. It is not: that half
// still types.
import { describe, expect, it } from "vitest";
import { buildBoards } from "../../src/pages/Troubleshooting";

const left = (extra = {}) => ({ side: "left", port: "COM30", keyboardId: 1, connected: true, ...extra });
const right = (extra = {}) => ({ side: "right", port: "COM29", keyboardId: 1, connected: true, ...extra });

describe("buildBoards", () => {
  it("flags two halves that disagree about their version", () => {
    const [b] = buildBoards([left({ firmwareVersion: "3.41.0" }), right({ firmwareVersion: "3.35.4" })]);
    expect(b.mismatch).toBe(true);
    expect(b.quiet).toBeNull();
  });

  it("names the half that is not reporting, and the partner that still is", () => {
    const [b] = buildBoards([left({ firmwareVersion: "3.41.0" }), right({ reporting: false })]);
    expect(b.mismatch).toBe(false);          // only one version is known: they do not "disagree"
    expect(b.quiet.side).toBe("right");
    expect(b.quietPartner.firmwareVersion).toBe("3.41.0");
  });

  it("says nothing about a keyboard where both halves read normally", () => {
    const [b] = buildBoards([left({ firmwareVersion: "3.41.0" }), right({ firmwareVersion: "3.41.0" })]);
    expect(b.mismatch).toBe(false);
    expect(b.quiet).toBeNull();
  });

  it("does not call an unplugged half quiet", () => {
    // Disconnected is its own state with its own message; a half that is gone has not "answered
    // with nothing".
    const [b] = buildBoards([left({ firmwareVersion: "3.41.0" }),
                             right({ connected: false, reporting: false })]);
    expect(b.quiet).toBeNull();
  });

  it("keeps two keyboards apart", () => {
    const boards = buildBoards([
      left({ firmwareVersion: "3.41.0" }),
      right({ reporting: false }),
      left({ keyboardId: 2, port: "COM7", firmwareVersion: "3.35.4" }),
      right({ keyboardId: 2, port: "COM8", firmwareVersion: "3.35.4" }),
    ]);
    expect(boards).toHaveLength(2);
    expect(boards[0].quiet.side).toBe("right");
    expect(boards[1].quiet).toBeNull();
  });
});
