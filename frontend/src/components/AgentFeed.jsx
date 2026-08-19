import React, { useRef, useEffect } from 'react';
import { 
  Bot, 
  Sparkles, 
  Clock, 
  Zap, 
  CheckCircle2, 
  AlertCircle, 
  ShieldCheck, 
  Navigation, 
  UserCheck, 
  TrendingUp,
  Cpu,
  ArrowRight
} from 'lucide-react';

export function AgentFeed({ activeChain }) {
  const scrollRef = useRef(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [activeChain]);

  if (!activeChain) {
    return (
      <div style={{
        height: '100%',
        minHeight: 320,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 30,
        textAlign: 'center',
        backgroundColor: '#FFFFFF',
        borderRadius: 'var(--radius-lg)',
        border: '1px solid var(--border-light)'
      }}>
        <div style={{
          width: 52,
          height: 52,
          borderRadius: '50%',
          backgroundColor: 'var(--bg-subtle)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          color: 'var(--primary)',
          marginBottom: 16
        }}>
          <Bot size={28} />
        </div>
        <h4 style={{ fontSize: 16, fontWeight: 700, color: 'var(--text-main)', marginBottom: 6 }}>
          No active disruption
        </h4>
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', maxWidth: 360, lineHeight: 1.5 }}>
          Six specialist agents are on standby, and the router decides which of them this incident actually needs. Trigger a disruption on any active delivery or arm <b>Autonomous</b> watchdog to self-trigger.
        </p>
      </div>
    );
  }

  const { plan, agents = {}, resolution, incident_id, delivery_id, disruption_label, disruption_icon, detected_as, risk_before, trigger } = activeChain;

  return (
    <div style={{
      height: '100%',
      display: 'flex',
      flexDirection: 'column',
      backgroundColor: '#FFFFFF',
      borderRadius: 'var(--radius-lg)',
      border: '1px solid var(--border-light)',
      overflow: 'hidden'
    }}>
      {/* Incident Header */}
      <div style={{
        padding: '14px 18px',
        backgroundColor: 'var(--primary)',
        color: '#FFFFFF',
        borderBottom: '1px solid rgba(255,255,255,0.1)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 20 }}>{disruption_icon}</span>
            <div>
              <span style={{ fontSize: 14, fontWeight: 700 }}>{disruption_label}</span>
              <span style={{ fontSize: 12, opacity: 0.8, marginLeft: 8 }}>· {delivery_id}</span>
            </div>
          </div>
          <span className="mono" style={{ fontSize: 11, backgroundColor: 'rgba(255,255,255,0.15)', padding: '2px 8px', borderRadius: 4 }}>
            {incident_id}
          </span>
        </div>

        <div style={{ fontSize: 12, color: 'var(--accent-light)', display: 'flex', alignItems: 'center', gap: 6 }}>
          <span>Detected via: <b>{detected_as}</b></span>
          <span>· Risk: <b>{(risk_before?.risk * 100).toFixed(0)}%</b> ({risk_before?.band})</span>
          {trigger !== 'manual' && (
            <span style={{ backgroundColor: 'var(--accent-dark)', color: '#FFFFFF', padding: '1px 6px', borderRadius: 3, fontSize: 10, fontWeight: 700 }}>
              AUTO-TRIGGERED
            </span>
          )}
        </div>
      </div>

      {/* Agents Execution Spine */}
      <div 
        ref={scrollRef} 
        style={{
          flex: 1,
          padding: 16,
          overflowY: 'auto',
          display: 'flex',
          flexDirection: 'column',
          gap: 12,
          backgroundColor: '#F9FBFA'
        }}
      >
        {/* Router Plan Card */}
        {plan && (
          <div style={{
            backgroundColor: '#FFFFFF',
            borderRadius: 'var(--radius-md)',
            border: '1px solid #D8E6DE',
            padding: 12,
            boxShadow: 'var(--shadow-sm)'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span className="badge badge-resolving" style={{ fontSize: 10 }}>ROUTER</span>
                <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--primary)' }}>
                  {plan.path?.toUpperCase()}
                </span>
              </div>
              <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                {plan.agents?.length}/{plan.total} roles active
                {plan.saved > 0 && <b style={{ color: 'var(--accent-dark)', marginLeft: 4 }}>({plan.saved} calls saved)</b>}
              </span>
            </div>

            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
              {plan.specs?.map((s) => {
                const isActive = plan.agents?.includes(s.id);
                return (
                  <span 
                    key={s.id}
                    style={{
                      fontSize: 11,
                      fontWeight: 600,
                      padding: '3px 8px',
                      borderRadius: 4,
                      display: 'inline-flex',
                      alignItems: 'center',
                      gap: 4,
                      backgroundColor: isActive ? 'var(--accent-light)' : 'var(--bg-subtle)',
                      color: isActive ? 'var(--accent-dark)' : 'var(--text-muted)',
                      border: `1px solid ${isActive ? 'var(--accent-border)' : '#E2ECE7'}`
                    }}
                  >
                    <span>{s.icon}</span>
                    <span>{s.label.replace(' Agent', '')}</span>
                  </span>
                );
              })}
            </div>

            <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.4 }}>
              {plan.reason}
            </div>
          </div>
        )}

        {/* Individual Agent Execution Cards */}
        {Object.values(agents).map((ag) => (
          <div 
            key={ag.id}
            style={{
              backgroundColor: '#FFFFFF',
              borderRadius: 'var(--radius-md)',
              border: `1px solid ${ag.status === 'active' ? '#8B5CF6' : 'var(--border-light)'}`,
              padding: 12,
              boxShadow: ag.status === 'active' ? '0 0 0 2px rgba(139, 92, 246, 0.15)' : 'var(--shadow-sm)',
              position: 'relative'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 16 }}>{ag.icon}</span>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-main)' }}>{ag.label}</div>
                  <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{ag.owns}</div>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
                {ag.status === 'active' ? (
                  <span style={{ color: '#7C3AED', fontWeight: 600, display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span className="pulse-dot" style={{ backgroundColor: '#7C3AED', width: 6, height: 6 }} />
                    reasoning...
                  </span>
                ) : (
                  <span style={{ color: 'var(--text-muted)' }}>
                    {ag.ms ? `${(ag.ms / 1000).toFixed(1)}s` : ''}
                    {ag.tokens?.output ? ` · ${ag.tokens.output} tok` : ''}
                  </span>
                )}
              </div>
            </div>

            {/* Agent rationale body */}
            <div style={{
              fontSize: 12,
              color: 'var(--text-main)',
              lineHeight: 1.5,
              whiteSpace: 'pre-wrap',
              backgroundColor: 'var(--bg-subtle)',
              padding: 8,
              borderRadius: 6,
              border: '1px solid var(--border-light)',
              fontFamily: 'inherit'
            }}>
              {ag.text || (ag.status === 'active' ? 'Synthesizing fleet state and constraints...' : '')}
            </div>

            {ag.source && ag.source !== 'live' && (
              <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 4, fontStyle: 'italic' }}>
                Mode: {ag.source} ({ag.note || 'deterministic calibrated fallback'})
              </div>
            )}
          </div>
        ))}

        {/* Resolution Banner */}
        {resolution && (
          <div style={{
            backgroundColor: '#ECFDF5',
            border: '1px solid #A7F3D0',
            borderRadius: 'var(--radius-md)',
            padding: 14,
            marginTop: 4,
            boxShadow: 'var(--shadow-md)'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <CheckCircle2 size={18} color="#059669" />
              <span style={{ fontSize: 14, fontWeight: 800, color: '#065F46' }}>
                Resolution Authoritative: {resolution.outcome?.toUpperCase()}
              </span>
              <span className="mono" style={{ fontSize: 11, marginLeft: 'auto', color: '#047857' }}>
                {resolution.seconds?.toFixed(1)}s total
              </span>
            </div>
            
            <p style={{ fontSize: 12, color: '#065F46', lineHeight: 1.5, marginBottom: 8 }}>
              {resolution.summary}
            </p>

            {resolution.details && (
              <div style={{
                fontSize: 11,
                color: '#047857',
                backgroundColor: 'rgba(255,255,255,0.6)',
                padding: '8px 10px',
                borderRadius: 4,
                display: 'grid',
                gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                gap: 6
              }}>
                {Object.entries(resolution.details).map(([k, v]) => (
                  <div key={k}>
                    <span style={{ opacity: 0.8 }}>{k.replace(/_/g, ' ')}:</span> <b>{String(v)}</b>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
