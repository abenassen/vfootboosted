import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import clsx from 'clsx';
import { useEffect, useMemo, useState } from 'react';
// Un'icona per voce, e ognuna dice la SUA voce: la maglia per le rose, il podio
// per la classifica, l'urna per le decisioni. Le emoji le disegnano tre sistemi
// operativi diversi, quindi la stessa barra aveva tre stili e tre spessori.
import {
  ArrowLeftRight, BarChart3, BookOpen, CalendarDays, CircleDot, ClipboardCheck, ClipboardList,
  Check, ChevronDown, Home, LayoutGrid, LogOut, MoreHorizontal, Settings, Shirt, UserRound, Vote, X,
  type LucideIcon,
} from 'lucide-react';
import type { CompetitionItem } from '../types/league';
import LeagueSwitcher from '../components/LeagueSwitcher';
import CompetitionSwitcher from '../components/CompetitionSwitcher';
import { useAuth } from '../auth/AuthContext';
import { Button } from '../components/ui';
import logo from '../assets/logo.png';
import Avatar from '../components/Avatar';
import Crest from '../components/Crest';
import { useLeagueContext } from '../league/LeagueContext';
import { useCompetitionContext } from '../league/CompetitionContext';
import { compColor } from '../league/competitionColors';
import { useDecisionAlerts } from '../league/useDecisionAlerts';
import { PageErrorBoundary } from '../components/PageErrorBoundary';
import UpdateBanner from '../components/UpdateBanner';

// League-scoped navigation (left sidebar + mobile bar): everything here is about
// the CURRENTLY selected league. User-level actions (Le mie leghe) and switching
// between leagues live in the top bar instead.
// scope: 'competition' pages refer to the CURRENT competition (they follow the
// competition switcher) and get an indigo accent; 'league' pages are global.
type NavItem = {
  to: string;
  label: string;
  icon: LucideIcon;
  scope: 'league' | 'competition';
  badge?: number;
  /** Marks the entry that has work waiting on it — a dot, where a badge would
   *  have to invent a number the shell does not know. */
  flag?: boolean;
  /** Not part of running the league: drawn below a separator. */
  aside?: boolean;
  /** Si accende SOLO sul suo indirizzo esatto. Serve a «Rose», che ha la
   *  formazione annidata sotto di sé (`/squad/formation`): senza, aprire la
   *  formazione accendeva due voci del menu, la sua e quella della pagina che le
   *  presta il pezzo di indirizzo. */
  exact?: boolean;
};

const HOME_ITEM: NavItem = { to: '/home', label: 'Home lega', icon: Home, scope: 'league' };

const leagueNav: NavItem[] = [
  // "Rose" and not "Squadra": the page opens on your own, but the strip at the
  // top browses every roster in the league, so the plural is what it does.
  { to: '/squad', label: 'Rose', icon: Shirt, scope: 'league', exact: true },
  { to: '/listone', label: 'Listone', icon: ClipboardList, scope: 'league' },
  { to: '/market', label: 'Mercato', icon: ArrowLeftRight, scope: 'league' },
  { to: '/decisioni', label: 'Decisioni', icon: Vote, scope: 'league' },
  { to: '/league-admin?tab=league', label: 'Gestione lega', icon: Settings, scope: 'league' },
  // Last, and after a separator: the real championship is what the league is
  // played ON, not a page you need to run it. Everything above is the league.
  { to: '/serie-a', label: 'Serie A', icon: CircleDot, scope: 'league', aside: true },
  // E qui sotto la pagina che spiega da dove vengono i voti: si consulta una
  // volta e non si torna, per cui sta fra le voci di lato e non fra quelle con
  // cui si gioca. NON «Come si vota»: faceva credere che a votare fossero gli
  // utenti, che e' proprio il contrario di quel che la pagina racconta.
  { to: '/voto-puro', label: 'Voto spiegato', icon: BookOpen, scope: 'league', aside: true },
];

/** LE PAGINE CHE UNA COMPETIZIONE PORTA CON SÉ — e sono diverse a seconda di
 *  com'è fatta, per cui il selettore della competizione non sceglie soltanto dei
 *  dati: cambia il menu.
 *
 *  Un campionato produce due cose distinte, un calendario che si legge una
 *  giornata alla volta e una tabella che le riassume tutte. Una coppa secca no:
 *  il suo tabellone È il suo calendario — sette partite, tutte insieme, già in
 *  ordine di turno — e tenere due voci significava mandare nello stesso posto
 *  con due nomi. Gironi più playoff tornano a due, perché lì le tabelle dei
 *  gironi esistono davvero e non stanno nel calendario.
 *
 *  `result_view` lo decide già il server leggendo i tipi delle fasi (vedi
 *  `_result_view` in league_views.py): qui non si indovina niente. */
function competitionNav(c: CompetitionItem | null): NavItem[] {
  if (!c) return [];
  // La formazione la si schiera PER una competizione — la pagina ha un proprio
  // menu per sceglierla e una casella «manda questa a tutte» — quindi sta nel
  // gruppo colorato con le altre, non fra le pagine di lega. Prima nel gruppo
  // perché è quella che si apre più spesso.
  const formation: NavItem = {
    to: '/squad/formation', label: 'Formazione', icon: ClipboardCheck, scope: 'competition',
  };
  const calendar: NavItem = { to: '/matches', label: 'Calendario', icon: CalendarDays, scope: 'competition' };
  switch (c.result_view) {
    case 'tabellone':
      return [formation, { to: '/standings', label: 'Tabellone', icon: LayoutGrid, scope: 'competition' }];
    case 'risultati':
      return [formation, calendar, { to: '/standings', label: 'Risultati', icon: LayoutGrid, scope: 'competition' }];
    default:
      return [formation, calendar, { to: '/standings', label: 'Classifica', icon: BarChart3, scope: 'competition' }];
  }
}

/** Quante voci stanno nella barra del telefono prima di «Altro». Cinque slot
 *  fissi, e fissi vuol dire che il quinto è SEMPRE «Altro»: una barra che scorre
 *  nasconde metà di sé senza dirlo, e nessuno scorre un menu che non sa di poter
 *  scorrere. */
const MOBILE_SLOTS = 4;
/** Altezza della fila di slot, in pixel. Serve in tre posti che devono
 *  concordare — la barra, lo spazio che le si lascia sotto al contenuto e il
 *  foglio che le si appoggia sopra — e finché era scritta a mano in classi
 *  Tailwind i tre numeri non erano lo stesso numero (`pb-20` = 80px contro una
 *  barra alta 63). */
const MOBILE_BAR_H = 60;
/** E l'altezza della striscia delle competizioni, quando c'è. Sta sopra gli slot
 *  dentro lo stesso blocco fisso, quindi entra nello stesso conto: senza, il
 *  foglio «Altro» si appoggiava a sessanta pixel e le chip gli mangiavano
 *  l'ultima riga (il Logout finiva sotto). */
const MOBILE_CHIPS_H = 40;

const USER_ADMIN_TO = '/league-admin?tab=user';

// Someone in NO league gets no league menu at all. Every entry of leagueNav needs
// a selected league to show anything — /serie-a and /listone included, because
// both are scoped to the league's reference season — so for a brand-new account
// the whole menu is ten links that all answer "Seleziona una lega". What is left
// is enough: the logo goes home, "Le mie leghe" is in the bar, and Home itself
// carries the create/join call to action.

function usePageTitle(pathname: string) {
  return useMemo(() => {
    if (pathname.startsWith('/home')) return 'Home lega';
    if (pathname.startsWith('/profilo')) return 'Profilo';
    // Resolved by the caller, which can see the tab in the query string: the same
    // route is "Le mie leghe" or "Gestione lega" depending on it, and a single
    // word for both ("Amministrazione") matched neither the menu nor the page.
    if (pathname.startsWith('/league-admin')) return '';
    if (pathname.startsWith('/league')) return 'Lega';
    if (pathname.startsWith('/squad/formation')) return 'Formazione';
    if (pathname.startsWith('/squad')) return 'Rose';
    if (pathname.startsWith('/matches/')) return 'Match';
    // «Calendario» e non «Partite»: è la parola che la home usa già per mandare
    // qui ("Calendario →" sotto ogni competizione), ed è quella giusta per tutte
    // e tre le forme — turni di campionato, turni di coppa, giornate dei gironi.
    if (pathname.startsWith('/matches')) return 'Calendario';
    if (pathname.startsWith('/standings')) return 'Classifica';
    if (pathname.startsWith('/serie-a/')) return 'Partita Serie A';
    if (pathname.startsWith('/serie-a')) return 'Serie A';
    if (pathname.startsWith('/listone')) return 'Listone';
    if (pathname.startsWith('/market')) return 'Mercato';
    if (pathname.startsWith('/decisioni')) return 'Decisioni';
    // Mancava, e la sala d'asta si intestava «Vfoot»: il ripiego pensato per una
    // pagina senza nome, su una pagina che ce l'ha scritto in mezzo allo schermo.
    if (pathname.startsWith('/auction')) return 'Asta';
    return 'Vfoot';
  }, [pathname]);
}

// league-admin links are query-sensitive (tab=user vs tab=league); other links
// use the default NavLink matching. Returns undefined => use NavLink default.
function leagueAdminActive(search: string, pathname: string, to: string): boolean | undefined {
  if (!to.startsWith('/league-admin')) return undefined;
  if (!pathname.startsWith('/league-admin')) return false;
  const wantUser = to.includes('tab=user');
  const haveUser = search.includes('tab=user');
  return wantUser ? haveUser : !haveUser;
}

export default function AppShell() {
  const location = useLocation();
  const navigate = useNavigate();
  const { user, logout } = useAuth();
  const { selectedLeague, selectedLeagueId, leagues, setSelectedLeagueId, loading: leaguesLoading } = useLeagueContext();
  const {
    competitions,
    selectedCompetitionId,
    selectedCompetition,
    setSelectedCompetitionId,
    loading: competitionsLoading,
  } = useCompetitionContext();
  const activeTeamName = selectedLeague?.team_name?.trim() || null;
  // the current competition's accent colour (distinct per competition in the league)
  const color = compColor(competitions.findIndex((c) => c.competition_id === selectedCompetitionId));
  // Pending league decisions: shown on the Decisioni entry so nobody has to go
  // looking for a question that was addressed to them.
  const alerts = useDecisionAlerts(selectedLeague?.league_id ?? null);

  // The "results" page (and its menu entry/title) adapts to the current competition:
  // a round-robin shows a standings table → "Classifica"; a knockout shows a bracket
  // → "Tabellone". (Mixed group+KO competitions will show both, labelled "Tabellone".)
  const resultView = selectedCompetition?.result_view ?? 'classifica';
  const standingsLabel =
    resultView === 'tabellone' ? 'Tabellone' : resultView === 'risultati' ? 'Risultati' : 'Classifica';
  // The real reference-championship name comes from the league's competition entity
  // (year-independent, e.g. "Serie A"); the season/year lives on the page badge.
  // Falls back to "Serie A" only when the league has no reference season yet.
  const refCompetition = selectedLeague?.reference_season?.competition ?? 'Serie A';
  const hasLeagues = leagues.length > 0;
  // A league with no competition is still being set up. Not the same case as
  // having no league at all — Serie A, Listone and Squadra work perfectly well
  // here, so blanking the menu would take away pages that do something. What is
  // actually wrong is narrower: two entries cannot show anything without a
  // calendar, and the page that HAS the pending work is the tenth of ten, behind
  // a horizontal scroll on a phone.
  const leagueInSetup = hasLeagues && !competitionsLoading && competitions.length === 0;

  // Gestione lega is admin-only: the page itself already refuses everyone else,
  // so leaving it in the menu offered every participant a door to a "serve il
  // ruolo admin".
  const isLeagueAdmin = selectedLeague?.role === 'admin';

  // Le voci che la competizione corrente porta con sé: una o due, mai fisse.
  const compNav = useMemo(
    () => (leagueInSetup ? [] : competitionNav(selectedCompetition)),
    [selectedCompetition, leagueInSetup],
  );

  const nav = useMemo<NavItem[]>(() => {
    const league = leagueNav
      .filter((it) => isLeagueAdmin || !it.to.startsWith('/league-admin'))
      .map((it): NavItem => {
        if (it.to === '/serie-a') return { ...it, label: refCompetition };
        // One number per audience, and they must not be mixed: the admin's is his
        // whole sign-off queue, the member's is only what he was asked. Falling back
        // from one to the other made 17 pending sign-offs read as 1 the moment the
        // admin opened a single consultation.
        if (it.to === '/decisioni')
          return { ...it, badge: alerts.isAdmin ? alerts.blocking : alerts.attention };
        return it;
      });

    if (leagueInSetup) {
      // Niente competizioni: niente calendario e niente formazione da schierare.
      // Straight after Home, flagged: Gestione lega is the only place where the
      // league can be moved forward, and it should not have to be hunted for.
      const adminIndex = league.findIndex((it) => it.to.startsWith('/league-admin'));
      if (adminIndex < 0) return [HOME_ITEM, ...league];
      const admin: NavItem = { ...league[adminIndex], flag: true };
      return [HOME_ITEM, admin, ...league.filter((_, i) => i !== adminIndex)];
    }

    // L'ORDINE È LA BARRA DEL TELEFONO: i primi quattro sono gli slot fissi, il
    // resto finisce nel foglio «Altro». Home, la formazione, e poi quello che la
    // competizione scelta mette a disposizione — che è appunto il punto in cui il
    // selettore della competizione si vede cambiare il menu sotto le dita.
    return [HOME_ITEM, ...compNav, ...league];
  }, [compNav, refCompetition, alerts, leagueInSetup, isLeagueAdmin]);
  // Also empty WHILE LOADING, not just when the list comes back empty: drawing the
  // menu optimistically would flash ten dead links at exactly the brand-new
  // account we are trying to spare them from.
  const visibleNav = leaguesLoading || !hasLeagues ? [] : nav;

  // I CINQUE SLOT. I primi quattro dalla lista, il quinto è «Altro» e apre il
  // resto verso l'alto. Le voci che restano fuori non spariscono e soprattutto
  // non si portano dietro un numero che nessuno vede: il loro totale finisce
  // ADDOSSO ad «Altro» — era esattamente il caso di «Decisioni», che è l'unica
  // voce con un contatore ed era la settima di nove, fuori dallo schermo.
  // Chi non è in nessuna lega non ha voci di lega, e la barra spariva del tutto —
  // e con lei «Altro», che è dove stanno il profilo e il Logout. Da telefono, un
  // account appena creato non aveva NESSUN modo di uscire. Due voci bastano: la
  // home, dov'è l'invito a crearne una, e le proprie leghe.
  const barItems = (visibleNav.length
    ? visibleNav
    : [HOME_ITEM, { to: USER_ADMIN_TO, label: 'Le mie leghe', icon: LayoutGrid, scope: 'league' as const }]
  ).slice(0, MOBILE_SLOTS);
  const sheetItems = visibleNav.slice(MOBILE_SLOTS);
  const sheetBadge = sheetItems.reduce((n, it) => n + (it.badge ?? 0), 0);
  const sheetFlag = sheetItems.some((it) => it.flag);

  const [moreOpen, setMoreOpen] = useState(false);
  const [leagueOpen, setLeagueOpen] = useState(false);
  // Si chiude da sola quando si arriva da qualche parte: un foglio che sopravvive
  // alla navigazione copre la pagina che hai appena chiesto.
  useEffect(() => {
    setMoreOpen(false);
    setLeagueOpen(false);
  }, [location.pathname, location.search]);
  const anySheet = moreOpen || leagueOpen;
  useEffect(() => {
    if (!anySheet) return;
    function onKey(e: KeyboardEvent) {
      if (e.key !== 'Escape') return;
      setMoreOpen(false);
      setLeagueOpen(false);
    }
    document.addEventListener('keydown', onKey);
    // Niente scroll dietro al foglio: il dito che manca il bersaglio deve trovare
    // il foglio, non far scorrere la pagina sotto.
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
    };
  }, [anySheet]);

  const baseTitle = usePageTitle(location.pathname);
  const title = location.pathname.startsWith('/standings')
    ? standingsLabel
    : location.pathname.startsWith('/serie-a/')
      ? `Partita ${refCompetition}`
      : location.pathname.startsWith('/serie-a')
        ? refCompetition
        : baseTitle;

  // La pagina si apre sulla scheda «Le mie leghe», quindi e' l'indirizzo a dover
  // dire quando NON e' quella. Prima chiedeva il contrario (tab=user esplicito),
  // e un /league-admin nudo — la voce di menu, il ritorno dalla creazione di una
  // lega — si intestava «Gestione lega» sopra l'elenco delle leghe.
  const adminTab = new URLSearchParams(location.search).get('tab') ?? '';
  const isUserAdmin =
    location.pathname.startsWith('/league-admin') &&
    !['league', 'roster', 'competitions', 'matchdays', 'auction', 'market'].includes(adminTab);
  // Le pagine sotto /league-admin/competitions non sono nessuna delle due
  // schede: hanno un nome loro, ed e' quello scritto in cima alla pagina.
  const competitionEditor = location.pathname.startsWith('/league-admin/competitions/')
    ? location.pathname.endsWith('/new')
      ? 'Nuova competizione'
      : location.pathname.endsWith('/advanced')
        ? 'Costruzione avanzata'
        : 'Modifica competizione'
    : null;
  // Only the mobile header shows a page title (no sidebar there to say where you
  // are). It has to match the words used in the menu and on the page itself.
  const mobileTitle = competitionEditor
    ? competitionEditor
    : location.pathname.startsWith('/league-admin')
    ? isUserAdmin
      ? 'Le mie leghe'
      : 'Gestione lega'
    : // Chi non è in nessuna lega vedeva «Home lega» sopra un invito a crearne
      // una: il titolo nominava la cosa che ancora non esiste.
      location.pathname.startsWith('/home') && !selectedLeague
      ? 'Vfoot'
      : title;

  const navItemClass = (active: boolean, scope: 'league' | 'competition') =>
    clsx(
      'flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-semibold',
      active
        ? scope === 'competition'
          ? `${color.bg700} text-white shadow-card`
          : 'bg-brand text-on-brand shadow-card'
        : scope === 'competition'
          ? `${color.text700} ${color.hover50}`
          : 'text-ink-soft hover:bg-surface-2'
    );

  function renderNav(item: NavItem) {
    const manual = leagueAdminActive(location.search, location.pathname, item.to);
    const content = (
      <>
        <item.icon size={18} strokeWidth={1.9} aria-hidden />
        {item.label}
        {item.badge ? (
          <span className="ml-auto rounded-full bg-warn px-1.5 py-0.5 text-[10px] font-bold text-white">
            {item.badge}
          </span>
        ) : item.flag ? (
          <span
            className="ml-auto h-2 w-2 rounded-full bg-warn"
            title="Ci sono passi da completare"
            aria-label="Ci sono passi da completare"
          />
        ) : null}
      </>
    );
    if (manual === undefined) {
      return (
        <NavLink key={item.to} to={item.to} end={item.exact} className={({ isActive }) => navItemClass(isActive, item.scope)}>
          {content}
        </NavLink>
      );
    }
    return (
      <Link key={item.to} to={item.to} className={navItemClass(manual, item.scope)}>
        {content}
      </Link>
    );
  }

  const isCompetitionPage =
    location.pathname.startsWith('/matches') ||
    location.pathname.startsWith('/standings') ||
    location.pathname.startsWith('/squad/formation');

  /** Cambiare competizione può togliere di mezzo la pagina che stai guardando.
   *  Dal campionato — calendario e classifica — a una coppa secca, che ha il solo
   *  tabellone, il `/matches` che hai sotto gli occhi smette di appartenere alla
   *  competizione scelta: resterebbe lì a mostrare il calendario di prima sotto un
   *  nome nuovo. Ti si porta sulla prima pagina che la nuova competizione ha
   *  davvero. */
  // Le pastiglie ci sono solo dove servono: su una pagina di competizione, e solo
  // se c'è più di una competizione fra cui scegliere. Tutto il blocco fisso in
  // basso è alto quanto questo, e tre punti devono saperlo — gli slot, lo spazio
  // sotto al contenuto, il foglio che ci si appoggia.
  const showCompetitionChips = isCompetitionPage && competitions.length > 1;
  const mobileBarBlock = MOBILE_BAR_H + (showCompetitionChips ? MOBILE_CHIPS_H : 0);

  /** Cambiare lega cambia tutto quello che c'è sotto — rose, listone, mercato,
   *  e soprattutto QUALI competizioni esistono. Le pagine di competizione della
   *  lega vecchia non hanno un equivalente in quella nuova, quindi da lì si
   *  torna a casa; dalle pagine di lega si resta dove si è, che è la stessa
   *  domanda posta a un'altra lega. */
  const chooseLeague = (leagueId: number) => {
    setSelectedLeagueId(leagueId);
    setLeagueOpen(false);
    if (isCompetitionPage) navigate('/home');
  };

  const chooseCompetition = (c: CompetitionItem) => {
    setSelectedCompetitionId(c.competition_id);
    const next = competitionNav(c);
    if (!isCompetitionPage || !next.length) return;
    // La formazione è l'unica che tiene la competizione nell'indirizzo, e da lì
    // la rimette nel contesto: cambiarla solo nel contesto verrebbe annullato
    // dalla pagina stessa un istante dopo. Si riparte senza giornata, così
    // ricade su quella da schierare PER QUESTA competizione.
    if (location.pathname.startsWith('/squad/formation')) {
      navigate(`/squad/formation?competition=${c.competition_id}`);
      return;
    }
    if (next.some((it) => location.pathname.startsWith(it.to))) return;
    navigate(next[0].to);
  };

  return (
    <div className="min-h-screen bg-paper text-ink">
      <UpdateBanner />
      {/* Desktop top bar — cross-league: switcher + user admin + account */}
      <div className="vf-hero hidden border-b border-black/10 md:block">
        <div className="mx-auto max-w-7xl px-4 py-3 flex items-center justify-between">
          {/* Logo + wordmark are the way home, as everywhere else on the web —
              so Home needs no menu entry of its own. No page title beside it:
              the page already titles itself, and the two disagreed (this bar said
              "Amministrazione" where the menu entry and the page both said
              "Gestione lega"). */}
          <Link to="/home" className="flex items-center gap-3 rounded-lg hover:opacity-80" aria-label="Vai alla home">
            <img src={logo} alt="Vfoot logo" className="h-11 w-11 rounded-xl bg-surface object-cover p-0.5 shadow-sm" />
            <div className="font-cond text-2xl font-bold uppercase leading-none tracking-wide">Vfoot Boosted</div>
          </Link>

          <div className="flex items-center gap-3">
            {/* League context, in the order it is read: which league, which
                competition inside it, which team is yours in it. */}
            {hasLeagues ? (
              <div className="flex items-end gap-2">
                <label className="flex flex-col gap-0.5">
                  <span className="px-1 font-cond text-[11px] font-bold uppercase tracking-wide text-white/75">Lega</span>
                  <LeagueSwitcher />
                </label>
                {competitions.length ? (
                  <label className="flex flex-col gap-0.5">
                    <span className="px-1 font-cond text-[11px] font-bold uppercase tracking-wide text-white/75">Competizione</span>
                    <CompetitionSwitcher />
                  </label>
                ) : null}
              </div>
            ) : null}

            {/* The team is a separate target from the account below: it belongs to
                ONE league and changes with the switcher, and it leads to the page
                where it can actually be renamed. */}
            {hasLeagues ? (
              <Link
                to="/squad"
                className={clsx(
                  'flex items-center gap-2 rounded-xl px-2 py-1',
                  location.pathname.startsWith('/squad') ? 'bg-black/30' : 'hover:bg-surface/15',
                )}
                title="La tua squadra in questa lega"
              >
                <Crest descriptor={selectedLeague?.team_crest} teamName={activeTeamName} size={30} />
                <div className="text-left text-xs leading-tight">
                  <div className={'text-white/70'}>
                    Squadra
                  </div>
                  <div
                    className={clsx(
                      'font-semibold',
                      'text-white',
                      !activeTeamName && 'italic font-normal text-white/60',
                    )}
                  >
                    {activeTeamName ?? 'non impostata'}
                  </div>
                </div>
              </Link>
            ) : null}

            <Link
              to={USER_ADMIN_TO}
              className={clsx(
                'flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-semibold',
                isUserAdmin ? 'bg-black/30 text-white' : 'text-white/85 hover:bg-surface/15'
              )}
            >
              <span>🗂️</span> Le mie leghe
            </Link>

            {/* Solo per chi gestisce il sito. Nascondere la voce e' cortesia:
                le API dietro rispondono 403 a chiunque non sia staff, quindi un
                client che mentisse su questo flag troverebbe una pagina muta. */}
            {user?.is_staff && (
              <Link
                to="/manutenzione"
                className={clsx(
                  'flex items-center gap-1 rounded-xl px-2 py-1 text-sm',
                  location.pathname.startsWith('/manutenzione') ? 'bg-black/30' : 'hover:bg-surface/15',
                )}
                title="Manutenzione del sito"
              >
                <span>🩺</span> Manutenzione
              </Link>
            )}

            <div className="h-8 w-px bg-surface/25" aria-hidden />

            <Link
              to="/profilo"
              className={clsx(
                'flex items-center gap-2 rounded-xl px-2 py-1',
                location.pathname.startsWith('/profilo') ? 'bg-black/30' : 'hover:bg-surface/15',
              )}
              title="Il tuo profilo"
            >
              <Avatar descriptor={user?.avatar} username={user?.username} size={30} />
              <div className="text-left text-xs leading-tight">
                <div className={'text-white/70'}>
                  Fantallenatore
                </div>
                <div
                  className={clsx(
                    'font-semibold',
                    'text-white',
                  )}
                >
                  {user?.username ?? 'Utente'}
                </div>
              </div>
            </Link>
            <Button size="sm" variant="secondary" onClick={() => void logout()}>
              Logout
            </Button>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-7xl md:grid md:grid-cols-[240px_1fr] md:gap-6">
        {/* Desktop sidebar — current league only */}
        <aside className="hidden md:block sticky top-0 self-start h-[calc(100vh-57px)] overflow-auto px-4 py-6">
          <div className="px-1 pb-2 font-cond text-xs font-bold uppercase tracking-wide text-ink-faint">
            {selectedLeague?.name ?? 'Nessuna lega'}
          </div>
          {/* The two competition-scoped entries follow the switcher, and until now
              only their COLOUR said so — you had to know the palette to know which
              competition Partite and Classifica were about. Now they sit under a
              heading that names it. */}
          <nav className="space-y-1">
            {visibleNav
              .filter((it) => !it.aside && it.scope !== 'competition')
              .map(renderNav)}
          </nav>
          {selectedCompetition && visibleNav.some((it) => it.scope === 'competition') ? (
            <div className={clsx('mt-3 rounded-xl border-l-4 py-2 pl-2', color.border600, color.tint)}>
              <div className={clsx('flex items-center gap-1.5 px-1 pb-1 text-[10px] font-bold uppercase tracking-wide', color.text700)}>
                <span className={clsx('h-2 w-2 rounded-full', color.dot)} aria-hidden />
                <span className="truncate">{selectedCompetition.name}</span>
              </div>
              <nav className="space-y-1">
                {visibleNav.filter((it) => it.scope === 'competition').map(renderNav)}
              </nav>
            </div>
          ) : null}
          {visibleNav.some((it) => it.aside) ? (
            <nav className="mt-3 space-y-1 border-t pt-3">
              {visibleNav.filter((it) => it.aside).map(renderNav)}
            </nav>
          ) : null}

          {/* No "active league" card here: name and role are already in the top
              bar, where they can also be CHANGED. Only the empty state needs a
              word, since then the sidebar links lead nowhere useful. */}
          {!selectedLeague && !leaguesLoading ? (
            hasLeagues ? (
              <div className="mt-6 rounded-2xl border border-line bg-surface shadow-card p-4 text-xs text-ink-faint">
                Seleziona una lega dal menu in alto.
              </div>
            ) : (
              <Link
                to={USER_ADMIN_TO}
                className="mt-6 block rounded-2xl bg-brand p-4 text-center text-sm font-bold text-on-brand shadow-card hover:bg-brand-strong"
              >
                Crea o unisciti a una lega
              </Link>
            )
          ) : null}
        </aside>

        {/* Main */}
        <main className="md:pb-8 px-4 py-4 md:py-6">
          {/* MOBILE HEADER. Tre bersagli e basta: il logo che va a casa, la riga
              che dice dove sei e in che lega — ed è da lì che la lega si cambia —
              e la faccia, che porta al profilo.

              Prima erano sei, ammucchiati: 🗂️ + avatar + Logout schiacciati
              nell'angolo destro (l'avatar si comprimeva perché era l'unico
              elastico dei tre), e sotto una scheda da centoquarantasette pixel
              con due menu a tendina. Il Logout è finito in «Altro» — è la cosa
              che si fa meno di tutte e stava accanto a quelle che si fanno di
              più — e la scheda non c'è: il nome della lega lo scriveva già questa
              riga, e adesso quella riga È il modo di cambiarla. */}
          <div className="md:hidden mb-3 flex items-center justify-between gap-2">
            <div className="flex min-w-0 items-center gap-2">
              <Link to="/home" aria-label="Vai alla home" className="shrink-0">
                <img src={logo} alt="Vfoot logo" className="h-8 w-8 rounded-lg object-cover" />
              </Link>
              <div className="min-w-0">
                <div className="truncate font-bold text-lg leading-tight">{mobileTitle}</div>
                {/* IL SELETTORE DELLA LEGA, e stavolta seleziona davvero.
                    Prima era un link a «Le mie leghe» con una freccia in fondo:
                    la freccia prometteva una tendina, il dito otteneva una
                    pagina, e l'unico modo di cambiare lega di là era un
                    bottoncino «Gestisci» che poi scaricava in Gestione lega. Ora
                    apre l'elenco delle leghe, con lo stemma grande abbastanza da
                    riconoscerlo; creare, entrare e gestire restano di là, in
                    fondo al foglio. */}
                {hasLeagues ? (
                  <button
                    type="button"
                    onClick={() => setLeagueOpen((o) => !o)}
                    aria-expanded={leagueOpen}
                    aria-label="Cambia lega"
                    className={clsx(
                      'mt-0.5 flex max-w-full items-center gap-1.5 rounded-lg py-0.5 pr-1 text-[11px] leading-tight',
                      leagueOpen ? 'text-brand-strong' : 'text-ink-faint',
                    )}
                  >
                    {selectedLeague ? (
                      <Crest
                        descriptor={selectedLeague.team_crest}
                        teamName={activeTeamName}
                        size={22}
                        className={activeTeamName ? undefined : 'opacity-40'}
                      />
                    ) : null}
                    <span className="truncate">
                      {selectedLeague
                        ? `${selectedLeague.name} · ${activeTeamName ?? 'squadra non impostata'}`
                        : 'Seleziona una lega'}
                    </span>
                    {/* Una freccia che si vede. Il carattere «▾» al sessanta per
                        cento di opacità, in coda a una riga di undici pixel già
                        smorta, non si leggeva come un comando — e questa riga è
                        l'unico modo di cambiare lega. Su un fondo suo, con un
                        bordo, e che gira quando il foglio è aperto. */}
                    <span
                      aria-hidden
                      className={clsx(
                        'flex h-5 w-5 shrink-0 items-center justify-center rounded-md border transition-transform',
                        leagueOpen
                          ? 'rotate-180 border-brand bg-brand text-on-brand'
                          : 'border-line bg-surface-2 text-ink-soft',
                      )}
                    >
                      <ChevronDown size={14} strokeWidth={2.75} />
                    </span>
                  </button>
                ) : null}
              </div>
            </div>
            {/* shrink-0: era l'unico elemento comprimibile della fila e la fila era
                troppo piena, per cui l'avatar veniva schiacciato in una scheggia. */}
            <Link
              to="/profilo"
              aria-label="Profilo"
              className={clsx(
                'shrink-0 rounded-full',
                location.pathname.startsWith('/profilo') ? 'ring-2 ring-brand ring-offset-1' : '',
              )}
            >
              <Avatar descriptor={user?.avatar} username={user?.username} size={34} />
            </Link>
          </div>

          {/* Keyed on the route: a boundary that has caught STAYS caught, so
              without this the card would follow you onto pages that work. */}
          <PageErrorBoundary key={location.pathname}>
            <Outlet />
          </PageErrorBoundary>

          {/* Lo spazio esatto della barra fissa, striscia delle competizioni e
              safe area comprese. `viewport-fit=cover` è dichiarato dall'inizio ma
              nessuno leggeva mai `env(safe-area-inset-bottom)`: in app installata
              su un telefono con la barra del gesto, le etichette finivano sotto
              l'indicatore di casa. */}
          {/* Senza condizioni, come la barra: ora c'è sempre, e quello che le
              finisce sotto resta illeggibile allo stesso modo. */}
          <div
            className="md:hidden"
            aria-hidden
            style={{
              height: `calc(env(safe-area-inset-bottom, 0px) + ${mobileBarBlock + 16}px)`,
            }}
          />
        </main>
      </div>

      {/* IL FOGLIO DELLE LEGHE. Lo apre la riga che nomina la lega corrente, che
          è il posto da cui uno si aspetta di cambiarla. Non duplica «Le mie
          leghe»: là si creano, ci si entra con un codice e si amministrano —
          cose lunghe, che vogliono una pagina — qui si sceglie soltanto, che è
          la cosa veloce e va fatta col pollice. */}
      {leagueOpen ? (
        <div className="md:hidden fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Cambia lega">
          <button
            type="button"
            aria-label="Chiudi"
            className="absolute inset-0 bg-ink/40"
            onClick={() => setLeagueOpen(false)}
          />
          <div
            className="absolute inset-x-0 bottom-0 max-h-[80vh] overflow-y-auto rounded-t-3xl border-t border-line bg-surface shadow-lift"
            style={{ paddingBottom: `calc(env(safe-area-inset-bottom, 0px) + ${mobileBarBlock}px)` }}
          >
            <div className="sticky top-0 flex items-center justify-between bg-surface px-4 pt-3">
              <span className="font-cond text-xs font-bold uppercase tracking-wide text-ink-faint">Le tue leghe</span>
              <button
                type="button"
                onClick={() => setLeagueOpen(false)}
                aria-label="Chiudi"
                className="rounded-lg p-1.5 text-ink-faint hover:bg-surface-2"
              >
                <X size={18} strokeWidth={2} aria-hidden />
              </button>
            </div>
            <div className="space-y-1.5 px-3 pb-3 pt-2">
              {leagues.map((l) => {
                const sel = l.league_id === selectedLeagueId;
                const team = l.team_name?.trim() || null;
                return (
                  <button
                    key={l.league_id}
                    type="button"
                    onClick={() => chooseLeague(l.league_id)}
                    aria-pressed={sel}
                    className={clsx(
                      'flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left',
                      sel ? 'border-brand bg-brand/12' : 'border-line bg-surface-2',
                    )}
                  >
                    {/* Trentadue pixel: lo stemma è come si riconosce la propria
                        squadra a colpo d'occhio, e a quattordici non lo si
                        riconosceva affatto. */}
                    <Crest descriptor={l.team_crest} teamName={team} size={32} className={team ? undefined : 'opacity-40'} />
                    <span className="min-w-0 flex-1">
                      <span className={clsx('block truncate text-sm font-semibold', sel ? 'text-brand-strong' : 'text-ink')}>
                        {l.name}
                      </span>
                      <span className="block truncate text-xs text-ink-faint">
                        {team ?? 'squadra non impostata'} · {l.role === 'admin' ? 'amministratore' : 'partecipante'}
                      </span>
                    </span>
                    {sel ? <Check size={18} strokeWidth={2.4} aria-hidden className="shrink-0 text-brand-strong" /> : null}
                  </button>
                );
              })}
            </div>
            <div className="border-t border-line px-3 py-3">
              <Link
                to={USER_ADMIN_TO}
                className="flex min-h-[52px] items-center gap-2.5 rounded-xl bg-surface-2 px-3 py-2 text-sm font-semibold text-ink-soft"
              >
                <LayoutGrid size={19} strokeWidth={1.9} aria-hidden className="shrink-0" />
                <span className="min-w-0">Le mie leghe — crea, entra con un codice, gestisci</span>
              </Link>
            </div>
          </div>
        </div>
      ) : null}

      {/* IL FOGLIO «ALTRO». Sale da sopra la barra, non copre tutto, e si chiude
          toccando fuori: quello che non entra nei cinque slot sta qui, in chiaro,
          invece che dietro uno scorrimento orizzontale che nessuno sa di poter
          fare — e che quando lo si faceva portava via anche la voce della pagina
          in cui si era, lasciando la barra senza nessuna voce accesa. */}
      {moreOpen ? (
        <div className="md:hidden fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Altre pagine">
          <button
            type="button"
            aria-label="Chiudi"
            className="absolute inset-0 bg-ink/40"
            onClick={() => setMoreOpen(false)}
          />
          <div
            className="absolute inset-x-0 bottom-0 rounded-t-3xl border-t border-line bg-surface shadow-lift"
            style={{ paddingBottom: `calc(env(safe-area-inset-bottom, 0px) + ${mobileBarBlock}px)` }}
          >
            <div className="flex items-center justify-between px-4 pt-3">
              <span className="font-cond text-xs font-bold uppercase tracking-wide text-ink-faint">Altro</span>
              <button
                type="button"
                onClick={() => setMoreOpen(false)}
                aria-label="Chiudi"
                className="rounded-lg p-1.5 text-ink-faint hover:bg-surface-2"
              >
                <X size={18} strokeWidth={2} aria-hidden />
              </button>
            </div>
            {/* Due per riga: bersagli larghi, non una lista di righe sottili. */}
            <div className="grid grid-cols-2 gap-1.5 px-3 pb-3 pt-2">
              {sheetItems.map((it) => {
                const manual = leagueAdminActive(location.search, location.pathname, it.to);
                const cls = (active: boolean) =>
                  clsx(
                    'flex min-h-[52px] items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-semibold',
                    active
                      ? it.scope === 'competition'
                        ? clsx(color.tint, color.text700)
                        : 'bg-brand/12 text-brand-strong'
                      : 'bg-surface-2 text-ink-soft',
                  );
                const inner = (
                  <>
                    <it.icon size={19} strokeWidth={1.9} aria-hidden className="shrink-0" />
                    <span className="min-w-0 truncate">{it.label}</span>
                    {it.badge ? (
                      <span className="ml-auto shrink-0 rounded-full bg-warn px-1.5 py-0.5 text-[10px] font-bold text-white">
                        {it.badge}
                      </span>
                    ) : it.flag ? (
                      <span
                        className="ml-auto h-2 w-2 shrink-0 rounded-full bg-warn"
                        aria-label="Ci sono passi da completare"
                      />
                    ) : null}
                  </>
                );
                return manual === undefined ? (
                  <NavLink key={it.to} to={it.to} end={it.exact} className={({ isActive }) => cls(isActive)}>
                    {inner}
                  </NavLink>
                ) : (
                  <Link key={it.to} to={it.to} className={cls(manual)}>
                    {inner}
                  </Link>
                );
              })}
            </div>
            {/* L'account, sotto una riga: non è la lega, è chi la gioca. */}
            <div className="grid grid-cols-2 gap-1.5 border-t border-line px-3 py-3">
              <Link
                to={USER_ADMIN_TO}
                className={clsx(
                  'flex min-h-[52px] items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-semibold',
                  isUserAdmin ? 'bg-brand/12 text-brand-strong' : 'bg-surface-2 text-ink-soft',
                )}
              >
                <LayoutGrid size={19} strokeWidth={1.9} aria-hidden className="shrink-0" />
                <span className="min-w-0 truncate">Le mie leghe</span>
              </Link>
              <Link
                to="/profilo"
                className={clsx(
                  'flex min-h-[52px] items-center gap-2.5 rounded-xl px-3 py-2 text-sm font-semibold',
                  location.pathname.startsWith('/profilo') ? 'bg-brand/12 text-brand-strong' : 'bg-surface-2 text-ink-soft',
                )}
              >
                <UserRound size={19} strokeWidth={1.9} aria-hidden className="shrink-0" />
                <span className="min-w-0 truncate">{user?.username ?? 'Profilo'}</span>
              </Link>
              <button
                type="button"
                onClick={() => void logout()}
                className="col-span-2 flex min-h-[52px] items-center justify-center gap-2.5 rounded-xl border border-line px-3 py-2 text-sm font-semibold text-ink-faint"
              >
                <LogOut size={18} strokeWidth={1.9} aria-hidden /> Logout
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {/* LA BARRA. Cinque slot, sempre cinque, sempre gli stessi posti: niente
          scorrimento orizzontale. I due slot centrali appartengono alla
          COMPETIZIONE e cambiano con lei — un campionato ci mette calendario e
          classifica, una coppa secca il solo tabellone — ed è per questo che le
          pastiglie per sceglierla stanno qui sopra, appiccicate: cambi
          competizione col pollice e vedi il menu riscriversi due centimetri più
          in alto, invece che in cima alla pagina dove non si collega a niente. */}
      <div
        className="md:hidden fixed bottom-0 left-0 right-0 z-50 border-t border-line bg-surface"
        style={{ paddingBottom: 'env(safe-area-inset-bottom, 0px)' }}
      >
        {showCompetitionChips ? (
          <div
            className="flex gap-1.5 overflow-x-auto border-b border-line px-2 py-1.5"
            style={{ height: MOBILE_CHIPS_H, scrollbarWidth: 'none' }}
          >
            {competitions.map((c, i) => {
              const cc = compColor(i);
              const sel = c.competition_id === selectedCompetitionId;
              return (
                <button
                  key={c.competition_id}
                  type="button"
                  onClick={() => chooseCompetition(c)}
                  aria-pressed={sel}
                  className={clsx(
                    'flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-semibold',
                    sel ? clsx(cc.border600, cc.tint, cc.text800) : 'border-line bg-surface text-ink-faint',
                  )}
                >
                  <span className={clsx('h-2 w-2 shrink-0 rounded-full', cc.dot)} aria-hidden />
                  <span className="max-w-[9rem] truncate">{c.name}</span>
                </button>
              );
            })}
          </div>
        ) : null}
        <div className="flex" style={{ height: MOBILE_BAR_H }}>
          {barItems.map((it) => {
            const manual = leagueAdminActive(location.search, location.pathname, it.to);
            // Active state must be unmistakable on a phone: a coloured top accent bar
            // + a tinted background + darker text, not just a subtle text-colour shift.
            // border-t-2 (transparent when inactive) keeps every item the same height.
            const cls = (active: boolean) =>
              clsx(
                'flex flex-1 basis-0 flex-col items-center justify-center gap-1 border-t-2 px-0.5 py-2 text-[10px] font-semibold leading-tight transition-colors',
                active
                  ? it.scope === 'competition'
                    ? clsx(color.text700, color.tint, color.border600)
                    : 'border-brand bg-brand/12 text-brand-strong'
                  : clsx('border-transparent', it.scope === 'competition' ? color.text400 : 'text-ink-faint')
              );
            const inner = (
              <>
                <span className="relative leading-none">
                  <it.icon size={19} strokeWidth={1.9} aria-hidden />
                  {it.badge ? (
                    <span className="absolute -right-2 -top-1 rounded-full bg-warn px-1 text-[9px] font-bold text-white">
                      {it.badge}
                    </span>
                  ) : it.flag ? (
                    <span
                      className="absolute -right-1 -top-0.5 h-2 w-2 rounded-full bg-warn"
                      aria-label="Ci sono passi da completare"
                    />
                  ) : null}
                </span>
                <span className="w-full truncate text-center">{it.label}</span>
              </>
            );
            if (manual === undefined) {
              return (
                <NavLink key={it.to} to={it.to} end={it.exact} className={({ isActive }) => cls(isActive)}>
                  {inner}
                </NavLink>
              );
            }
            return (
              <Link key={it.to} to={it.to} className={cls(manual)}>
                {inner}
              </Link>
            );
          })}
          {/* Sempre, anche quando non c'è nessuna pagina da nascondere: sotto le
              voci di menu il foglio tiene l'account — profilo e Logout — che
              esistono pure senza una lega. Prima appariva solo se avanzavano
              voci, quindi spariva proprio a chi ha meno strada per uscire. */}
          {
            <button
              type="button"
              onClick={() => setMoreOpen((o) => !o)}
              aria-expanded={moreOpen}
              aria-label="Altre pagine"
              className={clsx(
                'flex flex-1 basis-0 flex-col items-center justify-center gap-1 border-t-2 px-0.5 py-2 text-[10px] font-semibold leading-tight transition-colors',
                moreOpen ? 'border-brand bg-brand/12 text-brand-strong' : 'border-transparent text-ink-faint',
              )}
            >
              <span className="relative leading-none">
                <MoreHorizontal size={19} strokeWidth={1.9} aria-hidden />
                {/* Il numero di quello che è nascosto, ADDOSSO a quello che lo
                    nasconde: senza, «Decisioni» portava il suo contatore fuori
                    dallo schermo e la barra non lo diceva. */}
                {sheetBadge ? (
                  <span className="absolute -right-2 -top-1 rounded-full bg-warn px-1 text-[9px] font-bold text-white">
                    {sheetBadge}
                  </span>
                ) : sheetFlag ? (
                  <span className="absolute -right-1 -top-0.5 h-2 w-2 rounded-full bg-warn" />
                ) : null}
              </span>
              <span className="w-full truncate text-center">Altro</span>
            </button>
          }
        </div>
      </div>
    </div>
  );
}
