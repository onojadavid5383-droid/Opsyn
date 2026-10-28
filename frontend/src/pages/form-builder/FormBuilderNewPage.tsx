// ============================================================
// OPSYN — Dynamic Form Schema Builder (Phase 5 + Phase 6)
// src/pages/form-builder/FormBuilderNewPage.tsx
//
// Three-panel: Field Type Palette | Schema Canvas | Field Config
// Phase 6 additions: Version history modal, re-publish for
// published schemas, snapshot viewer.
// ============================================================

import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import type { ApiError } from '../../api/client';
import {
  formBuilderApi,
  type FieldDefinition,
  type FieldTypeInfo,
  type FormSchema,
  type FormAssociation,
} from '../../api/form-builder.api';
import { GlassModal, GlassSelect } from '../../components/glass';
import SchemaChangeReview from '../../components/form-builder/SchemaChangeReview';

// ── Constants ─────────────────────────────────────────────────

const MODULES = [
  { value: 'customer',        label: 'Customer'        },
  { value: 'infrastructure',  label: 'Infrastructure'  },
  { value: 'pipeline',        label: 'Pipeline'        },
  { value: 'field_ops',       label: 'Field Ops'       },
  { value: 'generic',         label: 'Generic'         },
];

const CONTEXT_TYPE_OPTIONS = [
  { value: 'module',            label: 'Module'           },
  { value: 'pipeline_stage',    label: 'Pipeline Stage'   },
  { value: 'department',        label: 'Department'       },
  { value: 'external_trigger',  label: 'External Trigger' },
  { value: 'user_role',         label: 'User Role'        },
];

const TRIGGER_EVENT_OPTIONS = [
  { value: 'on_create',      label: 'On Create'      },
  { value: 'on_stage_enter', label: 'On Stage Enter' },
  { value: 'on_approval',    label: 'On Approval'    },
  { value: 'manual',         label: 'Manual'         },
];

const CATEGORY_ORDER  = ['basic', 'choice', 'media', 'structured', 'advanced', 'layout'];
const CATEGORY_LABELS: Record<string, string> = {
  basic:      'Basic',
  choice:     'Choice',
  media:      'Media',
  structured: 'Structured',
  advanced:   'Advanced',
  layout:     'Layout',
};

const WIDTH_OPTIONS = [
  { value: 'full',       label: 'Full width'  },
  { value: 'half',       label: 'Half width'  },
  { value: 'third',      label: 'One-third'   },
  { value: 'two_thirds', label: 'Two-thirds'  },
  { value: 'quarter',    label: 'Quarter'     },
];

// ── Utilities ─────────────────────────────────────────────────

function toMachineName(s: string): string {
  return s.toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 100) || 'schema';
}

function toFieldKey(typeKey: string): string {
  const suffix = Math.random().toString(36).slice(2, 7);
  return `${typeKey}_${suffix}`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: 'medium', timeStyle: 'short',
  });
}

// ── Shared input style ────────────────────────────────────────

const inputStyle: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box',
  padding: '6px 10px', borderRadius: 6,
  border: '1px solid var(--color-border)',
  background: 'rgba(255,255,255,0.05)',
  color: 'var(--chalk1)',
  fontFamily: 'var(--font-display)',
  fontSize: 12, outline: 'none',
};

// ── Field type SVG icons ───────────────────────────────────────

const FIELD_ICON_PATHS: Record<string, string> = {
  string:         'M2 5h12M2 8h8M2 11h10',
  text:           'M2 3h12v10H2zm2 3h8M4 9h6',
  integer:        'M7 4v8m1-8v8M5 7h6',
  float:          'M7 4v8M5 7h6M11 10h.5',
  boolean:        'M3 8a5 5 0 0010 0 5 5 0 00-10 0zm5 0V6m0 4h.01',
  date:           'M2 4h12v10H2zm0 4h12M5 2v4m6-4v4',
  datetime:       'M2 4h10v10H2zm0 4h10M5 2v4m4-4v4M13 10a3 3 0 100-6',
  time:           'M8 3a5 5 0 100 10A5 5 0 008 3zm0 2v3l2 2',
  email:          'M2 4h12v8H2zm0 0l6 5 6-5',
  phone:          'M5 2a2 2 0 00-2 2v8a2 2 0 002 2h6a2 2 0 002-2V4a2 2 0 00-2-2H5zm3 9h.01',
  url:            'M5 8h6M7 5l3 3-3 3M2 8a6 6 0 1012 0A6 6 0 002 8',
  enum:           'M3 5h2v2H3zm4 0h6M3 9h2v2H3zm4 0h6',
  multiselect:    'M3 4h2v2H3zm4 0h6M3 8h2v2H3zm4 0h4M3 12h2v2H3zm4 0h6',
  radio:          'M3 5a2 2 0 114 0 2 2 0 01-4 0zm5 1h5M3 10a2 2 0 114 0 2 2 0 01-4 0zm5 1h5',
  file:           'M4 2h6l4 4v10H4zm6-2v4h4',
  image:          'M2 2h12v12H2zm0 8l3-3 3 3 2-2 4 4',
  coordinates:    'M8 2a4 4 0 00-4 4c0 4 4 8 4 8s4-4 4-8a4 4 0 00-4-4zm0 5a1 1 0 110-2 1 1 0 010 2',
  address:        'M8 2a6 6 0 00-6 6c0 4 6 8 6 8s6-4 6-8a6 6 0 00-6-6zm0 8a2 2 0 110-4 2 2 0 010 4',
  currency:       'M8 2v2m0 8v2M5 5h5a2 2 0 010 4H6a2 2 0 000 4h6',
  rating:         'M8 2l2 4h4l-3 3 1 4-4-2-4 2 1-4-3-3h4z',
  signature:      'M2 12c2-4 4-7 6-7s4 3 6 7',
  lookup:         'M11 11l3 3m-5-2a5 5 0 110-10 5 5 0 010 10z',
  computed:       'M2 8h3l2-4 2 8 2-4h3',
  section_header: 'M2 4h12M2 8h8M2 12h6',
};

function FieldTypeIcon({ type, size = 14 }: { type: string; size?: number }) {
  return (
    <svg
      width={size} height={size} viewBox="0 0 16 16" fill="none"
      stroke="currentColor" strokeWidth={1.5}
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
    >
      <path d={FIELD_ICON_PATHS[type] ?? 'M3 3h10v10H3z'} />
    </svg>
  );
}

// ══ SMALL REUSABLE COMPONENTS ════════════════════════════════

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { bg: string; color: string }> = {
    draft:     { bg: 'rgba(255,180,0,0.15)',   color: '#ffb400'                  },
    published: { bg: 'rgba(0,194,168,0.15)',   color: 'var(--color-teal)'        },
    archived:  { bg: 'rgba(255,255,255,0.08)', color: 'var(--text-muted)'   },
  };
  const c = map[status] ?? map.draft;
  return (
    <span style={{
      padding: '2px 8px', borderRadius: 4,
      fontSize: 10, fontWeight: 700,
      fontFamily: 'var(--font-display)',
      letterSpacing: '0.08em', textTransform: 'uppercase' as const,
      background: c.bg, color: c.color,
    }}>
      {status}
    </span>
  );
}

function Btn({
  children, primary, ghost, small, danger, disabled, onClick,
}: {
  children:  React.ReactNode;
  primary?:  boolean;
  ghost?:    boolean;
  small?:    boolean;
  danger?:   boolean;
  disabled?: boolean;
  onClick?:  () => void;
}) {
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      style={{
        padding:    small ? '4px 12px' : '7px 16px',
        borderRadius: 6,
        border:     primary
          ? 'none'
          : `1px solid ${danger ? 'rgba(255,80,80,0.40)' : 'var(--color-border)'}`,
        cursor:     disabled ? 'default' : 'pointer',
        fontFamily: 'var(--font-display)',
        fontSize:   small ? 11 : 12,
        fontWeight: 600,
        color:      primary ? 'var(--color-navy)'
                  : danger  ? 'rgba(255,80,80,0.85)'
                  :           'var(--chalk2)',
        background: primary ? 'var(--color-teal)'
                  : ghost   ? 'rgba(255,255,255,0.07)'
                  :           'transparent',
        opacity:    disabled ? 0.5 : 1,
        whiteSpace: 'nowrap' as const,
        transition: 'opacity 120ms',
      }}
    >
      {children}
    </button>
  );
}

function IconBtn({ children, title, danger, disabled, onClick }: {
  children:  React.ReactNode;
  title?:    string;
  danger?:   boolean;
  disabled?: boolean;
  onClick?:  React.MouseEventHandler<HTMLButtonElement>;
}) {
  return (
    <button
      title={title} disabled={disabled} onClick={onClick}
      style={{
        width: 18, height: 18,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: 'none', border: 'none',
        cursor: disabled ? 'default' : 'pointer',
        color: danger ? 'rgba(255,80,80,0.60)' : 'rgba(255,255,255,0.30)',
        fontSize: 9, padding: 0, lineHeight: 1,
        borderRadius: 3,
        opacity: disabled ? 0.25 : 1, flexShrink: 0,
      }}
    >
      {children}
    </button>
  );
}

function TagChip({ children, color }: { children: React.ReactNode; color?: 'teal' | 'dim' }) {
  return (
    <span style={{
      padding: '1px 5px', borderRadius: 3,
      fontSize: 9, fontWeight: 700,
      fontFamily: 'var(--font-display)', letterSpacing: '0.05em',
      background: color === 'teal' ? 'rgba(0,194,168,0.15)' : 'rgba(255,255,255,0.07)',
      color:      color === 'teal' ? 'var(--color-teal)'     : 'rgba(255,255,255,0.35)',
    }}>
      {children}
    </span>
  );
}

function FormField({ label, children, small }: {
  label: string; children: React.ReactNode; small?: boolean;
}) {
  return (
    <div style={{ marginBottom: small ? 8 : 12 }}>
      <label style={{
        display: 'block', fontSize: 10, fontWeight: 600,
        fontFamily: 'var(--font-display)', color: 'var(--text-muted)',
        marginBottom: 4, textTransform: 'uppercase' as const, letterSpacing: '0.08em',
      }}>
        {label}
      </label>
      {children}
    </div>
  );
}

function Toggle({ label, description, checked, onChange }: {
  label: string; description: string; checked: boolean; onChange: (v: boolean) => void;
}) {
  return (
    <div
      onClick={() => onChange(!checked)}
      style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '6px 0', cursor: 'pointer' }}
    >
      <div style={{
        width: 32, height: 18, borderRadius: 9,
        background: checked ? 'var(--color-teal)' : 'rgba(255,255,255,0.15)',
        position: 'relative', transition: 'background 150ms', flexShrink: 0,
      }}>
        <div style={{
          position: 'absolute', top: 2, left: checked ? 16 : 2,
          width: 14, height: 14, borderRadius: 7,
          background: 'var(--surface)', transition: 'left 150ms',
        }} />
      </div>
      <div>
        <div style={{
          fontSize: 12, fontFamily: 'var(--font-display)',
          color: 'var(--chalk2)', fontWeight: checked ? 600 : 400,
        }}>
          {label}
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-display)' }}>
          {description}
        </div>
      </div>
    </div>
  );
}

function Modal({ title, width = 480, children, onClose }: {
  title:    string;
  width?:   number;
  children: React.ReactNode;
  onClose:  () => void;
}) {
  const size = width <= 440 ? 'sm' : width <= 600 ? 'md' : width <= 760 ? 'lg' : 'xl';
  return (
    <GlassModal open onClose={onClose} title={title} size={size}>
      <div style={{ display: 'flex', flexDirection: 'column' }}>{children}</div>
    </GlassModal>
  );
}

// ══ VERSION HISTORY MODAL (Phase 6) ══════════════════════════

function VersionHistoryModal({
  schemaId,
  schemaName,
  onClose,
}: {
  schemaId:   string;
  schemaName: string;
  onClose:    () => void;
}) {
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);

  const versionsQ = useQuery({
    queryKey: ['form-builder', 'versions', schemaId],
    queryFn:  () => formBuilderApi.getSchemaVersions(schemaId),
  });

  const snapshotQ = useQuery({
    queryKey: ['form-builder', 'version-snapshot', selectedVersionId],
    queryFn:  () => formBuilderApi.getSchemaVersion(schemaId, selectedVersionId!),
    enabled:  !!selectedVersionId,
  });

  const versions    = versionsQ.data ?? [];
  const snapshot    = snapshotQ.data ?? null;
  const snapFields  = snapshot?.field_snapshot ?? [];

  return (
    <Modal title={`Version History — ${schemaName}`} width={840} onClose={onClose}>
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

        {/* Version list */}
        <div style={{
          width: 280, flexShrink: 0,
          borderRight: '1px solid var(--color-border)',
          overflowY: 'auto', scrollbarWidth: 'thin' as const,
        }}>
          {versionsQ.isLoading && (
            <div style={{ padding: 16, fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-display)' }}>
              Loading versions…
            </div>
          )}
          {!versionsQ.isLoading && versions.length === 0 && (
            <div style={{
              padding: '32px 16px', textAlign: 'center',
              fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-display)',
            }}>
              No published versions yet.
            </div>
          )}
          {versions.map(v => (
            <button
              key={v.id}
              onClick={() => setSelectedVersionId(v.id)}
              style={{
                display: 'flex', flexDirection: 'column', gap: 3,
                width: '100%', padding: '12px 14px',
                border: 'none', textAlign: 'left' as const,
                background: selectedVersionId === v.id
                  ? 'rgba(0,194,168,0.10)'
                  : 'transparent',
                boxShadow: selectedVersionId === v.id
                  ? 'inset 3px 0 0 var(--color-teal)'
                  : 'none',
                cursor: 'pointer',
                borderBottom: '1px solid var(--color-border)',
                transition: 'background 120ms',
              }}
            >
              <div style={{
                display: 'flex', alignItems: 'center', gap: 6,
              }}>
                <span style={{
                  fontSize: 13, fontWeight: 700,
                  fontFamily: 'var(--font-display)', color: 'var(--chalk1)',
                }}>
                  v{v.version_number}
                </span>
                {v.is_current && (
                  <span style={{
                    padding: '1px 6px', borderRadius: 4,
                    background: 'rgba(0,194,168,0.15)',
                    color: 'var(--color-teal)',
                    fontSize: 9, fontWeight: 700, fontFamily: 'var(--font-display)',
                    letterSpacing: '0.06em', textTransform: 'uppercase' as const,
                  }}>
                    current
                  </span>
                )}
              </div>
              <div style={{
                fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-display)',
              }}>
                {fmtDate(v.published_at)}
              </div>
              {v.changelog && (
                <div style={{
                  fontSize: 11, color: 'var(--chalk3)', fontFamily: 'var(--font-display)',
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
                }}>
                  {v.changelog}
                </div>
              )}
              <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-display)' }}>
                {(v.field_snapshot?.length ?? 0)} fields
              </div>
            </button>
          ))}
        </div>

        {/* Snapshot viewer */}
        <div style={{ flex: 1, overflowY: 'auto', scrollbarWidth: 'thin' as const }}>
          {!selectedVersionId && (
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              height: '100%',
              fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-display)',
            }}>
              Select a version to view its field snapshot
            </div>
          )}

          {selectedVersionId && snapshotQ.isLoading && (
            <div style={{ padding: 16, fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-display)' }}>
              Loading snapshot…
            </div>
          )}

          {snapshot && (
            <div style={{ padding: 16 }}>
              {/* Version meta */}
              <div style={{
                padding: '10px 14px', borderRadius: 8,
                border: '1px solid var(--color-border)',
                background: 'rgba(255,255,255,0.03)',
                marginBottom: 14,
              }}>
                <div style={{
                  fontSize: 12, fontWeight: 700,
                  fontFamily: 'var(--font-display)', color: 'var(--chalk1)',
                  marginBottom: 4,
                }}>
                  Version {snapshot.version_number} — Immutable Snapshot
                </div>
                <div style={{
                  fontSize: 11, color: 'var(--text-muted)',
                  fontFamily: 'var(--font-display)', display: 'flex', gap: 16,
                }}>
                  <span>Published: {fmtDate(snapshot.published_at)}</span>
                  <span>{snapFields.length} fields</span>
                </div>
                {snapshot.changelog && (
                  <div style={{
                    marginTop: 6, fontSize: 12, color: 'var(--chalk3)',
                    fontFamily: 'var(--font-display)',
                  }}>
                    {snapshot.changelog}
                  </div>
                )}
              </div>

              {/* Snapshot fields (read-only) */}
              {snapFields.length === 0 && (
                <div style={{
                  fontSize: 12, color: 'var(--text-muted)',
                  fontFamily: 'var(--font-display)',
                }}>
                  No fields in this snapshot.
                </div>
              )}
              {snapFields.map((field, idx) => (
                <div key={field.id ?? idx} style={{
                  display: 'flex', alignItems: 'center', gap: 10,
                  padding: '8px 12px', marginBottom: 6, borderRadius: 8,
                  border: '1px solid var(--color-border)',
                  background: 'var(--color-surface)',
                }}>
                  <span style={{ color: 'var(--color-teal)', opacity: 0.6, flexShrink: 0 }}>
                    <FieldTypeIcon type={field.field_type} size={14} />
                  </span>
                  <div style={{ flex: 1, overflow: 'hidden' }}>
                    <div style={{
                      fontSize: 12, fontWeight: 600,
                      fontFamily: 'var(--font-display)', color: 'var(--chalk1)',
                    }}>
                      {field.label}
                      {field.is_required && (
                        <span style={{ color: '#ff5a5a', marginLeft: 3, fontSize: 10 }}>*</span>
                      )}
                    </div>
                    <div style={{
                      fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace',
                    }}>
                      {field.field_key} · {field.field_type}
                    </div>
                  </div>
                  <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                    {field.is_hidden && <TagChip>hidden</TagChip>}
                    {field.is_unique && <TagChip color="teal">unique</TagChip>}
                    <TagChip color="dim">{field.width}</TagChip>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </Modal>
  );
}

// ══ FIELD TYPE PALETTE (left panel) ══════════════════════════

function FieldTypePalette({
  groupedTypes, canAdd, adding, onAdd,
}: {
  groupedTypes: Record<string, FieldTypeInfo[]>;
  canAdd:       boolean;
  adding:       boolean;
  onAdd:        (ft: FieldTypeInfo) => void;
}) {
  return (
    <div style={{
      width: 220, flexShrink: 0,
      borderRight: '1px solid var(--color-border)',
      overflowY: 'auto', overflowX: 'hidden',
      background: 'var(--color-surface)',
      scrollbarWidth: 'none' as const,
    }}>
      <div style={{
        padding: '12px 12px 6px',
        fontSize: 10, fontWeight: 700,
        fontFamily: 'var(--font-display)',
        color: 'var(--text-muted)',
        letterSpacing: '0.12em', textTransform: 'uppercase' as const,
      }}>
        Field Types
      </div>

      {!canAdd && (
        <div style={{
          margin: '4px 12px 10px', padding: '7px 10px', borderRadius: 6,
          background: 'rgba(255,180,0,0.10)', color: '#ffb400',
          fontSize: 11, fontFamily: 'var(--font-display)',
        }}>
          Select a schema to add fields
        </div>
      )}

      {CATEGORY_ORDER.map(cat => {
        const types = groupedTypes[cat];
        if (!types?.length) return null;
        return (
          <div key={cat} style={{ marginBottom: 4 }}>
            <div style={{
              padding: '6px 12px 3px',
              fontSize: 9, fontWeight: 700,
              fontFamily: 'var(--font-display)',
              color: 'var(--text-muted)',
              letterSpacing: '0.10em', textTransform: 'uppercase' as const,
            }}>
              {CATEGORY_LABELS[cat] ?? cat}
            </div>
            {types.map(ft => (
              <button
                key={ft.key}
                disabled={!canAdd || adding}
                onClick={() => onAdd(ft)}
                style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  width: '100%', padding: '6px 12px',
                  border: 'none', background: 'transparent',
                  cursor: canAdd ? 'pointer' : 'default',
                  textAlign: 'left' as const,
                  fontFamily: 'var(--font-display)', fontSize: 12,
                  color: canAdd ? 'var(--chalk2)' : 'rgba(255,255,255,0.28)',
                  opacity: canAdd ? 1 : 0.6, transition: 'background 100ms',
                }}
                onMouseEnter={e => {
                  if (canAdd) (e.currentTarget as HTMLElement).style.background = 'rgba(0,194,168,0.09)';
                }}
                onMouseLeave={e => {
                  (e.currentTarget as HTMLElement).style.background = 'transparent';
                }}
              >
                <span style={{ color: 'var(--color-teal)', opacity: 0.8, flexShrink: 0 }}>
                  <FieldTypeIcon type={ft.key} />
                </span>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {ft.label}
                </span>
              </button>
            ))}
          </div>
        );
      })}
      <div style={{ height: 24 }} />
    </div>
  );
}

// ══ FIELD CARD ════════════════════════════════════════════════

function FieldCard({
  field, isFirst, isLast, isEditing, isArchived,
  onEdit, onDelete, onMoveUp, onMoveDown,
}: {
  field:      FieldDefinition;
  isFirst:    boolean;
  isLast:     boolean;
  isEditing:  boolean;
  isArchived: boolean;
  onEdit:     () => void;
  onDelete:   () => void;
  onMoveUp:   () => void;
  onMoveDown: () => void;
}) {
  return (
    <div
      onClick={isArchived ? undefined : onEdit}
      style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '10px 12px', marginBottom: 6, borderRadius: 8,
        border: `1px solid ${isEditing ? 'var(--color-teal)' : 'var(--color-border)'}`,
        background: isEditing ? 'rgba(0,194,168,0.06)' : 'var(--color-surface)',
        cursor: isArchived ? 'default' : 'pointer',
        transition: 'border-color 120ms, background 120ms',
      }}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: 1, flexShrink: 0 }}>
        <IconBtn title="Move up"   disabled={isFirst || isArchived}
          onClick={e => { e.stopPropagation(); onMoveUp(); }}>▲</IconBtn>
        <IconBtn title="Move down" disabled={isLast  || isArchived}
          onClick={e => { e.stopPropagation(); onMoveDown(); }}>▼</IconBtn>
      </div>
      <span style={{ flexShrink: 0, color: 'var(--color-teal)', opacity: 0.75 }}>
        <FieldTypeIcon type={field.field_type} size={15} />
      </span>
      <div style={{ flex: 1, overflow: 'hidden' }}>
        <div style={{
          fontSize: 13, fontWeight: 600,
          fontFamily: 'var(--font-display)', color: 'var(--chalk1)',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
        }}>
          {field.label}
          {field.is_required && (
            <span style={{ color: '#ff5a5a', marginLeft: 3, fontSize: 11 }}>*</span>
          )}
        </div>
        <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
          {field.field_key} · {field.field_type}
        </div>
      </div>
      <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
        {field.is_hidden && <TagChip>hidden</TagChip>}
        {field.is_unique && <TagChip color="teal">unique</TagChip>}
        <TagChip color="dim">{field.width}</TagChip>
      </div>
      {!isArchived && (
        <IconBtn danger title="Delete field"
          onClick={e => { e.stopPropagation(); onDelete(); }}>✕</IconBtn>
      )}
    </div>
  );
}

// ══ SCHEMA CANVAS (center panel) ═════════════════════════════

function SchemaCanvas({
  schema, fields, loading, editingFieldId,
  onEditField, onDeleteField, onMoveField,
}: {
  schema:         FormSchema | null;
  fields:         FieldDefinition[];
  loading:        boolean;
  editingFieldId: string | null;
  onEditField:    (f: FieldDefinition) => void;
  onDeleteField:  (id: string) => void;
  onMoveField:    (id: string, dir: 'up' | 'down') => void;
}) {
  if (!schema) {
    return (
      <div style={{
        flex: 1, display: 'flex',
        alignItems: 'center', justifyContent: 'center',
        flexDirection: 'column', gap: 10,
        color: 'var(--text-muted)',
        fontFamily: 'var(--font-display)', fontSize: 13,
      }}>
        <svg width={44} height={44} viewBox="0 0 16 16" fill="none"
             stroke="currentColor" strokeWidth={0.9} strokeLinecap="round">
          <path d="M3 2h10v12H3zm2 3h6M5 7h6M5 10h4" />
        </svg>
        Select or create a schema to begin
      </div>
    );
  }

  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      overflow: 'hidden', background: 'var(--color-bg)',
    }}>
      <div style={{
        padding: '12px 16px',
        borderBottom: '1px solid var(--color-border)',
        background: 'var(--color-surface)', flexShrink: 0,
      }}>
        <div style={{
          fontSize: 15, fontWeight: 700,
          fontFamily: 'var(--font-display)', color: 'var(--chalk1)', marginBottom: 2,
        }}>
          {schema.name}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-display)' }}>
          v{schema.current_version} · {schema.module} · {fields.length} field{fields.length !== 1 ? 's' : ''}
          {schema.machine_name && (
            <span style={{ fontFamily: 'monospace', marginLeft: 6, opacity: 0.7 }}>
              {schema.machine_name}
            </span>
          )}
        </div>
      </div>

      <div style={{
        flex: 1, overflowY: 'auto', padding: '14px 16px',
        scrollbarWidth: 'thin' as const,
      }}>
        {loading && (
          <div style={{
            color: 'var(--text-muted)', fontSize: 12, fontFamily: 'var(--font-display)',
          }}>
            Loading fields…
          </div>
        )}
        {!loading && fields.length === 0 && (
          <div style={{
            textAlign: 'center', padding: '52px 0',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-display)', fontSize: 13,
          }}>
            {schema.status === 'archived'
              ? 'This schema is archived and cannot be modified.'
              : 'No fields yet. Click a field type in the palette to add one.'}
          </div>
        )}
        {fields.map((field, idx) => (
          <FieldCard
            key={field.id}
            field={field}
            isFirst={idx === 0}
            isLast={idx === fields.length - 1}
            isEditing={editingFieldId === field.id}
            isArchived={schema.status === 'archived'}
            onEdit={() => onEditField(field)}
            onDelete={() => onDeleteField(field.id)}
            onMoveUp={() => onMoveField(field.id, 'up')}
            onMoveDown={() => onMoveField(field.id, 'down')}
          />
        ))}
        <div style={{ height: 24 }} />
      </div>
    </div>
  );
}

// ══ FIELD CONFIG DRAWER (right panel) ════════════════════════

function FieldConfigDrawer({
  field, fieldTypes, schemaFields, saving, onSave, onClose,
}: {
  field:      FieldDefinition | null;
  fieldTypes: FieldTypeInfo[];
  schemaFields: FieldDefinition[];
  saving:     boolean;
  onSave:     (data: Record<string, unknown>) => void;
  onClose:    () => void;
}) {
  const [draft, setDraft]        = useState<Record<string, unknown>>({});
  const [optionInput, setOption] = useState('');
  const [logicError, setLogicError] = useState('');

  useEffect(() => {
    if (field) {
      // Re-seed only when the selection changes, so in-progress edits survive
      // // parent re-renders.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setDraft({
        label:            field.label,
        placeholder:      field.placeholder ?? '',
        help_text:        field.help_text ?? '',
        section_group:    field.section_group ?? '',
        width:            field.width,
        is_required:      field.is_required,
        is_unique:        field.is_unique,
        is_hidden:        field.is_hidden,
        role_visibility:  [...(field.role_visibility ?? [])].join(', '),
        role_editable:    [...(field.role_editable ?? [])].join(', '),
        stage_visible_from: field.stage_visible_from ?? '',
        stage_required_at: field.stage_required_at ?? '',
        conditional_logic: field.conditional_logic ? JSON.stringify(field.conditional_logic, null, 2) : '',
        options:          [...(field.options ?? [])],
        validation_rules: { ...(field.validation_rules ?? {}) },
      });
      setOption('');
    }
  // Re-seed only when the selection changes, so in-progress edits survive
  // // parent re-renders.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [field?.id]);

  if (!field) {
    return (
      <div style={{
        width: 320, flexShrink: 0,
        borderLeft: '1px solid var(--color-border)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        flexDirection: 'column', gap: 10,
        color: 'var(--text-muted)',
        fontFamily: 'var(--font-display)', fontSize: 12,
        background: 'var(--color-surface)',
      }}>
        <svg width={32} height={32} viewBox="0 0 16 16" fill="none"
             stroke="currentColor" strokeWidth={1} strokeLinecap="round">
          <path d="M3 3h10v10H3zm3 4h4M6 8h4" />
        </svg>
        Select a field to configure
      </div>
    );
  }

  const ftInfo   = fieldTypes.find(ft => ft.key === field.field_type);
  const hasOpts  = ftInfo?.has_options ?? false;
  const valRules = ftInfo?.validation_rules ?? [];
  let conditionalLogic: { action?: string; match?: string; conditions?: Array<{ field_key: string; operator: string; value?: unknown }> } = {};
  try { conditionalLogic = JSON.parse(String(draft.conditional_logic ?? '') || '{}'); } catch { /* malformed draft is reported on save */ }

  const set = (key: string, val: unknown) =>
    setDraft(d => ({ ...d, [key]: val }));

  const addOption = () => {
    const v = optionInput.trim();
    if (!v) return;
    const cur = (draft.options ?? []) as string[];
    if (!cur.includes(v)) set('options', [...cur, v]);
    setOption('');
  };

  const removeOption = (opt: string) =>
    set('options', ((draft.options ?? []) as string[]).filter(o => o !== opt));

  const setVRule = (rule: string, raw: string) => {
    const cur = { ...((draft.validation_rules ?? {}) as Record<string, unknown>) };
    if (raw === '') { delete cur[rule]; }
    else { cur[rule] = isNaN(Number(raw)) ? raw : Number(raw); }
    set('validation_rules', cur);
  };

  const setLogic = (next: typeof conditionalLogic) => set('conditional_logic', JSON.stringify(next, null, 2));
  const setLogicCondition = (index: number, patch: Partial<{ field_key: string; operator: string; value?: unknown }>) => {
    const conditions = [...(conditionalLogic.conditions ?? [])];
    conditions[index] = { ...conditions[index], ...patch };
    setLogic({ ...conditionalLogic, conditions });
  };

  return (
    <div style={{
      width: 320, flexShrink: 0,
      borderLeft: '1px solid var(--color-border)',
      display: 'flex', flexDirection: 'column',
      background: 'var(--color-surface)', overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center',
        padding: '10px 14px', borderBottom: '1px solid var(--color-border)', flexShrink: 0,
      }}>
        <div style={{ flex: 1 }}>
          <div style={{
            fontSize: 12, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--chalk1)',
          }}>
            Configure Field
          </div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
            {field.field_key} · {field.field_type}
          </div>
        </div>
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

      {/* Body */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 14, scrollbarWidth: 'thin' as const }}>
        <FormField label="Label">
          <input
            style={inputStyle}
            value={(draft.label ?? '') as string}
            onChange={e => set('label', e.target.value)}
          />
        </FormField>
        <FormField label="Placeholder">
          <input
            style={inputStyle}
            placeholder="Hint shown inside the field"
            value={(draft.placeholder ?? '') as string}
            onChange={e => set('placeholder', e.target.value)}
          />
        </FormField>
        <FormField label="Help Text">
          <input
            style={inputStyle}
            placeholder="Shown below the field"
            value={(draft.help_text ?? '') as string}
            onChange={e => set('help_text', e.target.value)}
          />
        </FormField>
        <FormField label="Section Group">
          <input
            style={inputStyle}
            placeholder="Optional section label"
            value={(draft.section_group ?? '') as string}
            onChange={e => set('section_group', e.target.value)}
          />
        </FormField>
        <FormField label="Width">
          <GlassSelect value={String((draft.width ?? 'full') as string)} onChange={v => set('width', v)} options={[...WIDTH_OPTIONS.map((w) => ({ value: String(w.value), label: String(w.label) }))]} ariaLabel="Field width" />
        </FormField>

        {/* Behaviour toggles */}
        <div style={{ marginBottom: 14 }}>
          <div style={{
            fontSize: 10, fontWeight: 700,
            fontFamily: 'var(--font-display)',
            color: 'var(--text-muted)',
            letterSpacing: '0.10em', textTransform: 'uppercase' as const,
            marginBottom: 6,
          }}>
            Behaviour
          </div>
          <Toggle
            label="Required"
            description="Submission fails if this field is empty"
            checked={!!(draft.is_required)}
            onChange={v => set('is_required', v)}
          />
          <Toggle
            label="Unique"
            description="Value must be unique across all submissions"
            checked={!!(draft.is_unique)}
            onChange={v => set('is_unique', v)}
          />
          <Toggle
            label="Hidden"
            description="Not rendered in the form UI"
            checked={!!(draft.is_hidden)}
            onChange={v => set('is_hidden', v)}
          />
        </div>

        <div style={{ marginBottom: 14 }}>
          <div style={{ fontSize: 10, fontWeight: 700, fontFamily: 'var(--font-display)', color: 'var(--text-muted)', letterSpacing: '0.10em', textTransform: 'uppercase' as const, marginBottom: 6 }}>Visibility &amp; Access</div>
          <FormField label="Visible to roles (comma separated)" small>
            <input style={inputStyle} value={String(draft.role_visibility ?? '')} onChange={e => set('role_visibility', e.target.value)} placeholder="Blank means all roles" />
          </FormField>
          <FormField label="Editable by roles (comma separated)" small>
            <input style={inputStyle} value={String(draft.role_editable ?? '')} onChange={e => set('role_editable', e.target.value)} placeholder="Blank means all roles" />
          </FormField>
          <FormField label="Visible from pipeline stage order" small>
            <input type="number" min="0" style={inputStyle} value={String(draft.stage_visible_from ?? '')} onChange={e => set('stage_visible_from', e.target.value)} />
          </FormField>
          <FormField label="Required from pipeline stage order" small>
            <input type="number" min="0" style={inputStyle} value={String(draft.stage_required_at ?? '')} onChange={e => set('stage_required_at', e.target.value)} />
          </FormField>
          <FormField label="Conditional logic (JSON)" small>
            <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
              <GlassSelect value={conditionalLogic.action ?? 'show'} onChange={action => setLogic({ ...conditionalLogic, action })} options={['show', 'hide', 'require', 'disable', 'clear'].map(v => ({ value: v, label: v }))} ariaLabel="Conditional action" />
              <GlassSelect value={conditionalLogic.match ?? 'all'} onChange={match => setLogic({ ...conditionalLogic, match })} options={[{ value: 'all', label: 'All conditions' }, { value: 'any', label: 'Any condition' }]} ariaLabel="Condition matching" />
            </div>
            {(conditionalLogic.conditions ?? []).map((condition, index) => (
              <div key={index} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr auto', gap: 4, marginBottom: 6, alignItems: 'center' }}>
                <GlassSelect value={condition.field_key} onChange={field_key => setLogicCondition(index, { field_key })} options={schemaFields.filter(f => f.id !== field.id).map(f => ({ value: f.field_key, label: f.label }))} ariaLabel={`Condition ${index + 1} field`} />
                <GlassSelect value={condition.operator} onChange={operator => setLogicCondition(index, { operator })} options={['equals', 'not_equals', 'contains', 'not_contains', 'greater_than', 'less_than', 'is_empty', 'is_not_empty', 'in', 'not_in'].map(v => ({ value: v, label: v.replaceAll('_', ' ') }))} ariaLabel={`Condition ${index + 1} operator`} />
                <input style={inputStyle} value={String(condition.value ?? '')} disabled={condition.operator === 'is_empty' || condition.operator === 'is_not_empty'} onChange={e => setLogicCondition(index, { value: e.target.value })} aria-label={`Condition ${index + 1} value`} />
                <button type="button" onClick={() => setLogic({ ...conditionalLogic, conditions: (conditionalLogic.conditions ?? []).filter((_, i) => i !== index) })} aria-label={`Remove condition ${index + 1}`} style={{ border: 0, background: 'none', color: '#ff5a5a', cursor: 'pointer' }}>×</button>
              </div>
            ))}
            <Btn ghost small onClick={() => setLogic({ action: conditionalLogic.action ?? 'show', match: conditionalLogic.match ?? 'all', conditions: [...(conditionalLogic.conditions ?? []), { field_key: schemaFields.find(f => f.id !== field.id)?.field_key ?? '', operator: 'equals', value: '' }] })}>Add condition</Btn>
          </FormField>
          {logicError && <div role="alert" style={{ color: '#ff5a5a', fontSize: 11, marginTop: -8, marginBottom: 10 }}>{logicError}</div>}
        </div>

        {/* Options (enum / radio / multiselect) */}
        {hasOpts && (
          <div style={{ marginBottom: 14 }}>
            <div style={{
              fontSize: 10, fontWeight: 700,
              fontFamily: 'var(--font-display)',
              color: 'var(--text-muted)',
              letterSpacing: '0.10em', textTransform: 'uppercase' as const,
              marginBottom: 6,
            }}>
              Options
            </div>
            <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
              <input
                style={{ ...inputStyle, flex: 1 }}
                placeholder="Add option value…"
                value={optionInput}
                onChange={e => setOption(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && addOption()}
              />
              <Btn ghost small onClick={addOption}>Add</Btn>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {((draft.options ?? []) as string[]).map(opt => (
                <div key={opt} style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '4px 8px', borderRadius: 4,
                  background: 'rgba(255,255,255,0.05)',
                  fontSize: 12, fontFamily: 'var(--font-display)', color: 'var(--chalk2)',
                }}>
                  <span style={{ flex: 1 }}>{opt}</span>
                  <button
                    onClick={() => removeOption(opt)}
                    style={{
                      background: 'none', border: 'none', cursor: 'pointer',
                      color: 'rgba(255,80,80,0.70)', fontSize: 12, padding: 2,
                    }}
                  >✕</button>
                </div>
              ))}
              {((draft.options ?? []) as string[]).length === 0 && (
                <div style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-display)' }}>
                  No options yet
                </div>
              )}
            </div>
          </div>
        )}

        {/* Validation rules */}
        {valRules.length > 0 && (
          <div style={{ marginBottom: 14 }}>
            <div style={{
              fontSize: 10, fontWeight: 700,
              fontFamily: 'var(--font-display)',
              color: 'var(--text-muted)',
              letterSpacing: '0.10em', textTransform: 'uppercase' as const,
              marginBottom: 6,
            }}>
              Validation Rules
            </div>
            {valRules.map(rule => (
              <FormField key={rule} label={rule} small>
                <input
                  style={inputStyle}
                  placeholder={`Value for ${rule}`}
                  value={String(((draft.validation_rules ?? {}) as Record<string, unknown>)[rule] ?? '')}
                  onChange={e => setVRule(rule, e.target.value)}
                />
              </FormField>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div style={{
        padding: '10px 14px', borderTop: '1px solid var(--color-border)',
        display: 'flex', gap: 8, justifyContent: 'flex-end', flexShrink: 0,
      }}>
        <Btn ghost small onClick={onClose}>Cancel</Btn>
        <Btn
          primary small
          disabled={saving || !((draft.label as string)?.trim())}
          onClick={() => {
            let conditional_logic: unknown = null;
            try { conditional_logic = String(draft.conditional_logic ?? '').trim() ? JSON.parse(String(draft.conditional_logic)) : null; }
            catch { setLogicError('Enter valid JSON for conditional logic.'); return; }
            const roleList = (key: string) => String(draft[key] ?? '').split(',').map(v => v.trim()).filter(Boolean);
            const stageValue = (key: string) => String(draft[key] ?? '').trim() === '' ? null : Number(draft[key]);
            onSave({ ...draft, conditional_logic, role_visibility: roleList('role_visibility'), role_editable: roleList('role_editable'), stage_visible_from: stageValue('stage_visible_from'), stage_required_at: stageValue('stage_required_at') });
          }}
        >
          {saving ? 'Saving…' : 'Save Field'}
        </Btn>
      </div>
    </div>
  );
}

// ══ ASSOCIATIONS PANEL (right drawer — Phase 8) ══════════════

const BLANK_ASSOC_FORM = {
  context_type:  'module',
  context_id:    '',
  context_label: '',
  is_mandatory:  false,
  display_order: 0,
  trigger_event: '' as string,
};

function AssociationsPanel({
  schemaId,
  onClose,
}: {
  schemaId: string;
  onClose:  () => void;
}) {
  const qc = useQueryClient();
  const [showCreate,    setShowCreate]    = useState(false);
  const [editingAssoc,  setEditingAssoc]  = useState<FormAssociation | null>(null);
  const [form,          setForm]          = useState({ ...BLANK_ASSOC_FORM });
  const [formErr,       setFormErr]       = useState('');

  const assocsQ = useQuery({
    queryKey: ['form-builder', 'associations', schemaId],
    queryFn:  () => formBuilderApi.getAssociations({ schema_id: schemaId, limit: 100 }),
  });

  const createMut = useMutation({
    mutationFn: () => formBuilderApi.createAssociation({
      schema_id:     schemaId,
      context_type:  form.context_type,
      context_id:    form.context_id.trim() || undefined,
      context_label: form.context_label.trim(),
      is_mandatory:  form.is_mandatory,
      display_order: form.display_order,
      trigger_event: form.trigger_event || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['form-builder', 'associations', schemaId] });
      setShowCreate(false);
      setForm({ ...BLANK_ASSOC_FORM });
      setFormErr('');
    },
    onError: (e: ApiError) => {
      const msg = e?.response?.data?.detail ?? 'Failed to create association.';
      setFormErr(typeof msg === 'string' ? msg : JSON.stringify(msg));
    },
  });

  const updateMut = useMutation({
    mutationFn: () => formBuilderApi.updateAssociation(editingAssoc!.id, {
      context_label: form.context_label.trim(),
      is_mandatory:  form.is_mandatory,
      display_order: form.display_order,
      trigger_event: form.trigger_event || null,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['form-builder', 'associations', schemaId] });
      setEditingAssoc(null);
      setForm({ ...BLANK_ASSOC_FORM });
      setFormErr('');
    },
    onError: (e: ApiError) => {
      const msg = e?.response?.data?.detail ?? 'Failed to update association.';
      setFormErr(typeof msg === 'string' ? msg : JSON.stringify(msg));
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => formBuilderApi.deleteAssociation(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['form-builder', 'associations', schemaId] });
    },
  });

  const openEdit = (a: FormAssociation) => {
    setEditingAssoc(a);
    setForm({
      context_type:  a.context_type,
      context_id:    a.context_id ?? '',
      context_label: a.context_label,
      is_mandatory:  a.is_mandatory,
      display_order: a.display_order,
      trigger_event: a.trigger_event ?? '',
    });
    setFormErr('');
  };

  const closeForm = () => {
    setShowCreate(false);
    setEditingAssoc(null);
    setForm({ ...BLANK_ASSOC_FORM });
    setFormErr('');
  };

  const associations = assocsQ.data?.associations ?? [];
  const isEditing    = !!editingAssoc;
  const showForm     = showCreate || isEditing;
  const isSaving     = createMut.isPending || updateMut.isPending;

  const ctxLabel = (ct: string) =>
    CONTEXT_TYPE_OPTIONS.find(o => o.value === ct)?.label ?? ct;
  const evtLabel = (ev: string | null) =>
    ev ? (TRIGGER_EVENT_OPTIONS.find(o => o.value === ev)?.label ?? ev) : '—';

  return (
    <div style={{
      width: 320, flexShrink: 0,
      borderLeft: '1px solid var(--color-border)',
      display: 'flex', flexDirection: 'column',
      background: 'var(--color-surface)', overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center',
        padding: '10px 14px', borderBottom: '1px solid var(--color-border)', flexShrink: 0,
      }}>
        <div style={{
          flex: 1, fontSize: 12, fontWeight: 700,
          fontFamily: 'var(--font-display)', color: 'var(--chalk1)',
        }}>
          Associations
        </div>
        {!showForm && (
          <Btn ghost small onClick={() => { setShowCreate(true); setFormErr(''); }}>
            + Add
          </Btn>
        )}
        <button
          onClick={showForm ? closeForm : onClose}
          style={{
            marginLeft: 8, background: 'none', border: 'none', cursor: 'pointer',
            color: 'var(--text-muted)', fontSize: 20, lineHeight: 1, padding: 4,
          }}
        >
          {showForm ? '←' : '×'}
        </button>
      </div>

      {/* Create / Edit form */}
      {showForm && (
        <div style={{ flex: 1, overflowY: 'auto', padding: 14, scrollbarWidth: 'thin' as const }}>
          <div style={{
            fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-display)',
            color: 'var(--text-muted)', marginBottom: 12,
            textTransform: 'uppercase' as const, letterSpacing: '.08em',
          }}>
            {isEditing ? 'Edit Association' : 'New Association'}
          </div>

          <FormField label="Context Type">
            <GlassSelect value={String(form.context_type)} onChange={v => setForm(f => ({ ...f, context_type: v }))} options={[...CONTEXT_TYPE_OPTIONS.map((o) => ({ value: String(o.value), label: String(o.label) }))]} disabled={isEditing} ariaLabel="Context type" />
          </FormField>

          {!isEditing && (
            <FormField label="Context ID (optional UUID)">
              <input
                style={inputStyle}
                placeholder="Leave blank for module-level"
                value={form.context_id}
                onChange={e => setForm(f => ({ ...f, context_id: e.target.value }))}
              />
            </FormField>
          )}

          <FormField label="Context Label">
            <input
              style={inputStyle}
              placeholder="e.g. Customer Intake"
              value={form.context_label}
              onChange={e => setForm(f => ({ ...f, context_label: e.target.value }))}
            />
          </FormField>

          <FormField label="Trigger Event">
            <GlassSelect value={String(form.trigger_event)} onChange={v => setForm(f => ({ ...f, trigger_event: v }))} options={[...TRIGGER_EVENT_OPTIONS.map((o) => ({ value: String(o.value), label: String(o.label) }))]} placeholder={'— None —'} ariaLabel="Trigger event" />
          </FormField>

          <FormField label="Display Order">
            <input
              style={inputStyle}
              type="number" min={0}
              value={form.display_order}
              onChange={e => setForm(f => ({ ...f, display_order: Number(e.target.value) }))}
            />
          </FormField>

          <Toggle
            label="Mandatory"
            description="Submission cannot advance without completing this form"
            checked={form.is_mandatory}
            onChange={v => setForm(f => ({ ...f, is_mandatory: v }))}
          />

          {formErr && (
            <div style={{
              marginTop: 10, padding: '8px 10px', borderRadius: 6,
              background: 'rgba(255,80,80,0.12)', color: '#ff5a5a',
              fontSize: 11, fontFamily: 'var(--font-display)',
            }}>
              {formErr}
            </div>
          )}

          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', marginTop: 14 }}>
            <Btn ghost small onClick={closeForm}>Cancel</Btn>
            <Btn
              primary small
              disabled={isSaving || !form.context_label.trim()}
              onClick={() => isEditing ? updateMut.mutate() : createMut.mutate()}
            >
              {isSaving ? 'Saving…' : isEditing ? 'Update' : 'Create'}
            </Btn>
          </div>
        </div>
      )}

      {/* List */}
      {!showForm && (
        <div style={{ flex: 1, overflowY: 'auto', padding: 14, scrollbarWidth: 'thin' as const }}>
          {assocsQ.isLoading && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-display)' }}>
              Loading…
            </div>
          )}
          {!assocsQ.isLoading && associations.length === 0 && (
            <div style={{
              textAlign: 'center', padding: '36px 0',
              fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-display)',
            }}>
              No associations yet.
              <br />
              <span style={{ fontSize: 11, opacity: 0.7 }}>
                Link this schema to a module, pipeline stage, or other context.
              </span>
            </div>
          )}
          {associations.map(a => (
            <div key={a.id} style={{
              padding: '10px 12px', marginBottom: 8, borderRadius: 8,
              border: '1px solid var(--color-border)',
              background: 'var(--color-surface)',
            }}>
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                <div style={{ flex: 1, overflow: 'hidden' }}>
                  <div style={{
                    fontSize: 12, fontWeight: 600,
                    fontFamily: 'var(--font-display)', color: 'var(--chalk1)',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
                  }}>
                    {a.context_label}
                  </div>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' as const, marginTop: 4 }}>
                    <TagChip color="teal">{ctxLabel(a.context_type)}</TagChip>
                    {a.is_mandatory && <TagChip color="dim">mandatory</TagChip>}
                    {a.trigger_event && <TagChip>{evtLabel(a.trigger_event)}</TagChip>}
                  </div>
                  {a.context_id && (
                    <div style={{
                      fontSize: 9, fontFamily: 'monospace',
                      color: 'var(--text-muted)', marginTop: 3,
                    }}>
                      {a.context_id.slice(0, 8)}…
                    </div>
                  )}
                </div>
                <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
                  <IconBtn title="Edit" onClick={() => openEdit(a)}>✎</IconBtn>
                  <IconBtn danger title="Delete" onClick={() => {
                    if (window.confirm('Remove this association?')) deleteMut.mutate(a.id);
                  }}>✕</IconBtn>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ══ TOP BAR ══════════════════════════════════════════════════

function TopBar({
  schemas, selectedId, schema,
  onSelectSchema, onNewSchema, onPublish, onArchive, onVersionHistory,
  onPreview, onSubmissions, onAssociations,
  archiving,
}: {
  schemas:          FormSchema[];
  selectedId:       string | null;
  schema:           FormSchema | null;
  onSelectSchema:   (id: string) => void;
  onNewSchema:      () => void;
  onPublish:        () => void;
  onArchive:        () => void;
  onVersionHistory: () => void;
  onPreview:        () => void;
  onSubmissions:    () => void;
  onAssociations:   () => void;
  archiving:        boolean;
}) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '10px 16px',
      borderBottom: '1px solid var(--color-border)',
      background: 'var(--color-surface)', flexShrink: 0,
    }}>
      <div style={{
        fontSize: 14, fontWeight: 700,
        fontFamily: 'var(--font-display)', color: 'var(--chalk1)',
        marginRight: 4, whiteSpace: 'nowrap' as const,
      }}>
        Form Builder
      </div>

      <GlassSelect value={String(selectedId ?? '')} onChange={v => v && onSelectSchema(v)} options={[...schemas.map((s) => ({ value: String(s.id), label: String(s.name) }))]} placeholder={'— Select a schema —'} ariaLabel="Form schema" compact />

      {schema && <StatusBadge status={schema.status} />}

      <div style={{ flex: 1 }} />

      {schema && schema.current_version > 0 && (
        <Btn ghost small onClick={onVersionHistory}>
          Versions ({schema.current_version})
        </Btn>
      )}

      {schema && (
        <Btn ghost small onClick={onAssociations}>Associations</Btn>
      )}

      {schema && schema.status === 'published' && (
        <>
          <Btn ghost small onClick={onPreview}>Preview</Btn>
          <Btn ghost small onClick={onSubmissions}>Submissions</Btn>
        </>
      )}

      {schema && schema.status !== 'archived' && (
        <>
          <Btn primary small onClick={onPublish}>
            {schema.status === 'published' ? 'Re-publish' : 'Publish'}
          </Btn>
          <Btn ghost small onClick={onArchive} disabled={archiving}>
            {archiving ? 'Archiving…' : 'Archive'}
          </Btn>
        </>
      )}

      <Btn primary small onClick={onNewSchema}>+ New Schema</Btn>
    </div>
  );
}

// ══ MAIN PAGE ════════════════════════════════════════════════

export default function FormBuilderNewPage() {
  const { schemaId: paramId } = useParams<{ schemaId?: string }>();
  const navigate = useNavigate();
  const qc       = useQueryClient();

  const [selectedId,       setSelectedId]       = useState<string | null>(paramId ?? null);
  const [editingField,     setEditingField]     = useState<FieldDefinition | null>(null);
  const [showCreate,       setShowCreate]       = useState(false);
  const [showPublish,      setShowPublish]      = useState(false);
  const [showVersions,     setShowVersions]     = useState(false);
  const [showAssociations, setShowAssociations] = useState(false);
  const [publishNote,      setPublishNote]      = useState('');
  const [createErr,        setCreateErr]        = useState('');

  // Create schema form state
  const [createForm, setCreateForm] = useState({
    name:         '',
    machine_name: '',
    machineEdited: false,    // track whether user manually changed machine_name
    module:       'generic',
    description:  '',
  });

  useEffect(() => {
    // Re-seed only when the selection changes, so in-progress edits survive
    // // parent re-renders.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    if (paramId && paramId !== selectedId) setSelectedId(paramId);
  // Re-seed only when the selection changes, so in-progress edits survive
  // // parent re-renders.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paramId]);

  // Auto-populate machine_name when name changes (unless manually edited)
  const handleNameChange = (name: string) => {
    setCreateForm(f => ({
      ...f,
      name,
      machine_name: f.machineEdited ? f.machine_name : toMachineName(name),
    }));
  };

  // ── Queries ──────────────────────────────────────────────────

  const schemasQ = useQuery({
    queryKey: ['form-builder', 'schemas'],
    queryFn:  () => formBuilderApi.getSchemas({ limit: 100 }),
  });

  const fieldTypesQ = useQuery({
    queryKey:  ['form-builder', 'field-types'],
    queryFn:   formBuilderApi.getFieldTypes,
    staleTime: Infinity,
  });

  const schemaQ = useQuery({
    queryKey: ['form-builder', 'schema', selectedId],
    queryFn:  () => formBuilderApi.getSchema(selectedId!),
    enabled:  !!selectedId,
  });

  const fieldsQ = useQuery({
    queryKey: ['form-builder', 'fields', selectedId],
    queryFn:  () => formBuilderApi.getFields(selectedId!),
    enabled:  !!selectedId,
  });

  // ── Mutations ────────────────────────────────────────────────

  const createSchemaMut = useMutation({
    mutationFn: formBuilderApi.createSchema,
    onSuccess: s => {
      qc.invalidateQueries({ queryKey: ['form-builder', 'schemas'] });
      setSelectedId(s.id);
      navigate(`/form-builder/${s.id}`, { replace: true });
      setShowCreate(false);
      setCreateForm({ name: '', machine_name: '', machineEdited: false, module: 'generic', description: '' });
      setCreateErr('');
    },
    onError: () => setCreateErr('Failed to create schema. Please try again.'),
  });

  const publishMut = useMutation({
    mutationFn: () => formBuilderApi.publishSchema(selectedId!, publishNote || undefined),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['form-builder', 'schema', selectedId] });
      qc.invalidateQueries({ queryKey: ['form-builder', 'schemas'] });
      qc.invalidateQueries({ queryKey: ['form-builder', 'versions', selectedId] });
      setShowPublish(false);
      setPublishNote('');
    },
  });

  const archiveMut = useMutation({
    mutationFn: () => formBuilderApi.archiveSchema(selectedId!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['form-builder', 'schema', selectedId] });
      qc.invalidateQueries({ queryKey: ['form-builder', 'schemas'] });
    },
  });

  const createFieldMut = useMutation({
    mutationFn: (data: { field_key: string; field_type: string; label: string }) =>
      formBuilderApi.createField(selectedId!, data),
    onSuccess: field => {
      qc.invalidateQueries({ queryKey: ['form-builder', 'fields', selectedId] });
      setEditingField(field);
    },
  });

  const updateFieldMut = useMutation({
    mutationFn: (data: Record<string, unknown>) =>
      formBuilderApi.updateField(selectedId!, editingField!.id, data as Parameters<typeof formBuilderApi.updateField>[2]),
    onSuccess: updated => {
      qc.invalidateQueries({ queryKey: ['form-builder', 'fields', selectedId] });
      setEditingField(updated);
    },
  });

  const deleteFieldMut = useMutation({
    mutationFn: (fieldId: string) => formBuilderApi.deleteField(selectedId!, fieldId),
    onSuccess: (_, deletedId) => {
      qc.invalidateQueries({ queryKey: ['form-builder', 'fields', selectedId] });
      if (editingField?.id === deletedId) setEditingField(null);
    },
  });

  const reorderMut = useMutation({
    mutationFn: (order: string[]) => formBuilderApi.reorderFields(selectedId!, order),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['form-builder', 'fields', selectedId] });
    },
  });

  // ── Derived ──────────────────────────────────────────────────

  const schemas    = schemasQ.data?.schemas ?? [];
  const fieldTypes = fieldTypesQ.data ?? [];
  const schema     = schemaQ.data ?? null;
  const fields     = [...(fieldsQ.data ?? [])].sort((a, b) => a.display_order - b.display_order);

  const groupedTypes: Record<string, FieldTypeInfo[]> = {};
  for (const ft of fieldTypes) (groupedTypes[ft.category] ??= []).push(ft);

  // ── Handlers ─────────────────────────────────────────────────

  const handleSelectSchema = (id: string) => {
    setSelectedId(id);
    setEditingField(null);
    setShowAssociations(false);
    navigate(`/form-builder/${id}`, { replace: true });
  };

  const handleAddField = (ft: FieldTypeInfo) => {
    if (!selectedId || schema?.status === 'archived') return;
    createFieldMut.mutate({
      field_key:  toFieldKey(ft.key),
      field_type: ft.key,
      label:      ft.label,
    });
  };

  const handleMoveField = (fieldId: string, dir: 'up' | 'down') => {
    const idx = fields.findIndex(f => f.id === fieldId);
    if (idx < 0) return;
    if (dir === 'up'   && idx === 0)                return;
    if (dir === 'down' && idx === fields.length - 1) return;
    const next = [...fields];
    const swapIdx = dir === 'up' ? idx - 1 : idx + 1;
    [next[idx], next[swapIdx]] = [next[swapIdx], next[idx]];
    reorderMut.mutate(next.map(f => f.id));
  };

  // ── Render ───────────────────────────────────────────────────

  return (
    <div data-surface="console" style={{
      display: 'flex', flexDirection: 'column',
      height: '100%', background: 'var(--color-surface)', overflow: 'hidden',
    }}>
      <h1 className="sr-only">Form builder</h1>
      <TopBar
        schemas={schemas}
        selectedId={selectedId}
        schema={schema}
        onSelectSchema={handleSelectSchema}
        onNewSchema={() => setShowCreate(true)}
        onPublish={() => setShowPublish(true)}
        onArchive={() => {
          if (window.confirm('Archive this schema? It will no longer accept new submissions.')) {
            archiveMut.mutate();
          }
        }}
        onVersionHistory={() => setShowVersions(true)}
        onPreview={() => navigate(`/form-builder/${selectedId}/preview`)}
        onSubmissions={() => navigate(`/form-builder/${selectedId}/submissions`)}
        onAssociations={() => { setShowAssociations(v => !v); setEditingField(null); }}
        archiving={archiveMut.isPending}
      />

      {/* ── Pending structural changes → dynamic DDL ────────── */}
      {selectedId && schema && (
        <SchemaChangeReview
          schemaId={selectedId}
          enabled={schema.status !== 'archived'}
        />
      )}

      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <FieldTypePalette
          groupedTypes={groupedTypes}
          canAdd={!!selectedId && schema?.status !== 'archived' && !showAssociations}
          adding={createFieldMut.isPending}
          onAdd={handleAddField}
        />

        <SchemaCanvas
          schema={schema}
          fields={fields}
          loading={fieldsQ.isLoading}
          editingFieldId={editingField?.id ?? null}
          onEditField={f => { setEditingField(f); setShowAssociations(false); }}
          onDeleteField={id => {
            if (window.confirm('Delete this field? This cannot be undone.')) {
              deleteFieldMut.mutate(id);
            }
          }}
          onMoveField={handleMoveField}
        />

        {showAssociations && selectedId ? (
          <AssociationsPanel
            schemaId={selectedId}
            onClose={() => setShowAssociations(false)}
          />
        ) : (
          <FieldConfigDrawer
            field={editingField}
            fieldTypes={fieldTypes}
            schemaFields={fields}
            saving={updateFieldMut.isPending}
            onSave={data => updateFieldMut.mutate(data)}
            onClose={() => setEditingField(null)}
          />
        )}
      </div>

      {/* ── Create schema modal ─────────────────────────────── */}
      {showCreate && (
        <Modal
          title="New Form Schema"
          onClose={() => { setShowCreate(false); setCreateErr(''); }}
        >
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <FormField label="Schema Name">
              <input
                style={inputStyle}
                placeholder="e.g. Customer Intake Form"
                value={createForm.name}
                onChange={e => handleNameChange(e.target.value)}
              />
            </FormField>
            <FormField label="Machine Name">
              <input
                style={inputStyle}
                placeholder="e.g. customer_intake_form"
                value={createForm.machine_name}
                onChange={e => setCreateForm(f => ({
                  ...f,
                  machine_name: e.target.value,
                  machineEdited: true,
                }))}
              />
              <div style={{
                fontSize: 10, color: 'var(--text-muted)',
                fontFamily: 'var(--font-display)', marginTop: 3,
              }}>
                Lowercase letters, numbers and underscores only. Must start with a letter.
              </div>
            </FormField>
            <FormField label="Module">
              <GlassSelect value={String(createForm.module)} onChange={v => setCreateForm(f => ({ ...f, module: v }))} options={[...MODULES.map((m) => ({ value: String(m.value), label: String(m.label) }))]} ariaLabel="Module" />
            </FormField>
            <FormField label="Description (optional)">
              <textarea
                style={{ ...inputStyle, height: 68, resize: 'vertical' as const }}
                placeholder="Brief description of this form's purpose"
                value={createForm.description}
                onChange={e => setCreateForm(f => ({ ...f, description: e.target.value }))}
              />
            </FormField>
            {createErr && (
              <div style={{ color: '#ff5a5a', fontSize: 12, fontFamily: 'var(--font-display)' }}>
                {createErr}
              </div>
            )}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <Btn ghost onClick={() => { setShowCreate(false); setCreateErr(''); }}>Cancel</Btn>
              <Btn
                primary
                disabled={
                  !createForm.name.trim() ||
                  !createForm.machine_name.trim() ||
                  !/^[a-z][a-z0-9_]*$/.test(createForm.machine_name) ||
                  createSchemaMut.isPending
                }
                onClick={() => {
                  setCreateErr('');
                  createSchemaMut.mutate({
                    name:         createForm.name.trim(),
                    machine_name: createForm.machine_name.trim(),
                    module:       createForm.module,
                    description:  createForm.description.trim() || undefined,
                  });
                }}
              >
                {createSchemaMut.isPending ? 'Creating…' : 'Create Schema'}
              </Btn>
            </div>
          </div>
        </Modal>
      )}

      {/* ── Publish / Re-publish modal ────────────────────── */}
      {showPublish && (
        <Modal
          title={schema?.status === 'published' ? 'Re-publish Schema' : 'Publish Schema'}
          onClose={() => { setShowPublish(false); setPublishNote(''); }}
        >
          <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
            {schema?.status === 'published' ? (
              <p style={{
                margin: 0, fontSize: 13,
                color: 'var(--chalk3)', fontFamily: 'var(--font-display)', lineHeight: 1.5,
              }}>
                Publishing creates a new <strong style={{ color: 'var(--chalk2)' }}>
                  v{(schema?.current_version ?? 0) + 1}
                </strong> immutable snapshot of the current fields. The previous version
                remains in history and is never modified.
              </p>
            ) : (
              <p style={{
                margin: 0, fontSize: 13,
                color: 'var(--chalk3)', fontFamily: 'var(--font-display)', lineHeight: 1.5,
              }}>
                Publishing creates an <strong style={{ color: 'var(--chalk2)' }}>immutable
                version snapshot</strong> of the current field set. You can continue editing and
                re-publish to create future versions.
              </p>
            )}
            <FormField label="Changelog (optional)">
              <input
                style={inputStyle}
                placeholder="e.g. Added email verification field"
                value={publishNote}
                onChange={e => setPublishNote(e.target.value)}
              />
            </FormField>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <Btn ghost onClick={() => { setShowPublish(false); setPublishNote(''); }}>Cancel</Btn>
              <Btn primary disabled={publishMut.isPending} onClick={() => publishMut.mutate()}>
                {publishMut.isPending
                  ? 'Publishing…'
                  : schema?.status === 'published' ? 'Re-publish' : 'Publish Schema'}
              </Btn>
            </div>
          </div>
        </Modal>
      )}

      {/* ── Version history modal (Phase 6) ─────────────── */}
      {showVersions && schema && (
        <VersionHistoryModal
          schemaId={schema.id}
          schemaName={schema.name}
          onClose={() => setShowVersions(false)}
        />
      )}
    </div>
  );
}
