import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  concludeLeagueMatchday,
  getCompetitionStructure,
  getLeagueDetail,
  getLeagueFixtures,
  getLeagueMatchdays,
} from '../api';
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

/** What is going on in the league right now, all of it on one page.
 *
 *  Replaces the old "Lega" page, which was a hub of links to pages that already
 *  existed. The questions people actually open the app for are "who plays whom
 *  this week" and "how is it going" — asked once per competition, because a
 *  league can run a championship and a cup side by side.
 */
export default function LeagueHome({ competitions }: { competitions: CompetitionItem[] }) {
  const { selectedLeagueId, selectedLeague } = useLeagueContext();
  const isAdmin = selectedLeague?.role === 'admin';

  const [detail, setDetail] = useState<LeagueDetail | null>(null);
  const [fixtures, setFixtures] = useState<LeagueFixtureItem[]>([]);
  const [structures, setStructures] = useState<Record<number, CompetitionStructure>>({});
  const [matchdays, setMatchdays] = useState<LeagueMatchdayItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  useEffect(() => {
    if (!selectedLeagueId) return;
    let alive = true;
    void getLeagueDetail(selectedLeagueId).then((d) => alive && setDetail(d)).catch(() => {});
    void getLeagueFixtures(selectedLeagueId).then((f) => alive && setFixtures(f)).catch(() => {});
    void getLeagueMatchdays(selectedLeagueId).then((m) => alive && setMatchdays(m)).catch(() => {});
    return () => {
      alive = false;
    };
  }, [selectedLeagueId]);

  // One structure per competition: it is what carries the standings, per stage.
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
      setStructures(Object.fromEntries(entries.filter(Boolean) as Array<readonly [number, CompetitionStructure]>));
    });
    return () => {
      alive = false;
    };
  }, [selectedLeagueId, competitions]);

  // The matchday the league is standing on, and whether the real round behind it
  // is over — the only case in which concluding is a sensible offer.
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
                    ]);
                  })
                  .catch((e: unknown) =>
                    // Concluding can need per-team decisions (forfait vs formazione
                    // precedente); that flow lives in Gestione lega, so a failure
                    // here points there instead of pretending to handle it.
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

      {competitions.map((c) => (
        <CompetitionBlock
          key={c.competition_id}
          competition={c}
          fixtures={fixtures.filter((f) => f.competition_id === c.competition_id)}
          structure={structures[c.competition_id] ?? null}
          myTeamName={selectedLeague?.team_name?.trim() || null}
        />
      ))}

      {detail ? <Participants detail={detail} myTeamName={selectedLeague?.team_name?.trim() || null} /> : null}
    </div>
  );
}

/** One competition: the round being played, and how it stands. */
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
  // The round to show: the one in play, else the first not yet played, else the
  // last one played — a concluded competition should still show its final round.
  const round = useMemo(() => {
    const byRound = [...new Set(fixtures.map((f) => f.round_no))].sort((a, b) => a - b);
    const current = byRound.find((r) => fixtures.some((f) => f.round_no === r && f.phase === 'current'));
    if (current != null) return current;
    const next = byRound.find((r) => fixtures.some((f) => f.round_no === r && f.status !== 'finished'));
    return next ?? byRound[byRound.length - 1] ?? null;
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

      {shown.length ? (
        <div className="mt-3">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            {shown[0]?.round_label && new Set(shown.map((f) => f.stage_name)).size === 1
              ? shown[0].round_label
              : `Giornata ${round}`}
            {typeof shown[0]?.real_matchday === 'number' ? ` · giornata reale ${shown[0].real_matchday}` : ''}
          </div>
          <div className="mt-1.5 space-y-1">
            {shown.map((f) => (
              <MiniFixture key={f.fixture_id} f={f} />
            ))}
          </div>
        </div>
      ) : null}

      {/* A competition that has not started has nothing to report: a table of
          zeros is not a standing, and it would push the ones that matter down. */}
      {started && tables.length ? (
        <div className="mt-4 space-y-3">
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
                <Link to="/standings" className="mt-1 inline-block text-xs font-semibold text-slate-500 hover:text-slate-800">
                  Classifica completa →
                </Link>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
    </Card>
  );
}

function MiniFixture({ f }: { f: LeagueFixtureItem }) {
  const finished = f.status === 'finished' && f.score;
  const row = (
    <div
      className={`flex items-center gap-2 rounded-lg px-2 py-1 text-sm ${
        f.is_user_involved ? 'bg-slate-100 font-semibold' : ''
      }`}
    >
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
  );
  return f.has_detail ? (
    <Link to={`/matches/${f.fixture_id}`} className="block hover:opacity-80">
      {row}
    </Link>
  ) : (
    row
  );
}

/** Who is in the league. The strip inside a roster page browses between teams;
 *  this is the roll call, with the crests, and it belongs on the home page. */
function Participants({ detail, myTeamName }: { detail: LeagueDetail; myTeamName: string | null }) {
  return (
    <Card className="p-4">
      <SectionTitle>Partecipanti</SectionTitle>
      <div className="mt-2 grid gap-1.5 sm:grid-cols-2">
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
                  {mine ? <span className="ml-1.5 text-[10px] font-bold uppercase text-emerald-600">la tua</span> : null}
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
