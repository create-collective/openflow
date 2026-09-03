// The Windows logo, for LGUI/RGUI. Replaces U+229E "squared plus" (⊞), which is a maths
// symbol that reads as a stick figure at keycap size. Four panes with a gap, drawn in
// currentColor so it inherits the keycap's contrast colour.
export default function WindowsIcon({ size = 13, style }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" style={style}
         role="img" aria-label="Windows key">
      <path d="M2.4 4.9 10.6 3.8v7.6H2.4V4.9zM11.6 3.6 22 2.2v9.2H11.6V3.6zM2.4 12.6h8.2v7.6L2.4 19.1v-6.5zM11.6 12.6H22v9.2l-10.4-1.4v-7.8z" />
    </svg>
  );
}
