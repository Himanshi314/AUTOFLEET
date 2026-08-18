import React, { useState, useMemo } from 'react';
import { useAuth } from '../context/AuthContext';
import { InteractiveMap } from '../components/InteractiveMap';
import { 
  Truck, 
  MapPin, 
  Clock, 
  AlertTriangle, 
  CheckCircle2, 
  PhoneCall, 
  ShieldCheck, 
  IndianRupee, 
  Navigation, 
  BatteryCharging, 
  HelpCircle,
  ThermometerSnowflake,
  Send,
  Zap
} from 'lucide-react';

export function CourierDashboard({ fleetState, onTriggerDisruption, activeChain }) {
  const { user } = useAuth();
  const [selectedDisruption, setSelectedDisruption] = useState(null);
  const [reportingModalOpen, setReportingModalOpen] = useState(false);
  const [actionSuccess, setActionSuccess] = useState(null);

  // Find deliveries associated with this courier or default to first active
  const activeDelivery = useMemo(() => {
    if (!fleetState || !fleetState.deliveries || fleetState.deliveries.length === 0) return null;
    const match = fleetState.deliveries.find(d => 
      d.driver_id === user?.driverId || 
      d.driver_name?.toLowerCase().includes('suresh') ||
      d.original_driver_id === user?.driverId
    );
    return match || fleetState.deliveries[0];
  }, [fleetState, user]);

  const courierDriver = useMemo(() => {
    if (!fleetState || !fleetState.drivers) return null;
    return fleetState.drivers.find(d => 
      d.id === user?.driverId || 
      d.name?.toLowerCase().includes('suresh')
    ) || fleetState.drivers[0];
  }, [fleetState, user]);

  const handleReportDisruption = async (disruptionKey) => {
    if (!activeDelivery) return;
    setReportingModalOpen(false);
    setActionSuccess(`Reporting ${disruptionKey.replace(/_/g, ' ')}...`);
    const res = await onTriggerDisruption(activeDelivery.id, disruptionKey, 'courier-mobile-app');
    if (res && res.ok) {
      setActionSuccess(`Disruption reported! Multi-agent resolution initiated.`);
      setTimeout(() => setActionSuccess(null), 5000);
    }
  };

  const handleConfirmHandover = () => {
    setActionSuccess('Handover confirmed! Payload transferred safely.');
    setTimeout(() => setActionSuccess(null), 4000);
  };

  const isReassigned = activeDelivery?.status === 'Reassigned' || activeDelivery?.reassigned;
  const isResolving = activeDelivery?.status === 'Resolving';

  return (
    <div style={{ maxWidth: 1280, margin: '0 auto', padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Top Welcome & Driver Status Banner */}
      <div style={{
        backgroundColor: '#FFFFFF',
        borderRadius: 'var(--radius-lg)',
        padding: '18px 24px',
        border: '1px solid var(--border-light)',
        boxShadow: 'var(--shadow-sm)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: 16
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <div style={{
            width: 48,
            height: 48,
            borderRadius: '50%',
            backgroundColor: 'var(--accent-light)',
            color: 'var(--primary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 20,
            fontWeight: 800,
            border: '2px solid var(--accent-border)'
          }}>
            {user?.name?.charAt(0) || 'S'}
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <h2 style={{ fontSize: 20, fontWeight: 800, color: 'var(--text-main)' }}>
                Good evening, {user?.name || 'Suresh'}
              </h2>
              <span className="badge badge-nominal" style={{ padding: '3px 10px' }}>
                <span className="pulse-dot" style={{ width: 6, height: 6 }} />
                Online &amp; Active
              </span>
            </div>
            <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 2 }}>
              ID: <span className="mono font-semibold">{user?.driverId || 'DRV-BLR-04'}</span> · Vehicle: <b>{courierDriver?.vehicle || user?.vehicle || 'Ather 450X EV'}</b> · Hub: <b>{user?.hub || 'Indiranagar Hub'}</b>
            </p>
          </div>
        </div>

        {/* Quick Driver Stats Pill */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 16,
          backgroundColor: 'var(--bg-subtle)',
          padding: '8px 16px',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border-light)'
        }}>
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 600 }}>TODAY'S SHIFT</div>
            <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--primary)' }}>
              {user?.completedToday || 12} <small style={{ fontSize: 10, fontWeight: 500 }}>drops</small>
            </div>
          </div>
          <div style={{ width: 1, height: 26, backgroundColor: 'var(--border-light)' }} />
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 600 }}>EARNINGS</div>
            <div style={{ fontSize: 16, fontWeight: 800, color: '#059669' }}>
              ₹{user?.earningsToday || 860}
            </div>
          </div>
          <div style={{ width: 1, height: 26, backgroundColor: 'var(--border-light)' }} />
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', fontWeight: 600 }}>RATING</div>
            <div style={{ fontSize: 16, fontWeight: 800, color: '#D97706' }}>
              ★ {user?.rating || 4.9}
            </div>
          </div>
        </div>
      </div>

      {/* Safety & Disruption Alert Banner */}
      {isReassigned && (
        <div style={{
          backgroundColor: '#EFF6FF',
          border: '1px solid #BFDBFE',
          borderRadius: 'var(--radius-md)',
          padding: '14px 20px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 12,
          animation: 'fadeIn 0.3s ease'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{
              width: 36,
              height: 36,
              borderRadius: '50%',
              backgroundColor: '#DBEAFE',
              color: '#2563EB',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0
            }}>
              <ShieldCheck size={20} />
            </div>
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#1E40AF' }}>
                Automated Exception Handled · Roadside Assistance Dispatched
              </div>
              <div style={{ fontSize: 12, color: '#3B82F6' }}>
                Delivery reassigned to replacement driver. Your trip earnings are 100% protected and roadside support is en route to your coordinates.
              </div>
            </div>
          </div>
          <button 
            onClick={() => alert("Roadside Assistance Team: +91 80 4567 8900\nETA: 6 minutes to your location.")}
            className="btn-primary" 
            style={{ backgroundColor: '#2563EB', padding: '8px 14px', fontSize: 12 }}
          >
            <PhoneCall size={14} />
            Call Roadside Assist
          </button>
        </div>
      )}

      {actionSuccess && (
        <div style={{
          backgroundColor: '#ECFDF5',
          border: '1px solid #A7F3D0',
          color: '#065F46',
          padding: '12px 18px',
          borderRadius: 'var(--radius-md)',
          fontSize: 13,
          fontWeight: 600,
          display: 'flex',
          alignItems: 'center',
          gap: 8
        }}>
          <CheckCircle2 size={16} />
          {actionSuccess}
        </div>
      )}

      {/* Main Grid: Active Order on Left, Map & Actions on Right */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))', gap: 20 }}>
        {/* Active Order Card */}
        <div className="card" style={{ padding: 22, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Truck size={20} color="var(--primary)" />
              <span style={{ fontSize: 16, fontWeight: 800, color: 'var(--primary)' }}>
                {activeDelivery?.id || 'Order D-103'}
              </span>
            </div>
            <span className={`badge ${
              activeDelivery?.status === 'Resolving' ? 'badge-resolving' :
              activeDelivery?.status === 'Reassigned' ? 'badge-reassigned' :
              activeDelivery?.status === 'Escalated' ? 'badge-escalated' : 'badge-onroute'
            }`}>
              {activeDelivery?.status || 'On Route'}
            </span>
          </div>

          <div style={{
            backgroundColor: 'var(--bg-subtle)',
            padding: 14,
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border-light)',
            display: 'flex',
            flexDirection: 'column',
            gap: 10
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>Payload</span>
              <span style={{ fontWeight: 700, color: 'var(--text-main)' }}>{activeDelivery?.payload || 'Emergency Medical Consignment'}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>Recipient / Facility</span>
              <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>{activeDelivery?.recipient || 'Manipal Hospital Care Center'}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>Destination</span>
              <span style={{ fontWeight: 600, color: 'var(--text-main)' }}>{activeDelivery?.destination_name || 'Old Airport Road, Kodihalli'}</span>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
              <span style={{ color: 'var(--text-secondary)' }}>Estimated ETA</span>
              <span style={{ fontWeight: 800, color: '#059669' }}>
                {activeDelivery?.eta_minutes ? `${activeDelivery.eta_minutes.toFixed(0)} min` : '18 min'}
              </span>
            </div>

            {/* Cold Chain Indicator if applicable */}
            {activeDelivery?.cold_chain && (
              <div style={{
                marginTop: 4,
                padding: '8px 10px',
                borderRadius: 6,
                backgroundColor: activeDelivery.cold_minutes_remaining < 60 ? '#FEF2F2' : '#F0FDF4',
                border: `1px solid ${activeDelivery.cold_minutes_remaining < 60 ? '#FECACA' : '#BBF7D0'}`,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                fontSize: 12
              }}>
                <span style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#065F46', fontWeight: 600 }}>
                  <ThermometerSnowflake size={14} color="#059669" />
                  Cold-Chain Window
                </span>
                <b className="mono" style={{ color: activeDelivery.cold_minutes_remaining < 60 ? '#DC2626' : '#059669' }}>
                  {activeDelivery.cold_minutes_remaining} min remaining
                </b>
              </div>
            )}
          </div>

          {/* Failure Risk Indicator */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
              <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>Telemetry Failure Risk</span>
              <span className={`badge ${
                activeDelivery?.risk_band === 'critical' ? 'badge-critical' :
                activeDelivery?.risk_band === 'elevated' ? 'badge-elevated' : 'badge-nominal'
              }`}>
                {activeDelivery?.risk ? `${(activeDelivery.risk * 100).toFixed(0)}% (${activeDelivery.risk_band})` : '14% (nominal)'}
              </span>
            </div>
            <div style={{ height: 6, backgroundColor: '#E2ECE7', borderRadius: 3, overflow: 'hidden' }}>
              <div 
                style={{
                  height: '100%',
                  width: `${activeDelivery?.risk ? (activeDelivery.risk * 100) : 14}%`,
                  backgroundColor: activeDelivery?.risk_band === 'critical' ? '#EF4444' : activeDelivery?.risk_band === 'elevated' ? '#F59E0B' : '#10B981',
                  transition: 'width 0.4s ease'
                }}
              />
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              Dominant telemetry factor: <b>{activeDelivery?.risk_top_driver || 'None / Stable'}</b>
            </div>
          </div>

          {/* Action Buttons for Courier */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 'auto' }}>
            {isReassigned ? (
              <button 
                onClick={handleConfirmHandover}
                className="btn-primary" 
                style={{ padding: 12, fontSize: 14, backgroundColor: '#059669' }}
              >
                <CheckCircle2 size={16} />
                Confirm Payload Handover to Replacement Driver
              </button>
            ) : (
              <button 
                onClick={handleConfirmHandover}
                className="btn-primary" 
                style={{ padding: 12, fontSize: 14 }}
              >
                <CheckCircle2 size={16} />
                Confirm Successful Drop-Off
              </button>
            )}

            <button
              onClick={() => setReportingModalOpen(true)}
              disabled={isResolving}
              className="btn-secondary"
              style={{
                padding: 11,
                fontSize: 13,
                borderColor: '#FCD34D',
                backgroundColor: '#FFFBEB',
                color: '#B45309'
              }}
            >
              <AlertTriangle size={15} />
              {isResolving ? 'Resolving Disruption via Multi-Agent Chain...' : 'Report Disruption / Roadside Help'}
            </button>
          </div>
        </div>

        {/* Live Route Map Card */}
        <div className="card" style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12, minHeight: 420 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <Navigation size={18} color="var(--primary)" />
              <h3 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-main)' }}>
                Live GPS Navigation &amp; Fleet Corridors
              </h3>
            </div>
            <span className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
              Bengaluru South
            </span>
          </div>

          <div style={{ flex: 1, minHeight: 340, borderRadius: 'var(--radius-md)', overflow: 'hidden', border: '1px solid var(--border-light)' }}>
            <InteractiveMap 
              mapData={fleetState?.map} 
              deliveries={fleetState?.deliveries || []}
              drivers={fleetState?.drivers || []}
              selectedDeliveryId={activeDelivery?.id}
            />
          </div>
        </div>
      </div>

      {/* Disruption Reporting Modal */}
      {reportingModalOpen && (
        <div style={{
          position: 'fixed',
          inset: 0,
          backgroundColor: 'rgba(0,0,0,0.5)',
          backdropFilter: 'blur(2px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 120,
          padding: 20
        }}>
          <div className="card" style={{ maxWidth: 500, width: '100%', padding: 24, animation: 'fadeIn 0.2s ease' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <AlertTriangle size={20} color="#D97706" />
                <h3 style={{ fontSize: 17, fontWeight: 800, color: 'var(--primary)' }}>
                  Report Disruption on {activeDelivery?.id}
                </h3>
              </div>
              <button onClick={() => setReportingModalOpen(false)} style={{ fontSize: 18, color: 'var(--text-muted)' }}>✕</button>
            </div>

            <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 16 }}>
              Select the exception you are experiencing. The AutoFleet AI multi-agent chain will immediately assign the nearest optimal standby driver, notify the recipient, and dispatch roadside assistance.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {[
                { key: 'bike_breakdown', label: 'Vehicle Breakdown / Puncture', icon: '🛵', desc: 'Bike dead, cannot proceed with delivery' },
                { key: 'customer_not_home', label: 'Customer Not Available / Gate Locked', icon: '🚪', desc: 'Attempted drop but recipient absent' },
                { key: 'wrong_address', label: 'Incorrect / Incomplete Address', icon: '📍', desc: 'Location does not match GPS pin' },
                { key: 'traffic_gridlock', label: 'Severe Traffic Gridlock', icon: '🚗', desc: 'Corridor impassable, ETA delayed >25 min' },
                { key: 'cold_chain_breach', label: 'Cold-Chain Unit Temperature Spike', icon: '❄️', desc: 'Cooling box temperature rising rapidly' }
              ].map((item) => (
                <button
                  key={item.key}
                  onClick={() => handleReportDisruption(item.key)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '12px 16px',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid var(--border-light)',
                    backgroundColor: 'var(--bg-card)',
                    textAlign: 'left',
                    transition: 'all 0.15s ease'
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'var(--bg-subtle)'; e.currentTarget.style.borderColor = 'var(--accent)'; }}
                  onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'var(--bg-card)'; e.currentTarget.style.borderColor = 'var(--border-light)'; }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span style={{ fontSize: 22 }}>{item.icon}</span>
                    <div>
                      <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-main)' }}>{item.label}</div>
                      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{item.desc}</div>
                    </div>
                  </div>
                  <Zap size={15} color="var(--accent-dark)" />
                </button>
              ))}
            </div>

            <button
              onClick={() => setReportingModalOpen(false)}
              className="btn-secondary"
              style={{ width: '100%', marginTop: 16, padding: 10 }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
