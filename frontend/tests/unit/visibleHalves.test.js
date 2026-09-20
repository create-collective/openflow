// A keyboard that has been unplugged lingers in the backend's live map as a disconnected entry.
// That is right when it is the ONLY keyboard -- "your keyboard is not answering" is the thing to
// show -- and a ghost pair when another is still attached, which also kept the "Acting on"
// picker up after there was nothing left to choose between (SCRUM-86).
import { describe, expect, it } from "vitest";
import { visibleHalves } from "../../src/lib/showAllKeyboards";

const half = (keyboardId, side, connected) => ({ keyboardId, side, connected, port: `${keyboardId}${side}` });

const donorLive = [half(0, "left", true), half(0, "right", true)];
const warrantyOff = [half(1, "left", false), half(1, "right", false)];

describe("visibleHalves", () => {
  it("drops a keyboard that has been switched off while another is connected", () => {
    const got = visibleHalves([...donorLive, ...warrantyOff]);
    expect(got.map((h) => h.keyboardId)).toEqual([0, 0]);
  });

  it("keeps the last keyboard even when it goes, so its state is still reported", () => {
    const got = visibleHalves([half(0, "left", false), half(0, "right", false)]);
    expect(got).toHaveLength(2);
  });

  it("keeps everything when nothing at all is connected", () => {
    const got = visibleHalves([...warrantyOff, half(0, "left", false), half(0, "right", false)]);
    expect(got).toHaveLength(4);
  });

  it("keeps both keyboards while both are connected", () => {
    const got = visibleHalves([...donorLive, half(1, "left", true), half(1, "right", true)]);
    expect(got).toHaveLength(4);
  });

  it("keeps a keyboard with one half answering", () => {
    const got = visibleHalves([...donorLive, half(1, "left", true), half(1, "right", false)]);
    expect(got).toHaveLength(4);
  });

  it("shows everything when the troubleshooting toggle is on", () => {
    const got = visibleHalves([...donorLive, ...warrantyOff], true);
    expect(got).toHaveLength(4);
  });

  it("leaves a single keyboard untouched", () => {
    expect(visibleHalves(donorLive)).toEqual(donorLive);
  });
});
