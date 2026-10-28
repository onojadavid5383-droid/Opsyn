// ============================================================
// OPSYN — ActivityTimeline
// Unified chronological feed for tasks, projects, outages,
// and onboarding requests. Blueprint Section 4 + 15.2.
// ============================================================

import { RefreshCw } from 'lucide-react';
import React, { useState } from 'react';
import type { TimelineEntityType } from './types';
import { TimelineEvent } from './TimelineEvent';
import { TimelineCommentForm } from './TimelineCommentForm';
import { Spinner } from '../ui/Spinner';
import { EmptyState } from '../ui/EmptyState';
import {
  useTaskTimeline,
  useProjectTimeline,
  useOutageTimeline,
  useOnboardingTimeline,
} from '../../hooks/index';
import s from './ActivityTimeline.module.css';

// ── Props ─────────────────────────────────────────────────────

export interface ActivityTimelineProps {
  entityType:   TimelineEntityType;
  entityId:     string;
  canComment?:  boolean;
  maxHeight?:   number | string;
  showFilter?:  boolean;
  style?:       React.CSSProperties;
}

// ── Hook selector by entity type ─────────────────────────────

function useTimeline(entityType: TimelineEntityType, entityId: string) {
  const task       = useTaskTimeline(entityType === 'task'       ? entityId : undefined);
  const project    = useProjectTimeline(entityType === 'project' ? entityId : undefined);
  const outage     = useOutageTimeline(entityType === 'outage'   ? entityId : undefined);
  const onboarding = useOnboardingTimeline(entityType === 'onboarding' ? entityId : undefined);

  const map = { task, project, outage, onboarding };
  return map[entityType];
}

// ── Main component ────────────────────────────────────────────

export function ActivityTimeline({
  entityType,
  entityId,
  canComment  = false,
  maxHeight,
  showFilter  = false,
  style,
}: ActivityTimelineProps) {
  const [replyToId, setReplyToId]       = useState<string | null>(null);
  const [replyToActor, setReplyToActor] = useState<string | null>(null);
  const [filterType, setFilterType]     = useState<string>('all');

  const { data: rawEntries = [], isLoading, error, refetch } = useTimeline(entityType, entityId);

  // Group threaded replies under their parent
  const entries = React.useMemo(() => {
    const topLevel = rawEntries.filter(e => !e.parent_id);
    const byParent: Record<string, typeof rawEntries> = {};
    rawEntries.filter(e => e.parent_id).forEach(r => {
      if (!byParent[r.parent_id!]) byParent[r.parent_id!] = [];
      byParent[r.parent_id!].push(r);
    });
    return topLevel.map(e => ({
      ...e,
      replies: byParent[e.id] ?? e.replies ?? [],
    }));
  }, [rawEntries]);

  // Apply event-type filter
  const filtered = filterType === 'all'
    ? entries
    : entries.filter(e =>
        filterType === 'comments' ? e.event_type === 'user_comment' : e.is_system
      );

  const handleReply = (parentId: string) => {
    const parent = entries.find(e => e.id === parentId);
    setReplyToId(parentId);
    setReplyToActor(parent?.actor_label ?? null);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 0, ...style }}>

      {/* Header */}
      <div className={s.header}>
        <span className={s.title}>
          Activity
          {rawEntries.length > 0 && (
            <span className={s.count}>
              {rawEntries.length}
              <span className="sr-only"> {rawEntries.length === 1 ? 'event' : 'events'}</span>
            </span>
          )}
        </span>

        <div className={s.controls}>
          {showFilter && (
            <div className={s.segment} role="group" aria-label="Show">
              {(['all', 'comments', 'system'] as const).map(f => (
                <button key={f} type="button" className={s.seg} aria-pressed={filterType === f} onClick={() => setFilterType(f)}>
                  {f}
                </button>
              ))}
            </div>
          )}
          <button type="button" className={s.icon} onClick={() => refetch()} aria-label="Refresh activity" title="Refresh activity">
            <RefreshCw size={16} aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* Comment form at top if canComment */}
      {canComment && (
        <div style={{ marginBottom: 16 }}>
          <TimelineCommentForm
            entityType={entityType}
            entityId={entityId}
            replyToId={replyToId}
            replyToActor={replyToActor}
            onCancelReply={() => { setReplyToId(null); setReplyToActor(null); }}
          />
        </div>
      )}

      {/* Feed */}
      <div style={{
        display:    'flex',
        flexDirection:'column',
        gap:        12,
        overflowY:  maxHeight ? 'auto' : undefined,
        maxHeight,
        paddingRight: maxHeight ? 4 : undefined,
      }}>
        {isLoading ? (
          <Spinner center size="md" />
        ) : error ? (
          <EmptyState
            icon="⚠"
            title="Failed to load timeline"
            message="Could not fetch activity. Click to retry."
            action={{ label: 'Retry', onClick: () => refetch() }}
            size="sm"
          />
        ) : filtered.length === 0 ? (
          <EmptyState
            icon="📋"
            title="No activity yet"
            message={canComment ? 'Be the first to add a work log entry.' : 'Activity will appear here as work progresses.'}
            size="sm"
          />
        ) : (
          filtered.map(entry => (
            <TimelineEvent
              key={entry.id}
              entry={entry}
              onReply={handleReply}
            />
          ))
        )}
      </div>
    </div>
  );
}
