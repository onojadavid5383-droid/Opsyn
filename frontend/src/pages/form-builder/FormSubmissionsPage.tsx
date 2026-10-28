// ============================================================
// OPSYN — Form Submissions List + Detail (Phase 7)
// src/pages/form-builder/FormSubmissionsPage.tsx
//
// Route: /form-builder/:schemaId/submissions
// Shows all submissions for a given schema.
// Inline detail view with field snapshot rendering (read-only).
// ============================================================

import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { formBuilderApi, type FormSubmission } from '../../api/form-builder.api';
import FormRenderer from '../../components/form-builder/FormRenderer';
import { GlassModal, GlassSelect } from '../../components/glass';

// ── Utilities ─────────────────────────────────────────────────

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: 'medium', timeStyle: 'short',
  });
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, { bg: string; color: string }> = {
    draft:     { bg: 'rgba(255,180,0,0.15)',   color: '#ffb400'             },
    submitted: { bg: 'rgba(0,140,255,0.15)',   color: '#4da6ff'             },
    approved:  { bg: 'rgba(0,194,168,0.15)',   color: 'var(--color-teal)'   },
    rejected:  { bg: 'rgba(255,80,80,0.15)',   color: '#ff5a5a'             },
  };
  const c = map[status] ?? map.draft;
  return (
    <span style={{
      padding: '2px 8px', borderRadius: 4,
      fontSize: 10, fontWeight: 700,
      fontFamily: 'var(--font-display)',
      textTransform: 'uppercase' as const, letterSpacing: '0.08em',
      background: c.bg, color: c.color,
    }}>
      {status}
    </span>
  );
}

// ── Submission Detail Modal ────────────────────────────────────

function SubmissionDetailModal({
  submission, schemaId, onClose,
}: {
  submission: FormSubmission;
  schemaId:   string;
  onClose:    () => void;
}) {
  const qc = useQueryClient();

  const approveMut = useMutation({
    mutationFn: () => formBuilderApi.approveSubmission(submission.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['form-builder', 'submissions', schemaId] });
      onClose();
    },
  });

  const rejectMut = useMutation({
    mutationFn: (reason: string) => formBuilderApi.rejectSubmission(submission.id, reason),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['form-builder', 'submissions', schemaId] });
      onClose();
    },
  });

  const [showRejectInput, setShowRejectInput] = useState(false);
  const [rejectReason,    setRejectReason]    = useState('');
  const [exportError, setExportError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const busy = approveMut.isPending || rejectMut.isPending;

  const handleExport = async () => {
    setExporting(true);
    setExportError(null);
    try {
      const blob = await formBuilderApi.exportSubmission(submission.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `submission_${submission.id}.json`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      setExportError('Could not export this submission. Please try again.');
    } finally {
      setExporting(false);
    }
  };

  return (
    <GlassModal open onClose={onClose} ariaLabel="Submission details" size="lg" hideClose>
        {/* Modal header */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '14px 16px',
          borderBottom: '1px solid var(--color-border)', flexShrink: 0,
        }}>
          <div style={{ flex: 1 }}>
            <div style={{
              fontSize: 14, fontWeight: 700,
              fontFamily: 'var(--font-display)', color: 'var(--chalk1)',
            }}>
              Submission Detail
            </div>
            <div style={{
              fontSize: 10, color: 'var(--text-muted)',
              fontFamily: 'monospace',
            }}>
              {submission.id}
            </div>
          </div>
          <StatusPill status={submission.status} />
          <button
            onClick={handleExport}
            disabled={exporting}
            style={{
              padding: '4px 12px', borderRadius: 6,
              border: '1px solid var(--color-border)',
              background: 'rgba(255,255,255,0.07)',
              color: 'var(--chalk2)',
              fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 600,
              cursor: exporting ? 'wait' : 'pointer', opacity: exporting ? 0.6 : 1,
            }}
          >
            {exporting ? 'Exporting…' : 'Export JSON'}
          </button>
          <button
            onClick={onClose}
            style={{
              background: 'none', border: 'none', cursor: 'pointer',
              color: 'var(--text-muted)', fontSize: 20, lineHeight: 1, padding: 4,
            }}
          >
            ×
          </button>
        </div>

        {exportError && <div role="alert" style={{ color: '#ff5a5a', fontSize: 12, padding: '8px 16px' }}>{exportError}</div>}

        {/* Modal body — read-only renderer */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 20, scrollbarWidth: 'thin' as const }}>
          <FormRenderer
            schemaId={schemaId}
            entityType={submission.entity_type}
            entityId={submission.entity_id ?? undefined}
            viewSubmission={submission}
          />
        </div>

        {/* Modal footer — approve/reject (only for submitted) */}
        {submission.status === 'submitted' && (
          <div style={{
            padding: '12px 16px',
            borderTop: '1px solid var(--color-border)',
            display: 'flex', flexDirection: 'column', gap: 8,
            flexShrink: 0,
          }}>
            {!showRejectInput ? (
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                <button
                  onClick={() => setShowRejectInput(true)}
                  disabled={busy}
                  style={btnStyle(false, true, busy)}
                >
                  Reject
                </button>
                <button
                  onClick={() => approveMut.mutate()}
                  disabled={busy}
                  style={btnStyle(true, false, busy)}
                >
                  {approveMut.isPending ? 'Approving…' : 'Approve'}
                </button>
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <input
                  style={{
                    width: '100%', boxSizing: 'border-box',
                    padding: '8px 11px', borderRadius: 6,
                    border: '1px solid var(--color-border)',
                    background: 'rgba(255,255,255,0.06)',
                    color: 'var(--chalk1)',
                    fontFamily: 'var(--font-display)', fontSize: 12, outline: 'none',
                  }}
                  placeholder="Rejection reason (required)"
                  value={rejectReason}
                  onChange={e => setRejectReason(e.target.value)}
                />
                <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                  <button
                    onClick={() => { setShowRejectInput(false); setRejectReason(''); }}
                    style={btnStyle(false, false, false)}
                  >
                    Cancel
                  </button>
                  <button
                    disabled={!rejectReason.trim() || busy}
                    onClick={() => rejectMut.mutate(rejectReason.trim())}
                    style={btnStyle(false, true, busy || !rejectReason.trim())}
                  >
                    {rejectMut.isPending ? 'Rejecting…' : 'Confirm Reject'}
                  </button>
                </div>
              </div>
            )}
          </div>
        )}
      </GlassModal>
  );
}

// ── Button helper ─────────────────────────────────────────────

function btnStyle(primary: boolean, danger: boolean, disabled: boolean): React.CSSProperties {
  return {
    padding: '7px 18px', borderRadius: 6,
    border: primary ? 'none' : `1px solid ${danger ? 'rgba(255,80,80,0.40)' : 'var(--color-border)'}`,
    background: primary ? 'var(--color-teal)' : 'rgba(255,255,255,0.07)',
    color: primary ? 'var(--color-navy)' : danger ? 'rgba(255,80,80,0.85)' : 'var(--chalk2)',
    fontFamily: 'var(--font-display)', fontSize: 12, fontWeight: 600,
    cursor: disabled ? 'default' : 'pointer', opacity: disabled ? 0.5 : 1,
  };
}

// ══ SUBMISSIONS PAGE ══════════════════════════════════════════

export default function FormSubmissionsPage() {
  const { schemaId } = useParams<{ schemaId: string }>();
  const navigate     = useNavigate();

  const [statusFilter,     setStatusFilter]     = useState('');
  const [page,             setPage]             = useState(1);
  const [selectedSub,      setSelectedSub]      = useState<FormSubmission | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const PAGE_SIZE = 20;

  const schemaQ = useQuery({
    queryKey: ['form-builder', 'schema', schemaId],
    queryFn:  () => formBuilderApi.getSchema(schemaId!),
    enabled:  !!schemaId,
  });

  const subsQ = useQuery({
    queryKey: ['form-builder', 'submissions', schemaId, statusFilter, page],
    queryFn:  () => formBuilderApi.getSubmissions({
      schema_id: schemaId,
      status:    statusFilter || undefined,
      page,
      limit:     PAGE_SIZE,
    }),
    enabled: !!schemaId,
  });

  const submissions = subsQ.data?.submissions ?? [];
  const total       = subsQ.data?.total ?? 0;
  const totalPages  = Math.ceil(total / PAGE_SIZE);

  const exportWorkbook = async () => {
    if (!schemaId) return;
    setExporting(true);
    setExportError(null);
    try {
      const blob = await formBuilderApi.exportSubmissions(schemaId);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `${schemaQ.data?.machine_name ?? 'form'}_submissions.xlsx`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      setExportError('Could not export submissions. Please try again.');
    } finally {
      setExporting(false);
    }
  };

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

  return (
    <div data-surface="console" style={{
      display: 'flex', flexDirection: 'column',
      height: '100%', overflow: 'hidden',
      background: 'var(--color-bg)',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12,
        padding: '12px 20px',
        borderBottom: '1px solid var(--color-border)',
        background: 'var(--color-surface)', flexShrink: 0,
      }}>
        <button
          onClick={() => navigate(`/form-builder/${schemaId}`)}
          style={{
            background: 'none', border: 'none', cursor: 'pointer',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-display)', fontSize: 12,
          }}
        >
          ← Builder
        </button>
        <h1 style={{
          fontSize: 14, fontWeight: 700, margin: 0,
          fontFamily: 'var(--font-display)', color: 'var(--chalk1)',
        }}>
          Submissions
          {schemaQ.data && (
            <span style={{ color: 'var(--text-muted)', fontWeight: 400, marginLeft: 8, fontSize: 12 }}>
              {schemaQ.data.name}
            </span>
          )}
        </h1>
        <div style={{ flex: 1 }} />

        <button onClick={exportWorkbook} disabled={exporting} style={{ padding: '5px 12px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'rgba(255,255,255,0.07)', color: 'var(--chalk2)', fontFamily: 'var(--font-display)', fontSize: 11, cursor: exporting ? 'wait' : 'pointer', opacity: exporting ? 0.6 : 1 }}>
          {exporting ? 'Exporting…' : 'Export XLSX'}
        </button>

        {/* Status filter */}
        <GlassSelect value={String(statusFilter)} onChange={v => { setStatusFilter(v); setPage(1); }} options={[{ value: 'draft', label: 'Draft' }, { value: 'submitted', label: 'Submitted' }, { value: 'approved', label: 'Approved' }, { value: 'rejected', label: 'Rejected' }]} placeholder={'All statuses'} ariaLabel="Filter by status" compact />

        <button
          onClick={() => navigate(`/form-builder/${schemaId}/preview`)}
          style={{
            padding: '5px 14px', borderRadius: 6,
            border: '1px solid var(--color-border)',
            background: 'rgba(255,255,255,0.07)',
            color: 'var(--chalk2)',
            fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 600,
            cursor: 'pointer',
          }}
        >
          + New Submission
        </button>
      </div>

      {exportError && <div role="alert" style={{ padding: '8px 20px', color: '#ff5a5a', fontSize: 12 }}>{exportError}</div>}

      {/* Table */}
      <div style={{ flex: 1, overflowY: 'auto', scrollbarWidth: 'thin' as const }}>
        {subsQ.isLoading && (
          <div style={{
            padding: '40px', textAlign: 'center',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-display)', fontSize: 13,
          }}>
            Loading submissions…
          </div>
        )}

        {!subsQ.isLoading && submissions.length === 0 && (
          <div style={{
            padding: '60px', textAlign: 'center',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-display)', fontSize: 13,
          }}>
            {statusFilter
              ? `No ${statusFilter} submissions found.`
              : 'No submissions yet.'}
          </div>
        )}

        {submissions.length > 0 && (
          <table style={{
            width: '100%', borderCollapse: 'collapse',
            fontFamily: 'var(--font-display)',
          }}>
            <thead>
              <tr style={{
                borderBottom: '1px solid var(--color-border)',
                background: 'var(--color-surface)',
              }}>
                {['Status', 'Submitted At', 'Entity Type', 'Entity ID', 'Submitted By', ''].map(h => (
                  <th key={h} style={{
                    padding: '10px 16px', textAlign: 'left' as const,
                    fontSize: 10, fontWeight: 700,
                    color: 'var(--text-muted)',
                    letterSpacing: '0.10em', textTransform: 'uppercase' as const,
                    whiteSpace: 'nowrap' as const,
                  }}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {submissions.map(sub => (
                <tr
                  key={sub.id}
                  onClick={() => setSelectedSub(sub)}
                  style={{
                    borderBottom: '1px solid var(--color-border)',
                    cursor: 'pointer',
                    transition: 'background 100ms',
                  }}
                  onMouseEnter={e => {
                    (e.currentTarget as HTMLElement).style.background = 'rgba(255,255,255,0.03)';
                  }}
                  onMouseLeave={e => {
                    (e.currentTarget as HTMLElement).style.background = 'transparent';
                  }}
                >
                  <td style={{ padding: '12px 16px' }}>
                    <StatusPill status={sub.status} />
                  </td>
                  <td style={{
                    padding: '12px 16px', fontSize: 12,
                    color: 'var(--chalk2)',
                  }}>
                    {fmtDate(sub.submitted_at)}
                  </td>
                  <td style={{
                    padding: '12px 16px', fontSize: 12,
                    color: 'var(--chalk2)',
                  }}>
                    {sub.entity_type}
                  </td>
                  <td style={{
                    padding: '12px 16px', fontSize: 11,
                    color: 'var(--text-muted)', fontFamily: 'monospace',
                  }}>
                    {sub.entity_id
                      ? sub.entity_id.slice(0, 8) + '…'
                      : '—'}
                  </td>
                  <td style={{
                    padding: '12px 16px', fontSize: 11,
                    color: 'var(--text-muted)', fontFamily: 'monospace',
                  }}>
                    {sub.submitted_by
                      ? sub.submitted_by.slice(0, 8) + '…'
                      : '—'}
                  </td>
                  <td style={{ padding: '12px 16px', textAlign: 'right' as const }}>
                    <button
                      onClick={e => { e.stopPropagation(); setSelectedSub(sub); }}
                      style={{
                        background: 'none', border: 'none',
                        cursor: 'pointer', color: 'var(--color-teal)',
                        fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 600,
                        padding: 0,
                      }}
                    >
                      View →
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
          padding: '12px 20px',
          borderTop: '1px solid var(--color-border)',
          background: 'var(--color-surface)', flexShrink: 0,
        }}>
          <button
            onClick={() => setPage(p => Math.max(1, p - 1))}
            disabled={page === 1}
            style={{
              padding: '4px 12px', borderRadius: 6,
              border: '1px solid var(--color-border)',
              background: 'rgba(255,255,255,0.06)',
              color: page === 1 ? 'rgba(255,255,255,0.25)' : 'var(--chalk2)',
              fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 600,
              cursor: page === 1 ? 'default' : 'pointer',
            }}
          >
            ← Prev
          </button>
          <span style={{
            fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-display)',
          }}>
            Page {page} of {totalPages} ({total} total)
          </span>
          <button
            onClick={() => setPage(p => Math.min(totalPages, p + 1))}
            disabled={page === totalPages}
            style={{
              padding: '4px 12px', borderRadius: 6,
              border: '1px solid var(--color-border)',
              background: 'rgba(255,255,255,0.06)',
              color: page === totalPages ? 'rgba(255,255,255,0.25)' : 'var(--chalk2)',
              fontFamily: 'var(--font-display)', fontSize: 11, fontWeight: 600,
              cursor: page === totalPages ? 'default' : 'pointer',
            }}
          >
            Next →
          </button>
        </div>
      )}

      {/* Detail modal */}
      {selectedSub && (
        <SubmissionDetailModal
          submission={selectedSub}
          schemaId={schemaId}
          onClose={() => setSelectedSub(null)}
        />
      )}
    </div>
  );
}
