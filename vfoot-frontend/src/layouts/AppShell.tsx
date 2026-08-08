import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import clsx from 'clsx';
import { useMemo } from 'react';
// Un'icona per voce, e ognuna dice la SUA voce: la maglia per le rose, il podio
// per la classifica, l'urna per le decisioni. Le emoji le disegnano tre sistemi
// operativi diversi, quindi la stessa barra aveva tre stili e tre spessori.
import {
  ArrowLeftRight, BarChart3, CalendarDays, CircleDot, ClipboardList, Home,
  LayoutGrid, Settings, Shirt, Vote, type LucideIcon,
} from 'lucide-react';
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
};

const leagueNav = [
  { to: '/home', label: 'Home lega', icon: Home, scope: 'league' as const },
  // "Rose" and not "Squadra": the page opens on your own, but the strip at the
  // top browses every roster in the league, so the plural is what it does.
  { to: '/squad', label: 'Rose', icon: Shirt, scope: 'league' as const },
  { to: '/matches', label: 'Partite', icon: CalendarDays, scope: 'competition' as const },
  { to: '/standings', label: 'Classifica', icon: BarChart3, scope: 'competition' as const },
  { to: '/listone', label: 'Listone', icon: ClipboardList, scope: 'league' as const },
  { to: '/market', label: 'Mercato', icon: ArrowLeftRight, scope: 'league' as const },
  { to: '/decisioni', label: 'Decisioni', icon: Vote, scope: 'league' as const },
  { to: '/league-admin?tab=league', label: 'Gestione lega', icon: Settings, scope: 'league' as const },
  // Last, and after a separator: the real championship is what the league is
  // played ON, not a page you need to run it. Everything above is the league.
  { to: '/serie-a', label: 'Serie A', icon: CircleDot, scope: 'league' as const, aside: true },
];

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
    if (pathname.startsWith('/matches')) return 'Partite';
    if (pathname.startsWith('/standings')) return 'Classifica';
    if (pathname.startsWith('/serie-a/')) return 'Partita Serie A';
    if (pathname.startsWith('/serie-a')) return 'Serie A';
    if (pathname.startsWith('/listone')) return 'Listone';
    if (pathname.startsWith('/market')) return 'Mercato';
    if (pathname.startsWith('/decisioni')) return 'Decisioni';
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
  const { user, logout } = useAuth();
  const { selectedLeague, leagues, loading: leaguesLoading } = useLeagueContext();
  const {
    competitions,
    selectedCompetitionId,
    selectedCompetition,
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

  const nav = useMemo<NavItem[]>(() => {
    const items = leagueNav
      .filter((it) => isLeagueAdmin || !it.to.startsWith('/league-admin'))
      .map((it): NavItem => {
        if (it.to === '/standings')
          return { ...it, label: standingsLabel, icon: resultView === 'classifica' ? BarChart3 : LayoutGrid };
        if (it.to === '/serie-a') return { ...it, label: refCompetition };
        // One number per audience, and they must not be mixed: the admin's is his
        // whole sign-off queue, the member's is only what he was asked. Falling back
        // from one to the other made 17 pending sign-offs read as 1 the moment the
        // admin opened a single consultation.
        if (it.to === '/decisioni')
          return { ...it, badge: alerts.isAdmin ? alerts.blocking : alerts.attention };
        return it;
      });

    if (!leagueInSetup) return items;

    // Partite and Classifica read the CURRENT competition; with none they can only
    // report their own emptiness.
    const usable = items.filter((it) => it.to !== '/matches' && it.to !== '/standings');
    const adminIndex = usable.findIndex((it) => it.to.startsWith('/league-admin'));
    if (adminIndex < 0) return usable;
    // Straight after Home, flagged: it is the only place where the league can be
    // moved forward, and it should not have to be hunted for.
    const admin: NavItem = { ...usable[adminIndex], flag: true };
    const rest = usable.filter((_, i) => i !== adminIndex);
    return [rest[0], admin, ...rest.slice(1)];
  }, [standingsLabel, resultView, refCompetition, alerts, leagueInSetup, isLeagueAdmin]);
  // Also empty WHILE LOADING, not just when the list comes back empty: drawing the
  // menu optimistically would flash ten dead links at exactly the brand-new
  // account we are trying to spare them from.
  const visibleNav = leaguesLoading || !hasLeagues ? [] : nav;

  const baseTitle = usePageTitle(location.pathname);
  const title = location.pathname.startsWith('/standings')
    ? standingsLabel
    : location.pathname.startsWith('/serie-a/')
      ? `Partita ${refCompetition}`
      : location.pathname.startsWith('/serie-a')
        ? refCompetition
        : baseTitle;

  const isUserAdmin = location.pathname.startsWith('/league-admin') && location.search.includes('tab=user');
  // Only the mobile header shows a page title (no sidebar there to say where you
  // are). It has to match the words used in the menu and on the page itself.
  const mobileTitle = location.pathname.startsWith('/league-admin')
    ? isUserAdmin
      ? 'Le mie leghe'
      : 'Gestione lega'
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
        <NavLink key={item.to} to={item.to} className={({ isActive }) => navItemClass(isActive, item.scope)}>
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
    location.pathname.startsWith('/matches') || location.pathname.startsWith('/standings');

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
        <main className="pb-20 md:pb-8 px-4 py-4 md:py-6">
          {/* Mobile header */}
          <div className="md:hidden mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Link to="/home" aria-label="Vai alla home" className="shrink-0">
                <img src={logo} alt="Vfoot logo" className="h-8 w-8 rounded-lg object-cover" />
              </Link>
              <div>
                <div className="text-xs text-ink-faint">Vfoot Boosted</div>
                <div className="font-bold text-lg leading-tight">{mobileTitle}</div>
                {selectedLeague ? (
                  <div className="flex items-center gap-1 text-[11px] text-ink-faint leading-tight">
                    {activeTeamName ? (
                      <Crest descriptor={selectedLeague.team_crest} teamName={activeTeamName} size={14} />
                    ) : null}
                    <span className="truncate">
                      {selectedLeague.name} · {activeTeamName ?? 'squadra non impostata'}
                    </span>
                  </div>
                ) : null}
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Link
                to={USER_ADMIN_TO}
                aria-label="Le mie leghe"
                className={clsx(
                  'rounded-xl px-2 py-2 text-sm',
                  isUserAdmin ? 'bg-ink text-paper' : 'bg-surface-2 text-ink-soft'
                )}
              >
                🗂️
              </Link>
              <Link
                to="/profilo"
                aria-label="Profilo"
                className={clsx(
                  'rounded-full',
                  location.pathname.startsWith('/profilo') ? 'ring-2 ring-brand ring-offset-1' : '',
                )}
              >
                <Avatar descriptor={user?.avatar} username={user?.username} size={34} />
              </Link>
              <Button size="sm" variant="secondary" onClick={() => void logout()}>
                Logout
              </Button>
            </div>
          </div>

          {/* Mobile context bar: the active LEAGUE and COMPETITION, clearly labelled
              and full-width so the current selection is always obvious on a phone. */}
          {hasLeagues ? (
            <div className="md:hidden mb-3 grid grid-cols-1 gap-2 rounded-2xl border border-line bg-surface p-3 shadow-card">
              <label className="block">
                <span className="mb-1 block font-cond text-[10px] font-bold uppercase tracking-wide text-ink-faint">Lega</span>
                <LeagueSwitcher compact />
              </label>
              {competitions.length ? (
                <label className="block">
                  <span className={clsx('mb-1 block text-[10px] font-semibold uppercase tracking-wide', color.text500)}>
                    Competizione
                  </span>
                  <CompetitionSwitcher compact />
                </label>
              ) : null}
            </div>
          ) : null}

          {/* Accent strip: signals at a glance that this page is scoped to the CURRENT
              competition (indigo), vs the neutral league-level pages. */}
          {isCompetitionPage && selectedCompetition ? (
            <div className={clsx('mb-3 flex items-center gap-2 rounded-xl border-l-4 px-3 py-2', color.border600, color.tint)}>
              <span className="text-sm">🏆</span>
              <span className={clsx('text-xs font-semibold uppercase tracking-wide', color.text700)}>Competizione</span>
              <span className={clsx('text-sm font-bold', color.text900)}>{selectedCompetition.name}</span>
            </div>
          ) : null}

          {/* Keyed on the route: a boundary that has caught STAYS caught, so
              without this the card would follow you onto pages that work. */}
          <PageErrorBoundary key={location.pathname}>
            <Outlet />
          </PageErrorBoundary>
        </main>
      </div>

      {/* Mobile tab bar — current league only. Too many items to share one row on a
          phone, so it scrolls horizontally with fixed-width, non-wrapping items
          (labels stay legible instead of overlapping). */}
      <div
        className={clsx(
          'md:hidden fixed bottom-0 left-0 right-0 border-t border-line bg-surface',
          visibleNav.length ? '' : 'hidden',
        )}
      >
        <div
          className="flex overflow-x-auto"
          style={{ scrollbarWidth: 'none' }}
        >
          {visibleNav.map((it) => {
            const manual = leagueAdminActive(location.search, location.pathname, it.to);
            // Active state must be unmistakable on a phone: a coloured top accent bar
            // + a tinted background + darker text, not just a subtle text-colour shift.
            // border-t-2 (transparent when inactive) keeps every item the same height.
            const cls = (active: boolean) =>
              clsx(
                'flex shrink-0 basis-[20%] flex-col items-center justify-center gap-1 whitespace-nowrap border-t-2 px-1 py-2 text-[11px] font-semibold transition-colors',
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
                <span className="mt-1">{it.label}</span>
              </>
            );
            if (manual === undefined) {
              return (
                <NavLink key={it.to} to={it.to} className={({ isActive }) => cls(isActive)}>
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
        </div>
      </div>
    </div>
  );
}
