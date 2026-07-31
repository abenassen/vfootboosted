import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  concludeLeagueMatchday,
  getCompetitionStructure,
  getLeagueActivity,
  getLeagueDetail,
  getLeagueFixtures,
  getLeagueMatchdays,
} from '../api';
import type { LeagueActivityItem } from '../api/backend';
import { useLeagueContext } from '../league/LeagueContext';
import { competitionFormatLabel } from '../league/competitionFormat';
import { Badge, Button, Card, SectionTitle } from './ui';
import Crest from './Crest';
import type {
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
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedLeagueId) return;
    let alive = true;
    void getLeagueDetail(selectedLeagueId).then((d) => alive && setDetail(d)).catch(() => {});
    void getLeagueFixtures(selectedLeagueId).then((f) => alive && setFixtures(f)).catch(() => {});
    void getLeagueMatchdays(selectedLeagueId).then((m) => alive && setMatchdays(m)).catch(() => {});
    void getLeagueActivity(selectedLeagueId, 8).then((a) => alive && setActivity(a)).catch(() => {});
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
                      getLeagueActivity(selectedLeagueId, 8).then(setActivity),
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
                <div className="text-[11px] font-bold uppercase tracking-wide text-slate-500">
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
                    className="mt-2 inline-flex rounded-lg bg-slate-900 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-slate-800"
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
        {/* 2 — how the last ones went */}
        {lastResults.length ? (
          <Card className="p-4">
            <SectionTitle>Ultimi risultati</SectionTitle>
            <div className="mt-2 space-y-1">
              {lastResults.map((f) => (
                <MiniFixture key={f.fixture_id} f={f} competition={compName.get(f.competition_id)} />
              ))}
            </div>
          </Card>
        ) : null}

        {/* 3 — what has been happening */}
        <Card className="p-4">
          <SectionTitle>Novità</SectionTitle>
          {activity.length ? (
            <ul className="mt-2 space-y-1.5">
              {activity.map((a, i) => (
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
        {competitions.map((c) => (
          <CompetitionBlock
            key={c.competition_id}
            competition={c}
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
  fixtures,
  structure,
  myTeamName,
}: {
  competition: CompetitionItem;
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
    <Card className="p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <SectionTitle className="!mb-0">{competition.name}</SectionTitle>
          <Badge tone={competition.competition_type === 'knockout' ? 'amber' : 'blue'}>
            {competitionFormatLabel(competition)}
          </Badge>
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

function MiniFixture({ f, competition }: { f: LeagueFixtureItem; competition?: string }) {
  const finished = f.status === 'finished' && f.score;
  const row = (
    <div
      className={`rounded-lg px-2 py-1 ${f.is_user_involved ? 'bg-slate-100 font-semibold' : ''}`}
    >
      {competition ? (
        <div className="text-[10px] font-bold uppercase tracking-wide text-slate-400">{competition}</div>
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
