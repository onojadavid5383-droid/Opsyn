// ============================================================
// OPSYN — EscalateModal  (Corrective Plan A.4)
// Escalate a task to the department manager with a mandatory note.
// Backend: POST /{id}/escalate  { note }
// Visibility: current assignee only
// ============================================================

import { useRef, useState } from 'react';
import { GlassModal } from '../../../components/glass';
import { Button, Textarea } from '../../../components/ui';
import s from './TaskDialog.module.css';

export interface EscalateModalProps {
  taskTitle: string;
  onConfirm: (note: string) => void;
  onClose:   () => void;
  isPending: boolean;
}

const MIN_NOTE = 20;

export function EscalateModal({ taskTitle, onConfirm, onClose, isPending }: EscalateModalProps) {
  const [note, setNote] = useState('');
  const [touched, setTouched] = useState(false);
  const field = useRef<HTMLTextAreaElement | null>(null);

  const trimmed = note.trim();
  const valid = trimmed.length >= MIN_NOTE;
  const error = touched && !valid
    ? `Write at least ${MIN_NOTE} characters (${trimmed.length}/${MIN_NOTE})`
    : undefined;

  const submit = () => {
    setTouched(true);
    if (valid && !isPending) onConfirm(trimmed);
  };

  return (
    <GlassModal
      open
      onClose={onClose}
      size="sm"
      title="Escalate to manager"
      description="Your department manager is notified with your note."
      initialFocus={field as React.MutableRefObject<HTMLElement | null>}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isPending}>Cancel</Button>
          <Button variant="primary" onClick={submit} disabled={!valid} loading={isPending}>Escalate to manager</Button>
        </>
      }
    >
      <div className={s.stack}>
        <div className={s.preview}>{taskTitle}</div>
        <Textarea
          label="Escalation note"
          required
          textareaRef={field}
          value={note}
          onChange={setNote}
          onBlur={() => setTouched(true)}
          placeholder="Why does this need manager attention? The blocker, the urgency, or the decision needed."
          rows={4}
          hint={error ? undefined : `At least ${MIN_NOTE} characters`}
          error={error}
        />
        <p className={s.notice} data-tone="warning">
          An escalation comment is posted on the task and your manager gets an in-app notification.
        </p>
      </div>
    </GlassModal>
  );
}
