// ============================================================
// OPSYN — AdminDeleteModal  (Corrective Plan B.1)
// Admin task deletion governance: mandatory reason + typed CONFIRM.
// Backend: DELETE /{id}  { reason }  (soft-delete, role >= 4)
// Visibility: admin users (roleLevel >= 4) AND task.is_deleted === false
// ============================================================

import { Trash2 } from 'lucide-react';
import { useId, useRef, useState } from 'react';
import { GlassModal } from '../../../components/glass';
import { Button, Input, Textarea } from '../../../components/ui';
import s from './TaskDialog.module.css';

export interface AdminDeleteModalProps {
  taskId:       string;
  taskTitle:    string;
  ticketNumber: string | null;
  deptName:     string | null;
  onConfirm:    (reason: string) => void;
  onClose:      () => void;
  isPending:    boolean;
}

const CONFIRM_PHRASE = 'CONFIRM';
const MIN_REASON = 20;

export function AdminDeleteModal({
  taskId: _taskId, taskTitle, ticketNumber, deptName, onConfirm, onClose, isPending,
}: AdminDeleteModalProps) {
  const [reason, setReason] = useState('');
  const [confirmText, setConfirmText] = useState('');
  const [touched, setTouched] = useState(false);
  const field = useRef<HTMLTextAreaElement | null>(null);
  const uid = useId().replace(/:/g, '');

  const trimmed = reason.trim();
  const reasonOk = trimmed.length >= MIN_REASON;
  const reasonError = touched && !reasonOk
    ? `Reason must be at least ${MIN_REASON} characters (${trimmed.length}/${MIN_REASON})`
    : undefined;
  const confirmOk = confirmText === CONFIRM_PHRASE;
  const canSubmit = reasonOk && confirmOk && !isPending;

  const submit = () => {
    setTouched(true);
    if (canSubmit) onConfirm(trimmed);
  };

  return (
    <GlassModal
      open
      onClose={onClose}
      size="sm"
      role="alertdialog"
      title="Delete task"
      description="This is logged, and the department manager is notified."
      initialFocus={field as React.MutableRefObject<HTMLElement | null>}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isPending}>Cancel</Button>
          <Button variant="danger-solid" leftIcon={<Trash2 size={16} aria-hidden="true" />} onClick={submit} disabled={!reasonOk || !confirmOk} loading={isPending}>
            Delete task
          </Button>
        </>
      }
    >
      <div className={s.stack}>
        <div className={s.preview}>
          {(ticketNumber || deptName) && (
            <span className={s.previewRef}>{[ticketNumber, deptName].filter(Boolean).map((v, i) => <span key={i}>{i > 0 ? ' · ' : ''}{v}</span>)}</span>
          )}
          {taskTitle}
        </div>
        <Textarea
          id={`${uid}-reason`}
          label="Reason for deletion"
          required
          textareaRef={field}
          value={reason}
          onChange={setReason}
          onBlur={() => setTouched(true)}
          placeholder="Stored in the audit log — say why this task is being removed"
          rows={3}
          hint={reasonError ? undefined : `At least ${MIN_REASON} characters`}
          error={reasonError}
        />
        <Input
          id={`${uid}-confirm`}
          label={`Type ${CONFIRM_PHRASE} to confirm`}
          value={confirmText}
          onChange={setConfirmText}
          placeholder={CONFIRM_PHRASE}
          autoComplete="off"
          error={confirmText && !confirmOk ? `Type exactly: ${CONFIRM_PHRASE}` : undefined}
        />
        <p className={s.notice} data-tone="critical">
          The task will be soft-deleted. The department manager gets an in-app notification, and admins can restore it from Deleted tasks.
        </p>
      </div>
    </GlassModal>
  );
}
