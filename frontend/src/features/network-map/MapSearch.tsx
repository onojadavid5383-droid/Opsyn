// ============================================================
// OPSYN NETWORK MAP — asset search (WAI-ARIA combobox).
// "Search by" narrows the match to code or name. Results come from
// GET /network/search (live assets only, exact code first), so every
// result can be flown to and selected.
// Keys: ↑/↓ move, Enter chooses, Esc clears.
// ============================================================

import { useEffect, useId, useState } from 'react';
import { Search } from 'lucide-react';
import type { NetAssetSummary, NetAssetType } from '@shared';
import type { NetworkSearchField } from '../../api/network.api';
import { useAssetSearch } from './queries';
import { markerDataUrl } from './markerImages';
import { LIFECYCLE_LABEL } from './symbology';
import s from './NetworkMap.module.css';

const FIELDS: { id: NetworkSearchField; label: string }[] = [
  { id: 'any', label: 'Code or name' },
  { id: 'code', label: 'Code' },
  { id: 'name', label: 'Name' },
];

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

interface Props {
  typeLabel: (type: NetAssetType) => string;
  onChoose:  (asset: NetAssetSummary) => void;
}

export function MapSearch({ typeLabel, onChoose }: Props) {
  const [q, setQ] = useState('');
  const [field, setField] = useState<NetworkSearchField>('any');
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();
  const term = useDebounced(q, 200);
  const { data, isFetching, isError } = useAssetSearch(term, field);
  const results = term.trim().length >= 2 ? data ?? [] : [];
  const showList = open && q.trim().length >= 2;

  const choose = (a: NetAssetSummary) => {
    onChoose(a);
    setQ(a.asset_code);
    setOpen(false);
  };

  const onKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setActive(i => Math.min(i + 1, Math.max(results.length - 1, 0))); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setActive(i => Math.max(i - 1, 0)); }
    else if (e.key === 'Enter' && results[active]) { e.preventDefault(); choose(results[active]); }
    else if (e.key === 'Escape') { setQ(''); setOpen(false); }
  };

  return (
    <div className={s.search}>
      <div className={s.searchBar}>
        <label className={s.srOnly} htmlFor={`${listId}-field`}>Search by</label>
        <select
          id={`${listId}-field`}
          className={s.searchField}
          value={field}
          onChange={e => { setField(e.target.value as NetworkSearchField); setActive(0); }}
        >
          {FIELDS.map(f => <option key={f.id} value={f.id}>{f.label}</option>)}
        </select>
        <div className={s.searchInputWrap}>
          <Search size={16} className={s.searchIcon} aria-hidden />
          <input
            className={s.searchInput}
            type="search"
            role="combobox"
            aria-label="Find an asset"
            aria-expanded={showList}
            aria-controls={listId}
            aria-autocomplete="list"
            aria-activedescendant={showList && results[active] ? `${listId}-${active}` : undefined}
            placeholder="Find an asset, e.g. FAT-0014"
            value={q}
            onChange={e => { setQ(e.target.value); setOpen(true); setActive(0); }}
            onFocus={() => setOpen(true)}
            onBlur={() => window.setTimeout(() => setOpen(false), 120)}
            onKeyDown={onKeyDown}
            autoComplete="off"
          />
        </div>
      </div>

      {showList && (
        <ul id={listId} role="listbox" aria-label="Matching assets" className={s.results}>
          {results.map((a, i) => (
            <li
              key={a.id}
              id={`${listId}-${i}`}
              role="option"
              aria-selected={i === active}
              className={s.result}
              onMouseDown={e => { e.preventDefault(); choose(a); }}
              onMouseEnter={() => setActive(i)}
            >
              <img src={markerDataUrl(a.asset_type)} alt="" width={28} height={28} />
              <span style={{ minWidth: 0 }}>
                <span className={s.resultCode}>{a.asset_code}</span>
                <span className={s.resultMeta}>
                  {typeLabel(a.asset_type)}{a.name && a.name !== a.asset_code ? `, ${a.name}` : ''}
                </span>
              </span>
              <span className={s.resultMeta}>{LIFECYCLE_LABEL[a.lifecycle_status]}</span>
            </li>
          ))}
          {!results.length && (
            <li className={s.resultNote} role="presentation">
              {isError ? 'Search is unavailable right now. Try again in a moment.'
                : isFetching ? 'Searching…'
                : `No asset in service matches "${term.trim()}". Check the code, or search by name instead.`}
            </li>
          )}
        </ul>
      )}
    </div>
  );
}
