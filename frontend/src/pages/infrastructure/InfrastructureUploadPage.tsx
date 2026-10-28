// ============================================================
// OPSYN — InfrastructureUploadPage
// Bulk upload of network plant (poles, FATs, FDTs, cables… into the
// unified network) and of the original asset register (OLT, cabinet,
// splitter). Types, columns and accepted formats come from
// GET /infrastructure/upload-types, so a new type needs no change here.
//
// Three-step workflow:
//   Step 1 — Select asset type + choose an Excel or GeoJSON file
//   Step 2 — Validation results (valid / error / duplicate rows)
//   Step 3 — Commit confirmation or error report download
// ============================================================

import { useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation, useQuery } from '@tanstack/react-query';
import type { UploadTypeSpec } from '@shared';
import { infrastructureApi } from '../../api/index';
import { networkApi } from '../../api/network.api';
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
type AssetType  = string;
type StepId     = 1 | 2 | 3;

interface ValidationSummary {
  session_id:    string;
  asset_type:    string;
  status:        string;   // 'validated' | 'failed'
  total_rows:    number;
  valid_rows:    number;
  duplicate_rows: number;
  error_rows:    number;
  warnings:      number;
  errors:        Array<{ row: number; field: string; error: string }>;
}

interface CommitResult {
  session_id:    string;
  committed_rows: number;
  status:        string;   // 'committed' | 'rolled_back'
  error?:        string;
}

const ACCEPT: Record<'xlsx' | 'geojson', string> = { xlsx: '.xlsx', geojson: '.geojson,.json' };
const FORMAT_NAME: Record<'xlsx' | 'geojson', string> = { xlsx: 'Excel (.xlsx)', geojson: 'GeoJSON' };
const GROUPS: { id: UploadTypeSpec['group']; label: string; note: string }[] = [
  { id: 'network', label: 'Network plant', note: 'Goes straight onto the network map' },
  { id: 'register', label: 'Asset register', note: 'OLTs, cabinets and splitters, also shown on the network map' },
];

// ── Step indicator ────────────────────────────────────────────
function StepIndicator({ current }: { current: StepId }) {
  const steps = [
    { id: 1 as StepId, label: 'Select & Upload' },
    { id: 2 as StepId, label: 'Review Validation' },
    { id: 3 as StepId, label: 'Commit' },
  ];
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 0, marginBottom: 28 }}>
      {steps.map((s, i) => (
        <div key={s.id} style={{ display: 'flex', alignItems: 'center', flex: i < steps.length - 1 ? 1 : 'none' }}>
          <div style={{
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
          }}>
            <div style={{
              width: 28, height: 28, borderRadius: '50%',
              background: current > s.id ? 'var(--accent)' : current === s.id ? 'var(--accent)' : 'var(--surface2)',
              border: `2px solid ${current >= s.id ? 'var(--accent)' : 'var(--border)'}`,
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
              background: current > s.id ? 'var(--accent)' : 'var(--border)',
            }} />
          )}
        </div>
      ))}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────
function InfrastructureUploadContent() {
  const navigate = useNavigate();
  const toast    = useToast();
  const fileRef  = useRef<HTMLInputElement>(null);

  const [step,       setStep]       = useState<StepId>(1);
  const [assetType,  setAssetType]  = useState<AssetType>('pole');
  const [showOptional, setShowOptional] = useState(false);
  const types = useQuery({ queryKey: ['infra', 'upload-types'], queryFn: networkApi.uploadTypes, staleTime: Infinity });
  const spec = types.data?.find(t => t.key === assetType);
  const formats = spec?.formats ?? ['xlsx'];
  const formatText = formats.map(f => FORMAT_NAME[f]).join(' or ');
  const [file,       setFile]       = useState<File | null>(null);
  const [summary,    setSummary]    = useState<ValidationSummary | null>(null);
  const [commitResult, setCommitResult] = useState<CommitResult | null>(null);
  const [downloading, setDownloading] = useState(false);

  // ── Mutations ───────────────────────────────────────────────
  const uploadMutation = useMutation({
    mutationFn: ({ assetType, file }: { assetType: AssetType; file: File }) =>
      infrastructureApi.uploadAssetFile(assetType, file),
    onSuccess: (data: ValidationSummary) => {
      setSummary(data);
      setStep(2);
    },
    onError: (e: ApiError) => {
      const msg = e?.response?.data?.detail?.errors?.[0] ?? e?.detail ?? 'Upload failed';
      toast.error('Upload failed', msg);
    },
  });

  const commitMutation = useMutation({
    mutationFn: (sessionId: string) => infrastructureApi.commitUploadSession(sessionId),
    onSuccess: (data: CommitResult) => {
      setCommitResult(data);
      setStep(3);
      if (data.status === 'committed') {
        toast.success('Committed', `${data.committed_rows} rows inserted into live tables`);
      } else {
        toast.error('Rollback', data.error ?? 'Commit rolled back due to a database error');
      }
    },
    onError: (e: ApiError) => {
      toast.error('Commit failed', e?.detail ?? 'Unknown error');
    },
  });

  // ── Handlers ────────────────────────────────────────────────
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null;
    setFile(f);
  };

  const handleUpload = () => {
    if (!file) { toast.error('No file selected', `Choose an ${formatText} file first`); return; }
    uploadMutation.mutate({ assetType, file });
  };

  const handleCommit = () => {
    if (!summary) return;
    commitMutation.mutate(summary.session_id);
  };

  const handleDownloadErrors = async () => {
    if (!summary) return;
    setDownloading(true);
    try {
      const res = await infrastructureApi.downloadErrorReport(summary.session_id);
      const url = URL.createObjectURL(res.data as Blob);
      const a   = document.createElement('a');
      a.href     = url;
      a.download = `errors_${summary.asset_type}_${summary.session_id}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error('Download failed', 'Could not retrieve the error report');
    } finally {
      setDownloading(false);
    }
  };

  const handleReset = () => {
    setStep(1);
    setFile(null);
    setSummary(null);
    setCommitResult(null);
    if (fileRef.current) fileRef.current.value = '';
  };

  // ── Render helpers ───────────────────────────────────────────
  const downloadTemplate = async () => {
    if (!spec) return;
    try {
      const blob = await networkApi.uploadTemplate(spec.key);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `opsyn_${spec.key}_template.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error('Download failed', 'The template could not be downloaded');
    }
  };

  const renderStep1 = () => (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      {/* Asset type selector, grouped */}
      {types.isLoading && <div style={{ fontSize: 13, color: 'var(--text-secondary)' }}><Spinner size="xs" /> Loading upload types…</div>}
      {types.isError && <div role="alert" style={{ fontSize: 13, color: 'var(--status-critical-fg)' }}>Couldn't load the upload types. Reload the page to try again.</div>}
      {GROUPS.map(g => {
        const items = (types.data ?? []).filter(t => t.group === g.id);
        if (!items.length) return null;
        return (
          <fieldset key={g.id} style={{ border: 0, margin: 0, padding: 0, minWidth: 0 }}>
            <legend style={labelStyle}>{g.label}</legend>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 8 }}>{g.note}</div>
            <div role="radiogroup" aria-label={g.label} style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(170px, 1fr))', gap: 10 }}>
              {items.map(opt => (
                <button
                  key={opt.key}
                  type="button"
                  role="radio"
                  aria-checked={assetType === opt.key}
                  onClick={() => { setAssetType(opt.key); setFile(null); setShowOptional(false); if (fileRef.current) fileRef.current.value = ''; }}
                  style={{
                    padding: '10px 12px', borderRadius: 8, cursor: 'pointer', textAlign: 'left',
                    background: assetType === opt.key ? 'var(--surface-selected)' : 'var(--surface)',
                    border: `2px solid ${assetType === opt.key ? 'var(--brand)' : 'var(--border)'}`,
                    color: 'var(--text-primary)', font: 'inherit',
                  }}
                >
                  <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 2 }}>{opt.label}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{opt.description}</div>
                </button>
              ))}
            </div>
          </fieldset>
        );
      })}

      {/* Columns */}
      {spec && (
        <div style={{ background: 'var(--surface-sunken)', borderRadius: 8, padding: '12px 16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 6 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>Required columns</div>
            <Button variant="ghost" size="sm" onClick={downloadTemplate}>Download Excel template</Button>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {spec.required_columns.map(col => <span key={col} style={chipStyle}>{col}</span>)}
          </div>
          {spec.geojson_geometry && (
            <div style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 8 }}>
              {spec.geojson_geometry === 'Point'
                ? 'In GeoJSON, a Point geometry replaces longitude and latitude.'
                : 'In GeoJSON, a LineString geometry replaces geometry_wkt. In Excel, write the route as LINESTRING(lng lat, lng lat, …).'}
              {' '}Leave asset_code blank to have a code generated.
            </div>
          )}
          {spec.optional_columns.length > 0 && (
            <>
              <button
                type="button"
                onClick={() => setShowOptional(v => !v)}
                aria-expanded={showOptional}
                style={{ marginTop: 8, padding: 0, border: 0, background: 'none', color: 'var(--accent-text)', font: 'inherit', fontSize: 12, textDecoration: 'underline', cursor: 'pointer' }}
              >
                {showOptional ? 'Hide optional columns' : `Show ${spec.optional_columns.length} optional columns`}
              </button>
              {showOptional && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 8 }}>
                  {spec.optional_columns.map(col => <span key={col} style={chipStyle}>{col}</span>)}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* File input */}
      <div>
        <label style={labelStyle}>{formatText} file</label>
        <div style={{
          marginTop: 8, border: '2px dashed var(--border)', borderRadius: 10,
          padding: '24px', textAlign: 'center', background: 'var(--surface2)',
        }}>
          <input
            ref={fileRef}
            type="file"
            accept={formats.map(f => ACCEPT[f]).join(',')}
            onChange={handleFileChange}
            style={{ display: 'none' }}
            id="upload-file-input"
          />
          <label htmlFor="upload-file-input" style={{ cursor: 'pointer' }}>
            <div style={{ fontSize: 28, marginBottom: 8 }}>📂</div>
            <div style={{ fontSize: 13, color: 'var(--chalk2)', marginBottom: 4 }}>
              {file ? (
                <span style={{ color: 'var(--accent-text)', fontWeight: 600 }}>{file.name}</span>
              ) : (
                <span>Click to choose an <strong>{formatText}</strong> file</span>
              )}
            </div>
            <div style={{ fontSize: 11, color: 'var(--chalk4)' }}>Max 10 MB</div>
          </label>
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
        <Button variant="ghost" onClick={() => navigate('/infrastructure')}>Cancel</Button>
        <Button
          onClick={handleUpload}
          disabled={!file || !spec || uploadMutation.isPending}
        >
          {uploadMutation.isPending ? <><Spinner size="xs" /> Validating…</> : 'Upload & Validate'}
        </Button>
      </div>
    </div>
  );

  const renderStep2 = () => {
    if (!summary) return null;
    const hasFailed = summary.status === 'failed';
    const hasErrors = summary.error_rows > 0;
    const canCommit = !hasFailed && summary.valid_rows > 0;

    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        {/* Status banner */}
        <div style={{
          padding: '14px 18px', borderRadius: 10,
          background: hasFailed ? 'var(--error-dim)' : hasErrors ? 'var(--warning-dim)' : 'var(--success-dim)',
          border: `1px solid ${hasFailed ? 'var(--error)' : hasErrors ? 'var(--warning)' : 'var(--success)'}`,
          display: 'flex', alignItems: 'center', gap: 12,
        }}>
          <span style={{ fontSize: 20 }}>{hasFailed ? '✕' : hasErrors ? '⚠' : '✓'}</span>
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--chalk1)' }}>
              {hasFailed
                ? 'Validation failed — file could not be processed'
                : hasErrors
                  ? `Validation complete — ${summary.error_rows} row(s) have errors`
                  : `Validation passed — all ${summary.valid_rows} rows are ready to commit`
              }
            </div>
            {summary.warnings > 0 && (
              <div style={{ fontSize: 12, color: 'var(--chalk3)', marginTop: 2 }}>
                {summary.warnings} warning(s) (zero-island coordinates)
              </div>
            )}
          </div>
        </div>

        {/* Row count summary */}
        {!hasFailed && (
          <div style={{ display: 'flex', gap: 12 }}>
            {[
              { label: 'Total Rows',      value: summary.total_rows,    color: 'var(--chalk2)' },
              { label: 'Valid',           value: summary.valid_rows,    color: 'var(--success)' },
              { label: 'Errors',          value: summary.error_rows,    color: 'var(--error)' },
              { label: 'Duplicates',      value: summary.duplicate_rows, color: 'var(--warning)' },
            ].map(stat => (
              <div key={stat.label} style={{
                flex: 1, background: 'var(--surface2)', borderRadius: 8,
                padding: '12px 16px', textAlign: 'center',
              }}>
                <div style={{ fontSize: 22, fontWeight: 700, color: stat.color }}>{stat.value}</div>
                <div style={{ fontSize: 11, color: 'var(--chalk3)', marginTop: 2 }}>{stat.label}</div>
              </div>
            ))}
          </div>
        )}

        {/* Error list (first 20) */}
        {summary.errors.length > 0 && (
          <div>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--chalk2)', marginBottom: 8 }}>
              Errors {summary.errors.length > 20 ? `(showing first 20 of ${summary.errors.length})` : ''}
            </div>
            <div style={{
              maxHeight: 240, overflowY: 'auto', borderRadius: 8,
              border: '1px solid var(--border)',
            }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: 'var(--surface2)' }}>
                    {['Row', 'Field', 'Error'].map(h => (
                      <th key={h} style={{ padding: '8px 12px', textAlign: 'left', color: 'var(--chalk3)', fontWeight: 600, fontSize: 11 }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {summary.errors.slice(0, 20).map((err, i) => (
                    <tr key={i} style={{ borderTop: '1px solid var(--border)' }}>
                      <td style={{ padding: '7px 12px', color: 'var(--chalk3)' }}>{err.row}</td>
                      <td style={{ padding: '7px 12px', fontFamily: 'monospace', color: 'var(--chalk2)' }}>{err.field}</td>
                      <td style={{ padding: '7px 12px', color: 'var(--error)' }}>{err.error}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ display: 'flex', gap: 10 }}>
            <Button variant="ghost" onClick={handleReset}>← Start Over</Button>
            {summary.error_rows > 0 && (
              <Button
                variant="secondary"
                onClick={handleDownloadErrors}
                disabled={downloading}
              >
                {downloading ? <><Spinner size="xs" /> Downloading…</> : '⬇ Download Error Report'}
              </Button>
            )}
          </div>
          {canCommit && (
            <Button
              onClick={handleCommit}
              disabled={commitMutation.isPending}
            >
              {commitMutation.isPending
                ? <><Spinner size="xs" /> Committing…</>
                : `Commit ${summary.valid_rows} valid row${summary.valid_rows !== 1 ? 's' : ''}`
              }
            </Button>
          )}
        </div>
      </div>
    );
  };

  const renderStep3 = () => {
    if (!commitResult) return null;
    const succeeded = commitResult.status === 'committed';
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <div style={{
          padding: '28px', borderRadius: 12, textAlign: 'center',
          background: succeeded ? 'var(--success-dim)' : 'var(--error-dim)',
          border: `1px solid ${succeeded ? 'var(--success)' : 'var(--error)'}`,
        }}>
          <div style={{ fontSize: 40, marginBottom: 12 }}>{succeeded ? '✓' : '✕'}</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--chalk1)', marginBottom: 8 }}>
            {succeeded ? 'Import Complete' : 'Commit Rolled Back'}
          </div>
          {succeeded ? (
            <div style={{ fontSize: 14, color: 'var(--chalk2)' }}>
              <strong>{commitResult.committed_rows}</strong> {spec?.label.toLowerCase() ?? 'records'} added{spec?.group === 'network' ? ' to the network map' : ' to the register and the network map'}.
            </div>
          ) : (
            <div style={{ fontSize: 13, color: 'var(--error)' }}>
              {commitResult.error ?? 'A database error occurred. No rows were inserted.'}
            </div>
          )}
        </div>

        <div style={{ display: 'flex', justifyContent: 'center', gap: 12 }}>
          <Button variant="ghost" onClick={handleReset}>Upload Another File</Button>
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
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 4 }}>
          <Button variant="ghost" size="sm" leftIcon={<ArrowLeft size={16} aria-hidden="true" />} onClick={() => navigate('/infrastructure')}>
            Infrastructure
          </Button>
        </div>
        <PageHeader title="Bulk asset upload" lede="Import network plant or register assets from Excel or GeoJSON. Every row is checked before anything is written." />
      </div>

      {/* Step indicator */}
      <StepIndicator current={step} />

      {/* Step content card */}
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

// ── Shared style constants ─────────────────────────────────────
const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: 12, fontWeight: 600,
  color: 'var(--chalk2)', marginBottom: 2,
};

const chipStyle: React.CSSProperties = {
  display: 'inline-block', padding: '2px 8px', borderRadius: 4,
  background: 'var(--surface3)', border: '1px solid var(--border)',
  fontSize: 11, fontFamily: 'monospace', color: 'var(--chalk2)',
};

// ── Export wrapped in ErrorBoundary ───────────────────────────
export default function InfrastructureUploadPage() {
  return (
    <ErrorBoundary>
      <InfrastructureUploadContent />
    </ErrorBoundary>
  );
}
