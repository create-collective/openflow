import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

// The dialog shell: a backdrop, a centred panel, a title, an optional subtitle, the body, and a
// footer of buttons. Escape and a click on the backdrop close it unless `dismissable` is false
// (a flash in progress has nothing to go back to). Rendered into document.body so no page
// layout can clip it. Focus lands on the first enabled footer button when it opens, so a
// keyboard user is inside the dialog and Enter is a deliberate choice; `onClose` and
// `dismissable` are read through refs so a caller's inline handlers never re-run that.
export default function Modal({
  open, title, subtitle, onClose, dismissable = true, footer, width, className = "", children, ...rest
}) {
  const panel = useRef(null);
  const closeRef = useRef(onClose);
  const dismissRef = useRef(dismissable);
  closeRef.current = onClose;
  dismissRef.current = dismissable;

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape" && dismissRef.current && closeRef.current) closeRef.current();
    };
    document.addEventListener("keydown", onKey);
    const first = panel.current?.querySelector(".ui-modal-actions button:not(:disabled)") || panel.current;
    first?.focus?.();
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;
  const cls = ["ui-modal", className].filter(Boolean).join(" ");
  return createPortal(
    <div className="ui-modal-backdrop" onMouseDown={() => { if (dismissRef.current && closeRef.current) closeRef.current(); }}>
      <div
        {...rest}
        ref={panel}
        className={cls}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === "string" ? title : undefined}
        tabIndex={-1}
        style={width ? { width } : undefined}
        onMouseDown={(e) => e.stopPropagation()}
      >
        {title !== undefined && <h3 className="ui-modal-title">{title}</h3>}
        {subtitle && <p className="ui-modal-sub">{subtitle}</p>}
        {children}
        {footer && <div className="ui-modal-actions">{footer}</div>}
      </div>
    </div>,
    document.body,
  );
}
