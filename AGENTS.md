# AGENTS.md

## Project Overview

Vfoot Boosted is an evolution of the original Django-based Fantacalcio
platform.

There are **two conceptual layers** in the repository:\*\*

1.  **Legacy engine (`fantaapp`)**
    -   Classic Fantacalcio logic.
    -   Role-based (P, D, C, A).
    -   Linear fantavote computation (`fantafun.votostd`).
    -   League, formations, substitutions, modifiers implemented in
        `lega.py`.
2.  **New Vfoot Engine (in development)**
    -   Heatmap-driven positional influence.
    -   No predefined rigid roles.
    -   Tactical advantage emerges from spatial occupation.
    -   Zone-based duel mechanics.
    -   Designed to eventually replace classic role-based scoring.

Unless explicitly stated, new development should target the **new Vfoot
engine architecture**, not extend the legacy role-based model.

------------------------------------------------------------------------

## Core Design Philosophy (Vfoot Variant)

This project is NOT a small modification of classic Fantacalcio.

It is a **tactical, spatial simulation layer on top of real match
data**.

Key principles:

1.  Players do NOT have rigid predefined roles.
2.  Their effective role emerges from real match heatmaps.
3.  The pitch is discretized into zones.
4.  Each zone produces a duel between two fantasy teams.
5.  Tactical balance matters.
6.  Overcrowding must be penalized.
7.  The system must be:
    -   managerially rich,
    -   mathematically consistent,
    -   computationally feasible,
    -   understandable at conceptual level by users.

------------------------------------------------------------------------

## Spatial Model (New Engine)

### Pitch Partition

-   Rectangular grid (default: 5 columns × 4 rows).
-   Total zones: 20.
-   Configurable `ZoneSet`.

Each zone is independent for duel evaluation.

------------------------------------------------------------------------

### Heatmap-Based Presence

For each real match:

-   A player produces a heatmap.
-   Heatmap is normalized into a distribution over grid zones.
-   For each player and zone:

Presence(player, zone) ∈ \[0,1\]\
Sum over zones = 1

Presence is not manually assigned from role. It is computed from real
data.

------------------------------------------------------------------------

### Fantasy Formation

User selects 11 players.

No hard module constraints like 4-4-2 required. Tactical balance is
enforced through scoring mechanics.

------------------------------------------------------------------------

## Zone Duel Algorithm

For each zone Z:

1.  Compute weighted pure vote:

ZoneScore_team(Z) = Σ Presence(player,Z) × PureVote(player)

2.  Compare home vs away.
3.  Winner gets bonus.
4.  Loser gets malus.

Bonus/Malus default: ±10% of weighted fantavote contribution in that
zone.

Pure vote determines winner. Fantavote determines magnitude.

------------------------------------------------------------------------

## Overcrowding Rule (Anti-Bug Mechanism)

If total presence in a zone exceeds 100%:

TotalPresence(Z) \> 1

Then:

-   Contribution is renormalized.
-   Excess percentage is discarded.

This prevents stacking multiple players unrealistically.

Overcrowding must never increase net efficiency.

------------------------------------------------------------------------

## Scoring Pipeline (New Engine Target)

Future scoring flow should look like:

1.  Real match data ingestion.
2.  Heatmap → normalized zone presence.
3.  Zone duel resolution.
4.  Aggregate adjusted fantavote.
5.  Convert to goals.

Legacy goal conversion (optional reuse):

goals = floor((fantavote - 66) / 6) + 1

------------------------------------------------------------------------

## Backend Strategy (Going Forward)

New modules should follow this structure:

vfoot/ models/ zones.py heatmap.py presence.py services/ zone_engine.py
duel_engine.py scoring_engine.py api/ views.py serializers.py

Legacy app (`fantaapp`) should not be deeply modified. Instead, new
logic should live in parallel.

------------------------------------------------------------------------

## Classic Role Resolution (voto puro / listone)

A player's classic role (POR/DIF/CEN/ATT) has THREE layers. Do not confuse them —
mixing them up silently mis-scores wide attackers (a `left winger` Transfermarkt
files as a midfielder is really a forward).

1.  **`Player.classic_role_seed`** — the raw Transfermarkt seed. Wingers map to CEN by
    convention. This SEEDS the layers below; it must **never** be read to score.
2.  **`CurrentPlayerRole`** (ONE row per player, no season dimension,
    `manage.py compute_classic_roles`) — TM + a k-means style inference over 15
    measures that resolves ambiguous positions. A player with too few minutes to
    cluster (< 600) but who lined up at all is disambiguated by his **coarse
    SofaScore lineup position** (F/M/D, stored in `MatchAppearance.raw_stats
    ['position']`, method `sofa`); only a player who never appears falls back to
    the raw TM default. It is the CURRENT best estimate — a recompute (fresh
    scrape) overwrites it in place, there is no per-season history. This is **THE
    role for scoring** — reach it via `classic_rating.current_role_map()`, used by
    `build_reference`, `voto_puro_for_match`, `compute_role_averages`,
    `player_ratings`, and `classic_fit_weights`. (Calibrate a season's reference
    while the current roles still reflect that season's play, i.e. at season end.)
3.  **`LeaguePlayerRole`** — a league's frozen snapshot of layer 2 at listone time.
    Authority INSIDE that league (pagella display, lineup legality); it overrides
    layer 2 for that league only.

Listone arbitration: only players whose position is genuinely ambiguous AND whose
Transfermarkt market value clears `league_decisions.RELEVANCE_MIN_VALUE_EUR`
(€5M) reach the admin's decision queue; everyone below auto-takes the layer-2
proposal (no market value ⇒ obscure ⇒ auto-default). See `league_decisions.py`.

When the queue is raised: `snapshot_league_listone` is the single entry point, and
it runs at **league creation** (classic + reference season), on every **Transfermarkt
import**, when the market or an offer session **opens**, and on the admin's explicit
`decisions/refresh`. It is additive and idempotent — already-frozen roles never move.
A player awaiting a decision is deliberately left WITHOUT a `LeaguePlayerRole` row,
and that absence is the gate the auction and the offer market read; so the snapshot
must exclude both `players_needing_decision` **and** `undecided_player_ids` (the
first skips anyone already asked about, so on its own the next poll would seed him
and answer the question by accident).

Which measured players are ambiguous is decided by `CurrentPlayerRole.role_margin`,
NOT by `confidence`. The latter says how firmly a player sits in his *category*
(step 2 of the inference); what reaches the listone is step 3, the condensation of
eight styles into four roles, and the two questions have different answers — a
midfielder oscillating between `mediano` and `centrocampista` has a low confidence
and a completely determined role. `role_margin` re-aggregates the co-association
mass BY ROLE and reports the gap to the runner-up; below `ROLE_MARGIN_REVIEW` it
goes to a human. See `role_inference.role_margins`.

## Invariants (Hard Constraints)

Agents must NEVER:

-   Read `Player.classic_role_seed` to SCORE the voto puro — always go through
    `current_role_map()` (see Classic Role Resolution above).
-   Reintroduce rigid positional roles in the new engine.
-   Hardcode tactical bonuses into individual players.
-   Break zone normalization.
-   Remove overcrowding penalty.
-   Change scoring constants (like 10%) without explicit approval.

------------------------------------------------------------------------

## Priorities

1.  Mathematical coherence.
2.  Tactical fairness.
3.  Exploit resistance.
4.  Clean architecture separation (legacy vs new engine).
5.  Extensibility for future tactical layers.

------------------------------------------------------------------------

## Update Log

-   2026-02-12:
    -   Integrated original design philosophy (zone duels,
        overcrowding).
    -   Formalized heatmap-driven positional model.
    -   Clarified separation between legacy role-based engine and new
        Vfoot engine.
-   2026-02-15:
    -   Added StatsBomb feature ingestion pipeline in backend
        (`realdata/services/statsbomb_adapter.py`) with management
        command `import_statsbomb`.
    -   Imported full Serie A StatsBomb season (380 matches) into
        feature tables (`PlayerZoneFeature`, `TeamZoneFeature`).
    -   Adopted feature-only DB strategy for SQLite: raw event data kept
        outside main DB; added ingestion provenance table
        `DataIngestionManifest`.
    -   Added SQLite pre-import lock check in `import_statsbomb`
        command.
    -   Frontend context/UX refinements:
        - top bar now surfaces active team context (with explicit
          `Squadra:` label),
        - `Matches` page now shows only user-involved fixtures for
          current + next matchday window.

------------------------------------------------------------------------

## Current Implementation Snapshot (2026-02-15)

### Repository Layout (current)

-   `legacy-fanta/`: old Django legacy project (separate legacy repo).
-   `vfoot-backend/`: new backend (Django + DRF), active development.
-   `vfoot-frontend/`: new frontend (Vite + React), active development.
-   `experiments-vfootfrontend/`, `experiments-scrape-sofascore/`,
    `experiments-restructuring/`: non-core experimental material.

### Backend Status

-   Core Vfoot modules are split as:
    -   `vfoot/models/{zones.py,heatmap.py,presence.py,lineup.py}`
    -   `vfoot/services/{zone_engine.py,duel_engine.py,scoring_engine.py}`
    -   `vfoot/api/{views.py,serializers.py,urls.py,data_builders.py}`
-   Contract-oriented endpoints implemented:
    -   `GET /api/v1/lineup/context`
    -   `POST /api/v1/lineup/save`
    -   `GET /api/v1/matches`
    -   `GET /api/v1/matches/<match_id>`
-   Auth endpoints implemented and active:
    -   `POST /api/v1/auth/register`
    -   `POST /api/v1/auth/login`
    -   `GET /api/v1/auth/me`
    -   `POST /api/v1/auth/logout`
-   Protected endpoints require token auth (`TokenAuthentication`).
-   Overcrowding rule and ±10% duel modifier are enforced in backend
    duel logic.
-   `realdata` now supports feature-first ingestion with:
    -   `PlayerZoneFeature`
    -   `TeamZoneFeature`
    -   `DataIngestionManifest`
-   StatsBomb ingestion command available:
    -   `cd vfoot-backend/src && ../.venv/bin/python manage.py import_statsbomb --limit-matches <N>`
-   Full-season StatsBomb load completed in local SQLite (dev baseline):
    -   `Match`: 380
    -   `MatchAppearance`: 16,750
    -   `PlayerZoneFeature`: 608,647
    -   `TeamZoneFeature`: 175,961
-   Match-detail contract is still being progressively aligned from
    synthetic macro placeholders to provider-derived macro metrics.

### Frontend Status

-   API provider switch is implemented:
    -   `mock` or `backend` via `VITE_API_PROVIDER` in env.
    -   Runtime override with query param: `?api=mock|backend`.
-   Shared API adapter is in `src/api/` and pages no longer call mock
    API directly.
-   New public landing page with product narrative + auth forms:
    -   `src/pages/LandingPage.tsx`
-   Auth state/guarding:
    -   `src/auth/AuthContext.tsx`
    -   `/home`, `/league`, `/squad`, `/matches`, `/market` require
        authenticated session.
-   Top bar context improvements are implemented in
    `src/layouts/AppShell.tsx`:
    -   explicit current team label (`Squadra: ...`),
    -   league/team context visible also on mobile header.
-   `Matches` page filtering updated in `src/pages/MatchesPage.tsx`:
    -   only fixtures where user team is involved,
    -   only current and next matchday window (with fallback on round
        number when real matchday mapping is missing).

### Dev Notes

-   **Rebuilding a known application state: `manage.py simulate_scenario`.**
    The entry point for "put everything back the way it was so I can test X".
    `--list` describes the named scenarios (`g22-live` is a half-played matchday
    22 with one match in progress); `--at <instant>` moves the same scenario to
    another moment. Two guarantees it is built around, both covered by
    `realdata/tests_season_simulator.py`:
    -   same scenario + same instant → the identical season, down to the scorers;
    -   same scenario + a LATER instant → the SAME season further on. A match is
        always played in full and then cut back to the minute being watched, and
        each fixture draws from a stream keyed on its own provider id, so a goal
        scored at the 20th minute is still there at the 90th. Without both of
        those, advancing the clock re-rolls the season and nothing about a live
        pipeline can be tested.
    -   Winding the clock BACK is supported and is the case that rots silently:
        matches that have un-happened have their rows erased, and league
        matchdays no longer behind the front are reopened.
    -   Runs are incremental — a finished match's payload never changes, so it is
        ingested once. Moving the instant a few hours touches only the matches
        that changed. After editing the generator or changing the seed, pass
        `--fresh`: every payload is then different and the whole season must be
        re-ingested (minutes, not seconds).
-   **Playing a season that has not been played.** A synced calendar with no
    results leaves the whole scoring chain (voto puro, listone, pagelle,
    standings) with nothing to work on. Two commands fill it in — both driven by
    `simulate_scenario`, and neither inventing a database row directly:
    -   `manage.py simulate_sofascore_season --season 3 --through 22 --now
        2027-01-31T18:35:00+01:00` writes SofaScore-shaped JSON into the request
        cache and then runs the REAL importer over it (offline — a cached path
        never touches the network). Each appearance is donor-sampled from a
        completed season's stat blobs, so it is internally coherent; the events
        (scoreline, scorers, cards, subs) are decided first and always win. See
        `realdata/services/season_simulator.py` for what is and is not modelled.
    -   `manage.py advance_fantasy_league --league 62 --through 22` fields a
        lineup per manager per matchday and concludes the rounds behind the
        front, through `score_and_persist_matchday` — the same function the
        admin's Concludi button calls.
    -   The two are calibrated against the real season and stay within a few
        percent of it (shots, goals, cards, xG/xGOT by outcome, assists per
        goal). The known cost: scored against the frozen `vote_reference.json`,
        the synthetic ATT and POR averages sit about 0.1 of a vote above 6 —
        a fifth of the pagella's own grid step, and worth remembering before
        reading anything into a simulated listone.
-   **Driving the REAL live pipeline off a simulated season:
    `VFOOT_EGRESS_SIMULATED`.** `egress_client` is the one place the system
    crosses to the outside world — it warms the request cache, and everything
    else reads that cache offline. With the flag on, `run_egress` is served by a
    generator (`realdata/services/egress_sim.py`) that writes the payload
    SofaScore would be serving for that match *at this minute*, taken from
    `timezone.now()`. So `manage.py tick` on its ordinary cadence exercises the
    genuine scheduler, live poll, full-time observation and +15min/+1h
    finalization — only the bytes are invented:
        18:40 live-poll 1-0 · 19:50 status flips to finished · 20:05 stamp-ft
        · 20:25 final-check · 21:10 final-confirm -> data_ready
    Rebuilding the season at a later instant is NOT a substitute: it produces the
    same rows without ever running the state machine that is supposed to produce
    them.
    Two things this got wrong at first, both worth knowing: the importer resolves
    a match from the SCHEDULE and skips anything the schedule does not call
    finished, so the round's event file has to be updated alongside the live
    endpoint or finalization imports nothing while reporting success; and the
    "what minute is this match at" rule must live in ONE place
    (`season_simulator.status_at`, which also sits out the interval) or a fixture
    is at the 60th minute when rebuilt and the 75th when polled.
-   **`VFOOT_FAKE_NOW`** shifts the instant the app looks at the data from,
    without touching the data, so a simulated season can be observed from
    inside it. It patches `django.utils.timezone.now` from settings.py — early
    enough to catch `default=timezone.now` fields — and the clock WALKS rather
    than freezing. A middleware then ships the server's now as `X-Vfoot-Now` so
    the client's market countdowns do not measure across two clocks. Inert when
    the variable is unset. See `vfoot/simclock.py`.
-   Preferred way to start/stop both servers: **`./vfoot-dev`** at the
    repo root. It keeps the four places the host appears in sync
    (`DJANGO_ALLOWED_HOSTS`, `DJANGO_CORS_ORIGINS`,
    `VFOOT_FRONTEND_BASE_URL`, `VITE_API_BASE_URL`) and restarts:
    -   `./vfoot-dev local` — localhost only (the default assetto)
    -   `./vfoot-dev lan` — reachable from the home wifi on this
        machine's IP, re-detected at every run (DHCP-proof)
    -   `./vfoot-dev status` — mode, IP, what's running; also warns
        when the running backend's env has drifted from `.env`
-   Manual equivalents, if you need them:
    -   `cd vfoot-backend/src && ../.venv/bin/python manage.py runserver localhost:8000 --noreload`
    -   `cd vfoot-frontend && npm run dev -- --host localhost --port 5173`
-   Gotcha that cost an afternoon: `load_dotenv` does **not** override
    variables already exported in the shell, so a stale `export
    DJANGO_ALLOWED_HOSTS=...` silently beats `.env`. `./vfoot-dev`
    clears those before launching (`env -u`); `status` reports the
    mismatch if a server was started some other way.
-   Second gotcha: a Vite dev server left running for a day can serve a
    stale module graph after edits (blank page, "does not provide an
    export named X" for an export that plainly exists). Restart it and
    clear `node_modules/.vite` — `./vfoot-dev restart` does the former.
-   For heavy imports on SQLite, avoid running Django server in parallel
    with importer commands to reduce lock contention.
-   StatsBomb import lock check can be bypassed only when needed:
    -   `--skip-lock-check`
-   Conservative write mode for problematic local environments:
    -   `--safe-writes`

------------------------------------------------------------------------

## Vfoot Scoring Schema Summary (Working Baseline)

The Vfoot schema currently being implemented should follow this
two-stage logic:

1.  Compare home/away teams area-by-area by considering only players
    effectively active in each area.
2.  Convert these local comparisons into zone points and aggregate to
    the final match score.

### 1) Area and Zone Comparison Layer

-   For each real match, ingest player-level performance data with
    spatial information (heatmaps/events).
-   Compute normalized zone presence:
    -   `presence(player, zone)` in `[0,1]`
    -   sum across zones = 1 for each player.
-   For each tactical area/zone group (defense, midfield, attack,
    flanks, etc.), include only players with meaningful presence in
    those zones.
-   Build home/away comparative metrics per zone from:
    -   spatial presence,
    -   performance quality indicators (e.g. pure vote / derived quality
        features),
    -   optional contextual factors as needed.
-   Determine a local result (`home`, `away`, `draw`) for each zone.

### 2) Zone-to-Score Aggregation Layer

-   Assign zone points from each local duel.
-   Enforce anti-exploit overcrowding rule:
    -   if total presence in a zone exceeds 1, renormalize and discard
        excess efficiency.
-   Sum all zone outputs into overall home/away totals.
-   Expose both:
    -   final total score,
    -   per-zone breakdown (decisive zones, swings, story/explainability
        output).
-   Optionally map totals to legacy-style goals if needed.

### Calibration Note

This schema is intentionally a baseline. Detailed weighting and scoring
constants must be tuned on real historical data (hybrid strategy) so the
system is:

-   realistic in football terms,
-   tactically meaningful for users,
-   robust against exploits,
-   fun to play.
