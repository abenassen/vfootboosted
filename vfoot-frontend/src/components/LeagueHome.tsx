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
import {
  getLeagueHonours,
  getMarketActive,
  type LeagueActivityItem,
  type LeagueHonoursBoard,
} from '../api/backend';
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
  CompetitionSection,
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
  // Not the same glyph as `acquisto`: one is a manager spending credits, the
  // other is a real club signing a player, and the feed shows them side by side.
  mercato_reale: '✍️',
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
  const [honours, setHonours] = useState<LeagueHonoursBoard | null>(null);
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
    void getLeagueHonours(selectedLeagueId).then((h) => alive && setHonours(h)).catch(() => {});
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
      // A round that has kicked off is normally behind you — but not under the
      // per-player deadline, where half of it is still to be decided. There the
      // server says so (`can_set_lineup`), and dropping the fixture anyway would
      // hide the shortcut to the very lineup the manager can still change.
      const behind = f.lineup_locked && !f.can_set_lineup;
      if (f.status !== 'finished' && !behind && !out.has(f.competition_id)) {
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

  // IN DATE ORDER, for the same reason the block above is: `round_no` is the
  // competition's OWN turn number, not a date. Sorting the finished ones by it
  // let the championship — at its round 22 while a cup is at its round 3 — take
  // all four slots for good, so a semifinal played yesterday never appeared and
  // the block was "the last four of the championship" wearing the name of the
  // league's last four.
  const lastResults = useMemo(
    () =>
      [...mine]
        .filter((f) => f.status === 'finished')
        .sort(
          (a, b) =>
            (b.real_matchday ?? Number.NEGATIVE_INFINITY) - (a.real_matchday ?? Number.NEGATIVE_INFINITY) ||
            b.round_no - a.round_no,
        )
        .slice(0, 4),
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

  // TUTTE le altre partite della giornata aperta. La tua resta in evidenza sopra
  // — è quella per cui si apre l'app — ma finché c'era solo quella la domanda
  // successiva, "e gli altri?", non aveva risposta da nessuna parte: il
  // punteggio degli avversari esiste ed era già calcolato, semplicemente non
  // veniva mostrato. In ordine di competizione, così un campionato e una coppa
  // giocate lo stesso giorno non si mescolano.
  const otherOpenFixtures = useMemo(() => {
    if (!openMd) return [];
    return fixtures
      .filter((f) => !f.is_user_involved && f.real_matchday === openMd.real_matchday)
      .sort((a, b) => a.competition_id - b.competition_id || a.round_no - b.round_no);
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

      {/* LA LEGA È FINITA: da qui in poi la home apre sull'albo d'oro.
          Non è un blocco in più fra gli altri, è un cambio di domanda. Finché si
          gioca la home risponde a "cosa devo fare adesso"; quando non c'è più
          niente da giocare quella domanda non ha più risposta — le prossime
          partite sono zero, la giornata da schierare non esiste — e l'unica cosa
          che resta da dire è com'è andata. Perciò sta in cima e ci resta: per una
          lega conclusa questa È la home. */}
      {honours?.is_over ? <LeagueTrophyCase board={honours} myTeamName={myTeamName} /> : null}

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

          {/* E gli altri. La propria partita sta sopra, grande; il resto della
              giornata sta qui, compatto, perché la domanda è diversa — non
              "come sto andando" ma "come sta andando la giornata" — e finché
              mancava bisognava aprire il calendario per una cosa che il server
              stava già calcolando. */}
          {otherOpenFixtures.length ? (
            <div className="mt-4 border-t border-slate-100 pt-3">
              <div className="text-[11px] font-bold uppercase tracking-wide text-slate-400">
                Le altre partite della giornata
              </div>
              <div className="mt-1.5 grid gap-1 md:grid-cols-2">
                {otherOpenFixtures.map((f) => (
                  <MiniFixture
                    key={f.fixture_id}
                    f={f}
                    competition={compName.get(f.competition_id)}
                    competitionClass={compColorById.get(f.competition_id)?.text700}
                  />
                ))}
              </div>
            </div>
          ) : null}
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
                {/* Same wording as the results below, from the same function: the
                    two blocks sit one above the other and had no business naming a
                    round two different ways. */}
                <div className="mt-1 text-xs text-slate-500">{roundLabel(f)}</div>
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

      {/* A LEGA CONCLUSA questa fascia sparisce tutta: sono le tre domande di una
          stagione in corso — cosa devi fare, com'è andata la tua ultima partita,
          cosa è successo in giro — e quando non c'è più niente da giocare nessuna
          delle tre ha una risposta. «Da fare» direbbe per sempre «sei in pari»,
          gli ultimi risultati sarebbero quelli di maggio, e le news
          racconterebbero i premi che stanno già nella bacheca qui sopra. */}
      {honours?.is_over ? null : (
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
            {/* DELLA TUA SQUADRA, detto nel titolo: la lista è filtrata su di te
                (vedi `mine`), e un titolo generico prometteva i risultati della
                lega — che stanno nei blocchi delle competizioni. */}
            <SectionTitle>Ultimi risultati della tua squadra</SectionTitle>
            <div className="mt-2 space-y-1">
              {lastResults.map((f) => (
                <MiniFixture
                  key={f.fixture_id}
                  f={f}
                  competition={compName.get(f.competition_id)}
                  competitionClass={compColorById.get(f.competition_id)?.text700}
                  when
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
                      (isPrize || isEnd ? 'rounded-lg bg-amber-50 px-2 py-1.5' : '') +
                      // In evidenza: il server l'ha già messa in cima, qui si dice
                      // PERCHÉ ci sta. Senza il bordo una notizia fuori ordine
                      // cronologico sembra un elenco che ha sbagliato a ordinare.
                      (a.pinned ? ' border-l-2 border-amber-400 pl-2' : '')
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
                      {a.pinned ? (
                        <span className="mt-0.5 inline-block rounded bg-amber-200/70 px-1.5 text-[10px] font-bold uppercase tracking-wide text-amber-900">
                          in evidenza
                        </span>
                      ) : null}
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
      )}

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
            openMatchday={openMd?.real_matchday ?? null}
          />
        ))}
      </div>

      {detail ? <Participants detail={detail} myTeamName={myTeamName} /> : null}
    </div>
  );
}

/** La bacheca della lega: tutto quello che è stato vinto, quando non c'è più
 *  niente da vincere.
 *
 *  Raggruppata per COMPETIZIONE e non per premio: "chi ha vinto il campionato" e
 *  "chi ha fatto più gol nel campionato" sono due risposte sulla stessa stagione,
 *  e in un elenco piatto di sei trofei nessuno ritrova più il torneo che li ha
 *  assegnati. La propria squadra in grassetto: in una bacheca la prima cosa che
 *  si cerca è sé stessi.
 */
function LeagueTrophyCase({
  board,
  myTeamName,
}: {
  board: LeagueHonoursBoard;
  myTeamName: string | null;
}) {
  const byCompetition = useMemo(() => {
    const out = new Map<number, { name: string; awards: LeagueHonoursBoard['awards'] }>();
    for (const a of board.awards) {
      const row = out.get(a.competition_id) ?? { name: a.competition_name, awards: [] };
      row.awards.push(a);
      out.set(a.competition_id, row);
    }
    return [...out.values()];
  }, [board.awards]);

  return (
    <Card className="border-l-4 border-amber-400 bg-gradient-to-b from-amber-50/80 to-white p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <SectionTitle className="!mb-0 text-amber-900">🏆 Albo d'oro della lega</SectionTitle>
        <span className="text-[11px] text-amber-700">
          Stagione conclusa
          {board.finished_at ? ` il ${new Date(board.finished_at).toLocaleDateString('it-IT')}` : ''}
          {` · ${board.competitions_total} ${
            board.competitions_total === 1 ? 'competizione' : 'competizioni'
          }`}
        </span>
      </div>

      {byCompetition.length ? (
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {byCompetition.map((comp) => (
            <div key={comp.name} className="rounded-xl border border-amber-200 bg-white/70 p-3">
              <div className="text-[11px] font-bold uppercase tracking-wide text-amber-800">
                {comp.name}
              </div>
              <ul className="mt-1.5 space-y-1.5">
                {comp.awards.map((a) => (
                  <li key={a.prize_id} className="flex items-start gap-2">
                    <span className="text-xl leading-none" aria-hidden>
                      {a.icon}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-semibold text-slate-900">{a.name}</span>
                      <span className="block truncate text-[11px] text-slate-500">{a.condition_label}</span>
                      <span className="mt-0.5 flex flex-wrap items-center gap-1.5">
                        {a.winners.map((w) => (
                          <span key={w.team_id} className="flex items-center gap-1">
                            <Crest descriptor={w.crest} teamName={w.name ?? ''} size={18} />
                            <span
                              className={clsx(
                                'truncate text-xs',
                                w.name && w.name === myTeamName
                                  ? 'font-bold text-amber-900'
                                  : 'text-slate-700',
                              )}
                            >
                              {w.name}
                            </span>
                          </span>
                        ))}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      ) : (
        // Finita senza trofei: nessuna competizione aveva premi dichiarati. Va
        // detto, perché una bacheca vuota sotto "stagione conclusa" sembra un
        // caricamento rimasto a metà.
        <div className="mt-2 text-sm text-amber-800">
          La stagione è finita, ma nessuna competizione aveva premi da assegnare.
        </div>
      )}
    </Card>
  );
}

const sectionFixtures = (s: CompetitionSection) => (s.rounds ?? []).flatMap((r) => r.fixtures);

/** La competizione è ARRIVATA a questa fase?
 *
 *  La prova cambia col tipo, e non è un dettaglio: una fase a girone porta la
 *  classifica e non i turni, una a eliminazione porta i turni e non la classifica
 *  (il backend serve solo ciò che quella forma sa dire). Chiedere le partite a
 *  tutte e due faceva risultare "non ancora cominciato" un campionato alla
 *  trentaseiesima giornata. */
const sectionDrawn = (s: CompetitionSection) =>
  s.type === 'round_robin' ? (s.standings?.length ?? 0) > 0 : sectionFixtures(s).length > 0;

/** One competition: how it stands, and the round being played. */
function CompetitionBlock({
  competition,
  color,
  fixtures,
  structure,
  myTeamName,
  openMatchday,
}: {
  competition: CompetitionItem;
  color: CompColor;
  fixtures: LeagueFixtureItem[];
  structure: CompetitionStructure | null;
  myTeamName: string | null;
  /** La giornata cominciata e non ancora conclusa, se ce n'è una. */
  openMatchday: number | null;
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

  // QUESTA competizione, in questo momento. Il blocco raccontava soltanto la fase
  // — la classifica, o il turno disegnato — e per tutta la giornata in corso
  // restava identico a com'era il venerdì: la coppa che si stava giocando
  // proprio adesso non compariva da nessuna parte, e l'unico posto dove i
  // punteggi si muovevano era il pannello della propria partita.
  const openFixtures = useMemo(
    () =>
      openMatchday == null
        ? []
        : fixtures.filter((f) => f.real_matchday === openMatchday && f.status !== 'finished'),
    [fixtures, openMatchday],
  );
  // Si sta ancora giocando, o è tutto finito e manca solo il conteggio.
  const openMoving = openFixtures.some((f) => f.score_provisional);

  // DOVE LA COMPETIZIONE SI TROVA ADESSO, che non è la stessa cosa di "che forma
  // ha". Questa card mostrava le classifiche ogni volta che ne esisteva una, e
  // per una coppa a gironi quella condizione resta vera per sempre: a finale
  // giocata continuava a mostrare i gironi di novembre, cioè l'unica parte del
  // torneo che di sicuro non interessa più.
  //
  // Le fasi PARALLELE — i due gironi, che si giocano insieme — condividono
  // l'ordine e restano un gruppo solo: durante i gironi si vogliono entrambe le
  // classifiche, non l'ultima delle due.
  const phases = useMemo(() => {
    const sections = [...(structure?.sections ?? [])].sort((a, b) => a.order - b.order);
    const groups: CompetitionSection[][] = [];
    for (const s of sections) {
      const last = groups[groups.length - 1];
      if (last && last[0].order === s.order) last.push(s);
      else groups.push([s]);
    }
    return groups;
  }, [structure]);

  // L'ultima fase SORTEGGIATA: una fase senza partite non è ancora cominciata e
  // vive in `upcoming`, dove è dichiarata come da definire.
  const current = useMemo(() => {
    const drawn = phases.filter((g) => g.some(sectionDrawn));
    return drawn[drawn.length - 1] ?? null;
  }, [phases]);

  // Le classifiche solo se la fase corrente è un girone: dopo, la classifica del
  // girone è storia e la si legge dalla pagina della competizione.
  const tables = current && current[0].type === 'round_robin' ? current : [];

  // Il turno della fase corrente, quando è a eliminazione: l'ultimo disegnato.
  const knockoutRound = useMemo(() => {
    if (!current || current[0].type === 'round_robin') return null;
    const rounds = current
      .flatMap((s) => s.rounds ?? [])
      .filter((r) => r.fixtures.length)
      .sort((a, b) => a.round_no - b.round_no);
    return rounds[rounds.length - 1] ?? null;
  }, [current]);

  // Il quadro d'insieme non ripete ciò che è già scritto sopra. Senza questo, la
  // finale di coppa compariva due volte nella stessa card — una come "si gioca
  // adesso" e una come turno della fase corrente, che in una coppa arrivata in
  // fondo sono la stessa partita.
  const upstairs = new Set(openFixtures.map((f) => f.fixture_id));
  const knockoutPhase = (knockoutRound?.fixtures ?? []).filter((f) => !upstairs.has(f.fixture_id));
  const shownPhase = shown.filter((f) => !upstairs.has(f.fixture_id));

  // What this competition still has to come but cannot name yet. Without it a cup
  // whose semifinals are in the books reads as over: the final has no fixtures, so
  // there was nothing on this card to say it exists.
  const upcoming = (competition.stage_plan ?? []).filter((s) => s.pending);

  // Le due scorciatoie, con la competizione addosso: vedi useCompetitionFromQuery.
  const calendarTo = `/matches?competition=${competition.competition_id}`;
  const standingsTo = `/standings?competition=${competition.competition_id}`;

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
        {/* CON la competizione addosso. Senza, tutti e tre i blocchi portavano
            all'ultima competizione guardata — cioè quasi sempre al campionato — e
            il link sembrava sbagliato invece che privo di contesto. */}
        <Link to={calendarTo} className="text-xs font-semibold text-slate-500 hover:text-slate-800">
          Calendario →
        </Link>
      </div>

      {/* Quello che sta succedendo ADESSO, sopra a tutto: se questa competizione
          gioca nella giornata aperta, le sue partite stanno qui col punteggio che
          si muove. Sotto resta il quadro d'insieme — la classifica, o il turno
          della fase — che è la domanda dell'altro momento della settimana. */}
      {openFixtures.length ? (
        <div
          className={clsx(
            'mt-3 rounded-xl border p-2',
            openMoving ? 'border-violet-200 bg-violet-50/50' : 'border-emerald-200 bg-emerald-50/40',
          )}
        >
          <div className="flex items-center gap-1.5">
            {openMoving ? (
              <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-violet-600" />
            ) : null}
            <span
              className={clsx(
                'text-[11px] font-bold uppercase tracking-wide',
                openMoving ? 'text-violet-700' : 'text-emerald-700',
              )}
            >
              Giornata {openMatchday} · {openMoving ? 'in corso' : 'da concludere'}
            </span>
          </div>
          <div className="mt-1.5 space-y-1">
            {openFixtures.slice(0, 5).map((f) => (
              <MiniFixture key={f.fixture_id} f={f} />
            ))}
          </div>
          <div className={clsx('mt-1 text-[11px]', openMoving ? 'text-violet-700/80' : 'text-emerald-700/80')}>
            {openMoving
              ? 'Punteggi provvisori: diventano definitivi quando la giornata viene conclusa.'
              : 'Le partite sono finite: i punteggi si fissano con la conclusione della giornata.'}
          </div>
        </div>
      ) : null}

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
                      {/* Una partita ancora da finire dentro questi punti. Il
                          pallino è sulla RIGA e non sulla tabella perché è vero
                          di qualcuno e non di tutti: chi ha già giocato ha un
                          numero fermo, e distinguerli è metà dell'informazione. */}
                      {row.provisional ? (
                        <span
                          className="inline-block h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-violet-600"
                          title="Partita in corso: questi punti possono ancora cambiare"
                        />
                      ) : null}
                    </span>
                    {/* G V N P accanto ai punti. Senza, due squadre a 41 sembrano
                        pari mentre una ha una partita in meno — e appena la
                        classifica conta anche il provvisorio quel caso non è più
                        l'eccezione di metà settimana: è la domenica pomeriggio. */}
                    <span className="flex shrink-0 items-baseline gap-2">
                      <span className="hidden text-[11px] tabular-nums text-slate-400 sm:inline">
                        {row.played}g · {row.wins}V {row.draws}N {row.losses}P
                      </span>
                      <span className="tabular-nums">{row.points}</span>
                    </span>
                  </li>
                ))}
              </ol>
              {(s.standings?.length ?? 0) > 5 ? (
                <Link
                  to={standingsTo}
                  className="mt-1 inline-block text-xs font-semibold text-slate-500 hover:text-slate-800"
                >
                  Classifica completa →
                </Link>
              ) : null}
            </div>
          ))}
        </div>
      ) : knockoutPhase.length ? (
        <PlayingNow
          label={knockoutRound?.label || `Turno ${knockoutRound?.round_no ?? round}`}
          fixtures={knockoutPhase}
        />
      ) : shownPhase.length ? (
        <PlayingNow
          label={
            new Set(shownPhase.map((f) => f.stage_name)).size === 1
              ? shownPhase[0]?.round_label ?? `Turno ${round}`
              : `Turno ${round}`
          }
          fixtures={shownPhase}
        />
      ) : openFixtures.length || upcoming.length ? null : (
        <div className="mt-2 text-sm text-slate-500">Non è ancora cominciata.</div>
      )}

      {/* What is still to come and has no teams yet. A line, not a card: the detail
          — the rule, the matchdays, what is holding it up — lives in the calendar,
          and here the point is only that it EXISTS. */}
      {upcoming.map((s) => (
        <Link
          key={s.stage_id}
          to={calendarTo}
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

/** Le partite di una fase, e — se non hanno ancora un risultato — PERCHÉ.
 *
 *  La riga in fondo esiste per una domanda che la card faceva nascere e non
 *  sapeva chiudere: una finale disegnata, giocata sul campo vero, e nessun
 *  punteggio accanto. Non è un guasto ed è il modello a due orologi in azione —
 *  il calendario ha finito, il registro no — ma senza dirlo la card sembra
 *  semplicemente rotta. Il numero della giornata è quello che l'admin deve
 *  concludere, cioè l'azione che fa comparire i risultati.
 */
function PlayingNow({ label, fixtures }: { label: string; fixtures: LeagueFixtureItem[] }) {
  const pending = fixtures.filter((f) => f.status !== 'finished');
  const waiting = pending.filter((f) => f.phase === 'current' || f.phase === 'awaiting');
  const matchday = waiting.map((f) => f.real_matchday).find((m) => typeof m === 'number');
  return (
    <div className="mt-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1.5 space-y-1">
        {fixtures.slice(0, 4).map((f) => (
          <MiniFixture key={f.fixture_id} f={f} />
        ))}
      </div>
      {waiting.length ? (
        <div className="mt-1.5 text-xs text-slate-500">
          {waiting.length === pending.length && pending.length === 1
            ? 'Giocata: il risultato arriva con la conclusione'
            : 'I risultati arrivano con la conclusione'}
          {typeof matchday === 'number' ? ` della giornata ${matchday}` : ''}.
        </div>
      ) : null}
    </div>
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

/** WHEN a fixture was played, in the two units the league is scheduled in.
 *
 *  TURNO is the competition's own count, GIORNATA the real Serie A one. Two
 *  clocks, two words, never the same word for both — that is the league-wide
 *  convention, and the backend's `round_label` obeys it (it also carries a
 *  knockout's own name, "Semifinali", which beats any number).
 *
 *  ENTRAMBI, sempre, anche quando i numeri coincidono. In un campionato coincidono
 *  per costruzione — un turno per giornata reale — e per un momento si era pensato
 *  di stampare solo la giornata per non ripetersi; ma allora la stessa riga dice
 *  due cose diverse a seconda della competizione, e chi legge "Giornata 21" non ha
 *  modo di sapere se è il ventunesimo turno o no. In coppa i due numeri non
 *  coincidono mai. Meglio ridondante che ambiguo.
 */
function roundLabel(f: LeagueFixtureItem): string {
  const round = f.round_label ?? `Turno ${f.round_no}`;
  return typeof f.real_matchday === 'number' ? `${round} · giornata ${f.real_matchday}` : round;
}

function MiniFixture({
  f,
  competition,
  competitionClass,
  when,
}: {
  f: LeagueFixtureItem;
  competition?: string;
  competitionClass?: string;
  /** Show which round this was. Off inside a competition block, where every row
   *  belongs to the round already named above them; ON in "Ultimi risultati",
   *  which mixes competitions and where the name alone left no way to tell
   *  whether a result was from yesterday or from November. */
  when?: boolean;
}) {
  // Il punteggio c'è anche mentre si gioca (il server lo calcola per tutta la
  // giornata aperta, non solo per la tua partita) e questa riga lo buttava via:
  // chiedeva `status === 'finished'`, che diventa vero solo alla CONCLUSIONE, e
  // così per tutta la domenica ogni blocco diceva "vs" mentre il tabellino
  // dietro mostrava 68-72. Ora si mostra, e si dice che è provvisorio.
  const finished = f.status === 'finished' && f.score;
  // Non conclusa ma un punteggio ce l'ha. `score_provisional` distingue i due
  // modi di esserlo, e non è pignoleria: a metà partita il numero cambierà
  // ancora, a partite vere finite non cambierà più e manca solo il clic
  // dell'admin. Dirli allo stesso modo renderebbe sospetto un risultato che è
  // ormai fermo.
  const pending = !finished && f.score;
  const moving = pending && f.score_provisional;
  const row = (
    <div
      className={`rounded-lg px-2 py-1 ${f.is_user_involved ? 'bg-slate-100 font-semibold' : ''}`}
    >
      {competition || when ? (
        <div className="flex items-baseline justify-between gap-2">
          {competition ? (
            <span
              className={clsx(
                'truncate text-[10px] font-bold uppercase tracking-wide',
                competitionClass ?? 'text-slate-400',
              )}
            >
              {competition}
            </span>
          ) : (
            <span />
          )}
          {when ? (
            <span className="shrink-0 text-[10px] font-medium text-slate-400">{roundLabel(f)}</span>
          ) : null}
        </div>
      ) : null}
      <div className="flex items-center gap-2 text-sm">
        <span className="flex flex-1 items-center justify-end gap-1.5 truncate">
          <span className="truncate">{f.home_team.name}</span>
          <Crest descriptor={f.home_team.crest} teamName={f.home_team.name} size={18} />
        </span>
        <span
          className={clsx(
            'shrink-0 tabular-nums',
            moving ? 'font-bold text-violet-700' : pending ? 'font-semibold text-slate-600' : 'text-slate-500',
          )}
          title={
            moving
              ? 'Punteggio provvisorio: si sta ancora giocando'
              : pending
                ? 'In attesa della conclusione della giornata'
                : undefined
          }
        >
          {finished || pending
            ? `${Math.round(f.score!.home_total)}–${Math.round(f.score!.away_total)}`
            : 'vs'}
        </span>
        <span className="flex flex-1 items-center gap-1.5 truncate">
          <Crest descriptor={f.away_team.crest} teamName={f.away_team.name} size={18} />
          <span className="truncate">{f.away_team.name}</span>
        </span>
      </div>
      {/* Chi è passato, e per quale gradino della catena — SOLO quello che ha
          deciso questa sfida. Su un 1-1 la home mostrava il risultato e basta:
          la coppa risultava assegnata e la card non diceva a chi né perché. */}
      {f.advanced_team_id && f.advanced_reason ? (
        <div className="mt-0.5 text-[10px] leading-snug text-slate-500">
          passa {f.advanced_team_id === f.home_team.team_id ? f.home_team.name : f.away_team.name}
          {f.advanced_reason === 'punteggio'
            ? `: gol pari, punteggio più alto${
                f.totals ? ` ${f.totals.home.toFixed(1)}–${f.totals.away.toFixed(1)}` : ''
              }`
            : f.advanced_reason === 'rigori'
              ? `: gol e punteggi pari, ai rigori${
                  f.shootout ? ` ${f.shootout.home_goals}-${f.shootout.away_goals}` : ''
                }`
              : f.advanced_reason === 'fattore campo'
                ? ': tutto pari, era in casa nell’ultima gara'
                : ''}
        </div>
      ) : null}
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

/** Who is in the league, with the crests that make them recognisable.
 *
 *  DUE destinazioni per riga, perché sono due cose diverse. La SQUADRA è una
 *  proprietà di questa lega e finisce con lei: porta alla rosa. Il
 *  FANTALLENATORE no — gioca altrove, e i suoi trofei si accumulano attraverso i
 *  campionati — quindi porta alla sua scheda. Prima l'intera riga andava alla
 *  rosa e il nome sotto era testo morto, che è esattamente il motivo per cui
 *  l'albo d'oro era finito su una pagina che non è sua.
 */
function Participants({ detail, myTeamName }: { detail: LeagueDetail; myTeamName: string | null }) {
  return (
    <Card className="p-4">
      <SectionTitle>Partecipanti</SectionTitle>
      <div className="mt-2 grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
        {detail.teams.map((t) => {
          const mine = t.name === myTeamName;
          return (
            <div
              key={t.team_id}
              className={`flex items-center gap-2 rounded-xl border px-3 py-2 ${
                mine ? 'border-slate-300 bg-slate-50' : 'border-slate-100'
              }`}
            >
              {/* Lo stemma appartiene alla squadra, quindi segue il suo link. */}
              <Link to={mine ? '/squad' : `/teams/${t.team_id}`} className="shrink-0">
                <Crest descriptor={t.crest} teamName={t.name} size={30} />
              </Link>
              <span className="min-w-0 flex-1">
                <Link
                  to={mine ? '/squad' : `/teams/${t.team_id}`}
                  className="block truncate text-sm font-semibold text-slate-800 hover:underline"
                >
                  {t.name}
                  {mine ? (
                    <span className="ml-1.5 text-[10px] font-bold uppercase text-emerald-600">la tua</span>
                  ) : null}
                </Link>
                <Link
                  to={`/fantallenatori/${t.manager_user_id}`}
                  className="block truncate text-xs text-slate-500 hover:text-slate-800 hover:underline"
                >
                  {t.manager_username}
                </Link>
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}
