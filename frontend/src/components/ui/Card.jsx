// A bordered panel with an optional title row. `title` alone is the plain card heading. With
// `ruled` (or `head`, something before the title such as a status dot, or `actions`, after it)
// the heading becomes a ruled header row, the Information page's card shape; `actionsAlign`
// "end" pushes the actions to the far edge (a Clear button), the default keeps them beside the
// title (a side badge).
export default function Card({ title, head, actions, actionsAlign = "start", ruled = false, className = "", children, ...rest }) {
  const cls = ["ui-card", className].filter(Boolean).join(" ");
  const isRuled = ruled || head !== undefined || actions !== undefined;
  return (
    <div {...rest} className={cls}>
      {isRuled ? (
        <div className="ui-card-head">
          {head}
          {title !== undefined && <h3>{title}</h3>}
          {actions !== undefined && (
            <span className={"ui-card-actions" + (actionsAlign === "end" ? " ui-card-actions-end" : "")}>{actions}</span>
          )}
        </div>
      ) : title !== undefined ? (
        <h3>{title}</h3>
      ) : null}
      {children}
    </div>
  );
}
