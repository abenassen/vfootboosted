import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Button, Card, SectionTitle } from '../ui';
import { MatchScoreHeader, type MatchHeaderVM } from './MatchScoreHeader';
import { MatchManagers } from './MatchManagers';
import type {
  ClassicDefenseBonus,
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
  POR: 'bg-warn',
  DIF: 'bg-blue-500',
  CEN: 'bg-good',
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
          {x.n > 1 ? <span className="text-[9px] text-ink-faint">×{x.n}</span> : null}
        </span>
      ))}
      {ev.own_goals > 0 ? (
        <span title="autogol" className="rounded bg-bad-bg px-1 text-[9px] font-bold text-bad">
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
function svKind(p: ClassicPlayerLine): 'non_entrato' | 'dati_mancanti' | 'in_campo' | 'sv' {
  if (p.sv_reason === 'in_campo') return 'in_campo';
  if (p.sv_reason === 'non_entrato') return 'non_entrato';
  if (p.sv_reason === 'dati_mancanti') return p.minutes ? 'dati_mancanti' : 'non_entrato';
  return 'sv';
}

const DEF_MODE_LABEL: Record<string, string> = {
  add_own: 'aggiunto alla propria squadra',
  subtract_opponent: 'sottratto alla squadra avversaria',
};

const DEF_GATE_LABEL: Record<string, string> = {
  starters: 'almeno 4 difensori schierati dal 1’',
  effective: 'almeno 4 difensori con voto a fine giornata',
};

/** Perché il modificatore non è scattato, con le parole della regola che l’ha
 *  fermato. Dirlo dal `reason` e non dalla regola più comune non è pignoleria: la
 *  lega sceglie quale delle due difese deve essere di quattro, e una riga fissa
 *  finiva per accusare del difensore mancante chi invece aveva perso il portiere. */
function defenseReason(d: ClassicDefenseBonus): string {
  switch (d.reason) {
    case 'meno_di_4_difensori_titolari':
      return 'servono ≥4 difensori schierati dal 1’';
    case 'meno_di_4_difensori_con_voto':
      return 'servono ≥4 difensori con voto';
    case 'meno_di_3_difensori_con_voto':
      return 'meno di 3 difensori con voto';
    case 'portiere_senza_voto':
      return 'portiere senza voto';
    case 'disattivato':
      return 'spento in questa lega';
    default:
      // Referto vecchio o motivo che non conosciamo: si dice quel che serve,
      // secondo il cancello con cui è stato calcolato.
      return `servono ${DEF_GATE_LABEL[d.gate ?? 'starters']}`;
  }
}

/** A number that is still moving. Same mark everywhere it appears — on a single
 *  vote, on a team total, on the fixture — because it is the same statement: the
 *  real match behind it has not settled, so this will change.
 *
 *  VIOLET, not red, and that is not a taste. This row already speaks in colour:
 *  emerald is a bonus, rose is a malus, and the fantavoto itself is one or the
 *  other side of six. A red mark next to a red number reads as "another malus".
 *  Violet is the only strong colour the row does not already use for something. */
function LiveBadge({
  label = 'live',
  title = 'Il dato arriva da una partita ancora in corso: questo numero può ancora cambiare.',
}: { label?: string; title?: string }) {
  return (
    <span
      title={title}
      className="inline-flex shrink-0 items-center gap-1 rounded-full bg-live-bg px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wide text-live"
    >
      <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-live" />
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
                {/* "Turno" is the competition's own unit, "giornata" is Serie A's,
                    and they are never the same word. The stage name wins when there
                    is one: "Semifinali" says more than any number. */}
                {d.stage ? d.stage : `Turno ${d.fantasy_round}`} · giornata {d.real_matchday}
              </SectionTitle>
              {/* "In corso" and "provvisorio" are not the same claim, and one badge
                  for both told the wrong one half the time: a match that ENDED
                  twenty minutes ago still carries movable votes (the provider
                  confirms an hour later), and labelling that "in corso" says the
                  ball is still rolling. The clock rides with the live label —
                  from the appearances, so it costs nothing. */}
              {d.live ? (
                <LiveBadge label={d.minute != null ? `in corso · ${d.minute}'` : 'in corso'} />
              ) : d.provisional ? (
                <LiveBadge
                  label="provvisorio"
                  title="La partita è finita, ma i dati non sono ancora confermati: questi numeri possono cambiare di poco."
                />
              ) : null}
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
            <div className="text-[11px] text-ink-faint">
              Fantavoto = <b>voto puro</b> + <span className="text-good">bonus</span> −{' '}
              <span className="text-bad">malus</span> (gol +3, assist +1, autogol −2, rig. sbagliato
              −3, rig. parato +3, giallo −0,5, rosso −1, portiere −1 a gol subito).
              {!realMatch ? (
                <>
                  {' '}
                  Un titolare <b>s.v.</b> è rimpiazzato dal primo panchinaro utile (in ordine di panchina)
                  che mantiene la formazione valida.
                  {d.sv_office_vote
                    ? ` Se non ce n’è, il buco vale ${fmt(d.sv_office_vote)} d’ufficio.`
                    : ' Se non ce n’è, il suo posto non vale niente.'}
                  {d.defense_bonus_mode ? (
                    <>
                      {' '}
                      Modificatore difesa: <b>{DEF_MODE_LABEL[d.defense_bonus_mode] ?? d.defense_bonus_mode}</b>,
                      a chi ha <b>{DEF_GATE_LABEL[d.defense_bonus_gate ?? 'starters']}</b>.
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

      {/* In fondo, chi ha schierato tutto questo. Su una partita vera di Serie A
          non c'è: nessuno dei due allenatori del campionato ha un account qui, e
          il payload delle pagelle infatti non porta nessun fantallenatore. */}
      {!realMatch ? (
        <MatchManagers
          home={d.home_manager}
          away={d.away_manager}
          homeTeam={d.home_team}
          awayTeam={d.away_team}
          result={d.result}
        />
      ) : null}
    </div>
  );
}

function TeamColumn({
  name,
  team,
  realMatch,
}: {
  name: string;
  team: ClassicTeamDetail;
  realMatch: boolean;
}) {
  // Il bonus casa viaggia come un modificatore qualunque nel payload: lo si
  // legge da lì invece di ricalcolarlo, così il tabellino non può dissentire
  // dal punteggio che sta mostrando.
  const homeBonus =
    team.modifiers?.find((m) => m.key === 'home_advantage' && m.eligible)?.value ?? 0;
  return (
    <Card className="p-4">
      <div className="flex items-baseline justify-between gap-2">
        <SectionTitle>{name}</SectionTitle>
        <div className="flex items-center gap-1.5 text-sm text-ink-soft">
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
            <span className="text-ink-soft">
              🛡 Modificatore difesa: media <b>{fmt(team.defense.avg ?? 0)}</b> →{' '}
              <b className="text-good">+{fmt(team.defense.bonus)}</b>
            </span>
          ) : (
            <span className="text-ink-faint">🛡 Modificatore difesa non attivo ({defenseReason(team.defense)})</span>
          )}
          {team.defense.applied !== 0 ? (
            <span className="text-ink-faint">
              {' '}
              · totale {fmt(team.base_total)} {team.defense.applied >= 0 ? '+' : '−'}
              {fmt(Math.abs(team.defense.applied))} = {fmt(team.total)}
            </span>
          ) : null}
          {/* Il fattore campo si vede solo dove è stato assegnato: dirlo anche a
              chi gioca fuori casa ("non hai preso il bonus") sarebbe rumore. */}
          {homeBonus ? (
            <div className="text-ink-soft">
              🏟 Fattore campo: <b className="text-good">+{fmt(homeBonus)}</b>
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="mt-3 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">Titolari</div>
      <div className="divide-y">
        {team.starters.map((p) => (
          <PlayerRow key={p.player_id} p={p} />
        ))}
      </div>

      <div className="mt-4 text-[11px] font-semibold uppercase tracking-wide text-ink-faint">
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
  // He is on the pitch of a match in progress and has no vote YET. Not a senza
  // voto, and the row has to stop treating him like one twice over: he carries his
  // own pulsing badge (so the generic "live" one beside it would say it again),
  // and a substitute who has just come on is anything but inactive.
  const onPitchNow = p.sv && svKind(p) === 'in_campo';
  // a benched player who never entered and has no vote is greyed out
  const inactive = bench && !p.entered && !played && !onPitchNow;
  return (
    <>
    <div className={`flex items-center justify-between gap-2 py-1.5 ${inactive ? 'opacity-50' : ''}`}>
      <div className="flex min-w-0 items-center gap-2">
        {order != null ? (
          <span className="w-4 shrink-0 text-right text-[11px] font-semibold tabular-nums text-ink-faint">{order}</span>
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
                ? 'rounded border border-dashed border-line px-1.5 py-0.5 text-[10px] font-bold leading-none text-ink-faint'
                : `rounded px-1.5 py-0.5 text-[10px] font-bold leading-none text-white ${ROLE_CHIP[role]}`
            }
          >
            {ROLE_LABEL[role]}
            {p.role_known === false ? '?' : ''}
          </span>
        ) : null}
        <span className="min-w-0">
          <span className={`block truncate text-sm font-semibold text-ink ${p.replaced_by ? 'line-through opacity-60' : ''}`}>
            {p.name}
            {p.minutes > 0 ? <span className="ml-1 text-[11px] font-normal text-ink-faint">{p.minutes}′</span> : null}
            <EventIcons ev={p.events} />
          </span>
          {/* annotation line — always reserved (fixed height) so every row has the
              same height and the two teams' bench sections start at the same point */}
          <span className="block h-[15px] truncate text-[11px] leading-[15px]">
            {p.replaced_by ? (
              <span className="text-ink-faint">↓ esce · entra {p.replaced_by.name}</span>
            ) : p.entered && p.entered_for ? (
              <span className="font-semibold text-good">▲ entra per {p.entered_for.name}</span>
            ) : null}
          </span>
        </span>
      </div>

      <div className="flex shrink-0 items-center gap-2 text-right">
        {/* Outside the s.v. branch on purpose: a player of a match in progress is
            provisional whether he has a vote yet or not. A reserve keeper reading
            a flat "n.d." at the fortieth minute says "we have nothing on him",
            when what is true is "not yet". */}
        {p.provisional && !onPitchNow ? <LiveBadge /> : null}
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
            className="rounded border border-dashed border-accent px-1.5 py-0.5 text-[10px] font-bold text-accent"
          >
            non ancora giocata
          </span>
        ) : p.sv ? (
          // 'dati mancanti' is not a verdict on the player — say so, rather than
          // letting a gap in our data read as "he did nothing".
          svKind(p) === 'in_campo' ? (
            // He is playing RIGHT NOW and we have nothing on him yet — which is
            // not a senza voto and must not be printed as one. S.V. is a verdict
            // on a finished performance; at the fifth minute there is no
            // performance to judge, only a match that has barely started.
            <span
              title="È in campo: la partita è in corso e il suo voto non è ancora determinabile"
              className="inline-flex items-center gap-1 rounded-full bg-live-bg px-1.5 py-0.5 text-[10px] font-bold text-live"
            >
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-live" />
              in campo
            </span>
          ) : svKind(p) === 'non_entrato' ? (
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
              className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] font-bold text-ink-faint"
            >
              {p.provisional ? 'in panchina' : 'non ha giocato'}
            </span>
          ) : svKind(p) === 'dati_mancanti' ? (
            <span
              title="Ha giocato, ma non abbiamo la sua prestazione per questa partita"
              className="rounded border border-dashed border-warn px-1.5 py-0.5 text-[10px] font-bold text-warn"
            >
              n.d.
            </span>
          ) : (
            <span
              title="Senza voto: impiego insufficiente"
              className="rounded bg-surface-2 px-1.5 py-0.5 text-[10px] font-bold text-ink-faint"
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
                className="text-[11px] text-ink-faint underline decoration-dotted underline-offset-2 hover:text-ink"
              >
                {fmt(p.voto_puro ?? 0)}
              </button>
            ) : (
              <span className="text-[11px] text-ink-faint">{fmt(p.voto_puro ?? 0)}</span>
            )}
            {p.office ? (
              <span
                title={
                  p.sv_filled
                    ? "Voto d'ufficio: non ha preso voto e in panchina non c'era un rimpiazzo utile, la lega copre il buco"
                    : "Voto d'ufficio: la lega ha imposto questo voto per una partita non giocata"
                }
                className="rounded bg-accent/10 px-1.5 py-0.5 text-[10px] font-bold text-accent"
              >
                ufficio
              </span>
            ) : null}
            {p.bonus > 0 ? <span className="text-[11px] font-semibold text-good">+{fmt(p.bonus)}</span> : null}
            {p.malus > 0 ? <span className="text-[11px] font-semibold text-bad">−{fmt(p.malus)}</span> : null}
            <span
              className={`w-9 text-sm font-bold tabular-nums ${(p.fantavoto ?? 0) >= 6 ? 'text-good' : 'text-bad'}`}
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
      <span className="text-ink-soft">{label}</span>
      <span className={`shrink-0 font-mono text-[11px] font-semibold ${pts >= 0 ? 'text-good' : 'text-bad'}`}>
        {fmtPts(pts)}
      </span>
    </div>
  );
  return (
    <div className="mb-2 ml-8 rounded-xl bg-surface-2 px-3 py-2 text-[12px]">
      <div className="mb-1 flex items-baseline justify-between text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
        <span>Come nasce il voto puro</span>
        <span>{why.minutes}′ giocati</span>
      </div>
      <div className="space-y-0.5">
        <div className="flex items-baseline justify-between gap-3 text-ink-faint">
          <span>Media del ruolo</span>
          <span className="shrink-0 font-mono text-[11px] font-semibold">{why.base.toFixed(1)}</span>
        </div>
        {why.contributions.map((c) => line(c.label, c.points))}
        {why.other_count > 0 ? line(`altre ${why.other_count} voci minori`, why.other_points, '__other') : null}
        <div className="mt-1 flex items-baseline justify-between gap-3 border-t border-line pt-1 font-semibold text-ink">
          <span>Voto puro</span>
          <span className="shrink-0 font-mono">
            {why.voto.toFixed(1)}
            {Math.abs(why.subtotal - why.voto) >= 0.05 ? (
              <span className="ml-1 text-[10px] font-normal text-ink-faint">({why.subtotal.toFixed(2)} arrotondato)</span>
            ) : null}
          </span>
        </div>
      </div>
      {why.note ? <div className="mt-1.5 text-[11px] text-ink-faint">{why.note}</div> : null}
      {/* Il conto dice COME si compone questo voto; la guida dice PERCHE' le voci
          pesano cosi' e perche' il numero non e' quello del giornale. La domanda
          nasce qui, quindi la risposta si raggiunge da qui. */}
      <Link
        to="/voto-puro"
        className="mt-1.5 inline-block text-[11px] font-semibold text-accent underline decoration-dotted"
      >
        Come nasce il voto puro, in generale →
      </Link>
    </div>
  );
}
