// Adapters from the simulation API shapes to the neutral view-models consumed
// by the shared presentational components. This is the seam that keeps the UI
// reusable: the real DB-backed league will provide an analogous adapter from
// its own API shapes to the SAME view-models, so the components don't change.

import type { StandingRowVM } from '../components/league/StandingsTable';
import type { MatchHeaderVM } from '../components/match/MatchScoreHeader';
import type { ZoneCellVM } from '../components/match/ZonePitchGrid';
import type { ZoneInspectorVM, ZonePlayerVM } from '../components/match/ZoneInspector';
import type { LineupPlayerVM, LineupSubEvent } from '../components/match/LineupBoard';
import type { ScoreBuildVM } from '../components/match/ScoreBuildExplainer';
import { parseZoneKey, zoneName } from '../utils/zoneNames';
import type {
  SimFixtureDetail,
  SimLineup,
  SimPlayerTotal,
  SimStanding,
  SimZone,
} from '../types/simulation';

// Feature swings below this magnitude are noise (often zero-weight features) —
// not worth showing.
const FEATURE_SWING_MIN = 0.02;

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

function playersInZone(totals: SimPlayerTotal[], zoneKey: string): ZonePlayerVM[] {
  const list = totals
    .filter((p) => zoneKey in p.zones)
    .map((p) => ({ name: p.name, contribution: p.zones[zoneKey] }));
  const sumAbs = list.reduce((s, p) => s + Math.abs(p.contribution), 0) || 1;
  return list
    .map((p) => ({ ...p, share: Math.abs(p.contribution) / sumAbs }))
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
    features: zone.features
      .filter((f) => Math.abs(f.swing) >= FEATURE_SWING_MIN)
      .slice(0, 6)
      .map((f) => ({ feature: f.feature, home: f.home, away: f.away, swing: f.swing })),
    homePlayers: playersInZone(homeTotals, zone.zone_key),
    awayPlayers: playersInZone(awayTotals, zone.zone_key),
  };
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

export function lineupBoardVMs(lineup: SimLineup, totals: SimPlayerTotal[]): LineupPlayerVM[] {
  const totalById = new Map(totals.map((t) => [t.player_id, t]));

  const subsByStarter = new Map<number, LineupSubEvent[]>();
  for (const s of lineup.substitution_report.substitutions) {
    const kind: LineupSubEvent['kind'] =
      s.covered && s.bench ? 'covered' : s.reason === 'disciplinary_gap' ? 'disciplinary' : 'uncovered';
    const ev: LineupSubEvent = {
      kind,
      gapStart: s.gap[0],
      gapEnd: s.gap[1],
      bench: s.bench,
      coveredSeconds: s.covered_seconds,
    };
    const arr = subsByStarter.get(s.starter_id) ?? [];
    arr.push(ev);
    subsByStarter.set(s.starter_id, arr);
  }

  const rows = lineup.starters.map((p) => {
    const t = totalById.get(p.player_id);
    return {
      id: p.player_id,
      name: p.name,
      zones: t ? Object.keys(t.zones) : [],
      absTotal: t ? Math.abs(t.total) : 0,
      events: subsByStarter.get(p.player_id) ?? [],
    };
  });
  const sum = rows.reduce((s, r) => s + r.absTotal, 0) || 1;
  return rows
    .map((r) => ({ id: r.id, name: r.name, zones: r.zones, share: r.absTotal / sum, events: r.events }))
    .sort((a, b) => b.share - a.share);
}
