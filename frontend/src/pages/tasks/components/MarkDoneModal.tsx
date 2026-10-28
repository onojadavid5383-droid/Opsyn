// ============================================================
// OPSYN — MarkDoneModal
// Explicit Done / approval confirmation. Blueprint §2.2.
// ============================================================

import { GlassModal } from '../../../components/glass';
import { Button } from '../../../components/ui';
import s from './TaskDialog.module.css';

export interface MarkDoneModalProps {
  taskTitle:  string;
  onConfirm:  () => void;
  onClose:    () => void;
  isPending:  boolean;
}

export function MarkDoneModal({ taskTitle, onConfirm, onClose, isPending }: MarkDoneModalProps) {
  return (
    <GlassModal
      open
      onClose={onClose}
      size="sm"
      title="Mark as done"
      description="Confirm this task is complete."
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isPending}>Cancel</Button>
          <Button variant="primary" onClick={onConfirm} loading={isPending}>Mark as done</Button>
        </>
      }
    >
      <div className={s.stack}>
        <div className={s.preview}>{taskTitle}</div>
        <p className={s.text}>
          The task moves to <strong>Done</strong>. This is recorded in the audit trail and the activity timeline.
        </p>
      </div>
    </GlassModal>
  );
}
