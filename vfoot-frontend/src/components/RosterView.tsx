import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, SectionTitle, Badge } from './ui';
import { getLeagueDetail } from '../api';
import { useAuth } from '../auth/AuthContext';
import { useLeagueContext } from '../league/LeagueContext';
import type { LeagueTeam } from '../types/league';
import type { PlayerRole, MinutesLabel, TeamLineupContext, TeamLineupPlayer } from '../types/lineup';

// The structured roster: grouped by role, a spending summary, and a clickable
// detail per player. Shared between the manager's own Squad page and the
// read-only view of another participant's team, so both read identically.

const ROLE_LABEL: Record<PlayerRole, string> = { GK: 'POR', DEF: 'DIF', MID: 'CEN', ATT: 'ATT' };
const ROLE_NAME: Record<PlayerRole, string> = {
  GK: 'Portieri',
  DEF: 'Difensori',
  MID: 'Centrocampisti',
  ATT: 'Attaccanti',
};
const ROLE_CHIP: Record<PlayerRole, string> = {
  GK: 'bg-amber-500',
  DEF: 'bg-blue-500',
  MID: 'bg-emerald-500',
  ATT: 'bg-orange-500',
};
const ROLES: PlayerRole[] = ['GK', 'DEF', 'MID', 'ATT'];

export default function RosterView({ data }: { data: TeamLineupContext }) {
  const [openPlayer, setOpenPlayer] = useState<number | null>(null);
  const roster = [...data.roster].sort((a, b) => b.price - a.price);
  const budget = data.budget;
  const statsNote = data.stats_season
    ? data.stats_is_reference
      ? `Presenze, minuti e impiego sono aggiornati al campionato in corso (${data.stats_season}).`
      : `Il campionato non è ancora iniziato: presenze, minuti e impiego si riferiscono alla stagione ${data.stats_season}.`
    : null;

  return (
    <div className="space-y-4">
      <TeamSwitcher currentTeamId={data.team.team_id} ownTeamId={data.is_own ? data.team.team_id : null} />
      {budget ? (
        <Card className="p-4">
          <div className="grid grid-cols-3 gap-2">
            <Stat label="Budget" value={budget.initial} />
            <Stat label="Speso" value={budget.spent} tone="rose" />
            <Stat label="Residuo" value={budget.remaining} tone="emerald" />
          </div>
          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
            {ROLES.filter((r) => budget.by_role[r]).map((r) => (
              <span key={r}>
                {ROLE_NAME[r]}: <b className="text-slate-700">{budget.by_role[r]}</b>
              </span>
            ))}
          </div>
        </Card>
      ) : null}

      {ROLES.map((role) => {
        const group = roster.filter((p) => p.role === role);
        if (!group.length) return null;
        return (
          <Card key={role} className="p-4">
            <div className="flex items-baseline justify-between">
              <SectionTitle>{ROLE_NAME[role]}</SectionTitle>
              <span className="text-xs text-slate-400">
                {group.length} · {group.reduce((s, p) => s + p.price, 0)} crediti
              </span>
            </div>
            <div className="mt-2 divide-y">
              {group.map((p) => (
                <PlayerRow
                  key={p.player_id}
                  p={p}
                  open={openPlayer === p.player_id}
                  onToggle={() => setOpenPlayer((cur) => (cur === p.player_id ? null : p.player_id))}
                />
              ))}
            </div>
          </Card>
        );
      })}

      {statsNote ? <div className="px-1 text-[11px] text-slate-400">{statsNote}</div> : null}
    </div>
  );
}

/** A scrollable strip of every participant, so the rosters can be browsed one from
 *  another without going back to the League page — the manager's own team routes to
 *  /squad, the others to /teams/:id. Answers the ask for tab/swipe navigation. */
function TeamSwitcher({ currentTeamId }: { currentTeamId: number; ownTeamId: number | null }) {
  const { selectedLeagueId } = useLeagueContext();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [teams, setTeams] = useState<LeagueTeam[]>([]);

  useEffect(() => {
    if (!selectedLeagueId) return;
    let alive = true;
    void getLeagueDetail(selectedLeagueId)
      .then((d) => alive && setTeams(d.teams))
      .catch(() => setTeams([]));
    return () => {
      alive = false;
    };
  }, [selectedLeagueId]);

  // Which chip routes to /squad: the team the current user manages.
  const ownId = teams.find((t) => t.manager_user_id === user?.id)?.team_id ?? null;

  if (teams.length < 2) return null;
  return (
    <div className="-mx-1 flex gap-1.5 overflow-x-auto px-1 pb-1">
      {teams.map((t) => {
        const active = t.team_id === currentTeamId;
        const dest = t.team_id === ownId ? '/squad' : `/teams/${t.team_id}`;
        return (
          <button
            key={t.team_id}
            onClick={() => navigate(dest)}
            className={`shrink-0 rounded-full px-3 py-1 text-xs font-semibold ${
              active ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
            }`}
          >
            {t.name}
          </button>
        );
      })}
    </div>
  );
}

function Stat({ label, value, tone = 'slate' }: { label: string; value: number; tone?: 'slate' | 'rose' | 'emerald' }) {
  const color = tone === 'rose' ? 'text-rose-700' : tone === 'emerald' ? 'text-emerald-700' : 'text-slate-900';
  return (
    <div className="rounded-xl bg-slate-50 px-3 py-2 text-center">
      <div className="text-[10px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`text-lg font-bold ${color}`}>{value}</div>
    </div>
  );
}

function PlayerRow({ p, open, onToggle }: { p: TeamLineupPlayer; open: boolean; onToggle: () => void }) {
  return (
    <div className="py-2.5">
      <button type="button" onClick={onToggle} className="flex w-full items-center justify-between gap-3 text-left">
        <div className="flex min-w-0 items-center gap-2">
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ${ROLE_CHIP[p.role]}`}>
            {ROLE_LABEL[p.role]}
          </span>
          <div className="min-w-0">
            <div className="truncate font-semibold text-slate-900">{p.name}</div>
            <div className="truncate text-xs text-slate-500">{p.real_team ?? '—'}</div>
          </div>
        </div>
        {/* Fixed columns: the price sits in its own right-aligned slot so a missing
            usage badge (a newcomer with no history) never shifts it out of line. */}
        <div className="flex shrink-0 items-center gap-2">
          <span className="w-12 text-right font-mono text-sm font-bold text-slate-700">€{p.price}</span>
          <span className="hidden w-28 text-right sm:block">
            <MinutesBadge label={p.minutes_label} />
          </span>
        </div>
      </button>
      {open ? <PlayerDetail p={p} /> : null}
    </div>
  );
}

/** What we actually know about a player, made explicit rather than crammed into a
 *  cryptic "36 pres · 2.5 medi". The key clarification: "presenze" counts every
 *  call-up (bench included), which is why a reserve reads many appearances and
 *  almost no minutes — so starts are shown separately. */
function PlayerDetail({ p }: { p: TeamLineupPlayer }) {
  const vote = p.value != null ? p.value.toFixed(2) : null;
  return (
    <div className="mt-2 rounded-xl bg-slate-50 px-3 py-2 text-[12px]">
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-4">
        <Field label="Squadra" value={p.real_team ?? '—'} />
        <Field
          label="Da titolare"
          value={p.starts != null ? `${p.starts} su ${p.appearances} conv.` : `${p.appearances} conv.`}
        />
        <Field label="Minuti medi" value={`${p.avg_minutes}′`} />
        <Field label="Media voto" value={vote ?? '—'} hint={p.value_basis === 'estimate' ? 'stimata' : undefined} />
      </div>
      {p.next_match ? (
        <div className="mt-1.5 text-[11px] text-slate-500">
          Prossima: {p.next_match.home ? 'in casa contro' : 'in trasferta contro'}{' '}
          <b className="text-slate-700">{p.next_match.opponent}</b>
        </div>
      ) : null}
    </div>
  );
}

function Field({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-slate-400">{label}</div>
      <div className="font-semibold text-slate-700">
        {value}
        {hint ? <span className="ml-1 text-[10px] font-normal text-slate-400">({hint})</span> : null}
      </div>
    </div>
  );
}

function MinutesBadge({ label }: { label: MinutesLabel }) {
  // 'unknown' = no games to judge from (pre-season): say nothing rather than
  // labelling everybody as rarely used.
  if (label === 'unknown') return null;
  if (label === 'high') return <Badge tone="green">titolare abituale</Badge>;
  if (label === 'medium') return <Badge tone="slate">spesso impiegato</Badge>;
  return <Badge tone="amber">poco impiegato</Badge>;
}
