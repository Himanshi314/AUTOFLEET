import React, { useMemo, useState } from 'react';
import { Navigation, MapPin, BatteryCharging, AlertTriangle, CheckCircle2 } from 'lucide-react';

function createProjector(bounds, width = 1000, height = 600, padding = 45) {
  if (!bounds) return () => [0, 0];
  const { min_lat, max_lat, min_lon, max_lon } = bounds;
  const dLat = (max_lat - min_lat) || 1e-6;
  const dLon = (max_lon - min_lon) || 1e-6;

  return (lat, lon) => {
    const x = padding + ((lon - min_lon) / dLon) * (width - padding * 2);
    const y = padding + (1 - (lat - min_lat) / dLat) * (height - padding * 2);
    return [x, y];
  };
}

export function InteractiveMap({ 
  mapData, 
  deliveries = [], 
  drivers = [], 
  pickedDriver = null, 
  onSelectDriver = () => {},
  selectedDeliveryId = null
}) {
  const [hoveredDriver, setHoveredDriver] = useState(null);
  const [hoveredNode, setHoveredNode] = useState(null);

  const W = 1000;
  const H = 600;

  const proj = useMemo(() => {
    if (!mapData || !mapData.bounds) return () => [W / 2, H / 2];
    return createProjector(mapData.bounds, W, H, 50);
  }, [mapData]);

  const nodeById = useMemo(() => {
    const dict = {};
    if (mapData && mapData.nodes) {
      mapData.nodes.forEach(n => { dict[n.id] = n; });
    }
    return dict;
  }, [mapData]);

  const carryingDrivers = useMemo(() => {
    return new Set(deliveries.map(d => d.driver_id));
  }, [deliveries]);

  if (!mapData || !mapData.nodes) {
    return (
      <div style={{
        height: 380,
        backgroundColor: '#FFFFFF',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'var(--text-muted)',
        borderRadius: 'var(--radius-lg)'
      }}>
        Loading Bengaluru fleet map corridors...
      </div>
    );
  }

  const downCount = drivers.filter(d => d.status === 'unavailable').length;

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', minHeight: 380, overflow: 'hidden' }}>
      <svg 
        viewBox={`0 0 ${W} ${H}`} 
        preserveAspectRatio="xMidYMid meet" 
        style={{ width: '100%', height: '100%', backgroundColor: '#F8FAF9' }}
      >
        {/* Background Grid Accent */}
        <defs>
          <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
            <path d="M 40 0 L 0 0 0 40" fill="none" stroke="#EDF4F0" strokeWidth="0.8" />
          </pattern>
          <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
            <feGaussianBlur stdDeviation="3" result="blur" />
            <feComposite in="SourceGraphic" in2="blur" operator="over" />
          </filter>
        </defs>
        <rect width={W} height={H} fill="url(#grid)" />

        {/* Roads / Corridors */}
        <g className="roads">
          {mapData.roads?.map((r, i) => {
            const a = nodeById[r.from];
            const b = nodeById[r.to];
            if (!a || !b) return null;
            const [x1, y1] = proj(a.at[0], a.at[1]);
            const [x2, y2] = proj(b.at[0], b.at[1]);
            return (
              <line 
                key={`road-${i}`}
                x1={x1} y1={y1} x2={x2} y2={y2} 
                className="map-road"
              />
            );
          })}
        </g>

        {/* Nodes / Hubs / Depots */}
        <g className="nodes">
          {mapData.nodes?.map((n) => {
            const [x, y] = proj(n.at[0], n.at[1]);
            const isHub = n.kind === 'hub';
            const isPhc = n.kind === 'phc';
            return (
              <g 
                key={`node-${n.id}`} 
                onMouseEnter={() => setHoveredNode(n)}
                onMouseLeave={() => setHoveredNode(null)}
                style={{ cursor: 'pointer' }}
              >
                {isHub ? (
                  <>
                    <rect 
                      x={x - 6} y={y - 6} width={12} height={12} rx={3} 
                      className="map-node-hub"
                    />
                    <text x={x + 10} y={y + 4} className="map-node-label hub">
                      {n.name}
                    </text>
                  </>
                ) : (
                  <>
                    <circle 
                      cx={x} cy={y} r={isPhc ? 4.5 : 3} 
                      className={isPhc ? "map-node-phc" : "map-node-dot"}
                    />
                    <text x={x + 8} y={y + 3.5} className="map-node-label">
                      {n.name}
                    </text>
                  </>
                )}
              </g>
            );
          })}
        </g>

        {/* Active Delivery Routes */}
        <g className="routes">
          {deliveries.map((d) => {
            if (!d.driver_at || !d.destination_at) return null;
            const [dx, dy] = proj(d.driver_at[0], d.driver_at[1]);
            const [ex, ey] = proj(d.destination_at[0], d.destination_at[1]);

            const legs = [[dx, dy]];
            let handoverPt = null;

            if (d.handover_at) {
              const [hx, hy] = proj(d.handover_at[0], d.handover_at[1]);
              legs.push([hx, hy]);
              handoverPt = [hx, hy];
            }

            if (d.reroute && d.reroute.via) {
              const via = nodeById[d.reroute.via];
              if (via) legs.push(proj(via.at[0], via.at[1]));
            }

            legs.push([ex, ey]);
            const pathData = 'M ' + legs.map(([x, y]) => `${x} ${y}`).join(' L ');

            const isReassigned = d.status === 'Reassigned' || d.status === 'Rerouted';
            const isRisk = d.risk_band === 'critical' || d.risk_band === 'elevated';
            const isSelected = selectedDeliveryId === d.id;

            return (
              <g key={`route-${d.id}`}>
                <path 
                  d={pathData} 
                  className={
                    isReassigned ? 'map-route-new' :
                    isRisk ? 'map-route-risk' : 'map-route-live'
                  }
                  style={{
                    strokeWidth: isSelected ? 4 : undefined,
                    opacity: selectedDeliveryId && !isSelected ? 0.4 : 1
                  }}
                />

                {/* Handover Marker */}
                {handoverPt && (
                  <g transform={`translate(${handoverPt[0]}, ${handoverPt[1]})`}>
                    <circle r={6} fill="#10B981" fillOpacity={0.3} />
                    <circle r={3.5} fill="#10B981" stroke="#FFFFFF" strokeWidth={1.5} />
                    <text x={8} y={3} style={{ fontSize: 9, fontWeight: 700, fill: '#059669' }}>
                      Handover
                    </text>
                  </g>
                )}

                {/* Dropoff Destination Pin */}
                <g transform={`translate(${ex}, ${ey})`}>
                  <circle r={4} fill="#EF4444" stroke="#FFFFFF" strokeWidth={1.5} />
                </g>
              </g>
            );
          })}
        </g>

        {/* Driver Positions */}
        <g className="drivers">
          {drivers.map((drv) => {
            if (!drv.at) return null;
            const [x, y] = proj(drv.at[0], drv.at[1]);
            const isUnavailable = drv.status === 'unavailable';
            const isPicked = pickedDriver === drv.id;
            const isCarrying = carryingDrivers.has(drv.id);

            let fillColor = '#10B981';
            let haloColor = 'rgba(16, 185, 129, 0.25)';
            if (isUnavailable) {
              fillColor = '#EF4444';
              haloColor = 'rgba(239, 68, 68, 0.35)';
            } else if (isPicked) {
              fillColor = '#3B82F6';
              haloColor = 'rgba(59, 130, 246, 0.4)';
            } else if (!isCarrying) {
              fillColor = '#64748B';
              haloColor = 'rgba(100, 116, 139, 0.15)';
            }

            return (
              <g 
                key={`drv-${drv.id}`}
                transform={`translate(${x}, ${y})`}
                onClick={() => onSelectDriver(drv)}
                onMouseEnter={() => setHoveredDriver(drv)}
                onMouseLeave={() => setHoveredDriver(null)}
                style={{ cursor: 'pointer' }}
              >
                {/* Outer Glow Halo */}
                {(isCarrying || isUnavailable || isPicked) && (
                  <circle r={10} fill={haloColor} />
                )}
                {/* Inner Body */}
                <circle 
                  r={isCarrying || isPicked ? 5.5 : 4} 
                  fill={fillColor} 
                  stroke="#FFFFFF" 
                  strokeWidth={1.8} 
                />
                
                {/* Driver Name Tag */}
                {(isCarrying || isUnavailable || isPicked) && (
                  <text 
                    x={8} 
                    y={-4} 
                    style={{
                      fontSize: 9.5,
                      fontWeight: 700,
                      fill: isUnavailable ? '#DC2626' : isPicked ? '#2563EB' : 'var(--primary)',
                      textShadow: '0 1px 2px rgba(255,255,255,0.9)'
                    }}
                  >
                    {drv.name.split(' ')[0]}
                  </text>
                )}
              </g>
            );
          })}
        </g>
      </svg>

      {/* Floating Driver Hover Card */}
      {hoveredDriver && (
        <div style={{
          position: 'absolute',
          bottom: 40,
          left: 20,
          backgroundColor: '#FFFFFF',
          padding: '10px 14px',
          borderRadius: 'var(--radius-md)',
          boxShadow: 'var(--shadow-lg)',
          border: '1px solid var(--border-light)',
          fontSize: 12,
          zIndex: 20,
          minWidth: 190
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontWeight: 700, color: 'var(--text-main)' }}>{hoveredDriver.name}</span>
            <span className={`badge ${hoveredDriver.status === 'unavailable' ? 'badge-critical' : 'badge-nominal'}`}>
              {hoveredDriver.status}
            </span>
          </div>
          <div style={{ color: 'var(--text-secondary)', fontSize: 11, display: 'flex', flexDirection: 'column', gap: 2 }}>
            <div>ID: <span className="mono">{hoveredDriver.id}</span></div>
            <div>Vehicle: <b>{hoveredDriver.vehicle || 'EV Two-Wheeler'}</b></div>
            <div>Battery: <b>{hoveredDriver.battery_pct || 82}%</b></div>
            <div>Score: <b>{hoveredDriver.rating || 4.9} ★</b> ({hoveredDriver.completed_count || 14} drops)</div>
          </div>
        </div>
      )}

      {/* Map Legend & Telemetry Foot */}
      <div style={{
        position: 'absolute',
        bottom: 0,
        left: 0,
        right: 0,
        backgroundColor: 'rgba(255, 255, 255, 0.92)',
        backdropFilter: 'blur(4px)',
        borderTop: '1px solid var(--border-light)',
        padding: '6px 16px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        fontSize: 11,
        color: 'var(--text-secondary)'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: '#10B981' }} />
            Carrying ({carryingDrivers.size})
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 6, height: 6, borderRadius: '50%', backgroundColor: '#64748B' }} />
            Standby ({drivers.length - carryingDrivers.size - downCount})
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: '#EF4444' }} />
            Unavailable ({downCount})
          </span>
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
            <span style={{ width: 7, height: 7, borderRadius: 2, backgroundColor: 'var(--primary)' }} />
            Hub / PHC Depot
          </span>
        </div>

        <div className="mono" style={{ fontSize: 10, color: 'var(--text-muted)' }}>
          {mapData.nodes?.length || 0} nodes · {mapData.roads?.length || 0} corridors · real coords × 1.27 circuity
        </div>
      </div>
    </div>
  );
}
