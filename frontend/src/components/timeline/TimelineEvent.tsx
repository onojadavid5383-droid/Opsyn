// ============================================================
// OPSYN — TimelineEvent
// Renders a single activity timeline entry.
// 9 event types — 2 visual treatments: card and banner.
// Blueprint Section 4.1 + Section 15.2
// ============================================================

import React from 'react';
import type { TimelineEntry, TimelineEventType } from './types';
import { toRelative, toDateTime } from '../../utils/index';

// ── Visual config per event type ─────────────────────────────

interface EventConfig {
  icon:        string;
  label:       string;
  treatment:   'card' | 'banner';
  accentColor: string;
  bannerBg?:   string;
  tagColor?:   string;
  tagBg?:      string;
}

const EVENT_CONFIG: Record<TimelineEventType, EventConfig> = {
  user_comment: {
    icon: '', label: '', treatment: 'card',
    accentColor: 'transparent',
  },
  state_change: {
    icon: '⚙', label: 'STATE', treatment: 'card',
    accentColor: 'var(--chalk3)',
    tagColor: 'var(--chalk3)', tagBg: 'var(--bg4)',
  },
  assignment_change: {
    icon: '↔', label: 'ASSIGNED', treatment: 'card',
    accentColor: 'var(--blue)',
    tagColor: 'var(--blue)', tagBg: 'rgba(96,165,250,.1)',
  },
  block_reason: {
    icon: '⛔', label: 'BLOCKED', treatment: 'card',
    accentColor: 'var(--amber)',
    tagColor: 'var(--amber)', tagBg: 'rgba(251,191,36,.12)',
  },
  approval_event: {
    icon: '✓', label: 'APPROVAL', treatment: 'card',
    accentColor: 'var(--green)',
    tagColor: 'var(--green)', tagBg: 'rgba(74,222,128,.12)',
  },
  stage_advance: {
    icon: '▶', label: 'STAGE ADVANCED', treatment: 'banner',
    accentColor: 'var(--violet)',
    bannerBg: 'rgba(167,139,250,.08)',
    tagColor: 'var(--violet)', tagBg: 'rgba(167,139,250,.15)',
  },
  stage_pushback: {
    icon: '◀', label: 'PUSHED BACK', treatment: 'banner',
    accentColor: 'var(--rose)',
    bannerBg: 'rgba(248,113,113,.07)',
    tagColor: 'var(--rose)', tagBg: 'rgba(248,113,113,.15)',
  },
  pipeline_completion: {
    icon: '★', label: 'COMPLETED', treatment: 'banner',
    accentColor: 'var(--green)',
    bannerBg: 'rgba(74,222,128,.07)',
    tagColor: 'var(--green)', tagBg: 'rgba(74,222,128,.15)',
  },
  smartolt_event: {
    icon: '⚡', label: 'SMARTOLT', treatment: 'banner',
    accentColor: 'var(--rose)',
    bannerBg: 'rgba(248,113,113,.09)',
    tagColor: 'var(--rose)', tagBg: 'rgba(248,113,113,.18)',
  },
};

// ── Avatar initials from actor_label ─────────────────────────

function getInitials(label: string | undefined): string {
  if (!label) return '?';
  const parts = label.trim().split(/\s+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return label.slice(0, 2).toUpperCase();
}

function getAvatarColor(label: string | undefined): string {
  const COLORS = [
    'linear-gradient(135deg,#4ade80,#06b6d4)',
    'linear-gradient(135deg,#a78bfa,#06b6d4)',
    'linear-gradient(135deg,#fb923c,#f87171)',
    'linear-gradient(135deg,#22d3ee,#3b82f6)',
    'linear-gradient(135deg,#4ade80,#a78bfa)',
  ];
  if (!label) return COLORS[0];
  let hash = 0;
  for (let i = 0; i < label.length; i++) hash = label.charCodeAt(i) + ((hash << 5) - hash);
  return COLORS[Math.abs(hash) % COLORS.length];
}

// ── @mention + text highlight ─────────────────────────────────

function BodyText({ body }: { body: string | undefined }) {
  if (!body) return null;
  const parts = body.split(/(@\w[\w.-]*)/g);
  return (
    <>
      {parts.map((part, i) =>
        /^@\w/.test(part) ? (
          <span key={i} style={{
            background:   'rgba(251,191,36,.15)',
            color:        'var(--amber)',
            borderRadius: 3,
            padding:      '0 3px',
          }}>
            {part}
          </span>
        ) : part
      )}
    </>
  );
}

// ── Avatar component ──────────────────────────────────────────

function Avatar({ label, size = 28 }: { label: string | undefined; size?: number }) {
  const safeLabel = label ?? '';
  const isSystem = safeLabel === 'SYSTEM' || safeLabel === 'SmartOLT';
  return (
    <div style={{
      width:          size,
      height:         size,
      borderRadius:   '50%',
      background:     isSystem ? 'var(--bg4)' : getAvatarColor(safeLabel),
      display:        'flex',
      alignItems:     'center',
      justifyContent: 'center',
      fontSize:       size * 0.36,
      fontWeight:     700,
      color:          isSystem ? 'var(--chalk3)' : '#050810',
      flexShrink:     0,
      border:         isSystem ? '1px solid var(--wire2)' : 'none',
    }}>
      {isSystem ? '⚙' : getInitials(safeLabel)}
    </div>
  );
}

// ── Reply renderer (one level deep) ──────────────────────────

function ReplyCard({ entry }: { entry: TimelineEntry }) {
  return (
    <div style={{
      display:      'flex',
      gap:          8,
      marginTop:    8,
      paddingLeft:  36,
    }}>
      <Avatar label={entry.actor_label} size={22} />
      <div style={{
        flex:         1,
        background:   'var(--bg3)',
        border:       '1px solid var(--wire)',
        borderRadius: 'var(--r)',
        padding:      '7px 10px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: 'var(--chalk2)' }}>
            {entry.actor_label}
          </span>
          <span style={{ fontSize: 10, color: 'var(--chalk3)' }}>
            {toRelative(entry.created_at)}
          </span>
        </div>
        <div style={{ fontSize: 12, color: 'var(--chalk)', lineHeight: 1.5 }}>
          <BodyText body={entry.body} />
        </div>
      </div>
    </div>
  );
}

// ── Card treatment ────────────────────────────────────────────

function CardEvent({
  entry,
  config,
  onReply,
}: {
  entry:   TimelineEntry;
  config:  EventConfig;
  onReply: (parentId: string) => void;
}) {
  const isUser = entry.event_type === 'user_comment';

  return (
    <div style={{
      display:      'flex',
      gap:          10,
      animation:    'fadeUp .2s ease both',
    }}>
      <Avatar label={entry.actor_label} />

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 5, flexWrap: 'wrap' }}>
          <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--chalk)' }}>
            {entry.actor_label}
          </span>

          {!isUser && config.label && (
            <span style={{
              fontSize:     9,
              fontWeight:   700,
              letterSpacing:'.08em',
              color:        config.tagColor ?? 'var(--chalk3)',
              background:   config.tagBg   ?? 'var(--bg4)',
              padding:      '1px 5px',
              borderRadius: 4,
            }}>
              {config.icon} {config.label}
            </span>
          )}

          <span style={{ fontSize: 10, color: 'var(--chalk3)', marginLeft: 'auto' }}>
            <span title={toDateTime(entry.created_at)}>{toRelative(entry.created_at)}</span>
          </span>
        </div>

        {/* Body */}
        <div style={{
          background:   entry.is_system ? 'var(--bg3)' : 'var(--bg2)',
          border:       '1px solid var(--wire)',
          borderLeft:   config.accentColor !== 'transparent'
            ? `3px solid ${config.accentColor}`
            : '1px solid var(--wire)',
          borderRadius: 'var(--r)',
          padding:      '9px 12px',
          fontSize:     12,
          color:        entry.is_system ? 'var(--chalk2)' : 'var(--chalk)',
          lineHeight:   1.55,
        }}>
          <BodyText body={entry.body} />
        </div>

        {/* Reply action (user comments only, non-system) */}
        {isUser && (
          <button
            onClick={() => onReply(entry.id)}
            style={{
              marginTop:  4,
              background: 'none',
              border:     'none',
              color:      'var(--chalk3)',
              fontSize:   10,
              cursor:     'pointer',
              padding:    '2px 4px',
              fontFamily: 'var(--font)',
            }}
          >
            ↩ Reply
          </button>
        )}

        {/* Replies */}
        {entry.replies?.map(r => <ReplyCard key={r.id} entry={r} />)}
      </div>
    </div>
  );
}

// ── Banner treatment ──────────────────────────────────────────

function BannerEvent({ entry, config }: { entry: TimelineEntry; config: EventConfig }) {
  return (
    <div style={{
      background:   config.bannerBg ?? 'rgba(255,255,255,.03)',
      border:       `1px solid ${config.accentColor}33`,
      borderLeft:   `4px solid ${config.accentColor}`,
      borderRadius: 'var(--r)',
      padding:      '10px 14px',
      display:      'flex',
      alignItems:   'center',
      gap:          10,
      animation:    'fadeUp .2s ease both',
    }}>
      {/* Icon dot */}
      <span style={{
        fontSize:   16,
        color:      config.accentColor,
        flexShrink: 0,
        lineHeight: 1,
      }}>
        {config.icon}
      </span>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 3 }}>
          <span style={{
            fontSize:     9,
            fontWeight:   700,
            letterSpacing:'.1em',
            color:        config.tagColor,
            background:   config.tagBg,
            padding:      '1px 6px',
            borderRadius: 4,
          }}>
            {config.label}
          </span>
          <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--chalk2)' }}>
            {entry.actor_label}
          </span>
          <span style={{ fontSize: 10, color: 'var(--chalk3)', marginLeft: 'auto' }}>
            {toRelative(entry.created_at)}
          </span>
        </div>
        <div style={{ fontSize: 12, color: 'var(--chalk)', lineHeight: 1.5 }}>
          <BodyText body={entry.body} />
        </div>
      </div>
    </div>
  );
}

// ── Main export ───────────────────────────────────────────────

export interface TimelineEventProps {
  entry:   TimelineEntry;
  onReply: (parentId: string) => void;
}

export function TimelineEvent({ entry, onReply }: TimelineEventProps) {
  const config = EVENT_CONFIG[entry.event_type] ?? EVENT_CONFIG.state_change;

  if (config.treatment === 'banner') {
    return <BannerEvent entry={entry} config={config} />;
  }
  return <CardEvent entry={entry} config={config} onReply={onReply} />;
}
