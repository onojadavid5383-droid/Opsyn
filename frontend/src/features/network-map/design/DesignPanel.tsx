// ============================================================
// OPSYN DESIGN — the left panel in design mode (replaces the layer
// panel). Header: project · version · status. Then the boundary (draw,
// from inputs, clear) and the design's inputs: one row per layer with its
// count, a map switch, upload (replace or add) and remove. The live
// network stays on the map underneath as dimmed context.
// ============================================================

import { useId, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, PanelLeftClose, PenLine, Shapes, Trash2, Upload } from 'lucide-react';
import type { Design, DesignInputLayer, DesignInputLayerKey, DesignInputUploadResult } from '@shared';
import { Badge } from '../../../components/ui';
import {
  DESIGN_STATUS_LABEL, DESIGN_STATUS_TONE, INPUT_LAYERS, INPUT_META, designError, isEditable, type InputLayerMeta,
} from './designFormat';
import { useBoundaryFromInputs, useDesignInputs, useRemoveInputs, useUpdateDesign, useUploadInputs } from './designQueries';
import { useDesignMapStore } from './designStore';
import s from '../NetworkMap.module.css';
import d from './Design.module.css';

function InputSwatch({ meta }: { meta: InputLayerMeta }) {
  return (
    <svg className={s.swatch} viewBox="0 0 26 26" aria-hidden="true">
      {meta.geometry === 'line' && (<>
        <path d="M3 19 C 9 19, 12 7, 23 7" fill="none" stroke="#FFFFFF" strokeWidth={6} strokeLinecap="round" />
        <path d="M3 19 C 9 19, 12 7, 23 7" fill="none" stroke={meta.color} strokeWidth={3} strokeLinecap="round" />
      </>)}
      {meta.geometry === 'area' && <rect x="5" y="6" width="16" height="14" rx="1.5" fill={meta.color} fillOpacity={0.3} stroke={meta.color} strokeWidth={1.5} />}
      {meta.geometry === 'point' && (meta.key === 'homepass'
        ? <circle cx="13" cy="13" r="6" fill="#FFFFFF" stroke={meta.color} strokeWidth={2.5} />
        : <circle cx="13" cy="13" r={meta.key === 'pickup' ? 7 : 5} fill={meta.color} stroke="#FFFFFF" strokeWidth={2} />)}
    </svg>
  );
}

function UploadOutcome({ result, error }: { result: DesignInputUploadResult | undefined; error: unknown }) {
  if (error) return <p className={d.err} role="alert">{designError(error, 'The file could not be uploaded.')}</p>;
  if (!result) return null;
  if (result.status === 'rejected') {
    return (
      <div className={d.outcome} data-tone="bad" role="alert">
        <p>Nothing was saved: {result.errors.length} {result.errors.length === 1 ? 'problem' : 'problems'} in the file.</p>
        <ul>
          {result.errors.slice(0, 5).map((e, i) => (
            <li key={i}>{e.row ? `Feature ${e.row}: ` : ''}{e.error}</li>
          ))}
          {result.errors.length > 5 && <li>…and {result.errors.length - 5} more</li>}
        </ul>
      </div>
    );
  }
  return (
    <div className={d.outcome} data-tone="ok" role="status">
      <p>Saved {result.feature_count.toLocaleString('en-GB')} features.</p>
      {result.warnings.length > 0 && <ul>{result.warnings.map(w => <li key={w}>{w}</li>)}</ul>}
    </div>
  );
}

function InputRow({ designId, layer, editable }: { designId: string; layer: DesignInputLayer | undefined; editable: boolean }) {
  const meta = INPUT_META[(layer?.layer_key ?? 'road') as DesignInputLayerKey];
  const key = meta.key;
  const count = layer?.feature_count ?? 0;
  const id = useId();
  const fileRef = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState<File | null>(null);
  const [confirmRemove, setConfirmRemove] = useState(false);
  const { hiddenInputs, toggleInput } = useDesignMapStore();
  const upload = useUploadInputs(designId);
  const remove = useRemoveInputs(designId);

  const send = (file: File, mode: 'replace' | 'append') => {
    setPending(null);
    upload.mutate({ layer: key, file, mode });
  };
  const onFile = (file: File | undefined) => {
    if (!file) return;
    if (fileRef.current) fileRef.current.value = '';
    upload.reset();
    if (count === 0) send(file, 'replace');
    else setPending(file);                        // ask: replace or add?
  };

  return (
    <li className={d.inputItem}>
      <div className={s.row} data-empty={count === 0}>
        <InputSwatch meta={meta} />
        <label className={s.rowLabel} htmlFor={id}>
          {meta.label}
          {layer?.last_upload?.filename && <span className={s.rowHint}>{layer.last_upload.filename}</span>}
        </label>
        <span className={s.rowCount} aria-label={`${count} features`}>{count.toLocaleString('en-GB')}</span>
        <input id={id} type="checkbox" checked={!hiddenInputs.includes(key)} onChange={() => toggleInput(key)}
          aria-label={`Show ${meta.label.toLowerCase()} on the map`} />
      </div>

      {editable && (
        <div className={d.inputTools}>
          <input
            ref={fileRef}
            type="file"
            accept=".geojson,.json,.xlsx"
            className={s.srOnly}
            tabIndex={-1}
            aria-hidden="true"
            onChange={e => onFile(e.target.files?.[0])}
          />
          <button type="button" className={d.miniBtn} onClick={() => fileRef.current?.click()} disabled={upload.isPending}
            aria-label={`Upload ${meta.label.toLowerCase()}`}>
            <Upload size={13} aria-hidden />{upload.isPending ? 'Uploading…' : 'Upload'}
          </button>
          {count > 0 && !confirmRemove && (
            <button type="button" className={d.miniBtn} onClick={() => setConfirmRemove(true)} aria-label={`Remove ${meta.label.toLowerCase()}`}>
              <Trash2 size={13} aria-hidden />Remove
            </button>
          )}
          <span className={d.accepts}>{meta.accepts}</span>
        </div>
      )}

      {pending && (
        <div className={d.choice} role="group" aria-label={`What to do with ${pending.name}`}>
          <p><strong>{pending.name}</strong>: replace the {count.toLocaleString('en-GB')} {meta.label.toLowerCase()} or add to them?</p>
          <div className={d.choiceBtns}>
            <button type="button" className={d.miniBtn} data-strong onClick={() => send(pending, 'replace')}>Replace</button>
            <button type="button" className={d.miniBtn} onClick={() => send(pending, 'append')}>Add to them</button>
            <button type="button" className={d.miniBtn} onClick={() => setPending(null)}>Cancel</button>
          </div>
        </div>
      )}

      {confirmRemove && (
        <div className={d.choice} role="group" aria-label={`Remove ${meta.label.toLowerCase()}`}>
          <p>Remove all {count.toLocaleString('en-GB')} {meta.label.toLowerCase()} from this design?</p>
          <div className={d.choiceBtns}>
            <button type="button" className={d.miniBtn} data-danger
              onClick={() => remove.mutate(key, { onSettled: () => setConfirmRemove(false) })} disabled={remove.isPending}>
              {remove.isPending ? 'Removing…' : 'Remove'}
            </button>
            <button type="button" className={d.miniBtn} onClick={() => setConfirmRemove(false)}>Keep</button>
          </div>
        </div>
      )}
      {remove.isError && <p className={d.err} role="alert">{designError(remove.error)}</p>}
      <UploadOutcome result={upload.data} error={upload.error} />
    </li>
  );
}

interface Props {
  design: Design;
  onHide: () => void;
  onFit:  () => void;
}

export function DesignPanel({ design, onHide, onFit }: Props) {
  const navigate = useNavigate();
  const inputs = useDesignInputs(design.id);
  const fromInputs = useBoundaryFromInputs(design.id);
  const update = useUpdateDesign(design.id);
  const { drawing, setDrawing, setDrawer, mode, setMode } = useDesignMapStore();
  // Deployment follows approval (Phase 9 → 10)
  const deployable = design.status === 'APPROVED' || design.status === 'DEPLOYED';
  const editable = isEditable(design.status);
  const totalInputs = Object.values(design.input_counts).reduce((a, b) => a + b, 0);
  const byKey = new Map(inputs.data?.map(l => [l.layer_key, l]));

  return (
    <aside className={s.panel} aria-label="Design">
      <div className={s.panelHead}>
        <div style={{ minWidth: 0 }}>
          <Link className={d.crumb} to={`/projects/${design.project_id}`}>
            <ArrowLeft size={13} aria-hidden />{design.project_name ?? 'Project'}
          </Link>
          <h1 className={s.title} tabIndex={-1}>{design.name}</h1>
          <p className={d.headMeta}>
            <button type="button" className={d.versionLink} onClick={() => setDrawer('versions')}
              title="Versions and history">
              {design.current_version ? `Version ${design.current_version.version_no}` : 'No version'}
            </button>
            <Badge tone={DESIGN_STATUS_TONE[design.status]} dot size="xs">{DESIGN_STATUS_LABEL[design.status]}</Badge>
          </p>
        </div>
        <button type="button" className={s.iconBtn} onClick={onHide} aria-label="Hide design panel" title="Hide design panel">
          <PanelLeftClose size={18} aria-hidden />
        </button>
      </div>

      <div className={s.modes} role="group" aria-label="Map mode">
        <button type="button" className={s.mode} aria-pressed="false" onClick={() => navigate('/network')}>Network</button>
        <button type="button" className={s.mode} aria-pressed={mode === 'design'} onClick={() => setMode('design')}>Design</button>
        <button type="button" className={s.mode} aria-pressed={mode === 'deployment'} disabled={!deployable}
          aria-describedby="dp-mode-note" onClick={() => setMode('deployment')}>Deployment</button>
      </div>
      <p id="dp-mode-note" className={s.modeNote}>
        {mode === 'deployment' ? 'Each device and cable is ringed in the colour of its install state.'
          : deployable ? 'The network in service is shown faded for context. Deployment tracks the build.'
          : 'The network in service is shown faded for context. Deployment opens once the design and its BOQ are approved.'}
      </p>

      <div className={s.groups}>
        <section className={d.block} aria-labelledby="dp-boundary">
          <div className={d.blockHead}>
            <h2 id="dp-boundary">Boundary</h2>
            <span className={d.blockState} data-set={!!design.boundary}>{design.boundary ? 'Set' : 'Not set'}</span>
          </div>
          <p className={d.blockNote}>
            {design.boundary
              ? 'The design covers the area inside the dashed line. Inputs outside it are flagged.'
              : 'Draw the area this design covers, or take it from the inputs once they are uploaded.'}
          </p>
          {editable && (
            <div className={d.blockBtns}>
              <button type="button" className={d.miniBtn} data-strong={!design.boundary || undefined}
                aria-pressed={drawing} onClick={() => setDrawing(!drawing)}>
                <PenLine size={13} aria-hidden />{drawing ? 'Drawing…' : design.boundary ? 'Redraw' : 'Draw'}
              </button>
              <button type="button" className={d.miniBtn} onClick={() => fromInputs.mutate()}
                disabled={!totalInputs || fromInputs.isPending}
                title={totalInputs ? 'Outline every input, 30 m wide of the outermost' : 'Upload inputs first'}>
                <Shapes size={13} aria-hidden />{fromInputs.isPending ? 'Working…' : 'From inputs'}
              </button>
              {design.boundary && (
                <button type="button" className={d.miniBtn} onClick={() => update.mutate({ boundary: null })} disabled={update.isPending}>
                  Clear
                </button>
              )}
            </div>
          )}
          {(fromInputs.isError || update.isError) && (
            <p className={d.err} role="alert">{designError(fromInputs.error ?? update.error)}</p>
          )}
        </section>

        <section className={d.block} aria-labelledby="dp-inputs">
          <div className={d.blockHead}>
            <h2 id="dp-inputs">Inputs</h2>
            {design.bbox && <button type="button" className={s.textBtn} onClick={onFit}>Zoom to design</button>}
          </div>
          <p className={d.blockNote}>
            Roads are the routing graph: every cable in this design follows them. GeoJSON or Excel; a file with any bad
            feature is rejected whole.
          </p>
          {inputs.isError && <p className={d.err} role="alert">{designError(inputs.error, "Couldn't load the inputs.")}</p>}
          <ul className={d.inputList}>
            {INPUT_LAYERS.map(meta => (
              <InputRow
                key={meta.key}
                designId={design.id}
                layer={byKey.get(meta.key) ?? { layer_key: meta.key, label: meta.label, feature_count: design.input_counts[meta.key] ?? 0, last_upload: null }}
                editable={editable}
              />
            ))}
          </ul>
          {!editable && (
            <p className={d.blockNote}>This design is {DESIGN_STATUS_LABEL[design.status].toLowerCase()}; its inputs can't be changed.</p>
          )}
        </section>
      </div>
    </aside>
  );
}
