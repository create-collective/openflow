// Module display images (the hi-res set under public/modules, drawn at 1254 px and kept at 512).
// Track has a left and a right unit and swaps image by the active button to highlight it.
// Absolute paths: in the desktop app the backend serves the renderer at /, so they resolve the
// same way they do under Vite.
export default function ModuleVisual({ type, activeButton, side = "left" }) {
  let src;
  if (type === "TRACK") {
    const m = /button_(\d)/.exec(activeButton || "");
    src = `/modules/v2/track-${side === "right" ? "right" : "left"}-${m ? m[1] : "1"}.png`;
  } else if (type === "TUNE") {
    src = "/modules/v2/tune.png";
  } else {
    src = "/modules/v2/touch.png";
  }
  return (
    <div className="mod-visual">
      <img src={src} alt={`${type} module`} className="mod-img" />
    </div>
  );
}
