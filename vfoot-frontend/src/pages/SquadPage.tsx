import { useState } from 'react';
import { Card, SectionTitle, Badge } from '../components/ui';
import { useAsync } from '../utils/useAsync';
import { getTeamLineup } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import type { PlayerRole, MinutesLabel, TeamLineupPlayer } from '../types/lineup';

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

export default function SquadPage() {
  const { selectedLeagueId } = useLeagueContext();
  const { data, loading, error } = useAsync(
    () => (selectedLeagueId ? getTeamLineup(selectedLeagueId) : Promise.reject(new Error('Nessuna lega selezionata'))),
    [selectedLeagueId],
  );
  const [openPlayer, setOpenPlayer] = useState<number | null>(null);

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega per vedere la rosa.</div>;
  if (loading) return <div className="text-sm text-slate-500">Caricamento rosa…</div>;
  if (error || !data) return <div className="text-sm text-red-600">Errore: {error?.message ?? '…'}</div>;

  const roster = [...data.roster].sort((a, b) => b.price - a.price);
  const budget = data.budget;
  // Which season the playing-time stats describe, said plainly: pre-season these
  // are last year's, and a silent "poco impiegato" from stale data is the exact
  // confusion this note prevents.
  const statsNote = data.stats_season
    ? data.stats_is_reference
      ? `Presenze, minuti e impiego sono aggiornati al campionato in corso (${data.stats_season}).`
      : `Il campionato non è ancora iniziato: presenze, minuti e impiego si riferiscono alla stagione ${data.stats_season}.`
    : null;

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <SectionTitle>Squadra</SectionTitle>
        <div className="mt-1 text-xl font-black">{data.team.name}</div>
        <div className="text-sm text-slate-500">{roster.length} giocatori in rosa</div>

        {budget ? (
          <>
            <div className="mt-3 grid grid-cols-3 gap-2">
              <Stat label="Budget" value={budget.initial} />
              <Stat label="Speso" value={budget.spent} tone="rose" />
              <Stat label="Residuo" value={budget.remaining} tone="emerald" />
            </div>
            <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-slate-500">
              {(['GK', 'DEF', 'MID', 'ATT'] as PlayerRole[])
                .filter((r) => budget.by_role[r])
                .map((r) => (
                  <span key={r}>
                    {ROLE_NAME[r]}: <b className="text-slate-700">{budget.by_role[r]}</b>
                  </span>
                ))}
            </div>
          </>
        ) : null}
      </Card>

      {(['GK', 'DEF', 'MID', 'ATT'] as PlayerRole[]).map((role) => {
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
        <div className="flex shrink-0 items-center gap-2">
          <span className="font-mono text-sm font-bold text-slate-700">€{p.price}</span>
          <MinutesBadge label={p.minutes_label} />
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
        <Field label="Da titolare" value={`${p.starts} su ${p.appearances} conv.`} />
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
