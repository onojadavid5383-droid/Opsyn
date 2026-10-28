// ============================================================
// OPSYN — ForwardDeptModal  (Corrective Plan A.3)
// Forward an external task to another department.
// Backend: POST /{id}/forward-dept  { to_dept_id, note? }
// Visibility: external tasks only, current assignee/manager/lead/admin
// ============================================================

import { useQuery } from '@tanstack/react-query';
import { useId, useState } from 'react';
import type { Department } from '@shared';
import { orgApi } from '../../../api/index';
import { GlassModal } from '../../../components/glass';
import { Button, Input, Textarea } from '../../../components/ui';
import s from './TaskDialog.module.css';

export interface ForwardDeptModalProps {
  taskTitle:       string;
  currentDeptId:   string;
  onConfirm:       (toDeptId: string, note?: string) => void;
  onClose:         () => void;
  isPending:       boolean;
}

export function ForwardDeptModal({ taskTitle, currentDeptId, onConfirm, onClose, isPending }: ForwardDeptModalProps) {
  const [toDeptId, setToDeptId] = useState('');
  const [note, setNote] = useState('');
  const [search, setSearch] = useState('');
  const uid = useId().replace(/:/g, '');

  const { data: depts = [], isLoading } = useQuery({
    queryKey: ['departments'],
    queryFn: () => orgApi.getDepartments(),
    staleTime: 5 * 60 * 1000,
  });
  const all = depts as Department[];
  const filtered = all.filter(d => d.id !== currentDeptId && (!search || (d.name ?? '').toLowerCase().includes(search.toLowerCase())));
  const selected = all.find(d => d.id === toDeptId);
  const canSubmit = !!toDeptId && !isPending;

  return (
    <GlassModal
      open
      onClose={onClose}
      size="sm"
      title="Forward to department"
      description="Route this external task to another department's inbox."
      footer={
        <>
          <Button variant="secondary" onClick={onClose} disabled={isPending}>Cancel</Button>
          <Button variant="primary" onClick={() => canSubmit && onConfirm(toDeptId, note.trim() || undefined)} disabled={!toDeptId} loading={isPending}>
            Send to department
          </Button>
        </>
      }
    >
      <div className={s.stack}>
        <div className={s.preview}>{taskTitle}</div>
        <Input id={`${uid}-search`} label="Find a department" value={search} onChange={v => { setSearch(v); setToDeptId(''); }} placeholder="Type a department name" autoComplete="off" />
        <fieldset>
          <legend className="sr-only">Target department</legend>
          <div className={s.options}>
            {isLoading ? <p className={s.empty} role="status">Loading departments…</p>
              : filtered.length === 0 ? <p className={s.empty}>No other department matches.</p>
              : filtered.map(d => (
                <label key={d.id} className={s.option}>
                  <input type="radio" name={`${uid}-dept`} value={d.id} checked={toDeptId === d.id} onChange={() => setToDeptId(d.id)} />
                  <span className={s.optionName}>{d.name}</span>
                </label>
              ))}
          </div>
        </fieldset>
        {selected && <p className={s.notice}>Routing to <strong>{selected.name}</strong>. Their department inbox is notified.</p>}
        <Textarea id={`${uid}-note`} label="Routing note (optional)" value={note} onChange={setNote} placeholder="Context for the receiving department" rows={2} />
      </div>
    </GlassModal>
  );
}
