// ============================================================
// STAGE COMMENT THREAD COMPONENT
// Displays comments for a pipeline stage with threading
// ============================================================

import type { StageComment } from '@shared';

interface StageCommentThreadProps {
  stageId: string;
  projectId: string;
  comments: StageComment[];
  readOnly?: boolean;
}

export function StageCommentThread({ comments }: StageCommentThreadProps) {
  const sortedComments = [...comments].sort((a, b) =>
    new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
  );

  const getCommentTypeColor = (type: string) => {
    switch (type) {
      case 'progress': return 'var(--brand)';
      case 'issue': return 'var(--rose)';
      case 'note': return 'var(--amber)';
      default: return 'var(--chalk2)';
    }
  };

  const getCommentTypeIcon = (type: string) => {
    switch (type) {
      case 'progress': return '📈';
      case 'issue': return '⚠️';
      case 'note': return '📝';
      default: return '💬';
    }
  };

  if (comments.length === 0) {
    return (
      <div style={{
        padding: 16,
        textAlign: 'center',
        color: 'var(--chalk2)',
        fontSize: 14
      }}>
        No comments yet
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      {sortedComments.map((comment) => (
        <div
          key={comment.id}
          style={{
            display: 'flex',
            gap: 12,
            padding: 12,
            background: 'var(--bg)',
            border: '1px solid var(--wire2)',
            borderRadius: 8
          }}
        >
          {/* Avatar */}
          <div style={{
            width: 32,
            height: 32,
            borderRadius: '50%',
            background: 'var(--brand)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 14,
            fontWeight: 600,
            color: '#050810',
            flexShrink: 0
          }}>
            {comment.authorName.charAt(0).toUpperCase()}
          </div>

          {/* Comment Content */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              marginBottom: 4
            }}>
              <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--chalk)' }}>
                {comment.authorName}
              </span>
              <span style={{
                fontSize: 11,
                padding: '2px 6px',
                borderRadius: 4,
                background: `${getCommentTypeColor(comment.commentType)}20`,
                color: getCommentTypeColor(comment.commentType),
                fontWeight: 600
              }}>
                {getCommentTypeIcon(comment.commentType)} {comment.commentType}
              </span>
              <span style={{
                fontSize: 11,
                color: 'var(--chalk2)'
              }}>
                {new Date(comment.createdAt).toLocaleString()}
              </span>
            </div>

            <div style={{
              fontSize: 14,
              color: 'var(--chalk)',
              lineHeight: 1.5,
              whiteSpace: 'pre-wrap'
            }}>
              {comment.body}
            </div>

            {/* Attachments */}
            {comment.attachments && comment.attachments.length > 0 && (
              <div style={{ marginTop: 8, display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {comment.attachments.map((attachment: any, index: number) => (
                  <div
                    key={index}
                    style={{
                      padding: '4px 8px',
                      borderRadius: 4,
                      background: 'var(--bg2)',
                      border: '1px solid var(--wire2)',
                      fontSize: 12,
                      color: 'var(--chalk2)',
                      cursor: 'pointer'
                    }}
                  >
                    📎 {attachment.filename || `Attachment ${index + 1}`}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}