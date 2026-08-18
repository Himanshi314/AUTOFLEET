import React from 'react';
import { useAuth } from '../context/AuthContext';
import { 
  ShieldCheck, 
  Cpu, 
  RotateCcw, 
  BookOpen, 
  Radio, 
  LogOut, 
  Truck, 
  Building2, 
  Terminal, 
  Sparkles,
  ChevronDown
} from 'lucide-react';

export function Navbar({ 
  mode, 
  onModeChange, 
  autonomous, 
  onAutonomousToggle, 
  onReset, 
  onOpenAssumptions, 
  connected,
  currentRoute,
  onNavigate
}) {
  const { user, logout, switchRole } = useAuth();
  const [roleDropdownOpen, setRoleDropdownOpen] = React.useState(false);

  return (
    <header style={{
      backgroundColor: '#FFFFFF',
      borderBottom: '1px solid var(--border-light)',
      padding: '10px 20px',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      position: 'sticky',
      top: 0,
      zIndex: 40,
      boxShadow: '0 1px 3px rgba(0,0,0,0.03)'
    }}>
      {/* Brand & Active Role */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <div 
          onClick={() => onNavigate('/')} 
          style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer' }}
        >
          <div style={{
            width: 34,
            height: 34,
            borderRadius: 8,
            backgroundColor: 'var(--primary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--accent)',
            boxShadow: '0 2px 6px rgba(30,58,43,0.2)'
          }}>
            <svg width="20" height="20" viewBox="0 0 32 32" fill="none">
              <path d="M16 2 L29 9.5 L29 22.5 L16 30 L3 22.5 L3 9.5 Z" stroke="currentColor" strokeWidth="2.5" fill="rgba(52,211,153,0.15)"/>
              <circle cx="16" cy="16" r="4.5" fill="currentColor"/>
            </svg>
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 16, fontWeight: 800, color: 'var(--text-main)', letterSpacing: '-0.02em' }}>
                AutoFleet
              </span>
              <span style={{ 
                fontSize: 12, 
                fontWeight: 700, 
                backgroundColor: 'var(--accent-light)', 
                color: 'var(--accent-dark)',
                padding: '1px 5px',
                borderRadius: 4
              }}>AI</span>
            </div>
            <p style={{ fontSize: 10, color: 'var(--text-secondary)', fontWeight: 500, margin: 0, lineHeight: 1 }}>
              Autonomous Last-Mile Disruption Resolution
            </p>
          </div>
        </div>

        {/* Navigation Tabs for Easy Role Switching */}
        <nav style={{
          display: 'flex',
          alignItems: 'center',
          gap: 4,
          backgroundColor: 'var(--bg-subtle)',
          padding: 3,
          borderRadius: 'var(--radius-md)',
          marginLeft: 12
        }}>
          <button
            onClick={() => { switchRole('courier'); onNavigate('/courier/dashboard'); }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 12px',
              borderRadius: 'var(--radius-sm)',
              fontSize: 12,
              fontWeight: 600,
              color: currentRoute.includes('courier') ? 'var(--primary)' : 'var(--text-secondary)',
              backgroundColor: currentRoute.includes('courier') ? '#FFFFFF' : 'transparent',
              boxShadow: currentRoute.includes('courier') ? 'var(--shadow-sm)' : 'none',
            }}
          >
            <Truck size={14} />
            Courier
          </button>

          <button
            onClick={() => { switchRole('company'); onNavigate('/company/dashboard'); }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 12px',
              borderRadius: 'var(--radius-sm)',
              fontSize: 12,
              fontWeight: 600,
              color: currentRoute.includes('company') ? 'var(--primary)' : 'var(--text-secondary)',
              backgroundColor: currentRoute.includes('company') ? '#FFFFFF' : 'transparent',
              boxShadow: currentRoute.includes('company') ? 'var(--shadow-sm)' : 'none',
            }}
          >
            <Building2 size={14} />
            Operations
          </button>

          <button
            onClick={() => { switchRole('admin'); onNavigate('/admin/dashboard'); }}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              padding: '6px 12px',
              borderRadius: 'var(--radius-sm)',
              fontSize: 12,
              fontWeight: 600,
              color: currentRoute.includes('admin') ? 'var(--primary)' : 'var(--text-secondary)',
              backgroundColor: currentRoute.includes('admin') ? '#FFFFFF' : 'transparent',
              boxShadow: currentRoute.includes('admin') ? 'var(--shadow-sm)' : 'none',
            }}
          >
            <Terminal size={14} />
            Admin
          </button>
        </nav>
      </div>

      {/* Engine Controls & Mode Toggles */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {/* Scenario mode switcher (Commercial / Humanitarian) */}
        <div style={{
          display: 'flex',
          backgroundColor: 'var(--bg-subtle)',
          padding: 3,
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border-light)'
        }}>
          <button
            onClick={() => onModeChange('commercial')}
            style={{
              padding: '5px 12px',
              fontSize: 12,
              fontWeight: 600,
              borderRadius: 'var(--radius-sm)',
              color: mode === 'commercial' ? '#FFFFFF' : 'var(--text-secondary)',
              backgroundColor: mode === 'commercial' ? 'var(--primary)' : 'transparent',
              boxShadow: mode === 'commercial' ? '0 1px 2px rgba(0,0,0,0.1)' : 'none'
            }}
          >
            Commercial
          </button>
          <button
            onClick={() => onModeChange('humanitarian')}
            style={{
              padding: '5px 12px',
              fontSize: 12,
              fontWeight: 600,
              borderRadius: 'var(--radius-sm)',
              color: mode === 'humanitarian' ? '#FFFFFF' : 'var(--text-secondary)',
              backgroundColor: mode === 'humanitarian' ? 'var(--primary)' : 'transparent',
              boxShadow: mode === 'humanitarian' ? '0 1px 2px rgba(0,0,0,0.1)' : 'none'
            }}
          >
            Humanitarian (Cold-Chain)
          </button>
        </div>

        {/* Autonomous Mode Toggle Button */}
        <button
          onClick={onAutonomousToggle}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 7,
            padding: '6px 12px',
            borderRadius: 'var(--radius-md)',
            fontSize: 12,
            fontWeight: 600,
            backgroundColor: autonomous ? '#FEF3C7' : '#FFFFFF',
            border: `1px solid ${autonomous ? '#F59E0B' : 'var(--border-light)'}`,
            color: autonomous ? '#92400E' : 'var(--text-secondary)',
          }}
          title={autonomous ? "Autonomous watchdog active (>0.68 failure risk self-triggers)" : "Arm autonomous self-triggering"}
        >
          <span style={{
            width: 7,
            height: 7,
            borderRadius: '50%',
            backgroundColor: autonomous ? '#D97706' : '#94A3B8',
            animation: autonomous ? 'pulseGlow 1.5s infinite ease-in-out' : 'none'
          }} />
          <span>Autonomous</span>
          <span style={{
            fontSize: 10,
            fontWeight: 700,
            padding: '1px 5px',
            borderRadius: 3,
            backgroundColor: autonomous ? '#F59E0B' : 'var(--bg-subtle)',
            color: autonomous ? '#FFFFFF' : 'var(--text-muted)'
          }}>
            {autonomous ? 'ARMED' : 'OFF'}
          </span>
        </button>

        {/* Assumptions modal trigger */}
        <button
          onClick={onOpenAssumptions}
          className="btn-secondary"
          style={{ padding: '6px 11px', fontSize: 12 }}
          title="Inspect documented assumptions, emission factors, and model cards"
        >
          <BookOpen size={13} />
          Assumptions &amp; Models
        </button>

        {/* Reset button */}
        <button
          onClick={onReset}
          className="btn-secondary"
          style={{ padding: '6px 11px', fontSize: 12 }}
          title="Reset world fleet state"
        >
          <RotateCcw size={13} />
          Reset
        </button>

        {/* Live SSE Connection Badge */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          padding: '6px 10px',
          borderRadius: 'var(--radius-md)',
          backgroundColor: connected ? 'var(--accent-light)' : '#FEE2E2',
          color: connected ? 'var(--accent-dark)' : '#DC2626',
          fontSize: 11,
          fontWeight: 600,
          border: `1px solid ${connected ? 'var(--accent-border)' : '#FECACA'}`
        }}>
          <Radio size={12} style={{ animation: connected ? 'pulseGlow 2s infinite' : 'none' }} />
          <span>{connected ? 'SSE Live' : 'Reconnecting...'}</span>
        </div>

        {/* User profile & Logout */}
        {user && (
          <div style={{ position: 'relative' }}>
            <button
              onClick={() => setRoleDropdownOpen(!roleDropdownOpen)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                padding: '4px 8px',
                borderRadius: 'var(--radius-md)',
                backgroundColor: 'var(--bg-subtle)',
                border: '1px solid var(--border-light)',
                fontSize: 12,
                fontWeight: 600
              }}
            >
              <div style={{
                width: 24,
                height: 24,
                borderRadius: '50%',
                backgroundColor: 'var(--primary)',
                color: '#FFFFFF',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: 10,
                fontWeight: 700
              }}>
                {user.name.charAt(0)}
              </div>
              <span style={{ maxWidth: 100, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {user.name}
              </span>
              <ChevronDown size={13} color="var(--text-muted)" />
            </button>

            {roleDropdownOpen && (
              <div style={{
                position: 'absolute',
                right: 0,
                top: '110%',
                backgroundColor: '#FFFFFF',
                border: '1px solid var(--border-light)',
                borderRadius: 'var(--radius-md)',
                boxShadow: 'var(--shadow-lg)',
                padding: 6,
                minWidth: 180,
                zIndex: 100
              }}>
                <div style={{ padding: '6px 10px', borderBottom: '1px solid var(--border-light)', marginBottom: 4 }}>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-main)' }}>{user.name}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{user.email || user.phone}</div>
                  <span className="badge badge-nominal" style={{ marginTop: 4 }}>Role: {user.role.toUpperCase()}</span>
                </div>

                <button
                  onClick={() => { logout(); setRoleDropdownOpen(false); onNavigate('/login'); }}
                  style={{
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '6px 10px',
                    borderRadius: 'var(--radius-sm)',
                    fontSize: 12,
                    color: '#DC2626',
                    textAlign: 'left'
                  }}
                >
                  <LogOut size={13} />
                  Sign Out
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </header>
  );
}
