// ============================================================
// OPSYN — TimelineCommentForm
// Free-form work log comment entry (blueprint Section 6.2)
// Comments are pure work logs — no keywords trigger state changes
// ============================================================

import React, { useState, useRef, useEffect } from 'react';
import type { TimelineEntityType } from './types';
import { useAddTimelineComment } from '../../hooks/index';

export interface TimelineCommentFormProps {
  entityType:   TimelineEntityType;
  entityId:     string;
  replyToId?:   string | null;
  replyToActor?: string | null;
  onCancelReply?: () => void;
  placeholder?: string;
  autoFocus?:   boolean;
}

export function TimelineCommentForm({
  entityType,
  entityId,
  replyToId      = null,
  replyToActor   = null,
  onCancelReply,
  placeholder    = 'Add a work log entry… (@mention a colleague)',
  autoFocus      = false,
}: TimelineCommentFormProps) {
  const [body, setBody]       = useState('');
  const textareaRef           = useRef<HTMLTextAreaElement>(null);
  const { mutate, isPending } = useAddTimelineComment();

  useEffect(() => {
    if (autoFocus || replyToId) textareaRef.current?.focus();
  }, [autoFocus, replyToId]);

  // Auto-grow textarea
  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setBody(e.target.value);
    const el = e.target;
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 200) + 'px';
  };

  const handleSubmit = () => {
    const trimmed = body.trim();
    if (!trimmed || isPending) return;

    // Parse @mentions from body
    const mentionMatches = trimmed.match(/@(\w[\w.-]*)/g) ?? [];
    const mentions = mentionMatches.map(m => m.slice(1));

    mutate(
      {
        entityType,
        entityId,
        payload: {
          body:      trimmed,
          mentions:  mentions.length ? mentions : undefined,
          parent_id: replyToId ?? undefined,
        },
      },
      {
        onSuccess: () => {
          setBody('');
          if (textareaRef.current) textareaRef.current.style.height = 'auto';
          onCancelReply?.();
        },
      }
    );
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Ctrl+Enter or Cmd+Enter to submit
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div style={{
      background:   'var(--bg2)',
      border:       '1px solid var(--wire2)',
      borderRadius: 'var(--r2)',
      overflow:     'hidden',
    }}>
      {/* Reply banner */}
      {replyToId && replyToActor && (
        <div style={{
          display:       'flex',
          alignItems:    'center',
          justifyContent:'space-between',
          padding:       '6px 12px',
          background:    'var(--bg3)',
          borderBottom:  '1px solid var(--wire)',
          fontSize:      10,
          color:         'var(--chalk3)',
        }}>
          <span>↩ Replying to <strong style={{ color: 'var(--chalk2)' }}>{replyToActor}</strong></span>
          <button
            onClick={onCancelReply}
            style={{
              background: 'none', border: 'none',
              color: 'var(--chalk3)', cursor: 'pointer',
              fontSize: 14, padding: 0, lineHeight: 1,
            }}
          >×</button>
        </div>
      )}

      {/* Textarea */}
      <textarea
        ref={textareaRef}
        value={body}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
        placeholder={placeholder}
        rows={2}
        style={{
          width:       '100%',
          background:  'transparent',
          border:      'none',
          outline:     'none',
          padding:     '10px 12px',
          color:       'var(--chalk)',
          fontFamily:  'var(--font)',
          fontSize:    12,
          lineHeight:  1.55,
          resize:      'none',
          minHeight:   64,
          boxSizing:   'border-box',
        }}
      />

      {/* Footer bar */}
      <div style={{
        display:        'flex',
        alignItems:     'center',
        justifyContent: 'space-between',
        padding:        '6px 10px 8px',
        borderTop:      body.trim() ? '1px solid var(--wire)' : 'none',
      }}>
        <span style={{ fontSize: 10, color: 'var(--chalk3)' }}>
          {body.trim() ? 'Ctrl+Enter to post' : ''}
        </span>

        <div style={{ display: 'flex', gap: 6 }}>
          {replyToId && (
            <button
              onClick={onCancelReply}
              style={{
                background: 'none',
                border:     '1px solid var(--wire2)',
                borderRadius:'var(--r)',
                padding:    '5px 10px',
                color:      'var(--chalk3)',
                fontSize:   11,
                cursor:     'pointer',
                fontFamily: 'var(--font)',
              }}
            >
              Cancel
            </button>
          )}
          <button
            onClick={handleSubmit}
            disabled={!body.trim() || isPending}
            style={{
              background:  body.trim() && !isPending ? 'var(--brand)' : 'rgba(255,255,255,.05)',
              border:      'none',
              borderRadius:'var(--r)',
              padding:     '5px 14px',
              color:       body.trim() && !isPending ? '#050810' : 'var(--chalk3)',
              fontSize:    11,
              fontWeight:  700,
              cursor:      body.trim() && !isPending ? 'pointer' : 'not-allowed',
              fontFamily:  'var(--font)',
              transition:  'all .15s',
              boxShadow:   body.trim() ? '0 0 12px rgba(6,182,212,.2)' : 'none',
            }}
          >
            {isPending ? 'Posting…' : 'Post'}
          </button>
        </div>
      </div>
    </div>
  );
}
