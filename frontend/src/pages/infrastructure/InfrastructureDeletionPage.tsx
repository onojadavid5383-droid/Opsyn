// ============================================================
// OPSYN — InfrastructureDeletionPage
// Bulk FTTH asset soft-delete: splitter / cabinet / OLT
//
// Three-step workflow:
//   Step 1 — Select asset type + choose deletion xlsx file
//   Step 2 — Match preview (matched vs unmatched rows + detail table)
//   Step 3 — Execute confirmation (deleted count or failure)
// ============================================================

import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { infrastructureApi } from '../../api/index';
import { useUIStore } from '../../store/ui.store';
import { Button, Spinner } from '../../components/ui';
import { ErrorBoundary } from '../../components/ErrorBoundary';
import type { ApiError } from '../../api/client';
import { ArrowLeft } from 'lucide-react';
import { PageHeader } from '../../components/layout/Page';

// ── Toast helper ─────────────────────────────────────────────
function useToast() {
  const { addToast } = useUIStore();
  return {
    success: (title: string, msg?: string) => addToast({ type: 'success', title, message: msg }),
    error:   (title: string, msg?: string) => addToast({ type: 'error',   title, message: msg }),
    info:    (title: string, msg?: string) => addToast({ type: 'info',    title, message: msg }),
  };
}

// ── Types ─────────────────────────────────────────────────────
type AssetType = 'splitter' | 'cabinet' | 'olt';
type StepId    = 1 | 2 | 3;

interface MatchDetail {
  key:      Record<string, string | number>;
  status:   'matched' | 'unmatched';
  asset_id: string | null;
  reason:   string | null;
}

interface DeletionSession {
  id:               string;
  asset_type:       string;
  status:           string;
  original_filename: string;
  total_rows:       number;
  matched_rows:     number;
  unmatched_rows:   number;
  deleted_rows:     number | null;
  match_details:    MatchDetail[];
}

interface DeletionResult {
  session_id:   string;
  deleted_rows: number;
  status:       string;    // 'executed' | 'failed'
  error?:       string;
}

const ASSET_OPTIONS: { label: string; value: AssetType; description: string; keyColumns: string[] }[] = [
  {
    label: 'Splitter Boxes', value: 'splitter',
    description: 'Match by box_id + splitter_level',
    keyColumns: ['box_id', 'splitter_level'],
  },
  {
    label: 'Cabinets', value: 'cabinet',
    description: 'Match by cabinet_id + capacity',
    keyColumns: ['cabinet_id', 'capacity'],
  },
  {
    label: 'OLTs', value: 'olt',
    description: 'Match by name',
    keyColumns: ['name'],
  },
];

// ── Step indicator ────────────────────────────────────────────
function StepIndicator({ current }: { current: StepId }) {
  const steps = [
    { id: 1 as StepId, label: 'Select & Upload' },
    { id: 2 as StepId, label: 'Review Matches' },
    { id: 3 as StepId, label: 'Execute' },
  ];
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, marginBottom: 28 }}>
      {steps.map((s, i) => (
        <div key={s.id} style={{ display: 'flex', alignItems: 'center', flex: i < steps.length - 1 ? 1 : 'none' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
            <div style={{
              width: 28, height: 28, borderRadius: '50%',
              background: current > s.id ? 'var(--error)' : current === s.id ? 'var(--error)' : 'var(--surface2)',
              border: `2px solid ${current >= s.id ? 'var(--error)' : 'var(--border)'}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 12, fontWeight: 600,
              color: current >= s.id ? '#fff' : 'var(--chalk3)',
            }}>
              {current > s.id ? '✓' : s.id}
            </div>
            <span style={{
              fontSize: 11, whiteSpace: 'nowrap',
              color: current === s.id ? 'var(--chalk1)' : 'var(--chalk3)',
              fontWeight: current === s.id ? 600 : 400,
            }}>{s.label}</span>
          </div>
          {i < steps.length - 1 && (
            <div style={{
              flex: 1, height: 2, margin: '0 8px', marginBottom: 18,
              background: current > s.id ? 'var(--error)' : 'var(--border)',
            }} />
          )}
        </div>
      ))}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────
function InfrastructureDeletionContent() {
  const navigate = useNavigate();
  const toast    = useToast();
  const fileRef  = useRef<HTMLInputElement>(null);

  const [step,         setStep]         = useState<StepId>(1);
  const [assetType,    setAssetType]    = useState<AssetType>('splitter');
  const [file,         setFile]         = useState<File | null>(null);
  const [session,      setSession]      = useState<DeletionSession | null>(null);
  const [execResult,   setExecResult]   = useState<DeletionResult | null>(null);
  const [showUnmatched, setShowUnmatched] = useState(false);

  // ── Mutations ───────────────────────────────────────────────
  const uploadMutation = useMutation({
    mutationFn: ({ assetType, file }: { assetType: AssetType; file: File }) =>
      infrastructureApi.uploadDeletionFile(assetType, file),
    onSuccess: (data: DeletionSession) => {
      setSession(data);
      setStep(2);
    },
    onError: (e: ApiError) => {
      const errDetail = e?.response?.data?.detail;
      const msg = Array.isArray(errDetail?.errors)
        ? errDetail.errors[0]
        : (typeof errDetail === 'string' ? errDetail : e?.detail ?? 'Upload failed');
      toast.error('Upload failed', msg);
    },
  });

  const executeMutation = useMutation({
    mutationFn: (sessionId: string) => infrastructureApi.executeDeletion(sessionId),
    onSuccess: (data: DeletionResult) => {
      setExecResult(data);
      setStep(3);
      if (data.status === 'executed') {
        toast.success('Deletion complete', `${data.deleted_rows} record(s) soft-deleted`);
      } else {
        toast.error('Deletion failed', data.error ?? 'Database error — no records were deleted');
      }
    },
    onError: (e: ApiError) => {
      toast.error('Execute failed', e?.detail ?? 'Unknown error');
    },
  });

  // ── Handlers ────────────────────────────────────────────────
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFile(e.target.files?.[0] ?? null);
  };

  const handleUpload = () => {
    if (!file) { toast.error('No file selected', 'Please choose an xlsx file first'); return; }
    uploadMutation.mutate({ assetType, file });
  };

  const handleExecute = () => {
    if (!session) return;
    executeMutation.mutate(session.id);
  };

  const handleReset = () => {
    setStep(1);
    setFile(null);
    setSession(null);
    setExecResult(null);
    setShowUnmatched(false);
    if (fileRef.current) fileRef.current.value = '';
  };

  // ── Render helpers ────────────────────────────────────────────
  const selectedOpt = ASSET_OPTIONS.find(o => o.value === assetType)!;

  const renderStep1 = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Danger callout */}
      <div style={{
        padding: '12px 16px', borderRadius: 8,
        background: 'var(--error-dim)', border: '1px solid var(--error)',
        display: 'flex', gap: 12, alignItems: 'flex-start',
      }}>
        <span style={{ fontSize: 18, flexShrink: 0 }}>⚠</span>
        <div style={{ fontSize: 12, color: 'var(--chalk2)' }}>
          <strong>This action performs a soft-delete.</strong> Matched assets will be marked
          as deleted and excluded from all queries. This can only be reversed manually by
          a database administrator.
        </div>
      </div>

      {/* Asset type selector */}
      <div>
        <label style={labelStyle}>Asset Type to Delete</label>
        <div style={{ display: 'flex', gap: 12, marginTop: 8 }}>
          {ASSET_OPTIONS.map(opt => (
            <button
              key={opt.value}
              onClick={() => setAssetType(opt.value)}
              style={{
                flex: 1, padding: '12px 16px', borderRadius: 8, cursor: 'pointer',
                background: assetType === opt.value ? 'rgba(220,38,38,0.08)' : 'var(--surface2)',
                border: `2px solid ${assetType === opt.value ? 'var(--error)' : 'var(--border)'}`,
                textAlign: 'left', transition: 'all 0.15s',
              }}
            >
              <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--chalk1)', marginBottom: 4 }}>
                {opt.label}
              </div>
              <div style={{ fontSize: 11, color: 'var(--chalk2)' }}>{opt.description}</div>
            </button>
          ))}
        </div>
      </div>

      {/* Key columns hint */}
      <div style={{ background: 'var(--surface2)', borderRadius: 8, padding: '12px 16px' }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--chalk2)', marginBottom: 6 }}>
          Required xlsx columns
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {selectedOpt.keyColumns.map(col => (
            <span key={col} style={chipStyle}>{col}</span>
          ))}
        </div>
        <div style={{ fontSize: 11, color: 'var(--chalk3)', marginTop: 8 }}>
          Each row must contain the exact key values that identify the asset in the database.
        </div>
      </div>

      {/* File input */}
      <div>
        <label style={labelStyle}>Deletion File (.xlsx)</label>
        <div style={{
          marginTop: 8, border: '2px dashed var(--border)', borderRadius: 10,
          padding: '24px', textAlign: 'center', background: 'var(--surface2)',
        }}>
          <input
            ref={fileRef}
            type="file"
            accept=".xlsx"
            onChange={handleFileChange}
            style={{ display: 'none' }}
            id="deletion-file-input"
          />
          <label htmlFor="deletion-file-input" style={{ cursor: 'pointer' }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>📂</div>
            <div style={{ fontSize: 13, color: 'var(--chalk2)', marginBottom: 4 }}>
              {file ? (
                <span style={{ color: 'var(--error)', fontWeight: 600 }}>{file.name}</span>
              ) : (
                <span>Click to choose a <strong>.xlsx</strong> file</span>
              )}
            </div>
            <div style={{ fontSize: 11, color: 'var(--chalk4)' }}>Max 10 MB</div>
          </label>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
        <Button variant="ghost" onClick={() => navigate('/infrastructure')}>Cancel</Button>
        <Button
          variant="danger"
          onClick={handleUpload}
          disabled={!file || uploadMutation.isPending}
        >
          {uploadMutation.isPending ? <><Spinner size="xs" /> Matching…</> : 'Upload & Match'}
        </Button>
      </div>
    </div>
  );

  const renderStep2 = () => {
    if (!session) return null;
    const matched   = session.match_details.filter(d => d.status === 'matched');
    const unmatched = session.match_details.filter(d => d.status === 'unmatched');
    const canExecute = matched.length > 0;

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        {/* Summary strip */}
        <div style={{ display: 'flex', gap: 12 }}>
          {[
            { label: 'Total Rows',    value: session.total_rows,     color: 'var(--chalk2)' },
            { label: 'Matched',       value: session.matched_rows,   color: 'var(--error)' },
            { label: 'Not Found',     value: session.unmatched_rows, color: 'var(--chalk3)' },
          ].map(s => (
            <div key={s.label} style={{
              flex: 1, background: 'var(--surface2)', borderRadius: 8,
              padding: '12px 16px', textAlign: 'center',
            }}>
              <div style={{ fontSize: 22, fontWeight: 700, color: s.color }}>{s.value}</div>
              <div style={{ fontSize: 11, color: 'var(--chalk3)', marginTop: 2 }}>{s.label}</div>
            </div>
          ))}
        </div>

        {/* Danger confirmation banner */}
        {canExecute && (
          <div style={{
            padding: '14px 18px', borderRadius: 10,
            background: 'rgba(220,38,38,0.07)', border: '1px solid var(--error)',
          }}>
            <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--chalk1)', marginBottom: 4 }}>
              {session.matched_rows} asset{session.matched_rows !== 1 ? 's' : ''} will be soft-deleted
            </div>
            <div style={{ fontSize: 12, color: 'var(--chalk3)' }}>
              These records will be excluded from all live queries immediately.
              {session.unmatched_rows > 0 && ` ${session.unmatched_rows} row(s) were not found and will be skipped.`}
            </div>
          </div>
        )}

        {/* Matched assets table */}
        {matched.length > 0 && (
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--chalk2)', marginBottom: 8 }}>
              Assets to be deleted ({matched.length})
            </div>
            <div style={{ maxHeight: 220, overflowY: 'auto', borderRadius: 8, border: '1px solid var(--border)' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: 'var(--surface2)' }}>
                    {selectedOpt.keyColumns.map(col => (
                      <th key={col} style={thStyle}>{col}</th>
                    ))}
                    <th style={thStyle}>Asset ID</th>
                  </tr>
                </thead>
                <tbody>
                  {matched.map((d, i) => (
                    <tr key={i} style={{ borderTop: '1px solid var(--border)' }}>
                      {selectedOpt.keyColumns.map(col => (
                        <td key={col} style={{ padding: '7px 12px', fontFamily: 'monospace', color: 'var(--chalk1)' }}>
                          {String(d.key[col] ?? '—')}
                        </td>
                      ))}
                      <td style={{ padding: '7px 12px', fontFamily: 'monospace', fontSize: 10, color: 'var(--chalk3)' }}>
                        {d.asset_id ? d.asset_id.slice(0, 8) + '…' : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* Unmatched toggle */}
        {unmatched.length > 0 && (
          <div>
            <button
              onClick={() => setShowUnmatched(v => !v)}
              style={{
                background: 'none', border: 'none', cursor: 'pointer', padding: 0,
                fontSize: 12, color: 'var(--chalk3)', display: 'flex', alignItems: 'center', gap: 6,
              }}
            >
              <span style={{ fontSize: 10 }}>{showUnmatched ? '▼' : '▶'}</span>
              {unmatched.length} row{unmatched.length !== 1 ? 's' : ''} not found in the database
            </button>
            {showUnmatched && (
              <div style={{ marginTop: 8, maxHeight: 160, overflowY: 'auto', borderRadius: 8, border: '1px solid var(--border)' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ background: 'var(--surface2)' }}>
                      {selectedOpt.keyColumns.map(col => (
                        <th key={col} style={thStyle}>{col}</th>
                      ))}
                      <th style={thStyle}>Reason</th>
                    </tr>
                  </thead>
                  <tbody>
                    {unmatched.map((d, i) => (
                      <tr key={i} style={{ borderTop: '1px solid var(--border)' }}>
                        {selectedOpt.keyColumns.map(col => (
                          <td key={col} style={{ padding: '7px 12px', fontFamily: 'monospace', color: 'var(--chalk2)' }}>
                            {String(d.key[col] ?? '—')}
                          </td>
                        ))}
                        <td style={{ padding: '7px 12px', color: 'var(--chalk3)', fontSize: 11 }}>
                          {d.reason ?? 'Not found'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
          <Button variant="ghost" onClick={handleReset}>← Start Over</Button>
          {canExecute ? (
            <Button
              variant="danger"
              onClick={handleExecute}
              disabled={executeMutation.isPending}
            >
              {executeMutation.isPending
                ? <><Spinner size="xs" /> Deleting…</>
                : `Delete ${session.matched_rows} asset${session.matched_rows !== 1 ? 's' : ''}`
              }
            </Button>
          ) : (
            <div style={{ fontSize: 12, color: 'var(--chalk3)', alignSelf: 'center' }}>
              No matched records — nothing to delete.
            </div>
          )}
        </div>
      </div>
    );
  };

  const renderStep3 = () => {
    if (!execResult) return null;
    const succeeded = execResult.status === 'executed';
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div style={{
          padding: '28px', borderRadius: 12, textAlign: 'center',
          background: succeeded ? 'var(--success-dim)' : 'var(--error-dim)',
          border: `1px solid ${succeeded ? 'var(--success)' : 'var(--error)'}`,
        }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>{succeeded ? '✓' : '✕'}</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--chalk1)', marginBottom: 8 }}>
            {succeeded ? 'Deletion Complete' : 'Deletion Failed'}
          </div>
          {succeeded ? (
            <div style={{ fontSize: 14, color: 'var(--chalk2)' }}>
              <strong>{execResult.deleted_rows}</strong> {session?.asset_type} record{execResult.deleted_rows !== 1 ? 's' : ''} have been soft-deleted.
            </div>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--error)' }}>
              {execResult.error ?? 'A database error occurred. No records were deleted.'}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', justifyContent: 'center', gap: 12 }}>
          <Button variant="ghost" onClick={handleReset}>Delete More Records</Button>
          <Button onClick={() => navigate('/infrastructure')}>Back to Infrastructure</Button>
        </div>
      </div>
    );
  };

  return (
    <div style={{ overflow: 'auto', flex: 1 }}>
    <div style={{ padding: '28px 32px', maxWidth: 760, margin: '0 auto' }}>
      {/* Page header */}
      <div style={{ marginBottom: 24 }}>
        <div style={{ marginBottom: 4 }}>
          <Button variant="ghost" size="sm" leftIcon={<ArrowLeft size={16} aria-hidden="true" />} onClick={() => navigate('/infrastructure')}>
            Infrastructure
          </Button>
        </div>
        <PageHeader title="Bulk asset deletion" lede="Upload a deletion file to soft-delete FTTH assets by key. Assets are matched before any deletion is executed." />
      </div>

      <StepIndicator current={step} />

      <div style={{
        background: 'var(--surface1)', border: '1px solid var(--border)',
        borderRadius: 12, padding: '24px',
      }}>
        {step === 1 && renderStep1()}
        {step === 2 && renderStep2()}
        {step === 3 && renderStep3()}
      </div>
    </div>
    </div>
  );
}

// ── Shared style constants ────────────────────────────────────
const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: 12, fontWeight: 600,
  color: 'var(--chalk2)', marginBottom: 2,
};

const chipStyle: React.CSSProperties = {
  display: 'inline-block', padding: '2px 8px', borderRadius: 4,
  background: 'var(--surface3)', border: '1px solid var(--border)',
  fontSize: 11, fontFamily: 'monospace', color: 'var(--chalk2)',
};

const thStyle: React.CSSProperties = {
  padding: '8px 12px', textAlign: 'left',
  color: 'var(--chalk3)', fontWeight: 600, fontSize: 11,
};

// ── Export wrapped in ErrorBoundary ───────────────────────────
export default function InfrastructureDeletionPage() {
  return (
    <ErrorBoundary>
      <InfrastructureDeletionContent />
    </ErrorBoundary>
  );
}
