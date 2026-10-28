// ============================================================
// OPSYN — PushBackModal  (Corrective Plan A.1)
// Mandatory rejection reason + optional recipient selector.
// Backend: POST /{id}/push-back  { reason, to_user_id? }
// Visibility: current assignee OR manager (roleLevel >= 4)
// ============================================================

import { useQuery } from '@tanstack/react-query';
import { useRef, useState } from 'react';
import { tasksApi, type DeptStaffMember } from '../../../api/tasks.api';
import { GlassModal } from '../../../components/glass';
import { Button, Select, Textarea } from '../../../components/ui';
import s from './TaskDialog.module.css';

export interface PushBackModalProps {
  taskId:    string;
  taskTitle: string;
  onConfirm: (reason: string, toUserId?: string) => void;
  onClose:   () => void;
  isPending: boolean;
}

const MIN_REASON = 10;

export function PushBackModal({ taskId: _taskId, taskTitle, onConfirm, onClose, isPending }: PushBackModalProps) {
  const [reason, setReason] = useState('');
  const [toUserId, setToUserId] = useState('');
  const [touched, setTouched] = useState(false);
  const field = useRef<HTMLTextAreaElement | null>(null);

  const { data: staffData } = useQuery({
    queryKey: ['dept-staff', 'push-back'],
    queryFn: () => tasksApi.getDeptStaff(undefined, 100),
    staleTime: 5 * 60 * 1000,
  });
  const staff: DeptStaffMember[] = Array.isArray(staffData) ? staffData : [];

  const trimmed = reason.trim();
  const valid = trimmed.length >= MIN_REASON;
  const error = touched && !valid
    ? `Reason must be at least ${MIN_REASON} characters (${trimmed.length}/${MIN_REASON})`
    : undefined;

  const submit = () => {
    setTouched(true);
    if (valid && !isPending) onConfirm(trimmed, toUserId || undefined);
  };

  return (
    <GlassModal
      open
      onClose={onClose}
      size="sm"
      title="Push back task"
      description="Give a reason — everyone involved is notified."
      initialFocus={field as React.MutableRefObject<HTMLElement | null>}
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isPending}>Cancel</Button>
          <Button variant="danger-solid" onClick={submit} disabled={!valid} loading={isPending}>Push back task</Button>
        </>
      }
    >
      <div className={s.stack}>
        <div className={s.preview}>{taskTitle}</div>
        <Textarea
          label="Reason"
          required
          textareaRef={field}
          value={reason}
          onChange={setReason}
          onBlur={() => setTouched(true)}
          placeholder="Why is this task going back?"
          rows={4}
          hint={error ? undefined : `At least ${MIN_REASON} characters`}
          error={error}
        />
        {staff.length > 0 && (
          <Select
            label="Return to"
            value={toUserId}
            onChange={setToUserId}
            options={[
              { label: 'Previous assignee / department default', value: '' },
              ...staff.map(m => ({ label: `${m.full_name}${m.job_title ? ` — ${m.job_title}` : ''}`, value: m.user_id })),
            ]}
          />
        )}
      </div>
    </GlassModal>
  );
}
