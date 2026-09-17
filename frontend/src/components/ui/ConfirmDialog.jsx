import Button from "./Button";
import Modal from "./Modal";
import { settleDialog, usePendingDialog } from "../../lib/dialogs";

// The confirmation the app asks before doing something it cannot undo: a title that IS the
// question, the consequence in plain words, and two buttons where the confirming one says what
// it does ("Clear and pair", not "OK"). Danger-toned when the action erases something. Cancel
// takes focus, so Enter never confirms by accident.
export function ConfirmDialog({ request }) {
  if (!request) return null;
  const danger = request.tone === "danger";
  return (
    <Modal
      open
      title={request.title}
      onClose={() => settleDialog(false)}
      footer={
        <>
          <Button onClick={() => settleDialog(false)}>{request.cancelLabel}</Button>
          <Button variant={danger ? "danger" : "primary"} onClick={() => settleDialog(true)}>
            {request.confirmLabel}
          </Button>
        </>
      }
    >
      {request.message && <p className="ui-modal-sub">{request.message}</p>}
      {request.detail && <p className="ui-modal-detail">{request.detail}</p>}
    </Modal>
  );
}

// Mounted once, in App.jsx: renders whatever confirmDialog() is waiting on.
export default function DialogHost() {
  const request = usePendingDialog();
  return <ConfirmDialog request={request} />;
}
