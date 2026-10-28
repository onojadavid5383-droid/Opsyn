// ============================================================
// OPSYN — ReturnDeptModal  (Corrective Plan A.5)
// Return an external task to the previous department in its routing chain.
// Pre-fetches pipeline history to name the previous department.
// Backend: POST /{id}/return-dept  { reason }
// Visibility: external tasks, manager/team lead/admin (roleLevel >= 3)
// ============================================================

import { useQuery } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { tasksApi } from '../../../api/tasks.api';
import { GlassModal } from '../../../components/glass';
import { Button, Textarea } from '../../../components/ui';
import s from './TaskDialog.module.css';

export interface ReturnDeptModalProps {
  taskId:    string;
  taskTitle: string;
  onConfirm: (reason: string) => void;
  onClose:   () => void;
  isPending: boolean;
}

const MIN_REASON = 10;

export function ReturnDeptModal({ taskId, taskTitle, onConfirm, onClose, isPending }: ReturnDeptModalProps) {
  const [reason, setReason] = useState('');
  const [touched, setTouched] = useState(false);
  const field = useRef<HTMLTextAreaElement | null>(null);

  const { data: historyData, isLoading } = useQuery({
    queryKey: ['tasks', taskId, 'pipeline-history'],
    queryFn: () => tasksApi.getPipelineHistory(taskId),
    staleTime: 30 * 1000,
    enabled: !!taskId,
  });
  const stages = historyData?.stages ?? [];
  const current = stages.find(st => st.is_current);
  const previous = current
    ? stages.filter(st => !st.is_current && st.routing_order === current.routing_order - 1).at(0)
    : null;
  const canReturn = !!previous;

  const trimmed = reason.trim();
  const valid = trimmed.length >= MIN_REASON;
  const error = touched && !valid
    ? `Reason must be at least ${MIN_REASON} characters (${trimmed.length}/${MIN_REASON})`
    : undefined;

  const submit = () => {
    setTouched(true);
    if (valid && canReturn && !isPending) onConfirm(trimmed);
  };

  return (
    <GlassModal
      open
      onClose={onClose}
      size="sm"
      title="Return to previous department"
      description="Send this task back along its routing chain."
      initialFocus={field as React.MutableRefObject<HTMLElement | null>}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isPending}>Cancel</Button>
          <Button variant="primary" onClick={submit} disabled={!valid || !canReturn} loading={isPending}>Return to department</Button>
        </>
      }
    >
      <div className={s.stack}>
        <div className={s.preview}>{taskTitle}</div>
        {isLoading ? (
          <p className={s.notice} role="status">Loading routing history…</p>
        ) : canReturn ? (
          <p className={s.notice}>Returning to <strong>{previous?.dept?.name ?? 'the previous department'}</strong></p>
        ) : (
          <p className={s.notice} data-tone="warning">This task has no previous department in its routing chain, so it can't be returned.</p>
        )}
        <Textarea
          label="Reason"
          required
          textareaRef={field}
          value={reason}
          onChange={setReason}
          onBlur={() => setTouched(true)}
          disabled={!canReturn}
          placeholder={canReturn ? 'Why is this task going back?' : 'No previous department to return to'}
          rows={3}
          hint={error ? undefined : `At least ${MIN_REASON} characters`}
          error={error}
        />
      </div>
    </GlassModal>
  );
}
