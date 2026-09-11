import { MOUSE_BUTTONS, MOUSE_DIRECTIONS, MOUSE_MOTION, mousePick } from "../lib/mousedict";

// A mouse you click to bind, mirroring VirtualKeyboard: standalone, `{disabled, onPick}`, layout
// externalised to lib/mousedict.js.
//
// Drawn rather than listed because the whole point is that "which button is Mouse 4" has an
// obvious answer when you can see it and no obvious answer in a dropdown reading "M4". The side
// buttons are labelled Back and Forward for the same reason -- that is what they do, and M4/M5 is
// what the device calls them.
//
// Motion is separate from buttons and says so. A button binds to a tap; a direction pair binds to
// an AXIS, which is two device fields with the sign as the direction. Clicking one on a tap row
// would be offering something the field cannot hold.
//
// `motion` is false in the KEY context: a key position has no axis, so only buttons make sense
// there. Buttons themselves DO work on a key -- measured 2026-09-07, see actions_catalog.py.
// `directions` is set while a split-axis HALF is selected: the pairs give way to the eight
// single directions, which are what a half can hold besides a key.
export default function VirtualMouse({ disabled, onPick, disabledHint, motion = true, directions = false }) {
  const pick = (code) => { if (!disabled) onPick(mousePick(code)); };
  const btn = (area) => MOUSE_BUTTONS.find((b) => b.area === area);

  const Button = ({ area, className }) => {
    const b = btn(area);
    return (
      <button className={"vm-btn " + className} disabled={disabled} title={`${b.hint}  (${b.code})`}
        onClick={() => pick(b.code)}>
        <span className="vm-btn-label">{b.label}</span>
        <span className="vm-btn-code">{b.code}</span>
      </button>
    );
  };

  return (
    <div className="vm">
      {disabled && <div className="palette-disabled">{disabledHint}</div>}

      <div className="vm-body">
        <div className="vm-shell">
          <div className="vm-top">
            <Button area="left" className="vm-left" />
            <Button area="middle" className="vm-middle" />
            <Button area="right" className="vm-right" />
          </div>
          <div className="vm-palm" />
        </div>

        <div className="vm-side">
          <div className="vm-side-title">Side buttons</div>
          <Button area="side-back" className="vm-sidebtn" />
          <Button area="side-fwd" className="vm-sidebtn" />
        </div>
      </div>

      {directions && <div className="vm-motion">
        <div className="vm-side-title">
          Single direction — for this half of a split axis
        </div>
        <div className="vm-motion-grid">
          {MOUSE_DIRECTIONS.map((m) => (
            <button key={m.code} className="vm-motion-btn" disabled={disabled}
              title={m.hint} onClick={() => pick(m.code)}>
              <span className="vm-btn-label">{m.label}</span>
              <span className="vm-btn-code">{m.code.startsWith("SCROLL") ? "wheel" : "pointer"}</span>
            </button>
          ))}
        </div>
      </div>}

      {motion && !directions && <div className="vm-motion">
        <div className="vm-side-title">
          Motion — binds to an axis, not a tap
        </div>
        <div className="vm-motion-grid">
          {MOUSE_MOTION.map((m) => (
            <button key={m.code} className="vm-motion-btn" disabled={disabled}
              title={m.hint} onClick={() => pick(m.code)}>
              <span className="vm-btn-label">{m.label}</span>
              <span className="vm-btn-code">{m.axis}</span>
            </button>
          ))}
        </div>
      </div>}
    </div>
  );
}
