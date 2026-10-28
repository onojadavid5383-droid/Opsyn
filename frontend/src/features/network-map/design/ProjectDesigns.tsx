// ============================================================
// OPSYN DESIGN — a project's network designs (project page, "Network
// designs" tab). Lists the designs, creates one (V1, Draft), and opens
// each in the map's design mode: /network?mode=design&design=<id>.
// ============================================================

import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { formatDistanceToNow } from 'date-fns';
import { Map as MapIcon, Plus } from 'lucide-react';
import type { Design } from '@shared';
import { Badge } from '../../../components/ui';
import { useCreateDesign, useProjectDesigns } from './designQueries';
import { DESIGN_STATUS_LABEL, DESIGN_STATUS_TONE, designError, designHref } from './designFormat';
import d from './Design.module.css';

function inputsLine(design: Design): string {
  const c = design.input_counts;
  const parts = [
    c.road && `${c.road.toLocaleString('en-GB')} road segments`,
    c.homepass && `${c.homepass.toLocaleString('en-GB')} homepasses`,
    c.pole && `${c.pole.toLocaleString('en-GB')} poles`,
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : 'No inputs uploaded yet';
}

function ago(iso: string): string {
  try { return formatDistanceToNow(new Date(iso), { addSuffix: true }); } catch { return iso; }
}

export function ProjectDesigns({ projectId }: { projectId: string }) {
  const designs = useProjectDesigns(projectId);
  const create = useCreateDesign(projectId);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState('');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    create.mutate({ name: name.trim() }, { onSuccess: () => { setName(''); setAdding(false); } });
  };

  return (
    <section className={d.designs} aria-labelledby="pd-title">
      <header className={d.designsHead}>
        <div>
          <h2 id="pd-title" className={d.designsTitle}>Network designs</h2>
          <p className={d.designsLede}>
            Each design has its own boundary and inputs. Open one on the map to upload roads and
            homepasses, check it, and read its bill of quantities.
          </p>
        </div>
        <div className={d.designsActions}>
          <Link className={d.ghostBtn} to="/network"><MapIcon size={15} aria-hidden />Open network map</Link>
          {!adding && (
            <button type="button" className={d.solidBtn} onClick={() => setAdding(true)}>
              <Plus size={15} aria-hidden />New design
            </button>
          )}
        </div>
      </header>

      {adding && (
        <form className={d.newDesign} onSubmit={submit}>
          <label htmlFor="pd-name">Design name</label>
          <div className={d.newDesignRow}>
            <input
              id="pd-name"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="e.g. Allen Avenue phase 1"
              maxLength={200}
              autoFocus
            />
            <button type="submit" className={d.solidBtn} disabled={!name.trim() || create.isPending}>
              {create.isPending ? 'Creating…' : 'Create design'}
            </button>
            <button type="button" className={d.ghostBtn} onClick={() => { setAdding(false); create.reset(); }}>Cancel</button>
          </div>
          {create.isError && <p className={d.err} role="alert">{designError(create.error, 'The design could not be created.')}</p>}
        </form>
      )}

      {designs.isLoading && <div className={d.skel} aria-label="Loading designs" />}
      {designs.isError && <p className={d.err} role="alert">{designError(designs.error, "Couldn't load this project's designs.")}</p>}

      {designs.data && designs.data.length === 0 && !adding && (
        <div className={d.emptyCard}>
          <p className={d.emptyTitle}>No designs yet</p>
          <p>Start one, then upload the area's roads and homepasses on the map.</p>
          <button type="button" className={d.solidBtn} onClick={() => setAdding(true)}>
            <Plus size={15} aria-hidden />New design
          </button>
        </div>
      )}

      {designs.data && designs.data.length > 0 && (
        <ul className={d.designList}>
          {designs.data.map(design => (
            <li key={design.id} className={d.designItem}>
              <div className={d.designMain}>
                <p className={d.designName}>
                  <Link to={designHref(design.id)}>{design.name}</Link>
                </p>
                <p className={d.designMeta}>
                  {design.current_version ? `Version ${design.current_version.version_no}` : 'No version'}
                  {' · '}updated {ago(design.updated_at)}
                </p>
                <p className={d.designMeta}>{inputsLine(design)}</p>
              </div>
              <Badge tone={DESIGN_STATUS_TONE[design.status]} dot>{DESIGN_STATUS_LABEL[design.status]}</Badge>
              <Link className={d.ghostBtn} to={designHref(design.id)} aria-label={`Open ${design.name} on the map`}>
                Open on map
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
