// The classic arrow pointer, for the Mouse tab.
//
// An SVG rather than a glyph: the tab strip is single characters, and every mouse-ish codepoint
// is either an emoji (which renders in colour and at the wrong weight beside ⌨ and ⌘) or an
// arrow already used by another tab. Same approach as LayersIcon.
export default function CursorIcon({ size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true"
      fill="currentColor" style={{ display: "block" }}>
      <path d="M3 1.4 12.4 8.9a.5.5 0 0 1-.28.89l-3.6.3-1.9 3.4a.5.5 0 0 1-.93-.16L3 1.4Z" />
    </svg>
  );
}
