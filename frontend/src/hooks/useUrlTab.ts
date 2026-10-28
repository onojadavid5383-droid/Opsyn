// ============================================================
// OPSYN — useUrlTab / useUrlParam
// A page tab that lives in the URL (?tab=…), so navigation, the command
// palette and bookmarks can open a page on a specific tab. Unknown or missing
// values fall back to the default. Switching tabs replaces the history entry
// rather than pushing one — Back leaves the page, it doesn't step through tabs.
// ============================================================

import { useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';

/** Any single-valued URL parameter restricted to known values (filters, views). */
export function useUrlParam<T extends string>(key: string, allowed: readonly T[], fallback: T): [T, (value: T) => void] {
  const [params, setParams] = useSearchParams();
  const raw = params.get(key);
  const value = raw !== null && (allowed as readonly string[]).includes(raw) ? (raw as T) : fallback;

  const setValue = useCallback((next: T) => {
    setParams(prev => {
      const updated = new URLSearchParams(prev);
      if (next === fallback) updated.delete(key);
      else updated.set(key, next);
      return updated;
    }, { replace: true });
  }, [setParams, key, fallback]);

  return [value, setValue];
}

export function useUrlTab<T extends string>(allowed: readonly T[], fallback: T): [T, (tab: T) => void] {
  return useUrlParam('tab', allowed, fallback);
}
