// The stock Windows arrow pointer, for the Mouse tab.
//
// Drawn rather than a glyph: every mouse-ish codepoint is either an emoji (colour, wrong weight
// beside ⌨ and ⌘) or an arrow another tab already uses. Same approach as LayersIcon.
//
// Two details that the first attempt got wrong and are worth keeping right:
//
//   * The viewBox is the path's TIGHT bounding box, not a round 0 0 16 16. With slack in the
//     box the artwork sits wherever the path happens to fall, which is what made the first one
//     look off-centre; with a tight box plus xMidYMid the browser centres the actual ink.
//   * It is the full pointer WITH its tail, white on a dark outline, which is what makes it read
//     as a cursor instantly rather than as a generic triangle.
export default function CursorIcon({ size = 15 }) {
  return (
    <svg width={size} height={size} viewBox="3.4 1.2 14.6 20.5"
      preserveAspectRatio="xMidYMid meet" aria-hidden="true" style={{ display: "block" }}>
      <path
        d="M4 1.8 L4 18.6 L8.3 14.4 L11 20.9 L14.2 19.5 L11.6 13.2 L17.4 12.9 Z"
        fill="#fff" stroke="#111" strokeWidth="1.3"
        strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
