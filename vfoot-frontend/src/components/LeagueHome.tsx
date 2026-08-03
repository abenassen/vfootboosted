import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  concludeLeagueMatchday,
  getActiveAuction,
  getCompetitionStructure,
  getLeagueActivity,
  getLeagueDetail,
  getLeagueFixtures,
  getLeagueMatchdays,
} from '../api';
// Not re-exported by the api facade, same as in MarketPage.
import { getMarketActive, type LeagueActivityItem } from '../api/backend';
import type { MarketSessionInfo } from '../types/market';
import clsx from 'clsx';
import { useLeagueContext } from '../league/LeagueContext';
import { competitionFormatLabel } from '../league/competitionFormat';
import { compColor, type CompColor } from '../league/competitionColors';
import { useDecisionAlerts } from '../league/useDecisionAlerts';
import { useLiveSocket } from '../hooks/useNudgeSocket';
import { Badge, Button, Card, SectionTitle } from './ui';
import Crest from './Crest';
import type {
  ActiveAuctionInfo,
  CompetitionItem,
  CompetitionStructure,
  LeagueDetail,
  LeagueFixtureItem,
  LeagueMatchdayItem,
  LeagueStandingRow,
  MatchdayImpact,
} from '../types/league';

/** How far ahead a fixture may be and still count as "prossima partita", measured
 *  in REAL matchdays — the unit the whole league is scheduled in.
 *
 *  Four is about a month of football: near enough that setting a lineup for it is
 *  a sensible thing to do now, far enough that a cup tie a fortnight out is not
 *  hidden. Beyond it the fixture is not something you can act on, and putting it
 *  beside this weekend's match only made both look equally urgent. */
const NEXT_MATCH_HORIZON = 4;

/** One glyph per kind of news. Not 'premio': that line already begins with the
 *  trophy the admin picked for the prize itself. */
const ACTIVITY_ICON: Record<LeagueActivityItem['kind'], string> = {
  acquisto: '🔁',
  decisione: '🗳️',
  giornata: '🏁',
  competizione: '🎌',
  premio: '🏆',
};

/** The league at a glance, in the order a participant actually wants it:
 *  my next matches first (with the way to field a team for each), then the last
 *  results, then what has been happening, and only then the league-wide tables
 *  and the roll call.
 *
 *  Two columns from `lg` up: stacked, the useful part was pushed below the fold
 *  by material nobody opens the app for.
 */
export default function LeagueHome({ competitions }: { competitions: CompetitionItem[] }) {
  const { selectedLeagueId, selectedLeague } = useLeagueContext();
  const isAdmin = selectedLeague?.role === 'admin';
  const myTeamName = selectedLeague?.team_name?.trim() || null;

  const [detail, setDetail] = useState<LeagueDetail | null>(null);
  const [fixtures, setFixtures] = useState<LeagueFixtureItem[]>([]);
  const [structures, setStructures] = useState<Record<number, CompetitionStructure>>({});
  const [matchdays, setMatchdays] = useState<LeagueMatchdayItem[]>([]);
  const [activity, setActivity] = useState<LeagueActivityItem[]>([]);
  const [auction, setAuction] = useState<ActiveAuctionInfo | null>(null);
  const [marketSession, setMarketSession] = useState<MarketSessionInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  // Bumped by the live socket. Everything on this page is derived from the same
  // five calls, so one counter in their dep array is the whole refresh.
  const [liveTick, setLiveTick] = useState(0);
  useLiveSocket(selectedLeagueId ?? null, useCallback(() => setLiveTick((n) => n + 1), []));

  useEffect(() => {
    if (!selectedLeagueId) return;
    let alive = true;
    void getLeagueDetail(selectedLeagueId).then((d) => alive && setDetail(d)).catch(() => {});
    void getLeagueFixtures(selectedLeagueId).then((f) => alive && setFixtures(f)).catch(() => {});
    void getLeagueMatchdays(selectedLeagueId).then((m) => alive && setMatchdays(m)).catch(() => {});
    void getLeagueActivity(selectedLeagueId, 5).then((a) => alive && setActivity(a)).catch(() => {});
    void getActiveAuction(selectedLeagueId).then((a) => alive && setAuction(a)).catch(() => {});
    void getMarketActive(selectedLeagueId)
      .then((m) => alive && setMarketSession(m.session))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [selectedLeagueId, liveTick]);

  useEffect(() => {
    if (!selectedLeagueId) return;
    let alive = true;
    void Promise.all(
      competitions.map((c) =>
        getCompetitionStructure(selectedLeagueId, c.competition_id)
          .then((s) => [c.competition_id, s] as const)
          .catch(() => null),
      ),
    ).then((entries) => {
      if (!alive) return;
      setStructures(
        Object.fromEntries(entries.filter(Boolean) as Array<readonly [number, CompetitionStructure]>),
      );
    });
    return () => {
      alive = false;
    };
  }, [selectedLeagueId, competitions]);

  const compName = useMemo(
    () => new Map(competitions.map((c) => [c.competition_id, c.name])),
    [competitions],
  );
  // Same accent everywhere the competition is named, so a shortcut and the block
  // it belongs to are recognisably the same thing.
  const compColorById = useMemo(
    () => new Map(competitions.map((c, i) => [c.competition_id, compColor(i)])),
    [competitions],
  );

  const mine = fixtures.filter((f) => f.is_user_involved);
  // One "next" per competition: a league can run a championship and a cup, and
  // they are fielded separately.
  //
  // "Next" means the next one you can still FIELD, not the next one the admin has
  // yet to score: a fixture stays `scheduled` until its matchday is concluded, so
  // keying on that alone kept offering a round played weeks ago — and hid the one
  // still open — every time an admin was late. A locked round that has not been
  // scored yet belongs to the ledger banner below, not here.
  //
  // IN DATE ORDER, and only what is actually near. Both parts were missing and
  // both misread the same way: the list was sorted by the competition's OWN round
  // number, which is not a date — a cup at its round 3 came before a championship
  // at its round 23 although the championship is this Saturday and the cup is in
  // May. And nothing was dropped, so a competition whose next tie is five rounds
  // out sat next to this weekend's match as if the two were equally imminent.
  const nextByCompetition = useMemo(() => {
    const out = new Map<number, LeagueFixtureItem>();
    const byDate = [...mine].sort(
      (a, b) =>
        (a.real_matchday ?? Number.POSITIVE_INFINITY) - (b.real_matchday ?? Number.POSITIVE_INFINITY) ||
        a.round_no - b.round_no,
    );
    for (const f of byDate) {
      if (f.status !== 'finished' && !f.lineup_locked && !out.has(f.competition_id)) {
        out.set(f.competition_id, f);
      }
    }
    // Map iteration preserves insertion order, so this is already date-ordered.
    const all = [...out.values()];
    const anchor = all.find((f) => typeof f.real_matchday === 'number')?.real_matchday;
    if (anchor == null) return all;
    return all.filter((f, i) => {
      // The nearest one is shown whatever the distance: if the whole league is a
      // month away, "nothing" would be a worse answer than "the first thing".
      if (i === 0) return true;
      if (typeof f.real_matchday !== 'number') return false;
      return f.real_matchday - anchor <= NEXT_MATCH_HORIZON;
    });
  }, [mine]);

  const lastResults = useMemo(
    () => [...mine].filter((f) => f.status === 'finished').sort((a, b) => b.round_no - a.round_no).slice(0, 4),
    [mine],
  );

  const alerts = useDecisionAlerts(selectedLeagueId ?? null);

  // What is waiting on the reader, from data already on the page. Derived rather
  // than fetched: every item here is something the page already knows, so the
  // block cannot claim a chore that does not exist.
  const todo = useMemo(() => {
    const items: Array<{
      key: string;
      icon: string;
      text: string;
      detail?: string;
      to: string;
      className?: string;
    }> = [];

    for (const f of nextByCompetition) {
      if (!f.can_set_lineup) continue;
      items.push({
        key: `lineup-${f.fixture_id}`,
        icon: '📋',
        text: `Formazione · ${compName.get(f.competition_id) ?? ''}`,
        detail: `${f.home_team.name} vs ${f.away_team.name}`,
        to: `/squad/formation?competition=${f.competition_id}&matchday=${f.real_matchday}`,
        className: compColorById.get(f.competition_id)?.text700,
      });
    }

    // The admin's number is his whole sign-off queue, a member's is only what he
    // was asked — the same distinction the menu badge makes.
    const pending = alerts.isAdmin ? alerts.blocking : alerts.attention;
    if (pending) {
      items.push({
        key: 'decisions',
        icon: '🗳️',
        text: `${pending} ${pending === 1 ? 'decisione' : 'decisioni'} in sospeso`,
        detail: alerts.isAdmin ? 'Bloccano il mercato finché non sono risolte.' : 'Ti è stato chiesto un parere.',
        to: '/decisioni',
      });
    }

    return items;
  }, [nextByCompetition, compName, compColorById, alerts]);

  // The two clocks, kept apart here exactly as they are on the server. What is
  // being played comes from the real calendar and moves on its own; what has been
  // counted is the admin's ledger and is allowed to lag. Showing both is what makes
  // a forgotten conclusion legible instead of looking like a broken league.
  const playingMd = matchdays.find((m) => m.is_playing) ?? null;
  const fieldableMd = matchdays.find((m) => m.is_fieldable) ?? null;
  const awaitingMds = matchdays.filter((m) => m.status === 'awaiting');
  // Every arrear, not only the one that is unblocked right now: closing them in
  // order is what the button does, and the count is the honest size of the backlog.
  const queue = matchdays.filter((m) => m.awaits_conclusion);
  // What ELSE is waiting on those matchdays. The league steps over an unclosed
  // round by design, so an admin has no reason to hurry — unless a competition
  // cannot be drawn until he does, which is invisible from anywhere else.
  const blockedPhases = useMemo(() => {
    const seen = new Set<number>();
    const out: MatchdayImpact[] = [];
    for (const md of [...queue, ...awaitingMds]) {
      for (const d of md.decides ?? []) {
        if (seen.has(d.stage_id)) continue;
        seen.add(d.stage_id);
        out.push(d);
      }
    }
    return out;
  }, [queue, awaitingMds]);

  // THE ROUND YOU ARE IN: begun and not yet counted. Not "being played" — that was
  // the first attempt and it was too narrow, because your own match came and went
  // between one kick-off and the next. A round begins on Saturday afternoon and is
  // yours to follow until the admin closes it, whether or not there is a ball
  // rolling at the moment you happen to open the page.
  //
  // Whichever is ON THE PITCH if any, otherwise the last one that has begun. Not
  // simply the last: a matchday PARKED for a postponement is reopened on the night
  // of the recovery — it is being played weeks after the rounds that overtook it —
  // and taking the highest number would have offered you round 22 while your round
  // 16 was being decided in front of you. With a late admin several rounds are
  // begun-and-unscored; those arrears belong to the banner above, not here.
  //
  // Declared here and not with the other memos on purpose: it reads `matchdays`
  // a few lines up, and a useMemo placed above them would name them in its
  // dependency array before the bindings exist.
  const openMd = useMemo(() => {
    const begun = matchdays.filter((m) => m.has_kicked_off && m.status !== 'concluded');
    return begun.find((m) => m.is_playing) ?? begun[begun.length - 1] ?? null;
  }, [matchdays]);

  // Three states, three headlines. "Si gioca" while there is football on; "Risultato
  // finale" once every real match has settled and only the admin's click is missing;
  // and the plain in-between, which is most of a weekend.
  const openPhase: 'playing' | 'final' | 'open' = openMd
    ? openMd.is_playing
      ? 'playing'
      : openMd.real_completion?.is_completed
      ? 'final'
      : 'open'
    : 'open';

  const openFixtures = useMemo(() => {
    if (!openMd) return [];
    return fixtures.filter(
      (f) => f.is_user_involved && f.real_matchday === openMd.real_matchday,
    );
  }, [fixtures, openMd]);

  // Close the whole arrears queue in order, stopping at the first one that needs a
  // decision (a team without a lineup) — that conversation lives in Gestione lega.
  const concludeQueue = () => {
    if (!selectedLeagueId || !queue.length) return;
    setBusy(true);
    setMsg(null);
    void queue
      .reduce(
        (chain, md) => chain.then(() => concludeLeagueMatchday(selectedLeagueId, md.fantasy_matchday_id).then(() => {})),
        Promise.resolve(),
      )
      .then(() => setMsg(queue.length > 1 ? 'Giornate concluse.' : 'Giornata conclusa.'))
      .catch((e: unknown) =>
        setMsg(
          `Non è stato possibile concludere qui: ${
            e instanceof Error ? e.message : String(e)
          }. Aprila da Gestione lega → Giornate.`,
        ),
      )
      .finally(() => {
        setBusy(false);
        void Promise.all([
          getLeagueMatchdays(selectedLeagueId).then(setMatchdays),
          getLeagueFixtures(selectedLeagueId).then(setFixtures),
          getLeagueActivity(selectedLeagueId, 5).then(setActivity),
        ]).catch(() => {});
      });
  };

  if (!competitions.length) return null;

  return (
    <div className="space-y-4">
      {msg ? <Card className="p-3 text-sm text-slate-700">{msg}</Card> : null}

      {queue.length || awaitingMds.length ? (
        <Card
          className={clsx(
            'border-l-4 p-4',
            queue.length ? 'border-emerald-500 bg-emerald-50' : 'border-amber-500 bg-amber-50',
          )}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="min-w-0">
              {queue.length ? (
                <>
                  <div className="text-sm font-bold text-emerald-900">
                    {queue.length === 1
                      ? `La giornata ${queue[0].real_matchday} è finita`
                      : `Ci sono ${queue.length} giornate da chiudere`}
                  </div>
                  <div className="text-xs text-emerald-800">
                    {isAdmin
                      ? 'Tutte le partite reali sono concluse: puoi calcolare i punteggi.'
                      : `In attesa che l'amministratore chiuda ${
                          queue.length === 1 ? 'la giornata' : 'le giornate'
                        } ${queue.map((m) => m.real_matchday).join(', ')}.`}
                    {/* The other clock, said out loud: the league has NOT stopped,
                        only the counting has. */}
                    {playingMd ? ` Intanto si gioca la giornata ${playingMd.real_matchday}.` : ''}
                  </div>
                </>
              ) : (
                <>
                  <div className="text-sm font-bold text-amber-900">
                    {awaitingMds.length === 1
                      ? `Giornata ${awaitingMds[0].real_matchday} in attesa di recupero`
                      : `Giornate ${awaitingMds.map((m) => m.real_matchday).join(', ')} in attesa di recupero`}
                  </div>
                  <div className="text-xs text-amber-800">
                    La lega è andata avanti: {awaitingMds.length === 1 ? 'verrà conteggiata' : 'verranno conteggiate'}{' '}
                    quando le partite rinviate saranno giocate.
                    {awaitingMds[0]?.awaiting_reason ? ` (${awaitingMds[0].awaiting_reason})` : ''}
                  </div>
                </>
              )}
            </div>
            {isAdmin && queue.length ? (
              <Button size="sm" disabled={busy} onClick={concludeQueue}>
                {busy
                  ? 'Concludo…'
                  : queue.length === 1
                  ? 'Concludi la giornata'
                  : `Chiudi le ${queue.length} giornate`}
              </Button>
            ) : null}
          </div>
          {/* Arrears AND a parked matchday can coexist: the second line keeps the
              parked one visible instead of letting the queue hide it. */}
          {queue.length && awaitingMds.length ? (
            <div className="mt-2 text-xs text-emerald-800">
              In attesa di recupero: giornata {awaitingMds.map((m) => m.real_matchday).join(', ')}.
            </div>
          ) : null}
          {/* The consequence nobody could see. A league advancing past an unclosed
              round is normal; a competition that cannot be drawn because of it is
              not, and it stays stuck without a single message anywhere. */}
          {blockedPhases.length ? (
            <div className="mt-2 rounded-lg border border-slate-300 bg-white/70 p-2 text-xs text-slate-700">
              <div className="font-semibold">
                {blockedPhases.length === 1
                  ? 'Una fase è ferma in attesa di queste giornate:'
                  : 'Alcune fasi sono ferme in attesa di queste giornate:'}
              </div>
              <ul className="mt-1 space-y-0.5">
                {blockedPhases.map((d) => (
                  <li key={d.stage_id}>
                    <b>
                      {d.competition_name} · {d.stage_name}
                    </b>{' '}
                    — {d.rule_text}
                    {d.at_risk ? (
                      <span className="ml-1 font-semibold text-amber-700">
                        (le sue giornate sono già passate: verrà spostata più avanti)
                      </span>
                    ) : d.target_matchday != null ? (
                      <span className="text-slate-500"> · in calendario alla giornata {d.target_matchday}</span>
                    ) : null}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </Card>
      ) : fieldableMd ? (
        <div className="px-1 text-xs text-slate-500">
          {playingMd
            ? `Si gioca la giornata ${playingMd.real_matchday} · prossima da schierare: la ${fieldableMd.real_matchday}`
            : `Prossima giornata da schierare: la ${fieldableMd.real_matchday}`}
        </div>
      ) : null}

      {/* The market, when there IS one. The old Lega page carried this banner and
          it was worth keeping: an auction is a live event you have to be told
          about, unlike a permission flag that is on from the day the league is
          created. */}
      {auction?.auction_id ? (
        <Card className="border-2 border-green-300 bg-green-50 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="flex items-center gap-2">
                <Badge tone="green">Live</Badge>
                <span className="font-bold">Asta in corso</span>
              </div>
              <div className="mt-1 text-sm text-slate-600">
                {auction.is_admin
                  ? 'Sei il banditore: entra per chiamare i giocatori e aggiudicare.'
                  : 'Entra per seguire l’asta e rilanciare in tempo reale.'}
              </div>
            </div>
            <Link to="/auction">
              <Button>Entra nella sala asta →</Button>
            </Link>
          </div>
        </Card>
      ) : marketSession ? (
        <Card className="border-l-4 border-sky-500 bg-sky-50 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-bold text-sky-900">Mercato aperto</div>
              <div className="text-xs text-sky-800">Puoi fare offerte sugli svincolati.</div>
            </div>
            <Link to="/market">
              <Button size="sm">Vai al mercato →</Button>
            </Link>
          </div>
        </Card>
      ) : null}

      {/* 0 — THE ROUND YOU ARE IN. Above everything else: while a round is open it
          is the only thing on this page anyone opens the app for. What it offers is
          the tabellino, NOT the lineup — the round has locked, and a "Formazione"
          button here could only end on a 409. */}
      {openFixtures.length ? (
        <Card
          className={clsx(
            'border-2 p-4',
            openPhase === 'playing'
              ? 'border-violet-200 bg-violet-50/60'
              : openPhase === 'final'
              ? 'border-emerald-200 bg-emerald-50/50'
              : 'border-slate-200',
          )}
        >
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <span
                className={clsx(
                  'inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white',
                  openPhase === 'playing'
                    ? 'bg-violet-600'
                    : openPhase === 'final'
                    ? 'bg-emerald-600'
                    : 'bg-slate-500',
                )}
              >
                {openPhase === 'playing' ? (
                  <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-white" />
                ) : null}
                {openPhase === 'playing'
                  ? 'Si gioca'
                  : openPhase === 'final'
                  ? 'Risultato finale'
                  : 'In corso'}
              </span>
              <SectionTitle className="!mb-0">Giornata {openMd?.real_matchday}</SectionTitle>
            </div>
            <span className="text-[11px] text-slate-500">
              {openPhase === 'playing'
                ? 'I voti si aggiornano mentre si gioca e restano provvisori fino a fine partita.'
                : openPhase === 'final'
                ? 'Tutte le partite reali sono finite: manca solo il conteggio della lega.'
                : `${openMd?.real_completion.completed ?? 0} partite di Serie A su ${
                    openMd?.real_completion.total ?? 0
                  } sono già archiviate.`}
            </span>
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {openFixtures.map((f) => (
              <Link
                key={f.fixture_id}
                to={`/matches/${f.fixture_id}`}
                className="block rounded-xl border border-slate-200 bg-white p-3 transition hover:border-slate-300 hover:shadow-sm"
              >
                <div
                  className={clsx(
                    'text-[11px] font-bold uppercase tracking-wide',
                    compColorById.get(f.competition_id)?.text700 ?? 'text-slate-500',
                  )}
                >
                  {compName.get(f.competition_id) ?? 'Competizione'}
                </div>
                <div className="mt-1 flex items-center gap-2 text-sm font-semibold">
                  <Crest descriptor={f.home_team.crest} teamName={f.home_team.name} size={22} />
                  <span className="truncate">{f.home_team.name}</span>
                  {/* The running score, which is the whole reason to look. */}
                  <span className="shrink-0 font-mono tabular-nums text-slate-700">
                    {f.score ? `${Math.round(f.score.home_total)}–${Math.round(f.score.away_total)}` : 'vs'}
                  </span>
                  <span className="truncate">{f.away_team.name}</span>
                  <Crest descriptor={f.away_team.crest} teamName={f.away_team.name} size={22} />
                </div>
                <div className="mt-1.5 text-[11px] font-semibold text-slate-500">
                  {openPhase === 'playing' ? 'Segui i voti in diretta →' : 'Apri il tabellino →'}
                </div>
              </Link>
            ))}
          </div>
        </Card>
      ) : null}

      {/* 1 — my next matches, and how to field a team for each */}
      {nextByCompetition.length ? (
        <Card className="p-4">
          <SectionTitle>{nextByCompetition.length > 1 ? 'Le tue prossime partite' : 'La tua prossima partita'}</SectionTitle>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {nextByCompetition.map((f) => (
              <div key={f.fixture_id} className="rounded-xl border border-slate-200 p-3">
                {/* Which competition, on the shortcut itself: with a championship
                    and a cup running together, "Imposta formazione" alone does
                    not say which team sheet you are about to fill. */}
                <div
                  className={clsx(
                    'text-[11px] font-bold uppercase tracking-wide',
                    compColorById.get(f.competition_id)?.text700 ?? 'text-slate-500',
                  )}
                >
                  {compName.get(f.competition_id) ?? 'Competizione'}
                </div>
                <div className="mt-1 flex items-center gap-2 text-sm font-semibold">
                  <Crest descriptor={f.home_team.crest} teamName={f.home_team.name} size={22} />
                  <span className="truncate">{f.home_team.name}</span>
                  <span className="text-slate-400">vs</span>
                  <span className="truncate">{f.away_team.name}</span>
                  <Crest descriptor={f.away_team.crest} teamName={f.away_team.name} size={22} />
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {/* TURNO for the unit inside a competition, GIORNATA for the real
                      Serie A one — never the same word for both, which is what this
                      line used to do two words apart ("Giornata 3 · giornata reale
                      27"). `round_label` already carries the knockout's own name
                      ("Semifinali"), which beats any number. */}
                  {f.round_label ?? `Turno ${f.round_no}`}
                  {typeof f.real_matchday === 'number' ? ` · giornata ${f.real_matchday}` : ''}
                </div>
                {f.can_set_lineup ? (
                  <Link
                    to={`/squad/formation?competition=${f.competition_id}&matchday=${f.real_matchday}`}
                    className={clsx(
                      'mt-2 inline-flex rounded-lg px-2.5 py-1 text-[11px] font-semibold text-white hover:opacity-90',
                      compColorById.get(f.competition_id)?.bg700 ?? 'bg-slate-900',
                    )}
                  >
                    Formazione · {compName.get(f.competition_id) ?? ''}
                  </Link>
                ) : (
                  <div className="mt-2 text-[11px] text-slate-400">
                    La formazione si imposta quando hai una rosa.
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-2">
        {/* 2 — what is waiting for YOU. Beside the news, because one is what the
            league did and the other is what it is waiting on you to do. */}
        <Card className="p-4">
          <SectionTitle>Da fare</SectionTitle>
          {todo.length ? (
            <ul className="mt-2 space-y-1.5">
              {todo.map((t) => (
                <li key={t.key}>
                  <Link
                    to={t.to}
                    className="flex items-start gap-2 rounded-lg px-1 py-1 text-sm hover:bg-slate-50"
                  >
                    <span className="mt-0.5 shrink-0" aria-hidden>{t.icon}</span>
                    <span className="min-w-0">
                      <span className={clsx('block font-semibold', t.className ?? 'text-slate-700')}>{t.text}</span>
                      {t.detail ? <span className="block text-xs text-slate-500">{t.detail}</span> : null}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          ) : (
            <div className="mt-2 text-sm text-slate-500">Sei in pari: niente che aspetti te.</div>
          )}
        </Card>

        {/* 3 — how the last ones went */}
        {lastResults.length ? (
          <Card className="p-4">
            <SectionTitle>Ultimi risultati</SectionTitle>
            <div className="mt-2 space-y-1">
              {lastResults.map((f) => (
                <MiniFixture
                  key={f.fixture_id}
                  f={f}
                  competition={compName.get(f.competition_id)}
                  competitionClass={compColorById.get(f.competition_id)?.text700}
                />
              ))}
            </div>
          </Card>
        ) : null}

        {/* 3 — what has been happening */}
        <Card className="p-4">
          <SectionTitle>News</SectionTitle>
          {activity.length ? (
            <ul className="mt-2 space-y-1.5">
              {activity.slice(0, 5).map((a, i) => {
                // A trophy is the one thing in this feed worth stopping on: it is
                // the end of months of play, and a line identical to "acquisto:
                // Tizio" would let it go by unnoticed.
                const isPrize = a.kind === 'premio';
                const isEnd = a.kind === 'competizione';
                return (
                  <li
                    key={`${a.kind}-${i}`}
                    className={
                      'flex items-start gap-2 text-sm ' +
                      (isPrize || isEnd ? 'rounded-lg bg-amber-50 px-2 py-1.5' : '')
                    }
                  >
                    {/* A prize carries its OWN trophy inside the text — the one the
                        admin chose for it — so the row adds no glyph of its own. */}
                    {isPrize ? null : (
                      <span className="mt-0.5 shrink-0" aria-hidden>
                        {ACTIVITY_ICON[a.kind] ?? '🏁'}
                      </span>
                    )}
                    <span className="min-w-0">
                      <span
                        className={
                          'block truncate ' +
                          (isPrize ? 'font-semibold text-amber-900' : isEnd ? 'text-amber-900' : 'text-slate-700')
                        }
                      >
                        {a.text}
                      </span>
                      {a.detail ? (
                        <span className={'block text-xs ' + (isPrize || isEnd ? 'text-amber-700' : 'text-slate-400')}>
                          {a.detail}
                        </span>
                      ) : null}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="mt-2 text-sm text-slate-500">
              Ancora niente da raccontare: acquisti, decisioni e giornate concluse compaiono qui.
            </div>
          )}
        </Card>
      </div>

      {/* 4 — everything else */}
      <div className="grid gap-4 lg:grid-cols-2">
        {competitions.map((c, i) => (
          <CompetitionBlock
            key={c.competition_id}
            competition={c}
            // Same accent the switcher and the competition-scoped pages give it:
            // the colour identifies WHICH competition, by its position in the
            // league. Colouring by format instead made "champ" amber here and
            // green everywhere else.
            color={compColor(i)}
            fixtures={fixtures.filter((f) => f.competition_id === c.competition_id)}
            structure={structures[c.competition_id] ?? null}
            myTeamName={myTeamName}
          />
        ))}
      </div>

      {detail ? <Participants detail={detail} myTeamName={myTeamName} /> : null}
    </div>
  );
}

/** One competition: how it stands, and the round being played. */
function CompetitionBlock({
  competition,
  color,
  fixtures,
  structure,
  myTeamName,
}: {
  competition: CompetitionItem;
  color: CompColor;
  fixtures: LeagueFixtureItem[];
  structure: CompetitionStructure | null;
  myTeamName: string | null;
}) {
  const round = useMemo(() => {
    const rounds = [...new Set(fixtures.map((f) => f.round_no))].sort((a, b) => a - b);
    const current = rounds.find((r) => fixtures.some((f) => f.round_no === r && f.phase === 'current'));
    if (current != null) return current;
    const next = rounds.find((r) => fixtures.some((f) => f.round_no === r && f.status !== 'finished'));
    return next ?? rounds[rounds.length - 1] ?? null;
  }, [fixtures]);

  const shown = fixtures.filter((f) => f.round_no === round);
  const started = fixtures.some((f) => f.status === 'finished');
  const tables = (structure?.sections ?? []).filter((s) => s.type === 'round_robin');
  // What this competition still has to come but cannot name yet. Without it a cup
  // whose semifinals are in the books reads as over: the final has no fixtures, so
  // there was nothing on this card to say it exists.
  const upcoming = (competition.stage_plan ?? []).filter((s) => s.pending);

  return (
    <Card className={clsx('border-l-4 p-4', color.border600)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <SectionTitle className={clsx('!mb-0', color.text700)}>{competition.name}</SectionTitle>
          <span
            className={clsx(
              'inline-flex items-center rounded-full px-2 py-1 text-[11px] font-semibold',
              color.bg50,
              color.text800,
            )}
          >
            {competitionFormatLabel(competition)}
          </span>
        </div>
        <Link to="/matches" className="text-xs font-semibold text-slate-500 hover:text-slate-800">
          Calendario →
        </Link>
      </div>

      {/* A competition that has not started has nothing to report: a table of
          zeros is not a standing. */}
      {started && tables.length ? (
        <div className="mt-3 space-y-3">
          {tables.map((s) => (
            <div key={s.name}>
              {tables.length > 1 ? (
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{s.name}</div>
              ) : null}
              {/* Where you stand, IN THIS TABLE. It used to sit in the league's
                  identity card, which could only ever show one competition's
                  numbers and never said which — and with two round-robin
                  competitions, or two groups, "1ª · 36 pt" is simply not a
                  statement about a league. Here the name is one line above it. */}
              <MyStanding rows={s.standings ?? []} myTeamName={myTeamName} color={color} />
              <ol className="mt-1 divide-y text-sm">
                {(s.standings ?? []).slice(0, 5).map((row) => (
                  <li
                    key={row.team_id}
                    className={`flex items-center justify-between py-1.5 ${
                      row.team === myTeamName ? 'font-bold text-slate-900' : 'text-slate-600'
                    }`}
                  >
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="w-4 text-right text-xs text-slate-400">{row.rank}</span>
                      <Crest descriptor={row.crest} teamName={row.team} size={20} />
                      <span className="truncate">{row.team}</span>
                    </span>
                    <span className="tabular-nums">{row.points}</span>
                  </li>
                ))}
              </ol>
              {(s.standings?.length ?? 0) > 5 ? (
                <Link
                  to="/standings"
                  className="mt-1 inline-block text-xs font-semibold text-slate-500 hover:text-slate-800"
                >
                  Classifica completa →
                </Link>
              ) : null}
            </div>
          ))}
        </div>
      ) : shown.length ? (
        <div className="mt-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            {new Set(shown.map((f) => f.stage_name)).size === 1
              ? shown[0]?.round_label ?? `Turno ${round}`
              : `Turno ${round}`}
          </div>
          <div className="mt-1.5 space-y-1">
            {shown.slice(0, 4).map((f) => (
              <MiniFixture key={f.fixture_id} f={f} />
            ))}
          </div>
        </div>
      ) : upcoming.length ? null : (
        <div className="mt-2 text-sm text-slate-500">Non è ancora cominciata.</div>
      )}

      {/* What is still to come and has no teams yet. A line, not a card: the detail
          — the rule, the matchdays, what is holding it up — lives in the calendar,
          and here the point is only that it EXISTS. */}
      {upcoming.map((s) => (
        <Link
          key={s.stage_id}
          to="/matches"
          className="mt-2 block rounded-xl border border-dashed border-slate-300 px-3 py-2 hover:border-slate-400"
        >
          <div className="flex items-baseline justify-between gap-2">
            <span className={clsx('text-sm font-semibold', color.text700)}>{s.name}</span>
            <span className="shrink-0 text-[10px] font-bold uppercase tracking-wide text-slate-400">
              da definire
            </span>
          </div>
          <div className="text-xs text-slate-500">{s.rule_text || 'Partecipanti da sorteggiare'}</div>
        </Link>
      ))}
    </Card>
  );
}

/** Your line in ONE table: position, points, and the record behind them.
 *
 *  Nothing here is new — it is what the home page always showed, moved to where it
 *  is true. A team can be first in the championship and third in its group, and the
 *  only honest place for either number is under the name of the thing it counts. */
function MyStanding({
  rows,
  myTeamName,
  color,
}: {
  rows: LeagueStandingRow[];
  myTeamName: string | null;
  color: CompColor;
}) {
  const me = myTeamName ? rows.find((r) => r.team === myTeamName) ?? null : null;
  // Not in this table is a normal state, not an error: the other group, or a
  // spectator. Saying nothing is the right amount.
  if (!me) return null;
  return (
    <div className={clsx('mt-1 rounded-lg px-2 py-1 text-xs font-semibold', color.bg50, color.text800)}>
      {me.rank}ª · {me.points} pt
      <span className="font-normal">
        {' '}
        · {me.wins}V {me.draws}N {me.losses}P · media {me.avg_score_for.toFixed(1)}
      </span>
    </div>
  );
}

function MiniFixture({
  f,
  competition,
  competitionClass,
}: {
  f: LeagueFixtureItem;
  competition?: string;
  competitionClass?: string;
}) {
  const finished = f.status === 'finished' && f.score;
  const row = (
    <div
      className={`rounded-lg px-2 py-1 ${f.is_user_involved ? 'bg-slate-100 font-semibold' : ''}`}
    >
      {competition ? (
        <div className={clsx('text-[10px] font-bold uppercase tracking-wide', competitionClass ?? 'text-slate-400')}>
          {competition}
        </div>
      ) : null}
      <div className="flex items-center gap-2 text-sm">
        <span className="flex flex-1 items-center justify-end gap-1.5 truncate">
          <span className="truncate">{f.home_team.name}</span>
          <Crest descriptor={f.home_team.crest} teamName={f.home_team.name} size={18} />
        </span>
        <span className="shrink-0 tabular-nums text-slate-500">
          {finished ? `${Math.round(f.score!.home_total)}–${Math.round(f.score!.away_total)}` : 'vs'}
        </span>
        <span className="flex flex-1 items-center gap-1.5 truncate">
          <Crest descriptor={f.away_team.crest} teamName={f.away_team.name} size={18} />
          <span className="truncate">{f.away_team.name}</span>
        </span>
      </div>
    </div>
  );
  return f.has_detail ? (
    <Link to={`/matches/${f.fixture_id}`} className="block hover:opacity-80">
      {row}
    </Link>
  ) : (
    row
  );
}

/** Who is in the league, with the crests that make them recognisable. */
function Participants({ detail, myTeamName }: { detail: LeagueDetail; myTeamName: string | null }) {
  return (
    <Card className="p-4">
      <SectionTitle>Partecipanti</SectionTitle>
      <div className="mt-2 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
        {detail.teams.map((t) => {
          const mine = t.name === myTeamName;
          return (
            <Link
              key={t.team_id}
              to={mine ? '/squad' : `/teams/${t.team_id}`}
              className={`flex items-center gap-2 rounded-xl border px-3 py-2 transition hover:bg-slate-50 ${
                mine ? 'border-slate-300 bg-slate-50' : 'border-slate-100'
              }`}
            >
              <Crest descriptor={t.crest} teamName={t.name} size={30} />
              <span className="min-w-0">
                <span className="block truncate text-sm font-semibold text-slate-800">
                  {t.name}
                  {mine ? (
                    <span className="ml-1.5 text-[10px] font-bold uppercase text-emerald-600">la tua</span>
                  ) : null}
                </span>
                <span className="block truncate text-xs text-slate-500">{t.manager_username}</span>
              </span>
            </Link>
          );
        })}
      </div>
    </Card>
  );
}
