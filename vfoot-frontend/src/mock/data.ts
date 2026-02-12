import type {
  CoveragePreview,
  LineupContextResponse,
  MatchDetailResponse,
  MatchListItem,
  RosterPlayer,
  ZoneGrid,
  ZoneMapNumber
} from '../types/contracts';

function makeZoneGrid(cols = 6, rows = 4): ZoneGrid {
  const zone_ids: string[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      zone_ids.push(`z${r.toString().padStart(2, '0')}${c.toString().padStart(2, '0')}`);
    }
  }
  return { cols, rows, zone_ids, meta: { labeling: 'left-to-right top-to-bottom' } };
}

function clamp01(x: number) {
  return Math.max(0, Math.min(1, x));
}

function rand(seed: number) {
  // deterministic pseudo-random
  let t = seed + 0x6d2b79f5;
  t = Math.imul(t ^ (t >>> 15), t | 1);
  t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}

function gaussian2D(grid: ZoneGrid, cx: number, cy: number, sx: number, sy: number, seed: number): ZoneMapNumber {
  const out: number[] = [];
  for (let r = 0; r < grid.rows; r++) {
    for (let c = 0; c < grid.cols; c++) {
      const x = c / (grid.cols - 1);
      const y = r / (grid.rows - 1);
      const dx = (x - cx) / sx;
      const dy = (y - cy) / sy;
      const base = Math.exp(-0.5 * (dx * dx + dy * dy));
      const n = (rand(seed + r * 97 + c * 131) - 0.5) * 0.08;
      out.push(clamp01(base + n));
    }
  }
  return { values: out };
}

function scaleMap(m: ZoneMapNumber, k: number): ZoneMapNumber {
  return { values: m.values.map((v) => v * k) };
}

function addMaps(a: ZoneMapNumber, b: ZoneMapNumber): ZoneMapNumber {
  return { values: a.values.map((v, i) => v + (b.values[i] ?? 0)) };
}

function normalizeMap(m: ZoneMapNumber): ZoneMapNumber {
  const max = Math.max(...m.values, 1e-9);
  return { values: m.values.map((v) => v / max) };
}

function makePlayer(grid: ZoneGrid, i: number): RosterPlayer {
  const price = Math.round(4 + rand(10 + i) * 20);

  // pick a typical region (roughly: goalie near bottom center, defenders low, mids center, attackers high)
  const roleRoll = rand(1000 + i);
  let cx = 0.5;
  let cy = 0.6;
  let sx = 0.18;
  let sy = 0.18;
  let real_team = ['Inter', 'Milan', 'Juve', 'Roma', 'Napoli', 'Atalanta'][i % 6];

  if (roleRoll < 0.08) {
    // GK
    cx = 0.5;
    cy = 0.95;
    sx = 0.12;
    sy = 0.10;
  } else if (roleRoll < 0.35) {
    // DEF
    cx = 0.15 + rand(200 + i) * 0.7;
    cy = 0.78;
    sx = 0.20;
    sy = 0.18;
  } else if (roleRoll < 0.75) {
    // MID
    cx = 0.15 + rand(300 + i) * 0.7;
    cy = 0.55;
    sx = 0.22;
    sy = 0.22;
  } else {
    // ATT
    cx = 0.20 + rand(400 + i) * 0.6;
    cy = 0.25;
    sx = 0.20;
    sy = 0.18;
  }

  const zone_map = gaussian2D(grid, cx, cy, sx, sy, 5000 + i);
  const quality = normalizeMap(scaleMap(zone_map, 0.4 + price / 30));

  const minutes = rand(7000 + i);
  const minutes_expectation = minutes > 0.7 ? { value: 0.85, label: 'high' as const } : minutes > 0.35 ? { value: 0.55, label: 'medium' as const } : { value: 0.25, label: 'low' as const };

  return {
    player_id: `P${100 + i}`,
    name: `Giocatore ${String.fromCharCode(65 + (i % 26))}${i}`,
    real_team,
    price,
    status: {
      injury: null,
      suspension: false,
      minutes_expectation
    },
    estimated_influence: {
      zone_map,
      quality_map: quality,
      provenance: {
        source: 'sofascore (mock)',
        confidence: 0.55 + rand(9000 + i) * 0.35,
        notes: 'Stimato da ultime partite disponibili'
      }
    }
  };
}

function computeCoverage(grid: ZoneGrid, roster: RosterPlayer[], starterIds: string[]): CoveragePreview {
  const zero: ZoneMapNumber = { values: grid.zone_ids.map(() => 0) };
  let cov = zero;
  let qual = zero;
  for (const pid of starterIds) {
    const p = roster.find((x) => x.player_id === pid);
    if (!p) continue;
    cov = addMaps(cov, p.estimated_influence.zone_map);
    qual = addMaps(qual, p.estimated_influence.quality_map ?? p.estimated_influence.zone_map);
  }
  const covN = normalizeMap(cov);
  const qualN = normalizeMap(qual);

  // rough summaries by height: rows split into 3 bands
  const band = (r: number) => (r < grid.rows / 3 ? 'att' : r < (2 * grid.rows) / 3 ? 'mid' : 'def');
  let def = 0,
    mid = 0,
    att = 0;
  let defN = 0,
    midN = 0,
    attN = 0;
  for (let r = 0; r < grid.rows; r++) {
    for (let c = 0; c < grid.cols; c++) {
      const i = r * grid.cols + c;
      const v = covN.values[i];
      if (band(r) === 'def') def += v;
      if (band(r) === 'mid') mid += v;
      if (band(r) === 'att') att += v;
      defN += band(r) === 'def' ? 1 : 0;
      midN += band(r) === 'mid' ? 1 : 0;
      attN += band(r) === 'att' ? 1 : 0;
    }
  }

  const critical_holes: string[] = [];
  const threshold = 0.22;
  covN.values.forEach((v, idx) => {
    if (v < threshold) critical_holes.push(grid.zone_ids[idx]);
  });

  return {
    team_zone_coverage: covN,
    team_zone_quality: qualN,
    summary: {
      def_mid_att: {
        def: def / Math.max(1, defN),
        mid: mid / Math.max(1, midN),
        att: att / Math.max(1, attN)
      },
      critical_holes: critical_holes.slice(0, 6)
    }
  };
}

export const mockZoneGrid = makeZoneGrid(6, 4);

export const mockRoster: RosterPlayer[] = Array.from({ length: 20 }).map((_, i) => makePlayer(mockZoneGrid, i));

const defaultStarters = mockRoster.slice(0, 11).map((p) => p.player_id);
const defaultBench = mockRoster.slice(11, 16).map((p) => p.player_id);

export const mockLineupContext: LineupContextResponse = {
  league: { id: 'L1', name: 'Lega Friends' },
  matchday: { id: 'MD24', name: 'Giornata 24', deadline: '2026-02-13T19:45:00Z' },
  rules: { starters_count: 11, bench_count: 5, gk_separate_slot: true, allow_any_substitution: true },
  zone_grid: mockZoneGrid,
  squad: { team_id: 'T12', name: 'Casa FC', colors: { primary: '#0f172a', secondary: '#38bdf8' } },
  roster: mockRoster,
  saved_lineup: {
    lineup_id: 'LU88',
    gk_player_id: defaultStarters[0],
    starter_player_ids: defaultStarters,
    bench_player_ids: defaultBench,
    starter_backups: [
      { starter_player_id: defaultStarters[2], backup_player_ids: [defaultBench[0], defaultBench[1]] },
      { starter_player_id: defaultStarters[3], backup_player_ids: [defaultBench[2]] }
    ],
    ui_hints: { last_saved_at: '2026-02-11T21:00:00Z' }
  },
  coverage_preview: computeCoverage(mockZoneGrid, mockRoster, defaultStarters),
  provenance: { source: 'sofascore (mock)', confidence: 0.6 }
};

export const mockMatches: MatchListItem[] = [
  { match_id: 'M778', home: { team_id: 'T12', name: 'Casa FC' }, away: { team_id: 'T55', name: 'Trasferta FC' }, status: 'finished', score: { home_total: 72.4, away_total: 68.1 } },
  { match_id: 'M779', home: { team_id: 'T33', name: 'FC Aurora' }, away: { team_id: 'T12', name: 'Casa FC' }, status: 'finished', score: { home_total: 61.2, away_total: 70.0 } }
];

function makeMatchDetail(match_id = 'M778'): MatchDetailResponse {
  const grid = mockZoneGrid;
  const homeName = 'Casa FC';
  const awayName = 'Trasferta FC';

  // create zone swings
  const pointsValues: number[] = [];
  const marginValues: number[] = [];
  const winnerValues: Array<'home' | 'away' | 'draw'> = [];
  const keyFactorValues: string[] = [];

  const zone_results: MatchDetailResponse['zone_results'] = [];

  for (let i = 0; i < grid.zone_ids.length; i++) {
    const z = grid.zone_ids[i];
    const raw = rand(20000 + i * 17);
    const swing = (raw - 0.5) * 3.0; // roughly -1.5..+1.5
    const margin = Math.abs(swing) / 2.0;
    const points = Math.abs(swing) * (0.6 + rand(21000 + i) * 0.8); // 0..~2
    const winner: 'home' | 'away' | 'draw' = Math.abs(swing) < 0.15 ? 'draw' : swing > 0 ? 'home' : 'away';

    const key = ['defense', 'passing', 'attack', 'errors'][Math.floor(rand(22000 + i) * 4)];
    keyFactorValues.push(key);

    winnerValues.push(winner);
    pointsValues.push(points);
    marginValues.push(margin);

    const ms = {
      defense: { home: clamp01(0.4 + rand(23000 + i) * 0.6), away: clamp01(0.4 + rand(24000 + i) * 0.6), swing: 0 },
      passing: { home: clamp01(0.4 + rand(25000 + i) * 0.6), away: clamp01(0.4 + rand(26000 + i) * 0.6), swing: 0 },
      attack: { home: clamp01(0.4 + rand(27000 + i) * 0.6), away: clamp01(0.4 + rand(28000 + i) * 0.6), swing: 0 },
      errors: { home: clamp01(0.4 + rand(29000 + i) * 0.6), away: clamp01(0.4 + rand(30000 + i) * 0.6), swing: 0 }
    };
    for (const k of Object.keys(ms) as Array<keyof typeof ms>) {
      ms[k].swing = ms[k].home - ms[k].away;
    }

    // top contributors: take a couple roster players
    const h1 = mockRoster[Math.floor(rand(31000 + i) * 10)];
    const h2 = mockRoster[Math.floor(rand(32000 + i) * 10)];
    const a1 = mockRoster[10 + Math.floor(rand(33000 + i) * 10)];
    const a2 = mockRoster[10 + Math.floor(rand(34000 + i) * 10)];

    zone_results.push({
      zone_id: z,
      winner,
      points: { home: winner === 'home' ? points : 0, away: winner === 'away' ? points : 0, swing: winner === 'home' ? +points : winner === 'away' ? -points : 0 },
      margin,
      macro_scores: ms,
      key_factor: key,
      top_contributors: {
        home: [
          { player_id: h1.player_id, name: h1.name, contrib: +(0.1 + rand(35000 + i) * 0.6).toFixed(2) },
          { player_id: h2.player_id, name: h2.name, contrib: +(0.05 + rand(36000 + i) * 0.4).toFixed(2) }
        ],
        away: [
          { player_id: a1.player_id, name: a1.name, contrib: +(0.1 + rand(37000 + i) * 0.6).toFixed(2) },
          { player_id: a2.player_id, name: a2.name, contrib: +(0.05 + rand(38000 + i) * 0.4).toFixed(2) }
        ]
      },
      explain_stats: {
        attack: [
          { label: 'Tiri', home: Math.floor(rand(39000 + i) * 4), away: Math.floor(rand(40000 + i) * 4) },
          { label: 'Tocchi in area', home: Math.floor(rand(41000 + i) * 8), away: Math.floor(rand(42000 + i) * 8) }
        ],
        defense: [{ label: 'Tackle vinti', home: Math.floor(rand(43000 + i) * 5), away: Math.floor(rand(44000 + i) * 5) }]
      }
    });
  }

  // totals
  const homeZones = zone_results.reduce((s, z) => s + z.points.home, 0);
  const awayZones = zone_results.reduce((s, z) => s + z.points.away, 0);
  const homeTotal = 32.8 + homeZones;
  const awayTotal = 33.9 + awayZones;

  const decisive = [...zone_results]
    .sort((a, b) => Math.abs(b.points.swing) - Math.abs(a.points.swing))
    .slice(0, 3)
    .map((z) => z.zone_id);

  const swingRight = zone_results
    .filter((z) => z.zone_id.endsWith('05'))
    .reduce((s, z) => s + z.points.swing, 0);

  return {
    match: { match_id, league_id: 'L1', matchday_id: 'MD24', status: 'finished' },
    teams: {
      home: { team_id: 'T12', name: homeName, colors: { primary: '#0f172a', secondary: '#38bdf8' } },
      away: { team_id: 'T55', name: awayName, colors: { primary: '#7c2d12', secondary: '#fb7185' } }
    },
    zone_grid: grid,
    score: {
      home_total: +homeTotal.toFixed(1),
      away_total: +awayTotal.toFixed(1),
      breakdown: {
        zones_total: { home: +homeZones.toFixed(1), away: +awayZones.toFixed(1) },
        base_total: { home: 32.8, away: 33.9 }
      }
    },
    story: {
      takeaways: [
        { text: `Differenza sulle zone decisive: ${decisive.join(', ')}`, swing: +(homeZones - awayZones).toFixed(1) },
        { text: `Fascia destra swing: ${swingRight >= 0 ? '+' : ''}${swingRight.toFixed(1)}`, zone_group: 'right_flank', swing: +swingRight.toFixed(1) }
      ],
      decisive_zones: decisive
    },
    zone_results,
    zone_maps: {
      winner_map: { values: winnerValues },
      points_map: { values: pointsValues },
      margin_map: { values: marginValues },
      key_factor_map: { values: keyFactorValues }
    },
    line_summaries: {
      by_flank: {
        left: { swing: +zone_results.filter((_, idx) => idx % grid.cols < 2).reduce((s, z) => s + z.points.swing, 0).toFixed(1) },
        center: { swing: +zone_results.filter((_, idx) => idx % grid.cols >= 2 && idx % grid.cols <= 3).reduce((s, z) => s + z.points.swing, 0).toFixed(1) },
        right: { swing: +zone_results.filter((_, idx) => idx % grid.cols > 3).reduce((s, z) => s + z.points.swing, 0).toFixed(1) }
      },
      by_height: {
        def: { swing: +zone_results.filter((_, idx) => Math.floor(idx / grid.cols) > 2).reduce((s, z) => s + z.points.swing, 0).toFixed(1) },
        mid: { swing: +zone_results.filter((_, idx) => Math.floor(idx / grid.cols) === 2).reduce((s, z) => s + z.points.swing, 0).toFixed(1) },
        att: { swing: +zone_results.filter((_, idx) => Math.floor(idx / grid.cols) < 2).reduce((s, z) => s + z.points.swing, 0).toFixed(1) }
      }
    },
    provenance: { source: 'sofascore (mock)', confidence: 0.62 }
  };
}

export const mockMatchDetail: MatchDetailResponse = makeMatchDetail('M778');
