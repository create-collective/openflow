// @vitest-environment node
// The Modules page's vocabulary: pure, so the page can be rebuilt around it without changing
// what a row says.
import { describe, expect, it } from "vitest";
import {
  axisHalfId, axisHalfNames, byGesture, cleanCode, displayAction, gestureName, makeLabelFor,
  okForKind, parseAxisHalfId, statusBadge, targetLabel,
} from "../../src/lib/moduleLabels";

describe("gesture ordering and names", () => {
  it("sorts the canonical gestures first and unknown ones last", () => {
    const rows = [{ gesture: "swipe_up" }, { gesture: "weird" }, { gesture: "vertical" }, { gesture: "tap" }];
    expect(rows.sort(byGesture).map((r) => r.gesture)).toEqual(["vertical", "tap", "swipe_up", "weird"]);
  });
  it("names the pinch axis and tidies the rest", () => {
    // Pinch & spread is an axis, not one gesture: the combined behavior carries the name and
    // the split control breaks it into halves (proved on hardware 2026-09-18).
    expect(gestureName("pinch&spread")).toBe("Pinch & Spread");
    expect(gestureName("swipe_left")).toBe("swipe left");
    expect(targetLabel("button_2")).toBe("Button 2");
  });
});

describe("action labels", () => {
  it("prefers the catalog label, then the mouse dictionary, then the tidied code", () => {
    const labelFor = makeLabelFor([{ code: "SCROLL_UP - SCROLL_DOWN", label: "Vertical Scroll" }]);
    expect(labelFor("SCROLL_UP - SCROLL_DOWN")).toBe("Vertical Scroll");
    expect(labelFor("SOME_CODE - OTHER")).toBe("SOME CODE / OTHER");
    expect(cleanCode("")).toBe("—");
  });
  it("keeps the two RAW cases apart from Unassigned", () => {
    const labelFor = (c) => c;
    expect(displayAction("", labelFor)).toEqual({ text: "Unassigned", muted: true });
    expect(displayAction("RAW_p00:00m00", labelFor).text).toBe("Keyboard action");
    expect(displayAction("RAW_ab12", labelFor).text).toBe("Unrecognised");
    expect(displayAction("RAW_ab12", labelFor).title).toContain("ab12");
    expect(displayAction("F13", labelFor)).toEqual({ text: "F13", muted: false });
  });
});

describe("what a field can hold", () => {
  it("keypress and mouse-button fields take clicks, axes take pairs, DB-only rows take anything", () => {
    expect(okForKind("key", "keypress")).toBe(true);
    expect(okForKind("value", "keypress")).toBe(false);
    expect(okForKind("value", "axis")).toBe(true);
    expect(okForKind("key", "axis")).toBe(false);
    expect(okForKind("none", "axis")).toBe(true);
    expect(okForKind("layer_polite_toggle", null)).toBe(true);
  });
  it("badges locked, unsupported, flashable and app-only rows in that precedence", () => {
    expect(statusBadge({ locked: true, unsupported: true }).text).toBe("firmware");
    expect(statusBadge({ unsupported: true, flashable: true }).text).toBe("experimental");
    expect(statusBadge({ flashable: true })).toMatchObject({ tone: "ok", text: "flashable" });
    expect(statusBadge({})).toMatchObject({ tone: "neutral", text: "app only" });
  });
});

describe("axis halves", () => {
  it("round-trips a half id and names the directions by axis", () => {
    const id = axisHalfId("vertical:tune:1_finger", "-");
    expect(parseAxisHalfId(id)).toEqual({ behavior: "vertical:tune:1_finger", side: "-" });
    expect(parseAxisHalfId("b-123")).toBeNull();
    expect(axisHalfNames("vertical:tune:1_finger")).toEqual(["Up", "Down"]);
    expect(axisHalfNames("rotate:tune")).toEqual(["Rotate left", "Rotate right"]);
    expect(axisHalfNames("odd")).toEqual(["–", "+"]);
  });
});
