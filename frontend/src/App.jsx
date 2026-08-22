import React, { useState, useEffect } from 'react';
import { AuthProvider, useAuth } from './context/AuthContext';
import { useFleetStream } from './hooks/useFleetStream';
import { Navbar } from './components/Navbar';
import { AssumptionsModal } from './components/AssumptionsModal';
import { PortalGateway } from './views/PortalGateway';
import { CourierDashboard } from './views/CourierDashboard';
import { CompanyDashboard } from './views/CompanyDashboard';
import { AdminDashboard } from './views/AdminDashboard';
import { AuthView } from './views/AuthViews';

function AppContent() {
  const { user } = useAuth();
  const [route, setRoute] = useState(() => {
    const hash = window.location.hash.replace(/^#/, '');
    if (hash) return hash;
    const path = window.location.pathname;
    if (path.length > 1) return path;
    return '/company/dashboard'; // Default to operational fleet dashboard
  });

  const [assumptionsOpen, setAssumptionsOpen] = useState(false);

  const {
    state: fleetState,
    meta: fleetMeta,
    connected,
    activeChain,
    terminalLogs,
    currentAlert,
    pickedDriver,
    setPickedDriver,
    triggerDisruption,
    switchMode,
    setAutonomous,
    resetFleet,
    impactSeries
  } = useFleetStream();

  // Keep route synced with browser history and hash
  useEffect(() => {
    const handlePopState = () => {
      const hash = window.location.hash.replace(/^#/, '');
      if (hash) setRoute(hash);
      else setRoute(window.location.pathname || '/');
    };
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  const navigate = (newRoute) => {
    setRoute(newRoute);
    window.location.hash = newRoute;
  };

  const currentMode = fleetState?.mode || 'commercial';
  const isAutonomous = fleetMeta?.autonomous || false;

  const handleModeChange = (mode) => {
    switchMode(mode);
  };

  const handleAutonomousToggle = () => {
    setAutonomous(!isAutonomous);
  };

  const handleReset = () => {
    if (window.confirm("Reset all fleet deliveries, driver statuses, and active disruption incidents?")) {
      resetFleet();
    }
  };

  // Render view based on route
  const renderView = () => {
    // Portal / Gateway
    if (route === '/' || route === '/portal') {
      return <PortalGateway onNavigate={navigate} />;
    }

    // Courier Routes
    if (route === '/courier/dashboard') {
      return (
        <CourierDashboard 
          fleetState={fleetState} 
          onTriggerDisruption={triggerDisruption} 
          activeChain={activeChain} 
        />
      );
    }
    if (route === '/courier/login') {
      return <AuthView role="courier" onNavigate={navigate} />;
    }

    // Company / Operations Routes
    if (route === '/company/dashboard') {
      return (
        <CompanyDashboard
          fleetState={fleetState}
          fleetMeta={fleetMeta}
          impactSeries={impactSeries}
          onTriggerDisruption={triggerDisruption}
          activeChain={activeChain}
          pickedDriver={pickedDriver}
          setPickedDriver={setPickedDriver}
        />
      );
    }
    if (route === '/company/login') {
      return <AuthView role="company" onNavigate={navigate} />;
    }

    // Admin Routes
    if (route === '/admin/dashboard') {
      return (
        <AdminDashboard 
          fleetState={fleetState}
          fleetMeta={fleetMeta}
          terminalLogs={terminalLogs}
          onTriggerDisruption={triggerDisruption}
          onReset={handleReset}
          autonomous={isAutonomous}
          onAutonomousToggle={handleAutonomousToggle}
          activeChain={activeChain}
        />
      );
    }
    if (route === '/admin/login') {
      return <AuthView role="admin" onNavigate={navigate} />;
    }

    if (route === '/login') {
      return <AuthView role={user?.role || 'company'} onNavigate={navigate} />;
    }

    // Default fallback to company dashboard
    return (
      <CompanyDashboard 
        fleetState={fleetState}
        fleetMeta={fleetMeta}
        impactSeries={impactSeries}
        onTriggerDisruption={triggerDisruption}
        activeChain={activeChain}
        pickedDriver={pickedDriver}
        setPickedDriver={setPickedDriver}
      />
    );
  };

  return (
    <div style={{ minHeight: '100vh', display: 'flex', flexDirection: 'column', backgroundColor: 'var(--bg-page)' }}>
      {/* Global Navigation Bar */}
      <Navbar 
        mode={currentMode}
        onModeChange={handleModeChange}
        autonomous={isAutonomous}
        onAutonomousToggle={handleAutonomousToggle}
        onReset={handleReset}
        onOpenAssumptions={() => setAssumptionsOpen(true)}
        connected={connected}
        currentRoute={route}
        onNavigate={navigate}
      />

      {/* Main Viewport */}
      <main style={{ flex: 1 }}>
        {renderView()}
      </main>

      {/* Transparency Assumptions & Scientific Models Modal */}
      <AssumptionsModal 
        isOpen={assumptionsOpen}
        onClose={() => setAssumptionsOpen(false)}
        meta={fleetMeta}
      />
    </div>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}
