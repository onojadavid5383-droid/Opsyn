// ============================================================
// OPSYN — Form Preview & Test Page (Phase 7)
// src/pages/form-builder/FormPreviewPage.tsx
//
// Route: /form-builder/:schemaId/preview
// Lets admins test the FormRenderer for any published schema
// before embedding it in a module.
// ============================================================

import { useParams, useNavigate } from 'react-router-dom';
import FormRenderer from '../../components/form-builder/FormRenderer';
import type { FormSubmission } from '../../api/form-builder.api';

export default function FormPreviewPage() {
  const { schemaId } = useParams<{ schemaId: string }>();
  const navigate     = useNavigate();

  if (!schemaId) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100%', color: 'var(--text-muted)',
        fontFamily: 'var(--font-display)', fontSize: 13,
      }}>
        No schema selected.
      </div>
    );
  }

  const handleSubmitSuccess = (_sub: FormSubmission) => {
    navigate(`/form-builder/${schemaId}/submissions`);
  };

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      height: '100%', overflow: 'hidden',
      background: 'var(--color-bg)',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '12px 24px',
        borderBottom: '1px solid var(--color-border)',
        background: 'var(--color-surface)', flexShrink: 0,
      }}>
        <button
          onClick={() => navigate(`/form-builder/${schemaId}`)}
          style={{
            background: 'none', border: 'none',
            cursor: 'pointer', color: 'var(--text-muted)',
            fontFamily: 'var(--font-display)', fontSize: 12,
            display: 'flex', alignItems: 'center', gap: 4,
          }}
        >
          ← Builder
        </button>
        <div style={{
          fontSize: 13, fontWeight: 600,
          fontFamily: 'var(--font-display)', color: 'var(--chalk2)',
        }}>
          Preview & Test
        </div>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => navigate(`/form-builder/${schemaId}/submissions`)}
          style={{
            padding: '5px 14px', borderRadius: 6,
            border: '1px solid var(--color-border)',
            background: 'rgba(255,255,255,0.07)',
            color: 'var(--chalk2)',
            fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          View Submissions →
        </button>
      </div>

      {/* Form container */}
      <div style={{
        flex: 1, overflowY: 'auto',
        padding: '32px 0',
        display: 'flex', justifyContent: 'center',
        scrollbarWidth: 'thin' as const,
      }}>
        <div style={{
          width: '100%', maxWidth: 720,
          padding: '0 24px',
        }}>
          <div style={{
            padding: '28px', borderRadius: 10,
            border: '1px solid var(--color-border)',
            background: 'var(--color-surface)',
          }}>
            <FormRenderer
              schemaId={schemaId}
              entityType="preview"
              onSubmitSuccess={handleSubmitSuccess}
              onCancel={() => navigate(`/form-builder/${schemaId}`)}
            />
          </div>

          <div style={{
            marginTop: 16, textAlign: 'center',
            fontSize: 11, color: 'var(--text-muted)',
            fontFamily: 'var(--font-display)',
          }}>
            Preview mode — submissions are real and will appear in the submissions log
          </div>
        </div>
      </div>
    </div>
  );
}
