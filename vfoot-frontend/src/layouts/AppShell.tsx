import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import clsx from 'clsx';
import { useMemo } from 'react';
import LeagueSwitcher from '../components/LeagueSwitcher';
import CompetitionSwitcher from '../components/CompetitionSwitcher';
import { useAuth } from '../auth/AuthContext';
import { Button } from '../components/ui';
import logo from '../assets/logo.png';
import { useLeagueContext } from '../league/LeagueContext';
import { useCompetitionContext } from '../league/CompetitionContext';
import { compColor } from '../league/competitionColors';
import { useDecisionAlerts } from '../league/useDecisionAlerts';

// League-scoped navigation (left sidebar + mobile bar): everything here is about
// the CURRENTLY selected league. User-level actions (Le mie leghe) and switching
// between leagues live in the top bar instead.
// scope: 'competition' pages refer to the CURRENT competition (they follow the
// competition switcher) and get an indigo accent; 'league' pages are global.
type NavItem = { to: string; label: string; icon: string; scope: 'league' | 'competition'; badge?: number };

const leagueNav = [
  { to: '/home', label: 'Home', icon: '🏠', scope: 'league' as const },
  { to: '/league', label: 'Lega', icon: '🏆', scope: 'league' as const },
  { to: '/squad', label: 'Squadra', icon: '👥', scope: 'league' as const },
  { to: '/matches', label: 'Partite', icon: '🎯', scope: 'competition' as const },
  { to: '/standings', label: 'Classifica', icon: '📊', scope: 'competition' as const },
  { to: '/serie-a', label: 'Serie A', icon: '⚽', scope: 'league' as const },
  { to: '/listone', label: 'Listone', icon: '📋', scope: 'league' as const },
  { to: '/market', label: 'Mercato', icon: '💱', scope: 'league' as const },
  { to: '/decisioni', label: 'Decisioni', icon: '🗳️', scope: 'league' as const },
  { to: '/league-admin?tab=league', label: 'Gestione lega', icon: '⚙️', scope: 'league' as const },
];

const USER_ADMIN_TO = '/league-admin?tab=user';

function usePageTitle(pathname: string) {
  return useMemo(() => {
    if (pathname.startsWith('/home')) return 'Dashboard';
    if (pathname.startsWith('/league-admin')) return 'Amministrazione';
    if (pathname.startsWith('/league')) return 'Lega';
    if (pathname.startsWith('/squad/formation')) return 'Formazione';
    if (pathname.startsWith('/squad')) return 'Squadra';
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
  const { selectedLeague, leagues } = useLeagueContext();
  const { competitions, selectedCompetitionId, selectedCompetition } = useCompetitionContext();
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
  const nav = useMemo<NavItem[]>(
    () => leagueNav.map((it): NavItem => {
      if (it.to === '/standings')
        return { ...it, label: standingsLabel, icon: resultView === 'classifica' ? '📊' : '🗂️' };
      if (it.to === '/serie-a') return { ...it, label: refCompetition };
      if (it.to === '/decisioni') return { ...it, badge: alerts.attention || alerts.blocking };
      return it;
    }),
    [standingsLabel, resultView, refCompetition, alerts],
  );
  const baseTitle = usePageTitle(location.pathname);
  const title = location.pathname.startsWith('/standings')
    ? standingsLabel
    : location.pathname.startsWith('/serie-a/')
      ? `Partita ${refCompetition}`
      : location.pathname.startsWith('/serie-a')
        ? refCompetition
        : baseTitle;

  const isUserAdmin = location.pathname.startsWith('/league-admin') && location.search.includes('tab=user');

  const navItemClass = (active: boolean, scope: 'league' | 'competition') =>
    clsx(
      'flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-semibold',
      active
        ? scope === 'competition'
          ? `${color.bg700} text-white shadow-card`
          : 'bg-slate-900 text-white shadow-card'
        : scope === 'competition'
          ? `${color.text700} ${color.hover50}`
          : 'text-slate-700 hover:bg-slate-200'
    );

  function renderNav(item: NavItem) {
    const manual = leagueAdminActive(location.search, location.pathname, item.to);
    const content = (
      <>
        <span className="text-lg">{item.icon}</span>
        {item.label}
        {item.badge ? (
          <span className="ml-auto rounded-full bg-amber-500 px-1.5 py-0.5 text-[10px] font-bold text-white">
            {item.badge}
          </span>
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
    <div className="min-h-screen bg-slate-50 text-slate-900">
      {/* Desktop top bar — cross-league: switcher + user admin + account */}
      <div className="hidden md:block border-b bg-white">
        <div className="mx-auto max-w-7xl px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src={logo} alt="Vfoot logo" className="h-8 w-8 rounded-lg object-cover" />
            <div className="font-black tracking-tight text-lg">Vfoot Boosted</div>
            <div className="text-slate-400">/</div>
            <div className="font-semibold">{title}</div>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-end gap-2">
              <label className="flex flex-col gap-0.5">
                <span className="px-1 text-[10px] font-semibold uppercase tracking-wide text-slate-400">Lega</span>
                <LeagueSwitcher />
              </label>
              <label className="flex flex-col gap-0.5">
                <span className={clsx('px-1 text-[10px] font-semibold uppercase tracking-wide', color.text500)}>Competizione</span>
                <CompetitionSwitcher />
              </label>
            </div>
            <Link
              to={USER_ADMIN_TO}
              className={clsx(
                'flex items-center gap-1.5 rounded-xl px-3 py-2 text-sm font-semibold',
                isUserAdmin ? 'bg-slate-900 text-white' : 'text-slate-700 hover:bg-slate-100'
              )}
            >
              <span>🧑‍💼</span> Le mie leghe
            </Link>
            <div className="text-right text-xs leading-tight">
              <div className="text-slate-500">{user?.username ?? 'Utente'}</div>
              <div className="font-semibold text-slate-700">Squadra: {activeTeamName ?? 'non impostata'}</div>
            </div>
            <Button size="sm" variant="secondary" onClick={() => void logout()}>
              Logout
            </Button>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-7xl md:grid md:grid-cols-[240px_1fr] md:gap-6">
        {/* Desktop sidebar — current league only */}
        <aside className="hidden md:block sticky top-0 self-start h-[calc(100vh-57px)] overflow-auto px-4 py-6">
          <div className="px-1 pb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            {selectedLeague?.name ?? 'Nessuna lega'}
          </div>
          <nav className="space-y-1">{nav.map(renderNav)}</nav>

          {/* No "active league" card here: name and role are already in the top
              bar, where they can also be CHANGED. Only the empty state needs a
              word, since then the sidebar links lead nowhere useful. */}
          {!selectedLeague ? (
            <div className="mt-6 rounded-2xl bg-white shadow-card p-4 text-xs text-slate-500">
              {leagues.length
                ? 'Seleziona una lega dal menu in alto.'
                : 'Crea o unisciti a una lega da Le mie leghe.'}
            </div>
          ) : null}
        </aside>

        {/* Main */}
        <main className="pb-20 md:pb-8 px-4 py-4 md:py-6">
          {/* Mobile header */}
          <div className="md:hidden mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <img src={logo} alt="Vfoot logo" className="h-8 w-8 rounded-lg object-cover" />
              <div>
                <div className="text-xs text-slate-500">Vfoot Boosted</div>
                <div className="font-bold text-lg leading-tight">{title}</div>
                {selectedLeague ? (
                  <div className="text-[11px] text-slate-500 leading-tight">
                    {selectedLeague.name} · Squadra: {activeTeamName ?? 'non impostata'}
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
                  isUserAdmin ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-700'
                )}
              >
                🧑‍💼
              </Link>
              <Button size="sm" variant="secondary" onClick={() => void logout()}>
                Logout
              </Button>
            </div>
          </div>

          {/* Mobile context bar: the active LEAGUE and COMPETITION, clearly labelled
              and full-width so the current selection is always obvious on a phone. */}
          <div className="md:hidden mb-3 grid grid-cols-1 gap-2 rounded-2xl bg-white p-3 shadow-card">
            <label className="block">
              <span className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-slate-400">Lega</span>
              <LeagueSwitcher compact />
            </label>
            <label className="block">
              <span className={clsx('mb-1 block text-[10px] font-semibold uppercase tracking-wide', color.text500)}>
                Competizione
              </span>
              <CompetitionSwitcher compact />
            </label>
          </div>

          {/* Accent strip: signals at a glance that this page is scoped to the CURRENT
              competition (indigo), vs the neutral league-level pages. */}
          {isCompetitionPage && selectedCompetition ? (
            <div className={clsx('mb-3 flex items-center gap-2 rounded-xl border-l-4 px-3 py-2', color.border600, color.bg50)}>
              <span className="text-sm">🏆</span>
              <span className={clsx('text-xs font-semibold uppercase tracking-wide', color.text700)}>Competizione</span>
              <span className={clsx('text-sm font-bold', color.text900)}>{selectedCompetition.name}</span>
            </div>
          ) : null}

          <Outlet />
        </main>
      </div>

      {/* Mobile tab bar — current league only */}
      <div className="md:hidden fixed bottom-0 left-0 right-0 border-t bg-white">
        <div
          className="grid"
          style={{ gridTemplateColumns: `repeat(${nav.length}, minmax(0, 1fr))` }}
        >
          {nav.map((it) => {
            const manual = leagueAdminActive(location.search, location.pathname, it.to);
            const cls = (active: boolean) =>
              clsx(
                'flex flex-col items-center justify-center py-2 text-[11px] font-semibold',
                it.scope === 'competition'
                  ? active ? color.text700 : color.text400
                  : active ? 'text-slate-900' : 'text-slate-500'
              );
            const inner = (
              <>
                <span className="relative text-lg leading-none">
                  {it.icon}
                  {it.badge ? (
                    <span className="absolute -right-2 -top-1 rounded-full bg-amber-500 px-1 text-[9px] font-bold text-white">
                      {it.badge}
                    </span>
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
