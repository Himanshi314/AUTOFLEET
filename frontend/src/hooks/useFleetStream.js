import { useState, useEffect, useRef, useCallback } from 'react';

export function useFleetStream() {
  const [state, setState] = useState(null);
  const [meta, setMeta] = useState(null);
  const [connected, setConnected] = useState(false);
  const [activeChain, setActiveChain] = useState(null);
  const [logs, setLogs] = useState([]);
  const [terminalLogs, setTerminalLogs] = useState([]);
  const [currentAlert, setCurrentAlert] = useState(null);
  const [pickedDriver, setPickedDriver] = useState(null);
  const [activeIncidentCount, setActiveIncidentCount] = useState(0);
  const [impactSeries, setImpactSeries] = useState([]);

  const eventSourceRef = useRef(null);

  // Initial fetch as backup
  useEffect(() => {
    fetch('/api/state')
      .then(res => res.json())
      .then(data => {
        if (data.state) setState(data.state);
        if (data.meta) setMeta(data.meta);
      })
      .catch(err => {
        console.warn('Initial /api/state fetch error (waiting for SSE)', err);
      });
  }, []);

  // Server-Sent Events setup
  useEffect(() => {
    let es;
    let reconnectTimeout;

    function connect() {
      try {
        es = new EventSource('/api/stream');
        eventSourceRef.current = es;

        es.onopen = () => {
          setConnected(true);
        };

        es.onmessage = (e) => {
          if (!e.data) return;
          try {
            const ev = JSON.parse(e.data);
            handleEvent(ev);
          } catch (err) {
            console.error('Error parsing SSE event', err, e.data);
          }
        };

        es.onerror = () => {
          setConnected(false);
          es.close();
          reconnectTimeout = setTimeout(connect, 3000);
        };
      } catch (e) {
        console.error('SSE connection failed', e);
        reconnectTimeout = setTimeout(connect, 3000);
      }
    }

    connect();

    return () => {
      if (es) es.close();
      if (reconnectTimeout) clearTimeout(reconnectTimeout);
    };
  }, []);

  const handleEvent = useCallback((ev) => {
    const timestamp = new Date().toLocaleTimeString('en-US', { hour12: false });

    // Terminal & system logs
    if (ev.type === 'log') {
      const logEntry = {
        id: Math.random().toString(36).substring(2, 9),
        time: timestamp,
        level: ev.level || 'info',
        msg: ev.msg
      };
      setLogs(prev => [logEntry, ...prev.slice(0, 49)]);
      setTerminalLogs(prev => [...prev.slice(-99), `[${timestamp}] [${(ev.level || 'info').toUpperCase()}] ${ev.msg}`]);
    }

    switch (ev.type) {
      case 'hello':
        if (ev.state) setState(ev.state);
        if (ev.meta) setMeta(ev.meta);
        setConnected(true);
        break;

      case 'telemetry':
      case 'state':
      case 'reset':
        if (ev.state) setState(ev.state);
        if (ev.type === 'reset') {
          setActiveChain(null);
          setCurrentAlert(null);
          setImpactSeries([]);
        }
        break;

      // One point per resolved incident, carrying the ledger's own totals.
      // This is the only time-ordered history the client has: the server keeps
      // totals, not a series, so it is accumulated here as incidents land.
      // Nothing is interpolated or back-filled — an empty demo plots nothing.
      case 'impact':
        if (ev.totals) {
          setImpactSeries(prev => [...prev, {
            n: (ev.totals.incidents_resolved ?? prev.length + 1),
            km: ev.totals.km_avoided ?? 0,
            co2e: ev.totals.co2e_kg_avoided ?? 0,
            minutes: ev.totals.coordinator_minutes_saved ?? 0,
            delivery_id: ev.entry?.delivery_id || '',
          }]);
        }
        break;

      case 'mode':
        if (ev.state) setState(ev.state);
        if (ev.meta) setMeta(ev.meta);
        setActiveChain(null);
        break;

      case 'autonomous':
        setMeta(prev => prev ? { ...prev, autonomous: ev.enabled } : prev);
        break;

      case 'risk_alert':
        setCurrentAlert(ev);
        setTerminalLogs(prev => [
          ...prev.slice(-99),
          `[${timestamp}] [WATCHDOG] Risk threshold crossed for ${ev.delivery_id}: ${(ev.risk * 100).toFixed(0)}% (${ev.band}) -> ${ev.label}`
        ]);
        break;

      // NOTE ON EVENT NAMES: these must match autofleet/agents.py exactly.
      // They did not — this hook listened for incident_start / routing_plan /
      // resolution while the server emits chain_start / plan / resolved. Because
      // the chain was never initialised, every agent_* handler below hit its
      // `if (!prev) return prev` guard and the whole feed silently did nothing.
      // If you add an event server-side, add the case here or it is dropped.
      case 'chain_start':
        setActiveIncidentCount(c => c + 1);
        setActiveChain({
          incident_id: ev.incident_id,
          delivery_id: ev.delivery_id,
          disruption_key: ev.disruption,        // server sends `disruption`
          disruption_label: ev.disruption_label,
          disruption_icon: ev.disruption_icon,
          severity: ev.severity,
          detected_as: ev.detected_as,
          risk_before: ev.risk_before,
          trigger: ev.trigger,
          startTime: Date.now(),
          status: 'running',
          plan: null,
          agents: {},
          skipped: [],
          tools: [],
          toolCall: null,
          verification: null,
          selection: null,
          degraded: false,
          resolution: null,
        });
        setTerminalLogs(prev => [
          ...prev.slice(-99),
          `[${timestamp}] [CHAIN_START] ${ev.incident_id}: ${ev.disruption_label} on ${ev.delivery_id}`
        ]);
        break;

      case 'plan':
        setActiveChain(prev => {
          if (!prev) return prev;
          return {
            ...prev,
            plan: {
              path: ev.path,
              agents: ev.agents,
              total: ev.total,
              saved: ev.saved,
              specs: ev.specs,
              skipped: ev.skipped || [],
              reason: ev.reason
            }
          };
        });
        setTerminalLogs(prev => [
          ...prev.slice(-99),
          `[${timestamp}] [ROUTER] Path: ${ev.path.toUpperCase()} (${ev.agents.length}/${ev.total} roles active, ${ev.saved || 0} saved). Reason: ${ev.reason}`
        ]);
        break;

      case 'agent_start':
        setActiveChain(prev => {
          if (!prev) return prev;
          return {
            ...prev,
            agents: {
              ...prev.agents,
              [ev.agent]: {
                id: ev.agent,
                label: ev.label,
                icon: ev.icon,
                owns: ev.owns,
                text: '',
                status: 'active',
                startTime: Date.now()
              }
            }
          };
        });
        setTerminalLogs(prev => [
          ...prev.slice(-99),
          `[${timestamp}] [AGENT_START] ${ev.label} (${ev.owns})`
        ]);
        break;

      case 'agent_delta':
        setActiveChain(prev => {
          if (!prev || !prev.agents || !prev.agents[ev.agent]) return prev;
          const currentText = prev.agents[ev.agent].text || '';
          return {
            ...prev,
            agents: {
              ...prev.agents,
              [ev.agent]: {
                ...prev.agents[ev.agent],
                text: currentText + ev.text
              }
            }
          };
        });
        break;

      case 'agent_done':
        setActiveChain(prev => {
          if (!prev || !prev.agents || !prev.agents[ev.agent]) return prev;
          return {
            ...prev,
            agents: {
              ...prev.agents,
              [ev.agent]: {
                ...prev.agents[ev.agent],
                text: ev.text,
                status: 'done',
                ms: ev.ms,
                tokens: ev.tokens,
                source: ev.source,
                note: ev.note
              }
            }
          };
        });
        setTerminalLogs(prev => [
          ...prev.slice(-99),
          `[${timestamp}] [AGENT_DONE] ${ev.agent} completed in ${((ev.ms || 0)/1000).toFixed(2)}s (${ev.tokens?.output || 0} tokens, source: ${ev.source})`
        ]);
        break;

      // A role the router chose not to wake. Carries the reason, so the UI can
      // show that skipping was a decision rather than a gap.
      case 'agent_skipped':
        setActiveChain(prev => prev ? {
          ...prev,
          skipped: [...(prev.skipped || []), { id: ev.agent, label: ev.label, icon: ev.icon, owns: ev.owns, reason: ev.reason }]
        } : prev);
        break;

      // Deterministic model output (route alternates, driver ranking). Not the
      // language layer — these are the numbers the agents are handed.
      case 'tool':
        setActiveChain(prev => prev ? {
          ...prev,
          tools: [...(prev.tools || []), { name: ev.name, title: ev.title, detail: ev.detail, result: ev.result }]
        } : prev);
        break;

      // The one binding action in the chain: the reassignment tool call.
      case 'tool_call':
        setActiveChain(prev => prev ? {
          ...prev,
          toolCall: { agent: ev.agent, name: ev.name, input: ev.input, validated: ev.validated }
        } : prev);
        setTerminalLogs(prev => [
          ...prev.slice(-99),
          `[${timestamp}] [TOOL_CALL] ${ev.name}(${ev.input?.driver_id || '-'}) validated=${ev.validated}`
        ]);
        break;

      // Which driver the suitability model picked, and why.
      case 'selection':
        setActiveChain(prev => prev ? { ...prev, selection: ev } : prev);
        // InteractiveMap compares pickedDriver against drv.id, so this must be
        // the driver ID. The old code passed resolution.new_driver, a NAME,
        // which could never match and left the map highlight dead.
        if (ev.driver_id) setPickedDriver(ev.driver_id);
        break;

      // Fact-checker verdict over the numbers the agents stated in prose.
      case 'verification':
        setActiveChain(prev => prev ? { ...prev, verification: ev } : prev);
        setTerminalLogs(prev => [
          ...prev.slice(-99),
          `[${timestamp}] [VERIFY] ${ev.claims_checked} claims checked, ${ev.passed ? 'all traced to model output' : `${ev.unverified?.length || 0} UNVERIFIED`}`
        ]);
        break;

      // Chain budget spent: the resolution still completes, but from
      // deterministic output rather than the language layer.
      case 'degraded':
        setActiveChain(prev => prev ? { ...prev, degraded: true } : prev);
        break;

      case 'resolved':
        setActiveChain(prev => prev ? { ...prev, status: 'resolved', resolution: ev } : prev);
        setActiveIncidentCount(c => Math.max(0, c - 1));
        setTerminalLogs(prev => [
          ...prev.slice(-99),
          // The server sends no `outcome` field — reading ev.outcome.toUpperCase()
          // here used to throw and kill the handler.
          `[${timestamp}] [RESOLVED] ${ev.reassigned ? 'REASSIGNED' : 'RETAINED'} in ${ev.seconds}s: ${ev.summary}`
        ]);
        break;

      // No eligible driver: the system stops and hands the incident to a human
      // rather than inventing a resolution.
      case 'escalated':
        setActiveChain(prev => prev ? { ...prev, status: 'escalated', escalation: ev } : prev);
        setActiveIncidentCount(c => Math.max(0, c - 1));
        setTerminalLogs(prev => [
          ...prev.slice(-99),
          `[${timestamp}] [ESCALATED] ${ev.incident_id}: ${ev.reason || 'handed to a human coordinator'}`
        ]);
        break;

      // World changed under a running chain (mode switch or reset).
      case 'aborted':
        setActiveChain(null);
        setActiveIncidentCount(0);
        break;

      default:
        break;
    }
  }, []);

  // Actions connecting to existing read-only backend
  const triggerDisruption = useCallback(async (deliveryId, disruptionKey, trigger = 'manual') => {
    try {
      const res = await fetch('/api/disrupt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ delivery_id: deliveryId, disruption: disruptionKey, trigger })
      });
      return await res.json();
    } catch (e) {
      console.error('Trigger disruption error', e);
      return { ok: false, error: e.message };
    }
  }, []);

  const switchMode = useCallback(async (mode) => {
    try {
      const res = await fetch('/api/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode })
      });
      return await res.json();
    } catch (e) {
      console.error('Switch mode error', e);
      return { ok: false, error: e.message };
    }
  }, []);

  const setAutonomous = useCallback(async (enabled) => {
    try {
      const res = await fetch('/api/autonomous', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled })
      });
      const data = await res.json();
      if (data.ok) {
        setMeta(prev => prev ? { ...prev, autonomous: enabled } : prev);
      }
      return data;
    } catch (e) {
      console.error('Set autonomous error', e);
      return { ok: false, error: e.message };
    }
  }, []);

  const resetFleet = useCallback(async () => {
    try {
      const res = await fetch('/api/reset', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      setActiveChain(null);
      setCurrentAlert(null);
      setPickedDriver(null);
      return await res.json();
    } catch (e) {
      console.error('Reset fleet error', e);
      return { ok: false, error: e.message };
    }
  }, []);

  return {
    state,
    meta,
    connected,
    activeChain,
    logs,
    terminalLogs,
    currentAlert,
    pickedDriver,
    setPickedDriver,
    triggerDisruption,
    switchMode,
    setAutonomous,
    resetFleet,
    activeIncidentCount,
    impactSeries
  };
}
