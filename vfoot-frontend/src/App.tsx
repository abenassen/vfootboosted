import { Navigate, Route, Routes } from 'react-router-dom';
import type { ReactElement } from 'react';
import AppShell from './layouts/AppShell';
import DashboardPage from './pages/DashboardPage';
import LeaguePage from './pages/LeaguePage';
import SquadPage from './pages/SquadPage';
import FormationPage from './pages/FormationPage';
import MatchesPage from './pages/MatchesPage';
import LeagueMatchDetailPage from './pages/LeagueMatchDetailPage';
import CompetitionPage from './pages/CompetitionPage';
import MarketPage from './pages/MarketPage';
import LeagueAdminPage from './pages/LeagueAdminPage';
import CompetitionCreatePage from './pages/CompetitionCreatePage';
import NotFoundPage from './pages/NotFoundPage';
import LandingPage from './pages/LandingPage';
import VerifyEmailPage from './pages/VerifyEmailPage';
import { useAuth } from './auth/AuthContext';
import { LeagueProvider } from './league/LeagueContext';
import { CompetitionProvider } from './league/CompetitionContext';
import ClassificaPage from './pages/ClassificaPage';
import RealChampionshipPage from './pages/RealChampionshipPage';
import RealMatchDetailPage from './pages/RealMatchDetailPage';
import ListonePage from './pages/ListonePage';
import DecisionsPage from './pages/DecisionsPage';
import TeamRosterPage from './pages/TeamRosterPage';

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
      <Route path="/verifica-email" element={<VerifyEmailPage />} />
      <Route
        element={
          <RequireAuth>
            <LeagueProvider>
              <CompetitionProvider>
                <AppShell />
              </CompetitionProvider>
            </LeagueProvider>
          </RequireAuth>
        }
      >
        <Route path="home" element={<DashboardPage />} />
        <Route path="league" element={<LeaguePage />} />
        <Route path="squad" element={<SquadPage />} />
        <Route path="teams/:teamId" element={<TeamRosterPage />} />
        <Route path="squad/formation" element={<FormationPage />} />
        <Route path="matches" element={<MatchesPage />} />
        <Route path="standings" element={<ClassificaPage />} />
        <Route path="matches/:matchId" element={<LeagueMatchDetailPage />} />
        <Route path="serie-a" element={<RealChampionshipPage />} />
        <Route path="serie-a/:matchId" element={<RealMatchDetailPage />} />
        <Route path="listone" element={<ListonePage />} />
        <Route path="competitions/:competitionId" element={<CompetitionPage />} />
        <Route path="market" element={<MarketPage />} />
        <Route path="decisioni" element={<DecisionsPage />} />
        <Route path="league-admin" element={<LeagueAdminPage />} />
        <Route path="league-admin/competitions/new" element={<CompetitionCreatePage />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
