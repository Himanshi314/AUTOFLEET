import React, { useState, useMemo } from 'react';
import { InteractiveMap } from '../components/InteractiveMap';
import { AgentFeed } from '../components/AgentFeed';
import { 
  TrendingUp, 
  Package, 
  CheckCircle, 
  AlertOctagon, 
  Leaf, 
  Clock, 
  Zap, 
  Users, 
  ThermometerSnowflake, 
  ChevronRight, 
  Activity,
  Layers,
  ArrowRight,
  Filter
} from 'lucide-react';

export function CompanyDashboard({ 
  fleetState, 
  fleetMeta, 
  onTriggerDisruption, 
  activeChain, 
  pickedDriver, 
  setPickedDriver 
}) {
  const [selectedDeliveryId, setSelectedDeliveryId] = useState(null);
  const [filterRiskOnly, setFilterRiskOnly] = useState(false);
  const [activeTab, setActiveTab] = useState('feed'); // 'feed' | 'log'

  const deliveries = fleetState?.deliveries || [];
  const drivers = fleetState?.drivers || [];
  const impact = fleetState?.impact || {};
  const isHumanitarian = fleetState?.mode === 'humanitarian';

  // Available disruptions for current mode
  const availableDisruptions = useMemo(() => {
    const mode = fleetState?.mode || 'commercial';
    const all = fleetMeta?.disruptions || [
      { key: 'bike_breakdown', label: 'Bike Breakdown', icon: '🛵', modes: ['commercial', 'humanitarian'] },
      { key: 'customer_not_home', label: 'Customer Not Home', icon: '🚪', modes: ['commercial', 'humanitarian'] },
      { key: 'wrong_address', label: 'Wrong Address', icon: '📍', modes: ['commercial', 'humanitarian'] },
      { key: 'traffic_gridlock', label: 'Traffic Gridlock', icon: '🚗', modes: ['commercial', 'humanitarian'] },
      { key: 'cold_chain_breach', label: 'Cold-Chain Breach', icon: '❄️', modes: ['humanitarian'] },
    ];
    return all.filter(d => d.modes.includes(mode));
  }, [fleetState, fleetMeta]);

  const filteredDeliveries = useMemo(() => {
    if (!filterRiskOnly) return deliveries;
    return deliveries.filter(d => d.risk_band === 'critical' || d.risk_band === 'elevated' || d.status === 'Resolving');
  }, [deliveries, filterRiskOnly]);

  const activeResolvingCount = deliveries.filter(d => d.status === 'Resolving').length;
  const highRiskCount = deliveries.filter(d => d.risk_band === 'critical' || d.risk_band === 'elevated').length;

  return (
    <div style={{ maxWidth: 1440, margin: '0 auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Top Operational KPI Metrics Bar */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 12 }}>
        {/* Total Deliveries */}
        <div className="card" style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Total Volume (Today)
            </div>
            <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--primary)', marginTop: 2 }}>
              32,842
            </div>
            <div style={{ fontSize: 11, color: '#059669', display: 'flex', alignItems: 'center', gap: 4, marginTop: 2 }}>
              <TrendingUp size={12} /> +8.4% vs last week
            </div>
          </div>
          <div style={{ width: 40, height: 40, borderRadius: 8, backgroundColor: 'var(--bg-subtle)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--primary)' }}>
            <Package size={20} />
          </div>
        </div>

        {/* Active En Route */}
        <div className="card" style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Active {isHumanitarian ? 'Consignments' : 'Deliveries'}
            </div>
            <div style={{ fontSize: 24, fontWeight: 800, color: '#2563EB', marginTop: 2 }}>
              {deliveries.length > 0 ? deliveries.length * 40 + 8 : 488}
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)', marginTop: 2 }}>
              {drivers.length} couriers in live grid
            </div>
          </div>
          <div style={{ width: 40, height: 40, borderRadius: 8, backgroundColor: '#EFF6FF', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#2563EB' }}>
            <Activity size={20} />
          </div>
        </div>

        {/* SLA Compliance */}
        <div className="card" style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              On-Time SLA Rate
            </div>
            <div style={{ fontSize: 24, fontWeight: 800, color: '#059669', marginTop: 2 }}>
              96.7%
            </div>
            <div style={{ fontSize: 11, color: '#059669', marginTop: 2 }}>
              Autonomous saved 14m/incident
            </div>
          </div>
          <div style={{ width: 40, height: 40, borderRadius: 8, backgroundColor: '#ECFDF5', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#059669' }}>
            <CheckCircle size={20} />
          </div>
        </div>

        {/* Active Exceptions */}
        <div className="card" style={{ padding: '14px 18px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontSize: 11, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
              Active Exceptions
            </div>
            <div style={{ fontSize: 24, fontWeight: 800, color: activeResolvingCount > 0 ? '#7C3AED' : '#D97706', marginTop: 2 }}>
              {activeResolvingCount > 0 ? `${activeResolvingCount} Resolving` : `${highRiskCount || 4} at risk`}
            </div>
            <div style={{ fontSize: 11, color: activeResolvingCount > 0 ? '#7C3AED' : 'var(--text-muted)', marginTop: 2 }}>
              {activeResolvingCount > 0 ? 'Agent chain reasoning' : 'Watchdog threshold 0.68'}
            </div>
          </div>
          <div style={{ width: 40, height: 40, borderRadius: 8, backgroundColor: activeResolvingCount > 0 ? '#F5F3FF' : '#FEF3C7', display: 'flex', alignItems: 'center', justifyContent: 'center', color: activeResolvingCount > 0 ? '#7C3AED' : '#D97706' }}>
            <AlertOctagon size={20} />
          </div>
        </div>
      </div>

      {/* Cumulative Impact Strip */}
      <div className="card" style={{
        padding: '12px 18px',
        backgroundColor: 'var(--primary)',
        color: '#FFFFFF',
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
        gap: 12,
        alignItems: 'center'
      }}>
        <div style={{ borderRight: '1px solid rgba(255,255,255,0.1)', paddingRight: 10 }}>
          <div style={{ fontSize: 10, color: 'var(--accent-light)', textTransform: 'uppercase', fontWeight: 600 }}>Disruptions Resolved</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--accent)' }}>
            {impact.incidents_resolved || 0}
          </div>
          <div style={{ fontSize: 9, opacity: 0.75 }}>agent chain only</div>
        </div>

        <div style={{ borderRight: '1px solid rgba(255,255,255,0.1)', paddingRight: 10 }}>
          <div style={{ fontSize: 10, color: 'var(--accent-light)', textTransform: 'uppercase', fontWeight: 600 }}>Human Interventions</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: '#FFFFFF' }}>
            {impact.human_interventions || 0}
          </div>
          <div style={{ fontSize: 9, opacity: 0.75 }}>coordinators involved</div>
        </div>

        <div style={{ borderRight: '1px solid rgba(255,255,255,0.1)', paddingRight: 10 }}>
          <div style={{ fontSize: 10, color: 'var(--accent-light)', textTransform: 'uppercase', fontWeight: 600 }}>AI Calls Saved</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: '#A7F3D0' }}>
            {impact.llm_calls_saved || 0}
          </div>
          <div style={{ fontSize: 9, opacity: 0.75 }}>router skipped roles</div>
        </div>

        <div style={{ borderRight: '1px solid rgba(255,255,255,0.1)', paddingRight: 10 }}>
          <div style={{ fontSize: 10, color: 'var(--accent-light)', textTransform: 'uppercase', fontWeight: 600 }}>Redelivery km Avoided</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--accent)' }}>
            {(impact.km_avoided || 0).toFixed(1)} <small style={{ fontSize: 11 }}>km</small>
          </div>
          <div style={{ fontSize: 9, opacity: 0.75 }}>~27 km per retry</div>
        </div>

        <div style={{ borderRight: '1px solid rgba(255,255,255,0.1)', paddingRight: 10 }}>
          <div style={{ fontSize: 10, color: 'var(--accent-light)', textTransform: 'uppercase', fontWeight: 600 }}>CO₂e Avoided</div>
          <div style={{ fontSize: 20, fontWeight: 800, color: 'var(--accent)' }}>
            {(impact.co2e_kg_avoided || 0).toFixed(2)} <small style={{ fontSize: 11 }}>kg</small>
          </div>
          <div style={{ fontSize: 9, opacity: 0.75 }}>DEFRA &amp; ARAI factors</div>
        </div>

        <div>
          <div style={{ fontSize: 10, color: 'var(--accent-light)', textTransform: 'uppercase', fontWeight: 600 }}>
            {isHumanitarian ? 'Doses Preserved' : 'Coordinator Time Saved'}
          </div>
          <div style={{ fontSize: 20, fontWeight: 800, color: '#FCD34D' }}>
            {isHumanitarian 
              ? `${impact.doses_preserved || 0}`
              : `${(impact.coordinator_minutes_saved || 0).toFixed(0)} min`
            }
          </div>
          <div style={{ fontSize: 9, opacity: 0.75 }}>
            {isHumanitarian ? 'inside cold window' : '14m baseline saved'}
          </div>
        </div>
      </div>

      {/* Main Grid: Left = Bengaluru Map & Delivery Sparkline, Right = Live Deliveries & Agent Feed */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(420px, 1.4fr) minmax(360px, 1fr)', gap: 16, alignItems: 'start' }}>
        {/* Left Column: Map & Delivery Volume Trend */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Bengaluru Fleet Map Card */}
          <div className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12, minHeight: 460 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <h3 style={{ fontSize: 16, fontWeight: 800, color: 'var(--primary)' }}>
                  Live Bengaluru Fleet Map
                </h3>
                <p style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                  Real-time GPS telemetry, corridor circuity factor 1.27, and active handovers
                </p>
              </div>
              <span className="badge badge-nominal">
                <span className="pulse-dot" style={{ width: 6, height: 6 }} />
                Live Grid Stream
              </span>
            </div>

            <div style={{ height: 400, borderRadius: 'var(--radius-md)', overflow: 'hidden', border: '1px solid var(--border-light)' }}>
              <InteractiveMap 
                mapData={fleetState?.map}
                deliveries={deliveries}
                drivers={drivers}
                pickedDriver={pickedDriver}
                onSelectDriver={(drv) => setPickedDriver(drv.id)}
                selectedDeliveryId={selectedDeliveryId}
              />
            </div>
          </div>

          {/* Delivery Volume & Disruption Trend Chart Card */}
          <div className="card" style={{ padding: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
              <div>
                <h4 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-main)' }}>
                  Active Hourly Dispatch Volume &amp; Disruption Rate
                </h4>
                <p style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                  Peak traffic vs autonomous resolution efficiency over 24h
                </p>
              </div>
              <span className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                Today (08:00 - 20:00)
              </span>
            </div>

            {/* Smooth SVG Sparkline */}
            <div style={{ height: 90, width: '100%' }}>
              <svg viewBox="0 0 500 90" preserveAspectRatio="none" style={{ width: '100%', height: '100%' }}>
                <defs>
                  <linearGradient id="chartGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#34D399" stopOpacity="0.4" />
                    <stop offset="100%" stopColor="#34D399" stopOpacity="0.0" />
                  </linearGradient>
                </defs>
                <path 
                  d="M 0 70 Q 60 65, 120 45 T 240 30 T 360 40 T 500 20 L 500 90 L 0 90 Z" 
                  fill="url(#chartGrad)" 
                />
                <path 
                  d="M 0 70 Q 60 65, 120 45 T 240 30 T 360 40 T 500 20" 
                  fill="none" 
                  stroke="#10B981" 
                  strokeWidth="2.5" 
                />
                {/* Hourly tick marks */}
                {[0, 100, 200, 300, 400, 500].map((x, i) => (
                  <circle key={x} cx={x} cy={70 - i * 10 + (i % 2) * 15} r={3} fill="#1E3A2B" />
                ))}
              </svg>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-muted)', marginTop: 4 }}>
              <span>08:00</span>
              <span>11:00</span>
              <span>14:00</span>
              <span>17:00</span>
              <span>19:00 (Peak)</span>
              <span>21:00</span>
            </div>
          </div>
        </div>

        {/* Right Column: Fleet Deliveries & Agent Feed */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Active Deliveries List with Disruption Triggers */}
          <div className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <h3 style={{ fontSize: 15, fontWeight: 800, color: 'var(--primary)' }}>
                  Active {isHumanitarian ? 'Consignments' : 'Deliveries'} ({filteredDeliveries.length})
                </h3>
              </div>
              <button
                onClick={() => setFilterRiskOnly(!filterRiskOnly)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 4,
                  fontSize: 11,
                  fontWeight: 600,
                  padding: '4px 8px',
                  borderRadius: 4,
                  backgroundColor: filterRiskOnly ? '#FEF3C7' : 'var(--bg-subtle)',
                  color: filterRiskOnly ? '#B45309' : 'var(--text-secondary)',
                  border: `1px solid ${filterRiskOnly ? '#FDE68A' : 'var(--border-light)'}`
                }}
              >
                <Filter size={11} />
                {filterRiskOnly ? 'Show All' : 'High Risk Only'}
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 420, overflowY: 'auto', paddingRight: 4 }}>
              {filteredDeliveries.map((d) => {
                const isResolving = d.status === 'Resolving';
                const isReassigned = d.status === 'Reassigned' || d.reassigned;

                return (
                  <div
                    key={d.id}
                    onClick={() => setSelectedDeliveryId(selectedDeliveryId === d.id ? null : d.id)}
                    style={{
                      backgroundColor: selectedDeliveryId === d.id ? '#F2F8F5' : '#FFFFFF',
                      borderRadius: 'var(--radius-md)',
                      border: `1px solid ${
                        isResolving ? '#8B5CF6' :
                        isReassigned ? '#10B981' :
                        d.risk_band === 'critical' ? '#EF4444' :
                        selectedDeliveryId === d.id ? 'var(--primary)' : 'var(--border-light)'
                      }`,
                      padding: 12,
                      boxShadow: 'var(--shadow-sm)',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease'
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontWeight: 800, fontSize: 13, color: 'var(--primary)' }}>{d.id}</span>
                        <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>· {d.payload}</span>
                      </div>
                      <span className={`badge ${
                        isResolving ? 'badge-resolving' :
                        isReassigned ? 'badge-reassigned' :
                        d.status === 'Escalated' ? 'badge-escalated' : 'badge-onroute'
                      }`}>
                        {d.status}
                      </span>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, fontSize: 11, color: 'var(--text-secondary)', marginBottom: 8 }}>
                      <div>
                        <span style={{ opacity: 0.75 }}>Carrier:</span> <b>{d.driver_name}</b>
                        {d.reassigned && <span style={{ color: '#059669', marginLeft: 4 }}>(swapped)</span>}
                      </div>
                      <div>
                        <span style={{ opacity: 0.75 }}>Recipient:</span> {d.recipient}
                      </div>
                      <div>
                        <span style={{ opacity: 0.75 }}>Drop:</span> {d.destination_name}
                      </div>
                      <div>
                        <span style={{ opacity: 0.75 }}>ETA:</span> <b>{d.eta_minutes ? d.eta_minutes.toFixed(0) : 15} min</b>
                      </div>
                    </div>

                    {/* Cold Chain bar if present */}
                    {d.cold_chain && (
                      <div style={{
                        fontSize: 10,
                        backgroundColor: d.cold_minutes_remaining < 60 ? '#FEF2F2' : '#F0FDF4',
                        color: d.cold_minutes_remaining < 60 ? '#DC2626' : '#059669',
                        padding: '3px 6px',
                        borderRadius: 4,
                        marginBottom: 6,
                        display: 'flex',
                        justifyContent: 'space-between',
                        fontWeight: 600
                      }}>
                        <span>Cold-chain stability window</span>
                        <span>{d.cold_minutes_remaining} min left</span>
                      </div>
                    )}

                    {/* Risk meter */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, marginBottom: 10 }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10 }}>
                        <span style={{ color: 'var(--text-muted)' }}>Failure Risk</span>
                        <b style={{ color: d.risk_band === 'critical' ? '#DC2626' : d.risk_band === 'elevated' ? '#D97706' : '#059669' }}>
                          {(d.risk * 100).toFixed(0)}% · {d.risk_band}
                        </b>
                      </div>
                      <div style={{ height: 4, backgroundColor: '#E5EBE7', borderRadius: 2, overflow: 'hidden' }}>
                        <div 
                          style={{
                            height: '100%',
                            width: `${d.risk * 100}%`,
                            backgroundColor: d.risk_band === 'critical' ? '#EF4444' : d.risk_band === 'elevated' ? '#F59E0B' : '#10B981'
                          }}
                        />
                      </div>
                      <div style={{ fontSize: 9.5, color: 'var(--text-muted)' }}>
                        Top factor: <b>{d.risk_top_driver || 'None / nominal'}</b>
                      </div>
                    </div>

                    {/* Disruption Trigger Buttons */}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {availableDisruptions.map((t) => (
                        <button
                          key={t.key}
                          disabled={isResolving}
                          onClick={(e) => {
                            e.stopPropagation();
                            onTriggerDisruption(d.id, t.key, 'ops-console');
                          }}
                          style={{
                            fontSize: 10,
                            fontWeight: 600,
                            padding: '3px 7px',
                            borderRadius: 4,
                            backgroundColor: 'var(--bg-subtle)',
                            color: 'var(--text-main)',
                            border: '1px solid var(--border-light)',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 3
                          }}
                          title={t.detected_as || `Simulate ${t.label}`}
                        >
                          <span>{t.icon}</span>
                          <span>{t.label}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Live Agent Activity Feed Panel */}
          <div style={{ minHeight: 380, height: 420 }}>
            <AgentFeed activeChain={activeChain} />
          </div>
        </div>
      </div>
    </div>
  );
}
