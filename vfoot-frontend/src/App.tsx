import { Navigate, Route, Routes } from 'react-router-dom';
import { useCallback, useState, type ReactElement } from 'react';
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
import JoinLeaguePage from './pages/JoinLeaguePage';
import { useAuth } from './auth/AuthContext';
import { LeagueProvider } from './league/LeagueContext';
import { CompetitionProvider } from './league/CompetitionContext';
import { ChampionshipProvider } from './league/ChampionshipContext';
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
import CountdownPage, { isLaunched, rememberBypass, wantsBypass } from './pages/CountdownPage';

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

/** LA PORTA D'INGRESSO, finché il sito non è annunciato: prima dell'ora
 *  dell'apertura chi arriva senza sessione trova il conto alla rovescia, dopo
 *  trova la pagina di benvenuto di sempre. Il passaggio non ha bisogno di un
 *  deploy — è l'orologio a farlo, e la pagina stessa si fa da parte allo
 *  scoccare dell'ora.
 *
 *  È l'UNICO punto tappato, di proposito: le API rispondono come sempre, un
 *  link d'invito porta ancora alla lega che aspetta, e chi è già dentro non
 *  incontra mai il cartello. Passata l'apertura si può togliere questa funzione
 *  e cancellare CountdownPage: la rotta torna a essere una riga. */
function PublicEntry() {
  const { user, loading } = useAuth();
  const [open, setOpen] = useState(() => isLaunched() || wantsBypass());
  const reveal = useCallback(() => {
    rememberBypass();
    setOpen(true);
  }, []);

  if (open) return <LandingPage />;
  // La sessione si legge in locale quando non c'è (nessuna chiamata), quindi
  // questa attesa riguarda solo chi è già registrato: meglio un istante di
  // fondo scuro che un lampo di conto alla rovescia prima della sua home.
  if (loading) return <div className="min-h-screen bg-[#04120b]" />;
  if (user) return <LandingPage />;
  return <CountdownPage onOpen={reveal} />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<PublicEntry />} />
      <Route path="/verifica-email" element={<VerifyEmailPage />} />
      <Route path="/recupera-password" element={<ForgotPasswordPage />} />
      <Route path="/nuova-password" element={<NewPasswordPage />} />
      {/* FUORI da RequireAuth: un invito lo apre anche chi non ha un account, e
          l'indirizzo è quello che il backend pubblica già come `invite_link`. */}
      <Route path="/join/:code" element={<JoinLeaguePage />} />
      <Route
        element={
          <RequireAuth>
            <LeagueProvider>
              <CompetitionProvider>
                {/* Dentro le leghe perché la stagione da guardare la dice la lega
                    quando ce n'è una — e quando non ce n'è, è questo a dirla. */}
                <ChampionshipProvider>
                  <AppShell />
                </ChampionshipProvider>
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
