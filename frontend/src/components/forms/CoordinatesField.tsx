// ============================================================
// OPSYN COORDINATES FIELD — 3 input modes
// Mode 1: Manual  — separate Lat / Lng inputs
// Mode 2: GPS     — browser geolocation auto-fill
// Mode 3: Paste   — "lat, lng" single-line parse
// ============================================================

import { useState } from 'react';

interface CoordValue {
  lat: string;
  lng: string;
}

interface Props {
  value:    CoordValue | null;
  onChange: (v: CoordValue) => void;
  disabled?: boolean;
}

type Mode = 'manual' | 'gps' | 'paste';

const INPUT_STYLE: React.CSSProperties = {
  width: '100%', background: 'var(--bg3)', border: '1px solid var(--wire2)',
  borderRadius: 8, padding: '8px 10px', color: 'var(--chalk)',
  fontFamily: 'var(--mono)', fontSize: 12, outline: 'none',
};

const TAB_STYLE = (active: boolean): React.CSSProperties => ({
  padding: '4px 10px', borderRadius: 6, fontSize: 10, fontWeight: 600,
  cursor: 'pointer', border: 'none', fontFamily: 'var(--font)',
  background: active ? 'rgba(6,182,212,.15)' : 'transparent',
  color: active ? 'var(--cyan)' : 'var(--chalk3)',
  boxShadow: active ? 'inset 0 0 0 1px rgba(6,182,212,.3)' : 'none',
  transition: 'all .12s',
});

export default function CoordinatesField({ value, onChange, disabled }: Props) {
  const [mode, setMode] = useState<Mode>('manual');
  const [paste, setPaste] = useState('');
  const [gpsState, setGpsState] = useState<'idle' | 'loading' | 'error'>('idle');
  const [pasteErr, setPasteErr] = useState('');

  const lat = value?.lat ?? '';
  const lng = value?.lng ?? '';

  // ── Mode: GPS ─────────────────────────────────────────────
  const handleGps = () => {
    if (!navigator.geolocation) {
      setGpsState('error');
      return;
    }
    setGpsState('loading');
    navigator.geolocation.getCurrentPosition(
      pos => {
        onChange({
          lat: pos.coords.latitude.toFixed(6),
          lng: pos.coords.longitude.toFixed(6),
        });
        setGpsState('idle');
        setMode('manual');
      },
      () => setGpsState('error'),
      { timeout: 10_000 },
    );
  };

  // ── Mode: Paste ────────────────────────────────────────────
  const handleParse = () => {
    setPasteErr('');
    const cleaned = paste.trim().replace(/[()]/g, '');
    // Accept: "6.5244, 3.3792" or "6.5244 3.3792" or "6.5244,3.3792"
    const parts = cleaned.split(/[\s,]+/).filter(Boolean);
    if (parts.length < 2) {
      setPasteErr('Enter coordinates as "lat, lng" (e.g. 6.5244, 3.3792)');
      return;
    }
    const [latStr, lngStr] = parts;
    const latNum = parseFloat(latStr);
    const lngNum = parseFloat(lngStr);
    if (isNaN(latNum) || isNaN(lngNum)) {
      setPasteErr('Could not parse coordinates — check the format.');
      return;
    }
    if (latNum < -90 || latNum > 90)  { setPasteErr('Latitude must be between -90 and 90.'); return; }
    if (lngNum < -180 || lngNum > 180){ setPasteErr('Longitude must be between -180 and 180.'); return; }
    onChange({ lat: latNum.toFixed(6), lng: lngNum.toFixed(6) });
    setMode('manual');
    setPaste('');
  };

  return (
    <div>
      {/* Mode tabs */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 10 }}>
        {(['manual', 'gps', 'paste'] as Mode[]).map(m => (
          <button key={m} style={TAB_STYLE(mode === m)} onClick={() => setMode(m)} type="button" disabled={disabled}>
            {m === 'manual' ? 'Manual' : m === 'gps' ? 'GPS' : 'Paste'}
          </button>
        ))}
      </div>

      {/* Mode: Manual */}
      {mode === 'manual' && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
          <div>
            <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--chalk3)', marginBottom: 4, letterSpacing: '.08em', textTransform: 'uppercase' }}>Latitude</div>
            <input
              type="text" value={lat} placeholder="-90 to 90"
              disabled={disabled}
              onChange={e => onChange({ lat: e.target.value, lng })}
              style={INPUT_STYLE}
            />
          </div>
          <div>
            <div style={{ fontSize: 9, fontWeight: 700, color: 'var(--chalk3)', marginBottom: 4, letterSpacing: '.08em', textTransform: 'uppercase' }}>Longitude</div>
            <input
              type="text" value={lng} placeholder="-180 to 180"
              disabled={disabled}
              onChange={e => onChange({ lat, lng: e.target.value })}
              style={INPUT_STYLE}
            />
          </div>
        </div>
      )}

      {/* Mode: GPS */}
      {mode === 'gps' && (
        <div>
          <button
            type="button" onClick={handleGps}
            disabled={disabled || gpsState === 'loading'}
            style={{
              padding: '8px 16px', borderRadius: 8, border: 'none', cursor: 'pointer',
              background: 'rgba(6,182,212,.15)', color: 'var(--cyan)',
              fontFamily: 'var(--font)', fontSize: 12, fontWeight: 600,
              boxShadow: 'inset 0 0 0 1px rgba(6,182,212,.3)',
            }}>
            {gpsState === 'loading' ? 'Detecting…' : 'Use Current Location'}
          </button>
          {gpsState === 'error' && (
            <div style={{ marginTop: 6, fontSize: 11, color: 'var(--rose)' }}>
              Could not access location. Check browser permissions.
            </div>
          )}
          {lat && lng && (
            <div style={{ marginTop: 8, fontSize: 11, color: 'var(--chalk3)', fontFamily: 'var(--mono)' }}>
              Detected: {lat}, {lng}
            </div>
          )}
        </div>
      )}

      {/* Mode: Paste */}
      {mode === 'paste' && (
        <div>
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              type="text" value={paste} placeholder="e.g. 6.5244, 3.3792"
              disabled={disabled}
              onChange={e => { setPaste(e.target.value); setPasteErr(''); }}
              onKeyDown={e => e.key === 'Enter' && handleParse()}
              style={{ ...INPUT_STYLE, flex: 1 }}
            />
            <button
              type="button" onClick={handleParse} disabled={disabled || !paste.trim()}
              style={{
                padding: '8px 14px', borderRadius: 8, border: 'none',
                background: 'rgba(6,182,212,.15)', color: 'var(--cyan)',
                fontFamily: 'var(--font)', fontSize: 12, fontWeight: 600,
                cursor: 'pointer', flexShrink: 0,
              }}>
              Parse
            </button>
          </div>
          {pasteErr && (
            <div style={{ marginTop: 6, fontSize: 11, color: 'var(--rose)' }}>{pasteErr}</div>
          )}
        </div>
      )}

      {/* Resolved preview */}
      {lat && lng && mode !== 'manual' && (
        <div style={{ marginTop: 8, fontSize: 10, color: 'var(--chalk3)', fontFamily: 'var(--mono)' }}>
          ↳ {lat}, {lng}
        </div>
      )}
    </div>
  );
}
