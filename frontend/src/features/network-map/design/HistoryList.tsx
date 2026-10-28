// ============================================================
// OPSYN — an audit trail as a readable list (Network GIS Phase 8): what
// happened, to what, by whom, when. Used by the design's Versions drawer
// (the whole design, or one asset / cable) and the live asset inspector.
// Entries come from network_audit_trail (network + infrastructure logs).
// ============================================================

import { format } from 'date-fns';
import type { AuditEntry } from '@shared';
import { describeAudit } from './designFormat';
import d from './Design.module.css';

function when(iso: string): string {
  try { return format(new Date(iso), 'd MMM yyyy, HH:mm'); } catch { return iso; }
}

export function HistoryList({ entries, loading, error, showCode = true, empty = 'No changes recorded yet.' }: {
  entries: AuditEntry[] | undefined; loading?: boolean; error?: unknown; showCode?: boolean; empty?: string;
}) {
  if (loading) return <div className={d.skel} />;
  if (error) return <p className={d.err} role="alert">Couldn't load the history.</p>;
  if (!entries?.length) return <p className={d.blockNote}>{empty}</p>;
  return (
    <ol className={d.history}>
      {entries.map(e => {
        const { verb, detail } = describeAudit(e);
        return (
          <li key={e.id} data-action={e.action}>
            <p className={d.historyWhat}>
              <strong>{verb}</strong>
              {showCode && e.entity_code && <> <code>{e.entity_code}</code></>}
              {detail && <span className={d.historyDetail}> · {detail}</span>}
            </p>
            <p className={d.historyMeta}>{e.actor} · {when(e.occurred_at)}</p>
          </li>
        );
      })}
    </ol>
  );
}
