// ============================================================
// OPSYN FIRST-RUN WIZARD — src/pages/onboarding/FirstRunWizard.tsx
// 5-step guided setup after tenant registration
//   1. Branding & timezone
//   2. First Region + POP site
//   3. First OLT node + SmartOLT API key
//   4. Invite first staff member
//   5. Done
// ============================================================

import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useMutation } from '@tanstack/react-query';
import { infrastructureApi, settingsApi, smartoltApi, staffApi } from '../../api/index';
import OpsynMark from '../../components/brand/OpsynMark';
import { GlassSelect } from '../../components/glass';

type StepId = 1 | 2 | 3 | 4 | 5;

const STEPS: { id: StepId; label: string }[] = [
  { id: 1, label: 'Branding' },
  { id: 2, label: 'Network' },
  { id: 3, label: 'OLT' },
  { id: 4, label: 'Team' },
  { id: 5, label: 'Done' },
];

function StepIndicator({ current }: { current: StepId }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 0, marginBottom: 36 }}>
      {STEPS.map((s, i) => (
        <div key={s.id} style={{ display: 'flex', alignItems: 'center' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4 }}>
            <div style={{
              width: 32, height: 32, borderRadius: '50%',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 13, fontWeight: 700,
              background: current > s.id ? '#22c55e' : current === s.id ? 'var(--accent)' : 'var(--bg3)',
              color: current >= s.id ? '#fff' : 'var(--text3)',
              border: current === s.id ? '2px solid var(--accent)' : '2px solid transparent',
              transition: 'all 0.2s',
            }}>
              {current > s.id ? '✓' : s.id}
            </div>
            <span style={{ fontSize: 10, color: current >= s.id ? 'var(--text2)' : 'var(--text3)', whiteSpace: 'nowrap' }}>
              {s.label}
            </span>
          </div>
          {i < STEPS.length - 1 && (
            <div style={{
              width: 48, height: 2, margin: '0 4px', marginBottom: 18,
              background: current > s.id ? '#22c55e' : 'var(--border)',
              transition: 'background 0.3s',
            }} />
          )}
        </div>
      ))}
    </div>
  );
}

// ── Step 1: Branding ──────────────────────────────────────────
function Step1({ onNext }: { onNext: () => void }) {
  const [timezone, setTimezone] = useState(Intl.DateTimeFormat().resolvedOptions().timeZone);
  const [primaryColor, setPrimaryColor] = useState('#2563eb');

  return (
    <div>
      <h2 style={headStyle}>Set up your workspace</h2>
      <p style={subStyle}>Customise how Opsyn looks for your organisation.</p>

      <label style={labelStyle}>Primary Color</label>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
        <input
          type="color"
          value={primaryColor}
          onChange={e => setPrimaryColor(e.target.value)}
          style={{ width: 44, height: 44, border: 'none', borderRadius: 8, cursor: 'pointer', padding: 2, background: 'none' }}
        />
        <span style={{ fontFamily: 'monospace', fontSize: 14, color: 'var(--text2)' }}>{primaryColor}</span>
      </div>

      <label style={labelStyle}>Timezone</label>
      <GlassSelect value={String(timezone)} onChange={v => setTimezone(v)} options={[...[
          'Africa/Lagos', 'Africa/Nairobi', 'Africa/Johannesburg',
          'Europe/London', 'Europe/Paris', 'America/New_York',
          'America/Los_Angeles', 'Asia/Dubai', 'Asia/Kolkata',
          'Australia/Sydney', 'Pacific/Auckland',
        ].map((tz) => ({ value: String(tz), label: String(tz) }))]} ariaLabel="Time zone" />
      <p style={{ fontSize: 11, color: 'var(--text3)', marginTop: 4 }}>
        Detected: {Intl.DateTimeFormat().resolvedOptions().timeZone}
      </p>

      <button onClick={onNext} style={btnStyle}>Continue →</button>
    </div>
  );
}

// ── Step 2: Region + POP ──────────────────────────────────────
function Step2({ onNext, onSkip }: { onNext: (regionId: string, siteId: string) => void; onSkip: () => void }) {
  const [regionName, setRegionName] = useState('');
  const [regionCode, setRegionCode] = useState('');
  const [popName, setPopName]       = useState('');
  const [popAddress, setPopAddress] = useState('');
  const [lat, setLat]               = useState('');
  const [lng, setLng]               = useState('');
  const [error, setError]           = useState('');

  // createRegion lives on settingsApi (POST /settings/regions), not orgApi.
  const createRegion = useMutation({
    mutationFn: (p: { name: string; code: string; parent_id?: string }) =>
      settingsApi.createRegion(p),
  });
  const createSite   = useMutation({
    mutationFn: (p: Record<string, unknown>) => infrastructureApi.createSite(p),
  });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!regionName.trim() || !regionCode.trim() || !popName.trim()) {
      setError('Region name, code, and POP name are required.'); return;
    }
    setError('');
    try {
      const region = await createRegion.mutateAsync({ name: regionName, code: regionCode.toUpperCase() });
      const site = await createSite.mutateAsync({
        name: popName, site_type: 'POP', address: popAddress || undefined,
        latitude: lat ? parseFloat(lat) : undefined, longitude: lng ? parseFloat(lng) : undefined,
        region_id: region?.id, status: 'active',
      });
      onNext(region?.id || '', site?.id || '');
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to create region/POP.');
    }
  };

  const busy = createRegion.isPending || createSite.isPending;

  return (
    <form onSubmit={handleSubmit}>
      <h2 style={headStyle}>Add your first region & POP</h2>
      <p style={subStyle}>Define a network region and your first Point of Presence.</p>

      {error && <div style={errorStyle}>{error}</div>}

      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 12 }}>
        <div>
          <label style={labelStyle}>Region Name</label>
          <input style={inputStyle} placeholder="Lagos Metro" value={regionName} onChange={e => setRegionName(e.target.value)} required />
        </div>
        <div>
          <label style={labelStyle}>Code</label>
          <input style={inputStyle} placeholder="LGS" value={regionCode} onChange={e => setRegionCode(e.target.value)} maxLength={10} required />
        </div>
      </div>

      <label style={labelStyle}>POP Site Name</label>
      <input style={inputStyle} placeholder="Victoria Island POP" value={popName} onChange={e => setPopName(e.target.value)} required />

      <label style={labelStyle}>Address (optional)</label>
      <input style={inputStyle} placeholder="123 Broad Street, Lagos" value={popAddress} onChange={e => setPopAddress(e.target.value)} />

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div>
          <label style={labelStyle}>Latitude (optional)</label>
          <input style={inputStyle} type="number" step="any" placeholder="6.4550" value={lat} onChange={e => setLat(e.target.value)} />
        </div>
        <div>
          <label style={labelStyle}>Longitude (optional)</label>
          <input style={inputStyle} type="number" step="any" placeholder="3.3841" value={lng} onChange={e => setLng(e.target.value)} />
        </div>
      </div>

      <div style={{ display: 'flex', gap: 10, marginTop: 24 }}>
        <button type="button" onClick={onSkip} style={{ ...btnStyle, background: 'var(--bg3)', color: 'var(--text2)', flex: '0 0 auto', padding: '10px 20px', marginTop: 0 }}>
          Skip
        </button>
        <button type="submit" style={{ ...btnStyle, marginTop: 0, flex: 1 }} disabled={busy}>
          {busy ? 'Saving…' : 'Create & Continue →'}
        </button>
      </div>
    </form>
  );
}

// ── Step 3: OLT + SmartOLT ────────────────────────────────────
function Step3({ siteId, onNext, onSkip }: {
  regionId: string; siteId: string;
  onNext: () => void; onSkip: () => void;
}) {
  const [oltName, setOltName]   = useState('');
  const [apiKey, setApiKey]     = useState('');
  const [baseUrl, setBaseUrl]   = useState('https://app.smartolt.com');
  const [error, setError]       = useState('');

  const createNode    = useMutation({ mutationFn: (p: any) => (infrastructureApi as any).createNode(p) });
  const createSmartolt = useMutation({ mutationFn: (p: any) => smartoltApi.createConfig(p) });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!oltName.trim()) { setError('OLT name is required.'); return; }
    setError('');
    try {
      await createNode.mutateAsync({
        name: oltName, node_type: 'OLT',
        site_id: siteId || undefined,
        status: 'active',
      });
      if (apiKey.trim()) {
        await createSmartolt.mutateAsync({ base_url: baseUrl, api_key: apiKey, is_active: true });
      }
      onNext();
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Failed to create OLT.');
    }
  };

  const busy = createNode.isPending || createSmartolt.isPending;

  return (
    <form onSubmit={handleSubmit}>
      <h2 style={headStyle}>Add your first OLT</h2>
      <p style={subStyle}>Register an OLT node and optionally connect SmartOLT.</p>

      {error && <div style={errorStyle}>{error}</div>}

      <label style={labelStyle}>OLT Node Name</label>
      <input style={inputStyle} placeholder="VI-OLT-01" value={oltName} onChange={e => setOltName(e.target.value)} required />

      <div style={{ marginTop: 20, padding: '14px 16px', background: 'var(--bg3)', borderRadius: 10, border: '1px solid var(--border)' }}>
        <p style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 600, color: 'var(--text1)' }}>
          SmartOLT Integration <span style={{ fontWeight: 400, color: 'var(--text3)' }}>(optional)</span>
        </p>
        <label style={labelStyle}>SmartOLT Base URL</label>
        <input style={inputStyle} value={baseUrl} onChange={e => setBaseUrl(e.target.value)} />
        <label style={labelStyle}>API Key</label>
        <input style={inputStyle} type="password" placeholder="Leave blank to skip" value={apiKey} onChange={e => setApiKey(e.target.value)} />
      </div>

      <div style={{ display: 'flex', gap: 10, marginTop: 24 }}>
        <button type="button" onClick={onSkip} style={{ ...btnStyle, background: 'var(--bg3)', color: 'var(--text2)', flex: '0 0 auto', padding: '10px 20px', marginTop: 0 }}>
          Skip
        </button>
        <button type="submit" style={{ ...btnStyle, marginTop: 0, flex: 1 }} disabled={busy}>
          {busy ? 'Saving…' : 'Create & Continue →'}
        </button>
      </div>
    </form>
  );
}

// ── Step 4: Invite staff ──────────────────────────────────────
function Step4({ onNext, onSkip }: { onNext: () => void; onSkip: () => void }) {
  const [email, setEmail]     = useState('');
  const [roleId, setRoleId]   = useState('');
  const [error, setError]     = useState('');
  const [sent, setSent]       = useState(false);

  const invite = useMutation({ mutationFn: (p: any) => (staffApi as any).invite(p) });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!email.trim() || !/\S+@\S+\.\S+/.test(email)) { setError('Valid email is required.'); return; }
    setError('');
    try {
      await invite.mutateAsync({ email, role_id: roleId || undefined });
      setSent(true);
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Invite failed.');
    }
  };

  if (sent) {
    return (
      <div style={{ textAlign: 'center', padding: '20px 0' }}>
        <div style={{ fontSize: 48, marginBottom: 12 }}>📧</div>
        <h3 style={{ color: 'var(--text1)', marginBottom: 8 }}>Invite sent!</h3>
        <p style={{ color: 'var(--text2)', marginBottom: 24 }}>
          An activation email has been sent to <strong>{email}</strong>.
        </p>
        <button onClick={onNext} style={btnStyle}>Finish Setup →</button>
      </div>
    );
  }

  return (
    <form onSubmit={handleSubmit}>
      <h2 style={headStyle}>Invite your first team member</h2>
      <p style={subStyle}>Send an invite to a colleague — they'll set their own password.</p>

      {error && <div style={errorStyle}>{error}</div>}

      <label style={labelStyle}>Email Address</label>
      <input style={inputStyle} type="email" placeholder="colleague@company.com" value={email} onChange={e => setEmail(e.target.value)} required />

      <label style={labelStyle}>Role (optional)</label>
      <input style={inputStyle} placeholder="Leave blank for default Staff role" value={roleId} onChange={e => setRoleId(e.target.value)} />
      <p style={{ fontSize: 11, color: 'var(--text3)', marginTop: 4 }}>
        You can manage roles and permissions from the Staff settings page later.
      </p>

      <div style={{ display: 'flex', gap: 10, marginTop: 24 }}>
        <button type="button" onClick={onSkip} style={{ ...btnStyle, background: 'var(--bg3)', color: 'var(--text2)', flex: '0 0 auto', padding: '10px 20px', marginTop: 0 }}>
          Skip
        </button>
        <button type="submit" style={{ ...btnStyle, marginTop: 0, flex: 1 }} disabled={invite.isPending}>
          {invite.isPending ? 'Sending…' : 'Send Invite & Finish →'}
        </button>
      </div>
    </form>
  );
}

// ── Step 5: Done ──────────────────────────────────────────────
function Step5({ onFinish }: { onFinish: () => void }) {
  return (
    <div style={{ textAlign: 'center', padding: '12px 0 4px' }}>
      <div style={{ fontSize: 56, marginBottom: 16, lineHeight: 1 }}>🎉</div>
      <h2 style={{ ...headStyle, textAlign: 'center', marginBottom: 8 }}>
        Your workspace is ready!
      </h2>
      <p style={{ ...subStyle, textAlign: 'center', marginBottom: 28 }}>
        Everything is set up. You can always update your settings from the Admin panel.
      </p>

      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 28, textAlign: 'left',
      }}>
        {[
          { icon: '🗺️', title: 'Infrastructure Map', desc: 'View your GIS network map' },
          { icon: '📊', title: 'Reports', desc: 'Operational analytics & SLA' },
          { icon: '🔔', title: 'Outage Tracker', desc: 'Real-time incident management' },
          { icon: '👥', title: 'Staff', desc: 'Team management & schedules' },
        ].map(item => (
          <div key={item.title} style={{
            background: 'var(--bg3)', borderRadius: 10, padding: '14px 16px',
            border: '1px solid var(--border)',
          }}>
            <div style={{ fontSize: 24, marginBottom: 4 }}>{item.icon}</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text1)' }}>{item.title}</div>
            <div style={{ fontSize: 11, color: 'var(--text3)' }}>{item.desc}</div>
          </div>
        ))}
      </div>

      <button onClick={onFinish} style={btnStyle}>
        Go to Dashboard →
      </button>
    </div>
  );
}

// ── Main Wizard ───────────────────────────────────────────────
export default function FirstRunWizard() {
  const navigate = useNavigate();
  const [step, setStep]       = useState<StepId>(1);
  const [regionId, setRegionId] = useState('');
  const [siteId, setSiteId]     = useState('');

  const next = () => setStep(s => Math.min(s + 1, 5) as StepId);

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg1)', padding: '24px',
    }}>
      <div style={{ width: '100%', maxWidth: 520 }}>
        {/* Header */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <OpsynMark size={38} />
          <p style={{ color: 'var(--text2)', marginTop: 8, fontSize: 14 }}>
            Welcome to Opsyn — let's get you set up
          </p>
        </div>

        <StepIndicator current={step} />

        {/* Card */}
        <div style={{
          background: 'var(--bg2)', border: '1px solid var(--border)',
          borderRadius: 14, padding: '32px 36px',
        }}>
          {step === 1 && <Step1 onNext={next} />}
          {step === 2 && (
            <Step2
              onNext={(rId, sId) => { setRegionId(rId); setSiteId(sId); next(); }}
              onSkip={next}
            />
          )}
          {step === 3 && (
            <Step3 regionId={regionId} siteId={siteId} onNext={next} onSkip={next} />
          )}
          {step === 4 && <Step4 onNext={next} onSkip={next} />}
          {step === 5 && <Step5 onFinish={() => navigate('/dashboard', { replace: true })} />}
        </div>

        {/* Progress text */}
        {step < 5 && (
          <p style={{ textAlign: 'center', marginTop: 16, fontSize: 12, color: 'var(--text3)' }}>
            Step {step} of {STEPS.length - 1}
          </p>
        )}
      </div>
    </div>
  );
}

// ── Shared styles ─────────────────────────────────────────────
const headStyle: React.CSSProperties = {
  margin: '0 0 6px', fontSize: 20, fontWeight: 700, color: 'var(--text1)',
};
const subStyle: React.CSSProperties = {
  margin: '0 0 20px', fontSize: 13, color: 'var(--text2)',
};
const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: 12, fontWeight: 500,
  color: 'var(--text2)', marginBottom: 5, marginTop: 14,
};
const inputStyle: React.CSSProperties = {
  width: '100%', padding: '9px 12px', borderRadius: 8,
  border: '1px solid var(--border)', background: 'var(--bg3)',
  color: 'var(--text1)', fontSize: 14, boxSizing: 'border-box', outline: 'none',
};
const btnStyle: React.CSSProperties = {
  width: '100%', padding: '11px 16px', marginTop: 24,
  background: 'var(--accent)', color: 'var(--brand-contrast)',
  border: 'none', borderRadius: 8, fontSize: 14, fontWeight: 600, cursor: 'pointer',
};
const errorStyle: React.CSSProperties = {
  background: '#fee2e2', border: '1px solid #fca5a5', borderRadius: 8,
  padding: '10px 14px', marginBottom: 16, color: '#b91c1c', fontSize: 13,
};
