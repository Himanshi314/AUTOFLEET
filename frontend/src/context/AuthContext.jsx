import React, { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext(null);

export const DEMO_USERS = {
  courier: {
    role: 'courier',
    name: 'Suresh Kumar',
    email: 'suresh@autofleet.ai',
    phone: '+91 98765 43210',
    driverId: 'DRV-BLR-04',
    vehicle: 'Ather 450X (EV)',
    hub: 'Indiranagar Hub',
    rating: 4.9,
    completedToday: 12,
    earningsToday: 860,
    online: true,
  },
  company: {
    role: 'company',
    name: 'Delhivery Operations Desk',
    email: 'ops@delhivery.com',
    companyName: 'Delhivery Logistics Ltd.',
    fleetSize: 1420,
    activeHubs: 8,
  },
  admin: {
    role: 'admin',
    name: 'Root Controller',
    email: 'admin@autofleet.ai',
    accessLevel: 'SuperAdmin',
    engineVersion: 'AutoFleet-v1.4-production',
  }
};

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      const saved = localStorage.getItem('autofleet_auth');
      if (saved) {
        return JSON.parse(saved);
      }
    } catch (e) {
      console.error('Error parsing auth state', e);
    }
    // Default to company view for instant access or null for portal selector
    return DEMO_USERS.company;
  });

  const [notification, setNotification] = useState(null);

  useEffect(() => {
    if (user) {
      localStorage.setItem('autofleet_auth', JSON.stringify(user));
    } else {
      localStorage.removeItem('autofleet_auth');
    }
  }, [user]);

  const login = (role, credentials = {}) => {
    const base = DEMO_USERS[role] || DEMO_USERS.company;
    const loggedUser = {
      ...base,
      email: credentials.email || base.email,
      name: credentials.name || base.name,
      driverId: credentials.driverId || base.driverId,
      phone: credentials.phone || base.phone,
    };
    setUser(loggedUser);
    return loggedUser;
  };

  const register = (role, data) => {
    const newUser = {
      ...(DEMO_USERS[role] || {}),
      ...data,
      role,
    };
    setUser(newUser);
    return newUser;
  };

  const logout = () => {
    setUser(null);
  };

  const switchRole = (role) => {
    if (DEMO_USERS[role]) {
      setUser(DEMO_USERS[role]);
    }
  };

  return (
    <AuthContext.Provider value={{
      user,
      login,
      register,
      logout,
      switchRole,
      notification,
      setNotification,
      isAuthenticated: !!user,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
