// ============================================================
// OPSYN REGISTER PAGE — src/pages/auth/RegisterPage.tsx
// Self-service tenant registration: org details + admin account
// ============================================================

import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { authApi } from '../../api/index';
import OpsynMark from '../../components/brand/OpsynMark';

type Step = 1 | 2;

interface FormState {
  org_name:   string;
  slug:       string;
  first_name: string;
  last_name:  string;
  email:      string;
  password:   string;
  confirm:    string;
}

function slugify(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 80);
}

export default function RegisterPage() {
  const navigate = useNavigate();
  const [step, setStep]       = useState<Step>(1);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState('');

  const [form, setForm] = useState<FormState>({
    org_name: '', slug: '', first_name: '', last_name: '',
    email: '', password: '', confirm: '',
  });

  const set = (field: keyof FormState) => (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setForm(prev => {
      const next = { ...prev, [field]: value };
      if (field === 'org_name' && !prev.slug) {
        next.slug = slugify(value);
      }
      return next;
    });
  };

  const validateStep1 = () => {
    if (!form.org_name.trim()) return 'Organisation name is required.';
    if (!form.slug.trim())     return 'Subdomain is required.';
    if (!/^[a-z0-9][a-z0-9-]{2,79}$/.test(form.slug)) return 'Subdomain: 3-80 lowercase letters, numbers, hyphens.';
    return '';
  };

  const validateStep2 = () => {
    if (!form.first_name.trim()) return 'First name is required.';
    if (!form.last_name.trim())  return 'Last name is required.';
    if (!form.email.trim())      return 'Email is required.';
    if (!/\S+@\S+\.\S+/.test(form.email)) return 'Invalid email address.';
    if (form.password.length < 8)   return 'Password must be at least 8 characters.';
    if (form.password !== form.confirm) return 'Passwords do not match.';
    return '';
  };

  const handleNext = (e: React.FormEvent) => {
    e.preventDefault();
    const err = validateStep1();
    if (err) { setError(err); return; }
    setError('');
    setStep(2);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const err = validateStep2();
    if (err) { setError(err); return; }
    setError('');
    setLoading(true);
    try {
      await authApi.registerTenant({
        org_name:   form.org_name,
        slug:       form.slug,
        first_name: form.first_name,
        last_name:  form.last_name,
        email:      form.email,
        password:   form.password,
      });
      navigate('/setup', { replace: true });
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || 'Registration failed.';
      setError(detail);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg1)', padding: '24px',
    }}>
      <div style={{ width: '100%', maxWidth: 460 }}>
        {/* Logo */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <OpsynMark size={40} />
          <p style={{ color: 'var(--text2)', marginTop: 8, fontSize: 14 }}>
            Create your Opsyn workspace
          </p>
        </div>

        {/* Step indicator */}
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 28, gap: 8 }}>
          {([1, 2] as Step[]).map(s => (
            <div key={s} style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{
                width: 28, height: 28, borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 12, fontWeight: 600,
                background: step >= s ? 'var(--accent)' : 'var(--bg3)',
                color: step >= s ? '#fff' : 'var(--text2)',
                flexShrink: 0,
              }}>{s}</div>
              <span style={{ fontSize: 12, color: step >= s ? 'var(--text1)' : 'var(--text3)' }}>
                {s === 1 ? 'Organisation' : 'Admin Account'}
              </span>
              {s < 2 && <div style={{ flex: 1, height: 1, background: 'var(--border)' }} />}
            </div>
          ))}
        </div>

        {/* Card */}
        <div style={{
          background: 'var(--bg2)', border: '1px solid var(--border)',
          borderRadius: 12, padding: 32,
        }}>
          {error && (
            <div style={{
              background: '#fee2e2', border: '1px solid #fca5a5', borderRadius: 8,
              padding: '10px 14px', marginBottom: 20, color: '#b91c1c', fontSize: 13,
            }}>
              {error}
            </div>
          )}

          {/* ── Step 1: Organisation ─── */}
          {step === 1 && (
            <form onSubmit={handleNext}>
              <h2 style={{ margin: '0 0 20px', fontSize: 18, color: 'var(--text1)', fontWeight: 600 }}>
                About your organisation
              </h2>

              <label style={labelStyle}>Organisation Name</label>
              <input
                style={inputStyle}
                placeholder="Acme Telecom Ltd"
                value={form.org_name}
                onChange={set('org_name')}
                autoFocus
                required
              />

              <label style={labelStyle}>
                Subdomain
                <span style={{ color: 'var(--text3)', fontWeight: 400, marginLeft: 8 }}>
                  (used as your unique workspace ID)
                </span>
              </label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 0 }}>
                <input
                  style={{ ...inputStyle, borderRadius: '8px 0 0 8px', borderRight: 'none', flex: 1 }}
                  placeholder="acme-telecom"
                  value={form.slug}
                  onChange={set('slug')}
                  required
                />
                <span style={{
                  background: 'var(--bg3)', border: '1px solid var(--border)',
                  borderRadius: '0 8px 8px 0', padding: '9px 12px',
                  fontSize: 13, color: 'var(--text3)', whiteSpace: 'nowrap',
                }}>
                  .opsyn.io
                </span>
              </div>

              <button type="submit" style={btnStyle}>
                Continue →
              </button>
            </form>
          )}

          {/* ── Step 2: Admin account ─── */}
          {step === 2 && (
            <form onSubmit={handleSubmit}>
              <h2 style={{ margin: '0 0 20px', fontSize: 18, color: 'var(--text1)', fontWeight: 600 }}>
                Your admin account
              </h2>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <label style={labelStyle}>First Name</label>
                  <input style={inputStyle} placeholder="Jane" value={form.first_name} onChange={set('first_name')} required />
                </div>
                <div>
                  <label style={labelStyle}>Last Name</label>
                  <input style={inputStyle} placeholder="Smith" value={form.last_name} onChange={set('last_name')} required />
                </div>
              </div>

              <label style={labelStyle}>Work Email</label>
              <input
                style={inputStyle} type="email" placeholder="jane@acmetelecom.com"
                value={form.email} onChange={set('email')} required
              />

              <label style={labelStyle}>Password</label>
              <input
                style={inputStyle} type="password" placeholder="Min. 8 characters"
                value={form.password} onChange={set('password')} required
              />

              <label style={labelStyle}>Confirm Password</label>
              <input
                style={inputStyle} type="password" placeholder="Repeat password"
                value={form.confirm} onChange={set('confirm')} required
              />

              <div style={{ display: 'flex', gap: 10, marginTop: 24 }}>
                <button
                  type="button"
                  onClick={() => { setError(''); setStep(1); }}
                  style={{ ...btnStyle, background: 'var(--bg3)', color: 'var(--text1)', flex: '0 0 auto', padding: '10px 20px' }}
                >
                  ← Back
                </button>
                <button type="submit" style={{ ...btnStyle, flex: 1 }} disabled={loading}>
                  {loading ? 'Creating workspace…' : 'Create Workspace'}
                </button>
              </div>
            </form>
          )}
        </div>

        <p style={{ textAlign: 'center', marginTop: 20, fontSize: 13, color: 'var(--text3)' }}>
          Already have an account?{' '}
          <Link to="/login" style={{ color: 'var(--accent-text)', textDecoration: 'none' }}>
            Sign in
          </Link>
        </p>
      </div>
    </div>
  );
}

const labelStyle: React.CSSProperties = {
  display: 'block', fontSize: 12, fontWeight: 500,
  color: 'var(--text2)', marginBottom: 5, marginTop: 14,
};

const inputStyle: React.CSSProperties = {
  width: '100%', padding: '9px 12px', borderRadius: 8,
  border: '1px solid var(--border)', background: 'var(--bg3)',
  color: 'var(--text1)', fontSize: 14, boxSizing: 'border-box',
  outline: 'none',
};

const btnStyle: React.CSSProperties = {
  width: '100%', padding: '11px 16px',
  background: 'var(--accent)', color: 'var(--brand-contrast)',
  border: 'none', borderRadius: 8, fontSize: 14, fontWeight: 600,
  cursor: 'pointer', marginTop: 24,
};
