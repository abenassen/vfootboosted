import { NavLink, Outlet, useLocation } from 'react-router-dom';
import clsx from 'clsx';
import { useEffect, useMemo, useState } from 'react';
import LeagueSwitcher from '../components/LeagueSwitcher';
import { useAuth } from '../auth/AuthContext';
import { Button } from '../components/ui';
import logo from '../assets/logo.png';
import { useLeagueContext } from '../league/LeagueContext';
import { getCompetitions } from '../api';
import type { CompetitionItem } from '../types/league';

const navItems = [
  { to: '/home', label: 'Home', icon: '🏠' },
  { to: '/league', label: 'Lega', icon: '🏆' },
  { to: '/league-admin?tab=user', label: 'User Admin', icon: '🧑‍💼' },
  { to: '/squad', label: 'Squadra', icon: '👥' },
  { to: '/matches', label: 'Partite', icon: '🎯' },
  { to: '/market', label: 'Mercato', icon: '💱' }
];

function usePageTitle(pathname: string) {
  return useMemo(() => {
    if (pathname.startsWith('/home')) return 'Dashboard';
    if (pathname.startsWith('/league-admin')) return 'League Admin';
    if (pathname.startsWith('/league')) return 'Lega';
    if (pathname.startsWith('/squad/formation')) return 'Formazione';
    if (pathname.startsWith('/squad')) return 'Squadra';
    if (pathname.startsWith('/matches/')) return 'Match';
    if (pathname.startsWith('/matches')) return 'Partite';
    if (pathname.startsWith('/market')) return 'Mercato';
    return 'Vfoot';
  }, [pathname]);
}

export default function AppShell() {
  const location = useLocation();
  const title = usePageTitle(location.pathname);
  const { user, logout } = useAuth();
  const { selectedLeague, selectedLeagueId, leagues, setSelectedLeagueId } = useLeagueContext();
  const [quickCompetitions, setQuickCompetitions] = useState<CompetitionItem[]>([]);
  const activeTeamName = selectedLeague?.team_name?.trim() || null;

  useEffect(() => {
    if (!selectedLeagueId) {
      setQuickCompetitions([]);
      return;
    }
    void getCompetitions(selectedLeagueId)
      .then((c) => setQuickCompetitions(c.slice(0, 6)))
      .catch(() => setQuickCompetitions([]));
  }, [selectedLeagueId]);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      {/* Desktop top bar */}
      <div className="hidden md:block border-b bg-white">
        <div className="mx-auto max-w-7xl px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <img src={logo} alt="Vfoot logo" className="h-8 w-8 rounded-lg object-cover" />
            <div className="font-black tracking-tight text-lg">Vfoot Boosted</div>
            <div className="text-slate-400">/</div>
            <div className="font-semibold">{title}</div>
          </div>
          <div className="flex items-center gap-3">
            <LeagueSwitcher />
            <div className="text-right text-xs leading-tight">
              <div className="text-slate-500">{user?.username ?? 'Utente'}</div>
              <div className="font-semibold text-slate-700">
                Squadra: {activeTeamName ?? 'non impostata'}
              </div>
            </div>
            <Button size="sm" variant="secondary" onClick={() => void logout()}>
              Logout
            </Button>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-7xl md:grid md:grid-cols-[240px_1fr] md:gap-6">
        {/* Desktop sidebar */}
        <aside className="hidden md:block sticky top-0 self-start h-[calc(100vh-57px)] overflow-auto px-4 py-6">
          <nav className="space-y-1">
            {navItems.map((it) => (
              <NavLink
                key={it.to}
                to={it.to}
                className={({ isActive }) =>
                  clsx(
                    'flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-semibold',
                    isActive ? 'bg-slate-900 text-white shadow-card' : 'text-slate-700 hover:bg-slate-200'
                  )
                }
              >
                <span className="text-lg">{it.icon}</span>
                {it.label}
              </NavLink>
            ))}
          </nav>

          <div className="mt-6 rounded-2xl bg-white shadow-card p-4">
            <div className="text-xs font-semibold text-slate-500">Le tue leghe</div>
            <div className="mt-2 space-y-1">
              {leagues.length ? (
                leagues.map((l) => (
                  <button
                    key={l.league_id}
                    type="button"
                    className={clsx(
                      'w-full rounded-lg px-2 py-1 text-left text-sm font-semibold',
                      selectedLeague?.league_id === l.league_id ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-700'
                    )}
                    onClick={() => setSelectedLeagueId(l.league_id)}
                  >
                    {l.name}
                  </button>
                ))
              ) : (
                <div className="text-xs text-slate-500">Nessuna lega</div>
              )}
            </div>
          </div>

          <div className="mt-6 rounded-2xl bg-white shadow-card p-4">
            <div className="text-xs font-semibold text-slate-500">Lega attiva</div>
            <div className="mt-1 font-semibold">{selectedLeague?.name ?? 'Nessuna lega selezionata'}</div>
            <div className="mt-2 text-xs text-slate-500">
              {selectedLeague ? `Ruolo: ${selectedLeague.role}` : leagues.length ? 'Seleziona una lega dal menu in alto' : 'Crea o unisciti a una lega'}
            </div>
            {quickCompetitions.length ? (
              <div className="mt-3 space-y-1">
                {quickCompetitions.map((c) => (
                  <NavLink key={c.competition_id} to={`/competitions/${c.competition_id}`} className="block rounded-lg bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-200">
                    {c.name}
                  </NavLink>
                ))}
              </div>
            ) : null}
          </div>
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
              <LeagueSwitcher compact />
              <Button size="sm" variant="secondary" onClick={() => void logout()}>
                Logout
              </Button>
            </div>
          </div>

          <Outlet />
        </main>
      </div>

      {/* Mobile tab bar */}
      <div className="md:hidden fixed bottom-0 left-0 right-0 border-t bg-white">
        <div className="grid grid-cols-6">
          {navItems.map((it) => (
            <NavLink
              key={it.to}
              to={it.to}
              className={({ isActive }) =>
                clsx(
                  'flex flex-col items-center justify-center py-2 text-xs font-semibold',
                  isActive ? 'text-slate-900' : 'text-slate-500'
                )
              }
            >
              <span className="text-lg leading-none">{it.icon}</span>
              <span className="mt-1">{it.label}</span>
            </NavLink>
          ))}
        </div>
      </div>
    </div>
  );
}
