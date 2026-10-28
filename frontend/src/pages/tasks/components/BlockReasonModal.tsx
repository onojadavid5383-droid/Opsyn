// ============================================================
// OPSYN — BlockReasonModal
// A task only moves to Blocked with a reason the team can act on.
// Blueprint §2.2
// ============================================================

import { useRef, useState } from 'react';
import { GlassModal } from '../../../components/glass';
import { Button, Textarea } from '../../../components/ui';
import s from './TaskDialog.module.css';

export interface BlockReasonModalProps {
  onConfirm:  (reason: string) => void;
  onClose:    () => void;
  isPending:  boolean;
}

export function BlockReasonModal({ onConfirm, onClose, isPending }: BlockReasonModalProps) {
  const [reason, setReason] = useState('');
  const field = useRef<HTMLTextAreaElement | null>(null);
  const trimmed = reason.trim();

  return (
    <GlassModal
      open
      onClose={onClose}
      size="sm"
      title="Mark as blocked"
      description="Say what is blocking this task, so the team can clear it."
      initialFocus={field as React.MutableRefObject<HTMLElement | null>}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isPending}>Cancel</Button>
          <Button variant="danger-solid" onClick={() => trimmed && onConfirm(trimmed)} disabled={!trimmed} loading={isPending}>
            Block task
          </Button>
        </>
      }
    >
      <div className={s.stack}>
        <Textarea
          label="Reason"
          required
          textareaRef={field}
          value={reason}
          onChange={setReason}
          placeholder="e.g. Waiting on a road-crossing permit from the local authority"
          rows={4}
        />
      </div>
    </GlassModal>
  );
}
