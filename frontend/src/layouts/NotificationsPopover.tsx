// ============================================================
// OPSYN — NotificationsPopover: the bell's glass popover.
// Latest notifications, mark-all-read, and a way to the full inbox.
// ============================================================

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { formatDistanceToNowStrict } from 'date-fns';
import { Bell, BellOff, CheckCheck } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import type { Notification } from '@shared';
import { notificationsApi } from '../api/index';
import { GlassPopover } from '../components/glass';
import styles from './NotificationsPopover.module.css';
import shell from './Shell.module.css';

const PREVIEW_COUNT = 8;

const toArr = (d: unknown): Notification[] =>
  Array.isArray(d) ? d : ((d as { items?: Notification[] } | undefined)?.items ?? []);

function ago(iso: string): string {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? '' : `${formatDistanceToNowStrict(t)} ago`;
}

function NotificationList({ close }: { close: () => void }) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { data, isPending, isError } = useQuery({
    queryKey: ['notifications', 'list'],
    queryFn:  () => notificationsApi.list(),
  });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['notifications'] });
  };
  const markAll = useMutation({ mutationFn: () => notificationsApi.markAllRead(), onSuccess: refresh });
  const markOne = useMutation({ mutationFn: (id: string) => notificationsApi.markRead(id), onSuccess: refresh });

  const items = toArr(data).slice(0, PREVIEW_COUNT);
  const hasUnread = items.some(n => !n.is_read);

  const open = (n: Notification) => {
    if (!n.is_read) markOne.mutate(n.id);
    close();
    if (n.action_url) navigate(n.action_url);
  };

  return (
    <>
      <div className={styles.head}>
        <h3 className={styles.title}>Notifications</h3>
        {hasUnread && (
          <button type="button" className={`liquid-glass-item ${styles.textBtn}`} onClick={() => markAll.mutate()} disabled={markAll.isPending}>
            <CheckCheck size={14} aria-hidden="true" /> Mark all read
          </button>
        )}
      </div>

      {isPending && <p className={styles.empty}>Loading…</p>}
      {isError && <p className={styles.empty}>Notifications couldn't be loaded. Try again in a moment.</p>}
      {!isPending && !isError && items.length === 0 && (
        <p className={styles.empty}><BellOff size={16} aria-hidden="true" /> You're all caught up.</p>
      )}

      {items.length > 0 && (
        <ul className={styles.list}>
          {items.map(n => (
            <li key={n.id}>
              <button type="button" className={`liquid-glass-item ${styles.item}`} onClick={() => open(n)}>
                <span className={styles.dot} data-unread={!n.is_read || undefined} aria-hidden="true" />
                <span className={styles.text}>
                  <span className={styles.itemTitle}>
                    {n.title}
                    {!n.is_read && <span className="sr-only"> (unread)</span>}
                  </span>
                  {n.body && <span className={styles.body}>{n.body}</span>}
                  <span className={styles.time}>{ago(n.created_at)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <button type="button" className={styles.all} onClick={() => { close(); navigate('/notifications'); }}>
        View all notifications
      </button>
    </>
  );
}

export default function NotificationsPopover({ unreadCount }: { unreadCount: number }) {
  return (
    <GlassPopover
      ariaLabel="Notifications"
      placement="bottom-end"
      className={styles.popover}
      renderTrigger={p => (
        <button
          {...p}
          type="button"
          className={shell.iconBtn}
          aria-label={unreadCount > 0 ? `Notifications, ${unreadCount} unread` : 'Notifications'}
        >
          <Bell size={18} aria-hidden="true" />
          {unreadCount > 0 && <span className={shell.bellCount} aria-hidden="true">{unreadCount > 99 ? '99+' : unreadCount}</span>}
        </button>
      )}
    >
      {({ close }) => <NotificationList close={close} />}
    </GlassPopover>
  );
}
