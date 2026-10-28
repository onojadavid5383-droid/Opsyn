// ============================================================
// OPSYN MAP — asset search (floating glass combobox)
// Find by what engineers actually type: OLT names, cabinet and splitter box
// IDs, site names. Enter picks the top result; the map flies to it and opens
// it in the inspector. ARIA combobox: focus stays in the input.
// ============================================================

import { Search } from 'lucide-react';
import { useId, useMemo, useState, type KeyboardEvent } from 'react';
import type { MapPalette } from './mapIcons';
import { searchAssets, type MapAsset } from './mapModel';
import { AssetShape } from './ShapeIcon';
import s from './InfraMap.module.css';

export default function MapSearch({ assets, palette, onPick }: {
  assets: MapAsset[]; palette: MapPalette; onPick: (a: MapAsset) => void;
}) {
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();
  const results = useMemo(() => searchAssets(assets, query), [assets, query]);
  const idx = Math.min(active, Math.max(results.length - 1, 0));

  const pick = (a: MapAsset | undefined) => {
    if (!a) return;
    onPick(a);
    setOpen(false);
    setQuery(a.label);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive((idx + 1) % Math.max(results.length, 1)); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive((idx - 1 + results.length) % Math.max(results.length, 1)); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(results[idx]); }
    else if (e.key === 'Escape') { setOpen(false); }
  };

  const showList = open && query.trim().length > 0;
  return (
    <div className={s.searchBox}>
      <Search size={16} className={s.searchIcon} aria-hidden="true" />
      <input
        className={`liquid-glass-menu ${s.searchInput}`}
        role="combobox"
        aria-label="Search assets"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={showList && results.length ? `${listId}-${idx}` : undefined}
        placeholder="Search OLT, cabinet, splitter, site…"
        value={query}
        onChange={e => { setQuery(e.target.value); setOpen(true); setActive(0); }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={onKeyDown}
        autoComplete="off"
        spellCheck={false}
      />
      {showList && (
        <div id={listId} role="listbox" aria-label="Matching assets" className={`liquid-glass-menu ${s.results}`}>
          {results.length === 0 && <p className={s.noResults}>No mapped asset matches “{query}”.</p>}
          {results.map((a, i) => (
            <div
              key={a.key}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === idx}
              data-active={i === idx ? 'true' : undefined}
              className={`liquid-glass-item ${s.result}`}
              onMouseMove={() => setActive(i)}
              onMouseDown={e => { e.preventDefault(); pick(a); }}
            >
              <AssetShape kind={a.kind} color={palette.state[a.state]} outline={palette.outline} level={(a.raw as { splitter_level?: string }).splitter_level} />
              <span className={s.resultText}>
                <span className={s.resultLabel}>{a.label}</span>
                <span className={s.resultSub}>{a.sublabel}</span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
