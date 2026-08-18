import React from 'react';
import { useAuth } from '../context/AuthContext';
import { 
  Truck, 
  Building2, 
  Terminal, 
  ArrowRight, 
  ShieldCheck, 
  Zap, 
  Sparkles, 
  TrendingUp, 
  MapPin,
  Bot
} from 'lucide-react';

export function PortalGateway({ onNavigate }) {
  const { switchRole } = useAuth();

  const portals = [
    {
      id: 'courier',
      title: 'Courier & Delivery Partner',
      badge: 'Driver Experience',
      badgeColor: 'badge-nominal',
      icon: <Truck size={28} />,
      desc: 'Mobile-optimized interface for riders. View active consignment, live GPS navigation, receive roadside assistance alerts, and confirm handovers with protected earnings.',
      features: ['Live Order D-103 navigation', 'Roadside assistance & SOS', 'Guaranteed breakdown pay', 'Quick 1-tap disruption report'],
      route: '/courier/dashboard',
      loginRoute: '/courier/login'
    },
    {
      id: 'company',
      title: 'Logistics Operations Desk',
      badge: 'Fleet Control',
      badgeColor: 'badge-onroute',
      icon: <Building2 size={28} />,
      desc: 'Full command center for 3PL and enterprise carriers. Monitor Bengaluru live corridor map, SLA metrics, failure risk meters, and watch the 5-agent AI chain resolve disruptions in ~4.2s.',
      features: ['Live Bengaluru fleet map', 'Autonomous watchdog (0.68)', 'Real-time multi-agent stream', 'CO2e & km impact counters'],
      route: '/company/dashboard',
      loginRoute: '/company/login'
    },
    {
      id: 'admin',
      title: 'Admin & Pipeline Visualizer',
      badge: 'System Control',
      badgeColor: 'badge-resolving',
      icon: <Terminal size={28} />,
      desc: 'Root engine architecture inspection. View live node graph of the 6-stage pipeline, streaming terminal logs, model calibration weights, and emergency overrides.',
      features: ['6-Stage pipeline node flow', 'Dark-green streaming terminal', 'Model calibration cards', 'Global simulation triggers'],
      route: '/admin/dashboard',
      loginRoute: '/admin/login'
    }
  ];

  return (
    <div style={{ maxWidth: 1200, margin: '0 auto', padding: '40px 20px', display: 'flex', flexDirection: 'column', gap: 32 }}>
      {/* Hero Header */}
      <div style={{ textAlign: 'center', maxWidth: 740, margin: '0 auto' }}>
        <div style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: 6,
          backgroundColor: 'var(--accent-light)',
          color: 'var(--accent-dark)',
          padding: '4px 12px',
          borderRadius: 20,
          fontSize: 12,
          fontWeight: 700,
          marginBottom: 14
        }}>
          <Sparkles size={14} />
          AutoFleet AI — Multi-Role Architecture
        </div>

        <h1 style={{ fontSize: 36, fontWeight: 800, color: 'var(--primary)', letterSpacing: '-0.03em', lineHeight: 1.2 }}>
          Autonomous Last-Mile Disruption Resolution
        </h1>

        <p style={{ fontSize: 16, color: 'var(--text-secondary)', marginTop: 12, lineHeight: 1.6 }}>
          When a delivery fails, human coordinators take 10–20 minutes to fix it. AutoFleet AI detects telemetry disruption and resolves it end-to-end in <b>~4 seconds</b>. Select a role below to explore the application:
        </p>
      </div>

      {/* Role Cards Grid */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 24 }}>
        {portals.map((p) => (
          <div 
            key={p.id}
            className="card"
            style={{
              padding: 28,
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              transition: 'transform 0.2s ease, box-shadow 0.2s ease'
            }}
          >
            <div>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                <div style={{
                  width: 54,
                  height: 54,
                  borderRadius: 14,
                  backgroundColor: 'var(--primary)',
                  color: 'var(--accent)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  boxShadow: '0 4px 12px rgba(30,58,43,0.2)'
                }}>
                  {p.icon}
                </div>
                <span className={`badge ${p.badgeColor}`}>{p.badge}</span>
              </div>

              <h3 style={{ fontSize: 20, fontWeight: 800, color: 'var(--text-main)', marginBottom: 8 }}>
                {p.title}
              </h3>

              <p style={{ fontSize: 13, color: 'var(--text-secondary)', lineHeight: 1.5, marginBottom: 18 }}>
                {p.desc}
              </p>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 24 }}>
                {p.features.map((f, i) => (
                  <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: 'var(--text-main)' }}>
                    <div style={{ width: 5, height: 5, borderRadius: '50%', backgroundColor: 'var(--accent-dark)' }} />
                    <span>{f}</span>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <button
                onClick={() => {
                  switchRole(p.id);
                  onNavigate(p.route);
                }}
                className="btn-primary"
                style={{ width: '100%', padding: '12px', fontSize: 13 }}
              >
                Launch {p.title.split(' ')[0]} Dashboard
                <ArrowRight size={15} />
              </button>

              <button
                onClick={() => onNavigate(p.loginRoute)}
                className="btn-secondary"
                style={{ width: '100%', padding: '9px', fontSize: 12 }}
              >
                Sign In / Switch Account
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
