import type { LineupContextResponse, MatchDetailResponse, MatchListItem, SaveLineupRequest, SaveLineupResponse } from '../types/contracts';
import { mockLineupContext, mockMatches, mockMatchDetail } from './data';
import { computeCoveragePreview } from '../utils/coverage';

let inMemoryLineup = structuredClone(mockLineupContext.saved_lineup);

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function getLineupContext(): Promise<LineupContextResponse> {
  await sleep(250);
  const base = structuredClone(mockLineupContext);
  base.saved_lineup = structuredClone(inMemoryLineup);
  // recompute preview based on current lineup
  base.coverage_preview = computeCoveragePreview(base.zone_grid, base.roster, base.saved_lineup, base.rules.gk_separate_slot);
  return base;
}

export async function saveLineup(req: SaveLineupRequest): Promise<SaveLineupResponse> {
  await sleep(300);
  inMemoryLineup = {
    lineup_id: 'LU-' + Math.floor(Math.random() * 10000),
    gk_player_id: req.gk_player_id ?? null,
    starter_player_ids: req.starter_player_ids,
    bench_player_ids: req.bench_player_ids,
    starter_backups: req.starter_backups,
    ui_hints: { last_saved_at: new Date().toISOString() }
  };

  const roster = mockLineupContext.roster;
  const preview = computeCoveragePreview(mockLineupContext.zone_grid, roster, inMemoryLineup, mockLineupContext.rules.gk_separate_slot);

  const warnings: SaveLineupResponse['warnings'] = [];
  for (const pid of req.starter_player_ids) {
    const p = roster.find((x) => x.player_id === pid);
    if (p && p.status.minutes_expectation.label === 'low') {
      warnings.push({ code: 'LOW_MINUTES_RISK', player_id: pid, message: `${p.name}: rischio minutaggio` });
    }
  }

  return {
    lineup_id: inMemoryLineup.lineup_id,
    saved_at: new Date().toISOString(),
    coverage_preview: preview,
    warnings: warnings.length ? warnings : undefined
  };
}

export async function getMatches(): Promise<MatchListItem[]> {
  await sleep(200);
  return structuredClone(mockMatches);
}

export async function getMatchDetail(matchId: string): Promise<MatchDetailResponse> {
  await sleep(280);
  // Single mock; in futuro: usare matchId
  return structuredClone({ ...mockMatchDetail, match: { ...mockMatchDetail.match, match_id: matchId } });
}
