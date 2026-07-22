import { Link } from 'react-router-dom';
import { Button, Card, SectionTitle } from '../ui';
import { MatchScoreHeader, type MatchHeaderVM } from './MatchScoreHeader';
import type {
  ClassicFixtureDetail,
  ClassicPlayerEvents,
  ClassicPlayerLine,
  ClassicRole,
  ClassicTeamDetail,
} from '../../types/classic';

// Classic-mode match detail: voto puro + bonus/malus = fantavoto per player, the
// ordered bench, and the substitutions that bring a benched player in for an s.v.
// starter. No zone pitch (classic has no zone duel).

const ROLE_LABEL: Record<ClassicRole, string> = { POR: 'POR', DIF: 'DIF', CEN: 'CEN', ATT: 'ATT' };
const ROLE_CHIP: Record<ClassicRole, string> = {
  POR: 'bg-amber-500',
  DIF: 'bg-blue-500',
  CEN: 'bg-emerald-500',
  ATT: 'bg-orange-500',
};

function fmt(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
}

// Goal / assist / card / own-goal markers shown next to a player's name.
function EventIcons({ ev }: { ev: ClassicPlayerEvents }) {
  const items: { node: string; n: number; title: string }[] = [
    { node: '⚽', n: ev.goals, title: 'gol' },
    { node: '👟', n: ev.assists, title: 'assist' },
    { node: '🟨', n: ev.yellow, title: 'ammonizione' },
    { node: '🟥', n: ev.red, title: 'espulsione' },
  ].filter((x) => x.n > 0);
  if (!items.length && !ev.own_goals) return null;
  return (
    <span className="ml-1 inline-flex items-center gap-0.5 align-middle">
      {items.map((x, i) => (
        <span key={i} title={x.title} className="text-[11px] leading-none">
          {x.node}
          {x.n > 1 ? <span className="text-[9px] text-slate-500">×{x.n}</span> : null}
        </span>
      ))}
      {ev.own_goals > 0 ? (
        <span title="autogol" className="rounded bg-rose-100 px-1 text-[9px] font-bold text-rose-700">
          AG{ev.own_goals > 1 ? `×${ev.own_goals}` : ''}
        </span>
      ) : null}
    </span>
  );
}

const DEF_MODE_LABEL: Record<string, string> = {
  add_own: 'aggiunto alla propria squadra',
  subtract_opponent: 'sottratto alla squadra avversaria',
};

export function ClassicMatchDetail({
  fixture,
  backTo,
  backLabel = '← Partite',
}: {
  fixture: ClassicFixtureDetail;
  backTo: string;
  backLabel?: string;
}) {
  const d = fixture;
  const header: MatchHeaderVM = {
    homeName: d.home_team,
    awayName: d.away_team,
    homeGoals: d.home_goals,
    awayGoals: d.away_goals,
    result: d.result,
    homeSubtitle: `Fantavoto ${fmt(d.home_total)}`,
    awaySubtitle: `Fantavoto ${fmt(d.away_total)}`,
  };

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <MatchScoreHeader
          header={header}
          eyebrow={
            <SectionTitle>
              {d.stage ? d.stage : `Giornata ${d.fantasy_round}`} · Serie A reale {d.real_matchday}
            </SectionTitle>
          }
          action={
            <Link to={backTo}>
              <Button variant="ghost" size="sm">
                {backLabel}
              </Button>
            </Link>
          }
          footer={
            <div className="text-[11px] text-slate-500">
              Fantavoto = <b>voto puro</b> + <span className="text-emerald-600">bonus</span> −{' '}
              <span className="text-rose-600">malus</span> (gol +3, assist +1, autogol −2, rig. sbagliato
              −3, rig. parato +3, giallo −0,5, rosso −1, portiere −1 a gol subito). Un titolare <b>s.v.</b>{' '}
              è rimpiazzato dal primo panchinaro utile (in ordine di panchina) che mantiene la formazione valida.
              {d.defense_bonus_mode ? (
                <>
                  {' '}
                  Modificatore difesa: <b>{DEF_MODE_LABEL[d.defense_bonus_mode] ?? d.defense_bonus_mode}</b>.
                </>
              ) : null}
            </div>
          }
        />
      </Card>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <TeamColumn name={d.home_team} team={d.home} />
        <TeamColumn name={d.away_team} team={d.away} />
      </div>
    </div>
  );
}

function TeamColumn({ name, team }: { name: string; team: ClassicTeamDetail }) {
  return (
    <Card className="p-4">
      <div className="flex items-baseline justify-between">
        <SectionTitle>{name}</SectionTitle>
        <div className="text-sm text-slate-600">
          {team.goals} gol · <b>{fmt(team.total)}</b> fanta
        </div>
      </div>
      <div className="mt-0.5 text-[11px]">
        {team.defense.eligible ? (
          <span className="text-slate-600">
            🛡 Modificatore difesa: media <b>{fmt(team.defense.avg ?? 0)}</b> →{' '}
            <b className="text-emerald-700">+{fmt(team.defense.bonus)}</b>
          </span>
        ) : (
          <span className="text-slate-400">🛡 Modificatore difesa non attivo (servono ≥4 difensori titolari)</span>
        )}
        {team.defense.applied !== 0 ? (
          <span className="text-slate-400">
            {' '}
            · totale {fmt(team.base_total)} {team.defense.applied >= 0 ? '+' : '−'}
            {fmt(Math.abs(team.defense.applied))} = {fmt(team.total)}
          </span>
        ) : null}
      </div>

      <div className="mt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Titolari</div>
      <div className="divide-y">
        {team.starters.map((p) => (
          <PlayerRow key={p.player_id} p={p} />
        ))}
      </div>

      <div className="mt-4 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        Panchina · ordine = priorità
      </div>
      <div className="divide-y">
        {team.bench.map((p, i) => (
          <PlayerRow key={p.player_id} p={p} order={i + 1} bench />
        ))}
      </div>
    </Card>
  );
}

function PlayerRow({ p, order, bench = false }: { p: ClassicPlayerLine; order?: number; bench?: boolean }) {
  const played = !p.sv && p.fantavoto != null;
  // a benched player who never entered and has no vote is greyed out
  const inactive = bench && !p.entered && !played;
  return (
    <div className={`flex items-center justify-between gap-2 py-1.5 ${inactive ? 'opacity-50' : ''}`}>
      <div className="flex min-w-0 items-center gap-2">
        {order != null ? (
          <span className="w-4 shrink-0 text-right text-[11px] font-semibold tabular-nums text-slate-400">{order}</span>
        ) : null}
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ${ROLE_CHIP[p.role]}`}>
          {ROLE_LABEL[p.role]}
        </span>
        <span className="min-w-0">
          <span className={`block truncate text-sm font-semibold text-slate-800 ${p.replaced_by ? 'line-through opacity-60' : ''}`}>
            {p.name}
            {p.minutes > 0 ? <span className="ml-1 text-[11px] font-normal text-slate-400">{p.minutes}′</span> : null}
            <EventIcons ev={p.events} />
          </span>
          {/* annotation line — always reserved (fixed height) so every row has the
              same height and the two teams' bench sections start at the same point */}
          <span className="block h-[15px] truncate text-[11px] leading-[15px]">
            {p.replaced_by ? (
              <span className="text-slate-500">↓ esce · entra {p.replaced_by.name}</span>
            ) : p.entered && p.entered_for ? (
              <span className="font-semibold text-emerald-600">▲ entra per {p.entered_for.name}</span>
            ) : null}
          </span>
        </span>
      </div>

      <div className="flex shrink-0 items-center gap-2 text-right">
        {p.sv ? (
          <span className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-bold text-slate-500">S.V.</span>
        ) : (
          <>
            <span className="text-[11px] text-slate-500">{fmt(p.voto_puro ?? 0)}</span>
            {p.bonus > 0 ? <span className="text-[11px] font-semibold text-emerald-600">+{fmt(p.bonus)}</span> : null}
            {p.malus > 0 ? <span className="text-[11px] font-semibold text-rose-600">−{fmt(p.malus)}</span> : null}
            <span
              className={`w-9 text-sm font-bold tabular-nums ${(p.fantavoto ?? 0) >= 6 ? 'text-emerald-700' : 'text-rose-700'}`}
            >
              {fmt(p.fantavoto ?? 0)}
            </span>
          </>
        )}
      </div>
    </div>
  );
}
