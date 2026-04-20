import { createContext, useContext, useEffect, useState, ReactNode } from "react";

export interface AuthUser {
  id: number;
  username: string;
  role: "admin" | "user";
  max_nicks: number | null;
  is_locked: boolean;
  created_at?: string;
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
}

interface AuthContextValue extends AuthState {
  login: (token: string, user: AuthUser) => void;
  logout: () => void;
  setUser: (user: AuthUser) => void;
}

const STORAGE_KEY = "auth";
const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ token: null, user: null });

  useEffect(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      try { setState(JSON.parse(raw)); }
      catch { localStorage.removeItem(STORAGE_KEY); }
    }
  }, []);

  const login = (token: string, user: AuthUser) => {
    const next = { token, user };
    setState(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  };

  const logout = () => {
    setState({ token: null, user: null });
    localStorage.removeItem(STORAGE_KEY);
  };

  const setUser = (user: AuthUser) => {
    const next = { ...state, user };
    setState(next);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  };

  return (
    <AuthContext.Provider value={{ ...state, login, logout, setUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
