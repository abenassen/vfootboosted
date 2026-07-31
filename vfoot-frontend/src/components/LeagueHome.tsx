import { useEffect, useMemo, useState } from 'react';
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
import { Badge, Button, Card, SectionTitle } from './ui';
import Crest from './Crest';
import type {
  ActiveAuctionInfo,
  CompetitionItem,
  CompetitionStructure,
  LeagueDetail,
  LeagueFixtureItem,
  LeagueMatchdayItem,
} from '../types/league';

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
  }, [selectedLeagueId]);

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
  const nextByCompetition = useMemo(() => {
    const out = new Map<number, LeagueFixtureItem>();
    for (const f of [...mine].sort((a, b) => a.round_no - b.round_no)) {
      if (f.status !== 'finished' && !out.has(f.competition_id)) out.set(f.competition_id, f);
    }
    return [...out.values()];
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

  const currentMd = matchdays.find((m) => m.phase === 'current') ?? null;
  const canConclude =
    isAdmin && currentMd && currentMd.status === 'planned' && currentMd.real_completion.is_completed;

  if (!competitions.length) return null;

  return (
    <div className="space-y-4">
      {msg ? <Card className="p-3 text-sm text-slate-700">{msg}</Card> : null}

      {canConclude && currentMd ? (
        <Card className="border-l-4 border-emerald-500 bg-emerald-50 p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <div className="text-sm font-bold text-emerald-900">
                La giornata {currentMd.real_matchday} è finita
              </div>
              <div className="text-xs text-emerald-800">
                Tutte le partite reali sono concluse: puoi calcolare i punteggi e far avanzare la lega.
              </div>
            </div>
            <Button
              size="sm"
              disabled={busy}
              onClick={() => {
                if (!selectedLeagueId) return;
                setBusy(true);
                setMsg(null);
                void concludeLeagueMatchday(selectedLeagueId, currentMd.fantasy_matchday_id)
                  .then(() => {
                    setMsg('Giornata conclusa.');
                    return Promise.all([
                      getLeagueMatchdays(selectedLeagueId).then(setMatchdays),
                      getLeagueFixtures(selectedLeagueId).then(setFixtures),
                      getLeagueActivity(selectedLeagueId, 5).then(setActivity),
                    ]);
                  })
                  .catch((e: unknown) =>
                    // Concluding can need per-team decisions (forfait vs previous
                    // lineup); that flow lives in Gestione lega, so a failure here
                    // points there instead of pretending to handle it.
                    setMsg(
                      `Non è stato possibile concludere qui: ${
                        e instanceof Error ? e.message : String(e)
                      }. Aprila da Gestione lega → Giornate.`,
                    ),
                  )
                  .finally(() => setBusy(false));
              }}
            >
              {busy ? 'Concludo…' : 'Concludi la giornata'}
            </Button>
          </div>
        </Card>
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
                  {f.round_label ?? `Giornata ${f.round_no}`}
                  {typeof f.real_matchday === 'number' ? ` · giornata reale ${f.real_matchday}` : ''}
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
              {activity.slice(0, 5).map((a, i) => (
                <li key={`${a.kind}-${i}`} className="flex items-start gap-2 text-sm">
                  <span className="mt-0.5 shrink-0" aria-hidden>
                    {a.kind === 'acquisto' ? '🔁' : a.kind === 'decisione' ? '🗳️' : '🏁'}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-slate-700">{a.text}</span>
                    {a.detail ? <span className="block text-xs text-slate-400">{a.detail}</span> : null}
                  </span>
                </li>
              ))}
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
              ? shown[0]?.round_label ?? `Giornata ${round}`
              : `Giornata ${round}`}
          </div>
          <div className="mt-1.5 space-y-1">
            {shown.slice(0, 4).map((f) => (
              <MiniFixture key={f.fixture_id} f={f} />
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-2 text-sm text-slate-500">Non è ancora cominciata.</div>
      )}
    </Card>
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
