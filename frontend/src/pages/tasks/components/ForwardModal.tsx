// ============================================================
// OPSYN — ForwardModal  (Corrective Plan A.2)
// Forward an internal task to another staff member in the same department.
// Backend: POST /{id}/forward  { to_user_id, note? }
// Visibility: internal task, current assignee OR manager/lead
// ============================================================

import { useQuery } from '@tanstack/react-query';
import { useId, useState } from 'react';
import { tasksApi, type DeptStaffMember } from '../../../api/tasks.api';
import { GlassModal } from '../../../components/glass';
import { Button, Input, Textarea } from '../../../components/ui';
import s from './TaskDialog.module.css';

export interface ForwardModalProps {
  taskTitle:       string;
  currentUserId:   string;
  onConfirm:       (toUserId: string, note?: string) => void;
  onClose:         () => void;
  isPending:       boolean;
}

export function ForwardModal({ taskTitle, currentUserId, onConfirm, onClose, isPending }: ForwardModalProps) {
  const [toUserId, setToUserId] = useState('');
  const [note, setNote] = useState('');
  const [search, setSearch] = useState('');
  const uid = useId().replace(/:/g, '');

  const { data: staffData, isLoading } = useQuery({
    queryKey: ['dept-staff', 'forward', search],
    queryFn: () => tasksApi.getDeptStaff(search || undefined, 50),
    staleTime: 30 * 1000,
  });
  const staff: DeptStaffMember[] = (Array.isArray(staffData) ? staffData : []).filter(m => m.user_id !== currentUserId);
  const canSubmit = !!toUserId && !isPending;

  return (
    <GlassModal
      open
      onClose={onClose}
      size="sm"
      title="Forward task to staff"
      description="Reassign this task to someone else in your department."
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isPending}>Cancel</Button>
          <Button variant="primary" onClick={() => canSubmit && onConfirm(toUserId, note.trim() || undefined)} disabled={!toUserId} loading={isPending}>
            Forward task
          </Button>
        </>
      }
    >
      <div className={s.stack}>
        <div className={s.preview}>{taskTitle}</div>
        <Input
          id={`${uid}-search`}
          label="Find a colleague"
          value={search}
          onChange={v => { setSearch(v); setToUserId(''); }}
          placeholder="Type a name"
          autoComplete="off"
        />
        <fieldset>
          <legend className="sr-only">Forward to</legend>
          <div className={s.options}>
            {isLoading ? <p className={s.empty} role="status">Loading staff…</p>
              : staff.length === 0 ? <p className={s.empty}>No one in your department matches.</p>
              : staff.map(m => (
                <label key={m.user_id} className={s.option}>
                  <input type="radio" name={`${uid}-to`} value={m.user_id} checked={toUserId === m.user_id} onChange={() => setToUserId(m.user_id)} />
                  <span className={s.optionText}>
                    <span className={s.optionName}>{m.full_name}</span>
                    {m.job_title && <span className={s.optionSub}>{m.job_title}</span>}
                  </span>
                </label>
              ))}
          </div>
        </fieldset>
        <Textarea id={`${uid}-note`} label="Note (optional)" value={note} onChange={setNote} placeholder="Context for the new assignee" rows={2} />
      </div>
    </GlassModal>
  );
}
