import type { CoveragePreview, RosterPlayer, SavedLineup, ZoneGrid } from '../types/contracts';

function zeros(n: number) {
  return Array.from({ length: n }, () => 0);
}

function sumInto(target: number[], src: number[], weight = 1) {
  for (let i = 0; i < target.length; i++) target[i] += (src[i] ?? 0) * weight;
}

function normalizeTo01(values: number[]) {
  const max = Math.max(...values, 0.0001);
  return values.map((v) => v / max);
}

export function computeCoveragePreview(
  grid: ZoneGrid,
  roster: RosterPlayer[],
  lineup: SavedLineup,
  gkSeparate: boolean
): CoveragePreview {
  const n = grid.zone_ids.length;
  const coverage = zeros(n);
  const quality = zeros(n);

  const starters = new Set(lineup.starter_player_ids);
  const gk = lineup.gk_player_id;

  for (const p of roster) {
    const isStarter = starters.has(p.player_id);
    if (!isStarter) continue;
    if (gkSeparate && gk && p.player_id === gk) {
      // GK counts, but with smaller field influence by default
      sumInto(coverage, p.estimated_influence.zone_map.values, 0.7);
      if (p.estimated_influence.quality_map) sumInto(quality, p.estimated_influence.quality_map.values, 0.7);
      else sumInto(quality, p.estimated_influence.zone_map.values, (p.price / 20) * 0.7);
    } else {
      sumInto(coverage, p.estimated_influence.zone_map.values, 1);
      if (p.estimated_influence.quality_map) sumInto(quality, p.estimated_influence.quality_map.values, 1);
      else sumInto(quality, p.estimated_influence.zone_map.values, p.price / 20);
    }
  }

  // summarize: split by rows (att at top, def at bottom)
  const defRows = Math.max(1, Math.floor(grid.rows / 3));
  const midRows = Math.max(1, Math.floor(grid.rows / 3));
  const attRows = grid.rows - defRows - midRows;

  const rowSums = Array.from({ length: grid.rows }, (_, r) => {
    let s = 0;
    for (let c = 0; c < grid.cols; c++) s += coverage[r * grid.cols + c] ?? 0;
    return s;
  });

  const att = rowSums.slice(0, attRows).reduce((a, b) => a + b, 0);
  const mid = rowSums.slice(attRows, attRows + midRows).reduce((a, b) => a + b, 0);
  const def = rowSums.slice(attRows + midRows).reduce((a, b) => a + b, 0);
  const total = att + mid + def + 1e-9;

  const normalized = normalizeTo01(coverage);
  const holes: string[] = [];
  for (let i = 0; i < normalized.length; i++) {
    if (normalized[i] < 0.18) holes.push(grid.zone_ids[i]);
  }

  return {
    team_zone_coverage: { values: normalizeTo01(coverage) },
    team_zone_quality: { values: normalizeTo01(quality) },
    summary: {
      def_mid_att: {
        def: def / total,
        mid: mid / total,
        att: att / total
      },
      critical_holes: holes.slice(0, 6)
    }
  };
}
