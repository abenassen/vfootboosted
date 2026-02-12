import { Navigate, Route, Routes } from 'react-router-dom';
import AppShell from './layouts/AppShell';
import DashboardPage from './pages/DashboardPage';
import LeaguePage from './pages/LeaguePage';
import SquadPage from './pages/SquadPage';
import FormationPage from './pages/FormationPage';
import MatchesPage from './pages/MatchesPage';
import MatchDetailPage from './pages/MatchDetailPage';
import MarketPage from './pages/MarketPage';
import NotFoundPage from './pages/NotFoundPage';

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}
        path="/">
        <Route index element={<Navigate to="/home" replace />} />
        <Route path="home" element={<DashboardPage />} />
        <Route path="league" element={<LeaguePage />} />
        <Route path="squad" element={<SquadPage />} />
        <Route path="squad/formation" element={<FormationPage />} />
        <Route path="matches" element={<MatchesPage />} />
        <Route path="matches/:matchId" element={<MatchDetailPage />} />
        <Route path="market" element={<MarketPage />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
