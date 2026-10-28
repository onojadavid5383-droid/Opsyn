// ============================================================
// OPSYN DESIGN — manual design tools (Phase 6): a vertical tool rail on
// the map's left edge, what-to-do-next card, undo / redo (on the server,
// so they survive a reload) and the keyboard: V select, H pan, R measure,
// A add, M move, D delete, C cable, K connect, X split, E extend,
// G redraw; Ctrl+Z undo, Ctrl+Shift+Z / Ctrl+Y redo; Enter finishes a
// redraw, Esc steps back (then back to Select), Delete / Backspace picks
// the Delete tool.
// ============================================================

import { useCallback, useEffect } from 'react';
import {
  Cable, GitFork, Hand, MousePointer2, Move, PencilLine, Plus, Radius, Redo2, Scissors, Trash2, Undo2, Waypoints, X,
  type LucideIcon,
} from 'lucide-react';
import { formatKm } from './designFormat';
import { ADDABLE, DRAWABLE, SHORTCUTS, hint, pathLength, type EditTool } from './editMachine';
import { useDesignMapStore } from './designStore';
import { useOperationLog, useUndoRedo } from './designQueries';
import d from './Design.module.css';

const TOOLS: { tool: EditTool; label: string; icon: LucideIcon; key: string }[] = [
  { tool: 'select', label: 'Select', icon: MousePointer2, key: 'V' },
  { tool: 'pan', label: 'Pan', icon: Hand, key: 'H' },
  { tool: 'measure', label: 'Measure', icon: Radius, key: 'R' },
  { tool: 'add', label: 'Add a device', icon: Plus, key: 'A' },
  { tool: 'move', label: 'Move', icon: Move, key: 'M' },
  { tool: 'delete', label: 'Delete', icon: Trash2, key: 'D' },
  { tool: 'cable', label: 'Draw a cable', icon: Cable, key: 'C' },
  { tool: 'connect', label: 'Connect (feeds)', icon: GitFork, key: 'K' },
  { tool: 'split', label: 'Split a cable', icon: Scissors, key: 'X' },
  { tool: 'extend', label: 'Extend a cable', icon: Waypoints, key: 'E' },
  { tool: 'redraw', label: 'Redraw a cable', icon: PencilLine, key: 'G' },
];

function typing(t: EventTarget | null) {
  return t instanceof HTMLInputElement || t instanceof HTMLTextAreaElement || t instanceof HTMLSelectElement
    || (t instanceof HTMLElement && t.isContentEditable);
}

export function ManualToolbar({ designId, busy }: { designId: string; busy: boolean }) {
  const { edit, send, note, setManual, setNote, change, setDrawer } = useDesignMapStore();
  const log = useOperationLog(designId);
  const { undo, redo } = useUndoRedo(designId);
  const canUndo = !!log.data?.can_undo && !undo.isPending && !redo.isPending && !busy;
  const canRedo = !!log.data?.can_redo && !undo.isPending && !redo.isPending && !busy;
  // Say what was undone / redone: the map change alone can be easy to miss
  const { mutate: undoMutate } = undo;
  const { mutate: redoMutate } = redo;
  const doUndo = useCallback(() => undoMutate(undefined, {
    onSuccess: res => setNote({ tone: 'ok', text: res.operation.label }),
  }), [undoMutate, setNote]);
  const doRedo = useCallback(() => redoMutate(undefined, {
    onSuccess: res => setNote({ tone: 'ok', text: res.operation.label }),
  }), [redoMutate, setNote]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (typing(e.target)) return;
      const k = e.key.toLowerCase();
      if ((e.ctrlKey || e.metaKey) && k === 'z') {
        e.preventDefault();
        if (e.shiftKey) { if (canRedo) doRedo(); } else if (canUndo) doUndo();
        return;
      }
      if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); if (canRedo) doRedo(); return; }
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      if (k === 'escape') { send({ type: 'CANCEL' }); return; }
      if (k === 'enter') { send({ type: 'FINISH' }); return; }
      if (k === 'delete' || k === 'backspace') { send({ type: 'TOOL', tool: 'delete' }); return; }
      const tool = SHORTCUTS[k];
      if (tool) send({ type: 'TOOL', tool });
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [send, canUndo, canRedo, doUndo, doRedo]);

  const mutError = (undo.error ?? redo.error) as { detail?: string; message?: string } | null;
  const measured = edit.tool === 'measure' && edit.points.length >= 2 ? pathLength(edit.points) : null;

  return (
    <>
      <nav className={d.palette} aria-label="Manual design tools">
        {TOOLS.map(t => (
          <button key={t.tool} type="button" className={d.paletteBtn} aria-pressed={edit.tool === t.tool}
            onClick={() => send({ type: 'TOOL', tool: t.tool })} title={`${t.label} (${t.key})`} aria-label={t.label}
            aria-keyshortcuts={t.key}>
            <t.icon size={17} aria-hidden />
          </button>
        ))}
        <span className={d.paletteRule} aria-hidden />
        <button type="button" className={d.paletteBtn} onClick={doUndo} disabled={!canUndo}
          title={log.data?.undo_label ? `Undo: ${log.data.undo_label} (Ctrl+Z)` : 'Nothing to undo'} aria-label="Undo" aria-keyshortcuts="Control+Z">
          <Undo2 size={17} aria-hidden />
        </button>
        <button type="button" className={d.paletteBtn} onClick={doRedo} disabled={!canRedo}
          title={log.data?.redo_label ? `Redo: ${log.data.redo_label} (Ctrl+Shift+Z)` : 'Nothing to redo'} aria-label="Redo"
          aria-keyshortcuts="Control+Shift+Z">
          <Redo2 size={17} aria-hidden />
        </button>
        <span className={d.paletteRule} aria-hidden />
        <button type="button" className={d.paletteBtn} onClick={() => setManual(false)} title="Close the manual tools" aria-label="Close the manual tools">
          <X size={17} aria-hidden />
        </button>
      </nav>

      <section className={d.toolCard} aria-label="Tool" aria-live="polite">
        <p className={d.toolTitle}>{TOOLS.find(t => t.tool === edit.tool)?.label}</p>

        {edit.tool === 'add' && (
          <div className={d.chips} role="radiogroup" aria-label="Device">
            {ADDABLE.map(a => (
              <button key={a.type} type="button" role="radio" aria-checked={edit.subtype === a.type} className={d.chip}
                onClick={() => send({ type: 'TOOL', tool: 'add', subtype: a.type })}>{a.label}</button>
            ))}
          </div>
        )}
        {edit.tool === 'cable' && (
          <div className={d.chips} role="radiogroup" aria-label="Cable">
            {DRAWABLE.map(c => (
              <button key={c.category} type="button" role="radio" aria-checked={edit.subtype === c.category} className={d.chip}
                onClick={() => send({ type: 'TOOL', tool: 'cable', subtype: c.category })}>{c.label}</button>
            ))}
          </div>
        )}
        {edit.tool === 'split' && (
          <div className={d.chips} role="radiogroup" aria-label="At the cut">
            <button type="button" role="radio" aria-checked={!edit.subtype} className={d.chip}
              onClick={() => send({ type: 'TOOL', tool: 'split', subtype: null })}>Just cut</button>
            <button type="button" role="radio" aria-checked={edit.subtype === 'CLOSURE'} className={d.chip}
              onClick={() => send({ type: 'TOOL', tool: 'split', subtype: 'CLOSURE' })}>Place a closure</button>
          </div>
        )}
        {(edit.tool === 'cable' || edit.tool === 'extend') && (
          <label className={d.routeToggle}>
            <input type="checkbox" checked={edit.route === 'road'}
              onChange={e => send({ type: 'ROUTE', route: e.target.checked ? 'road' : 'straight' })} />
            Follow the roads
          </label>
        )}

        <p className={d.toolHint}>{hint(edit)}</p>
        {measured !== null && <p className={d.toolMeasure}>{formatKm(measured / 1000)} over {edit.points.length} points</p>}
        {busy && <p className={d.toolHint} role="status">Working…</p>}
        {note && <p className={note.tone === 'error' ? d.err : d.toolOk} role={note.tone === 'error' ? 'alert' : 'status'}>{note.text}</p>}
        {mutError && <p className={d.err} role="alert">{mutError.detail ?? mutError.message}</p>}
        {change && change.rerouted.length > 0 && (
          <div className={d.rerouted}>
            <p>Recalculated {change.rerouted.length} {change.rerouted.length === 1 ? 'cable' : 'cables'}:</p>
            <ul>
              {change.rerouted.slice(0, 5).map(c => (
                <li key={c.id}>
                  <span>{c.code}</span>
                  <span className={d.num}>{Math.round(c.before_m)} → {Math.round(c.after_m)} m</span>
                  {c.note && <em>{c.note}</em>}
                </li>
              ))}
              {change.rerouted.length > 5 && <li>…and {change.rerouted.length - 5} more</li>}
            </ul>
          </div>
        )}
        {change && change.delta.issues.new.length > 0 && (
          // Local recalculation never re-assigns customers or re-places boxes (D7): that is a full engine run
          <p className={d.toolHint}>
            Customers to re-assign or boxes to re-place?{' '}
            <button type="button" className={d.linkish} onClick={() => setDrawer('auto')}>Regenerate with the engine</button>
            {' '}(a new version; this one is kept).
          </p>
        )}
        {(edit.tool === 'redraw' || edit.tool === 'measure') && (edit.points.length > 0 || edit.picks.length > 0) && (
          <div className={d.choiceBtns}>
            {edit.tool === 'redraw' && <button type="button" className={d.miniBtn} data-strong onClick={() => send({ type: 'FINISH' })}>Finish</button>}
            <button type="button" className={d.miniBtn} onClick={() => send({ type: 'CANCEL' })}>{edit.tool === 'measure' ? 'Clear' : 'Cancel'}</button>
          </div>
        )}
      </section>
    </>
  );
}
