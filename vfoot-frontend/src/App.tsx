import { Navigate, Route, Routes } from 'react-router-dom';
import type { ReactElement } from 'react';
import AppShell from './layouts/AppShell';
import DashboardPage from './pages/DashboardPage';
import SquadPage from './pages/SquadPage';
import FormationPage from './pages/FormationPage';
import MatchesPage from './pages/MatchesPage';
import LeagueMatchDetailPage from './pages/LeagueMatchDetailPage';
import CompetitionPage from './pages/CompetitionPage';
import MarketPage from './pages/MarketPage';
import AuctionRoomPage from './pages/AuctionRoomPage';
import LeagueAdminPage from './pages/LeagueAdminPage';
import CompetitionCreatePage from './pages/CompetitionCreatePage';
import CompetitionEditPage from './pages/CompetitionEditPage';
import CompetitionAdvancedPage from './pages/CompetitionAdvancedPage';
import NotFoundPage from './pages/NotFoundPage';
import LandingPage from './pages/LandingPage';
import VerifyEmailPage from './pages/VerifyEmailPage';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import NewPasswordPage from './pages/NewPasswordPage';
import { useAuth } from './auth/AuthContext';
import { LeagueProvider } from './league/LeagueContext';
import { CompetitionProvider } from './league/CompetitionContext';
import ClassificaPage from './pages/ClassificaPage';
import RealChampionshipPage from './pages/RealChampionshipPage';
import RealMatchDetailPage from './pages/RealMatchDetailPage';
import ListonePage from './pages/ListonePage';
import DecisionsPage from './pages/DecisionsPage';
import TeamRosterPage from './pages/TeamRosterPage';
import ProfilePage from './pages/ProfilePage';
import ManagerProfilePage from './pages/ManagerProfilePage';
import MaintenancePage from './pages/MaintenancePage';
import VotoPuroPage from './pages/VotoPuroPage';

function RequireAuth({ children }: { children: ReactElement }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="p-6 text-sm text-ink-faint">Caricamento sessione…</div>;
  if (!user) return <Navigate to="/" replace />;
  return children;
}

/** Chi gestisce il SITO, non una lega: il flag `is_staff` di Django, lo stesso che
 *  apre /admin/. Questo rimando NON è il cancello — le API dietro controllano da
 *  sole e rispondono 403 — ma senza di lui un utente qualunque che digita l'URL si
 *  trova davanti il titolo della pagina e un messaggio d'errore, cioè scopre che
 *  la pagina esiste senza ricavarne niente. Tanto vale non mostrargliela. */
function RequireStaff({ children }: { children: ReactElement }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="p-6 text-sm text-ink-faint">Caricamento sessione…</div>;
  if (!user?.is_staff) return <Navigate to="/home" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/verifica-email" element={<VerifyEmailPage />} />
      <Route path="/recupera-password" element={<ForgotPasswordPage />} />
      <Route path="/nuova-password" element={<NewPasswordPage />} />
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
        <Route path="profilo" element={<ProfilePage />} />
        {/* La scheda pubblica di un fantallenatore. Non sotto /leagues: un albo
            d'oro attraversa i campionati, e la pagina con lui. */}
        <Route path="fantallenatori/:userId" element={<ManagerProfilePage />} />
        {/* "Lega" was a hub of links to pages that already existed; what only it
            had — the round being played, the standings, who is in the league —
            now lives on the home page. Kept as a redirect for bookmarks. */}
        <Route path="league" element={<Navigate to="/home" replace />} />
        <Route path="squad" element={<SquadPage />} />
        <Route path="teams/:teamId" element={<TeamRosterPage />} />
        <Route path="squad/formation" element={<FormationPage />} />
        <Route path="matches" element={<MatchesPage />} />
        <Route path="standings" element={<ClassificaPage />} />
        <Route path="matches/:matchId" element={<LeagueMatchDetailPage />} />
        <Route path="serie-a" element={<RealChampionshipPage />} />
        <Route path="serie-a/:matchId" element={<RealMatchDetailPage />} />
        <Route path="listone" element={<ListonePage />} />
        {/* Pagina di consultazione, non di gioco: spiega da dove viene il voto
            puro. Ci si arriva dal menu e dal dettaglio di un voto nelle pagelle,
            che e' il momento in cui la domanda nasce. */}
        <Route path="voto-puro" element={<VotoPuroPage />} />
        <Route path="competitions/:competitionId" element={<CompetitionPage />} />
        <Route path="market" element={<MarketPage />} />
        <Route path="auction" element={<AuctionRoomPage />} />
        <Route path="decisioni" element={<DecisionsPage />} />
        <Route path="league-admin" element={<LeagueAdminPage />} />
        {/* Manutenzione del sito: riservata a chi lo gestisce, non a chi
            amministra una lega. La rotta esiste per tutti, ma le API dietro
            rispondono 403 a chi non e' staff: nascondere la voce di menu e'
            cortesia, il cancello sta nel backend. */}
        <Route
          path="manutenzione"
          element={
            <RequireStaff>
              <MaintenancePage />
            </RequireStaff>
          }
        />
        <Route path="league-admin/competitions/new" element={<CompetitionCreatePage />} />
        {/* "advanced" before ":competitionId", or the word would be read as an id. */}
        <Route path="league-admin/competitions/advanced" element={<CompetitionAdvancedPage />} />
        <Route path="league-admin/competitions/:competitionId" element={<CompetitionEditPage />} />
      </Route>
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
