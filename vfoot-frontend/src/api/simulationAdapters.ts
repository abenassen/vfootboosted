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
import { mirrorZoneKey, parseZoneKey, zoneName } from '../utils/zoneNames';
import type {
  SimFixtureDetail,
  SimLineup,
  SimPlayerTotal,
  SimStanding,
  SimZone,
  SimZonePlayer,
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

function zonePlayersVM(players: SimZonePlayer[]): ZonePlayerVM[] {
  // Stored per-zone contributors (already specular & top-N from the backend).
  const sumAbs = players.reduce((s, p) => s + Math.abs(p.contribution), 0) || 1;
  return players.map((p) => ({
    name: p.name,
    contribution: p.contribution,
    share: Math.abs(p.contribution) / sumAbs,
  }));
}

export function buildZoneInspector(zone: SimZone, homeName: string, awayName: string): ZoneInspectorVM {
  return {
    zoneKey: zone.zone_key,
    name: zoneName(zone.zone_key),
    winner: zone.winner,
    winnerLabel: zone.winner === 'home' ? homeName : zone.winner === 'away' ? awayName : 'Pari',
    margin: zone.margin,
    homeName,
    awayName,
    macros: zone.macros.map((m) => ({ label: m.label, homeShare: m.home_share })),
    features: zone.features
      .filter((f) => Math.abs(f.swing) >= FEATURE_SWING_MIN)
      .slice(0, 6)
      .map((f) => ({ feature: f.feature, home: f.home, away: f.away, swing: f.swing })),
    // Per-zone players come straight from the backend (consistent with the
    // radar/feature bars; away side already mirrored to the physical zone).
    homePlayers: zonePlayersVM(zone.home_players),
    awayPlayers: zonePlayersVM(zone.away_players),
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
    homeGkAdjustment: fx.home_lineup.gk_adjustment ?? 0,
    awayGkAdjustment: fx.away_lineup.gk_adjustment ?? 0,
  };
}

// Spatial centre of gravity along the pitch length (0 = own defense, 4 =
// attack), weighted by the magnitude of the player's zone contributions.
function averageColumn(zones: Record<string, number>): number | null {
  let weighted = 0;
  let total = 0;
  for (const [zoneKey, value] of Object.entries(zones)) {
    const pos = parseZoneKey(zoneKey);
    if (!pos) continue;
    const w = Math.abs(value);
    weighted += w * pos.col;
    total += w;
  }
  return total > 0 ? weighted / total : null;
}

export function lineupBoardVMs(
  lineup: SimLineup,
  totals: SimPlayerTotal[],
  mirror = false,
): LineupPlayerVM[] {
  const totalById = new Map(totals.map((t) => [t.player_id, t]));

  const subsByStarter = new Map<number, LineupSubEvent[]>();
  for (const s of lineup.substitution_report.substitutions) {
    const kind: LineupSubEvent['kind'] =
      s.covered && s.bench ? 'covered' : s.reason === 'disciplinary_gap' ? 'disciplinary' : 'uncovered';
    const gapTotal = s.gap[1] - s.gap[0];
    const ev: LineupSubEvent = {
      kind,
      gapKind: (s.gap_kind as LineupSubEvent['gapKind']) ?? 'post_exit',
      gapStart: s.gap[0],
      gapEnd: s.gap[1],
      bench: s.bench,
      benchPositive: s.bench_id != null ? (totalById.get(s.bench_id)?.total ?? 0) >= 0 : true,
      coveredSeconds: s.covered_seconds,
      uncoveredSeconds: Math.max(0, gapTotal - (s.covered_seconds ?? 0)),
    };
    const arr = subsByStarter.get(s.starter_id) ?? [];
    arr.push(ev);
    subsByStarter.set(s.starter_id, arr);
  }

  // A lineup SLOT = the starter + the bench player(s) who covered their gaps.
  // Influence bar, role and order are computed on the COMBINED slot, so a
  // substituted/absent starter shows the contribution and role of who actually
  // played that slot (the dominant contributor by |contribution|).
  const roleById = new Map<number, string>();
  for (const p of [...lineup.starters, ...lineup.bench]) {
    if (p.role) roleById.set(p.player_id, p.role);
  }
  // starter_id -> bench player ids that covered them
  const subIdsByStarter = new Map<number, number[]>();
  for (const s of lineup.substitution_report.substitutions) {
    if (s.covered && s.bench_id != null) {
      const arr = subIdsByStarter.get(s.starter_id) ?? [];
      arr.push(s.bench_id);
      subIdsByStarter.set(s.starter_id, arr);
    }
  }

  const rows = lineup.starters.map((p) => {
    const subIds = subIdsByStarter.get(p.player_id) ?? [];
    const memberIds = [p.player_id, ...subIds];
    const combinedZones: Record<string, number> = {};
    const addZones = (zones: Record<string, number>) => {
      for (const [zoneKey, value] of Object.entries(zones)) {
        combinedZones[zoneKey] = (combinedZones[zoneKey] ?? 0) + value;
      }
    };
    let combinedTotal = 0;
    let dominantId = p.player_id;
    let dominantAbs = -1;
    for (const id of memberIds) {
      const t = totalById.get(id);
      if (!t) continue;
      addZones(t.zones);
      combinedTotal += t.total;
      if (Math.abs(t.total) > dominantAbs) {
        dominantAbs = Math.abs(t.total);
        dominantId = id;
      }
    }
    // Role of the slot = role of the dominant contributor (who actually played
    // it most), falling back to the nominal starter's role.
    const role = roleById.get(dominantId) ?? roleById.get(p.player_id) ?? null;
    // Footprint zones go on the shared (home-perspective) map, so away players
    // are mirrored. avgCol stays in the OWN frame, used only for fine ordering.
    const ownZoneKeys = Object.keys(combinedZones);
    return {
      id: p.player_id,
      name: p.name,
      role,
      zones: mirror ? ownZoneKeys.map(mirrorZoneKey) : ownZoneKeys,
      absTotal: Math.abs(combinedTotal),
      starterPositive: (totalById.get(p.player_id)?.total ?? 0) >= 0,
      avgCol: averageColumn(combinedZones),
      events: subsByStarter.get(p.player_id) ?? [],
    };
  });
  const maxAbs = Math.max(0.0001, ...rows.map((r) => r.absTotal));
  return rows.map((r) => ({
    id: r.id,
    name: r.name,
    role: r.role,
    zones: r.zones,
    relevance: r.absTotal / maxAbs,
    starterPositive: r.starterPositive,
    avgCol: r.avgCol,
    events: r.events,
  }));
}
