import React, { useState, useRef, useEffect } from 'react';
import { 
  Terminal, 
  Cpu, 
  Layers, 
  Sliders, 
  Zap, 
  Activity, 
  ShieldAlert, 
  RotateCcw, 
  CheckCircle2, 
  Play, 
  ArrowRight, 
  Database,
  GitBranch,
  Bot
} from 'lucide-react';

export function AdminDashboard({ 
  fleetState, 
  fleetMeta, 
  terminalLogs = [], 
  onTriggerDisruption, 
  onReset, 
  autonomous, 
  onAutonomousToggle,
  activeChain 
}) {
  const terminalEndRef = useRef(null);
  const [selectedAgentNode, setSelectedAgentNode] = useState('router');

  useEffect(() => {
    if (terminalEndRef.current) {
      terminalEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [terminalLogs]);

  const pipelineNodes = [
    {
      id: 'ingest',
      name: '1. Event Ingest & Watchdog',
      role: 'Telemetry Monitor',
      icon: '📡',
      desc: 'Evaluates real-time delivery telemetry. Detects failure risk crossing 0.68 threshold without human input.'
    },
    {
      id: 'router',
      name: '2. Agent Router',
      role: 'Role Orchestrator',
      icon: '🧠',
      desc: 'Determines minimal subset of specialist agents required. Avoids 1-3 unnecessary LLM calls per incident.'
    },
    {
      id: 'recipient_comms',
      name: '3. Recipient Comms',
      role: 'Customer Agent',
      icon: '💬',
      desc: 'Communicates with recipient over SMS/WhatsApp. Negotiates safe drops or updated ETAs.'
    },
    {
      id: 'route_and_fleet',
      name: '4. Route & Fleet',
      role: 'Dispatch Agent',
      icon: '🛵',
      desc: 'Evaluates standby drivers, calculates detour km, battery levels, and suitability margins.'
    },
    {
      id: 'driver_support',
      name: '5. Driver Support',
      role: 'Roadside & Pay Agent',
      icon: '🛡️',
      desc: 'Dispatches roadside assistance, marks courier unavailable, and locks in trip earnings.'
    },
    {
      id: 'resolution',
      name: '6. Resolution Engine',
      role: 'Authoritative State',
      icon: '⚡',
      desc: 'Synthesizes decisions and executes atomic write-back to world state and SSE subscribers.'
    }
  ];

  return (
    <div style={{ maxWidth: 1440, margin: '0 auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Top Admin System Header */}
      <div style={{
        backgroundColor: '#FFFFFF',
        borderRadius: 'var(--radius-lg)',
        padding: '16px 22px',
        border: '1px solid var(--border-light)',
        boxShadow: 'var(--shadow-sm)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 14
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 40,
            height: 40,
            borderRadius: 8,
            backgroundColor: 'var(--primary)',
            color: 'var(--accent)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            <Terminal size={22} />
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <h2 style={{ fontSize: 18, fontWeight: 800, color: 'var(--text-main)' }}>
                System Architecture &amp; Pipeline Control
              </h2>
              <span className="badge badge-nominal">Engine v1.4-active</span>
            </div>
            <p style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
              LLM inference status: <b>{fleetMeta?.llm?.mode || 'deterministic fallback active (no API key needed)'}</b>
            </p>
          </div>
        </div>

        {/* Global Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <button
            onClick={onAutonomousToggle}
            className="btn-secondary"
            style={{
              borderColor: autonomous ? '#F59E0B' : 'var(--border-light)',
              backgroundColor: autonomous ? '#FEF3C7' : '#FFFFFF',
              color: autonomous ? '#B45309' : 'var(--text-secondary)'
            }}
          >
            <Zap size={14} color={autonomous ? '#D97706' : 'var(--text-muted)'} />
            Watchdog: <b>{autonomous ? 'ARMED (>0.68)' : 'OFF'}</b>
          </button>

          <button
            onClick={onReset}
            className="btn-secondary"
            style={{ color: '#DC2626', borderColor: '#FECACA' }}
          >
            <RotateCcw size={14} />
            Emergency Fleet Reset
          </button>
        </div>
      </div>

      {/* Main Grid: Pipeline Node Visualizer (Left) & Real-Time Terminal (Right) */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: 16, alignItems: 'start' }}>
        {/* Left: Agent Pipeline Flow Visualizer */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div className="card" style={{ padding: 18, display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <h3 style={{ fontSize: 16, fontWeight: 800, color: 'var(--primary)' }}>
                  Multi-Agent Disruption Resolution Pipeline
                </h3>
                <p style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                  Click any node to inspect constraints and role ownership
                </p>
              </div>
              <span className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                6 Core Stages
              </span>
            </div>

            {/* Visual Node Chain */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {pipelineNodes.map((node, i) => {
                const isSelected = selectedAgentNode === node.id;
                const isCurrentlyActive = activeChain && activeChain.status === 'running';

                return (
                  <div key={node.id}>
                    <div
                      onClick={() => setSelectedAgentNode(node.id)}
                      style={{
                        padding: '12px 16px',
                        borderRadius: 'var(--radius-md)',
                        backgroundColor: isSelected ? 'var(--bg-subtle)' : '#FFFFFF',
                        border: `1.5px solid ${isSelected ? 'var(--primary)' : 'var(--border-light)'}`,
                        boxShadow: isSelected ? 'var(--shadow-md)' : 'var(--shadow-sm)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'space-between',
                        cursor: 'pointer',
                        transition: 'all 0.15s ease'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <span style={{ fontSize: 22 }}>{node.icon}</span>
                        <div>
                          <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-main)' }}>
                            {node.name}
                          </div>
                          <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                            Role: <b>{node.role}</b>
                          </div>
                        </div>
                      </div>

                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <span className="badge badge-nominal" style={{ fontSize: 10 }}>Ready</span>
                        <ArrowRight size={14} color="var(--text-muted)" />
                      </div>
                    </div>

                    {/* Node Connector Line */}
                    {i < pipelineNodes.length - 1 && (
                      <div style={{ height: 10, width: 2, backgroundColor: '#CADAD2', margin: '0 auto' }} />
                    )}
                  </div>
                );
              })}
            </div>

            {/* Selected Node Inspector Detail */}
            {selectedAgentNode && (
              <div style={{
                backgroundColor: 'var(--bg-subtle)',
                padding: 14,
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-light)',
                marginTop: 6
              }}>
                <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--primary)', marginBottom: 4 }}>
                  Stage Details: {pipelineNodes.find(n => n.id === selectedAgentNode)?.name}
                </div>
                <div style={{ fontSize: 12, color: 'var(--text-main)', lineHeight: 1.5 }}>
                  {pipelineNodes.find(n => n.id === selectedAgentNode)?.desc}
                </div>
              </div>
            )}
          </div>

          {/* Model Calibration Cards */}
          <div className="card" style={{ padding: 18 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
              <Sliders size={18} color="var(--primary)" />
              <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--primary)' }}>
                Model Heuristics &amp; Calibration Weights
              </h4>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10, fontSize: 11 }}>
              <div style={{ backgroundColor: 'var(--bg-subtle)', padding: 10, borderRadius: 6 }}>
                <div style={{ fontWeight: 700, color: 'var(--text-main)' }}>Battery Degradation</div>
                <div className="mono" style={{ color: 'var(--accent-dark)', fontWeight: 600 }}>Weight: 0.35</div>
                <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>EV charge drops below route safety</div>
              </div>
              <div style={{ backgroundColor: 'var(--bg-subtle)', padding: 10, borderRadius: 6 }}>
                <div style={{ fontWeight: 700, color: 'var(--text-main)' }}>Corridor Congestion</div>
                <div className="mono" style={{ color: 'var(--accent-dark)', fontWeight: 600 }}>Weight: 0.25</div>
                <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>Traffic speed drop on arterial road</div>
              </div>
              <div style={{ backgroundColor: 'var(--bg-subtle)', padding: 10, borderRadius: 6 }}>
                <div style={{ fontWeight: 700, color: 'var(--text-main)' }}>Driver Shift Fatigue</div>
                <div className="mono" style={{ color: 'var(--accent-dark)', fontWeight: 600 }}>Weight: 0.20</div>
                <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>Hours continuously on delivery</div>
              </div>
              <div style={{ backgroundColor: 'var(--bg-subtle)', padding: 10, borderRadius: 6 }}>
                <div style={{ fontWeight: 700, color: 'var(--text-main)' }}>Recipient Absence Prior</div>
                <div className="mono" style={{ color: 'var(--accent-dark)', fontWeight: 600 }}>Weight: 0.20</div>
                <div style={{ color: 'var(--text-muted)', fontSize: 10 }}>Historical missed delivery probability</div>
              </div>
            </div>
          </div>
        </div>

        {/* Right: Live Dark-Green Streaming Terminal */}
        <div style={{
          backgroundColor: 'var(--terminal-bg)',
          borderRadius: 'var(--radius-lg)',
          border: '1px solid var(--terminal-border)',
          display: 'flex',
          flexDirection: 'column',
          height: 720,
          boxShadow: 'var(--shadow-lg)',
          overflow: 'hidden'
        }}>
          {/* Terminal Window Header */}
          <div style={{
            padding: '10px 16px',
            backgroundColor: '#0F2117',
            borderBottom: '1px solid var(--terminal-border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <div style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: '#EF4444' }} />
              <div style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: '#F59E0B' }} />
              <div style={{ width: 10, height: 10, borderRadius: '50%', backgroundColor: '#10B981' }} />
              <span className="mono" style={{ fontSize: 12, fontWeight: 700, color: 'var(--terminal-dim)', marginLeft: 8 }}>
                autofleet-ai-engine.log — /api/stream
              </span>
            </div>
            <span className="mono" style={{ fontSize: 10, color: '#6EE7B7' }}>
              {terminalLogs.length} events logged
            </span>
          </div>

          {/* Terminal Body */}
          <div style={{
            flex: 1,
            padding: 16,
            overflowY: 'auto',
            fontFamily: 'var(--font-mono)',
            fontSize: 11.5,
            color: 'var(--terminal-text)',
            lineHeight: 1.6,
            display: 'flex',
            flexDirection: 'column',
            gap: 4,
            whiteSpace: 'pre-wrap'
          }}>
            <div style={{ color: '#6EE7B7', opacity: 0.7, marginBottom: 8 }}>
              # AutoFleet AI Real-Time System Log &amp; Agent Reasoning Trace<br />
              # Event-Driven Architecture · Stdlib Python Engine · SSE Channel Live<br />
              ----------------------------------------------------------------------
            </div>

            {terminalLogs.length === 0 ? (
              <div style={{ color: '#4B7A60', fontStyle: 'italic' }}>
                Waiting for telemetry drift and disruption events...
              </div>
            ) : (
              terminalLogs.map((line, idx) => {
                let color = '#4ADE80';
                if (line.includes('[WATCHDOG]') || line.includes('[WARN]')) color = '#FDE047';
                if (line.includes('[ERROR]')) color = '#F87171';
                if (line.includes('[RESOLUTION]')) color = '#67E8F9';
                if (line.includes('[ROUTER]')) color = '#C084FC';

                return (
                  <div key={idx} style={{ color }}>
                    {line}
                  </div>
                );
              })
            )}
            <div ref={terminalEndRef} />
          </div>

          {/* Quick Simulation Trigger Toolbar */}
          <div style={{
            padding: '10px 14px',
            backgroundColor: '#0F2117',
            borderTop: '1px solid var(--terminal-border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 8,
            fontSize: 11
          }}>
            <span style={{ color: 'var(--terminal-dim)', fontWeight: 600 }}>Quick Test:</span>
            <div style={{ display: 'flex', gap: 6 }}>
              <button
                onClick={() => onTriggerDisruption(fleetState?.deliveries?.[0]?.id || 'D-101', 'bike_breakdown', 'admin-terminal')}
                style={{
                  padding: '4px 8px',
                  backgroundColor: '#1E3A2B',
                  color: '#A7F3D0',
                  borderRadius: 4,
                  fontSize: 10,
                  fontWeight: 600,
                  border: '1px solid #2D5A3F'
                }}
              >
                ⚡ Fire Breakdown
              </button>
              <button
                onClick={() => onTriggerDisruption(fleetState?.deliveries?.[1]?.id || 'D-102', 'customer_not_home', 'admin-terminal')}
                style={{
                  padding: '4px 8px',
                  backgroundColor: '#1E3A2B',
                  color: '#A7F3D0',
                  borderRadius: 4,
                  fontSize: 10,
                  fontWeight: 600,
                  border: '1px solid #2D5A3F'
                }}
              >
                ⚡ Fire Not Home
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
