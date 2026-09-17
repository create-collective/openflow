import { useId } from "react";

// The OpenFlow mark: the Track module's silhouette (a square top-left corner, a circle for the
// rest) as a ring cut into five segments, from the owner's signature sheet (2026-09-17). Drawn
// as a vector so it is crisp at 22 px in the nav and at 1024 px as the app icon. The colour is
// the parent's `color`, so the nav gives it the brand cyan and the app icon paints it white;
// the hole and the cuts are transparent and show whatever is behind.
export function BrandMarkShape({ id }) {
  return (
    <>
      <mask id={id} maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100">
        <path d="M9 0H50A50 50 0 1 1 0 50V9A9 9 0 0 1 9 0Z" fill="white" />
        <circle cx="50" cy="50" r="28.5" fill="black" />
        <g stroke="black" strokeWidth="3.6" fill="none">
          <path d="M54.5 -2V26" />
          <path d="M50 50L104 25" />
          <path d="M50 50L94 85" />
          <path d="M50 50L26 102" />
          <path d="M-2 49.5H26" />
        </g>
      </mask>
      <rect width="100" height="100" fill="currentColor" mask={`url(#${id})`} />
    </>
  );
}

export default function BrandMark({ size = 22, className = "", ...rest }) {
  const id = "brand-" + useId().replace(/:/g, "");
  return (
    <svg {...rest} className={className} width={size} height={size} viewBox="0 0 100 100" aria-hidden="true">
      <BrandMarkShape id={id} />
    </svg>
  );
}
