import { useEffect, useRef } from "react";

// The board, scaled to the width it has. The Create is drawn at one size (its geometry is by
// design and never reflows); on a window narrower than that it used to run off the right edge
// and take the band, the palette and the LED cards with it. This scales the whole board
// uniformly, never above 1x, to the room left beside the cards column, and because the parts
// under the board take the board's width they follow. Wider than the board, it stays 1x and
// the page group centres. CSS zoom rather than transform: zoom changes the layout size, which
// is what keeps the header, the band and the palette on the board's edges.
export default function BoardFit({ children }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return undefined;
    const page = el.closest("main") || document.body;
    const fit = () => {
      el.style.zoom = 1;
      const natural = el.scrollWidth || 1;
      const cs = getComputedStyle(page);
      const inner = page.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight);
      // Whatever shares the row with the board (the cards column) and the gap between them.
      const split = el.closest(".editor-split");
      let aside = 0;
      if (split) {
        for (const c of split.children) if (!c.contains(el)) aside += c.getBoundingClientRect().width;
        aside += parseFloat(getComputedStyle(split).columnGap) || 0;
      }
      const z = Math.min(1, Math.max(0.5, (inner - aside) / natural));
      el.style.zoom = z.toFixed(4);
    };
    fit();
    const ro = new ResizeObserver(fit);
    ro.observe(page);
    return () => ro.disconnect();
  }, []);
  return <div className="board-fit" ref={ref}>{children}</div>;
}
