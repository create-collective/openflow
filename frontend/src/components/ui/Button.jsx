// The one button.
//
// `variant` is what the button IS: the primary action, an ordinary one, a dangerous one, or a
// ghost that only shows on hover. `size` is where it sits: md in a card or a form, sm in a
// board toolbar (the old .board-btn metrics), xs beside a heading (the old .btn.tiny). `done`
// is the green "it worked" state the board buttons show for a few seconds after a read or a
// flash; `busy` disables it and is the caller's cue to change the label. `pressed` renders a
// toggle-like button with aria-pressed.
export default function Button({
  variant = "secondary",
  size = "md",
  done = false,
  busy = false,
  pressed,
  className = "",
  type = "button",
  children,
  ...rest
}) {
  const cls = [
    "ui-btn",
    `ui-btn-${variant}`,
    size !== "md" ? `ui-btn-${size}` : "",
    done ? "ui-btn-done" : "",
    className,
  ].filter(Boolean).join(" ");
  return (
    <button {...rest} type={type} className={cls} aria-pressed={pressed} disabled={rest.disabled || busy}>
      {children}
    </button>
  );
}
