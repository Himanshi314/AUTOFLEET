import React from 'react';
import { X, BookOpen, Scale, ShieldAlert, Leaf, Clock, Cpu } from 'lucide-react';

export function AssumptionsModal({ isOpen, onClose, meta }) {
  if (!isOpen) return null;

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: 'rgba(18, 36, 26, 0.45)',
      backdropFilter: 'blur(3px)',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      zIndex: 100,
      padding: 20
    }} onClick={onClose}>
      <div 
        style={{
          backgroundColor: '#FFFFFF',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-float)',
          maxWidth: 780,
          width: '100%',
          maxHeight: '90vh',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          animation: 'fadeIn 0.2s ease-out'
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div style={{
          padding: '18px 24px',
          borderBottom: '1px solid var(--border-light)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          backgroundColor: 'var(--bg-subtle)'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{
              width: 36,
              height: 36,
              borderRadius: 8,
              backgroundColor: 'var(--primary)',
              color: 'var(--accent)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center'
            }}>
              <BookOpen size={20} />
            </div>
            <div>
              <h3 style={{ fontSize: 18, fontWeight: 700, color: 'var(--text-main)' }}>
                Assumptions, Models &amp; Scientific Reference
              </h3>
              <p style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                Every metric on the dashboard traces back to these documented calculations.
              </p>
            </div>
          </div>
          <button 
            onClick={onClose}
            style={{
              padding: 6,
              borderRadius: '50%',
              backgroundColor: '#FFFFFF',
              border: '1px solid var(--border-light)',
              color: 'var(--text-secondary)'
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Content */}
        <div style={{ padding: 24, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 20 }}>
          {/* Honest Disclaimer */}
          <div style={{
            backgroundColor: '#FEF3C7',
            border: '1px solid #FCD34D',
            padding: 14,
            borderRadius: 'var(--radius-md)',
            display: 'flex',
            gap: 12,
            alignItems: 'flex-start'
          }}>
            <ShieldAlert size={20} color="#D97706" style={{ flexShrink: 0, marginTop: 2 }} />
            <div style={{ fontSize: 12, color: '#92400E', lineHeight: 1.5 }}>
              <b>Scientific Positioning:</b> This dashboard uses hand-calibrated operational heuristics and published emission standards. The failure risk scores are uncalibrated indicator probabilities, not fitted statistical parameters. 66% of real incidents have an obvious best driver; the multi-agent chain exists to handle the ambiguous, interdependent tail without hard-coding hundreds of static rules.
            </div>
          </div>

          {/* Grid of Sections */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
            {/* Emission Factors */}
            <div className="card" style={{ padding: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <Leaf size={18} color="#059669" />
                <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--primary)' }}>CO₂e Emission Standards</h4>
              </div>
              <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 10 }}>
                Sourced from DEFRA/DESNZ 2025 GHG conversion factors and the CEA CO2 Baseline Database v21.0 (India grid). Each factor is an estimate — see EMISSION_SOURCES in autofleet/impact.py for the per-vehicle citation:
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6, fontSize: 11 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 8px', backgroundColor: 'var(--bg-subtle)', borderRadius: 4 }}>
                  <span>Electric 2-Wheeler (EV)</span>
                  <b className="mono">0.021 kg CO₂e / km</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 8px', backgroundColor: 'var(--bg-subtle)', borderRadius: 4 }}>
                  <span>Petrol Two-Wheeler (ICE)</span>
                  <b className="mono">0.045 kg CO₂e / km</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 8px', backgroundColor: 'var(--bg-subtle)', borderRadius: 4 }}>
                  <span>Electric Van / LCV</span>
                  <b className="mono">0.078 kg CO₂e / km</b>
                </div>
                <div style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 8px', backgroundColor: 'var(--bg-subtle)', borderRadius: 4 }}>
                  <span>Diesel Van / LCV</span>
                  <b className="mono">0.174 kg CO₂e / km</b>
                </div>
              </div>
            </div>

            {/* Time & Economic Constants */}
            <div className="card" style={{ padding: 16 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
                <Clock size={18} color="#2563EB" />
                <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--primary)' }}>Operational Baseline</h4>
              </div>
              <ul style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6, paddingLeft: 18 }}>
                <li><b>Coordinator time saved:</b> 14 minutes baseline per phone exception (calls, reassignment, route updating).</li>
                <li><b>Avoided redelivery distance:</b> ~27 km per prevented second-attempt trip in Bengaluru metropolitan.</li>
                <li><b>Routing circuity factor:</b> Haversine aerial distance × <b>1.35</b> assumed street network factor.</li>
                <li><b>Cold-chain threshold:</b> 60–90 minute strict stability window for vaccines and blood consignments.</li>
              </ul>
            </div>
          </div>

          {/* Model Cards */}
          <div className="card" style={{ padding: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
              <Cpu size={18} color="#7C3AED" />
              <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--primary)' }}>Active Intelligence Models</h4>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 12, fontSize: 12 }}>
              <div style={{ backgroundColor: 'var(--bg-subtle)', padding: 12, borderRadius: 'var(--radius-md)' }}>
                <div style={{ fontWeight: 700, color: 'var(--text-main)', marginBottom: 4 }}>
                  disruption-risk-v1 (Watchdog Heuristic)
                </div>
                <p style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                  Calculates predicted failure probability using battery degradation, corridor traffic index, historical recipient absent rates, and driver shift duration.
                </p>
              </div>

              <div style={{ backgroundColor: 'var(--bg-subtle)', padding: 12, borderRadius: 'var(--radius-md)' }}>
                <div style={{ fontWeight: 700, color: 'var(--text-main)', marginBottom: 4 }}>
                  agent-router-v1 (5-Specialist Coordinator)
                </div>
                <p style={{ color: 'var(--text-secondary)', lineHeight: 1.4 }}>
                  Determines minimal required agent subset (Recipient Comms, Route &amp; Fleet, Driver Support, Resolution) to minimize token consumption and latency.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Footer */}
        <div style={{
          padding: '14px 24px',
          borderTop: '1px solid var(--border-light)',
          display: 'flex',
          justifyContent: 'flex-end',
          backgroundColor: '#FFFFFF'
        }}>
          <button onClick={onClose} className="btn-primary" style={{ padding: '8px 18px', fontSize: 13 }}>
            Understood
          </button>
        </div>
      </div>
    </div>
  );
}
