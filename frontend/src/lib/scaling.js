// Interface scaling, applied as a CSS zoom on the document root so it works in both the browser
// dev build and the Electron shell (Electron's setZoomFactor would work only in the shell). The
// stored value is -500..500 with 0 = default; map that to a 0.5x .. 1.5x zoom, a tenth per 100.
export function scaleToZoom(value) {
  const v = Number(value) || 0;
  const zoom = 1 + Math.max(-500, Math.min(500, v)) / 1000;
  return Math.round(zoom * 1000) / 1000;
}

export function applyInterfaceScaling(value) {
  try {
    document.documentElement.style.zoom = String(scaleToZoom(value));
  } catch { /* zoom unsupported: leave the UI at 1x rather than throw */ }
}

/** Pull interface_scaling out of an /api/settings payload, or null if absent. */
export function scalingFromSettings(settings) {
  const groups = settings?.groups || [];
  for (const g of groups) {
    for (const f of g.fields || []) {
      if (f.id === "interface_scaling") return f.value;
    }
  }
  return null;
}
