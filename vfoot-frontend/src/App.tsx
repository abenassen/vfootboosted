import { Navigate, Route, Routes } from 'react-router-dom';
import type { ReactElement } from 'react';
import AppShell from './layouts/AppShell';
import DashboardPage from './pages/DashboardPage';
import LeaguePage from './pages/LeaguePage';
import SquadPage from './pages/SquadPage';
import FormationPage from './pages/FormationPage';
import MatchesPage from './pages/MatchesPage';
import MatchDetailPage from './pages/MatchDetailPage';
import MarketPage from './pages/MarketPage';
import LeagueAdminPage from './pages/LeagueAdminPage';
import NotFoundPage from './pages/NotFoundPage';
import LandingPage from './pages/LandingPage';
import { useAuth } from './auth/AuthContext';

function RequireAuth({ children }: { children: ReactElement }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="p-6 text-sm text-slate-500">Caricamento sessione…</div>;
  if (!user) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route path="home" element={<DashboardPage />} />
        <Route path="league" element={<LeaguePage />} />
        <Route path="squad" element={<SquadPage />} />
        <Route path="squad/formation" element={<FormationPage />} />
        <Route path="matches" element={<MatchesPage />} />
        <Route path="matches/:matchId" element={<MatchDetailPage />} />
        <Route path="market" element={<MarketPage />} />
        <Route path="league-admin" element={<LeagueAdminPage />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
