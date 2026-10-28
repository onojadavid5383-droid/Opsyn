// ============================================================
// OPSYN — Command Center: outstanding work + what changed recently
//   TaskPipelinePanel  real counts by deadline bucket + the most urgent tasks
//                      (no progress bars: the API has no progress to show)
//   ActivityPanel      the latest events across tasks, projects, outages
// ============================================================

import { useQuery } from '@tanstack/react-query';
import { formatDistanceToNowStrict } from 'date-fns';
import { Link } from 'react-router-dom';
import { activityApi } from '../../api/index';
import { tasksApi } from '../../api/tasks.api';
import { Badge, type BadgeVariant } from '../../components/ui';
import { toArr } from './dashboardData';
import s from './Dashboard.module.css';

const ago = (iso?: string | null) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isNaN(t) ? '' : formatDistanceToNowStrict(t, { addSuffix: true });
};

const PRIORITY: Record<string, BadgeVariant> = { critical: 'critical', high: 'high', medium: 'default', low: 'info' };

interface BoardTask { id: string; title: string; ticket_number?: string; priority?: string; deadline?: string | null }

export function TaskPipelinePanel({ className }: { className?: string }) {
  const q = useQuery({ queryKey: ['tasks', 'board'], queryFn: () => tasksApi.getBoard(), refetchInterval: 60_000 });
  const board = q.data as Record<string, BoardTask[] | undefined> | undefined;
  const count = (k: string) => board?.[k]?.length ?? 0;
  const urgent = [...(board?.overdue ?? []), ...(board?.today ?? [])].slice(0, 5);

  const BUCKETS = [
    { key: 'overdue', label: 'Overdue', cls: s.bucketOverdue },
    { key: 'today', label: 'Due today' },
    { key: 'this_week', label: 'This week' },
    { key: 'backlog', label: 'Backlog' },
  ];

  return (
    <section className={`${s.panel} ${className ?? ''}`} aria-labelledby="cc-pipeline">
      <header className={s.panelHead}>
        <h2 id="cc-pipeline" className={s.panelTitle}>
          Task pipeline<span className={s.panelSub}>Open tasks by deadline</span>
        </h2>
        <Link to="/tasks" className={s.link}>Task board</Link>
      </header>
      <div className={s.panelBody}>
        <div className={s.buckets}>
          {BUCKETS.map(b => (
            <Link key={b.key} to="/tasks" className={`${s.bucket} ${b.cls ?? ''}`}>
              <span className={s.bucketCount}>{q.isPending ? '…' : count(b.key)}</span>
              <span className={s.bucketLabel}>{b.label}</span>
            </Link>
          ))}
        </div>
        {q.isError && <p className={s.empty}>Tasks couldn't be loaded.</p>}
        {!q.isPending && !q.isError && urgent.length === 0 && <p className={s.empty}>Nothing overdue or due today.</p>}
        {urgent.length > 0 && (
          <ul className={s.list} aria-label="Most urgent tasks">
            {urgent.map(t => (
              <li key={t.id} className={s.listItem}>
                <span className={s.listMain}>
                  <span className={s.listTitle}>{t.title}</span>
                  <span className={s.listMeta}>
                    {t.ticket_number && <span className={s.ref}>{t.ticket_number}</span>}
                    {t.deadline && <> · due {ago(t.deadline)}</>}
                  </span>
                </span>
                {t.priority && <Badge variant={PRIORITY[t.priority] ?? 'default'} size="xs">{t.priority}</Badge>}
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

interface FeedItem { id: string; entity_type: string; entity_id: string; actor_label: string; body: string; created_at: string }

const ENTITY_PATH: Record<string, (id: string) => string> = {
  project: id => `/projects/${id}`,
  outage:  id => `/outage/${id}`,
  task:    () => '/tasks',
};

export function ActivityPanel({ className }: { className?: string }) {
  const q = useQuery({ queryKey: ['activity', 'recent'], queryFn: () => activityApi.getGlobalFeed({ size: 8 }), refetchInterval: 60_000 });
  const items = toArr<FeedItem>(q.data);

  return (
    <section className={`${s.panel} ${className ?? ''}`} aria-labelledby="cc-activity">
      <header className={s.panelHead}>
        <h2 id="cc-activity" className={s.panelTitle}>
          Recent activity<span className={s.panelSub}>Across tasks, projects and outages</span>
        </h2>
        <Link to="/activity" className={s.link}>All activity</Link>
      </header>
      <div className={s.panelBody}>
        {q.isPending && <p className={s.empty}>Loading…</p>}
        {q.isError && <p className={s.empty}>Activity couldn't be loaded.</p>}
        {!q.isPending && !q.isError && items.length === 0 && <p className={s.empty}>No activity recorded yet.</p>}
        {items.length > 0 && (
          <ul className={s.list}>
            {items.map(e => {
              const path = ENTITY_PATH[e.entity_type]?.(e.entity_id);
              const text = <span className={s.listTitle}>{e.body}</span>;
              return (
                <li key={e.id} className={s.listItem}>
                  <span className={s.listMain}>
                    {path ? <Link to={path} style={{ color: 'inherit' }}>{text}</Link> : text}
                    <span className={s.listMeta}>{e.actor_label} · {e.entity_type}</span>
                  </span>
                  <time className={s.listTime} dateTime={e.created_at}>{ago(e.created_at)}</time>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </section>
  );
}
