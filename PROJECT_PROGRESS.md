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
  `zone_out = K · tanh(margin / K)`, `match_margin = WEIGHTED mean_z(zone_out)`
  where central width bands count `(1 + zone_center_weight)×` vs flanks
  (`zone_center_weight` calibrated, small ≈ 0.06 → ~6% heavier, intentionally
  modest). `team_score = base ± home_adv ± score_scale · (boost · match_margin)`.
- Per-player attribution is exact (margin is linear in vectors):
  `contribution(player, zone) = Σ_f param_f · feature_f / scale_f`.
- **Goalkeeper is scored separately, NOT in the zones.** The keeper is excluded
  from the team zone vectors; instead they get a "goals prevented" rating =
  xG faced (opponent real xG) − goals conceded (opponent real goals), and a good
  keeper REDUCES the opponent's score: `away_score -= w·home_gk` /
  `home_score -= w·away_gk` (w = `--gk-weight`, default 2.5; rating clamped ±2).
  Excluding the keeper from the zones is ≈ symmetric so the calibration (fit with
  keepers) is kept as-is. Surfaced in the UI: the POR row shows "gol evitati …"
  and the score explainer notes each keeper's effect on the opponent.

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
  - **Roles inferred spatially** (NOT from StatsBomb position labels): role
    GK/DEF/MID/ATT comes from the player's column centre of gravity + own-box
    touch share (`_role_from_footprint`; GK touch ~96% in their own box).
    Thresholds set from the data. Avg lineup ≈ 1 GK / 3.5 DEF / 3.6 MID / 2.9 ATT.
  - **Exactly one goalkeeper STARTS** (never two in the XI). The bench keeps a
    backup keeper, and a **goalkeeper may only be substituted by a goalkeeper**
    (and vice versa). The one-GK rule will gate user lineups later.
  - **Favours regulars**: selection weights value by season start rate and the
    pool `min_appearances` default is 15.
  - **Overcrowding-aware**: outfield slots filled greedily by value minus a
    penalty for crowding zones already covered (season touch footprint). No
    explicit "uncovered zone" reward — only the overcrowding disincentive.
- **Substitute coverage (engine)**: bench = the whole remaining squad (ordered
  reserves, not a fixed 7). For each starter gap the engine picks the reserve
  that most **improves the team** (calibration-weighted contribution × gap
  overlap), GK↔GK only. Uncovered gaps are now ~0.9% (was ~8%). Gaps are
  classified by **exit category**, not duration: `pre_entry` (came on late),
  `post_exit` via `substitution_off`, disciplinary (red/second-yellow, not
  coverable), `absent` (never played). A player who steps off and returns
  (injury) is NOT a substitution and is ignored.
- **Known limit**: the heuristic fields the SAME XI every matchday (no
  per-matchday adaptation, no hindsight), so ~9.7/11 of the picked XI actually
  play that round — real rotation. Closing this fully needs the per-matchday
  predictive model (next step #2).
- Artifact per fixture stores: scores/goals, `home_lineup`/`away_lineup`
  (starters/bench with `role`, substitution_report), and `vector_report` =
  {total_margin, boosted_margin, score_build, zones[20] (margin/winner/macros/
  top features + per-zone top-6 home/away players, specular), home_player_totals/
  away_player_totals}.

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
  saturating); full 5×4 pitch map (click any zone); ZoneInspector — headlined by
  a dominance tug-of-war bar + "X vince · margine N" (who won and by how much),
  then per-macro SIGNED contribution bars (Attacco/Creazione/Difesa/Recupero/
  Pulizia, home-left / away-right) that SUM to the margin — faithful, unlike an
  equal-axis volume radar (which was removed because it could contradict the
  winner); a collapsible "Dati reali per feature" (RAW event values home vs away,
  not duplicate percentage bars) and who-acted-here as %;
  LineupBoard where each row is a SLOT = starter +
  the substitute(s) who covered them: the role band (POR/DIF/CEN/ATT from the
  slot's dominant contributor) and ordering use the combined starter+subs
  footprint. The keeper (POR) is shown apart with "gol evitati …". Click a player
  to light up their zones on the (mirrored-for-away) map. Each outfield slot has
  ONE bar: THICKNESS = impact magnitude, horizontal SEGMENTS = minutes each
  occupant played (starter / substitute / uncovered), COLOUR = sign (green =
  helped, red = hurt, grey = uncovered) — so a relevant-but-negative player reads
  red. Substitutions are always shown inline: the slot line shows BOTH names
  ("Starter / Substitute", no hierarchy) + text ("entrato al X'", "uscito al X'",
  "espulso", "non sceso in campo").

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

## Materialized league (Phase 2 — DONE)

The dry-run simulation is now persisted as a real league the app manages through
its standard UI.

- DB backup taken first: `vfoot-backend/src/db_backup_<ts>.sqlite3` (gitignored).
- `FantasyFixtureDetail` (OneToOne→FantasyFixture, `vfoot_home/away`, JSON
  `payload`) stores each fixture's rich breakdown (same shape the simulation
  produces), migration `0008`.
- `python manage.py materialize_simulation` builds, from the artifact: a
  `FantasyLeague` (owner+admin = `simviewer`, who also manages **Manager 1**;
  the other 9 managers are generated `sim_manager_N` users), teams + full 25-man
  rosters, a round-robin `FantasyCompetition` (status done), 38 matchdays, 190
  finished fixtures (goals in `home_total/away_total`), per-team
  `FantasyLineupSubmission`s, and a `FantasyFixtureDetail` payload per fixture.
  Idempotent (replaces a prior run in PROTECT-FK dependency order). The
  `simulate_*` command now also emits full squads (`teams[].roster`).
- Endpoints: `GET /leagues/<id>/standings` (computed from fixtures, incl. avg
  Vfoot score) and `GET /fixtures/<id>` (the rich payload).
- Frontend: `LeaguePage` shows a Classifica table (reuses `StandingsTable`, own
  team highlighted); the rich view is the reusable `components/match/MatchDetail`
  used by BOTH the simulation page and `LeagueMatchDetailPage` (`/matches/:id` →
  `GET /fixtures/<id>`). Verified logged in as `simviewer`.
- NOTE: the run-server must be restarted after backend code changes
  (`--noreload`). The materialized league for the current DB is id 30.

## Page revision — real-data pass (DONE)

Audited every page (code + live as `simviewer`) and brought the rest onto real
data:
- **Squad + Formation**: now use the real team roster via a new shared service
  `vfoot/services/player_profiles.py` (footprint, spatially-inferred role,
  minutes from `MatchAppearance`) and endpoints `GET /leagues/<id>/lineup` +
  `POST /leagues/<id>/lineup/save` (SavedLineupSnapshot keyed per
  league+matchday+team). Formation is a real XI builder (GK + 10 via POR/XI/Panca,
  matchday selector, **live coverage heatmap from footprints**, save). Replaced
  the synthetic `data_builders` lineup for league play.
- **Home/Dashboard**: real rank/points, next-or-last fixture → rich detail,
  market status, season record (from standings + fixtures).
- **Market**: honest — real market status + roster value + link to the real
  auction in League Admin (removed the fake "Offri" stub).
- **Cleanup**: League Admin gated behind `selectedLeague.role === 'admin'`;
  competition-card link relabeled "Apri" (the unified calendar is `/matches`).
- Still synthetic-only: the old `lineup/context`/`data_builders` path (kept for
  mock mode). Predictive per-matchday model is the next enhancement on top of
  `player_profiles`.

## Open items / next steps (suggested order)

1. ~~Spatial balance in the lineup heuristic~~ — DONE: exactly one GK +
   overcrowding-aware outfield selection (see Simulation engine above). Possible
   refinement: tune the overcrowding weight, or extend the GK rule to a
   user-facing lineup validator in Phase 2.
2. ~~Predictive player model for the formation page~~ — FIRST VERSION DONE.
   The Formation page is an as-of, no-leakage mid-season view: choosing matchday
   N computes role/footprint/minutes from matches BEFORE N only, plus a
   recent-form "expected contribution" per player (calibration-weighted net value
   over the last ~6 matchdays; in `player_profiles.player_form`). It defaults to a
   mid-season matchday, shows the data cutoff, and offers a form-based "Suggerisci
   XI". The lineup is **referred to a competition** (SavedLineupSnapshot keyed per
   team+competition; matchdays from that competition's fixtures), with an "invia a
   tutte le competizioni" option; access is from the Calendar ("Imposta
   formazione" on your fixture) / Home, not the Squad page. GK rule: just
   Titolare/Panchina with exactly one goalkeeper among the 11 starters.
   Next refinements: position/availability prediction (not just descriptive
   form), opponent-aware expectation, expected coverage vs the opponent, and the
   competition-organisation rework (build competitions as sets of league fixtures
   mapped to real matchdays).
3. ~~Materialize a simulation into the persistent league tables~~ — DONE
   (Phase 2): see "Materialized league" below.
4. Optional model tuning: nudge base so pred goals/team ≈ real (1.21→1.29);
   explore K and per-zone weighting; consider whether macro categories need
   refinement (touches_in_box already excluded as ambiguous).
5. Repo hygiene: the work is committed on `main` but NOT pushed; push when ready.

## Environment note

Image paste into the Claude Code terminal requires `xclip` (X11 session, no
clipboard tool was installed). `sudo apt install xclip` fixes it.

---

# Multi-mode + live Serie A data — Aura & Classic (2026-06-16)

Pivot from the StatsBomb 2015/16 retrospective baseline to the just-concluded
**SofaScore 2025-26** season as the live substrate, and introduction of a second
game mode. This file remains the single progress/roadmap tracker (no separate
ROADMAP file). Security workflow: Claude writes code + runs OFFLINE imports from
cache (local); the USER runs network steps (scrape / install / live probe) via `!`.

## Roster sourcing & cross-provider identity (Transfermarkt ↔ SofaScore)

SofaScore has match data but not standalone squads → **Transfermarkt** is the
authoritative, transfer-fresh roster source, matched to SofaScore identities by
**name + date of birth**.

- `realdata/services/scrape_transfermarkt_squads.py` (USER-run, httpx+bs4, ~21
  reqs/league) → `historical-data/serie-a/transfermarkt/IT1/2025/club_*.json`.
- `realdata/services/identity.py`: `norm_name`, `name_similarity`, `is_placeholder_dob`.
- `manage.py import_transfermarkt_squads` (OFFLINE, idempotent, `--dry-run`):
  two-pass match (exact-DOB+name → exact-name → fuzzy≥0.85), writes
  `PlayerTeamStint` + `PlayerAlias(transfermarkt)`, fixes placeholder/wrong DOBs.
  Real run: 536 matched, 4 created, idempotent on re-run.
- SofaScore adapter `_adopt_by_identity` guard enforces "one player, many providers"
  (DOB-required) for the few TM-only newcomers; never touches DOB-less StatsBomb.
- StatsBomb DOB: verified ABSENT at source (open data) — unrecoverable.

## Market sync — stints open/close (live availability)

Roles are frozen (below) but the player POOL follows the real market.
**Availability = open `PlayerTeamStint` (end_date NULL)** on the season; helper
`vfoot/services/listone.py::eligible_player_ids(cs_id)`.

- The TM importer now CLOSES departures (sold abroad / out of every scraped squad):
  sets `end_date` (not delete — preserves history); a returning player reopens;
  intra-Serie-A moves close old-team + open new-team stint (still eligible).
- Guards: `--no-close-departures`, `--as-of ISO`, `--min-squad N` completeness
  guard (skip closing on a partial scrape). Verified self-healing.
- `Player.is_goalkeeper` = fixed tag from TM position == "Goalkeeper" (covers
  never-played keepers, e.g. Arthur Borghi). 68 tagged.

## Game modes (schema)

`FantasyLeague.mode` ∈ {**aura**, **classic**}, chosen at league creation
(default aura = existing zone behaviour). vfoot migration 0013.

- **aura** = the innovative zone-occupation/duel mode (all prior work).
- **classic** = traditional fantacalcio: role formations, score = Σ fantavoti =
  voto puro + bonus/malus. Field-occupation viz stays but decorative.

Roles:
- `Player.classic_role` (POR/DIF/CEN/ATT) + `role_source` = GLOBAL **seed** from
  TM position (wingers→CEN), realdata migration 0007. NOT what a league scores on.
- **`LeaguePlayerRole`** (league, player, role, source∈{seed,admin}; vfoot 0014) =
  per-league **FROZEN listone**. Fantacalcio fixes roles at season start; they must
  not drift when TM re-classifies. `snapshot_league_listone(league, reset=False)` +
  `manage.py freeze_league_listone`: ADDITIVE (new signings get a role; existing
  rows — seed AND admin — untouched, so a weekly TM re-import has ZERO impact on a
  started league). Verified end-to-end.
- Classic formation rules (confirmed): 1 POR, DIF≥3, ATT in [1,3], every role <6,
  11 total; non-eligible (departed) players = soft block.
- Departed-but-owned player: NO automation (stays in roster, not eligible);
  replacement is league-admin-driven (direct releases / market sessions).

## In-season schema (postponements / live / office votes)

- `Match.status` (scheduled/live/finished/postponed/cancelled) + `data_ready`
  (COMPLETE scoring data present AND stable) + `data_checked_at`. realdata 0006.
  Backfilled: all 760 existing 25-26 matches → finished/data_ready.
- `OfficeOverride` (vfoot 0012) — per-league "voto d'ufficio" with PRIORITY over
  real data; outfield = global-mean zone vector, GK = neutral goals-prevented.
- `probe_live_data.py` (USER-run, time-sensitive) measures SofaScore live + post-FT
  data stabilisation timing — needed before the schedule-refresh cadence. PENDING.

## Classic voto puro — heuristic from our own data

`vfoot/services/classic_rating.py` (+ cmds `classic_voto_distribution`,
`classic_calibrate`). User chose a heuristic over capturing SofaScore's `rating`.

Pipeline:
- **Two buckets**: IMPACT events counted as **totals** (`TOTAL_WEIGHTS`: xG, xGOT,
  xA, big_chance_created/missed, key_passes, shots, shots_on_target,
  errors_led_to_goal) — a decisive action's value doesn't scale with minutes, and
  this kills the per-90 cameo blow-up at its source; VOLUME/involvement **per-90**
  (`PER90_WEIGHTS`: touches, passes, duels, recoveries, dribbles, errors…), floored.
- `sqrt` tail compression; **z-score WITHIN role** (median 6 per role; pooled-std
  option balances the role mix in the top — recommended).
- **s.v. gate** (`is_rated`: minutes≥15 AND touches≥12 → else senza voto; 17.1%).
- **Bayesian shrinkage** for short games (`w=min/(min+SHRINKAGE_MINUTES)`) +
  `EXTRAP_FLOOR_MINUTES` (don't project a cameo's per-90 to 90').
- **Shooting semantics** (user insight: xG is chance quality, not the shooter's
  execution/merit): xG +0.5 (got into position) + **xGOT** +1.2 (execution) −
  big_chance_missed −0.8 (a squandered easy chance nets NEGATIVE); chance-creation
  credit goes to the CREATOR via xA, not double-counted on the shooter. No
  goal-paradox: shots/xG/xGOT include scoring shots (outcome-independent); only the
  discrete +3 goal goes to the bonus layer.

Data fix: `duels_won` was double-counting aerials (`duelWon`+`aerialWon`) → fixed to
`duelWon`. Feature set expanded with the 6 signals above + `expectedGoalsOnTarget`;
whole 25-26 season re-derived OFFLINE from cache (`import_sofascore --no-skip-existing
--delay 0`, deletes+rewrites per match). All shared in `PlayerZoneFeature` → these
also enrich the **Aura** zone duel (separate weight calibration, pending).

Calibration vs SofaScore `rating` (independent pro grade, read from cache):
correlation **0.439 → 0.513 → 0.530 → 0.593** across the refinements (xGOT was the
biggest jump). Outlier hunt is the calibration tool: "we rate BELOW" = goalscorers
(correct — bonus closes it); "we rate ABOVE" pointed to the missing
big_chance_missed/errorLeadToAGoal malus (now added). Distribution stays pagella-
shaped (median 6.0).

## Roadmap / next steps

1. **Finish voto-puro calibration**: lock `spread_k`, pooled-vs-per-role std,
   `SHRINKAGE_MINUTES`/`EXTRAP_FLOOR_MINUTES`, final weights — maximise rating
   correlation + minimise outliers.
2. **Bonus/malus layer**: goals/goalAssist (in cache!) + cards → fantavoto = voto
   puro + bonus/malus, per-league configurable; re-validate full fantavoto vs rating.
3. **Classic formation validator** (1 POR, DIF≥3, ATT 1-3, <6/role, 11; soft block
   for non-eligible).
4. **Textual voto-explanation generator** *(after the heuristic is calibrated)* —
   a short text justifying the voto the user reads, by reading the heuristic's
   feature contributions, e.g. *"7.5 — two big chances created + good recovery work;
   docked for one squandered clear chance."* Must explain both voto puro and the
   bonus/malus contribution; reusable in both match-detail views.
5. **UI**: mode picker at league creation; classic match-detail = fantavoti list
   (with the explanation); role-based formation page; admin listone-override editor.
6. **In-season**: apply OfficeOverride + data_ready in the scoring path; live/
   provisional estimate + schedule-refresh job (depends on the live-probe timing);
   per-league postponement policy (wait vs office votes).
7. **Aura**: fold the richer features (xGOT, xA, big chances, dribbles, decisive
   errors) into the zone-duel weights (separate calibration).

## External-vote benchmark (fantacalcio.it) — diagnostic, 2026-06-16

External data dropped in `data_fantacalcio/2025-2026/` (38 .xlsx, one per giornata;
sheets `Fantacalcio` editorial, `Statistico` algorithmic, `Italia` editorial). The
`Voto` column is the base pagella; bonus/malus (Gf, Ass, Amm, Esp…) are separate
columns — so it's a clean comparison vs our goal-independent voto puro. NOT a
calibration step (user: this need not change our heuristic).

Tool: `vfoot/management/commands/compare_external_votes.py --sheet <name>`. Matches
external (team + surname) → our players via open stints; ~7070 both-rated pairs.

Results (vs our voto puro; corr = Pearson):

| Source | std | corr vs ours | corr rating (all) | corr rating NON-scorers | goal-dep |
|---|---|---|---|---|---|
| Fantacalcio (editorial) | 0.61 | 0.443 | 0.654 | 0.546 | 0.52 (+1.16/gol) |
| Italia (editorial)      | 0.63 | 0.456 | 0.669 | 0.572 | 0.50 (+1.15/gol) |
| Statistico (algorithmic)| 0.66 | 0.476 | 0.693 | **0.609** | 0.49 (+1.18/gol) |
| **Ours (heuristic)**    | 0.60 | —    | 0.588 | 0.521 | **0.33** (+0.75/gol) |

`corr rating NON-scorers` (goal confound removed) is the fair performance test.
Findings:
- All sources are about equally FLAT (std ~0.60-0.66; ours 0.60) — flatness is
  intrinsic to a base pagella, not a defect unique to the site.
- The editorials' base vote is GOAL-INFLATED (+~1.15 per goal, corr ~0.50) — it
  double-counts the goal (in the base AND the +3 bonus). Ours is far more goal-
  independent (+0.75, corr 0.33), by design. This confirms the user's "too
  correlated with bonus" critique for the editorial votes.
- On pure performance (non-scorers) the editorials barely beat ours (0.55-0.57 vs
  0.521). The **Statistico** (their algorithmic vote, the true analog to ours) is
  the only one clearly ahead: 0.609 vs 0.521. Caveat: it likely shares Opta-like
  methodology with SofaScore's rating, inflating that correlation; our zone-derived
  pipeline is methodologically different.

Conclusion: our heuristic is well positioned — same granularity, cleanest voto-puro
/ bonus separation (no goal double-count), competitive performance tracking. The
~0.09 gap to the Statistico on non-scorers is the only headroom (likely qualitative
/ positional signals our features miss) — an optional future improvement, not
required. The `compare_external_votes` command is kept for re-runs.

---

## Weight-fit diagnostic — what's the ceiling our data can reach? (2026-06-17)

Follow-up to the external-vote benchmark. The benchmark compared our *hand-tuned*
voto puro to each provider; it could not separate "our DATA lacks the signal" from
"our WEIGHTS are suboptimal". This step does. Because our voto is LINEAR in its
feature weights (`index = Σ wₖ·compress(featureₖ)`, `vote = 6 + k·w·(index−mean)/std`),
"find the weights that best reproduce a target vote" is a closed-form RIDGE
regression of the SAME compressed feature basis (+ per-role intercepts) onto the
target. Its cross-validated correlation is the CEILING our features can reach for
that target; the baseline is our current model's correlation on the same sample.

Command: `python manage.py classic_fit_weights --target {rating|statistico|fantacalcio|italia} [--per-role]`
(5-fold CV, ridge α chosen by CV; intercepts unpenalised; standardized features).

| Target | our model (baseline) | optimal re-weight (CV) | gain | in-sample |
|---|---|---|---|---|
| **SofaScore rating** | 0.593 | **0.710** | +0.118 | 0.714 |
| Statistico (algorithmic) | 0.479 | 0.552 | +0.073 | 0.557 |
| Fantacalcio (editorial) | 0.445 | 0.542 | +0.097 | 0.546 |
| Italia (editorial) | 0.458 | 0.543 | +0.085 | 0.547 |

In-sample ≈ CV everywhere → negligible overfitting; the gaps are real signal.

**Reading (answers the two questions that motivated this):**
1. *Do we already have analogous data?* YES, asymmetrically. Against the **SofaScore
   rating** the ceiling is **0.71** — high, as expected: that rating is built from
   Opta-like event data, the same family we ingest from SofaScore, so we hold almost
   all of its signal. Against the **fantacalcio.it** sheets the ceiling caps at
   **~0.54 for ALL of them (even the algorithmic Statistico)** — a low ceiling that
   is NOT our fault: those votes carry subjective/contextual components absent from
   event data, partly irreproducible by anyone starting from Opta-like inputs.
2. *Are their weights different from ours, and is that OK?* There is a real
   +0.07…+0.12 gap on every target → we ARE leaving correlation on the table via
   hand-weighting. Robust fitted signals (vs rating): `xg_on_target` top (we already
   weight high ✓), then `duels_won`, `expected_assists`; and notably **`passes_completed`
   / `touches` (clean ball-circulation volume) get MUCH more weight than we give them
   (0.079 vs 0.02; 0.031 vs 0.01)** — our clearest under-weighting. Build-up features
   (`progressive_passes/carries`, `passes_into_box`, `pressures`) collapse to ~0 and a
   few shot features flip sign, but that is RIDGE COLLINEARITY splitting credit among
   correlated features (touches/passes absorb it), NOT evidence they're worthless —
   individual near-zero / sign-flipped coefs must not be over-read.

**Conclusion:** confirms the benchmark's verdict — no change to the heuristic is
*required*. But the diagnostic gives a concrete, low-risk lever if we later want to
tighten toward the rating: **raise the weight of ball-circulation volume
(passes_completed/touches)**, keep xGOT/duels/xA where they are. The ~0.71 wall on
the rating (and ~0.54 on the editorial/algorithmic sheets) is the information limit
of event data, not of our parametrisation. `classic_fit_weights` is kept for re-runs.

### Addendum (2026-06-17): two follow-up checks on the weight-fit diagnostic

**(a) Why is agreement with fantacalcio.it so low — is it the excluded goals/assists?**
Added `classic_fit_weights --with-bonus` (pulls goals/goalAssist from cache lineups,
adds them as 2 extra fit features). Ceiling jumps:

| target | no bonus | + goals/assists |
|---|---|---|
| Fantacalcio (editorial) | 0.542 | **0.662** |
| Statistico (algorithmic) | 0.552 | **0.663** |
| SofaScore rating | 0.710 | **0.798** |

For the editorial vote, `goals` (std-coef 0.310) and `assists` (0.143) are the TWO
LARGEST coefficients of all — above every performance feature. So most of the low
agreement with the fantacalcio.it base vote is exactly the goal/assist signal we
hold out of voto puro. This is BY DESIGN, not a loss: in real play the goal becomes
the +3 bonus ON TOP of the base, so our fantavoto = voto puro + bonus re-includes it.
`--with-bonus` is a proxy for the full fantavoto: once goals re-enter, agreement rises
to ~0.66 (their sheets) / ~0.80 (rating). Confirms the clean voto-puro/bonus split.

**(b) Is the SofaScore↔fantacalcio.it name match reliable, or are mismatches
inflating the disagreement?** Independent audit cross-checking the Ruolo (P/D/C/A)
declared in the sheet (a signal NOT used for matching):
- 73% of external rated rows matched 1:1; the 27% dropped is DROPPED (ambiguous
  surname or no-team), never mis-matched — it only lowers N. Matching is conservative
  by construction: any surname shared by 2+ players on a team is dropped (never a
  guessed pick).
- Among matches, role AGREES 93.1%. The 6.9% "disagreements" are NOT wrong identities
  — every case is a winger/wing-back where OUR "winger→CEN" convention differs from
  their P/D/C/A taxonomy (Bellanova, De Ketelaere, Kühn, Soulé, Berardi, Cuadrado…),
  same player correctly matched. Effective wrong-identity rate ≈ 0.
Conclusion: the gap to fantacalcio.it is NOT a matching artefact. It is (a) the
held-out goals/assists and (b) the intrinsic ceiling of those votes (~0.54 without
bonus for anyone starting from event data). The `rating` target is matched by EXACT
SofaScore id (no name ambiguity) and still has the highest ceiling, corroborating this.

---

## Live-data probe — first successful run (2026-06-17)

`probe_live_data.py` finally ran (the playwright block is resolved): captured a live
match (Iraq–Norway, World Cup) at 90s polls with `--post-final-minutes 120`,
`--headful --channel chrome`, logging to `live_probe.jsonl`.

**Confirmed (the win):** every input our `PlayerZoneFeature` pipeline needs is
available and moving in near-real-time DURING the match — `lineups_with_stats=52`
with `stats_items=21` (full per-player stats), `shots` 22→25 and `heatmap_points`
46→48 growing poll-by-poll. So a LIVE / provisional voto puro is feasible from the
same data we use offline. The `inprogress → finished` status transition is detected
cleanly. The probe records a `stable_s` dict (seconds-since-last-change PER feature)
— exactly the instrument to define `data_ready`.

**Proposed `data_ready` rule** (roadmap pt 6): `status == finished AND
min(stable_s over {shots, heatmap, stats, incidents}) ≥ threshold`, with the
threshold calibrated from the post-full-time stabilization window.

**Still missing:** the actual post-FT stabilization latency. This run ended ~on the
final whistle (only 1–2 polls past "finished"), so the 120-min post-final window
never really exercised — we don't yet know how many minutes after FT the shotmap/
heatmap/stats stop changing. Need one clean run that continues well past FT (ideally
attach to a match minutes from ending and let the post-final window run in full).
Serie A timings may differ but the SofaScore data shape is identical, so the
threshold generalizes.

**Gotcha:** `--log` APPENDS. The current file has a degenerate earlier capture
(shots=0/hm=0 throughout) concatenated before the valid Iraq–Norway run — use a
fresh log filename per run (`--log live_probe_$(date +%s).jsonl`).

---

## Classic formation page + order-aware bench substitution (2026-06-17)

Implemented the classic-mode formation page and the substitution semantics that make
the stored lineup ORDER meaningful.

### Backend
- **`vfoot/services/formation_rules.py`** (new) — single source of truth for the
  classic XI constraints: exactly 1 GK, DEF ≥ 3, ATT ∈ [1,3], strictly < 6 per role
  (max 5), 11 total. `validate_classic_lineup(starter_roles) -> [italian errors]`,
  `CLASSIC_CONSTRAINTS` dict mirrored to the client so page and server validate
  identically. Roles use the frontend taxonomy GK/DEF/MID/ATT.
- **`vfoot/services/lineup_substitution.py`** (new) — the algorithm that consumes the
  ordered bench:
  - `apply_classic_substitutions(starters, bench, roles, voted)`: for each s.v.
    starter, walk the bench in PRIORITY order and bring in the first player who has a
    vote AND keeps the formation legal (constraint-checked per swap); each bench player
    used once; leftover s.v. starters returned as `unresolved`.
  - `apply_aura_substitutions(starters, bench, voted, score)`: substitute = best
    available benched player by score; stored order only breaks ties.
  Both return the same `SubResult(effective, subs, unresolved)` so scoring is
  mode-agnostic. (Service is ready; wiring into the live scoring path is pending.)
- **`LeagueTeamLineupView`**: in classic mode the roster `role` now comes from the
  FROZEN listone (`LeaguePlayerRole`, fallback `Player.classic_role`, then spatial),
  not the spatial guess — classic pins roles at season start. Response `rules` now
  carries `mode` + `classic_constraints` (null in aura); top-level `mode` added.
- **`LeagueTeamLineupSaveView`**: server-side classic validation using frozen roles —
  an illegal XI is rejected 400 with `errors`, so a crafted request can't bypass the UI.

### Frontend (`FormationPage.tsx`, `types/lineup.ts`)
- Starters ordered by role **P, D, C, A**; mode badge (Classic/Aura).
- Classic: live constraint validation (mirror of the server validator) shown inline;
  **Save is blocked** until the XI is legal. Aura keeps the simple 1-GK rule.
- **Ordered bench = substitution priority**, always stored. New `benchOrder` state with
  ▲/▼ reorder controls and a visible priority index; toggling a player keeps the order
  in sync (demoted → lowest priority). The save sends `bench_player_ids` in that order.
  Mode-specific hint: classic = "first benched with a vote that keeps the XI legal";
  aura = "best available, order only breaks ties".

### Integrity test — full site (all green)
- Frontend `tsc -b && vite build`: **clean**, 75 modules, all 15 pages compile.
- Backend `manage.py check`: **0 issues**; full unit suite (`vfoot realdata players`):
  **17 passed** (2 skipped).
- New dedicated tests `vfoot/tests_formation.py`: **14 passed** (constraint matrix +
  classic substitution order/eligibility/uniqueness + aura best-score/tie-break).
- E2E `@mock` GUI smoke (via system Chrome channel, no backend): **passed** — landing →
  register → home → admin → create league → overview → roster → competitions → auction.

Page-by-page status (compile-verified + smoke where covered):

| Page | Status |
|---|---|
| Landing / register / Dashboard | ok (smoke) |
| League / Squad / Market | ok (compile) |
| **Squad ▸ Formation** | **updated** (classic rules + ordered bench); compile-verified |
| Matches / LeagueMatchDetail | ok (compile) |
| Competition / CompetitionCreate | ok (smoke: competitions tab) |
| LeagueAdmin | ok (smoke) |
| Simulation (overview/matches/detail) | ok (compile) |
| NotFound | ok |

### What still requires work
1. **Wire substitution into scoring** — `apply_classic/aura_substitutions` exist + are
   tested but are not yet called by the actual scoring path (the classic fantavoto =
   voto puro + bonus pipeline isn't built yet; see below).
2. **Classic scoring pipeline** — bonus/malus table (goals/goalAssist/cards from cache)
   → fantavoto = voto puro + bonus; then apply substitutions over the ordered bench;
   re-validate full fantavoto vs rating. (Roadmap pt 2.)
3. **Formation-page E2E** — the `@mock` provider stubs `getTeamLineup` (real backend
   only), so the formation page isn't covered by the headless smoke; the existing
   `@backend` suite doesn't visit it. Add a `@backend` spec that sets a classic XI,
   asserts the constraint block, reorders the bench, and saves. Needs the backend
   harness (skipped here to avoid mutating the dev DB overnight).
4. **Browser version** — Playwright wants chromium build 1208; installed are 1161/1223.
   Ran e2e via the system Chrome channel instead. A `playwright install` (network/user
   step) would let `npm run test:e2e:mock` run as-is.
5. Voto-explanation generator; in-season OfficeOverride/data_ready in scoring; live
   provisional estimate (pending the post-FT probe window — in progress).

### Live-probe — post-FT stabilization result (2026-06-17, Iraq–Norway)

The probe was left running. Result on the post-full-time window:

- **Continuous probing for ~28 min after FT.** The ONLY revision landed at **+3.0 min**
  past the final whistle: `shots` 25 → 24 (one shot reclassified). Everything else —
  heatmap (48), per-player stats (52 players × 21 items), incidents (20), goals (5) —
  was already frozen at FT and stayed put. So the scoring-relevant data settled within
  ~3 minutes; it was stable from +3m through +28m.
- Then a **single isolated poll ~7.4 h later** (the laptop SUSPENDED overnight — one
  441-min gap in the log, confirmed via rel-time + wall-clock `t`), which showed
  `heatmap_points` 48 → 50 (+2) with `shots` still 24. Isolated and post-suspend, so it
  cannot be cleanly distinguished from a snapshot artefact; a +2/48 heatmap drift is
  immaterial to zone distribution anyway.

**Conclusion / `data_ready` threshold.** For this match, definitive data was ready
within ~5 minutes of FT. A safe, simple rule:

    data_ready = (status == finished) AND
                 (min stable_s over {shots, heatmap, stats, incidents} ≥ ~10 min)

10–15 min of count-stability clears the only real revision (the +3m shots fix) with
margin; micro heatmap fill-ins beyond that don't move voto puro. Caveats: (1) single
match; (2) World Cup, not Serie A — Opta-heavy Serie A coverage may revise xG/rating
more and later, so re-confirm on a Serie A fixture; (3) the overnight machine-suspend
prevented a clean continuous 120-min window, so the slow-drift question (late xG/rating
passes) is NOT fully answered — a re-run on a machine that stays awake is the clean test.
Probe is no longer writing (process idle/dead after suspend); restart for the Serie A run.

---

## Classic demo league seeded for frontend testing (2026-06-17)

New command **`vfoot/management/commands/seed_classic_demo_league.py`** — builds a fully
browsable CLASSIC league from real 2025-26 Serie A data (idempotent by name+owner):
- 10 teams, REALISTIC rosters snake-drafted from the real pool (3 POR / 8 DIF / 8 CEN /
  6 ATT = 25 each), listone FROZEN (LeaguePlayerRole, 250 rows);
- round-robin Campionato: 10 teams → 9-round cycle × `--cycles` (default 4) = **36 fantasy
  rounds on real matchdays 1..36** (the last 2 of 38 skipped, as the user specified),
  5 fixtures/round → **180 fixtures**, home/away flipped each cycle;
- per team & matchday a VALID classic XI (1 POR, 3-4-3) + ordered bench, stored as both
  FantasyLineupSubmission (per fixture) and SavedLineupSnapshot (so the formation page
  shows them);
- each fixture scored with the REAL classic fantavoto (voto puro heuristic + goal/assist
  bonus from cache, ordered bench resolving s.v. starters), total → classic goals via the
  66/72/78… thresholds; minimal FantasyFixtureDetail payload (lineups + per-player
  fantavoti, EMPTY zone report) so the match-detail page renders without aura zone-duel.

Seeded league: **id 33** "Lega Classic Demo · Serie A 2025/26", owner **andrea**, comp id
83 "Campionato Classic", invite `m3xbyG5w`. Verified at the API level (force-authenticated
owner): LeagueFixturesView 200 / 180 fixtures with scores; LeagueStandingsView 200 (Demo
Team 3 leads 19-10-7); FixtureDetailView 200; LeagueTeamLineupView 200 mode=classic,
roster 25 with frozen roles, saved lineup present. All 90 sampled XIs legal 3-4-3.

**Bug fixed along the way:** `SavedLineupSnapshot.unique_together` was `(league_id,
matchday_id)` — it omitted `lineup_id`, so only ONE team per league could store a lineup
per matchday (every other team's save would hit the UNIQUE constraint). The whole app keys
saved lineups by `lineup_id` (team+competition). Fixed to `(league_id, matchday_id,
lineup_id)` (vfoot migration 0015). Surfaced precisely because the demo saves 10 teams ×
36 matchdays.

**Known limit (frontend):** the match-detail component (`MatchDetail.tsx`) is aura
zone-duel-only; classic has no dedicated fantavoto detail UI yet. The demo's detail payload
renders (header score + both lineups + per-player fantavoti) but with an EMPTY zone pitch.
A classic-native match-detail view is the remaining frontend piece. Fixtures list,
standings and the formation page are fully classic.

To view: log into the frontend as **andrea**, select "Lega Classic Demo", browse Partite /
Competizione / Classifica / Formazione. Re-point to another account with
`python manage.py seed_classic_demo_league --owner <username>`.

---

## Classic match-detail view + richer demo scoring (2026-06-17)

Addressing testing feedback on the classic demo league's match page (was showing the
AURA zone-duel text + an empty pitch, no fantavoto breakdown, no bench/subs):

- **`seed_classic_demo_league` reworked**: each team now fields a FIXED depth-chart XI
  (3-4-3 by season regularity), so on some matchdays a regular is s.v. and the ORDERED
  bench substitution fires — visible substitutions (1455 s.v. slots / 1393 subs across
  the 180 fixtures). The FantasyFixtureDetail payload is now classic-native (`mode:
  'classic'`): per player voto_puro, bonus (gol +3 / assist +1 / pen save +3), malus
  (autogol −2 / pen miss −3 / GK −1 per goal conceded), fantavoto, sv flag, and
  replaced_by / entered_for; plus the ordered bench and the substitution list. Bonus/
  malus read from cached lineups stats (no cards — they're in incidents, omitted for now).
- **Frontend classic detail**: `components/match/ClassicMatchDetail.tsx` + `types/classic.ts`.
  `LeagueMatchDetailPage` branches on `data.mode === 'classic'` → the fantavoto view
  (voto puro + bonus/malus = fantavoto per player, ordered bench with ▲ entered markers,
  substituted starters struck through). NO zone pitch in classic (per user: the empty
  field made no sense). Aura leagues still render the zone-duel `MatchDetail`.
  `getFixtureDetail` return type widened to `SimFixtureDetail | ClassicFixtureDetail`.
- **Bug fixed**: LeagueAdminPage kept a stale `selectedTeamId` when switching leagues →
  roster fetch 404 ("No FantasyTeam matches"). Now re-picks the first team when the
  selected one isn't in the loaded league, and the roster effect waits for the matching
  league detail.

Build clean (tsc + vite, 76 modules). Re-seeded league is now **id 34** (re-running the
command makes a new id; re-select it in the UI). Cards as malus, and a classic standings/
match list polish, remain as follow-ups.

---

## League max-substitutions option, cards ingestion, classic-detail polish (2026-06-17)

Three follow-ups from classic-detail testing:

1. **Max substitutions = league option** (admin-configurable, default 5).
   - `FantasyLeague.max_substitutions` PositiveSmallIntegerField default 5 (migration
     vfoot 0016). `apply_classic_substitutions(..., max_subs=None)` now caps the number
     of subs (remaining s.v. starters stay unresolved). New `LeagueSettingsUpdateView`
     PATCH `/leagues/<id>/settings` (admin-only, validates 0..11); `mode` +
     `max_substitutions` added to the league-detail response.
   - Frontend: `updateLeagueSettings` API fn + a "Sostituzioni massime per giornata"
     number input with Save in the LeagueAdmin overview panel. `LeagueDetail` type gains
     `mode` + `max_substitutions`.
   - The seed now scores with `league.max_substitutions`; verified the cap holds (max
     subs in any team-fixture = 5) and a unit test covers it (18 tests green).

2. **Cards ingested into the DB.** The SofaScore import only parsed lineups/stats — the
   per-match `*_incidents.json` (cards/goals/subs) were cached but NEVER ingested, so
   `MatchDisciplinaryEvent` had 0 rows for 2025-26 (the 2056 existing rows were 2015-16
   StatsBomb). New `realdata/management/commands/import_sofascore_incidents.py` reads the
   cached incidents (offline) → 1457 cards for cs=2 (1389 yellow / 45 red / 23 second
   yellow). The demo now applies them as malus (yellow −0.5, red/2nd-yellow −1) alongside
   own goal −2, pen miss −3, GK −1/goal conceded. (Goals/subs from incidents not yet
   ingested — only cards, which is what the malus needed.)

3. **Classic match-detail alignment**: each player row now reserves a fixed-height
   annotation line, so both teams' starter blocks are equal height and the two benches
   start at the same vertical position.

Re-seeded league is now **id 35** (re-running the seed makes a new id; re-select it).
Build clean (tsc+vite), `manage.py check` clean, 18 vfoot tests pass.

---

## Goals/assists in DB, defence modifier, event icons (2026-06-17)

1. **Goals & assists now persisted in the DB.** They were only ever read at runtime
   from the cached SofaScore lineups JSON (never stored). Added `MatchAppearance.goals`
   / `.assists` (realdata migration 0008), populated by the adapter for FUTURE scrapes,
   and backfilled offline for cs=2 via `backfill_appearance_goals` (900 goals / 612
   assists). Cards were ingested earlier into MatchDisciplinaryEvent (1457 rows). The
   demo now reads goals/assists from the DB; cards/own-goals/pens still complete the
   bonus/malus.

2. **Defence modifier (bonus difesa)** — league-configurable (admin):
   `FantasyLeague.defense_bonus_enabled` + `defense_bonus_mode` (add_own /
   subtract_opponent), migration vfoot 0017; exposed in league detail + the settings
   PATCH. Service `vfoot/services/defense_bonus.py`: gate = ≥4 defenders AT KICKOFF
   (not via subs); value = avg(top-3 defender voti puri + GK voto puro, excluding
   bonus/malus) → banded (≤6:+0, ≤6.25:+1, ≤6.5:+2, ≤6.75:+3, ≤7:+3.5, >7:+4); applied
   to own total or subtracted from the opponent's. 3 unit tests. Demo now fields a MIX
   of modules (several with 4-5 defenders) so the bonus actually triggers (243/360
   team-fixtures eligible, 141 with bonus>0).

3. **Match-detail icons**: goal ⚽ / assist 👟 / yellow 🟨 / red 🟥 / own-goal AG next to
   each player; a per-team "Modificatore difesa: media X → +N" line showing base→total.

4. **Admin UI**: the "Opzioni partita" panel now also has a Modificatore-difesa toggle +
   an apply-mode select; `updateLeagueSettings` generalised to a settings object.

Re-seeded league is now **id 37**. Build clean (tsc+vite), `check` clean, 21 vfoot tests.
Note for future SofaScore scrapes (user requirement): goals/assists are auto-persisted
by the adapter now; CARD ingestion still runs as the separate `import_sofascore_incidents`
step (folding it into the main import is a follow-up).

---

## Cards folded into the main SofaScore import (2026-06-17)

Per user request ("cards must never be a problem in future scrapes"): the SofaScore
adapter now ingests disciplinary events as part of every match import, so no separate
step is needed going forward.

- `SofaScoreClient` already had `incidents_records(match_id)` (cached `/incidents`).
- `sofascore_adapter._ingest_match` now fetches incidents and calls the new module
  helper `_ingest_cards(...)` → creates `MatchDisciplinaryEvent` rows (idempotent:
  drops this match's sofascore card events, then bulk-inserts). `incidentClass`
  yellow/red/yellowRed → CARD_YELLOW/RED/SECOND_YELLOW; player via `_player`,
  team_side via `isHome`, minute via `time`. `SofaIngestResult.cards` + the per-match
  and final logs report the count.
- Verified offline on a cached match (6 card events, idempotent). `manage.py check`
  clean, 21 tests pass.

The standalone `import_sofascore_incidents` command remains as a BACKFILL tool for
seasons imported before this change (it's how cs=2 cards were first loaded); new scrapes
no longer need it. (Goals/assists are likewise auto-persisted on MatchAppearance by the
adapter — the per-player scoring inputs are now all captured by the normal import.)

---

## Second competition (knockout cup) + multi-competition UX findings (2026-06-17)

Added a knockout **Coppa Classic** to the demo seed (`--no-cup` to skip): 8 teams,
single-elimination over the second half (Quarti md24 / Semifinali md30 / Finale md36),
winners advance by classic goals (ties → fantavoto total → home). 7 fixtures, scored
with the same classic engine. Re-seeded league is **id 38** with 2 competitions.

Purpose: stress-test the league-vs-competition structure. Findings (verified via the
real endpoints):
- **Per-competition view is correct.** `/competitions/{id}` (CompetitionPage) →
  `getLeagueFixtures(league, competitionId)` returns only that competition's fixtures
  (cup: 7, rounds 1-3). Good.
- **Lega-page "Classifica" is LEAGUE-AGGREGATE and wrong with >1 competition.**
  `LeagueStandingsView` ignores competition and sums ALL finished fixtures
  (`competition__league=league`) with the first competition's points. After the cup,
  Demo Team 8 shows G=39 (not 36) and jumps to #1 on cup wins — the knockout pollutes
  the championship table (and a knockout has no table at all).
- **"Sfoglia le partite" / Partite (MatchesPage) is a CROSS-competition calendar with
  no competition awareness.** `getLeagueFixtures(league)` (no competition) returns all
  187 fixtures merged and groups purely by `round_no`, so cup rounds 1-3 collide with
  championship rounds 1-3 under the same "Giornata", with no competition label/filter.

Recommendation (pending user decision): standings and the calendar are
COMPETITION-scoped, not league-scoped. Options: (a) make `LeagueStandingsView` accept a
`competition_id` (default first round-robin), and the Lega page show standings for a
selected competition (or only link to per-competition pages, hiding tables for
knockouts); (b) make MatchesPage competition-aware (a competition selector + group by
that competition's rounds + show the competition name). The cup match-detail already
shows its stage label ("Quarti di finale") via the new payload `stage` field.

---

## League ▸ Competition context: switcher + scoped pages (2026-06-17)

Implemented the chosen UX (competition switcher): the league level is a global hub;
standings/brackets are competition-scoped and follow a "current competition".

- **`CompetitionContext`** (mirrors LeagueContext): competitions of the active league +
  `selectedCompetitionId` (remembered per league), resets/defaults on league change.
  Mounted inside `LeagueProvider`.
- **`CompetitionSwitcher`** next to the LeagueSwitcher. Desktop top bar: both labelled
  ("Lega" / "Competizione"). **Mobile: a dedicated full-width, labelled context bar**
  under the header so the active league+competition are always obvious (was the user's
  complaint — the compact switcher was cramped/invisible on phones).
- **Partite (MatchesPage)** now competition-scoped: `getLeagueFixtures(league,
  competitionId)`, type badge, knockout rounds labelled by stage (round_label).
- **New Classifica page + menu item**: round-robin → standings table; knockout →
  3-column bracket (winners bold). Follows the switcher.
- **Lega page = hub**: removed the (league-aggregate, wrong) standings table; now shows
  a competition SUMMARY (type badge + progress + Apri) and clickable participants→roster.
- **Backend**: `LeagueStandingsView` accepts `competition_id`, defaults to the first
  round-robin (a knockout has no table). Verified: default championship standings G=36
  (was polluted to 39 by cup wins before); `getLeagueStandings(league, competitionId)`
  updated client+mock.

Build clean (tsc+vite, 79 modules), `manage.py check` clean, e2e @mock smoke passes.

## Dynamic results label (Classifica vs Tabellone) (2026-06-17)

The "results" menu entry / page title / page heading now adapt to the current
competition type: round-robin → "Classifica" (standings table), knockout →
"Tabellone" (bracket), driven by the competition switcher (AppShell derives the nav
label + title from `selectedCompetition`; ClassificaPage heading too). Build clean,
e2e @mock passes.

OPEN (proposed, not built): stage-aware competitions (e.g. group stage + knockout).
The backend already has CompetitionStage / CompetitionStageParticipant /
CompetitionStageRule + the competition_stages service. Plan: a competition is an
ordered list of STAGES, each with a kind (group round-robin → table(s); knockout →
bracket); the results page renders the stages in order with their native view; the
label is the decisive stage's (or a neutral "Risultati" for mixed). The demo cup is
currently a FLAT knockout (round_no 1-3, no CompetitionStage rows) — a group+KO demo
would need stages populated.

## Stage-aware competitions (group+KO) + scope color coding (2026-06-17)

Implemented option A (stage-aware results) + the league-vs-competition color code.

**Stage-aware results**
- Backend `CompetitionStructureView` (`/leagues/<id>/competitions/<cid>/structure`):
  returns an ordered list of SECTIONS — a standings table per round-robin stage, a
  bracket per knockout stage; a flat competition (no stages) yields one section from
  its own type. KO round labels derived from fixture count (Finale/Semifinali/Quarti/
  Ottavi). `_compute_standings` extracted as a shared helper. `_result_view(comp)` →
  'classifica' | 'tabellone' | 'risultati' (mixed stages), exposed on the competition
  serialization so the switcher/menu can label without fetching the structure.
- Seed: a 3rd demo competition **Coppa Gironi** — 2 round-robin groups (4 teams, md
  19-21) using real CompetitionStage + CompetitionStageParticipant rows, then a
  knockout stage (semifinali md28, finale md33) seeded by the group tables. `_play_fixture`
  helper (shared by both cups via `self._ctx`). League now has 3 competitions
  (Campionato → classifica, Coppa Classic → tabellone, Coppa Gironi → risultati).
- Frontend: the results page (ClassificaPage) now consumes the structure endpoint and
  renders sections — group tables side by side, then the bracket. The menu entry / title
  adapt: Classifica / Tabellone / Risultati (from `selectedCompetition.result_view`).

**Color code (league vs competition)**
- Competition-scoped pages (Partite, Risultati) get an INDIGO accent: nav items indigo
  (active = indigo-700), an indigo accent strip "🏆 Competizione · <name>" above the
  content, and the competition switcher styled indigo. League-generic pages stay neutral
  (slate). So at a glance you know whether you're in league-global or competition context.

Re-seeded league = **id 39** (3 competitions). Verified the structure endpoint for all
three types. Build clean (tsc+vite), check clean, 21 tests + e2e @mock pass.

---

## STATE / RESUME POINT (2026-06-17)

Where we are, to continue later.

**Demo league**: `seed_classic_demo_league` → "Lega Classic Demo · Serie A 2025/26",
currently **id 39**, owner **andrea** (manages Demo Team 1), cs=2 (Serie A 2025-26).
Re-running the seed tears down the same-name league and makes a NEW id — re-select it
in the UI. 10 teams, 3 competitions: **Campionato Classic** (round-robin, 180 fx →
Classifica), **Coppa Classic** (flat knockout, 7 fx → Tabellone), **Coppa Gironi**
(2 RR groups + KO via CompetitionStage, 15 fx → Risultati). Frontend: run backend on
:8000 and `VITE_API_PROVIDER=backend npm run dev`, log in as andrea.

**Classic mode — done & working** (all verified, build/check/tests green):
- voto puro heuristic (`classic_rating.py`) calibrated vs SofaScore rating / fantacalcio.it;
  weight-fit diagnostic showed ceiling ~0.71 (rating) / ~0.54 (sheets).
- fantavoto = voto puro + bonus/malus: goals/assists (now in DB on MatchAppearance),
  cards (MatchDisciplinaryEvent — ingested into the MAIN sofascore import going forward),
  own goals/penalties (cache). Defence modifier (league-configurable: enabled + add_own/
  subtract_opponent; ≥4 starting DEF gate; banded).
- ordered-bench substitution (max_substitutions league option, default 5).
- formation page (classic rules + ordered bench), classic match-detail (fantavoto
  breakdown + icons ⚽👟🟨🟥 + defence row, no zone pitch).
- League ▸ Competition UX: competition switcher (mobile context bar), per-competition
  ACCENT COLOUR (custom coloured dropdown + matching nav/strip), stage-aware Risultati
  page (table per RR stage, bracket per KO), dynamic label Classifica/Tabellone/Risultati.
  Lega page = global hub (no tables). Backend `CompetitionStructureView`.

**OPEN THREAD — roster / contracts (just discussed, NOTHING changed yet):**
- Current model IS contract-based: `FantasyRosterSlot(team, player, purchase_price,
  acquired_at, released_at)`; active roster = released_at NULL; release = soft-delete
  (history preserved in DB). Market = auctions (AuctionSession→Nomination→Bid); closing
  a nomination creates a slot with purchase_price = winning bid. Matches the user's
  original "contracts + history" design.
- GAPS identified (candidate next work): (a) transfer HISTORY exists in DB but is NOT
  surfaced anywhere — no view lists released slots; (b) NO budget (no budget field on
  team/session; buys don't deduct, releases don't refund, bids uncapped); (c) contracts
  not linked to a market session (no FK to AuctionSession; only timestamps).
- Two transfer layers: fantasy CONTRACT (FantasyRosterSlot = ownership) vs REAL transfer
  (PlayerTeamStint = real club → drives eligibility/listone). Departed-but-owned players
  stay owned (no automation; admin resolves via market) — by earlier decision.
- **Proposed next step (user leaning toward):** (a) expose the transfer history (per team
  + per league), reusing the data already stored. Then optionally (b) budget, (c)
  contract↔session link.

**RE-CHECK s.v. criterion (user memo 2026-06-17):** current gate is `is_rated =
minutes>=15 AND touches>=12` (classic_rating.py). The "4'" the user saw was just an
EXAMPLE below the 15' floor, NOT the threshold. User finds the hard AND too strict —
wants a BROADER time+events criterion (e.g. a voto if minutes>=15 OR enough involvement
/ a decisive event even with fewer minutes). To refine + recalibrate on the real distro.

**Other roadmap items still pending** (older): live provisional scoring + data_ready
threshold (needs a clean post-FT probe run, Serie A, machine awake); apply OfficeOverride
in the scoring path; voto-explanation generator; Aura: fold richer features into the
zone-duel; review/test the advanced competition-creation UI (it already supports stages).

---

## Phase 1 — match-centric ingestion pipeline (calendar sync + scheduler tick) (2026-07-20)

First slab of the "semiautomatic operation" work. Goal: make a real season's
match calendar and its lifecycle drive everything, so on the always-on Linode
server the data updates itself. Mode-INDEPENDENT (serves classic and aura).
Decisions captured in memory `live-finalization-pipeline`.

**Calendar source = SofaScore** (verified: it already publishes Serie A 2026/27,
season id **95836**, all 38 rounds, stable match ids + provisional kickoffs). Same
provider whose ids we scrape → no cross-provider fixture mapping. Probe:
`realdata/services/probe_next_season.py` (user-run, browser transport).

**Schema (realdata migrations 0009, 0010):**
- `CompetitionSeason.external_source/external_id` — holds the SofaScore season id,
  resolved ONCE by name (`get_valid_seasons`). Leagues point at this shared edition
  via the existing `FantasyLeague.reference_season`, so ingestion is per-real-season
  (dedup), not per-league.
- `Match.kickoff_provisional` — set while a whole round shares one placeholder
  timestamp; the scheduler must not open a live window on it.
- `Match.finished_at` — observed full-time; the +15min/+1h finalization is measured
  from this, not from an estimate.

**`realdata/services/calendar_sync.py`** (network-agnostic — takes a client):
- `resolve_competition_season(client, year_label, season_id=None)` → get/create the
  CompetitionSeason and stamp its season id.
- `sync_calendar(client, cs, season_id, rounds=None)` → upsert every fixture (status
  mapped SofaScore→Match lifecycle, provisional-kickoff detection), returns a diff
  report (created / kickoff-moved / status-flipped / postponed) so the scheduler can
  react. Idempotent.

**`realdata/services/match_scheduler.py`** — pure DB-driven policy (no I/O):
`plan_tick(now, matches)` classifies each match into stamp_ft / live_poll (confirmed
kickoff .. +135min, plus any status=live) / final_check (+15min) / final_confirm
(+1h → data_ready). No cron-per-match; robust to postponements (fires at the new time).

**Commands (portable; on Linode via systemd/cron):**
- `python manage.py sync_calendar --year 26/27 --browser` (daily; `--rounds 1,2` for a
  cheap frequent run; `--offline --season-id` for dev on the warm cache).
- `python manage.py tick` (every minute; `--dry-run`, `--now ISO` for testing). The
  state machine (stamp FT, +15/+1h finalization, data_ready) is REAL and applied; the
  per-match SCRAPE calls are stubbed hooks (`_scrape_live`/`_scrape_final`) to be wired
  in the next (ingestion) phase.

**Verified:**
- `sync_calendar --offline` on the warm 25-26 cache: 385 fixtures / 38 rounds, 380
  unchanged, and correctly CREATED the 5 postponed fixtures the finished-only import had
  skipped (marked `postponed`) — real postponement handling. Idempotent on re-run.
- `tick` on the real clock: 0 due (25-26 all data_ready). Lifecycle exercised by tests.
- New tests `realdata/tests_calendar_scheduler.py`: 16 (plan_tick matrix incl.
  provisional/live-window/finalization + FakeClient sync incl. provisional flag,
  idempotency, postponement detection + tick-command full lifecycle). Full backend
  suite: 37 passed (2 skipped), `manage.py check` clean.

**Next (Phase 2 — live in-progress):** wire the stubbed scrape hooks to the SofaScore
adapter (live provisional scrape sets status/goals/finished_at; final scrape computes
definitive votes); provisional-vs-final flag on the match-detail endpoint; frontend
distinguishes live/finished + page-open auto-refresh (polling). Then Phase 3 classic
finalization scoring + admin rectification override.

---

## Real reference-championship view in the league (Serie A calendar/results + pagelle) (2026-07-20)

Feature: from inside their league, the user can browse the REAL reference
championship (e.g. Serie A) — calendar + results, each played match clickable to
the vote-relevant per-player detail. Uses the Match rows the calendar-sync keeps
fresh. Mode-INDEPENDENT (every league gets it).

**Backend**
- `vfoot/services/classic_pagella.py` (new) — extracted the fantavoto assembly
  (previously cache-coupled + path-hardcoded inside `seed_classic_demo_league`)
  into a reusable, DB-only service. `pagella_for_match(match, reference)` → per-team
  ClassicTeamDetail-shaped lines: voto puro (`voto_puro_for_match`) + bonus
  (3·goals + assists) − malus (cards) for outfield, GK baseline − conceded − cards;
  `get_reference(cs_id)` lru-cached. Reusable by the future live classic scoring.
  Scope note: own-goal/pen-save/pen-miss not in the DB → default 0 (goals/assists/
  cards, the dominant terms, are complete).
- `LeagueRealFixturesView` (`GET /leagues/<id>/real-fixtures[?matchday=N]`) — real
  matches of `league.reference_season` grouped by matchday, with score/status/
  kickoff/provisional/has_detail + a `current_matchday` hint.
- `LeagueRealMatchDetailView` (`GET /leagues/<id>/real-matches/<mid>`) — the pagella
  shaped as a classic fixture (`mode:'classic'`), 404 when no appearances. Aura zone
  breakdown for real matches is a planned follow-up (kept the endpoint pagella-only
  for now — satisfies "informazioni rilevanti per i voti" for every league).

**Frontend**
- `types/realChampionship.ts`; `getRealFixtures` / `getRealMatchDetail` in
  api/backend.ts + mock stubs + api/index.ts wiring.
- `pages/RealChampionshipPage.tsx` — matchday selector, live/finished/scheduled/
  postponed states, played matches clickable.
- `pages/RealMatchDetailPage.tsx` — reuses `ClassicMatchDetail` (backTo `/serie-a`).
- Nav: new "Serie A" ⚽ item (scope `league`, neutral — it's real data, not a fantasy
  competition) + routes `serie-a` / `serie-a/:matchId` + page titles.

**Verified**
- New backend tests `vfoot/tests_real_championship.py` (4): GK malus / sv outfield /
  team total; fixtures grouping; classic-shape detail; 404 without appearances.
- Full backend suite: 41 passed (2 skipped), `check` clean. Frontend `tsc + vite`
  build clean (82 modules).
- Full URL-stack smoke on the demo league (id 39, Serie A 2025/26): real-fixtures 200
  (10 md1 fixtures), real-matches/381 200 (mode classic, 2-1, home_total 70.5, Simeone
  goal 6.5+3=9.5). To view: run backend, `VITE_API_PROVIDER=backend npm run dev`, log
  in as andrea, open the "Serie A" tab.

**Follow-up:** aura leagues → add the zone-duel breakdown to the real-match detail
(build ZoneVectors from the match's TeamZoneFeature + `score_zone_duel` → SimFixtureDetail,
render via the existing `MatchDetail`).

### Real-championship view — two fixes (2026-07-20)

1. **Postponed duplicates.** SofaScore represents a postponement as TWO events with
   different ids (the original → `postponed`, no score; the rescheduled replay →
   `finished`, with score); both are legitimately synced. `LeagueRealFixturesView` now
   HIDES a postponed row once a non-postponed sibling for the same leg
   (home_team_id, away_team_id) exists, so md16's 4 rescheduled fixtures show once (the
   played game). A genuinely postponed-and-not-yet-replayed match stays visible.
2. **Pagella order.** `classic_pagella._team_detail` now orders players by role
   (POR→DIF→CEN→ATT), fantavoto desc within a role, s.v. last — the standard pagella
   reading order (was fantavoto-desc overall, putting attackers on top). `ClassicMatchDetail`
   renders payload order, so this is a backend-only change.

Regression tests added (tests_real_championship now 7): starter role order,
superseded-postponed hidden, unreplayed-postponed visible.

## Status-aware match resolver (player+matchday -> real match + outcome) (2026-07-20)

`vfoot/services/match_resolver.py` — the robust bridge from a fantasy player to their
real-match outcome, that the Phase-3 live classic scoring will call. For fantasy round R
(= real matchday R of the reference season) it finds the ONE real match of the player's
club and returns a STATUS-AWARE outcome, distinguishing what a naive "(matchday,player_id)
vote lookup" conflates:

- `VOTO` — club match concluded (data_ready), player rated -> fantavoto;
- `SENZA_VOTO` — concluded, player not rated -> bench-substitutable;
- `PENDING` — club match NOT concluded (postponed/scheduled/live/finished-not-stable) ->
  no vote yet -> league POSTPONEMENT POLICY (wait or office vote), NOT a bench sub;
- `NO_MATCH` — club has no fixture this matchday, or player has no club.

Key properties:
- Club = player's current open `PlayerTeamStint` (correct for live/upcoming scoring;
  documented caveat for mid-season-transfer retrospective scoring).
- `authoritative_match` prefers the concluded (data_ready) row over the postponed shell,
  so the SofaScore postponed-DUPLICATE never shadows the played game — the earlier
  scoring-conflict worry, resolved in code.
- `resolve_matchday(cs, md, player_ids)` batches: one `pagella_for_match` per distinct
  concluded match.

Verified on real data (demo league, md16): AC Milan players (club had postponed shell id
870 + data_ready replay id 688) all resolve to the REPLAY (688) with voto/sv, never
pending; distribution over 300 rostered players = 137 voto / 163 sv / 0 pending / 0
no_match (season concluded). Tests `vfoot/tests_match_resolver.py` (8): no_match, pending
(scheduled/postponed/finished-not-ready), concluded voto/sv, postponed-duplicate prefers
replay, no-stint. Full backend suite: 52 passed (2 skipped).

This is the concrete `(player, matchday) -> match + outcome` resolver the user asked to
have in place; Phase-3 live scoring plugs its outcome (fantavoto for VOTO, bench search for
SENZA_VOTO, postponement policy for PENDING) into the league-result computation.

### Dynamic reference-championship label (drop the last Serie-A-only assumption) (2026-07-20)

The "Serie A" nav item + page title were hardcoded strings. Now they derive from the
league's reference competition: `LeagueListCreateView` returns `reference_season`
({id, name, competition, season}) on each list row (select_related, no N+1);
`LeagueSummary` type + mock updated; `AppShell` computes
`refCompetition = selectedLeague?.reference_season?.competition ?? 'Serie A'` and uses it
for the nav label and the page/detail title (same pattern as the dynamic standings label).
The page heading already came from `Competition.name` (year-independent) with the year on
the badge (`CompetitionSeason.name`). So a non-Serie-A reference season now labels itself
correctly everywhere; 'Serie A' remains only as the no-reference-season fallback.
Frontend build clean, backend 52 tests pass.

---

# PROGRAMMA PROSSIMI PASSI (autorevole, 2026-07-20)

Obiettivo: rendere una lega **Classic** operativa in modo **semiautomatico** su un
server Linode sempre acceso. La raccolta dati è indipendente dalla modalità (serve anche
ad Aura). Ordine guidato dal PERCORSO CRITICO; Aura predittiva/zone in parallelo o dopo.

## FATTO (fondamenta)
- **Pipeline dati Fase 1**: schema (CompetitionSeason.external_id, Match.kickoff_provisional
  /finished_at), `calendar_sync` (fonte = SofaScore, id match stabili; calendario 26/27 =
  season 95836 confermato disponibile), `tick` DB-driven (finestra live + finalizzazione
  +15min/+1h → data_ready; scrape STUBBED). `probe_next_season.py`.
- **Vista campionato reale in-lega**: calendario/risultati Serie A + pagelle per-partita
  cliccabili; `classic_pagella` (servizio riusabile), etichette competizione dinamiche.
- **`match_resolver`** (bridge scoring): `(giocatore, giornata) → match reale + esito`
  a stati VOTO / SENZA_VOTO / PENDING / NO_MATCH; preferisce data_ready al guscio rinviato.

## PERCORSO CRITICO → Classic semiautomatico

### Fase 2 — Ingestione live (collegare gli hook stubbed del `tick`)
1. Collegare `_scrape_live` all'adapter SofaScore: scrape provvisorio del match in corso →
   aggiorna `status`/gol, imposta `finished_at` al passaggio a finished.
2. Collegare `_scrape_final`: scrape completo (stats/incidents/heatmap) ai +15min/+1h →
   `data_ready`. Riusa `import_sofascore` adapter per singolo match.
3. Flag provvisorio/finale sugli endpoint (`real-fixtures`, `real-matches`, match-detail).
4. Frontend: distinguere in-corso/concluso + **auto-refresh a pagina aperta** (polling).
5. Deploy scheduler su Linode: systemd/cron (`sync_calendar` giornaliero + `tick` al minuto).
6. Migrazione **SQLite → Postgres** quando il live va in produzione (scritture frequenti).

### Fase 3 — Scoring live della lega Classic (calcolo risultati)
1. Percorso di scoring che, per ogni giornata fantasy, chiama `match_resolver` per giocatore
   e instrada l'esito: VOTO → fantavoto; SENZA_VOTO → ricerca panchina
   (`apply_classic_substitutions`, già scritta/testata ma non ancora chiamata); PENDING →
   policy postposte; NO_MATCH → nessun contributo.
2. **Policy postposte per lega** (attesa vs voto d'ufficio / `OfficeOverride`).
3. Finalizzazione giornata automatica → aggiornamento classifica.
4. **Pannello rettifiche admin**: override manuale su match già chiuso + ricalcolo giornata
   (per gol riassegnati ecc.).

### Fase 0 — Conferma soglia probe (opportunistica, NON bloccante)
- Run pulita della probe live su un match **Serie A** con macchina accesa per tarare la
  soglia `data_ready`. Si parte comunque coi default +15min/+1h.

## PRECONDIZIONE AVVIO STAGIONE
- Import anagrafico su 26/27 (season 95836): squadre + rose Transfermarkt + **listone
  congelato**, prima del via.
- Rendere `FantasyLeague.reference_season` **obbligatoria + immutabile** alla creazione
  (scelta per nome; oggi è null=True/SET_NULL — resta l'unico pezzo Fase-1 non fatto).

## PARALLELO / DOPO — Aura & rifiniture
- **Aura zone su match reale** (follow-up già individuato): ZoneVectors da `TeamZoneFeature`
  + `score_zone_duel` → `SimFixtureDetail` → componente `MatchDetail`, per il dettaglio
  partita reale nelle leghe aura (l'altra metà di "pagella + zone se aura").
- **Aura predittiva**: modello player-zona atteso (tendenza spaziale + rate + minuti) per
  numeri pre-partita nella pagina formazione.
- Feature ricche (xGOT, xA, big chances) nei pesi del duello aura.

## CROSS-CUTTING (quando comodo)
- Rose/contratti: esporre storico trasferimenti; budget (scala/rimborsa/tetto offerte);
  link contratto↔sessione asta.
- Generatore spiegazione testuale del voto.
- Ricalibrare il criterio s.v. (più largo: minuti≥15 OR coinvolgimento/evento decisivo).

## SINTESI PERCORSO CRITICO
Fase 2 → Fase 3 (+ precondizione avvio) = una lega Classic che gira da sola ogni giornata:
i dati entrano, i voti si calcolano e si confermano, l'admin interviene solo sulle
rettifiche. Fase 0 taratura in parallelo; Aura è l'elemento differenziante successivo.

## Kickoff reliability check vs Wikipedia + status-driven principle (2026-07-20)

First real ingestion of the 26/27 calendar (`sync_calendar --year 26/27 --browser`, 380
matches; fixed a Playwright-sync × Django-ORM async clash with DJANGO_ALLOW_ASYNC_UNSAFE
scoped to the browser path, and a package-vs-standalone import in sofascore_browser_client).

Validated stored kickoffs against the official Wikipedia schedule (giornate 1-4):
- Where SofaScore has CONFIRMED a time, it matches Wikipedia EXACTLY. Ingestion is faithful.
- Many times are still PLACEHOLDERS (13:00 UTC): 26/27 rounds 6-38 wholly, plus some
  matches inside partially-confirmed rounds 1-5 (round 1: Roma-Fio, Bologna-Lazio,
  Inter-Monza; round 2: 8/10). They firm up before match day.

No reliable per-match "confirmed" signal exists: SofaScore JSON is identical for
placeholder vs confirmed; the placeholder (15:00 CEST) coincides with real 15:00 slots;
and the confirmed 25-26 season has 8/38 rounds with ≥3 matches at 13:00 UTC (large
same-time clusters are normal). So `kickoff_provisional` honestly flags only FULLY-
unscheduled rounds, not partial placeholders — and any timestamp heuristic would
false-positive on real matches.

DESIGN CONSEQUENCE (Phase 2 requirement): correctness must NOT depend on kickoff accuracy.
(1) calendar-sync runs FREQUENTLY near match days (converges times, catches status flips);
(2) the tick's authoritative live trigger is `status=live` (set by the sync from
SofaScore's inprogress), not the stored kickoff — `plan_tick` already always polls
status=live, so a stale placeholder kickoff cannot miss a match. Stored kickoff = polling
optimization only. No code change needed now; this is baked into Phase 2 sync cadence.

### Nuovo requisito — lock formazione per orario d'inizio (emerso 2026-07-20)

Meccanica di gioco (NON ancora implementata): un manager può schierare solo giocatori la
cui partita reale NON è ancora iniziata al momento della consegna. Soluzione robusta con
doppio segnale: (a) kickoff confermato → conto alla rovescia "si blocca alle HH:MM" mostrato
all'utente (affidabile a ridosso del deadline, quando SofaScore ha consolidato l'orario);
(b) `status` reale → GATE RIGIDO: un giocatore con partita già live/finished è bloccato
comunque, a prescindere dall'orario salvato (safe by construction). Caso limite (match
ancora placeholder al deadline) → blocco conservativo al primo orario noto del turno; lo
stato lo chiude appena parte. Da collegare al lavoro formazione/scoring (Fase 2-3).

Chiarimento sul polling (correzione di una formulazione precedente): il kickoff confermato
È il trigger primario ed è affidabile vicino al match day (SofaScore consolida in anticipo);
lo `status=live` è la RETE DI SICUREZZA — il calendar-sync è 1 richiesta per giornata (=10
match), quindi girato spesso nella finestra-giorno del turno cattura il flip a inprogress
anche se un singolo orario fosse impreciso. I due si rinforzano.

### Correzione alla precondizione: import rose = sync RICORRENTE, non una tantum (2026-07-20)

Chiarimento su immutabile vs dinamico (4 concetti distinti da NON confondere):
1. associazione lega→campionato (`reference_season`) = IMMUTABILE una volta settata;
2. pool giocatori/eleggibilità (`PlayerTeamStint` aperti, `eligible_player_ids`) = DINAMICO,
   segue il mercato reale — l'import TM CHIUDE le partenze e APRE gli arrivi, così la lega
   resta fedele alla lista AGGIORNATA del suo campionato;
3. listone congelato (`LeaguePlayerRole`) congela solo il RUOLO (additivo: un nuovo arrivo
   riceve un ruolo; i ruoli non driftano), non il pool; un arrivo è usabile via fallback
   `Player.classic_role`;
4. proprietà fantasy (`FantasyRosterSlot`) persiste anche se il giocatore lascia il
   campionato reale (diventa non-schierabile; l'admin risolve via mercato — no automazione).
CONSEGUENZA: l'import anagrafico/rose TM è un SYNC RICORRENTE (schedulato, più fitto nelle
finestre di mercato), parte della pipeline di Fase 2 accanto al calendar-sync. La modifica
"reference_season immutabile" riguarda SOLO il concetto (1).

## Listone page — championship player pool with filters/value sort (2026-07-20)

New in-league page listing the full player pool of the reference championship.
- Backend `vfoot/services/player_ratings.py`: `season_player_ratings(cs_id)` (cached avg
  voto puro per player over finished matches) + `value_source_cs(reference_cs)` (uses the
  reference season if it has data, else the most recent prior edition of the same
  competition — so pre-season the value = last season's average). `LeagueChampionshipPlayersView`
  (GET /leagues/<id>/championship-players): pool = `eligible_player_ids(reference_season)`
  (open stints), each row = role (frozen LeaguePlayerRole → classic_role fallback), real
  club, ownership in THIS league (free vs owned+owner), value + appearances. Sorted by value.
- Frontend `pages/ListonePage.tsx`: role filter (POR/DIF/CEN/ATT), "solo svincolati" toggle,
  search (player/club), value↓/name sort; table with role chip, club, value, apps, status.
  api/type/mock wired; nav "Listone" 📋 (scope league) + route.
- Verified on demo league (cs=2): 536 players, 286 free / 250 owned, 446 valued; top by
  value Dimarco 7.03, Yıldız 6.84, N. Paz 6.67… Backend 52 tests pass, frontend build clean.
- NOTE (26/27): the pool is currently EMPTY (0 open stints) until the TM roster import runs;
  value falls back to 25-26 averages. GKs have no value (voto_puro is outfield-only) — v1 gap.

## Rose 26/27 importate + fix del matcher fuzzy DOB-aware (2026-07-20)

Import anagrafico rose Serie A 26/27 (cs id 3) da Transfermarkt (660 giocatori, 20 club;
scrape utente + `import_transfermarkt_squads --competition-season 3`). Risultato: 463
matchati a Player SofaScore esistenti (397 via alias, 65 DOB+nome), 197 nuovi creati,
660 stint aperti = il pool. Consistency 0. Il file scrapato era finito in `transfermarkt~`
(tilde di troppo nel --cache-dir): spostato in `transfermarkt/IT1/2026`.

**Bug corretto (identità)**: il Pass-3 fuzzy del matcher usava solo il nome (soglia 0.85)
IGNORANDO la data di nascita → fondeva giocatori diversi con nomi simili: "Di Renzo (2002)"
→ "Di Lorenzo (1993)" (corrompendo la DOB del capitano del Napoli), "Sebastian Esposito
(2005)" → "Sebastiano Esposito (2002)". Alzare `--name-threshold` peggiorava (è la soglia
del Pass-1 DOB: più alta → più giocatori scaricati sul fuzzy). Fix (principio confermato
dall'utente: soglia nome NON alta, la DOB dirime quando c'è): nel fuzzy si SCARTANO i
candidati con DOB nota e non-placeholder DIVERSA. Risultato: 0 fuzzy errati, Di Lorenzo/
Di Renzo ora Player separati con DOB corrette, i match legittimi di trascrizione (Nico/
Nicolás González) restano. 52 test verdi.

Pool 26/27 pronto per la pagina Listone (valore = media voto 25-26, sorgente cs=2). Manca
solo una LEGA su reference_season=cs3 per vederlo in UI (le demo sono su cs=2).

## (a) reference_season obbligatoria+immutabile · (b) lega demo 26/27 (2026-07-20)

**(a) Associazione lega→campionato blindata.** `CreateLeagueSerializer` richiede
`reference_season_id`; `LeagueListCreateView.post` la imposta alla creazione;
`LeagueReferenceSeasonView.patch` ora RIFIUTA ogni cambio quando già impostata (400,
messaggio esplicito), consente il no-op con la stessa stagione e l'assegnazione solo alle
leghe legacy che ne sono prive. Frontend: `CreateLeagueRequest += reference_season_id`,
form "Crea Lega" in LeagueAdminPage con select delle stagioni reali (`getRealSeasons`) +
nota che la scelta è definitiva. `CompetitionCreatePage` era già corretto (mostra il
selettore solo se la lega non ha stagione). Test `ReferenceSeasonImmutabilityTests` (3):
create senza stagione → 400, create con → 201, cambio → 400 (+ no-op stessa → 200).

**(b) Lega demo pre-stagione.** Nuovo comando `seed_preseason_league` — costruisce una lega
su un campionato NON ancora iniziato (a differenza di seed_classic_demo_league che punteggia
una stagione conclusa): rose snake-draftate dal pool eleggibile corrente ordinato per valore
(media voto dell'ultima stagione con dati), listone congelato, campionato round-robin con
calendario NON giocato. Eseguito su cs=3 → **lega id 42 "Lega Serie A 2026-2027"**, owner
andrea (Team 1), 10 squadre, 250 slot, listone 659 ruoli, 45 partite.

Verificato sulle due pagine reali per la lega 42: **Listone** 660 giocatori (410 svincolati /
250 posseduti, valori da 25-26, top Pavard 7.5 · Dimarco 7.03) e **Serie A** 38 giornate del
26/27 (g1: 10 partite `scheduled`). Suite backend 55 test, build frontend pulita.

## Valore di mercato come dato esterno + performance/valore progressivo (2026-07-21)

**Perf**: `season_player_ratings` riscritto in BULK — chiamava `voto_puro_for_match` per
partita e ogni chiamata rileggeva l'intera tabella Player 3 volte: **1901 query → 4**,
risultati identici. Cache **persistente su file** (`CACHES` filebased) con chiave
**versionata sui dati** (`n match finiti : ultimo data_checked_at`), quindi sopravvive ai
riavvii, è condivisa fra worker e si auto-invalida quando una giornata viene finalizzata.
Applicata anche a `get_reference`. Endpoint listone: 4.47s a ogni riavvio → **0.07s**.

**Valore progressivo** (richiesta utente): `valore = w·forma_corrente + (1−w)·stagione_prec`,
`w = n/(n+5)` sulle presenze a voto correnti. Pre-stagione = valore anno scorso; dopo 5
presenze 50/50; fine stagione ≈ forma corrente. Esordiente senza storico → `null` finché non
gioca. 7 test (`tests_player_values`) bloccano monotonia e pesi.

**Diagnosi dei 307 senza valore** (dubbio utente su identità mal riconosciute): NON è un
problema di matching. 72 PORTIERI (esclusi per design dal voto puro) + 54 che hanno giocato
ma mai raggiunto la soglia s.v. + 181 davvero nuovi, di cui 81 nelle 3 NEOPROMOSSE (Venezia/
Frosinone/Monza, non in Serie A 25-26) e 100 acquisti/giovani (TM elenca rose complete: 33
per club). Caccia ai duplicati: **1 solo su 660**, benigno (riga StatsBomb senza DOB, 0
presenze). Il fix DOB-aware non ha generato duplicati.

**Valore di mercato — modellato come dato da sorgente esterna** (requisito utente): nuovo
modello `realdata.PlayerMarketValue` (player, provider, provider_player_id, value_eur,
currency, raw_value, as_of; unique per player+provider+as_of) = serie storica provenienzata,
non un campo nudo su Player. Popolato dall'import TM (`_parse_market_value`: '€3.50m' →
3500000). 660 quotazioni, 658 con importo. Esposto nel Listone come COLONNA PROPRIA e chiave
di ordinamento SECONDARIA: il voto resta la chiave primaria, il mercato ordina la coda di chi
non ha ancora un voto (era alfabetica). Mai usato come sostituto di un voto.

### Portieri — indagine completata, implementazione da fare
I portieri non hanno voto perché `voto_puro_for_match` li esclude e **non ingeriamo NESSUNA
statistica da portiere**: `DISTRIBUTED_STAT_MAP` mappa solo stat da movimento. Verificato che
la cache grezza le contiene già: `goalsPrevented` (xGOT subiti − gol subiti, la metrica
chiave), `saves`, `savedShotsFromInsideTheBox`, `keeperSaveValue`, `goalkeeperValueNormalized`,
`penaltySave`/`penaltyFaced`, `goodHighClaim`, `punches`, `crossNotClaimed`,
`accurateKeeperSweeper`/`totalKeeperSweeper`, `errorLeadToAShot`.
PIANO: (1) estendere DISTRIBUTED_STAT_MAP con le feature GK; (2) ri-derivare la 25-26 OFFLINE
da cache (`import_sofascore --no-skip-existing`); (3) canale voto GK ancorato a goalsPrevented
+ volume/difficoltà parate + rigori parati + gioco aereo − errori, z-scorato DENTRO il ruolo.
Decisione utente: una media portieri più bassa NON è un problema (il filtro per ruolo esiste
apposta), quindi niente forzature di scala; e per i portieri NON si usa il valore TM.

## Voto portieri — canale GK dedicato, calibrato vs rating SofaScore (2026-07-21)

I portieri non avevano voto perché (a) `voto_puro_for_match` li escludeva e (b) NON
ingerivamo alcuna statistica da portiere. Risolto end-to-end.

**Ingestione**: `DISTRIBUTED_STAT_MAP` estesa con `gk_saves`, `gk_saves_inside_box`,
`gk_penalty_saves`, `gk_high_claims`, `gk_punches`, `gk_crosses_not_claimed`,
`gk_sweeper` + `errors_led_to_shot`. Nuova `SIGNED_DISTRIBUTED_STAT_MAP` per
`gk_goals_prevented` (xGOT affrontati − gol subiti): il filtro `if tot <= 0` avrebbe
scartato i valori NEGATIVI, cioè proprio le partite in cui il portiere fa peggio
dell'atteso. Stagione 25-26 ri-derivata OFFLINE da cache (380 match, 1.263.313 feature).

**Modello**: `GK_TOTAL_WEIGHTS`/`GK_PER90_WEIGHTS` ancorati a `gk_goals_prevented` (2.5),
volume parate secondario (quelle in area pesano più del totale: tante parate possono
significare solo difesa scadente). `_compress_signed` (sqrt col segno) perché lo sqrt
normale azzerava i negativi. `index_for_role` smista GK/movimento; i portieri entrano in
`build_reference` e `voto_puro_for_match` con un PROPRIO bucket di ruolo → z-score dentro
il ruolo, scala auto-calibrata. Pagella: niente più 6.0 d'ufficio, il malus −1/gol resta
nel layer bonus (nessun doppio conteggio: il voto misura contro l'xG on target, il malus
conta i gol grezzi). Rimosso anche lo skip GK in `_compute_season_player_ratings`.

**DUE BUG trovati calibrando** (la verifica ha pagato):
1. `_per_match_player_totals` filtrava `feature_key__in=WEIGHTS` (solo movimento) →
   l'indice GK non vedeva NESSUNA feature da portiere ed era guidato dai soli lanci lunghi
   sbagliati: ordine perfettamente invertito (Suzuki rating 9.4 → indice peggiore; Sommer
   5.5 → migliore), corr **0.161**. Fix: fetch sull'unione WEIGHTS ∪ GK_WEIGHTS.
2. Il monitor di attesa dell'import usava `pgrep -f "manage.py import_sofascore"`, che
   matchava la command-line del ciclo stesso → attesa infinita e falso "import in corso".

**Calibrazione finale vs rating SofaScore** (761 valutazioni GK):
- corr **0.161 → 0.783**, PIÙ ALTA dei movimenti (~0.6): la prestazione di un portiere è
  più monodimensionale e goals_prevented la misura direttamente.
- distribuzione sana: 4.0–7.5, campana centrata su 6.0 (era 535/761 piatti a 6.0).
- nessuna regressione: complessivo 0.593 → **0.609**; DIF 0.527, CEN 0.645, ATT 0.628.
- Listone: 33/72 portieri ora hanno un valore (Provedel, Maignan, Carnesecchi, Svilar in
  testa); senza valore 307 → 274. Media valore movimento 5.98 vs portieri 6.01 (lo
  z-score per ruolo la rende neutra; una media più bassa sarebbe stata comunque accettabile).
- Caveat noto: pochi portieri di riserva con 1-2 presenze hanno valori alti (varianza da
  piccolo campione) — la colonna Presenze permette di valutarlo; vale anche per i movimenti.
Test: 63 verdi (aggiornato il test pagella GK: senza dati un portiere è ora s.v., non 6.0).

## Listone unico: valore omogeneo stimato per tutti (2026-07-21)

Richiesta utente: un parametro OMOGENEO per ogni giocatore, così il listone è una lista
unica invece di relegare gli esordienti in coda; mantenendo l'ordinamento precedente come
opzione.

- `fit_value_from_market(values, market)`: regressione ai minimi quadrati del voto misurato
  su `log10(valore di mercato)`, tarata SOLO sui giocatori che hanno ENTRAMBI i segnali.
  Sui dati reali: `voto ≈ 4.139 + 0.268·log10(mv)`, **r = 0.485 su n=386** — relazione reale,
  non una scala inventata. Sotto 30 sovrapposizioni non stima nulla (niente fit azzardati).
- `player_values(cs, market)` ora restituisce per ogni giocatore `value` (MISURATO, None se
  mai valutato) + `estimated_value` (OMOGENEO: il voto misurato, altrimenti quello stimato)
  + `basis` ∈ corrente|precedente|misto|**stimato**, e il fit stesso.
- Le stime sono clampate in [5.0, 6.6]: una valutazione di mercato è evidenza molto più
  debole di una prestazione misurata e non deve mai scavalcare i top reali.
- Ordinamento di default = valore omogeneo. Frontend: 4 modalità — **Valore** (unico),
  **Voto reale** (misurato poi mercato, il comportamento precedente), **Mercato**, **Nome**.
  Le stime sono rese in corsivo con prefisso `~` e un badge dichiara la qualità del fit (r).

Effetto: senza valore 307 → **2**. Gli esordienti si inseriscono dove meritano invece che in
fondo — Stanković (32M) 86°, Gonçalo Ramos (30M) 92°, Douglas Luiz (18M) 118° — mentre in
testa restano i voti misurati (Pavard 7.5, Dimarco 7.03). Test: 68 verdi (5 nuovi sulla
stima: monotonia nel mercato, clamp, i misurati restano intatti, nessun fit senza dati).

## Listone: ordinamento per colonna, colonna presenze, shrinkage campione (2026-07-21)

**Ordinamento**: rimosso il pulsante ciclico; le intestazioni di colonna (Giocatore,
Squadra, Valore, Pres., Mercato) sono ora cliccabili — secondo click inverte, indicatore
▼/▲ sulla colonna attiva, colonne numeriche partono decrescenti. Chi non ha il valore
ordinato resta SEMPRE in fondo in entrambe le direzioni. La vecchia modalità "voto reale"
è diventata un FILTRO ("Solo con voto reale"), semanticamente più corretto di un ordinamento.

**Colonna presenze vuota**: mostrava le presenze della stagione CORRENTE, che nella 26/27
non è iniziata → 0 per tutti, mentre il valore veniva dalla precedente. Ora mostra le
presenze CHE SOSTENGONO il valore esposto (corrente, altrimenti precedente con marcatore
"prec."); anche l'ordinamento segue la stessa regola.

**Shrinkage per piccolo campione** (problema che la colonna vuota nascondeva): Pavard era
1° con 7.5 avendo giocato UNA partita, Rinaldi 7.0 idem. Ora ogni media stagionale è
regredita verso il 6 neutro in proporzione all'evidenza — `(n·avg + 5·6.0)/(n+5)` — prima
del blend corrente/precedente. Risultato: in testa solo stagioni vere (Dimarco 6.90 / 35
pres., Yıldız 6.74 / 34, N. Paz 6.59 / 35, De Ketelaere, Çalhanoğlu, Dybala); il miglior
giocatore con 1 sola presenza scende da 7.5 a 6.25.

**Robustezza frontend**: la pagina andava in crash bianco (`undefined.toFixed`) quando il
backend serviva una forma più vecchia — capitava col server avviato `--noreload` prima
delle modifiche. Ora usa controlli di tipo e degrada a "—". Test: 71 verdi (6 attese
aggiornate alla nuova matematica + 3 nuovi sullo shrinkage: una gara non fa un fuoriclasse,
la stagione piena resta intatta, il regolare batte la meteora).

## Messaggi d'errore leggibili dall'utente (2026-07-21)

Lo smoke test ha mostrato `API 401: {"detail":"Invalid credentials."}` in faccia all'utente
nella schermata di login. Corretto nel LAYER API, così ne beneficiano tutte le pagine.

- `parseJsonOrThrow` ora lancia un `ApiError` (status + payload grezzo) il cui `message` è
  una frase per l'utente; il dettaglio tecnico va in `console.warn` e resta su
  `ApiError.detail`, quindi il debug non si perde.
- Mappatura per stato: 401 su `/auth/login|register` → "Username o password non corretti",
  401 altrove → "Sessione scaduta"; 403/404/400 preferiscono il `detail` del backend
  (i nostri sono già scritti in italiano per l'utente); 5xx → "Errore del server".
  La distinzione del 401 usa l'ENDPOINT e non il token: un token scaduto rimasto in
  localStorage avrebbe fatto dire "sessione scaduta" a un login sbagliato.
- Fetch fallito (backend spento) → "Impossibile contattare il server…" invece di
  "Failed to fetch".
- **Backend i18n**: `LANGUAGE_CODE = 'it'` → Django/DRF emettono le validazioni standard
  già tradotte ("This field is required." → "Campo obbligatorio."); le locale italiane
  erano già installate e compilate. Tradotti anche i pochi messaggi custom inglesi
  ("Invalid credentials.", "Already joined.", "Cannot remove the last admin…",
  "Fixture not found.").
- **Nomi dei campi**: `FIELD_LABELS` traduce le chiavi tecniche nelle etichette del form →
  "Campionato di riferimento: Campo obbligatorio." invece di "reference_season_id: …".

Verificato sulla funzione reale e sugli endpoint reali. 71 test verdi, build pulita.

### Bug: "Imposta formazione" su partite già giocate (2026-07-21)

Segnalato durante lo smoke test: in una lega su campionato CONCLUSO il bottone
"Imposta formazione" compariva su fixture già disputate (2-2 a tabellino). La condizione
in `MatchesPage` era `is_user_involved && real_matchday != null` — non guardava se la
partita fosse già stata giocata. Aggiunto `status !== 'finished'`.

Verificando il fix è emerso un secondo difetto: nella lega PRE-STAGIONE il bottone non
compariva comunque, perché `seed_preseason_league` non creava i `FantasyMatchday` né
collegava i fixture (`real_matchday` = None) — l'avevo saltato per tenere il seed snello,
ma è proprio l'attività pre-stagione principale. Il seed ora mappa round N -> giornata
reale N e collega ogni fixture; il draft usa inoltre il valore UNIFICATO (voto misurato o
stimato dal mercato) invece di ordinare gli esordienti per ultimi.

Esito: lega 25-26 conclusa 41 bottoni -> 0; nuova lega 26/27 (id 43) 9 partite non giocate
-> 9 bottoni. NOTA: questo è solo l'ingresso nella UI; il vincolo forte "non si schiera un
giocatore la cui partita reale è iniziata" resta il lock formazione previsto in Fase 2-3.

### Pagina formazione: statistiche pre-stagione e partita reale (2026-07-21)

Due difetti segnalati provando la pagina formazione su una lega pre-stagione.

1. **"poco impiegato" per TUTTI.** `player_minutes` non era scoped a una stagione e la
   vista passava `as_of_matchday=1`, quindi il filtro `matchday < 1` escludeva ogni
   partita: 0 presenze -> `minutes_label` restituiva "low" per chiunque. Ora: le
   statistiche sono scoped alla stagione (`competition_season_id`) e, se la stagione di
   riferimento non ha ancora giocato, la vista ricade sull'ULTIMA stagione con dati
   (`previous_season_with_data`) — la stessa logica già usata per il valore nel Listone.
   `minutes_label` restituisce ora "unknown" quando non ci sono partite da cui giudicare,
   e la UI non mostra alcun badge (dire "poco impiegato" a chi non ha ancora giocato è
   semplicemente falso). Il payload espone `stats_season`. Esito sulla lega 26/27: da
   "tutti low" a 14 high / 5 medium / 4 low / 2 unknown, con stats da Serie A 2025-2026.

2. **Serviva la partita reale, non solo la zona.** Il payload della rosa espone ora
   `next_match` per ogni giocatore — avversario, casa/trasferta, orario e stato — risolto
   con `matchday_fixtures_by_team` (nuovo helper in `match_resolver`, che riusa la
   preferenza per la riga autorevole sui rinvii) + lo stint aperto del giocatore. La riga
   in formazione mostra "vs Cagliari · sab 22 ago 18:45"; quando l'orario è ancora un
   placeholder scrive "orario da definire" invece di inventare un'ora. La mappa delle zone
   al click resta (utile in modalità aura).

71 test verdi, build pulita.

### Pagina formazione: layout classic, riga compatta, media voto (2026-07-21)

Quattro rifiniture chieste provando la pagina.

1. **Campo regolare in modalità classic**: `PitchLineup` accetta `regular` (attivo se
   `mode === 'classic'`) e dispone l'XI per LINEE DI RUOLO, spaziate uniformemente,
   ignorando la posizione spaziale reale — che in classic è rumore, visto che conta solo
   il ruolo grossolano. Il rendering del campo è stato estratto in `PitchCanvas`,
   condiviso dai due layout (spaziale per aura, regolare per classic).
2. **Dettagli solo al click**: la riga mostra ora nome, ruolo, media voto e la partita in
   forma compatta; presenze/minuti/badge impiego/stagione dei dati compaiono in un
   riquadro solo quando il giocatore è selezionato.
3. **Squadra del giocatore visibile**: `next_match` porta ora anche il club proprio, e la
   UI rende la partita in ordine casa-trasferta con il club del giocatore in grassetto
   ("**Frosinone** - Juventus"), così si capisce per chi gioca.
4. **"rendimento atteso" sostituito**: era il margine del duello a zone (es. −0.01),
   incomprensibile in classic. Ora la riga mostra la MEDIA VOTO, la stessa cifra del
   Listone (misurata o stimata, con "(stimata)" quando è inferita). Il valore di forma
   resta un concetto aura e non viene più esibito qui né nel tooltip dei dischetti.

Nota di cablaggio: `player_values` va calibrato sull'INTERO pool, non sui 25 della rosa —
con un campione così piccolo il fit mercato->voto non si forma e ogni esordiente restava
senza valore. 71 test verdi, build pulita.

## DA FARE — Ristrutturazione registrazione (aggiunto 2026-07-21)

Stato attuale: `RegisterView` crea l'utente **subito e attivo** e restituisce il token;
l'email è **opzionale e non unica** (`data.get("email", "")`); nessun `EMAIL_BACKEND`
configurato; nessuna libreria OAuth. Una registrazione spuria è quindi banale.

**(a) Conferma via email**
- `email` obbligatoria e UNIVOCA + flag di verifica sull'utente (meglio di `is_active=False`,
  che impedisce il login senza spiegare perché).
- Link firmato con `default_token_generator` di Django (lo stesso del reset password):
  nessuna dipendenza aggiuntiva, nessun modello extra.
- Endpoint di verifica + rinvio email; login bloccato finché non verificato.
- Sviluppabile e testabile SUBITO con `EMAIL_BACKEND` di console; il provider si aggancia
  dopo cambiando solo configurazione.
- **Invio in produzione: NON dal VPS.** Linode blocca la porta 25 in uscita di default e un
  IP nuovo non ha reputazione (spam/rifiuti). Usare un relay SMTP transazionale; register.it
  serve soprattutto per i DNS: **SPF + DKIM + DMARC** sono indispensabili alla recapitabilità.

**(b) Accesso con Google**
- Requisiti: progetto Google Cloud, schermata di consenso, OAuth Client ID (Web), **HTTPS su
  dominio reale**, privacy policy + ToS se si pubblica fuori dalla modalità testing. Per i soli
  scope `email`/`profile` NON serve la verifica approfondita di Google.
- Integrazione consigliata per questa architettura (SPA + token DRF): il frontend ottiene un
  **ID token** da Google Identity Services, il backend lo verifica con `google-auth` e
  restituisce il proprio token DRF. Evita `django-allauth` (pensato per sessioni/redirect).
- Vantaggio: Google certifica l'email → questi utenti saltano la conferma.
- **Decisioni da prendere prima**: collegamento account (stessa email via password e via
  Google: si uniscono o si rifiuta?) e generazione dello username.

Prerequisito comune: hardening di produzione + HTTPS (oggi `DEBUG=True`, `ALLOWED_HOSTS`
solo localhost).

## Server Linode: ricognizione, pulizia, cadenza configurabile (2026-07-21)

**Ricognizione (accesso SSH fornito dall'utente).** Il server NON è vuoto: Nanode 1 GB
(1 vCPU, 965 MB RAM, 25 GB disco, swap già in uso), Ubuntu 20.04, **Python 3.8** (Django 5.2
ne richiede ≥3.10 → serve un interprete separato). Ospita l'**app legacy** in `/srv/vfoot`
(nginx → uwsgi + daphne) che serve **vfoot.it**, più `andreadeluca.online`, MySQL
(wordpress_db) e Redis. Certificati TLS validi per entrambi i domini. Nessun cron attivo:
l'app legacy non è più in uso.

**Correzione a una mia valutazione errata**: avevo concluso che un browser headless non
potesse girare su 965 MB. FALSO — Firefox 136 + geckodriver sono installati e lo scraping
legacy girava proprio così (`Browser('firefox', headless=True)`), anche schedulato. La
distinzione vera non è "browser sì/no" ma l'INTENSITÀ: scrape periodici brevi (calendario,
finalizzazione) hanno il profilo del legacy e reggono; il polling live minuto-per-minuto su
più partite in parallelo è tutt'altro carico.

**Pulizia disco** (autorizzata): journal vacuum, btmp (232 MB di tentativi di login falliti
— SSH sotto brute-force costante, da mettere nell'hardening), apt clean → **4,9 → 7,6 GB
liberi**. Docker era SPENTO: avviato temporaneamente per usare la sua stessa logica di
prune, recuperati 102 MB, poi riportato allo stato precedente. I container abbandonati erano
un'installazione Overleaf/mongo mai usata: rimossi su conferma dell'utente insieme a
immagini e volumi (`prune -af --volumes`, 2,89 GB). TOTALE: **4,9 -> 12 GB liberi**,
`/var/lib/docker` da 3,7 GB a 18 MB, docker riportato a inattivo com'era.

**Cadenza di scraping configurabile** (richiesta utente): nuovo
`VFOOT_LIVE_POLL_MINUTES` (default 2, da env var). `plan_tick` ora ripolla una singola
partita solo se `data_checked_at` è più vecchio dell'intervallo, e il `tick` lo timbra a
ogni poll. Così il tick può girare al minuto ma l'intensità reale è un parametro
ritarabile senza toccare codice — la leva per adattare la pipeline alla macchina.
4 test nuovi (mai pollata → dovuta; pollata da poco → saltata; oltre l'intervallo → dovuta;
allargando a 5 min la stessa partita non è più dovuta). 75 test verdi.

## Portabilità: configurazione da ambiente, percorsi, MySQL verificato (2026-07-21)

Preparazione al deploy, tutta verificata in locale.

**Configurazione da ambiente** (`.env` mai committato, `.env.example` versionato):
`DJANGO_SECRET_KEY` (chiave NUOVA generata; quella `django-insecure-` di default è
sparita) + guard che **rifiuta l'avvio con DEBUG spento e chiave di sviluppo**;
`DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`, `DJANGO_CORS_ORIGINS`; `DB_ENGINE`
(sqlite|mysql|postgresql) con credenziali; `VFOOT_LIVE_POLL_MINUTES`; `VFOOT_DATA_DIR`.
Per MySQL sono forzati `utf8mb4` e `STRICT_TRANS_TABLES` (senza, MySQL tronca in
SILENZIO invece di sollevare errore — corromperebbe nomi e valori delle feature).

**Percorsi hardcoded: azzerati.** I 6 comandi ausiliari derivano i percorsi da
`settings.VFOOT_DATA_DIR`. Verificato che caricano e che i default risolvono ai file reali.

**Driver MySQL**: `mysqlclient` richiede header di sistema; aggiunto **PyMySQL** come
fallback automatico in `config/__init__.py` (usato solo se `MySQLdb` non è importabile,
così dove c'è il driver nativo resta quello).

**MySQL VERIFICATO davvero** (non solo configurato): connessione a MySQL 8.0.45,
**tutte le migrazioni applicate da zero**, **75 test verdi** sul motore MySQL, e prova
utf8mb4 su nomi reali (Yıldız, Çalhanoğlu, Højlund, Ștefan, emoji) scritti e riletti
integri. Il codice è quindi indipendente dal motore.

**Nota di metodo (risposta a un dubbio dell'utente).** La titubanza verso un DB non
file-based nasceva dal flusso "sviluppo in locale, poi copio sul server". Il flusso resta
identico: cambia solo che non si copia più il database. Codice via `git pull`, schema via
**migrazioni**, dati utente che RESTANO sul server (copiarli sopra li distruggerebbe: è un
rischio del metodo, non del motore), dati di riferimento rigenerati dai comandi pipeline.
Si può anche tenere SQLite in locale e MySQL sul server — è solo una variabile d'ambiente —
al prezzo di possibili differenze che solo la produzione rivelerebbe.

Sul server, MySQL è GIÀ in esecuzione (serve WordPress): riusarlo evita ~200 MB di RAM
rispetto ad aggiungere Postgres, su una macchina da 965 MB.

## Server: Python 3.12 e database dedicato (2026-07-21)

Preparazione del server autorizzata dall'utente (punti 1 e 2). Decisione sul dominio:
**l'app legacy non deve più essere accessibile**, i file restano; quindi la nuova app
prenderà vfoot.it e potremo fermare uwsgi+daphne (misurati: ~83 MB liberabili).

**Ostacoli incontrati e risolti**
1. `apt` falliva scaricando gli indici: tentava **IPv6** e non raggiungeva i repo
   (`Failed to fetch ... [IP: 2a06:bc80::17]`). Risolto con
   `/etc/apt/apt.conf.d/99force-ipv4`; entrambi i repo poi rispondono 200.
2. **deadsnakes NON supporta più focal**: l'indice è scaricato ma il `Packages.gz` è
   VUOTO (20 byte, 0 pacchetti, fermo a ottobre 2025) — Ubuntu 20.04 ha chiuso il
   supporto standard ad aprile 2025. Verificato scaricando il file direttamente, non
   dedotto dai messaggi di apt.

**Soluzione**: `uv` (installato via pip, non con `curl | sh`) → **Python 3.12.13**
installato in 1,27 s da build precompilata, senza compilare e senza dipendenze di
sistema. Il Python di sistema (3.8) resta intatto, così l'app legacy non rischia nulla.
Compilare da sorgente avrebbe richiesto 10-30 minuti su 1 vCPU più ~300 MB di build deps.

**Database**: creati `vfoot_app` (utf8mb4/unicode_ci) e l'utente `vfoot_app`@localhost con
password generata casualmente; accesso verificato. Il `wordpress_db` esistente non è stato
toccato. Riusare l'istanza MySQL già attiva evita ~200 MB di RAM rispetto ad aggiungere
Postgres su una macchina da 965 MB.

Restano per il deploy vero: codice sul server + venv 3.12, `.env` di produzione, build del
frontend, nginx (nuovo vhost su vfoot.it al posto del legacy), gunicorn+systemd, timer per
sync_calendar/tick, e la ricostruzione dati dalla cache.

## Vincoli di deploy emersi: WordPress convivente e asta realtime (2026-07-22)

**1. La Linode ospita anche il WordPress personale dell'utente.** Isolamento verificato:
vhost nginx separati (`andreadeluca.online.conf` vs `fanta_nginx.conf` — tocchiamo solo
quest'ultimo), database MySQL distinti con utenti distinti (`wordpress_db` non toccato
quando è stato creato `vfoot_app`), php-fpm non coinvolto. L'unico punto di contatto reale
è la RAM: php-fpm ~117 MB, mysqld ~21 MB; fermare uwsgi+daphne del legacy ne libera ~83 MB.

**2. L'asta live è un requisito da portare.** Il legacy la implementava con **Django
Channels + WebSocket** (`chat/consumers.py`, `fanta/routing.py`, `fanta/asgi.py`), servita
da **daphne** sulla 8089 con **Redis** come channel layer — ecco a cosa servivano quei
processi. Meccanica: un banditore chiama un giocatore, i partecipanti connessi lo vedono
subito e rilanciano, il banditore accetta o no.
La NUOVA app ha i modelli (`AuctionSession`/`AuctionNomination`/`AuctionBid`) e gli
endpoint REST, ma NESSUN realtime: `getAuctionState` è su richiesta, niente polling né
WebSocket, nessuna dipendenza realtime in requirements.
Precisazione sulla diagnosi dell'utente: il costo non è dell'asta ma del POLLING (N client
× refresh continuo per sentirsi dire "nessuna novità"). Un'asta a 10 partecipanti su
WebSocket è carico trascurabile anche su questa macchina.

**DECISIONE DI ARCHITETTURA**: deployare da subito con **uvicorn (ASGI)** invece di
gunicorn (WSGI). `config/asgi.py` esiste già e Django 5.2 serve l'HTTP identicamente;
partire WSGI significherebbe rifare layer server e nginx quando aggiungeremo i WebSocket.
nginx va configurato SUBITO con l'inoltro dell'upgrade WebSocket sul percorso dedicato.
Redis è già in esecuzione: nessuna installazione aggiuntiva per il channel layer.

**DA FARE (asta live)**: aggiungere `channels` + `channels-redis`, i consumer per la
sessione d'asta (chiamata giocatore / rilancio / aggiudicazione), e l'aggancio frontend
via WebSocket al posto della lettura su richiesta.

## Deploy in produzione: rebuild su Debian 13 e app online (2026-07-22)

Il server era fermo a Ubuntu 20.04 (2020): Python 3.8, PostgreSQL 12, MariaDB 10.3, PHP 7.4
(fine vita 2022) — tutti sotto i minimi richiesti, e ogni passo richiedeva un aggiramento.
Scelta dell'utente: **Rebuild della stessa Linode** (nessun costo aggiuntivo, IP invariato),
con **Debian 13** preferita a Ubuntu 26.04 per base piu leggera e maturita (1 GB di RAM).

**Backup** (86 MB, verificato integro e ripristinabile prima del rebuild): WordPress file+DB,
certificati, configurazioni, app legacy senza log. Scoperta: 4,9 GB dei "dati" erano log mai
ruotati (`uwsgi.log` da solo 4,1 GB).

**Risultato del cambio di base** — spariti tutti gli aggiramenti:
Python 3.8 -> **3.13.5** · PostgreSQL 12 -> **17.10** · PHP 7.4 -> **8.4.23** ·
Chromium ora pacchettizzato nativamente · RAM disponibile 511 -> 764 Mi con **swap a zero**
(era 259 Mi) · disco 79% -> 4% occupato.

**Messa in sicurezza**: SSH solo a chiave (fail2ban ha registrato 97 tentativi falliti nella
prima ora), firewall nftables (solo 22/80/443, database irraggiungibili dall'esterno),
aggiornamenti automatici, hardening systemd sul servizio.

**Ripristinato**: WordPress su PHP 8.4, verificato a 200 con contenuto reale.

**Nuova app ONLINE su https://vfoot.it**: SPA React servita da nginx, API su uvicorn
**ASGI** (non WSGI — scelta presa per l'asta live, cosi i WebSocket non richiederanno di
rifare il layer server), PostgreSQL 17, TLS valido, redirect HTTP->HTTPS, percorso `/ws/`
gia predisposto per i WebSocket.

**Due bug intercettati verificando invece di assumere**:
1. La SECRET_KEY scritta via heredoc SSH era stata **corrotta dall'espansione della shell**
   (39 caratteri invece di 50: i `$` erano stati mangiati). Rigenerata ESEGUENDO Python sul
   server, senza passare da alcuna shell. Una chiave indebolita compromette sessioni, CSRF e
   token di reset password.
2. `check --deploy` segnalava 5 problemi: aggiunte impostazioni HTTPS dietro proxy
   (`SECURE_PROXY_SSL_HEADER` — senza, Django crede che tutto sia in chiaro e i cookie
   sicuri non attecchiscono), cookie sicuri, redirect SSL, HSTS **deliberatamente breve**
   (un max-age lungo e' difficile da annullare). Restano 2 avvisi, entrambi scelte
   consapevoli (HSTS su sottodomini e preload, quest ultimo di fatto irreversibile).

**Flusso di deploy collaudato**: modifica in locale -> commit -> push -> `git pull` sul
server -> migrate/collectstatic -> restart. Usato davvero due volte durante il deploy.

**Consumo attuale**: php-fpm 208 MB + mariadb 156 MB (WordPress) > postgres 89 + uvicorn 67
(la nostra app). 402 Mi disponibili. Se servira' margine per il browser, il primo posto dove
guardare e' la configurazione di WordPress, non la nostra app.

**Restano**: playwright+chromium per lo scraping, ricostruzione dati dalla cache, creazione
utente, taratura php-fpm/mariadb. I timer (`vfoot-tick`, `vfoot-calendar`) sono registrati e
abilitati ma NON avviati: prima servono dati e gli hook di scrape reali.

---

## 22 luglio 2026 — server operativo con dati veri e utente di test

**Chromium**: usiamo quello **di sistema** pacchettizzato da Debian invece di far
scaricare a Playwright una seconda copia dello stesso browser (~150 MB e un
aggiornamento in meno su una macchina da 1 GB). Il percorso e' configurabile
(`VFOOT_CHROMIUM_PATH`), non cablato nel codice.

**Cache di scraping fuori dal checkout**: `import_sofascore` e `sync_calendar`
risolvono la cache da `settings` (`VFOOT_DATA_DIR`), non piu' dalla posizione del
file sorgente. Sul server 1,5 GB di JSON stanno in `/srv/vfoot-data` e un
redeploy non li tocca. In locale il default resta invariato.

**Dati ricostruiti sul server** (PostgreSQL, da cache, zero rete):
380 partite 25/26, 772 giocatori, 17.773 presenze, 1.263.313 feature di zona;
calendario 26/27 (380 partite) e rose Transfermarkt (660 giocatori, 20 squadre,
660 valori di mercato, 72 portieri).

**Utente `andrea` creato** (staff+superuser) e due leghe di prova: `Lega Classic
Demo` sul 25/26 concluso (180 partite + coppe) e `Lega Serie A 2026-2027`
pre-campionato con listone congelato.

**Tre problemi trovati verificando, non assumendo**:
1. `import_sofascore` **non timbra lo stato** delle partite: restavano tutte
   `scheduled`, quindi la "stagione precedente con dati" non veniva trovata e
   TUTTI i valori del listone erano nulli. Lo stato lo assegna `sync_calendar`,
   che sul server avevo lanciato solo per il 26/27. Risolto sincronizzando anche
   il 25/26 offline. **Da ricordare: dopo un import storico serve sempre il sync
   del calendario di quella stagione.**
2. La cache Django viveva **dentro il checkout** e finiva di proprieta' di chi
   aveva lanciato per ultimo un comando (root, nel mio caso): il servizio poi
   riceveva `PermissionError` e rispondeva 500. Spostata in una directory di
   runtime (`DJANGO_CACHE_DIR`) di proprieta' dell'utente del servizio.
3. Con `DEBUG=False` Django **non logga da nessuna parte** i traceback delle
   richieste: il 500 era una pagina bianca e un journal vuoto. Aggiunta una
   configurazione `LOGGING` che manda `django.request` su stderr, che systemd
   cattura.

**Listone in produzione**: 4,5s a freddo, **0,29s a caldo** (cache calda), fit
valore/mercato r=0,443.

**RISOLTO (ed e' una notizia che cambia il piano)**: lo scraping dal server NON
funziona, e non per le ragioni che sospettavo. Confronto controllato, stesso
codice e stesso client:

| origine | token x-requested-with | esito |
|---|---|---|
| macchina locale (IP residenziale) | catturato (`7f4b46`) | **HTTP 200 in 5s** |
| server Linode (IP datacenter) | catturato (`7f4b46`) | **HTTP 403**, backoff fino a 7 tentativi |

Non e' RAM, non e' Chromium, non e' la sandbox: **Chromium sul server parte e
funziona** (7-8 processi, RAM libera ~190 Mi, nessun OOM, swap disponibile) e il
sito pubblico si carica con status 200 e titolo reale. A essere bloccate sono
solo le chiamate `/api/v1/` dall'IP del datacenter. Sembrava un blocco perche'
il client ritenta con backoff esponenziale invece di fallire subito.

**Conseguenza sul piano**: il polling live non puo' partire dal Linode. La strada
gia' ipotizzata — polling sul **Raspberry di casa** (IP residenziale) che spinge
i dati verso il server — diventa quella necessaria. Da decidere il meccanismo di
push (API autenticata vs SSH/rsync). I timer restano deliberatamente fermi.
