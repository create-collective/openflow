// The LED outline on Bindings: a white (or near-white) LED color vanished against light mode's
// white caps and board, so such an outline is drawn over a gray rim (owner, 2026-10-05).
import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import KeymapBoard, { isLight } from "../../src/components/KeymapBoard";

describe("isLight", () => {
  it("is true for white and near-white, false for saturated or dark colors", () => {
    expect(isLight("#ffffff")).toBe(true);
    expect(isLight("#f5f0e0")).toBe(true);
    expect(isLight("#ff0000")).toBe(false);
    expect(isLight("#00a0ff")).toBe(false);
    expect(isLight("#202020")).toBe(false);
    expect(isLight("")).toBe(false);
  });
});

describe("LED outline rim", () => {
  const board = (keys) => render(
    <KeymapBoard keysByPosition={keys} mode="bindings" ledOutline onSelectKey={() => {}} moduleAssign={{}} />);

  it("puts a rim under a white outline and none under a colored one", () => {
    const { container } = board({ 66: { colorHex: "#ffffff" }, 20: { colorHex: "#ff0000" } });
    expect(container.querySelectorAll('[data-testid="led-rim"]')).toHaveLength(1);
  });

  it("draws no rim when the outlines are off", () => {
    const { container } = render(
      <KeymapBoard keysByPosition={{ 66: { colorHex: "#ffffff" } }} mode="bindings"
        onSelectKey={() => {}} moduleAssign={{}} />);
    expect(container.querySelectorAll('[data-testid="led-rim"]')).toHaveLength(0);
  });
});
