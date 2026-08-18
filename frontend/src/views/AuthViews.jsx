import React, { useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { 
  Truck, 
  Building2, 
  Terminal, 
  KeyRound, 
  Mail, 
  Phone, 
  Lock, 
  User, 
  ShieldCheck, 
  ArrowRight,
  Sparkles
} from 'lucide-react';

export function AuthView({ role = 'company', onNavigate }) {
  const { login, register } = useAuth();
  const [isRegister, setIsRegister] = useState(false);
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [driverId, setDriverId] = useState('');
  const [companyName, setCompanyName] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (isRegister) {
      register(role, { name, email, phone, driverId, companyName });
    } else {
      login(role, { email, phone, driverId });
    }

    if (role === 'courier') onNavigate('/courier/dashboard');
    else if (role === 'company') onNavigate('/company/dashboard');
    else if (role === 'admin') onNavigate('/admin/dashboard');
  };

  const handleDemoLogin = () => {
    login(role);
    if (role === 'courier') onNavigate('/courier/dashboard');
    else if (role === 'company') onNavigate('/company/dashboard');
    else if (role === 'admin') onNavigate('/admin/dashboard');
  };

  return (
    <div style={{
      minHeight: 'calc(100vh - 70px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '40px 20px',
      backgroundColor: 'var(--bg-page)'
    }}>
      <div className="card" style={{
        maxWidth: 440,
        width: '100%',
        padding: '36px 32px',
        boxShadow: 'var(--shadow-lg)',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--border-light)',
        animation: 'fadeIn 0.25s ease'
      }}>
        {/* Role Icon Header */}
        <div style={{ textAlign: 'center', marginBottom: 24 }}>
          <div style={{
            width: 52,
            height: 52,
            borderRadius: 12,
            backgroundColor: 'var(--primary)',
            color: 'var(--accent)',
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            marginBottom: 14,
            boxShadow: '0 4px 12px rgba(30, 58, 43, 0.25)'
          }}>
            {role === 'courier' && <Truck size={26} />}
            {role === 'company' && <Building2 size={26} />}
            {role === 'admin' && <Terminal size={26} />}
          </div>

          <h2 style={{ fontSize: 22, fontWeight: 800, color: 'var(--text-main)', letterSpacing: '-0.02em' }}>
            {role === 'courier' && (isRegister ? 'Join as Delivery Partner' : 'Welcome back, Partner')}
            {role === 'company' && (isRegister ? 'Create Company Account' : 'Company Operations Portal')}
            {role === 'admin' && 'System Control / Root Access'}
          </h2>

          <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>
            {role === 'courier' && 'Sign in to access your live route, handovers, and protected trip earnings.'}
            {role === 'company' && 'Monitor active fleet telemetry, SLA rates, and autonomous AI resolutions.'}
            {role === 'admin' && 'Authorise access to system diagnostics, pipeline graph, and watchdog parameters.'}
          </p>
        </div>

        {/* Demo One-Click Access Button */}
        <div style={{
          backgroundColor: 'var(--bg-subtle)',
          padding: 12,
          borderRadius: 'var(--radius-md)',
          border: '1px solid #D1E2D8',
          marginBottom: 20,
          textAlign: 'center'
        }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--primary)', marginBottom: 6 }}>
            QUICK REVIEWER ACCESS (1-CLICK)
          </div>
          <button
            type="button"
            onClick={handleDemoLogin}
            className="btn-primary"
            style={{ width: '100%', padding: '9px 14px', fontSize: 12, backgroundColor: 'var(--accent-dark)' }}
          >
            <Sparkles size={14} />
            {role === 'courier' && 'Sign In as Suresh Kumar (Courier)'}
            {role === 'company' && 'Sign In as Operations Desk'}
            {role === 'admin' && 'Sign In as Root Administrator'}
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 20 }}>
          <div style={{ flex: 1, height: 1, backgroundColor: 'var(--border-light)' }} />
          <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600 }}>OR SIGN IN WITH CREDENTIALS</span>
          <div style={{ flex: 1, height: 1, backgroundColor: 'var(--border-light)' }} />
        </div>

        {/* Credentials Form */}
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          {isRegister && (
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-main)', marginBottom: 4 }}>
                Full Name
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  type="text"
                  required
                  placeholder="e.g. Suresh Kumar"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 12px 10px 36px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-light)',
                    fontSize: 13,
                    fontFamily: 'inherit'
                  }}
                />
                <User size={15} color="var(--text-muted)" style={{ position: 'absolute', left: 12, top: 12 }} />
              </div>
            </div>
          )}

          {role === 'courier' ? (
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-main)', marginBottom: 4 }}>
                Mobile Number or Driver ID
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  type="text"
                  required
                  placeholder="+91 98765 43210 or DRV-BLR-04"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 12px 10px 36px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-light)',
                    fontSize: 13,
                    fontFamily: 'inherit'
                  }}
                />
                <Phone size={15} color="var(--text-muted)" style={{ position: 'absolute', left: 12, top: 12 }} />
              </div>
            </div>
          ) : (
            <div>
              <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-main)', marginBottom: 4 }}>
                {role === 'admin' ? 'Master Admin Key / Email' : 'Corporate Email Address'}
              </label>
              <div style={{ position: 'relative' }}>
                <input
                  type="email"
                  required
                  placeholder={role === 'admin' ? 'admin@autofleet.ai' : 'ops@delhivery.com'}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '10px 12px 10px 36px',
                    borderRadius: 'var(--radius-sm)',
                    border: '1px solid var(--border-light)',
                    fontSize: 13,
                    fontFamily: 'inherit'
                  }}
                />
                <Mail size={15} color="var(--text-muted)" style={{ position: 'absolute', left: 12, top: 12 }} />
              </div>
            </div>
          )}

          <div>
            <label style={{ display: 'block', fontSize: 12, fontWeight: 600, color: 'var(--text-main)', marginBottom: 4 }}>
              {role === 'courier' ? 'Driver PIN / OTP' : 'Password'}
            </label>
            <div style={{ position: 'relative' }}>
              <input
                type="password"
                required
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                style={{
                  width: '100%',
                  padding: '10px 12px 10px 36px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border-light)',
                  fontSize: 13,
                  fontFamily: 'inherit'
                }}
              />
              <Lock size={15} color="var(--text-muted)" style={{ position: 'absolute', left: 12, top: 12 }} />
            </div>
          </div>

          <button
            type="submit"
            className="btn-primary"
            style={{ width: '100%', padding: '12px', fontSize: 14, marginTop: 6 }}
          >
            {role === 'courier' && (isRegister ? 'Register & Go Online' : 'SIGN IN / GO ONLINE')}
            {role === 'company' && (isRegister ? 'Complete Enterprise Registration' : 'Sign In to Operations Desk')}
            {role === 'admin' && 'Authorise Access'}
            <ArrowRight size={16} />
          </button>
        </form>

        {/* Toggle between Login and Registration */}
        {role !== 'admin' && (
          <div style={{ textAlign: 'center', marginTop: 18, fontSize: 12, color: 'var(--text-secondary)' }}>
            {isRegister ? 'Already registered?' : "Don't have an account yet?"}{' '}
            <button
              type="button"
              onClick={() => setIsRegister(!isRegister)}
              style={{ color: 'var(--primary)', fontWeight: 700, textDecoration: 'underline' }}
            >
              {isRegister ? 'Sign In' : (role === 'courier' ? 'Apply as Delivery Partner' : 'Request Access')}
            </button>
          </div>
        )}

        {/* Portal Switcher Footer */}
        <div style={{
          marginTop: 24,
          paddingTop: 16,
          borderTop: '1px solid var(--border-light)',
          display: 'flex',
          justifyContent: 'center',
          gap: 16,
          fontSize: 11,
          color: 'var(--text-muted)'
        }}>
          <button onClick={() => onNavigate('/courier/login')} style={{ color: role === 'courier' ? 'var(--primary)' : 'inherit', fontWeight: role === 'courier' ? 700 : 400 }}>
            Courier Login
          </button>
          <span>·</span>
          <button onClick={() => onNavigate('/company/login')} style={{ color: role === 'company' ? 'var(--primary)' : 'inherit', fontWeight: role === 'company' ? 700 : 400 }}>
            Operations Login
          </button>
          <span>·</span>
          <button onClick={() => onNavigate('/admin/login')} style={{ color: role === 'admin' ? 'var(--primary)' : 'inherit', fontWeight: role === 'admin' ? 700 : 400 }}>
            Admin Portal
          </button>
        </div>
      </div>
    </div>
  );
}
