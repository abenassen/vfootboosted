# Serie A Historical Data (Hybrid Baseline)

Downloaded on: 2026-02-12

## Folder Contents

- `statsbomb/`
  - `competitions.json`
  - `matches_12_27.json` (Serie A 2015/2016, 380 matches)
  - `events/*.json` (380 match event files)
  - `lineups/*.json` (380 lineup files)
- `wyscout/`
  - `raw_data/events.zip`, `raw_data/matches.zip`
  - `raw_data/players.json`, `raw_data/teams.json`
  - `extracted/events_Italy.json`, `extracted/matches_Italy.json`

## What Data Is Available

### StatsBomb (Open Data)

- Match-level metadata:
  - teams, score, date, stadium, matchweek, stage
- Event stream per match (coordinates included):
  - location system approx. `x in [0,120]`, `y in [0,80]`
  - event typing (`Pass`, `Carry`, `Duel`, `Shot`, etc.)
  - time indexing (`minute`, `second`, `period`)
- Lineups per match:
  - player identities, positions, cards, jersey numbers

Important: this source does not provide a direct player heatmap image in the files; heatmaps must be derived from event coordinates.

### Wyscout (Public Dataset)

- `events_Italy.json` event stream:
  - coordinates in `positions[]` with approx. `x,y in [0,100]`
  - event/sub-event taxonomy (`eventName`, `subEventName`)
  - event tags (`tags`) useful for outcomes/quality signals
  - links to player/team/match (`playerId`, `teamId`, `matchId`)
- `matches_Italy.json`:
  - match metadata, teamsData, winner, competition/season IDs
- `players.json`, `teams.json`:
  - entity metadata and role/team references

Again: no precomputed player heatmap object, but enough positional events to compute zone presence.

## Suitability for Current Vfoot Blueprint

Blueprint target:
1. Determine who is effectively active in each area/zone.
2. Compare home vs away in each zone using performance features.
3. Assign zone points and aggregate final score.

Both datasets are usable for this.

### Step A: Build Zone Presence (effective activity)

1. Normalize pitch coordinates to one internal system (recommended `[0,1] x [0,1]`).
   - StatsBomb: divide by `(120,80)`.
   - Wyscout: divide by `(100,100)`.
2. Normalize attacking direction so home/away are comparable by zone.
3. For each player in a match:
   - collect relevant on-ball event coordinates (pass origin, carry start/end, shot, duel, touches, recoveries, etc.)
   - bin into Vfoot grid zones (default 5x4)
   - compute normalized presence distribution over zones (sum=1)

### Step B: Build Zone Performance Features

Per player-zone, derive metrics such as:
- volume: touches/actions in zone
- quality: successful passes, progressive actions, duel outcomes, chance creation
- defensive impact: recoveries, interceptions, blocks, clearances

Then aggregate by team in each zone using presence-weighted contributions.

### Step C: Zone Duel and Scoring

For each zone:
- compute home/away zone score from weighted player features
- determine local winner/draw
- apply zone points + duel modifier (current baseline ±10%)
- enforce overcrowding rule:
  - if total effective presence in zone > 1, renormalize and discard excess efficiency

Aggregate all zone outputs to produce final home/away totals + explainable breakdown.

## Practical Limits / Caveats

- These are historical snapshots, not current-season live Serie A.
- Neither source provides direct SofaScore-like prebuilt heatmaps.
- Performance-to-fantavote mapping must be calibrated (model layer needed).
- Coordinate orientation and event-type harmonization are critical for consistency.

## Recommended Next Implementation Step

Create provider adapters:
- `adapters/statsbomb.py`
- `adapters/wyscout.py`

Each adapter should output a canonical event schema:
- `match_id`, `team_side`, `player_id`, `event_type`, `success_flag`, `x`, `y`, `minute`, `period`

Then feed the canonical stream into one shared Vfoot pipeline for:
- zone presence,
- area/zone duel comparison,
- point assignment and final score.
