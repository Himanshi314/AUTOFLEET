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

      case 'incident_start':
        setActiveIncidentCount(c => c + 1);
        setActiveChain({
          incident_id: ev.incident_id,
          delivery_id: ev.delivery_id,
          disruption_key: ev.disruption_key,
          disruption_label: ev.disruption_label,
          disruption_icon: ev.disruption_icon,
          detected_as: ev.detected_as,
          risk_before: ev.risk_before,
          trigger: ev.trigger,
          startTime: Date.now(),
          status: 'running',
          plan: null,
          agents: {},
          resolution: null,
        });
        setTerminalLogs(prev => [
          ...prev.slice(-99),
          `[${timestamp}] [INCIDENT_START] ${ev.incident_id}: ${ev.disruption_label} on ${ev.delivery_id}`
        ]);
        break;

      case 'routing_plan':
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

      case 'resolution':
        setActiveChain(prev => {
          if (!prev) return prev;
          return {
            ...prev,
            status: 'resolved',
            resolution: ev
          };
        });
        if (ev.new_driver) {
          setPickedDriver(ev.new_driver);
        }
        setTerminalLogs(prev => [
          ...prev.slice(-99),
          `[${timestamp}] [RESOLUTION] ${ev.outcome.toUpperCase()}: ${ev.summary}`
        ]);
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
    activeIncidentCount
  };
}
