import { NavLink, Outlet, useLocation } from 'react-router-dom';
import clsx from 'clsx';
import { useMemo } from 'react';
import LeagueSwitcher from '../components/LeagueSwitcher';

const navItems = [
  { to: '/home', label: 'Home', icon: '🏠' },
  { to: '/league', label: 'Lega', icon: '🏆' },
  { to: '/squad', label: 'Squadra', icon: '👥' },
  { to: '/matches', label: 'Partite', icon: '🎯' },
  { to: '/market', label: 'Mercato', icon: '💱' }
];

function usePageTitle(pathname: string) {
  return useMemo(() => {
    if (pathname.startsWith('/home')) return 'Dashboard';
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

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      {/* Desktop top bar */}
      <div className="hidden md:block border-b bg-white">
        <div className="mx-auto max-w-7xl px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="font-black tracking-tight text-lg">Vfoot Boosted</div>
            <div className="text-slate-400">/</div>
            <div className="font-semibold">{title}</div>
          </div>
          <div className="flex items-center gap-3">
            <LeagueSwitcher />
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
            <div className="text-xs font-semibold text-slate-500">Lega attiva</div>
            <div className="mt-1 font-semibold">Lega Friends</div>
            <div className="mt-2 text-xs text-slate-500">Giornata 24 · Deadline 13/02 20:45</div>
          </div>
        </aside>

        {/* Main */}
        <main className="pb-20 md:pb-8 px-4 py-4 md:py-6">
          {/* Mobile header */}
          <div className="md:hidden mb-3 flex items-center justify-between">
            <div>
              <div className="text-xs text-slate-500">Vfoot Boosted</div>
              <div className="font-bold text-lg leading-tight">{title}</div>
            </div>
            <LeagueSwitcher compact />
          </div>

          <Outlet />
        </main>
      </div>

      {/* Mobile tab bar */}
      <div className="md:hidden fixed bottom-0 left-0 right-0 border-t bg-white">
        <div className="grid grid-cols-5">
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
