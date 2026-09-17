// Module display images (from ScreenshotsOfNayaFlow/pngs, centres made transparent). Track swaps
// image by the active button to highlight it. Absolute paths: in the desktop app the backend
// serves the renderer at /, so they resolve the same way they do under Vite.
export default function ModuleVisual({ type, activeButton }) {
  let src;
  if (type === "TRACK") {
    const m = /button_(\d)/.exec(activeButton || "");
    src = `/modules/track${m ? m[1] : "1"}.png`;
  } else if (type === "TUNE") {
    src = "/modules/tune.png";
  } else {
    src = "/modules/touch.png";
  }
  return (
    <div className="mod-visual">
      <img src={src} alt={`${type} module`} className="mod-img" />
    </div>
  );
}
