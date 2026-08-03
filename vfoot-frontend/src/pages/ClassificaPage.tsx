import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCompetitionPrizes, getCompetitionStructure } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { useCompetitionContext } from '../league/CompetitionContext';
import { Badge, Card, SectionTitle } from '../components/ui';
import { StandingsTable, type StandingRowVM } from '../components/league/StandingsTable';
import type {
  CompetitionPrizeItem,
  CompetitionSection,
  CompetitionStructure,
  LeagueFixtureItem,
  LeagueStandingRow,
} from '../types/league';

const VIEW_TITLE: Record<string, string> = { classifica: 'Classifica', tabellone: 'Tabellone', risultati: 'Risultati' };

/** Perché è passato, quando il risultato da solo non lo spiega. Chi ha segnato di
 *  più non compare: quello si legge dal tabellone. */
const ADVANCED_REASON: Record<string, string> = {
  punteggio: 'passa ai punteggi',
  'fattore campo': 'passa per il fattore campo',
};

// Stage-aware results: renders a competition's SECTIONS in order — a standings table
// for each round-robin (group) stage and a bracket for each knockout stage. So a
// group+KO cup shows its group tables followed by the bracket. Follows the switcher.
export default function ClassificaPage() {
  const { selectedLeagueId, selectedLeague } = useLeagueContext();
  const { selectedCompetitionId } = useCompetitionContext();
  const [structure, setStructure] = useState<CompetitionStructure | null>(null);
  const [prizes, setPrizes] = useState<CompetitionPrizeItem[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selectedLeagueId || !selectedCompetitionId) {
      setStructure(null);
      return;
    }
    setLoading(true);
    void getCompetitionStructure(selectedLeagueId, selectedCompetitionId)
      .then(setStructure)
      .catch(() => setStructure(null))
      .finally(() => setLoading(false));
  }, [selectedLeagueId, selectedCompetitionId]);

  useEffect(() => {
    if (!selectedCompetitionId) {
      setPrizes([]);
      return;
    }
    let alive = true;
    void getCompetitionPrizes(selectedCompetitionId)
      .then((p) => alive && setPrizes(p))
      .catch(() => alive && setPrizes([]));
    return () => {
      alive = false;
    };
  }, [selectedCompetitionId]);

  if (!selectedLeagueId) return <div className="text-sm text-slate-500">Seleziona una lega.</div>;
  if (!selectedCompetitionId)
    return <div className="text-sm text-slate-500">Questa lega non ha ancora competizioni.</div>;
  if (loading || !structure) return <div className="text-sm text-slate-500">Caricamento…</div>;

  const tables = structure.sections.filter((s) => s.type === 'round_robin');
  const brackets = structure.sections.filter((s) => s.type === 'knockout');

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex items-center gap-2">
          <SectionTitle>{VIEW_TITLE[structure.result_view] ?? 'Risultati'}</SectionTitle>
          <Badge tone="blue">{structure.name}</Badge>
        </div>
        {structure.result_view === 'risultati' ? (
          <div className="mt-1 text-[11px] text-slate-400">Gironi (classifiche) seguiti dalla fase a eliminazione.</div>
        ) : null}
      </Card>

      {/* What is at stake, and who has already taken it. Above the table because
          a prize is the reason the table matters; a prize nobody has won yet is
          still worth reading — it says what the season is being played for. */}
      {prizes.length ? (
        <Card className="p-4">
          <SectionTitle>Premi</SectionTitle>
          <ul className="mt-2 grid gap-2 sm:grid-cols-2">
            {prizes.map((p) => (
              <li
                key={p.prize_id}
                className={
                  'flex items-start gap-2 rounded-xl border px-3 py-2 ' +
                  (p.winner_team_names.length
                    ? 'border-amber-200 bg-amber-50/60'
                    : 'border-slate-200 border-dashed')
                }
              >
                <span className="text-xl leading-none" aria-hidden>
                  {p.icon}
                </span>
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-900">{p.name}</div>
                  <div className="truncate text-[11px] text-slate-500">{p.condition_label}</div>
                  <div
                    className={
                      'truncate text-[11px] font-semibold ' +
                      (p.winner_team_names.length ? 'text-amber-800' : 'text-slate-400')
                    }
                  >
                    {p.winner_team_names.length ? p.winner_team_names.join(', ') : 'ancora da assegnare'}
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}

      {/* group / league tables — side by side when there are several groups */}
      {tables.length ? (
        <div className={tables.length > 1 ? 'grid gap-4 lg:grid-cols-2' : ''}>
          {tables.map((s) => (
            <Card key={s.name} className="p-4">
              {tables.length > 1 || brackets.length ? <SectionTitle>{s.name}</SectionTitle> : null}
              <div className={tables.length > 1 || brackets.length ? 'mt-2' : ''}>
                <StandingsTable
                  rows={rows(s.standings ?? [], selectedLeague?.team_name)}
                  prizeRanks={s.prize_ranks}
                  qualifyRanks={s.qualify_ranks}
                />
              </div>
            </Card>
          ))}
        </div>
      ) : null}

      {/* knockout brackets */}
      {brackets.map((s) => (
        <Bracket key={s.name} section={s} />
      ))}
    </div>
  );
}

function rows(s: LeagueStandingRow[], myTeam?: string | null): StandingRowVM[] {
  return s.map((r) => ({
    key: String(r.team_id),
    rank: r.rank,
    name: r.team,
    // ?? '' and not `r.crest`: undefined means "this caller has no crests at all"
    // and switches the column off for the whole table.
    crest: r.crest ?? '',
    played: r.played,
    wins: r.wins,
    draws: r.draws,
    losses: r.losses,
    goalsFor: r.goals_for,
    goalsAgainst: r.goals_against,
    goalDiff: r.goal_diff,
    points: r.points,
    avgScore: r.avg_score_for,
    highlight: myTeam ? r.team === myTeam : false,
  }));
}

function Bracket({ section }: { section: CompetitionSection }) {
  const rounds = section.rounds ?? [];
  if (!rounds.length) return null;
  // A phase that holds exactly its own round says its name twice — "Finale" over
  // "Finale" — which is how a cup built one phase per round (the shape the wizard
  // makes) came out. One of the two is enough.
  const sameName = rounds.length === 1 && rounds[0].label === section.name;
  return (
    <Card className="p-4">
      <SectionTitle>{section.name}</SectionTitle>
      <div className="mt-2 grid gap-4 md:grid-cols-3">
        {rounds.map((r) => (
          <div key={r.round_no}>
            {sameName ? null : (
              <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{r.label}</div>
            )}
            <div className="mt-2 space-y-2">
              {r.fixtures.map((f) => (
                <BracketMatch key={f.fixture_id} f={f} />
              ))}
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

function BracketMatch({ f }: { f: LeagueFixtureItem }) {
  const hs = f.score?.home_total ?? 0;
  const as = f.score?.away_total ?? 0;
  const done = f.status === 'finished' && f.score;
  // Chi passa lo dice il server: su un 1-1 il risultato non basta, e in un
  // tabellone la domanda è sempre "e adesso chi va avanti".
  const through = f.advanced_team_id ?? null;
  const homeWin = through !== null ? through === f.home_team.team_id : !!done && hs > as;
  const awayWin = through !== null ? through === f.away_team.team_id : !!done && as > hs;
  return (
    <Link to={`/matches/${f.fixture_id}`} className="block rounded-xl border border-slate-100 bg-slate-50 px-3 py-2 text-sm hover:opacity-80">
      <div className="flex items-center justify-between">
        <span className={homeWin ? 'font-bold text-slate-900' : 'text-slate-600'}>{f.home_team.name}</span>
        <span className="font-mono text-xs font-bold">{done ? Math.round(hs) : '–'}</span>
      </div>
      <div className="flex items-center justify-between">
        <span className={awayWin ? 'font-bold text-slate-900' : 'text-slate-600'}>{f.away_team.name}</span>
        <span className="font-mono text-xs font-bold">{done ? Math.round(as) : '–'}</span>
      </div>
      {f.advanced_reason ? (
        <div className="mt-1 text-[10px] uppercase tracking-wide text-slate-400">
          {ADVANCED_REASON[f.advanced_reason] ?? `passa: ${f.advanced_reason}`}
        </div>
      ) : null}
    </Link>
  );
}
