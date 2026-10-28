// ============================================================
// OPSYN LOGIN PAGE — src/pages/auth/LoginPage.tsx
// Email + password, JWT store, redirect to dashboard
// ============================================================

import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuthStore } from '../../store/auth.store';
import { authApi } from '../../api/index';
import OpsynMark from '../../components/brand/OpsynMark';
import { PoweredBy } from '../../components/brand/OpsynMark';

export default function LoginPage() {
  const navigate   = useNavigate();
  const setUser    = useAuthStore(s => s.setUser);
  const [email,    setEmail]    = useState('');
  const [password, setPassword] = useState('');
  const [loading,  setLoading]  = useState(false);
  const [error,    setError]    = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const data = await authApi.login(email, password);
      // authApi.login returns TokenResponse; fetch user from /staff/me
      // For now store minimal user from token claims
      const { access_token } = data as any;

      // Decode minimal claims from JWT (not sensitive — just for UI)
      const [, payloadB64] = access_token.split('.');
      const claims = JSON.parse(atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/')));

      setUser({
        id:        claims.sub,
        username:  claims.username || email.split('@')[0],
        email,
        role:      { id: '', name: claims.role || 'Staff', level: claims.role_level || 1, is_system_role: false },
        role_level: claims.role_level || 1,
        is_active: true,
      }, access_token);

      navigate('/dashboard', { replace: true });
    } catch (err: any) {
      setError(err?.detail || err?.message || 'Login failed. Check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'var(--bg)', fontFamily: 'var(--font)', position: 'relative',
    }}>
      {/* Grid texture */}
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        backgroundImage: 'linear-gradient(rgba(6,182,212,.018) 1px, transparent 1px), linear-gradient(90deg, rgba(6,182,212,.018) 1px, transparent 1px)',
        backgroundSize: '40px 40px',
      }} />

      <div style={{
        width: '100%', maxWidth: 420, padding: '0 20px',
        position: 'relative', zIndex: 1,
      }}>
        {/* Logo & brand */}
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
            Operational Intelligence Platform
          </div>
          <div style={{ marginTop: 8, display: 'flex', justifyContent: 'center' }}>
            <PoweredBy />
          </div>
        </div>

        {/* Card */}
        <div style={{
          background: 'var(--bg2)', border: '1px solid var(--wire2)',
          borderRadius: 16, padding: 28, position: 'relative', overflow: 'hidden',
          boxShadow: '0 8px 40px rgba(0,0,0,.6)',
        }}>
          {/* Top glow line */}
          <div style={{
            position: 'absolute', top: 0, left: 0, right: 0, height: 1,
            background: 'linear-gradient(90deg,transparent,rgba(6,182,212,.5),transparent)',
          }} />

          <h2 style={{ fontSize: 16, fontWeight: 700, color: 'var(--chalk)',
                       letterSpacing: '-.02em', marginBottom: 24 }}>
            Sign in to Opsyn
          </h2>

          {error && (
            <div style={{
              background: 'rgba(248,113,113,.08)', border: '1px solid rgba(248,113,113,.2)',
              borderRadius: 8, padding: '10px 12px', marginBottom: 16,
              fontSize: 12, color: 'var(--rose)',
            }}>{error}</div>
          )}

          <form onSubmit={handleSubmit}>
            <div style={{ marginBottom: 14 }}>
              <label htmlFor="email" style={{ display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--chalk3)',
                              marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.1em' }}>
                Email Address
              </label>
              <input
                id="email" name="email"
                type="email" required autoFocus
                value={email} onChange={e => setEmail(e.target.value)}
                placeholder="your.name@opsyn.ng"
                style={{
                  width: '100%', background: 'var(--bg3)', border: '1px solid var(--wire2)',
                  borderRadius: 8, padding: '9px 12px', color: 'var(--chalk)',
                  fontFamily: 'var(--font)', fontSize: 13, outline: 'none',
                }}
              />
            </div>
            <div style={{ marginBottom: 20 }}>
              <label htmlFor="password" style={{ display: 'block', fontSize: 9, fontWeight: 700, color: 'var(--chalk3)',
                              marginBottom: 5, textTransform: 'uppercase', letterSpacing: '.1em' }}>
                Password
              </label>
              <input
                id="password" name="password"
                type="password" required
                value={password} onChange={e => setPassword(e.target.value)}
                placeholder="••••••••"
                style={{
                  width: '100%', background: 'var(--bg3)', border: '1px solid var(--wire2)',
                  borderRadius: 8, padding: '9px 12px', color: 'var(--chalk)',
                  fontFamily: 'var(--font)', fontSize: 13, outline: 'none',
                }}
              />
            </div>

            <button type="submit" disabled={loading}
                    style={{
                      width: '100%', padding: '10px', borderRadius: 8, border: 'none',
                      background: loading ? 'var(--bg4)' : 'var(--brand)',
                      color: loading ? 'var(--chalk3)' : '#050810',
                      fontSize: 13, fontWeight: 700, cursor: loading ? 'not-allowed' : 'pointer',
                      fontFamily: 'var(--font)', letterSpacing: '.01em',
                      boxShadow: loading ? 'none' : '0 0 20px rgba(6,182,212,.35)',
                      transition: 'all .2s',
                    }}>
              {loading ? 'Authenticating…' : 'Sign In to Opsyn'}
            </button>
          </form>
        </div>

        <div style={{ textAlign: 'center', marginTop: 20, fontSize: 11, color: 'var(--chalk3)' }}>
          New to Opsyn?{' '}
          <Link to="/register" style={{ color: 'var(--brand)', textDecoration: 'none', fontWeight: 600 }}>
            Create a workspace
          </Link>
        </div>
        <div style={{ textAlign: 'center', marginTop: 8, fontSize: 11, color: 'var(--chalk3)' }}>
          Opsyn v2.0 · Operational Intelligence Platform
        </div>
      </div>
    </div>
  );
}
