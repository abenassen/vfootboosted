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

## Invariants (Hard Constraints)

Agents must NEVER:

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
