# Vfoot Boosted Project Progress

This file tracks current project status, implementation milestones, and concrete next steps.
It is meant to be updated as work progresses so future sessions can recover context quickly.

## Current Focus

### M7 - Real-Data Scoring Integration

Goal: turn the imported historical StatsBomb data into a playable Vfoot scoring model that produces reasonable fantasy match results and explainable zone breakdowns.

The project already has:

- a Django/DRF backend with fantasy leagues, teams, rosters, competitions, fixtures, auth, and lineup endpoints;
- a React/Vite frontend with mock/backend API switching;
- a zone-duel engine with 5x4 pitch grid, overcrowding normalization, and fixed +/-10% duel modifier;
- imported StatsBomb Serie A data in local SQLite feature tables.

The current gap is that key gameplay endpoints still rely partly on synthetic/hash-generated heatmaps, ratings, teams, and match details. M7 replaces those placeholders with provider-derived data and a calibrated first scoring model.

## Milestone History

- M0 - Workspace and architecture split: completed.
- M1 - Contract-first Vfoot backend and zone engine: completed.
- M2 - Frontend mock product flow: completed.
- M3 - Auth and protected app shell: completed.
- M4 - League admin, roster, competitions, fixtures, auctions: completed.
- M5 - Playwright smoke/e2e scaffolding: completed, with local sandbox limitations.
- M6 - StatsBomb feature ingestion: completed for local dev baseline.
- M7 - Real-data scoring integration: in progress.

## M7 Work Plan

1. Audit imported StatsBomb feature keys, coverage, and value distributions.
2. Define a first player-zone presence model from real feature volumes.
3. Define a first player-zone quality model from interpretable event features.
4. Build a real-data scoring service that outputs the existing match detail contract.
5. Calibrate score ranges across historical fixtures.
6. Wire fixture scoring and frontend match detail to real-data outputs.

## M7 Audit Notes

Completed first audit on 2026-06-07.

Local SQLite baseline:

- `Match`: 380
- `MatchAppearance`: 16,750
- `PlayerZoneFeature`: 608,647
- `TeamZoneFeature`: 175,961
- `DataIngestionManifest`: 1

Feature keys available in both player-zone and team-zone tables:

- `touches`
- `passes_attempted`
- `passes_completed`
- `passes_into_box`
- `progressive_passes_completed`
- `progressive_carries`
- `key_passes`
- `shots`
- `xg_shots`
- `touches_in_box`
- `pressures`
- `ball_recoveries`
- `interceptions`
- `blocks`
- `clearances`
- `duels_won`
- `errors_bad_passes`
- `errors_dispossessed`
- `errors_fouls_committed`
- `errors_miscontrols`

Zone keys in imported feature tables use StatsBomb import format:

- `Z_col_row`, e.g. `Z_3_2`

The current API grid uses:

- `zrowcol`, e.g. `z0203`

A mapping layer is required and has been added in `vfoot.services.realdata_scoring`.

Important caveat:

- `MatchAppearance.minutes_played` is not reliable for all players in this import.
- Many appearances have 0 minutes, while event features exist for 10,572 player-match rows with `touches`.
- First playable model should therefore rely primarily on event volume for active-player filtering and presence, not on imported minutes.

Useful observed player-match distributions:

- `touches`: n=10,572, p50=95, p90=179, p99=266, max=572
- `passes_attempted`: n=10,530, p50=33, p90=65, p99=97, max=204
- `pressures`: n=9,740, p50=12, p90=25, p99=38, max=73
- `shots`: n=5,179, p50=1, p90=4, p99=6, max=12
- `xg_shots`: n=5,179, p50=0.081, p90=0.461, p99=1.232, max=1.980

## M7 Model Notes

Initial service added:

- `vfoot/services/realdata_scoring.py`

First playable formula version:

- `realdata_scoring_v1`

Presence model:

- compute player-zone volume from weighted event counts;
- normalize per player so sum over zones is 1;
- skip players without positive presence volume;
- preserve overcrowding rule at team-zone scoring time.

Presence feature weights:

- `touches`: 1.00
- `pressures`: 0.35
- `ball_recoveries`: 0.50
- `interceptions`: 0.50
- `blocks`: 0.40
- `clearances`: 0.30

Quality model:

- start from `BASE_ZONE_RATING = 5.50`;
- add interpretable weighted event contributions per player-zone;
- clamp each zone rating to `[4.00, 8.50]`;
- first baseline sets `fantavote = pure_vote`;
- future goal/card fantasy modifiers should be layered later.

Positive quality features include completed/progressive passes, progressive carries, key passes, passes into box, shots, xG, box touches, duels won, recoveries, interceptions, blocks, clearances, pressures.

Negative quality features include bad passes, dispossessions, fouls committed, and miscontrols.

First live DB check:

- Source match: Atalanta vs Udinese, StatsBomb external id `3879863`
- Starter-like selection: first 11 home/away appearances ordered by starter/minutes/id
- Result: home `62.903`, away `62.039`
- Contract output includes 20 zones, decisive zones, zone maps, top contributors, and provenance.

Calibration sample:

- First 80 real matches with touch features.
- Home average/min/max: `64.086 / 59.948 / 67.492`
- Away average/min/max: `64.156 / 59.464 / 69.330`
- Combined average/min/max: `64.121 / 59.464 / 69.330`
- Differential average/min/max: `-0.069 / -9.382 / 7.517`

Interpretation:

- The first model produces stable, plausible score ranges.
- It is slightly low relative to legacy goal conversion threshold `66`.
- Calibration must decide whether to raise the base rating, rescale totals, or use a Vfoot-specific goal conversion.
- The current formula is intentionally transparent and non-ML; it is suitable as a baseline for calibration.

Goal-conversion calibration check:

- Dataset: all 380 imported StatsBomb matches.
- Evaluation setup: use each real team's own starter-like player set as a proxy lineup.
- Real average goals per team: `1.288`.
- Raw Vfoot score average per team: `64.176`.
- Raw Vfoot score sign accuracy against real W/D/L: `42.89%`.
- Standard Fantacalcio goal conversion without calibration:
  - very poor goal volume because most scores are below 66;
  - average predicted goals per team: `0.124`;
  - W/D/L accuracy after conversion: `31.32%`;
  - exact scoreline accuracy: `8.68%`;
  - goal MAE per team: `1.228`.

First calibrated conversion experiment:

```text
adjusted_home = raw_home + offset + home_advantage + diff_boost * (raw_home - raw_away)
adjusted_away = raw_away + offset - home_advantage - diff_boost * (raw_home - raw_away)
goals = standard Fantacalcio conversion on adjusted score
```

Best low-MAE candidates from a small grid:

- `offset=8.0`, `diff_boost=0.25`, `home_advantage=0.5`
  - goal MAE per team: `0.945`
  - W/D/L accuracy: `41.84%`
  - exact scoreline accuracy: `8.42%`
  - average predicted goals per team: `1.546`
- `offset=8.0`, `diff_boost=0.5`, `home_advantage=0.5`
  - goal MAE per team: `0.950`
  - W/D/L accuracy: `42.89%`
  - exact scoreline accuracy: `8.95%`
  - average predicted goals per team: `1.528`
- `offset=8.0`, `diff_boost=0.0`, `home_advantage=0.5`
  - goal MAE per team: `0.951`
  - W/D/L accuracy: `43.95%`
  - exact scoreline accuracy: `10.00%`
  - average predicted goals per team: `1.566`

Best W/D/L candidate found in this small grid:

- `offset=13.5`, `diff_boost=0.5`, `home_advantage=0.5`
  - W/D/L accuracy: `44.74%`
  - goal MAE per team: `1.411`
  - average predicted goals per team: `2.443`

Interpretation of goal calibration:

- A simple offset around `+8` makes standard Fantacalcio goal bands usable.
- Large offsets can marginally improve W/D/L but overproduce goals and are not acceptable.
- Differential amplification has limited benefit in the current formula; raw Vfoot score differences already carry most available signal.
- The model is directionally meaningful but not yet strongly predictive of real scorelines.
- Next improvement should target the underlying quality formula, not only the conversion layer.

Gradient-descent calibration command added:

- `vfoot/management/commands/calibrate_realdata_scoring.py`

Command:

```bash
cd vfoot-backend/src
../.venv/bin/python manage.py calibrate_realdata_scoring
```

It calibrates the score-to-goal conversion layer with:

- deterministic train/validation split by `match.id % 5`;
- soft differentiable goal conversion using sigmoid thresholds at `66, 72, 78, 84, 90, 96`;
- Adam optimizer with finite-difference gradients;
- optimized parameters:
  - `scale`
  - `offset`
  - `home_advantage`
  - `diff_boost`

Best run so far:

- output: `vfoot-backend/calibration/realdata_scoring_v1_conversion.json`
- parameters:
  - `scale`: `0.9763`
  - `offset`: `7.9830`
  - `home_advantage`: `0.7738`
  - `diff_boost`: `0.0`
- all-match metrics:
  - goal MAE per team: `0.863`
  - W/D/L accuracy: `36.32%`
  - exact scoreline accuracy: `9.21%`
  - predicted average goals per team: `1.222`
  - real average goals per team: `1.288`
- validation metrics:
  - goal MAE per team: `0.783`
  - W/D/L accuracy: `32.89%`
  - exact scoreline accuracy: `10.53%`
  - predicted average goals per team: `1.197`
  - real average goals per team: `1.243`

Interpretation of gradient run:

- Gradient descent found a cleaner conversion layer than the manual grid for goal volume and MAE.
- It consistently drives `diff_boost` to `0`, meaning post-hoc differential amplification does not help the differentiable objective.
- It improves goal calibration but does not improve W/D/L.
- Next calibration should therefore optimize the underlying feature weights used to produce raw Vfoot scores, with sign constraints and regularization toward the interpretable baseline.

Loss-function refinement:

- Added explicit differentiable sign loss to `calibrate_realdata_scoring`.
- First attempt used soft-goal differential; second attempt used adjusted-score differential directly.
- Tested `sign_weight=0.75`, `1.5`, and `3.0` variants.

Result:

- No improvement in hard W/D/L metrics.
- The optimizer still drives `diff_boost` to `0`.
- Best sign-loss variants remain close to:
  - `scale`: about `0.976`
  - `offset`: about `7.99`
  - `home_advantage`: about `0.77`
  - `diff_boost`: `0.0`
- Representative all-match metrics with adjusted-score sign loss:
  - `sign_weight=0.75`: goal MAE `0.861`, W/D/L `36.05%`, exact `8.95%`
  - `sign_weight=1.5`: goal MAE `0.866`, W/D/L `35.53%`, exact `8.42%`

Conclusion:

- The poorer W/D/L is not caused by an insufficiently expressive conversion layer.
- A conversion-only optimizer can calibrate average goal volume, but it cannot recover match-result fidelity if the raw team scores are not ranked well enough.
- Next step should move to M7 level 2: optimize the StatsBomb feature weights used in the raw scoring formula.
- This next optimizer should keep sign constraints:
  - positive features non-negative,
  - error features non-positive,
  - regularization toward current hand-authored weights,
  - fixed 10% duel modifier,
  - unchanged presence normalization and overcrowding.

Level 2 feature-weight calibration:

- Added command: `vfoot/management/commands/calibrate_realdata_feature_weights.py`
- The command optimizes grouped quality-feature multipliers instead of all individual StatsBomb weights at once.
- Feature groups:
  - `passing`: completed passes
  - `progression`: progressive passes/carries
  - `chance_creation`: key passes, passes into box
  - `shooting`: shots, xG, box touches
  - `duels`: duels won
  - `defending`: recoveries, interceptions, blocks, clearances
  - `pressure`: pressures
  - `errors`: bad passes, dispossessions, fouls, miscontrols
- Presence weights, overcrowding, and 10% duel modifier are unchanged.
- Uses SPSA gradient estimation by default, because standard finite differences were too slow for repeated full-engine evaluations.

Baseline before feature-weight calibration:

- goal MAE per team: `0.863`
- W/D/L accuracy: `36.32%`
- raw score sign accuracy: `42.89%`
- exact scoreline accuracy: `9.21%`

Best level 2 run so far:

- output: `vfoot-backend/calibration/realdata_scoring_v1_feature_groups_spsa_sign6.json`
- loss settings:
  - `sign_weight=6.0`
  - `diff_weight=1.0`
  - `regularization=0.02`
  - optimizer: `spsa`
- learned multipliers:
  - `passing`: `1.094`
  - `progression`: `1.163`
  - `chance_creation`: `1.072`
  - `shooting`: `1.279`
  - `duels`: `0.899`
  - `defending`: `1.185`
  - `pressure`: `1.108`
  - `errors`: `0.973`
  - `scale`: `0.970`
  - `offset`: `7.873`
  - `home_advantage`: `0.751`
- all-match metrics:
  - goal MAE per team: `0.859`
  - W/D/L accuracy: `38.42%`
  - raw score sign accuracy: `43.95%`
  - exact scoreline accuracy: `9.21%`
  - predicted average goals per team: `1.261`
  - real average goals per team: `1.288`
- validation metrics:
  - goal MAE per team: `0.763`
  - W/D/L accuracy: `34.21%`
  - raw score sign accuracy: `51.32%`
  - exact scoreline accuracy: `11.84%`

Interpretation of level 2 run:

- Feature-weight optimization improves all-match W/D/L modestly, from `36.32%` to `38.42%`.
- It does not yet beat the earlier manual hard-threshold W/D/L experiment.
- The validation raw-score sign accuracy reaching `51.32%` is promising: the raw score ranking can improve.
- The hard standard Fantacalcio goal bands still damage W/D/L after conversion, especially through threshold/tie effects.
- Further work should either:
  - optimize individual feature weights rather than grouped multipliers;
  - train directly against a hard-threshold-aware surrogate;
  - use cross-validation over several splits to avoid trusting one validation partition;
  - consider whether strict legacy goal bands are too coarse for judging model fidelity during calibration, even if retained for gameplay.

Soft-metric calibration policy:

- During calibration, use soft metrics as primary evaluation.
- Hard Fantacalcio goal bands should be treated as final gameplay diagnostics, not as the main training signal.
- Added soft metrics to both calibration commands:
  - `soft_goal_mae_per_team`
  - `soft_wdl_accuracy`
  - `soft_goal_diff_mae`
  - `soft_avg_pred_goals_per_team`

Best level 2 run re-evaluated with soft metrics:

- output: `vfoot-backend/calibration/realdata_scoring_v1_feature_groups_spsa_sign6_softmetrics.json`
- all-match soft metrics:
  - `soft_goal_mae_per_team`: `0.900`
  - `soft_wdl_accuracy`: `45.26%`
  - `soft_goal_diff_mae`: `1.289`
  - `soft_avg_pred_goals_per_team`: `1.293`
  - real average goals per team: `1.288`
- validation soft metrics:
  - `soft_goal_mae_per_team`: `0.814`
  - `soft_wdl_accuracy`: `48.68%`
  - `soft_goal_diff_mae`: `1.226`
  - `soft_avg_pred_goals_per_team`: `1.280`
  - real average goals per team: `1.243`

Soft baseline before level 2:

- all-match `soft_wdl_accuracy`: `44.47%`
- all-match `soft_goal_mae_per_team`: `0.900`
- all-match `soft_avg_pred_goals_per_team`: `1.266`

Soft interpretation:

- Grouped feature-weight calibration improves soft W/D/L only modestly: `44.47% -> 45.26%`.
- Soft goal volume is well calibrated after conversion: `1.293` vs real `1.288`.
- The current grouped model is therefore close on goal volume but still weak on match-result direction.
- Next meaningful attempt should optimize more granular feature weights and/or improve the real lineup/player selection proxy, because grouped multipliers alone do not extract a large signal.

Baseline sanity check:

- Real W/D/L distribution over 380 matches:
  - home win: `46.05%`
  - draw: `25.00%`
  - away win: `28.95%`
- Trivial majority baseline:
  - always predict home win: `46.05%`
- Simple feature-difference baselines:
  - `xg_shots` home vs away: `56.32%`
  - `xg_shots + home_advantage`: `57.89%`
  - `shots` home vs away: `47.11%`
  - `progressive_passes_completed` home vs away: `46.05%`
  - `key_passes` home vs away: `43.95%`
  - `touches` home vs away: `42.37%`
  - `touches_in_box` home vs away: `38.68%`

Interpretation:

- Current Vfoot soft W/D/L (`45.26%`) does not beat the trivial home-win baseline (`46.05%`).
- Simple team xG difference beats both by a large margin (`56.32%`, or `57.89%` with home advantage).
- Therefore the current Vfoot raw formula is diluting the strongest known signal, especially `xg_shots`.
- Next scoring iteration should explicitly anchor the model to team/player xG and chance quality before adding spatial/tactical modifiers.
- Treat `xg_shots + home_advantage` as the minimum baseline that Vfoot scoring must beat before considering the result model useful.

Vector-zone duel experiment:

- Added command: `vfoot/management/commands/calibrate_vector_zone_duel.py`
- This tests a richer zone comparison where each zone is represented by a home/away feature vector instead of one pre-aggregated scalar.
- Zone margin is currently:

```text
zone_margin = weight_vector dot (home_zone_vector - away_zone_vector)
match_margin = average(zone_margin over zones)
```

- Features used:
  - `xg_shots`
  - `shots`
  - `touches_in_box`
  - `key_passes`
  - `passes_into_box`
  - `progressive_passes_completed`
  - `progressive_carries`
  - `ball_recoveries`
  - `interceptions`
  - `pressures`
  - `clearances`
  - `errors_bad_passes`
  - `errors_dispossessed`
  - `errors_fouls_committed`
  - `errors_miscontrols`
- Uses `TeamZoneFeature` directly, max-normalizes each feature, and optimizes vector weights plus:
  - `base`
  - `score_scale`
  - `home_advantage`
- Output: `vfoot-backend/calibration/vector_zone_duel_v1.json`

Best vector-zone v1 run so far:

- Training command:

```bash
cd vfoot-backend/src
../.venv/bin/python manage.py calibrate_vector_zone_duel --epochs 400 --learning-rate 0.025 --regularization 0.03 --sign-weight 6.0 --diff-weight 1.0 --output calibration/vector_zone_duel_v1.json
```

- all-match metrics:
  - `soft_wdl_accuracy`: `56.32%`
  - `soft_goal_mae_per_team`: `0.860`
  - `soft_goal_diff_mae`: `1.171`
  - `soft_avg_pred_goals_per_team`: `1.324`
  - real average goals per team: `1.288`
- validation metrics:
  - `soft_wdl_accuracy`: `53.95%`
  - `soft_goal_mae_per_team`: `0.803`
  - `soft_goal_diff_mae`: `1.141`
  - `soft_avg_pred_goals_per_team`: `1.323`
  - real average goals per team: `1.243`

Learned weights:

- `xg_shots`: `1.496`
- `shots`: `0.625`
- `touches_in_box`: `0.158`
- `key_passes`: `0.873`
- `passes_into_box`: `0.000`
- `progressive_passes_completed`: `0.985`
- `progressive_carries`: `0.620`
- `ball_recoveries`: `0.000`
- `interceptions`: `0.753`
- `pressures`: `0.023`
- `clearances`: `1.011`
- `errors_bad_passes`: `-1.257`
- `errors_dispossessed`: `-0.646`
- `errors_fouls_committed`: `-0.401`
- `errors_miscontrols`: `-0.436`
- `base`: `70.995`
- `score_scale`: `9.678`
- `home_advantage`: `0.557`

Interpretation:

- The vector-zone model is a significant improvement over the current scalar Vfoot grouped model:
  - scalar/grouped soft W/D/L: `45.26%`
  - vector-zone soft W/D/L: `56.32%`
- It beats the trivial always-home baseline (`46.05%`) and matches the simple `xg_shots` difference baseline (`56.32%`).
- It does not yet beat `xg_shots + home_advantage` (`57.89%`).
- This suggests the vector idea has real potential, but the current linear implementation is still close to an xG-anchored baseline rather than clearly superior.
- The learned weights are mostly football-plausible:
  - strong positive weights for xG, shots, key passes, progression, interceptions;
  - negative weights for errors;
  - near-zero weights for pressure and some broad volume features.
- Items to inspect before treating this as production-calibration:
  - why `clearances` receives a large positive weight;
  - whether `passes_into_box` and `ball_recoveries` are redundant with other features or suppressed by normalization;
  - whether averaging zones underuses spatial structure;
  - whether attack-vs-defense interactions should be modeled explicitly instead of only `home - away`.

Retrospective vs predictive scoring split:

- There are now two conceptually different scoring problems.

Retrospective calibration:

- Goal: learn which event-derived zone features reproduce real match performance.
- Input: historical match events that already happened.
- Current best experiment: `vector_zone_duel_v1`.
- Data shape:

```text
real events -> TeamZoneFeature -> v_home(zone), v_away(zone)
```

- In this mode, substitutions and red cards are handled mostly implicitly:
  - a substitute only contributes events after entering;
  - a substituted player stops contributing events after leaving;
  - a red-carded player stops contributing future events;
  - the team effect of playing with fewer players is reflected indirectly in later event volumes.
- Therefore explicit player `effective_presence` is not necessary for this retrospective event-based calibration.
- The retrospective model should answer:

```text
Given the real event footprint of the two teams, which zones were won and how should that map to a plausible Vfoot score?
```

Predictive fantasy scoring:

- Goal: evaluate a fantasy lineup before future real events are known.
- Input: selected fantasy players plus historical/expected player tendencies.
- Required estimate:

```text
expected_player_vector(player, zone)
```

- This expected vector should combine:
  - spatial tendency: where the player usually acts;
  - event rates: what the player usually produces in those zones;
  - expected minutes / starting probability;
  - availability and risk factors;
  - later, opponent and tactical context.
- In this mode, an explicit effective-presence or expected-minutes factor is necessary because future event counts are unknown.
- The predictive model should answer:

```text
Given these selected fantasy players, what zone vectors do we expect them to generate, and which zones should the fantasy team win?
```

Architectural implication:

- Use retrospective calibration to learn the scoring function and feature weights.
- Use predictive player modeling to estimate the inputs to that scoring function for future fantasy lineups.
- Do not conflate the two:
  - retrospective scoring should stay event-based;
  - predictive fantasy scoring should estimate player-zone vectors before the match.

UI implication:

- Match review screen:
  - show observed zone vectors from real event data;
  - explain why each zone was won after the match.
- Lineup planning screen:
  - show predicted player/lineup zone vectors before the match;
  - expose uncertainty or expected minutes where relevant;
  - help managers understand tactical strengths/weaknesses before submitting the formation.

## Verification Notes

- Backend virtualenv was recreated on 2026-06-07.
- `../.venv/bin/python manage.py check` passes.
- All migrations are applied in the local SQLite database.
- Django runserver was verified on `localhost:8000` with `/admin/` returning HTTP 302.
- Frontend `npm run build` passes.
- `../.venv/bin/python manage.py test vfoot.tests_realdata_scoring` passes.
  - Two tests skip under the temporary test DB when no StatsBomb fixture data is loaded.
  - The zone mapping unit test runs normally.

## Data Quality Fixes

### StatsBomb Minutes Import

Fixed on 2026-06-07.

Problem:

- StatsBomb lineup positions use `to: null` to mean "until final whistle".
- The importer previously parsed `to=None` as minute `0`.
- This caused many full-match starters to be imported as `minutes_played = 0`.

Observed before fix:

- `MatchAppearance`: `16,750`
- `minutes_played = 0`: `11,827`
- starters with `minutes_played = 0`: `4,154`
- player-match rows with touches but zero minutes: `5,654`
- starter player-match rows with touches but zero minutes: `4,154`

Code fix:

- Updated `realdata/services/statsbomb_adapter.py`
- `_extract_minutes_and_starter` now treats `to=None` as final minute, default `90`.
- It also merges contiguous/tactical-shift intervals instead of relying only on min start / max end.

DB repair command added:

```bash
cd vfoot-backend/src
../.venv/bin/python manage.py update_statsbomb_minutes
```

Command result on local DB:

- scanned: `16,750`
- changed: `8,329`
- zero-to-nonzero: `5,639`
- missing matches: `0`
- missing appearances: `0`

Observed after fix:

- `minutes_played = 0`: `6,188`
- starters with `minutes_played = 0`: `0`
- player-match rows with touches but zero minutes: `24`
- starter player-match rows with touches but zero minutes: `0`
- average minutes: `44.93`
- max minutes: `94`

Impact:

- Current starter-like scoring metrics did not change materially because selection was already mostly driven by `is_starter`.
- The fix is still important for future weighting of substitutes, minutes-adjusted presence, lineup validation, and any calibration that uses playing time.

### Provider-Normalized Disciplinary Events

Added on 2026-06-07.

Problem:

- Discipline matters differently from ordinary event volume.
- A substitute with 20 played minutes and a starter sent off after 20 minutes should not be treated as equivalent at player-fantasy level.
- StatsBomb raw events contain cards, but the previous import only represented fouls as `errors_fouls_committed`.
- Cartellini were not available in the DB as explicit, queryable events.

Generic DB model added:

- `realdata.models.MatchDisciplinaryEvent`

Purpose:

- Store normalized disciplinary events independently of StatsBomb's raw JSON shape.
- Keep provider-specific identifiers and labels for traceability.
- Allow future adapters, such as Wyscout or SofaScore, to populate the same table.

Core fields:

- `match`
- `player`
- `team_season`
- `team_side`
- `period`
- `minute`
- `second`
- `elapsed_seconds`
- `card_type`
  - `yellow`
  - `second_yellow`
  - `red`
  - `unknown`
- `reason`
- `provider`
- `provider_event_id`
- `source_event_type`
- `source_card_name`
- `payload`

StatsBomb adapter behavior:

- Reads card information from:
  - `foul_committed.card`
  - `bad_behaviour.card`
- Normalizes:
  - `Yellow Card` -> `yellow`
  - `Second Yellow` -> `second_yellow`
  - `Red Card` -> `red`
- Preserves source event type and source card name.
- Full `import_statsbomb` now also populates `MatchDisciplinaryEvent`.

Dedicated backfill command added:

```bash
cd vfoot-backend/src
../.venv/bin/python manage.py import_statsbomb_disciplinary
```

This command imports only disciplinary events and does not regenerate zone features.

Local DB import result:

- matches scanned: `380`
- disciplinary events: `2,056`
- by normalized card type:
  - `yellow`: `1,928`
  - `second_yellow`: `80`
  - `red`: `48`

Scoring implication:

- Retrospective team-zone calibration can remain event-volume based.
- Player fantasy scoring should add a separate discipline/context layer later:

```text
player_score =
  event_based_zone_performance
  + discipline_modifier
  + minutes/context adjustment
```

- Red-card malus should likely be minute-dependent because the team damage depends on how long the team plays down a player.

### On-Pitch Intervals and Fantasy Substitution Semantics

Added on 2026-06-07.

Problem:

- For future fantasy scoring, aggregate `minutes_played` is not enough.
- We need to know exactly which time intervals a selected player was actually on the pitch.
- This is crucial because:
  - a player not starting can be covered by a bench player before he enters;
  - a player substituted off can be covered after he leaves;
  - a player sent off should not be covered after the red card;
  - event-based scoring should evaluate only the events that happen during the assigned player interval.

Generic DB model added:

- `realdata.models.PlayerOnPitchInterval`

Purpose:

- Store provider-normalized player participation windows.
- Make event-window scoring possible.
- Support future fantasy substitution logic without relying on provider-specific lineup JSON.

Core fields:

- `match`
- `player`
- `team_season`
- `team_side`
- `start_period`
- `start_minute`
- `start_second`
- `start_elapsed_seconds`
- `end_period`
- `end_minute`
- `end_second`
- `end_elapsed_seconds`
- `start_reason`
  - `starting_xi`
  - `substitution_on`
  - `tactical_shift`
  - `player_on`
  - `unknown_start`
- `end_reason`
  - `final_whistle`
  - `substitution_off`
  - `tactical_shift`
  - `red_card`
  - `player_off`
  - `unknown_end`
- `source_start_reason`
- `source_end_reason`
- `source_position`
- `provider`
- `provider_interval_id`
- `payload`

StatsBomb adapter behavior:

- Reads intervals from `lineups/*.json`, field `positions`.
- Preserves seconds, not only minutes:
  - e.g. `56:01`, `78:24`.
- Imports tactical-shift segments as separate intervals.
- Full `import_statsbomb` now also populates `PlayerOnPitchInterval`.

Dedicated backfill command added:

```bash
cd vfoot-backend/src
../.venv/bin/python manage.py import_statsbomb_intervals
```

This command imports only on-pitch intervals and does not regenerate zone features.

Local DB import result:

- matches scanned: `380`
- on-pitch intervals: `15,334`
- start reasons:
  - `starting_xi`: `8,360`
  - `tactical_shift`: `4,240`
  - `substitution_on`: `2,230`
  - `player_on`: `504`
- end reasons:
  - `final_whistle`: `8,368`
  - `tactical_shift`: `4,114`
  - `substitution_off`: `2,341`
  - `player_off`: `510`
  - `unknown_end`: `1`

Important note:

- StatsBomb lineup intervals in this dataset do not reliably encode red-card exits as `end_reason = red_card`.
- Red-card gaps should therefore be reconstructed by combining:
  - `PlayerOnPitchInterval`
  - `MatchDisciplinaryEvent(card_type in {red, second_yellow})`
- A player sent off at time `T` should be treated as unavailable and not fantasy-replaceable after `T`.

Target fantasy substitution rule:

```text
For each selected fantasy starter:
  1. Find real on-pitch intervals for that player.
  2. Score that player only on those intervals.
  3. Find gaps where the player is not on the pitch.
  4. If the gap is caused by non-disciplinary absence:
       attempt bench substitution according to the configured bench-search algorithm.
  5. If the gap is caused by red card / second yellow:
       leave the interval uncovered and apply disciplinary penalty.
```

Examples:

```text
Selected player starts and plays 0-60:
  selected player contributes 0-60
  bench may cover 60-90

Selected player does not start and enters at 70:
  bench may cover 0-70
  selected player contributes 70-90

Selected player is sent off at 20:
  selected player contributes 0-20
  20-90 is not coverable by bench
  red-card malus applies
```

Bench-search policy still to define:

- bench order;
- maximum fantasy substitutions;
- whether one bench player can cover multiple disjoint intervals;
- whether spatial compatibility replaces rigid positional-role compatibility;
- whether partial coverage is allowed if the bench player was also only on the pitch for part of the gap.

Proposed Vfoot-compatible direction:

- avoid rigid roles;
- use spatial/event compatibility instead:

```text
candidate_substitute is valid if their expected or observed zone vector can reasonably cover the missing interval.
```

- in retrospective tests, this can be based on actual interval-overlapping events;
- in predictive fantasy mode, this should be based on expected player-zone vectors and expected minutes.

Fantasy substitution control levels:

Two substitution-management modes should be supported conceptually.

Mode 1 - Automatic optimal bench search:

- Initial target for implementation.
- User selects starters and a bench list.
- The algorithm searches the bench for suitable replacements when a starter leaves a non-disciplinary gap.
- Bench order is not interpreted rigidly as the primary rule.
- The algorithm may use a heuristic score such as:

```text
candidate_score =
  interval_overlap
  + spatial/vector compatibility with missing starter
  + expected event contribution in uncovered zones
  - reuse/complexity penalties
```

- This mode is more flexible and better aligned with Vfoot's role-free philosophy.
- It also keeps the initial UI simpler:
  - pick starters;
  - pick bench;
  - let the engine optimize substitutions.

Mode 2 - Ordered bench with player-specific priorities:

- More advanced user-control mode.
- User still provides a generic ordered bench list.
- Default behavior:

```text
for each uncovered non-disciplinary gap:
  scan bench in user order
  pick first compatible substitute
```

- This is closer to standard Fantacalcio, but can be too rigid.
- Advanced extension:
  - users may attach specific preferred reserves to specific starters;
  - these player-specific reserves have priority over the generic bench order.

Example:

```text
Starter A:
  priority reserves: R1, R4

Starter B:
  priority reserves: R2

Generic bench:
  R3, R1, R2, R4, R5
```

Resolution order:

```text
if Starter A has a non-disciplinary gap:
  try R1, then R4
  if none works, fall back to generic bench order
```

Compatibility should remain Vfoot-style rather than classic rigid-role based:

- no mandatory `P/D/C/A` role lock in the new engine;
- use spatial/vector compatibility, expected zone coverage, and possibly hard goalkeeper special-casing if needed.

Implementation priority:

1. Implement Mode 1 first.
2. Use it to validate event-window scoring and bench coverage.
3. Later add Mode 2 as an advanced manager-control layer once the underlying substitution engine is stable.

Timeline consistency check:

- Added command:

```bash
cd vfoot-backend/src
../.venv/bin/python manage.py check_timeline_consistency
```

- Current DB result:
  - teams checked: `760`
  - invalid intervals: `0`
  - exact duplicate intervals: `0`
  - player interval overlaps: `0`
  - active-at-0 distribution: `{11: 760}`
  - max raw active players: `11`
  - raw over-11 timeline points: `0`
  - max discipline-adjusted active players: `11`
  - discipline-adjusted over-11 timeline points: `0`
  - red/second-yellow events checked: `128`
  - red events without raw interval drop: `0`
  - low active segments under 10 players for at least 60 seconds: `17`
    - these are explained by `red_count=2` in the benchmark examples, i.e. teams actually reduced to 9 players.

Interpretation:

- Initial raw `PlayerOnPitchInterval` import was not timeline-coherent.
- StatsBomb lineup `positions` can contain contradictory-looking combinations such as:
  - `Player Off`
  - `Player On`
  - `Substitution - On`
  at the same timestamp.
- Example:
  - match `3879863`, Udinese away;
  - Molla Wague has `Player Off`, then `Player On`;
  - Thomas Heurtaux also has `Substitution - On (Injury)` at the same timestamp;
  - naive interval counting temporarily yields 12 active players.
- Red-card exits are also not reliably encoded as interval endings in `positions`.
- Therefore the adapter now applies explicit event-derived exit constraints when materializing `PlayerOnPitchInterval`.

Implemented normalization:

- `lineups.positions` remains the base source for intervals.
- `events.Substitution` is treated as a hard cutoff for the outgoing player.
- `foul_committed.card` / `bad_behaviour.card` red or second yellow is treated as a hard cutoff for the sent-off player.
- Any interval starting at or after a player's hard cutoff is discarded.
- Any interval crossing a hard cutoff is truncated at the cutoff and marked with:
  - `end_reason = substitution_off`, or
  - `end_reason = red_card`.
- Regenerated local DB intervals:
  - before normalization: `15,334`
  - after substitution/red-card cutoff: `14,942`
  - after also using the real final match timestamp instead of fixed 90:00: `15,086`
  - intervals ending by red card: `126`

Additional consistency checks now included:

- no invalid intervals (`end <= start`);
- no exact duplicate intervals;
- no overlapping intervals for the same player;
- all 760 team-match timelines start with exactly 11 active players;
- no team ever exceeds 11 active players;
- no red/second-yellow event leaves the player active after the card;
- low active-count periods are explainable by multiple send-offs, not by timeline conflicts.

The normalized timeline now enforces:

```text
active_players(team, t) <= 11
red_card(player, t) => player inactive after t and not fantasy-replaceable
substitution_off(player, t) => player inactive after t and fantasy-replaceable if non-disciplinary
substitution_on(player, t) => replacement active after t
```

- This timeline is now reliable enough to be used as the base for event-window scoring and future fantasy bench-substitution logic.
- Remaining caveat:
  - `Player Off` / `Player On` injury-treatment intervals are preserved when they do not conflict with substitution/red-card hard cutoffs;
  - this is acceptable for active-player counting and event-window scoring, but if later we need exact temporary off-pitch treatment windows, they may need a separate availability layer.

## Immediate Next Steps

1. Add a calibration command/report for all 380 matches.
2. Decide the target score distribution and goal conversion behavior.
3. Wire `realdata_scoring_v1` into a backend endpoint behind a safe query flag or dedicated debug endpoint.
4. Replace synthetic match detail progressively once output stability is acceptable.
5. Add fixture-aware lineup selection using real fantasy rosters instead of starter-like real match appearances.

## Simulation UI Integration

Done on 2026-06-08.

Read-only API serving the dry-run artifact (no persistent-state mutation):

- `vfoot/services/simulation_report.py`
  - loads `calibration/historical_vfoot_league_dry_run.json`;
  - mtime-keyed `lru_cache`, so regenerating the report is picked up without
    a server restart;
  - assigns stable index-based `fixture_id`s and computes result/scoreline
    distributions and score range.
- `vfoot/api/simulation_views.py` (public read-only, `AllowAny`):
  - `GET /api/v1/simulations/historical-vfoot/latest`
  - `GET /api/v1/simulations/historical-vfoot/latest/fixtures`
  - `GET /api/v1/simulations/historical-vfoot/latest/fixtures/<id>`

Frontend `/simulation` section (consumes the API above, independent of the
mock/backend product switch since the artifact is always backend-served):

- `pages/SimulationOverviewPage.tsx`: config snapshot, full standings table,
  result distribution, top scorelines, score range, notes.
- `pages/SimulationMatchesPage.tsx`: per-round fixture browser with Vfoot
  score + goals and winner highlighting.
- `pages/SimulationMatchDetailPage.tsx`: zone-vector pitch grid (5x4) with
  per-zone feature-swing contributions, both lineups sorted by event score,
  and the temporal substitution report (covered / uncovered / red-card gaps).
- `api/simulation.ts`, `types/simulation.ts`, nav link + routes wired.

Verified in-browser with Playwright on desktop and mobile. Fixed a NaN
rendering bug on uncovered/disciplinary substitution rows (those entries omit
`bench`/`covered_seconds`; disciplinary gaps now render "espulso, intervallo
non copribile").

Next UI step: optionally let managers replay/adjust a simulated lineup, then
decide whether to materialize a simulation into the persistent league models.

### Match-detail redesign + shared scoring service (2026-06-08)

Shared math: `vfoot/services/vector_zone_scoring.py` is now the single source
of truth for the vector zone-duel. It returns the full explainable breakdown
(every zone's margin/winner/per-feature home-away swing) and exact per-player
per-zone contributions (the margin is linear in the feature vectors, so
attribution is exact). The simulate command uses it and stores, per fixture:
all 20 zones, score-build params, and home/away `player_totals`. Compact JSON
keeps the full season ~4MB. The future real-time match endpoint should call the
same service.

Two scoring layers were clarified for the UI:
- team score (and goals/standings) = `base ± scale · (boost · mean zone margin
  over all zones with presence)` — ALL zones contribute, not only the top few;
- the per-player `event_score` is only a selection heuristic (picks the XI),
  not a fantavoto and not additive to the team total. It is no longer shown.

Frontend match-detail rewrite (`SimulationMatchDetailPage`):
- friendly tactical zone names (0-based Z_col_row: col 0..4 defense→attack,
  row 0..3 flanks; orientation confirmed from xG/clearance distributions);
- full 20-zone pitch grid, click any zone → `ZoneInspector` graphical
  breakdown (per-feature home/away bars + swing, plus contributing players);
- `ScoreBuildExplainer` shows the formula with the actual numbers;
- `PlayerInfluence` replaces the vote list: most-influential players per team
  with their zone footprint (chips jump to the zone breakdown).
- predictive per-player numbers (where a player is expected to play / expected
  performance from recent history) are deferred to the future formation page.

## Full Historical Vfoot League Dry Run

Target scenario:

- Use the imported historical StatsBomb Serie A season as the real-data substrate.
- Simulate a complete Vfoot fantasy league with 10 managers.
- Managers start with a fixed auction budget.
- Players are assigned to fantasy squads through an initial auction/draft simulation.
- For each matchday:
  - managers submit lineups;
  - lineups are evaluated using real historical player event data;
  - non-disciplinary gaps may be covered by bench substitutions;
  - disciplinary gaps after red/second-yellow are not bench-coverable;
  - Vfoot scores are converted into fantasy match results;
  - league standings are updated.

Purpose:

- This is the first end-to-end platform rehearsal.
- It should test the full gameplay loop, not only the calibration model.
- It should expose whether the engine is:
  - playable over a whole season;
  - tactically meaningful;
  - robust to missing data, substitutions, red cards, and bench rules;
  - understandable enough to support frontend explanations later.

### Dry Run Step Plan

Step 1 - Historical player pool:

- Build a player pool from `MatchAppearance` and event-feature coverage.
- Compute basic eligibility metadata:
  - number of appearances;
  - starts;
  - minutes;
  - event coverage;
  - historical zone/vector profile.
- Avoid rigid classic roles in the new Vfoot engine.
- For auction heuristics only, derive soft player archetypes from spatial/event profiles if needed.

Step 2 - Auction / squad assignment:

- Simulate 10 fantasy managers.
- Give each manager an initial budget.
- Build squads through a first automatic auction heuristic.
- Initial implementation can be deterministic and reproducible:
  - rank players by historical value proxy;
  - distribute talent roughly evenly;
  - respect budget;
  - avoid all elite players concentrating in one fantasy team.
- Later versions can simulate real bidding behavior.

Step 3 - Fantasy fixture calendar:

- Generate a 10-team fantasy schedule.
- Decide whether to use:
  - one fantasy round per real Serie A matchday;
  - or a compact double round-robin schedule mapped onto historical matchdays.
- For first dry run:
  - use one fantasy round per real matchday where possible;
  - rotate pairings among 10 managers.

Step 4 - Lineup selection:

- For each manager and real matchday, select a starting lineup and bench from that manager's squad.
- Initial implementation can be automatic:
  - choose players with real data available in that matchday;
  - maximize expected/event-derived value;
  - maintain tactical diversity through zone coverage, not rigid roles.
- Later, frontend/user-submitted lineups replace the automatic selector.

Step 5 - Event-window scoring:

- Use `PlayerOnPitchInterval` to score only intervals where assigned players were actually on the pitch.
- For each selected starter:
  - use their event contribution during on-pitch intervals;
  - identify non-disciplinary missing intervals;
  - apply bench substitution mode 1 initially;
  - do not cover intervals after red/second-yellow.
- Aggregate player interval contributions into team-zone vectors.
- Feed those vectors into the calibrated Vfoot scoring function.

Step 6 - Bench substitution mode 1:

- Initial target:
  - automatic optimal bench search.
- For each uncovered non-disciplinary interval:
  - find candidate bench players with overlapping real on-pitch intervals;
  - estimate compatibility with missing zone coverage;
  - assign the best candidate subject to reuse limits.
- Keep this heuristic transparent and logged for debugging.

Step 7 - Match result conversion:

- Convert fantasy team Vfoot scores into goals.
- During calibration/testing, prefer soft metrics.
- For the season dry run, produce hard fantasy results:
  - win/draw/loss;
  - goals for/against;
  - standings points.

Step 8 - League standings and reports:

- Produce per-round and season outputs:
  - fantasy fixtures;
  - lineups;
  - substitutions applied;
  - uncovered disciplinary gaps;
  - Vfoot scores;
  - goals;
  - standings.
- Save outputs as JSON/CSV artifacts under `vfoot-backend/calibration/` or a future `simulation/` directory.

Step 9 - Validation questions:

- Does a full season run without data integrity failures?
- Are score distributions plausible?
- Do fantasy standings look non-random but not trivially determined by xG stars?
- Do bench substitutions behave sensibly?
- Are red cards handled as intended?
- Are explanations rich enough for future frontend views?

### Initial Implementation Target

Start with a backend management command:

```bash
cd vfoot-backend/src
../.venv/bin/python manage.py simulate_historical_vfoot_league
```

First version should:

- create an in-memory or artifact-only 10-manager league;
- generate deterministic squads from historical player value;
- generate automatic lineups;
- run a limited number of matchdays first, then the full season;
- write a JSON report;
- avoid mutating core fantasy app state until the simulation logic is stable.

Implemented scaffold:

- Added command:

```bash
cd vfoot-backend/src
../.venv/bin/python manage.py simulate_historical_vfoot_league
```

- Output:

```text
vfoot-backend/calibration/historical_vfoot_league_dry_run.json
```

- Current behavior:
  - artifact-only;
  - does not mutate `FantasyLeague`, `FantasyTeam`, roster, fixture, or lineup tables;
  - builds a historical player pool from `MatchAppearance` and `PlayerZoneFeature`;
  - simulates 10 managers;
  - assigns 25-player squads through deterministic snake allocation using historical value and budget prices;
  - generates 10-team round-robin pairings repeated over 38 real matchdays;
  - auto-selects 11 starters plus bench from players with event data in each real matchday;
  - computes a provisional event-score total;
  - converts scores to hard goals using Fantacalcio-style thresholds;
  - writes fixtures, lineups, scores, goals, and standings to JSON.

First full run:

- matchdays: `38`
- fixtures: `190`
- winner: `Manager 10`
- result distribution:
  - home wins: `36`
  - draws: `118`
  - away wins: `36`
- most common scorelines:
  - `3-3`: `111`
  - `3-2`: `29`
  - `2-3`: `28`
  - `2-2`: `7`
  - `3-4`: `6`
  - `4-3`: `6`
- score range:
  - min: `73.445`
  - avg: `79.961`
  - max: `86.510`
- all fixture lineups currently have 11 starters.

Current limitations:

- This is a scaffold, not the final Vfoot scoring engine.
- It now uses calibrated vector-zone scoring for fantasy fixtures.
- It now uses a first temporal substitution model based on `PlayerOnPitchInterval`.
- It still does not use raw event timestamps, because the DB currently stores `PlayerZoneFeature` as match-level aggregates.
- Legacy event scoring remains available with:

```bash
../.venv/bin/python manage.py simulate_historical_vfoot_league --scoring-mode event
```

- Event scoring uses a provisional linear event-value heuristic:

```text
score = score_base + score_scale * average_event_score
```

Vector scoring:

- Default mode:

```bash
../.venv/bin/python manage.py simulate_historical_vfoot_league --scoring-mode vector
```

- Builds per-lineup zone vectors by summing selected players' `PlayerZoneFeature` values in each real matchday.
- Compares home and away fantasy team vectors using:
  - `vfoot-backend/calibration/vector_zone_duel_v1.json`
  - calibrated feature scales;
  - calibrated feature weights;
  - calibrated `base` and `score_scale`.
- Fantasy fixture score:

```text
zone_margin = weight_vector dot (home_zone_vector - away_zone_vector)
match_margin = average(zone_margin over zones)
boosted_margin = fantasy_margin_boost * match_margin
home_score = base + fantasy_home_advantage + score_scale * boosted_margin
away_score = base - fantasy_home_advantage - score_scale * boosted_margin
```

- Current defaults:
  - `fantasy_home_advantage = 0`
  - `fantasy_margin_boost = 2`
- The margin boost does not change feature weights; it only makes fantasy fixture score differences less compressed for gameplay testing.

Updated full run with vector scoring:

- matchdays: `38`
- fixtures: `190`
- winner: `Manager 6`
- result distribution:
  - home wins: `59`
  - draws: `84`
  - away wins: `47`
- most common scorelines:
  - `1-1`: `84`
  - `2-1`: `58`
  - `1-2`: `47`
  - `2-0`: `1`
- score range:
  - min: `65.882`
  - avg: `70.995`
  - max: `76.108`

Next implementation step:

- Replace proportional feature scaling with true event-window scoring once raw event timestamps or time-bucketed features are imported.

Temporal substitution implementation:

- Added first Mode 1 implementation inside `simulate_historical_vfoot_league`.
- For every selected starter:
  - read their `PlayerOnPitchInterval` entries for the real matchday;
  - add their full match-level zone-vector contribution if they played;
  - compute missing intervals;
  - if the gap follows `end_reason = red_card`, leave it uncovered;
  - otherwise search the bench for the unused player with the largest overlap with that gap;
  - add the bench player's zone-vector contribution scaled by:

```text
covered_overlap_seconds / bench_player_active_seconds
```

- Important approximation:

```text
PlayerZoneFeature is currently match-level, not event-window-level.
```

- Therefore partial substitutions do not yet select only events that happened in the covered interval.
- Instead, the algorithm assumes the player's zone features are distributed across their active minutes and scales them proportionally.
- This is a reasonable bridge until raw timed events or time-bucketed zone features are imported.

Updated full run with vector scoring + temporal substitutions:

- matchdays: `38`
- fixtures: `190`
- winner: `Manager 6`
- result distribution:
  - home wins: `63`
  - draws: `81`
  - away wins: `46`
- most common scorelines:
  - `1-1`: `81`
  - `2-1`: `62`
  - `1-2`: `46`
  - `2-0`: `1`
- score range:
  - min: `65.918`
  - avg: `70.995`
  - max: `76.072`
- substitution diagnostics:
  - substitution/gap events logged: `835`
  - covered gap seconds: `694,525`
  - uncovered gap seconds: `60,361`
  - disciplinary gap seconds: `22,944`
  - average used bench players per fantasy team fixture: `2.095`

## Frontend Ideas Backlog

## Frontend Page Map for Historical League Simulation

Current reference artifact:

- `vfoot-backend/calibration/historical_vfoot_league_dry_run.json`
- Shape:
  - `config`
  - `teams`
  - `standings`
  - `fixtures`
  - `notes`
- Current content:
  - teams: `10`
  - fixtures: `190`
  - standings rows: `10`
  - fixture detail includes:
    - fantasy round / real matchday,
    - home/away scores and goals,
    - starters and bench,
    - temporal substitution report,
    - vector-zone report.

Important integration status:

- The historical Vfoot league simulation is currently an artifact-only dry run.
- It is not yet materialized into the persistent fantasy league tables.
- The frontend therefore cannot display it through the existing league, fixture, lineup, or match-detail APIs.
- Existing pages remain useful as UI targets, but a read-only simulation API/page layer is needed before the dry run can be browsed in the app.

Recommended first UI integration:

- Add a read-only simulation namespace instead of immediately mutating real league data.
- Suggested backend endpoints:
  - `GET /api/v1/simulations/historical-vfoot/latest`
  - `GET /api/v1/simulations/historical-vfoot/latest/fixtures`
  - `GET /api/v1/simulations/historical-vfoot/latest/fixtures/<fixture_id>`
- Suggested frontend routes:
  - `/simulation`
  - `/simulation/matches`
  - `/simulation/matches/:fixtureId`

Current page audit:

| Page | Current route | Intended role in dry-run UI | Current state |
| --- | --- | --- | --- |
| Landing / auth | `/` | Public access, login/register before entering app | Implemented; independent of simulation |
| Home dashboard | `/home` | Simulation snapshot: current round, standings leader, next fantasy fixture, warnings | Mostly static placeholders; not simulation-aware |
| League overview | `/league` | Managers, teams, standings, competition summary | Uses real backend league context; no dry-run standings |
| Standings | missing dedicated route | Full simulated table with points, W/D/L, GF/GA, average score | Missing; could live in `/simulation` first |
| Squad / roster | `/squad` | Team roster from simulated auction/allocation, player values, availability | Uses lineup context roster; no dry-run roster binding |
| Formation | `/squad/formation` | Manager lineup selection, bench, specific backup priorities, coverage preview | Implemented and already supports starter-specific backups; not wired to historical simulation outputs |
| Matches list | `/matches` | Fantasy fixture list by round, filtered by user team or all simulation fixtures | Uses persistent league fixtures; no dry-run artifact support |
| Match detail | `/matches/:matchId` | Core Vfoot explanation: final score, goals, zone-vector duel, decisive zones, substitutions, uncovered gaps | Good conceptual base; current contract differs from dry-run vector/substitution report |
| Competition calendar | `/competitions/:competitionId` | Round-by-round simulated league calendar | Uses persistent competition fixtures; no dry-run artifact support |
| Market | `/market` | Auction recap, player pool, budgets, unsold players, roster-building diagnostics | Currently mock/static |
| League admin | `/league-admin` | League setup, teams, competitions, matchdays, auction controls | Rich backend admin exists; separate from dry-run artifact |
| Simulation overview | missing | Read-only dry-run browser: config, teams, standings, distributions, diagnostics | Missing; recommended next page |
| Player detail | missing | Historical profile: vectors, availability, minutes, disciplinary events, price | Missing |

Near-term implementation plan:

1. Serve the dry-run JSON through a small authenticated read-only backend API.
2. Add `/simulation` to the app navigation as a development/testing surface.
3. Build simulation overview with standings, result distribution, scoreline distribution, config, and diagnostic totals.
4. Build simulation fixture detail by adapting the current `MatchDetailPage` layout to the dry-run fields:
   - score/goals,
   - starters/bench,
   - temporal substitutions,
   - uncovered vs disciplinary gaps,
   - vector-zone contributions.
5. Only after the UI/debug loop is useful, decide whether to materialize simulations into real league/competition models.

### Vector-Based Zone Duel Explainability

Potential future UX for a richer zone-duel model:

- Keep the main pitch grid simple:
  - zone color = winner (`home`, `away`, `draw`);
  - intensity = margin;
  - optional pattern/icon = dominant feature group.
- On zone click, show a feature-vector comparison panel:
  - home vs away bars for `xG`, shots, chance creation, progression, pressure, recoveries/interceptions, errors;
  - clear positive/negative contributions to the zone margin;
  - "why won" chips such as `xG +0.14`, `progression +3`, `errors forced +2`.
- Candidate backend contract extension:

```json
{
  "zone_id": "z0203",
  "winner": "home",
  "margin": 0.42,
  "feature_vectors": {
    "home": {"xg": 0.18, "shots": 2, "progression": 4, "pressure": 6, "recoveries": 3, "errors": 1},
    "away": {"xg": 0.04, "shots": 1, "progression": 2, "pressure": 8, "recoveries": 4, "errors": 3}
  },
  "feature_contributions": [
    {"key": "xg", "label": "xG", "swing": 0.31},
    {"key": "errors", "label": "Errors", "swing": 0.12},
    {"key": "pressure", "label": "Pressure", "swing": -0.08}
  ],
  "dominant_dimension": "xg"
}
```

This should wait until the backend vector-zone model proves useful in calibration.

---

# CONSOLIDATED STATE SNAPSHOT — 2026-06-08

This section is a self-contained handoff: where the project is, how it works,
how to run it, and what to do next. It supersedes the older sections above where
they conflict.

## One-paragraph summary

The historical Serie A StatsBomb season (380 matches) is loaded locally. There
is a **read-only simulated fantasy league** (10 managers, 38 matchdays) browsable
in the frontend under `/simulation`. The scoring engine is a **specular,
saturating, vector zone-duel**: for each pitch zone a team's attacking third is
compared with the opponent's defensive third (mirror), each zone produces a
*bounded* outcome (`K·tanh`), and the match score is the mean of those outcomes
mapped to a base±scale. This makes **player positioning tactically meaningful**
(contesting many zones and matching defenders to attackers beats stacking the
strongest players in one place). The match-detail UI explains all of this
spatially (pitch grid, click-a-zone breakdown, PES-style macro radar, per-player
zone footprints, role-free colour-coded lineup). Everything is committed on
`main` (not pushed); working tree clean except the untracked `screenshot/`.

## Scoring model (current, authoritative)

Single source of truth: `vfoot/services/vector_zone_scoring.py` →
`score_zone_duel(...)`. Used by the simulation and intended for the future
real-time match endpoint.

- Per-team, per-zone feature vector = sum of that team's players' StatsBomb
  features in the zone. Features normalized by fixed per-feature scales.
- **Specular mirror**: zone `(col,row)` of home is compared with away zone
  `(GRID_COLS-1-col, GRID_ROWS-1-row)` (grid 5×4). StatsBomb normalizes every
  team to attack toward the last column, so the two teams' frames differ by a
  180° rotation; the mirror makes the duel attack-vs-defense (verified: a team's
  left wing faces the opponent's right back). `mirror_zone()` lives in the
  service; the frontend mirror is `utils/zoneNames.mirrorZoneKey`.
- Per-zone raw margin: `Σ_f param_f · (home_f − away_f) / scale_f`.
- **Saturating aggregation** (this is what makes positioning matter):
  `zone_out = K · tanh(margin / K)`, `match_margin = mean_z(zone_out)`.
  `team_score = base ± home_adv ± score_scale · (boost · match_margin)`.
- Per-player attribution is exact (margin is linear in vectors):
  `contribution(player, zone) = Σ_f param_f · feature_f / scale_f`.

Calibration: `vfoot/management/commands/calibrate_vector_zone_duel.py` (SPSA +
Adam on the 380 matches, soft goal/sign loss, mirror + saturation baked in).
Output `calibration/vector_zone_duel_v1.json`, formula
`vector_zone_duel_v2_specular_saturating`. Current params:
`saturation_k≈0.72, base≈70.35, score_scale≈8.95, home_advantage≈0.54`,
weights e.g. `xg_shots 1.40, clearances 0.86, key_passes 0.86,
progressive_passes 0.68, progressive_carries 0.61, interceptions 0.47`, errors
negative. Metrics: all soft W/D/L **0.553** (val 0.526), goal MAE 0.860,
pred goals/team 1.21 vs real 1.29 — i.e. saturation+mirror cost ~nothing in
predictive accuracy vs the old linear 0.563 while restoring the tactical
property. Demonstration: same total xG, a *spread* lineup outscores a *stacked*
one.

Two scoring layers to keep distinct:
- Team score (and goals/standings) = the vector zone-duel above.
- Per-player `event_score` in the artifact is ONLY a selection heuristic; it is
  not a fantavoto and not additive. The UI does not show it.

## Simulation engine (artifact-only)

`vfoot/management/commands/simulate_historical_vfoot_league.py` →
`calibration/historical_vfoot_league_dry_run.json` (~5 MB, compact JSON,
deterministic, seed 42; regenerates in ~3 s). It does NOT mutate any persistent
fantasy tables.

- **Lineups (user-emulating heuristic)**: each manager's XI + bench is picked by
  **season value** with NO knowledge of who actually plays that round (managers
  can mis-pick). A picked starter who doesn't appear is `absent` and the engine
  tries to cover them from the bench. This removes the systematic upward bias of
  conditioning selection on same-match outcomes.
- **Substitute coverage (engine, "Mode 1")**: for each starter's on-pitch gaps,
  pick the best-overlapping unused bench player; bench contribution scaled by
  overlap. Gaps are classified by **exit category**, not duration:
  `pre_entry` (came on late), `post_exit` via `substitution_off`, disciplinary
  (red/second-yellow, not coverable), `absent` (never played). A player who
  steps off and returns (injury) is NOT a substitution and is ignored.
- Artifact per fixture stores: scores/goals, `home_lineup`/`away_lineup`
  (starters/bench, substitution_report), and `vector_report` = {total_margin,
  boosted_margin, score_build, zones[20] (margin/winner/macros/top features),
  home_player_totals/away_player_totals (per-zone contributions, own frame)}.

## Backend API (read-only simulation)

`vfoot/services/simulation_report.py` + `vfoot/api/simulation_views.py`
(AllowAny, mtime-cached). URLs in `vfoot/api/urls.py`:
- `GET /api/v1/simulations/historical-vfoot/latest` (config, teams, standings,
  distributions, notes)
- `GET .../latest/fixtures`
- `GET .../latest/fixtures/<int:id>`

## Frontend (`vfoot-frontend`, `/simulation` section)

- Pages: `SimulationOverviewPage` (standings + distributions + clickable team
  squads), `SimulationMatchesPage` (per-round), `SimulationMatchDetailPage`.
- API client `api/simulation.ts` (always hits the backend artifact, independent
  of the mock/backend switch). Types in `types/simulation.ts`.
- **Adapter seam** `api/simulationAdapters.ts`: maps `Sim*` shapes → neutral
  view-models. The future real league will write an analogous adapter to the
  SAME view-models, so components are reusable.
- **Neutral components** (data-source-agnostic):
  `components/league/StandingsTable`, `components/charts/Bars`,
  `components/match/{MatchScoreHeader, ZonePitchGrid, ZoneInspector, ZoneRadar,
  LineupBoard, ScoreBuildExplainer}`, `utils/{vfoot, zoneNames}`.
- Match-detail UX: score header; "Come nasce il punteggio" explainer (specular +
  saturating); full 5×4 pitch map (click any zone); ZoneInspector (PES macro
  radar Attacco/Creazione/Difesa/Recupero/Pulizia + percentage feature bars on
  hover + who acted here as %); role-free LineupBoard ordered by spatial
  tendency (avgCol) with DIF/CEN/ATT colour chips, click a player to light up
  their zones on the (mirrored-for-away) map, substitutions as inline
  expandables ("entrato al X'", "uscito al X'", "espulso", "non sceso in campo").

## How to run / verify

```bash
# backend
cd vfoot-backend/src && ../.venv/bin/python manage.py runserver localhost:8000 --noreload
# frontend
cd vfoot-frontend && npm run dev -- --host localhost --port 5173
# regenerate the simulation artifact (deterministic)
cd vfoot-backend/src && ../.venv/bin/python manage.py simulate_historical_vfoot_league
# re-calibrate the scoring model (writes calibration/vector_zone_duel_v1.json)
cd vfoot-backend/src && ../.venv/bin/python manage.py calibrate_vector_zone_duel --epochs 300
```

Browse: open `http://localhost:5173/?api=backend`, log in, then "Simulazione".
A dev test user exists: `simviewer` / `simpass123`. The `?api=backend` is needed
only on the first load (the provider is fixed for the SPA session). Playwright
(chromium installed) can drive the app headless: seed
`localStorage['vfoot_auth_token']` via `addInitScript`, load with `?api=backend`.

Verified this session: `manage.py check` clean; `manage.py test vfoot` passes
(2 skipped without StatsBomb fixtures in the test DB); `npm run build` passes;
pages render on desktop + mobile with no console errors.

## Open items / next steps (suggested order)

1. **Spatial balance in the lineup heuristic**: picking the top-11 by value with
   no roles sometimes fields two goalkeepers / leaves zones uncovered. Add a
   light balance (cover defense/midfield/attack bands, avoid extreme
   duplicates). The DIF/CEN/ATT colouring already exposes the problem.
2. **Predictive player model for the formation page** (the deferred numeric
   model): where a player is expected to play and expected performance from
   *recent* history (no leakage), used when a user submits a lineup.
3. **Materialize a simulation into the persistent league tables** (Phase 2):
   write a `FantasyLeague` + teams + competition + fixtures so the existing
   league/match pages can show it; have the real `/matches/<id>` endpoint emit
   the SAME `vector_report` shape via the shared `vector_zone_scoring` service.
4. Optional model tuning: nudge base so pred goals/team ≈ real (1.21→1.29);
   explore K and per-zone weighting; consider whether macro categories need
   refinement (touches_in_box already excluded as ambiguous).
5. Repo hygiene: the work is committed on `main` but NOT pushed; push when ready.

## Environment note

Image paste into the Claude Code terminal requires `xclip` (X11 session, no
clipboard tool was installed). `sudo apt install xclip` fixes it.
