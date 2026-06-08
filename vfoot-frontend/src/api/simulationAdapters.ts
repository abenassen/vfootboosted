// Adapters from the simulation API shapes to the neutral view-models consumed
// by the shared presentational components. This is the seam that keeps the UI
// reusable: the real DB-backed league will provide an analogous adapter from
// its own API shapes to the SAME view-models, so the components don't change.

import type { StandingRowVM } from '../components/league/StandingsTable';
import type { MatchHeaderVM } from '../components/match/MatchScoreHeader';
import type { ZoneCellVM } from '../components/match/ZonePitchGrid';
import type { ZoneDuelVM } from '../components/match/ZoneDuelList';
import type { LineupVM, SubEntryVM, SubReportVM } from '../components/match/LineupPanel';
import { parseZoneKey } from '../utils/vfoot';
import type {
  SimFixtureDetail,
  SimLineup,
  SimStanding,
  SimSubstitution,
  SimTopZone,
} from '../types/simulation';

export function standingsToVM(standings: SimStanding[], highlightTeam?: string | null): StandingRowVM[] {
  return standings.map((s) => ({
    key: s.team,
    rank: s.rank,
    name: s.team,
    played: s.played,
    wins: s.wins,
    draws: s.draws,
    losses: s.losses,
    goalsFor: s.goals_for,
    goalsAgainst: s.goals_against,
    goalDiff: s.goal_diff,
    points: s.points,
    avgScore: s.avg_score_for,
    highlight: highlightTeam ? s.team === highlightTeam : false,
  }));
}

export function fixtureToHeaderVM(fx: SimFixtureDetail): MatchHeaderVM {
  return {
    homeName: fx.home_team,
    awayName: fx.away_team,
    homeGoals: fx.home_goals,
    awayGoals: fx.away_goals,
    result: fx.result,
    homeSubtitle: `Vfoot ${fx.home_score.toFixed(2)}`,
    awaySubtitle: `Vfoot ${fx.away_score.toFixed(2)}`,
  };
}

export function zonesToCells(zones: SimTopZone[]): ZoneCellVM[] {
  const cells: ZoneCellVM[] = [];
  for (const z of zones) {
    const pos = parseZoneKey(z.zone_key);
    if (!pos) continue;
    cells.push({ zoneKey: z.zone_key, col: pos.col, row: pos.row, winner: z.winner, margin: z.margin });
  }
  return cells;
}

export function zonesToDuelVM(zones: SimTopZone[], homeName: string, awayName: string): ZoneDuelVM[] {
  return zones.map((z) => ({
    zoneKey: z.zone_key,
    winner: z.winner,
    winnerLabel: z.winner === 'home' ? homeName : z.winner === 'away' ? awayName : 'Pari',
    margin: z.margin,
    contributions: z.top_contributions.map((c) => ({ feature: c.feature, swing: c.swing })),
  }));
}

function subEntryToVM(s: SimSubstitution): SubEntryVM {
  const kind = s.covered && s.bench ? 'covered' : s.reason === 'disciplinary_gap' ? 'disciplinary' : 'uncovered';
  return {
    starter: s.starter,
    gapStart: s.gap[0],
    gapEnd: s.gap[1],
    kind,
    bench: s.bench,
    coveredSeconds: s.covered_seconds,
  };
}

export function lineupToVM(lineup: SimLineup, teamName: string, side: 'home' | 'away'): LineupVM {
  const sub = lineup.substitution_report;
  const report: SubReportVM = {
    coveredSeconds: sub.covered_gap_seconds,
    uncoveredSeconds: sub.uncovered_gap_seconds,
    disciplinarySeconds: sub.disciplinary_gap_seconds,
    usedBenchCount: sub.used_bench_count,
    entries: sub.substitutions.map(subEntryToVM),
  };
  return {
    teamName,
    side,
    score: lineup.score,
    starters: [...lineup.starters]
      .sort((a, b) => b.event_score - a.event_score)
      .map((p) => ({ id: p.player_id, name: p.name, score: p.event_score })),
    bench: lineup.bench.map((p) => ({ id: p.player_id, name: p.name, score: p.event_score })),
    subReport: report,
  };
}
