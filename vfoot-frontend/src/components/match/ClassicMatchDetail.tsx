import { useState } from 'react';
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
//
// `ev` is OPTIONAL, and the guard is the whole point. A placeholder line — senza
// voto, imposed vote, club that has not played — carries no events at all, and
// reading one threw here and took the entire tabellino down with it: a white page
// where the crash was, with nothing on screen to say so. The absence is a normal
// state with an obvious rendering, which is no marks at all.
function EventIcons({ ev }: { ev?: ClassicPlayerEvents }) {
  if (!ev) return null;
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

const LINEUP_TO_ROLE: Record<string, ClassicRole> = {
  GK: 'POR',
  DEF: 'DIF',
  MID: 'CEN',
  ATT: 'ATT',
};

/** The role to draw on the chip.
 *
 *  `role` is read off the PERFORMANCE, so a placeholder line — nobody who has not
 *  taken the field — has none, and the chip came out blank: an empty coloured box
 *  next to a name, on exactly the rows a manager is scanning to see WHO of his is
 *  still to play. `lineup_role` is on every line and says the same thing in the
 *  lineup's vocabulary.
 *
 *  Drawn solid, not dashed: this is not an inference from match data (which is what
 *  `role_known === false` marks) but the league's own frozen role — the very one the
 *  save endpoint validated the lineup against. */
function roleOf(p: ClassicPlayerLine): ClassicRole | null {
  return p.role ?? LINEUP_TO_ROLE[p.lineup_role] ?? null;
}

/** Which of the three s.v. this is, reading a frozen payload for what it means.
 *
 *  Before the backend told them apart, an unused substitute was written down as
 *  `dati_mancanti` — "no data" — which says the opposite of the truth: we have his
 *  data, and it says he never came on. Zero minutes settles it without a migration,
 *  and it is the same test the backend now makes at the source. A real hole keeps
 *  its badge: minutes on the pitch and no performance behind them. */
function svKind(p: ClassicPlayerLine): 'non_entrato' | 'dati_mancanti' | 'sv' {
  if (p.sv_reason === 'non_entrato') return 'non_entrato';
  if (p.sv_reason === 'dati_mancanti') return p.minutes ? 'dati_mancanti' : 'non_entrato';
  return 'sv';
}

const DEF_MODE_LABEL: Record<string, string> = {
  add_own: 'aggiunto alla propria squadra',
  subtract_opponent: 'sottratto alla squadra avversaria',
};

/** A number that is still moving. Same mark everywhere it appears — on a single
 *  vote, on a team total, on the fixture — because it is the same statement: the
 *  real match behind it has not settled, so this will change.
 *
 *  VIOLET, not red, and that is not a taste. This row already speaks in colour:
 *  emerald is a bonus, rose is a malus, and the fantavoto itself is one or the
 *  other side of six. A red mark next to a red number reads as "another malus".
 *  Violet is the only strong colour the row does not already use for something. */
function LiveBadge({ label = 'live' }: { label?: string }) {
  return (
    <span
      title="Il dato arriva da una partita ancora in corso: questo numero può ancora cambiare."
      className="inline-flex shrink-0 items-center gap-1 rounded-full bg-violet-100 px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-violet-700"
    >
      <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-violet-500" />
      {label}
    </span>
  );
}

export function ClassicMatchDetail({
  fixture,
  backTo,
  backLabel = '← Partite',
  variant = 'fantasy',
}: {
  fixture: ClassicFixtureDetail;
  backTo: string;
  backLabel?: string;
  // 'real' renders the pagelle of an actual Serie A match: the per-player voto puro
  // + bonus/malus is meaningful, but fantasy-scoring constructs (team fantavoto
  // total, defence modifier, bench priority / s.v. replacement) are not — they
  // belong to a vfoot fixture, not to the real game, so they are hidden here.
  variant?: 'fantasy' | 'real';
}) {
  const d = fixture;
  const realMatch = variant === 'real';
  const header: MatchHeaderVM = {
    homeName: d.home_team,
    awayName: d.away_team,
    homeGoals: d.home_goals,
    awayGoals: d.away_goals,
    result: d.result,
    homeSubtitle: realMatch ? undefined : `Fantavoto ${fmt(d.home_total)}`,
    awaySubtitle: realMatch ? undefined : `Fantavoto ${fmt(d.away_total)}`,
  };

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <MatchScoreHeader
          header={header}
          eyebrow={
            <div className="flex flex-wrap items-center gap-2">
              <SectionTitle>
                {d.stage ? d.stage : `Giornata ${d.fantasy_round}`} · Serie A reale {d.real_matchday}
              </SectionTitle>
              {d.provisional ? <LiveBadge label="in corso" /> : null}
            </div>
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
              −3, rig. parato +3, giallo −0,5, rosso −1, portiere −1 a gol subito).
              {!realMatch ? (
                <>
                  {' '}
                  Un titolare <b>s.v.</b> è rimpiazzato dal primo panchinaro utile (in ordine di panchina)
                  che mantiene la formazione valida.
                  {d.defense_bonus_mode ? (
                    <>
                      {' '}
                      Modificatore difesa: <b>{DEF_MODE_LABEL[d.defense_bonus_mode] ?? d.defense_bonus_mode}</b>.
                    </>
                  ) : null}
                </>
              ) : null}
            </div>
          }
        />
      </Card>

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <TeamColumn name={d.home_team} team={d.home} realMatch={realMatch} />
        <TeamColumn name={d.away_team} team={d.away} realMatch={realMatch} />
      </div>
    </div>
  );
}

function TeamColumn({ name, team, realMatch }: { name: string; team: ClassicTeamDetail; realMatch: boolean }) {
  return (
    <Card className="p-4">
      <div className="flex items-baseline justify-between gap-2">
        <SectionTitle>{name}</SectionTitle>
        <div className="flex items-center gap-1.5 text-sm text-slate-600">
          {/* A total made in part of provisional votes is itself provisional —
              there is no honest way to show a settled number on unsettled ones. */}
          {team.provisional ? <LiveBadge label="provvisorio" /> : null}
          <span>
            {team.goals} gol{!realMatch ? <> · <b>{fmt(team.total)}</b> fanta</> : null}
          </span>
        </div>
      </div>
      {/* Defence modifier is a fantasy-scoring construct: it means nothing for a
          real Serie A match, so it is only shown on vfoot fixtures. */}
      {!realMatch ? (
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
      ) : null}

      <div className="mt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-500">Titolari</div>
      <div className="divide-y">
        {team.starters.map((p) => (
          <PlayerRow key={p.player_id} p={p} />
        ))}
      </div>

      <div className="mt-4 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
        {realMatch ? 'Panchina' : 'Panchina · ordine = priorità'}
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
  const [open, setOpen] = useState(false);
  const played = !p.sv && p.fantavoto != null;
  const role = roleOf(p);
  const why = p.explanation;
  const hasWhy = !!why && (why.contributions.length > 0 || why.other_count > 0);
  // a benched player who never entered and has no vote is greyed out
  const inactive = bench && !p.entered && !played;
  return (
    <>
    <div className={`flex items-center justify-between gap-2 py-1.5 ${inactive ? 'opacity-50' : ''}`}>
      <div className="flex min-w-0 items-center gap-2">
        {order != null ? (
          <span className="w-4 shrink-0 text-right text-[11px] font-semibold tabular-nums text-slate-400">{order}</span>
        ) : null}
        {/* A guessed role is drawn hollow with a '?': showing it solid would state
            as fact something we inferred because his squad data is incomplete.
            No role at all draws NOTHING — an empty coloured box is worse than a
            gap, because it looks like a chip whose label failed to load. */}
        {role ? (
          <span
            title={p.role_known === false ? 'Ruolo non disponibile: stimato dai dati della partita' : undefined}
            className={
              p.role_known === false
                ? 'rounded border border-dashed border-slate-400 px-1.5 py-0.5 text-[10px] font-bold leading-none text-slate-500'
                : `rounded px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ${ROLE_CHIP[role]}`
            }
          >
            {ROLE_LABEL[role]}
            {p.role_known === false ? '?' : ''}
          </span>
        ) : null}
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
        {/* Outside the s.v. branch on purpose: a player of a match in progress is
            provisional whether he has a vote yet or not. A reserve keeper reading
            a flat "n.d." at the fortieth minute says "we have nothing on him",
            when what is true is "not yet". */}
        {p.provisional ? <LiveBadge /> : null}
        {p.pending ? (
          // An unplayed match is not a senza voto and must not read like one:
          // nothing happened yet, the bench does not cover it, and the slot settles
          // when the match is played (or by an office vote, if it never is).
          //
          // "rinviata" was a lie for most of the players who land here. `pending`
          // has always meant "his club's match has not been played" — which covers
          // a genuine postponement AND the 20:45 kick-off that simply has not
          // happened yet, and on a round in progress the second is nearly all of
          // them. The badge now says the thing both cases have in common; the
          // reason is the round's business, not the row's.
          <span
            title="Il suo club non ha ancora giocato la partita di questa giornata"
            className="rounded border border-dashed border-sky-400 px-1.5 py-0.5 text-[10px] font-bold text-sky-600"
          >
            non ancora giocata
          </span>
        ) : p.sv ? (
          // 'dati mancanti' is not a verdict on the player — say so, rather than
          // letting a gap in our data read as "he did nothing".
          svKind(p) === 'non_entrato' ? (
            // The bench, said plainly. And it is a DIFFERENT sentence depending on
            // whether the match is over: at the fortieth minute "non ha giocato" is
            // not yet true, and a reserve keeper can still come on. `provisional`
            // is the same mark the rest of the row uses for "this can still move".
            <span
              title={
                p.provisional
                  ? 'Non ancora entrato: la partita è in corso, può ancora giocare'
                  : 'Non è entrato in campo: nessun minuto giocato'
              }
              className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-bold text-slate-500"
            >
              {p.provisional ? 'in panchina' : 'non ha giocato'}
            </span>
          ) : svKind(p) === 'dati_mancanti' ? (
            <span
              title="Ha giocato, ma non abbiamo la sua prestazione per questa partita"
              className="rounded border border-dashed border-amber-400 px-1.5 py-0.5 text-[10px] font-bold text-amber-600"
            >
              n.d.
            </span>
          ) : (
            <span
              title="Senza voto: impiego insufficiente"
              className="rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-bold text-slate-500"
            >
              S.V.
            </span>
          )
        ) : (
          <>
            {/* The voto puro itself opens the breakdown — it is the number the
                explanation is about, so nothing else needs to say so. A dotted
                underline is the only hint; plain when there is nothing to show. */}
            {hasWhy ? (
              <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                title="Mostra il dettaglio del voto"
                className="text-[11px] text-slate-500 underline decoration-dotted underline-offset-2 hover:text-slate-800"
              >
                {fmt(p.voto_puro ?? 0)}
              </button>
            ) : (
              <span className="text-[11px] text-slate-500">{fmt(p.voto_puro ?? 0)}</span>
            )}
            {p.office ? (
              <span
                title="Voto d'ufficio: la lega ha imposto questo voto per una partita non giocata"
                className="rounded bg-sky-100 px-1.5 py-0.5 text-[10px] font-bold text-sky-700"
              >
                ufficio
              </span>
            ) : null}
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
    {open && why ? <WhyThisVote why={why} /> : null}
    </>
  );
}

/** The breakdown behind a voto puro, laid out so it ADDS UP: it starts from the
 *  role average and every slice moves it, ending on the vote itself — so the
 *  number can actually be derived from the rows, not just illustrated. */
function WhyThisVote({ why }: { why: NonNullable<ClassicPlayerLine['explanation']> }) {
  const fmtPts = (n: number) => `${n > 0 ? '+' : n < 0 ? '−' : ''}${Math.abs(n).toFixed(2)}`;
  const line = (label: string, pts: number, key?: string) => (
    <div key={key ?? label} className="flex items-baseline justify-between gap-3">
      <span className="text-slate-600">{label}</span>
      <span className={`shrink-0 font-mono text-[11px] font-semibold ${pts >= 0 ? 'text-emerald-700' : 'text-rose-700'}`}>
        {fmtPts(pts)}
      </span>
    </div>
  );
  return (
    <div className="mb-2 ml-8 rounded-xl bg-slate-50 px-3 py-2 text-[12px]">
      <div className="mb-1 flex items-baseline justify-between text-[10px] font-semibold uppercase tracking-wide text-slate-400">
        <span>Come nasce il voto puro</span>
        <span>{why.minutes}′ giocati</span>
      </div>
      <div className="space-y-0.5">
        <div className="flex items-baseline justify-between gap-3 text-slate-500">
          <span>Media del ruolo</span>
          <span className="shrink-0 font-mono text-[11px] font-semibold">{why.base.toFixed(1)}</span>
        </div>
        {why.contributions.map((c) => line(c.label, c.points))}
        {why.other_count > 0 ? line(`altre ${why.other_count} voci minori`, why.other_points, '__other') : null}
        <div className="mt-1 flex items-baseline justify-between gap-3 border-t border-slate-200 pt-1 font-semibold text-slate-800">
          <span>Voto puro</span>
          <span className="shrink-0 font-mono">
            {why.voto.toFixed(1)}
            {Math.abs(why.subtotal - why.voto) >= 0.05 ? (
              <span className="ml-1 text-[10px] font-normal text-slate-400">({why.subtotal.toFixed(2)} arrotondato)</span>
            ) : null}
          </span>
        </div>
      </div>
      {why.note ? <div className="mt-1.5 text-[11px] text-slate-500">{why.note}</div> : null}
    </div>
  );
}
