from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Sum

from realdata.models import Match, MatchAppearance, PlayerOnPitchInterval, PlayerZoneFeature
from vfoot.services.vector_zone_scoring import score_zone_duel


FEATURE_WEIGHTS = {
    "xg_shots": 1.50,
    "shots": 0.20,
    "touches_in_box": 0.04,
    "key_passes": 0.30,
    "passes_into_box": 0.12,
    "progressive_passes_completed": 0.08,
    "progressive_carries": 0.08,
    "ball_recoveries": 0.05,
    "interceptions": 0.10,
    "pressures": 0.015,
    "clearances": 0.05,
    "errors_bad_passes": -0.035,
    "errors_dispossessed": -0.09,
    "errors_fouls_committed": -0.06,
    "errors_miscontrols": -0.08,
}

GOAL_THRESHOLDS = (66.0, 72.0, 78.0, 84.0, 90.0, 96.0)
DEFAULT_VECTOR_CALIBRATION = "calibration/vector_zone_duel_v1.json"


@dataclass(frozen=True)
class PoolPlayer:
    player_id: int
    name: str
    appearances: int
    starts: int
    minutes: int
    value: float
    price: int


@dataclass
class SimTeam:
    id: int
    name: str
    budget: int
    roster: list[PoolPlayer] = field(default_factory=list)
    spent: int = 0
    points: int = 0
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    score_for: float = 0.0
    score_against: float = 0.0

    @property
    def remaining_budget(self) -> int:
        return self.budget - self.spent


def hard_goals(score: float) -> int:
    return sum(1 for threshold in GOAL_THRESHOLDS if score >= threshold)


def round_robin_rounds(team_ids: list[int], seed: int) -> list[list[tuple[int, int]]]:
    rng = random.Random(seed)
    work = list(team_ids)
    rng.shuffle(work)
    if len(work) % 2:
        work.append(-1)
    rounds = []
    for round_no in range(len(work) - 1):
        pairs = []
        for idx in range(len(work) // 2):
            a = work[idx]
            b = work[-1 - idx]
            if a == -1 or b == -1:
                continue
            pairs.append((a, b) if round_no % 2 == 0 else (b, a))
        rounds.append(pairs)
        work = [work[0], work[-1], *work[1:-1]]
    return rounds


class Command(BaseCommand):
    help = "Run an artifact-only historical Vfoot league dry run from imported realdata."

    def add_arguments(self, parser):
        parser.add_argument("--teams", type=int, default=10)
        parser.add_argument("--budget", type=int, default=500)
        parser.add_argument("--squad-size", type=int, default=25)
        parser.add_argument("--starters", type=int, default=11)
        parser.add_argument("--bench-size", type=int, default=7)
        parser.add_argument("--matchdays", type=int, default=0, help="0 means all available real matchdays.")
        parser.add_argument("--min-appearances", type=int, default=8)
        parser.add_argument("--score-base", type=float, default=58.0)
        parser.add_argument("--score-scale", type=float, default=8.0)
        parser.add_argument("--scoring-mode", choices=["vector", "event"], default="vector")
        parser.add_argument("--vector-calibration", type=str, default=DEFAULT_VECTOR_CALIBRATION)
        parser.add_argument("--fantasy-home-advantage", type=float, default=0.0)
        parser.add_argument("--fantasy-margin-boost", type=float, default=2.0)
        parser.add_argument("--disable-temporal-substitutions", action="store_true")
        parser.add_argument("--seed", type=int, default=42)
        parser.add_argument("--output", type=str, default="calibration/historical_vfoot_league_dry_run.json")

    def handle(self, *args, **options):
        team_count = int(options["teams"])
        budget = int(options["budget"])
        squad_size = int(options["squad_size"])
        starters_count = int(options["starters"])
        bench_size = int(options["bench_size"])
        seed = int(options["seed"])
        score_base = float(options["score_base"])
        score_scale = float(options["score_scale"])
        scoring_mode = str(options["scoring_mode"])
        fantasy_home_advantage = float(options["fantasy_home_advantage"])
        fantasy_margin_boost = float(options["fantasy_margin_boost"])
        if team_count < 2:
            raise CommandError("--teams must be >= 2")
        if squad_size < starters_count:
            raise CommandError("--squad-size must be >= --starters")

        matchdays = self._matchdays(int(options["matchdays"]))
        if not matchdays:
            raise CommandError("No historical matchdays found.")

        pool = self._player_pool(min_appearances=int(options["min_appearances"]))
        required_players = team_count * squad_size
        if len(pool) < required_players:
            raise CommandError(f"Player pool too small: {len(pool)} available, {required_players} required.")

        teams = [SimTeam(id=i + 1, name=f"Manager {i + 1}", budget=budget) for i in range(team_count)]
        self._assign_rosters(teams, pool, squad_size=squad_size)

        matchday_player_scores = self._matchday_player_scores()
        matchday_player_zone_features = self._matchday_player_zone_features() if scoring_mode == "vector" else {}
        matchday_player_intervals = self._matchday_player_intervals()
        goalkeepers = self._goalkeepers()
        season_footprints = self._player_season_footprints()
        vector_calibration = self._load_vector_calibration(str(options["vector_calibration"])) if scoring_mode == "vector" else None
        schedule = round_robin_rounds([team.id for team in teams], seed=seed)
        team_by_id = {team.id: team for team in teams}
        fixture_reports = []

        for idx, real_matchday in enumerate(matchdays, start=1):
            fantasy_pairs = schedule[(idx - 1) % len(schedule)]
            for home_id, away_id in fantasy_pairs:
                home = team_by_id[home_id]
                away = team_by_id[away_id]
                home_result = self._lineup_and_score(
                    home,
                    real_matchday=real_matchday,
                    player_scores=matchday_player_scores,
                    starters_count=starters_count,
                    bench_size=bench_size,
                    score_base=score_base,
                    score_scale=score_scale,
                    player_zone_features=matchday_player_zone_features.get(real_matchday, {}),
                    player_intervals=matchday_player_intervals["players"].get(real_matchday, {}),
                    player_final_seconds=matchday_player_intervals["player_final_seconds"].get(real_matchday, {}),
                    matchday_final_seconds=matchday_player_intervals["final_seconds"].get(real_matchday, 90 * 60),
                    temporal_substitutions=not bool(options["disable_temporal_substitutions"]),
                    goalkeepers=goalkeepers,
                    season_footprints=season_footprints,
                )
                away_result = self._lineup_and_score(
                    away,
                    real_matchday=real_matchday,
                    player_scores=matchday_player_scores,
                    starters_count=starters_count,
                    bench_size=bench_size,
                    score_base=score_base,
                    score_scale=score_scale,
                    player_zone_features=matchday_player_zone_features.get(real_matchday, {}),
                    player_intervals=matchday_player_intervals["players"].get(real_matchday, {}),
                    player_final_seconds=matchday_player_intervals["player_final_seconds"].get(real_matchday, {}),
                    matchday_final_seconds=matchday_player_intervals["final_seconds"].get(real_matchday, 90 * 60),
                    temporal_substitutions=not bool(options["disable_temporal_substitutions"]),
                    goalkeepers=goalkeepers,
                    season_footprints=season_footprints,
                )
                vector_report = None
                if scoring_mode == "vector":
                    home_score, away_score, vector_report = self._vector_fixture_scores(
                        home_result["_zone_vectors"],
                        away_result["_zone_vectors"],
                        vector_calibration,
                        home_players=home_result.get("_player_vectors", []),
                        away_players=away_result.get("_player_vectors", []),
                        fantasy_home_advantage=fantasy_home_advantage,
                        fantasy_margin_boost=fantasy_margin_boost,
                    )
                    home_result["score"] = home_score
                    away_result["score"] = away_score
                    home_result["vector_margin"] = round(vector_report["total_margin"], 6)
                    away_result["vector_margin"] = round(-vector_report["total_margin"], 6)
                home_result.pop("_zone_vectors", None)
                away_result.pop("_zone_vectors", None)
                home_result.pop("_player_vectors", None)
                away_result.pop("_player_vectors", None)
                home_goals = hard_goals(home_result["score"])
                away_goals = hard_goals(away_result["score"])
                self._apply_result(home, away, home_result["score"], away_result["score"], home_goals, away_goals)
                fixture_reports.append(
                    {
                        "fantasy_round": idx,
                        "real_matchday": real_matchday,
                        "home_team": home.name,
                        "away_team": away.name,
                        "home_score": round(home_result["score"], 3),
                        "away_score": round(away_result["score"], 3),
                        "home_goals": home_goals,
                        "away_goals": away_goals,
                        "vector_report": vector_report,
                        "home_lineup": home_result,
                        "away_lineup": away_result,
                    }
                )

        standings = sorted(
            teams,
            key=lambda team: (team.points, team.goals_for - team.goals_against, team.goals_for, team.score_for),
            reverse=True,
        )
        report = {
            "version": "historical_vfoot_league_dry_run_v0",
            "notes": [
                "Artifact-only dry run; does not mutate FantasyLeague/FantasyTeam tables.",
                "Lineups are automatic and use observed player matchday data.",
                "Vector mode compares fantasy team zone vectors with calibrated vector_zone_duel_v1 weights.",
                "Bench substitution mode 1 and interval-window scoring are still simplified in this scaffold.",
            ],
            "config": {
                "teams": team_count,
                "budget": budget,
                "squad_size": squad_size,
                "starters": starters_count,
                "bench_size": bench_size,
                "matchdays": len(matchdays),
                "seed": seed,
                "score_base": score_base,
                "score_scale": score_scale,
                "scoring_mode": scoring_mode,
                "vector_calibration": str(options["vector_calibration"]) if scoring_mode == "vector" else None,
                "fantasy_home_advantage": fantasy_home_advantage,
                "fantasy_margin_boost": fantasy_margin_boost,
                "temporal_substitutions": not bool(options["disable_temporal_substitutions"]),
            },
            "player_pool_size": len(pool),
            "teams": [
                {
                    "id": team.id,
                    "name": team.name,
                    "spent": team.spent,
                    "remaining_budget": team.remaining_budget,
                    "roster_size": len(team.roster),
                    "top_players": [
                        {
                            "player_id": player.player_id,
                            "name": player.name,
                            "price": player.price,
                            "value": round(player.value, 3),
                        }
                        for player in sorted(team.roster, key=lambda p: p.value, reverse=True)[:5]
                    ],
                }
                for team in teams
            ],
            "fixtures": fixture_reports,
            "standings": [
                {
                    "rank": rank,
                    "team": team.name,
                    "points": team.points,
                    "played": team.played,
                    "wins": team.wins,
                    "draws": team.draws,
                    "losses": team.losses,
                    "goals_for": team.goals_for,
                    "goals_against": team.goals_against,
                    "goal_diff": team.goals_for - team.goals_against,
                    "avg_score_for": round(team.score_for / team.played, 3) if team.played else 0.0,
                }
                for rank, team in enumerate(standings, start=1)
            ],
        }

        out_path = Path(str(options["output"]))
        if not out_path.is_absolute():
            out_path = Path.cwd().parent / out_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report, separators=(",", ":"), sort_keys=True) + "\n", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Wrote {out_path}"))
        self.stdout.write(
            self.style.SUCCESS(
                f"Simulated {len(matchdays)} matchdays, {len(fixture_reports)} fixtures, winner={standings[0].name}"
            )
        )

    def _matchdays(self, limit: int) -> list[int]:
        values = list(
            Match.objects.filter(matchday__isnull=False)
            .order_by("matchday")
            .values_list("matchday", flat=True)
            .distinct()
        )
        if limit > 0:
            values = values[:limit]
        return [int(v) for v in values]

    def _player_pool(self, *, min_appearances: int) -> list[PoolPlayer]:
        appearance_rows = (
            MatchAppearance.objects.values("player_id", "player__short_name", "player__full_name")
            .annotate(appearances=Count("id"), minutes=Sum("minutes_played"))
            .filter(appearances__gte=min_appearances)
        )
        feature_totals = self._player_feature_totals()
        pool = []
        for row in appearance_rows:
            player_id = int(row["player_id"])
            totals = feature_totals.get(player_id)
            if not totals:
                continue
            value = self._feature_value(totals) + 0.01 * float(row["minutes"] or 0)
            if value <= 0:
                continue
            starts = MatchAppearance.objects.filter(player_id=player_id, is_starter=True).count()
            pool.append(
                PoolPlayer(
                    player_id=player_id,
                    name=row["player__short_name"] or row["player__full_name"] or str(player_id),
                    appearances=int(row["appearances"] or 0),
                    starts=starts,
                    minutes=int(row["minutes"] or 0),
                    value=value,
                    price=max(1, int(round(math.sqrt(value)))),
                )
            )
        pool.sort(key=lambda player: (player.value, player.minutes), reverse=True)
        return pool

    def _goalkeepers(self) -> set[int]:
        # A player is a goalkeeper if their dominant lineup position is Goalkeeper.
        counts: dict[int, Counter] = defaultdict(Counter)
        for player_id, source_position in (
            PlayerOnPitchInterval.objects.exclude(source_position="").values_list("player_id", "source_position")
        ):
            counts[int(player_id)][str(source_position)] += 1
        return {pid for pid, c in counts.items() if c.most_common(1)[0][0] == "Goalkeeper"}

    def _player_season_footprints(self) -> dict[int, dict[str, float]]:
        # Normalized presence over zones (sum=1) from season touches; used as the
        # player's EXPECTED spatial footprint for overcrowding-aware selection.
        raw: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for player_id, zone_key, value in PlayerZoneFeature.objects.filter(feature_key="touches").values_list(
            "player_id", "zone_key", "value"
        ):
            raw[int(player_id)][str(zone_key)] += float(value or 0.0)
        footprints: dict[int, dict[str, float]] = {}
        for player_id, zones in raw.items():
            total = sum(zones.values())
            if total > 0:
                footprints[player_id] = {z: v / total for z, v in zones.items()}
        return footprints

    def _select_lineup(
        self,
        roster: list[PoolPlayer],
        starters_count: int,
        bench_size: int,
        *,
        goalkeepers: set[int],
        footprints: dict[int, dict[str, float]],
        overcrowd_weight: float = 0.6,
    ) -> tuple[list[PoolPlayer], list[PoolPlayer]]:
        """User-emulating pick: best players by value, but penalizing crowding the
        same pitch zones (encourages even coverage), with at most one goalkeeper.
        """
        gks = [p for p in roster if p.player_id in goalkeepers]
        outfield = [p for p in roster if p.player_id not in goalkeepers]
        max_value = max((p.value for p in roster), default=1.0) or 1.0

        starters: list[PoolPlayer] = []
        load: dict[str, float] = defaultdict(float)

        def add(player: PoolPlayer):
            starters.append(player)
            for zone, presence in footprints.get(player.player_id, {}).items():
                load[zone] += presence

        # Exactly one goalkeeper (the best available) — never two.
        if gks and starters_count > 0:
            add(max(gks, key=lambda p: p.value))

        remaining = list(outfield)
        while len(starters) < starters_count and remaining:
            selected_so_far = max(1, len(starters))
            best = None
            best_score = None
            for player in remaining:
                fp = footprints.get(player.player_id, {})
                crowd = sum(presence * load.get(zone, 0.0) for zone, presence in fp.items()) / selected_so_far
                score = player.value / max_value - overcrowd_weight * crowd
                if best_score is None or score > best_score:
                    best_score = score
                    best = player
            add(best)
            remaining.remove(best)

        # Bench = ordered reserves: best remaining players by value, INCLUDING a
        # backup goalkeeper so the engine can cover the starting keeper if absent.
        # (Only one GK ever STARTS; the reserve enters only to replace the keeper.)
        selected_ids = {p.player_id for p in starters}
        reserves = sorted(
            (p for p in roster if p.player_id not in selected_ids),
            key=lambda p: p.value,
            reverse=True,
        )
        bench = reserves[:bench_size]
        reserve_gks = [p for p in reserves if p.player_id in goalkeepers]
        if bench_size > 0 and reserve_gks and not any(p.player_id in goalkeepers for p in bench):
            # guarantee a backup keeper: swap in the best reserve GK for the weakest bench slot
            bench = sorted(bench[:-1] + reserve_gks[:1], key=lambda p: p.value, reverse=True)
        return starters, bench

    def _player_feature_totals(self) -> dict[int, dict[str, float]]:
        totals: dict[int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        for player_id, feature_key, value in PlayerZoneFeature.objects.filter(feature_key__in=FEATURE_WEIGHTS).values_list(
            "player_id",
            "feature_key",
            "value",
        ):
            totals[int(player_id)][str(feature_key)] += float(value or 0.0)
        return totals

    def _matchday_player_scores(self) -> dict[int, dict[int, float]]:
        matchday_by_match = dict(Match.objects.values_list("id", "matchday"))
        scores: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))
        for match_id, player_id, feature_key, value in PlayerZoneFeature.objects.filter(feature_key__in=FEATURE_WEIGHTS).values_list(
            "match_id",
            "player_id",
            "feature_key",
            "value",
        ):
            matchday = matchday_by_match.get(match_id)
            if matchday is None:
                continue
            scores[int(matchday)][int(player_id)] += FEATURE_WEIGHTS[str(feature_key)] * float(value or 0.0)
        return scores

    def _matchday_player_zone_features(self) -> dict[int, dict[int, dict[str, dict[str, float]]]]:
        matchday_by_match = dict(Match.objects.values_list("id", "matchday"))
        data: dict[int, dict[int, dict[str, dict[str, float]]]] = defaultdict(
            lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
        )
        for match_id, player_id, zone_key, feature_key, value in PlayerZoneFeature.objects.filter(
            feature_key__in=FEATURE_WEIGHTS
        ).values_list("match_id", "player_id", "zone_key", "feature_key", "value"):
            matchday = matchday_by_match.get(match_id)
            if matchday is None:
                continue
            data[int(matchday)][int(player_id)][str(zone_key)][str(feature_key)] += float(value or 0.0)
        return data

    def _matchday_player_intervals(self) -> dict[str, dict]:
        matchday_by_match = dict(Match.objects.values_list("id", "matchday"))
        players: dict[int, dict[int, list[dict]]] = defaultdict(lambda: defaultdict(list))
        final_seconds: dict[int, int] = defaultdict(lambda: 90 * 60)
        player_final_seconds: dict[int, dict[int, int]] = defaultdict(dict)
        for row in PlayerOnPitchInterval.objects.values(
            "match_id",
            "player_id",
            "start_elapsed_seconds",
            "end_elapsed_seconds",
            "end_reason",
        ):
            matchday = matchday_by_match.get(row["match_id"])
            if matchday is None:
                continue
            start = int(row["start_elapsed_seconds"])
            end = int(row["end_elapsed_seconds"])
            if end <= start:
                continue
            players[int(matchday)][int(row["player_id"])].append(
                {
                    "start": start,
                    "end": end,
                    "end_reason": str(row["end_reason"]),
                }
            )
            final_seconds[int(matchday)] = max(final_seconds[int(matchday)], end)
            current_player_final = player_final_seconds[int(matchday)].get(int(row["player_id"]), 90 * 60)
            player_final_seconds[int(matchday)][int(row["player_id"])] = max(current_player_final, end)
        for player_map in players.values():
            for intervals in player_map.values():
                intervals.sort(key=lambda item: (item["start"], item["end"]))
        return {"players": players, "final_seconds": final_seconds, "player_final_seconds": player_final_seconds}

    def _load_vector_calibration(self, path: str) -> dict:
        calibration_path = Path(path)
        if not calibration_path.is_absolute():
            calibration_path = Path.cwd().parent / calibration_path
        if not calibration_path.exists():
            raise CommandError(f"Vector calibration not found: {calibration_path}")
        return json.loads(calibration_path.read_text(encoding="utf-8"))

    def _feature_value(self, totals: dict[str, float]) -> float:
        return sum(FEATURE_WEIGHTS[key] * float(totals.get(key, 0.0)) for key in FEATURE_WEIGHTS)

    def _assign_rosters(self, teams: list[SimTeam], pool: list[PoolPlayer], *, squad_size: int):
        ordered_teams = list(teams)
        player_idx = 0
        for round_idx in range(squad_size):
            direction = ordered_teams if round_idx % 2 == 0 else list(reversed(ordered_teams))
            for team in direction:
                while player_idx < len(pool) and pool[player_idx].price > team.remaining_budget:
                    player_idx += 1
                if player_idx >= len(pool):
                    raise CommandError("Ran out of affordable players during roster assignment.")
                player = pool[player_idx]
                team.roster.append(player)
                team.spent += player.price
                player_idx += 1

    def _lineup_and_score(
        self,
        team: SimTeam,
        *,
        real_matchday: int,
        player_scores: dict[int, dict[int, float]],
        starters_count: int,
        bench_size: int,
        score_base: float,
        score_scale: float,
        player_zone_features: dict[int, dict[str, dict[str, float]]],
        player_intervals: dict[int, list[dict]],
        player_final_seconds: dict[int, int],
        matchday_final_seconds: int,
        temporal_substitutions: bool,
        goalkeepers: set[int],
        season_footprints: dict[int, dict[str, float]],
    ) -> dict:
        scores = player_scores.get(real_matchday, {})
        # Emulate a user picking their lineup BEFORE the match: best players by
        # value, penalizing pitch-zone overcrowding (even coverage) and allowing
        # at most one goalkeeper — with NO knowledge of who will actually play
        # that day, so the manager can "get it wrong". (event_score below is the
        # that-day value only for display, not for selection.)
        starter_players, bench_players = self._select_lineup(
            team.roster,
            starters_count,
            bench_size,
            goalkeepers=goalkeepers,
            footprints=season_footprints,
        )
        starters = [(player, scores.get(player.player_id, 0.0)) for player in starter_players]
        bench = [(player, scores.get(player.player_id, 0.0)) for player in bench_players]
        raw_sum = sum(score for _, score in starters)
        avg_event_score = raw_sum / max(1.0, starters_count)
        score = score_base + score_scale * avg_event_score
        if temporal_substitutions:
            zone_vectors, substitution_report, player_vectors = self._temporal_team_zone_vectors(
                starters=[player for player, _ in starters],
                bench=[player for player, _ in bench],
                player_zone_features=player_zone_features,
                player_intervals=player_intervals,
                player_final_seconds=player_final_seconds,
                matchday_final_seconds=matchday_final_seconds,
            )
        else:
            zone_vectors, player_vectors = self._team_zone_vectors(
                [player for player, _ in starters], player_zone_features
            )
            substitution_report = {
                "mode": "disabled",
                "substitutions": [],
                "covered_gap_seconds": 0,
                "uncovered_gap_seconds": 0,
                "disciplinary_gap_seconds": 0,
            }
        return {
            "score": score,
            "raw_event_sum": round(raw_sum, 3),
            "avg_event_score": round(avg_event_score, 3),
            "available_players": sum(1 for player in team.roster if scores.get(player.player_id, 0.0) > 0),
            "starter_count": len(starters),
            "bench_count": len(bench),
            "starters": [
                {"player_id": player.player_id, "name": player.name, "event_score": round(player_score, 3)}
                for player, player_score in starters
            ],
            "bench": [
                {"player_id": player.player_id, "name": player.name, "event_score": round(player_score, 3)}
                for player, player_score in bench
            ],
            "substitution_report": substitution_report,
            "_zone_vectors": zone_vectors,
            "_player_vectors": player_vectors,
        }

    def _team_zone_vectors(
        self,
        players: list[PoolPlayer],
        player_zone_features: dict[int, dict[str, dict[str, float]]],
    ) -> tuple[dict[str, dict[str, float]], list[dict]]:
        vectors: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        player_vectors: list[dict] = []
        for player in players:
            pv: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
            for zone_key, features in player_zone_features.get(player.player_id, {}).items():
                for feature_key, value in features.items():
                    vectors[zone_key][feature_key] += float(value)
                    pv[zone_key][feature_key] += float(value)
            if pv:
                player_vectors.append(
                    {
                        "player_id": player.player_id,
                        "name": player.name,
                        "vectors": {z: dict(f) for z, f in pv.items()},
                    }
                )
        return vectors, player_vectors

    def _temporal_team_zone_vectors(
        self,
        *,
        starters: list[PoolPlayer],
        bench: list[PoolPlayer],
        player_zone_features: dict[int, dict[str, dict[str, float]]],
        player_intervals: dict[int, list[dict]],
        player_final_seconds: dict[int, int],
        matchday_final_seconds: int,
    ) -> tuple[dict[str, dict[str, float]], dict, list[dict]]:
        vectors: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        player_vectors_map: dict[int, dict] = {}
        substitutions = []
        used_bench: set[int] = set()
        covered_gap_seconds = 0
        uncovered_gap_seconds = 0
        disciplinary_gap_seconds = 0

        for starter in starters:
            starter_intervals = player_intervals.get(starter.player_id, [])
            starter_final_seconds = player_final_seconds.get(starter.player_id, matchday_final_seconds)
            active_seconds = self._active_seconds(starter_intervals)
            if active_seconds > 0:
                self._add_scaled_player_features(
                    vectors,
                    player_zone_features.get(starter.player_id, {}),
                    scale=1.0,
                    player=starter,
                    player_vectors_map=player_vectors_map,
                )

            gaps = self._player_gaps(starter_intervals, starter_final_seconds)
            for gap_start, gap_end, is_disciplinary, gap_kind in gaps:
                gap_seconds = max(0, gap_end - gap_start)
                if gap_seconds <= 0:
                    continue
                if is_disciplinary:
                    disciplinary_gap_seconds += gap_seconds
                    uncovered_gap_seconds += gap_seconds
                    substitutions.append(
                        {
                            "starter": starter.name,
                            "starter_id": starter.player_id,
                            "gap": [gap_start, gap_end],
                            "gap_kind": gap_kind,
                            "covered": False,
                            "reason": "disciplinary_gap",
                        }
                    )
                    continue

                candidate = self._best_bench_candidate(
                    bench=bench,
                    used_bench=used_bench,
                    gap_start=gap_start,
                    gap_end=gap_end,
                    player_intervals=player_intervals,
                )
                if candidate is None:
                    uncovered_gap_seconds += gap_seconds
                    substitutions.append(
                        {
                            "starter": starter.name,
                            "starter_id": starter.player_id,
                            "gap": [gap_start, gap_end],
                            "gap_kind": gap_kind,
                            "covered": False,
                            "reason": "no_bench_overlap",
                        }
                    )
                    continue

                bench_player, overlap_seconds, bench_active_seconds = candidate
                used_bench.add(bench_player.player_id)
                covered_gap_seconds += overlap_seconds
                uncovered_gap_seconds += max(0, gap_seconds - overlap_seconds)
                self._add_scaled_player_features(
                    vectors,
                    player_zone_features.get(bench_player.player_id, {}),
                    scale=overlap_seconds / max(1, bench_active_seconds),
                    player=bench_player,
                    player_vectors_map=player_vectors_map,
                )
                substitutions.append(
                    {
                        "starter": starter.name,
                        "starter_id": starter.player_id,
                        "bench": bench_player.name,
                        "bench_id": bench_player.player_id,
                        "gap": [gap_start, gap_end],
                        "gap_kind": gap_kind,
                        "covered": True,
                        "covered_seconds": overlap_seconds,
                        "gap_seconds": gap_seconds,
                    }
                )

        player_vectors = [
            {"player_id": pid, "name": rec["name"], "vectors": {z: dict(f) for z, f in rec["vectors"].items()}}
            for pid, rec in player_vectors_map.items()
        ]
        return (
            vectors,
            {
                "mode": "auto_mode_1_temporal_scaled",
                "substitutions": substitutions,
                "covered_gap_seconds": covered_gap_seconds,
                "uncovered_gap_seconds": uncovered_gap_seconds,
                "disciplinary_gap_seconds": disciplinary_gap_seconds,
                "used_bench_count": len(used_bench),
            },
            player_vectors,
        )

    def _add_scaled_player_features(
        self,
        vectors: dict[str, dict[str, float]],
        zone_features: dict[str, dict[str, float]],
        *,
        scale: float,
        player: PoolPlayer | None = None,
        player_vectors_map: dict[int, dict] | None = None,
    ):
        if scale <= 0:
            return
        pv = None
        if player is not None and player_vectors_map is not None:
            pv = player_vectors_map.setdefault(
                player.player_id,
                {"name": player.name, "vectors": defaultdict(lambda: defaultdict(float))},
            )["vectors"]
        for zone_key, features in zone_features.items():
            for feature_key, value in features.items():
                scaled = float(value) * scale
                vectors[zone_key][feature_key] += scaled
                if pv is not None:
                    pv[zone_key][feature_key] += scaled

    def _active_seconds(self, intervals: list[dict]) -> int:
        return sum(max(0, int(item["end"]) - int(item["start"])) for item in intervals)

    def _player_gaps(self, intervals: list[dict], final_seconds: int) -> list[tuple[int, int, bool, str]]:
        # Returns (start, end, is_disciplinary, kind). We only treat a gap as a
        # real lineup change worth covering when it matches a substitution
        # category — not when a player merely steps off and returns:
        #   - 'pre_entry'  : player came on after kickoff (subentrato)
        #   - 'post_exit'  : player left for good via substitution or was sent off
        # A player who exits and later re-enters (e.g. injury treatment) is NOT
        # substituted: that intermediate window is ignored regardless of length.
        disciplinary_reasons = {"red_card", "second_yellow"}
        # Picked starter who never appeared this matchday: absent the whole game,
        # coverable by a bench player (a realistic lineup mistake).
        if not intervals:
            return [(0, final_seconds, False, "absent")]
        gaps: list[tuple[int, int, bool, str]] = []
        cursor = 0
        last_end_reason: str | None = None
        for interval in intervals:
            start = int(interval["start"])
            end = int(interval["end"])
            # Pre-entry gap only: a gap that opens between two intervals means the
            # player returned, so it is a temporary absence and is skipped.
            if start > cursor and cursor == 0:
                gaps.append((cursor, start, False, "pre_entry"))
            cursor = max(cursor, end)
            last_end_reason = interval.get("end_reason")
            if last_end_reason in disciplinary_reasons and cursor < final_seconds:
                gaps.append((cursor, final_seconds, True, "post_exit"))
                return gaps
        # Terminal exit before the final whistle counts only if it was a real
        # substitution (not an unexplained player_off / tactical truncation).
        if cursor < final_seconds and last_end_reason == "substitution_off":
            gaps.append((cursor, final_seconds, False, "post_exit"))
        return gaps

    def _best_bench_candidate(
        self,
        *,
        bench: list[PoolPlayer],
        used_bench: set[int],
        gap_start: int,
        gap_end: int,
        player_intervals: dict[int, list[dict]],
    ) -> tuple[PoolPlayer, int, int] | None:
        best = None
        best_key = None
        for candidate in bench:
            if candidate.player_id in used_bench:
                continue
            intervals = player_intervals.get(candidate.player_id, [])
            active = self._active_seconds(intervals)
            if active <= 0:
                continue
            overlap = 0
            for interval in intervals:
                overlap += max(0, min(gap_end, int(interval["end"])) - max(gap_start, int(interval["start"])))
            if overlap <= 0:
                continue
            key = (overlap, candidate.value)
            if best_key is None or key > best_key:
                best = (candidate, overlap, active)
                best_key = key
        return best

    def _vector_fixture_scores(
        self,
        home_vectors: dict[str, dict[str, float]],
        away_vectors: dict[str, dict[str, float]],
        calibration: dict,
        *,
        home_players: list[dict],
        away_players: list[dict],
        fantasy_home_advantage: float,
        fantasy_margin_boost: float,
    ) -> tuple[float, float, dict]:
        result = score_zone_duel(
            home_vectors,
            away_vectors,
            calibration,
            home_players=home_players,
            away_players=away_players,
            fantasy_home_advantage=fantasy_home_advantage,
            fantasy_margin_boost=fantasy_margin_boost,
        )
        # Keep the artifact compact: store zone margins + the top feature swings,
        # and the per-player zone contributions once (as player_totals). The
        # per-zone player lists are derivable from player_totals on the client,
        # so we strip them here. The shared service still returns them for the
        # future real-time match-detail endpoint.
        zones = [
            {
                "zone_key": z["zone_key"],
                "margin": z["margin"],
                "winner": z["winner"],
                "macros": z["macros"],
                "features": z["features"][:8],
            }
            for z in result["zones"]
        ]
        def compact_player_totals(rows):
            out = []
            for r in rows:
                top_zones = sorted(
                    ((z, c) for z, c in r["zones"].items() if abs(c) >= 0.01),
                    key=lambda item: abs(item[1]),
                    reverse=True,
                )[:8]
                out.append(
                    {
                        "player_id": r["player_id"],
                        "name": r["name"],
                        "total": round(r["total"], 3),
                        "zones": {z: round(c, 3) for z, c in top_zones},
                    }
                )
            return out

        report = {
            "total_margin": result["total_margin"],
            "boosted_margin": result["boosted_margin"],
            "score_build": result["score_build"],
            "zones": zones,
            "home_player_totals": compact_player_totals(result["home_player_totals"]),
            "away_player_totals": compact_player_totals(result["away_player_totals"]),
        }
        return result["home_score"], result["away_score"], report

    def _apply_result(
        self,
        home: SimTeam,
        away: SimTeam,
        home_score: float,
        away_score: float,
        home_goals: int,
        away_goals: int,
    ):
        home.played += 1
        away.played += 1
        home.goals_for += home_goals
        home.goals_against += away_goals
        away.goals_for += away_goals
        away.goals_against += home_goals
        home.score_for += home_score
        home.score_against += away_score
        away.score_for += away_score
        away.score_against += home_score
        if home_goals > away_goals:
            home.points += 3
            home.wins += 1
            away.losses += 1
        elif home_goals < away_goals:
            away.points += 3
            away.wins += 1
            home.losses += 1
        else:
            home.points += 1
            away.points += 1
            home.draws += 1
            away.draws += 1
