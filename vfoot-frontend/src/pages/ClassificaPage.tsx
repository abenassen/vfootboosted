import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getCompetitionStructure } from '../api';
import { useLeagueContext } from '../league/LeagueContext';
import { useCompetitionContext } from '../league/CompetitionContext';
import { Badge, Card, SectionTitle } from '../components/ui';
import { StandingsTable, type StandingRowVM } from '../components/league/StandingsTable';
import type { CompetitionSection, CompetitionStructure, LeagueFixtureItem, LeagueStandingRow } from '../types/league';

const VIEW_TITLE: Record<string, string> = { classifica: 'Classifica', tabellone: 'Tabellone', risultati: 'Risultati' };

// Stage-aware results: renders a competition's SECTIONS in order — a standings table
// for each round-robin (group) stage and a bracket for each knockout stage. So a
// group+KO cup shows its group tables followed by the bracket. Follows the switcher.
export default function ClassificaPage() {
  const { selectedLeagueId, selectedLeague } = useLeagueContext();
  const { selectedCompetitionId } = useCompetitionContext();
  const [structure, setStructure] = useState<CompetitionStructure | null>(null);
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

      {/* group / league tables — side by side when there are several groups */}
      {tables.length ? (
        <div className={tables.length > 1 ? 'grid gap-4 lg:grid-cols-2' : ''}>
          {tables.map((s) => (
            <Card key={s.name} className="p-4">
              {tables.length > 1 || brackets.length ? <SectionTitle>{s.name}</SectionTitle> : null}
              <div className={tables.length > 1 || brackets.length ? 'mt-2' : ''}>
                <StandingsTable rows={rows(s.standings ?? [], selectedLeague?.team_name)} promoCount={tables.length > 1 ? 2 : 4} />
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
  return (
    <Card className="p-4">
      {section.name !== 'Coppa Classic' ? <SectionTitle>{section.name}</SectionTitle> : null}
      <div className="mt-2 grid gap-4 md:grid-cols-3">
        {rounds.map((r) => (
          <div key={r.round_no}>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{r.label}</div>
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
  const homeWin = !!done && hs > as;
  const awayWin = !!done && as > hs;
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
    </Link>
  );
}
