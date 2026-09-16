// Board parity probe. Paste into the browser console (or run through the Chrome tool) on a page
// that shows the board (Bindings or LED Map). It reads every rendered keycap's box, compares it
// with docs/reference/create-key-geometry.json (served as /src/lib/keygeometry.json by Vite) at
// the scale implied by a plain key, and prints the worst deviations per half.
//
// Before 2026-09-16 (flexbox mirror, two scale factors): finger keys drifted up to 45 px and the
// thumbs ~60 px from NayaFlow's placement. Drawn from measured coordinates, every deviation
// should be 0 (browsers round to a hundredth of a pixel).
(async () => {
  const mode = document.querySelector(".kb-led") ? "colorMap" : "keyMap";
  const g = await fetch("/src/lib/keygeometry.json").then((r) => r.json());
  const canvas = document.querySelector(".kb-canvas") || document.querySelector(".keymap-board2");
  const b = canvas.getBoundingClientRect();
  const rect = {};
  document.querySelectorAll("button.kc").forEach((el) => {
    const m = /pos (\d+)/.exec(el.title);
    if (m) { const r = el.getBoundingClientRect(); rect[m[1]] = [r.left - b.left, r.top - b.top, r.width, r.height]; }
  });
  const out = {};
  for (const half of ["left", "right"]) {
    const ks = g.keys.filter((k) => k.half === half);
    const anchor = ks.find((k) => k.position === (half === "left" ? 16 : 29));
    const r0 = rect[anchor.position];
    const s = r0[2] / anchor.width;
    const dev = ks.map((k) => {
      const r = rect[k.position];
      const ex = (k[mode].x - anchor[mode].x) * s, ey = (k[mode].y - anchor[mode].y) * s;
      return { pos: k.position, label: k.label, dx: +(r[0] - r0[0] - ex).toFixed(2), dy: +(r[1] - r0[1] - ey).toFixed(2),
               dw: +(r[2] - k.width * s).toFixed(2), dh: +(r[3] - k.height * s).toFixed(2) };
    });
    const worst = dev.slice().sort((a, c) => Math.hypot(c.dx, c.dy) - Math.hypot(a.dx, a.dy)).slice(0, 5);
    out[half] = { scale: +s.toFixed(3), maxDev: +Math.max(...dev.map((d) => Math.hypot(d.dx, d.dy))).toFixed(2),
                  maxSizeDev: +Math.max(...dev.map((d) => Math.max(Math.abs(d.dw), Math.abs(d.dh)))).toFixed(2), worst };
  }
  console.log(JSON.stringify(out, null, 1));
  return out;
})();
