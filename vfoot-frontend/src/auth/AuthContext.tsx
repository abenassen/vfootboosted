import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { getCurrentUser, hasStoredSession, login as apiLogin, logout as apiLogout, register as apiRegister } from '../api';
import type {
  AuthUser,
  LoginRequest,
  RegisterRequest,
  RegisterResponse,
} from '../types/auth';

type AuthContextValue = {
  user: AuthUser | null;
  loading: boolean;
  login: (req: LoginRequest) => Promise<void>;
  /** Resolves with the backend's message; does NOT sign the user in. */
  register: (req: RegisterRequest) => Promise<RegisterResponse>;
  logout: () => Promise<void>;
  /** Re-read the session from the stored token — used after email confirmation
   *  or a Google sign-in, which obtain a token outside of login(). */
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function bootstrap() {
      if (!hasStoredSession()) {
        setLoading(false);
        return;
      }
      try {
        const u = await getCurrentUser();
        setUser(u);
      } catch {
        setUser(null);
      } finally {
        setLoading(false);
      }
    }
    void bootstrap();
  }, []);

  const login = useCallback(async (req: LoginRequest) => {
    const res = await apiLogin(req);
    setUser(res.user);
  }, []);

  const register = useCallback(async (req: RegisterRequest) => {
    // Intentionally no setUser: the account stays unusable until the emailed
    // link is opened, so pretending to be logged in here would be a lie.
    return apiRegister(req);
  }, []);

  const refresh = useCallback(async () => {
    if (!hasStoredSession()) {
      setUser(null);
      return;
    }
    try {
      setUser(await getCurrentUser());
    } catch {
      setUser(null);
    }
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setUser(null);
  }, []);

  const value = useMemo(
    () => ({
      user,
      loading,
      login,
      register,
      logout,
      refresh,
    }),
    [login, loading, logout, refresh, register, user]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
