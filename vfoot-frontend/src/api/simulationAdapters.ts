// Adapters from the simulation API shapes to the neutral view-models consumed
// by the shared presentational components. This is the seam that keeps the UI
// reusable: the real DB-backed league will provide an analogous adapter from
// its own API shapes to the SAME view-models, so the components don't change.

import type { StandingRowVM } from '../components/league/StandingsTable';
import type { MatchHeaderVM } from '../components/match/MatchScoreHeader';
import type { ZoneCellVM } from '../components/match/ZonePitchGrid';
import type { ZoneInspectorVM } from '../components/match/ZoneInspector';
import type { PlayerInfluenceVM } from '../components/match/PlayerInfluence';
import type { ScoreBuildVM } from '../components/match/ScoreBuildExplainer';
import type { LineupVM, SubEntryVM, SubReportVM } from '../components/match/LineupPanel';
import { parseZoneKey, zoneName } from '../utils/zoneNames';
import type {
  SimFixtureDetail,
  SimLineup,
  SimPlayerTotal,
  SimStanding,
  SimSubstitution,
  SimZone,
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

export function zonesToCells(zones: SimZone[]): ZoneCellVM[] {
  return zones.map((z) => {
    const pos = parseZoneKey(z.zone_key) ?? { col: 0, row: 0 };
    return {
      zoneKey: z.zone_key,
      col: pos.col,
      row: pos.row,
      winner: z.winner,
      margin: z.margin,
      hasPresence: z.features.length > 0,
    };
  });
}

function playersInZone(totals: SimPlayerTotal[], zoneKey: string) {
  return totals
    .filter((p) => zoneKey in p.zones)
    .map((p) => ({ name: p.name, contribution: p.zones[zoneKey] }))
    .sort((a, b) => Math.abs(b.contribution) - Math.abs(a.contribution));
}

export function buildZoneInspector(
  zone: SimZone,
  homeTotals: SimPlayerTotal[],
  awayTotals: SimPlayerTotal[],
  homeName: string,
  awayName: string,
): ZoneInspectorVM {
  return {
    zoneKey: zone.zone_key,
    name: zoneName(zone.zone_key),
    winner: zone.winner,
    winnerLabel: zone.winner === 'home' ? homeName : zone.winner === 'away' ? awayName : 'Pari',
    margin: zone.margin,
    homeName,
    awayName,
    features: zone.features.map((f) => ({ feature: f.feature, home: f.home, away: f.away, swing: f.swing })),
    homePlayers: playersInZone(homeTotals, zone.zone_key),
    awayPlayers: playersInZone(awayTotals, zone.zone_key),
  };
}

export function playerInfluenceVMs(totals: SimPlayerTotal[]): PlayerInfluenceVM[] {
  return totals.map((p) => ({
    playerId: p.player_id,
    name: p.name,
    total: p.total,
    footprint: Object.entries(p.zones)
      .map(([zoneKey, value]) => ({ zoneKey, value: value as number }))
      .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
      .slice(0, 5),
  }));
}

export function scoreBuildVM(fx: SimFixtureDetail): ScoreBuildVM {
  const sb = fx.vector_report.score_build;
  return {
    base: sb.base,
    scoreScale: sb.score_scale,
    boost: sb.fantasy_margin_boost,
    meanMargin: fx.vector_report.total_margin,
    boostedMargin: fx.vector_report.boosted_margin,
    zoneCount: sb.zone_count,
    homeName: fx.home_team,
    awayName: fx.away_team,
    homeScore: fx.home_score,
    awayScore: fx.away_score,
  };
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

export function lineupToSubReport(lineup: SimLineup): SubReportVM {
  const sub = lineup.substitution_report;
  return {
    coveredSeconds: sub.covered_gap_seconds,
    uncoveredSeconds: sub.uncovered_gap_seconds,
    disciplinarySeconds: sub.disciplinary_gap_seconds,
    usedBenchCount: sub.used_bench_count,
    entries: sub.substitutions.map(subEntryToVM),
  };
}

export function lineupToVM(lineup: SimLineup, teamName: string, side: 'home' | 'away'): LineupVM {
  return {
    teamName,
    side,
    score: lineup.score,
    starters: [...lineup.starters]
      .sort((a, b) => b.event_score - a.event_score)
      .map((p) => ({ id: p.player_id, name: p.name, score: p.event_score })),
    bench: lineup.bench.map((p) => ({ id: p.player_id, name: p.name, score: p.event_score })),
    subReport: lineupToSubReport(lineup),
  };
}
