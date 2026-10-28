// ============================================================
// OPSYN ACTIVATE PAGE — src/pages/auth/ActivatePage.tsx
// Redeems a one-time invite token and sets account password.
// Public route: /activate?token=<JWT>
// ============================================================

import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useAuthStore } from '../../store/auth.store';
import { authApi } from '../../api/index';
import OpsynMark from '../../components/brand/OpsynMark';
import { PoweredBy } from '../../components/brand/OpsynMark';

export default function ActivatePage() {
  const navigate      = useNavigate();
  const setUser       = useAuthStore(s => s.setUser);
  const [params]      = useSearchParams();
  const token         = params.get('token') ?? '';

  const [password,   setPassword]  = useState('');
  const [confirm,    setConfirm]   = useState('');
  const [loading,    setLoading]   = useState(false);
  const [error,      setError]     = useState('');
  // Derived, not state: it is a function of `token` and nothing else.
  const tokenError = !token;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }

    setLoading(true);
    try {
      const resp = await authApi.activate(token, password) as any;
      const { access_token } = resp.data;

      const [, payloadB64] = access_token.split('.');
      const claims = JSON.parse(atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/')));

      setUser({
        id:        claims.sub,
        username:  claims.username || '',
        email:     resp.data.user?.email || '',
        role:      { id: '', name: claims.role || 'Staff', level: claims.role_level || 1, is_system_role: false },
        role_level: claims.role_level || 1,
        is_active: true,
      }, access_token);

      navigate('/dashboard', { replace: true });
    } catch (err: any) {
      setError(
        err?.response?.data?.detail ||
        err?.detail ||
        err?.message ||
        'Activation failed. The link may have expired.',
      );
    } finally {
      setLoading(false);
    }
  };

  const inputStyle: React.CSSProperties = {
    width: '100%', background: 'var(--bg3)', border: '1px solid var(--wire2)',
    borderRadius: 8, padding: '9px 12px', color: 'var(--chalk)',
    fontFamily: 'var(--font)', fontSize: 13, outline: 'none',
  };
  const labelStyle: React.CSSProperties = {
    display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--chalk3)',
    marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.1em',
  };

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg)', fontFamily: 'var(--font)', position: 'relative',
    }}>
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        backgroundImage: 'linear-gradient(rgba(6,182,212,.018) 1px, transparent 1px), linear-gradient(90deg, rgba(6,182,212,.018) 1px, transparent 1px)',
        backgroundSize: '40px 40px',
      }} />

      <div style={{ width: '100%', maxWidth: 420, padding: '0 20px', position: 'relative', zIndex: 1 }}>
        <div style={{ textAlign: 'center', marginBottom: 36 }}>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 14 }}>
            <OpsynMark size={56} />
          </div>
          <div style={{
            fontWeight: 800, fontSize: 28, letterSpacing: '-.03em',
            background: 'var(--brand)',
            WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', backgroundClip: 'text',
          }}>Opsyn</div>
          <div style={{ fontSize: 13, color: 'var(--chalk3)', marginTop: 4 }}>
            Activate Your Account
          </div>
          <div style={{ marginTop: 8, display: 'flex', justifyContent: 'center' }}>
            <PoweredBy />
          </div>
        </div>

        <div style={{
          background: 'var(--bg2)', border: '1px solid var(--wire2)',
          borderRadius: 16, padding: 28, position: 'relative', overflow: 'hidden',
          boxShadow: '0 8px 40px rgba(0,0,0,.6)',
        }}>
          <div style={{
            position: 'absolute', top: 0, left: 0, right: 0, height: 1,
            background: 'linear-gradient(90deg,transparent,rgba(74,222,128,.5),transparent)',
          }} />

          {tokenError ? (
            <div style={{ textAlign: 'center', padding: '20px 0' }}>
              <div style={{ fontSize: 28, marginBottom: 12 }}>⚠️</div>
              <div style={{ fontWeight: 700, color: 'var(--rose)', fontSize: 14, marginBottom: 8 }}>
                Invalid Activation Link
              </div>
              <div style={{ fontSize: 12, color: 'var(--chalk3)', lineHeight: 1.6 }}>
                This link is missing a token. Please use the exact link from your invite email.
              </div>
              <button
                onClick={() => navigate('/login')}
                style={{
                  marginTop: 20, padding: '8px 20px', borderRadius: 8, border: 'none',
                  background: 'var(--bg4)', color: 'var(--chalk2)', cursor: 'pointer',
                  fontFamily: 'var(--font)', fontSize: 12,
                }}>
                Go to Login
              </button>
            </div>
          ) : (
            <>
              <h2 style={{ fontSize: 16, fontWeight: 700, color: 'var(--chalk)', letterSpacing: '-.02em', marginBottom: 8 }}>
                Set Your Password
              </h2>
              <p style={{ fontSize: 12, color: 'var(--chalk3)', marginBottom: 24, lineHeight: 1.5 }}>
                Your account has been provisioned by your administrator. Set a password to complete activation.
              </p>

              {error && (
                <div style={{
                  background: 'rgba(248,113,113,.08)', border: '1px solid rgba(248,113,113,.2)',
                  borderRadius: 8, padding: '10px 12px', marginBottom: 16,
                  fontSize: 12, color: 'var(--rose)',
                }}>{error}</div>
              )}

              <form onSubmit={handleSubmit}>
                <div style={{ marginBottom: 14 }}>
                  <label htmlFor="new-password" style={labelStyle}>New Password</label>
                  <input
                    id="new-password" name="new-password"
                    type="password" required autoFocus
                    value={password} onChange={e => setPassword(e.target.value)}
                    placeholder="Minimum 8 characters"
                    style={inputStyle}
                  />
                </div>
                <div style={{ marginBottom: 20 }}>
                  <label htmlFor="confirm-password" style={labelStyle}>Confirm Password</label>
                  <input
                    id="confirm-password" name="confirm-password"
                    type="password" required
                    value={confirm} onChange={e => setConfirm(e.target.value)}
                    placeholder="Repeat your password"
                    style={{
                      ...inputStyle,
                      borderColor: confirm && confirm !== password ? 'rgba(248,113,113,.5)' : undefined,
                    }}
                  />
                  {confirm && confirm !== password && (
                    <div style={{ fontSize: 11, color: 'var(--rose)', marginTop: 4 }}>Passwords do not match</div>
                  )}
                </div>

                <button type="submit" disabled={loading || !password || !confirm}
                  style={{
                    width: '100%', padding: '10px', borderRadius: 8, border: 'none',
                    background: (loading || !password || !confirm) ? 'var(--bg4)' : 'var(--brand)',
                    color: (loading || !password || !confirm) ? 'var(--chalk3)' : '#050810',
                    fontSize: 13, fontWeight: 700,
                    cursor: (loading || !password || !confirm) ? 'not-allowed' : 'pointer',
                    fontFamily: 'var(--font)', letterSpacing: '.01em',
                    boxShadow: (loading || !password || !confirm) ? 'none' : '0 0 20px rgba(74,222,128,.3)',
                    transition: 'all .2s',
                  }}>
                  {loading ? 'Activating…' : 'Activate Account'}
                </button>
              </form>
            </>
          )}
        </div>

        <div style={{ textAlign: 'center', marginTop: 20, fontSize: 11, color: 'var(--chalk3)' }}>
          Opsyn v2.0 · Operational Intelligence Platform
        </div>
      </div>
    </div>
  );
}
