from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from django.db import DatabaseError, transaction

from realdata.models import (
    CARD_RED,
    CARD_SECOND_YELLOW,
    CARD_UNKNOWN,
    CARD_YELLOW,
    Competition,
    CompetitionSeason,
    DataIngestionManifest,
    INTERVAL_FINAL_WHISTLE,
    INTERVAL_PLAYER_OFF,
    INTERVAL_PLAYER_ON,
    INTERVAL_RED_CARD,
    INTERVAL_STARTING_XI,
    INTERVAL_SUBSTITUTION_OFF,
    INTERVAL_SUBSTITUTION_ON,
    INTERVAL_TACTICAL_SHIFT,
    INTERVAL_UNKNOWN_END,
    INTERVAL_UNKNOWN_START,
    Match,
    MatchAppearance,
    MatchDisciplinaryEvent,
    Player,
    PlayerOnPitchInterval,
    PlayerZoneFeature,
    PROVIDER_STATSBOMB,
    SIDE_AWAY,
    SIDE_HOME,
    SIDE_UNKNOWN,
    Season,
    Team,
    TeamSeason,
    TeamZoneFeature,
)


PROVIDER = PROVIDER_STATSBOMB
BOX_X_MIN = 102.0 / 120.0
BOX_X_MAX = 18.0 / 120.0
BOX_Y_MIN = 18.0 / 80.0
BOX_Y_MAX = 62.0 / 80.0
WRITE_BATCH_SIZE = 50
WRITE_BATCH_SIZE_FAST = 1000


@dataclass(frozen=True)
class IngestStats:
    matches: int = 0
    teams: int = 0
    players: int = 0
    appearances: int = 0
    player_zone_features: int = 0
    team_zone_features: int = 0
    disciplinary_events: int = 0
    on_pitch_intervals: int = 0

    def add(self, **kwargs: int) -> "IngestStats":
        values = self.__dict__.copy()
        for k, v in kwargs.items():
            values[k] = values.get(k, 0) + int(v)
        return IngestStats(**values)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _season_code(season_name: str) -> str:
    # StatsBomb typical format: "2015/2016"
    return season_name.replace("/", "-")


def _parse_kickoff(match_date: str, kick_off: str | None) -> datetime | None:
    if not match_date:
        return None
    if not kick_off:
        dt = datetime.strptime(match_date, "%Y-%m-%d")
        return dt.replace(tzinfo=timezone.utc)
    # kick_off can be "20:45:00.000"
    time_part = kick_off.split(".")[0]
    dt = datetime.strptime(f"{match_date} {time_part}", "%Y-%m-%d %H:%M:%S")
    return dt.replace(tzinfo=timezone.utc)


def _clamp01(v: float) -> float:
    return min(1.0, max(0.0, v))


def _norm_xy(location: Any) -> tuple[float | None, float | None]:
    if not isinstance(location, list) or len(location) < 2:
        return None, None
    x = _clamp01(float(location[0]) / 120.0)
    y = _clamp01(float(location[1]) / 80.0)
    return x, y


def _zone_key(x: float, y: float, cols: int, rows: int) -> str:
    col = min(cols - 1, max(0, int(x * cols)))
    row = min(rows - 1, max(0, int(y * rows)))
    return f"Z_{col}_{row}"


def _is_box_coord(x: float | None, y: float | None) -> bool:
    if x is None or y is None:
        return False
    in_right = x >= BOX_X_MIN
    in_left = x <= BOX_X_MAX
    in_y = BOX_Y_MIN <= y <= BOX_Y_MAX
    return in_y and (in_right or in_left)


def _infer_success(event: dict[str, Any], event_type_name: str) -> bool | None:
    t = event_type_name.lower()
    detail = event.get(t)
    if not isinstance(detail, dict):
        return None

    outcome = detail.get("outcome")
    outcome_name = ""
    if isinstance(outcome, dict):
        outcome_name = str(outcome.get("name", "")).lower()

    if t == "pass":
        return outcome is None
    if t == "shot":
        if outcome_name:
            return outcome_name in {"goal", "saved", "saved to post"}
        return None
    if t == "duel":
        return "won" in outcome_name if outcome_name else None
    if t == "dribble":
        if outcome_name:
            return "complete" in outcome_name
        return None
    return None


def _event_end_xy(event: dict[str, Any], event_type_name: str) -> tuple[float | None, float | None]:
    t = event_type_name.lower()
    detail = event.get(t)
    if not isinstance(detail, dict):
        return None, None
    if t in {"pass", "carry", "shot", "dribble"}:
        return _norm_xy(detail.get("end_location"))
    return None, None


def _parse_clock_seconds(v: Any, *, default_seconds: int = 0) -> int:
    if v is None:
        return default_seconds
    if isinstance(v, (int, float)):
        return int(v) * 60
    s = str(v).strip()
    if not s:
        return default_seconds
    if ":" in s:
        mm, ss = (s.split(":", 1) + ["0"])[:2]
        minutes = int(mm) if mm.isdigit() else 0
        seconds = int(ss) if ss.isdigit() else 0
        return minutes * 60 + seconds
    return int(s) * 60 if s.isdigit() else default_seconds


def _clock_parts(seconds: int) -> tuple[int, int]:
    seconds = max(0, int(seconds))
    return seconds // 60, seconds % 60


def _normalise_interval_start_reason(reason: str) -> str:
    value = reason.strip().lower()
    if value.startswith("starting"):
        return INTERVAL_STARTING_XI
    if value.startswith("substitution"):
        return INTERVAL_SUBSTITUTION_ON
    if value.startswith("tactical shift"):
        return INTERVAL_TACTICAL_SHIFT
    if value.startswith("player on"):
        return INTERVAL_PLAYER_ON
    return INTERVAL_UNKNOWN_START


def _normalise_interval_end_reason(reason: str) -> str:
    value = reason.strip().lower()
    if value.startswith("final whistle"):
        return INTERVAL_FINAL_WHISTLE
    if value.startswith("substitution"):
        return INTERVAL_SUBSTITUTION_OFF
    if value.startswith("tactical shift"):
        return INTERVAL_TACTICAL_SHIFT
    if "red card" in value:
        return INTERVAL_RED_CARD
    if value.startswith("player off"):
        return INTERVAL_PLAYER_OFF
    return INTERVAL_UNKNOWN_END

def _match_final_elapsed_seconds(events: list[dict[str, Any]] | None) -> int:
    if not events:
        return 90 * 60
    max_seen = 90 * 60
    for event in events:
        max_seen = max(max_seen, _statsbomb_event_time(event))
    return max_seen


def _extract_minutes_and_starter(positions: list[dict[str, Any]], final_seconds: int = 90 * 60) -> tuple[int, bool]:
    if not positions:
        return 0, False

    intervals: list[tuple[int, int]] = []
    for p in positions:
        start = _parse_clock_seconds(p.get("from", 0), default_seconds=0)
        end = _parse_clock_seconds(p.get("to"), default_seconds=final_seconds)
        if end < start:
            end = start
        intervals.append((start, end))

    starts = [start for start, _ in intervals]
    is_starter = any(str(p.get("start_reason", "")).lower().startswith("starting") for p in positions) or min(starts) == 0

    intervals.sort()
    merged: list[tuple[int, int]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    minutes = round(sum(max(0, end - start) for start, end in merged) / 60)
    return minutes, is_starter


def _statsbomb_event_time(event: dict[str, Any]) -> int:
    return _event_elapsed_seconds(
        int(event.get("period") or 1),
        int(event.get("minute") or 0),
        int(event.get("second") or 0),
    )


def _player_exit_constraints_from_events(events: list[dict[str, Any]]) -> dict[str, tuple[int, str, str]]:
    constraints: dict[str, tuple[int, str, str]] = {}

    def set_constraint(player_ext_id: str, time: int, end_reason: str, source_end_reason: str):
        previous = constraints.get(player_ext_id)
        if previous is None or time < previous[0]:
            constraints[player_ext_id] = (time, end_reason, source_end_reason)

    for event in events:
        event_type_name = str(event.get("type", {}).get("name", ""))
        lower_type = event_type_name.lower()
        player_id_raw = event.get("player", {}).get("id")
        if player_id_raw is None:
            continue
        player_ext_id = str(player_id_raw)
        event_time = _statsbomb_event_time(event)

        if lower_type == "substitution":
            outcome = event.get("substitution", {}).get("outcome", {})
            outcome_name = str(outcome.get("name", "") or "").strip()
            source = f"Substitution - Off ({outcome_name})" if outcome_name else "Substitution - Off"
            set_constraint(player_ext_id, event_time, INTERVAL_SUBSTITUTION_OFF, source)
            continue

        card_payload = _extract_card_payload(event, event_type_name)
        if card_payload is None:
            continue
        card_name, _ = card_payload
        if _normalise_card_type(card_name) in {CARD_RED, CARD_SECOND_YELLOW}:
            set_constraint(player_ext_id, event_time, INTERVAL_RED_CARD, card_name)
    return constraints


def _on_pitch_intervals_from_positions(
    *,
    positions: list[dict[str, Any]],
    match_obj: Match,
    player: Player,
    team_season: TeamSeason,
    side: str,
    provider_player_id: str,
    exit_constraints: dict[str, tuple[int, str, str]] | None = None,
    final_seconds: int = 90 * 60,
) -> list[PlayerOnPitchInterval]:
    rows: list[PlayerOnPitchInterval] = []
    exit_constraint = (exit_constraints or {}).get(provider_player_id)
    for idx, position in enumerate(positions):
        start_elapsed = _parse_clock_seconds(position.get("from", 0), default_seconds=0)
        end_elapsed = _parse_clock_seconds(position.get("to"), default_seconds=final_seconds)
        source_end_override = None
        end_reason_override = None
        if exit_constraint is not None:
            exit_time, exit_reason, exit_source = exit_constraint
            if start_elapsed >= exit_time:
                continue
            if end_elapsed > exit_time:
                end_elapsed = exit_time
                end_reason_override = exit_reason
                source_end_override = exit_source
        if end_elapsed < start_elapsed:
            end_elapsed = start_elapsed
        if end_elapsed <= start_elapsed:
            continue
        start_minute, start_second = _clock_parts(start_elapsed)
        end_minute, end_second = _clock_parts(end_elapsed)
        source_start_reason = str(position.get("start_reason", "") or "")
        source_end_reason = source_end_override or str(position.get("end_reason", "") or "")
        rows.append(
            PlayerOnPitchInterval(
                match=match_obj,
                player=player,
                team_season=team_season,
                team_side=side,
                start_period=int(position.get("from_period") or 1),
                start_minute=start_minute,
                start_second=start_second,
                start_elapsed_seconds=start_elapsed,
                end_period=position.get("to_period"),
                end_minute=end_minute,
                end_second=end_second,
                end_elapsed_seconds=end_elapsed,
                start_reason=_normalise_interval_start_reason(source_start_reason),
                end_reason=end_reason_override or _normalise_interval_end_reason(source_end_reason),
                source_start_reason=source_start_reason,
                source_end_reason=source_end_reason,
                source_position=str(position.get("position", "") or ""),
                provider=PROVIDER,
                provider_interval_id=f"{match_obj.external_id}:{provider_player_id}:{idx}",
                payload={
                    "source": position,
                },
            )
        )
    return rows


def _key_pass(event: dict[str, Any]) -> bool:
    p = event.get("pass")
    if not isinstance(p, dict):
        return False
    return bool(p.get("shot_assist") or p.get("assisted_shot_id") or p.get("goal_assist"))


def _progressive(x: float | None, x_end: float | None) -> bool:
    if x is None or x_end is None:
        return False
    return abs(x_end - x) >= 0.15


def _normalise_card_type(card_name: str) -> str:
    value = card_name.strip().lower()
    if value == "yellow card":
        return CARD_YELLOW
    if value == "second yellow":
        return CARD_SECOND_YELLOW
    if value == "red card":
        return CARD_RED
    return CARD_UNKNOWN


def _event_elapsed_seconds(period: int, minute: int, second: int) -> int:
    # StatsBomb minute is a match-clock minute; keep this provider-agnostic
    # enough for ordering while preserving period/minute/second separately.
    return max(0, int(minute)) * 60 + max(0, int(second))


def _extract_card_payload(event: dict[str, Any], event_type_name: str) -> tuple[str, dict[str, Any]] | None:
    lower_type = event_type_name.lower()
    if lower_type == "foul committed":
        payload = event.get("foul_committed")
    elif lower_type == "bad behaviour":
        payload = event.get("bad_behaviour")
    else:
        return None
    if not isinstance(payload, dict):
        return None
    card = payload.get("card")
    if not isinstance(card, dict):
        return None
    card_name = str(card.get("name", "")).strip()
    if not card_name:
        return None
    return card_name, payload


def _disciplinary_row_from_statsbomb_event(
    *,
    event: dict[str, Any],
    event_type_name: str,
    match_obj: Match,
    home_team_ext_id: str,
    away_team_ext_id: str,
    team_cache: dict[str, TeamSeason],
    player_cache: dict[str, Player],
    fallback_index: int,
) -> MatchDisciplinaryEvent | None:
    team_id_raw = event.get("team", {}).get("id")
    team_ext_id = str(team_id_raw) if team_id_raw is not None else ""
    if team_ext_id == home_team_ext_id:
        side = SIDE_HOME
    elif team_ext_id == away_team_ext_id:
        side = SIDE_AWAY
    else:
        side = SIDE_UNKNOWN
    if side == SIDE_UNKNOWN:
        return None

    card_payload = _extract_card_payload(event, event_type_name)
    if card_payload is None:
        return None
    card_name, source_payload = card_payload

    player_obj: Player | None = None
    player_id_raw = event.get("player", {}).get("id")
    if player_id_raw is not None:
        player_ext_id = str(player_id_raw)
        player_obj = player_cache.get(player_ext_id)
        if not player_obj:
            player_obj = Player.objects.create(
                full_name=str(event.get("player", {}).get("name", f"SB-{player_ext_id}")),
                short_name=str(event.get("player", {}).get("name", f"SB-{player_ext_id}")),
                external_source=PROVIDER,
                external_id=player_ext_id,
            )
            player_cache[player_ext_id] = player_obj

    period = int(event.get("period") or 1)
    minute = int(event.get("minute") or 0)
    second = int(event.get("second") or 0)
    provider_event_id = str(event.get("id") or f"{match_obj.external_id}:disciplinary:{fallback_index}")
    return MatchDisciplinaryEvent(
        match=match_obj,
        player=player_obj,
        team_season=team_cache.get(team_ext_id),
        team_side=side,
        period=period,
        minute=minute,
        second=second,
        elapsed_seconds=_event_elapsed_seconds(period, minute, second),
        card_type=_normalise_card_type(card_name),
        reason=event_type_name,
        provider=PROVIDER,
        provider_event_id=provider_event_id,
        source_event_type=event_type_name,
        source_card_name=card_name,
        payload={
            "source": source_payload,
        },
    )


def ingest_statsbomb(
    dataset_root: Path,
    *,
    matches_file: str = "matches_12_27.json",
    events_dir: str = "events",
    lineups_dir: str = "lineups",
    limit_matches: int | None = None,
    zone_cols: int = 5,
    zone_rows: int = 4,
    include_events: bool = True,
    safe_writes: bool = False,
    data_version: str = "unknown",
    formula_version: str = "features_v1",
) -> IngestStats:
    stats = IngestStats()

    matches_path = dataset_root / matches_file
    events_path = dataset_root / events_dir
    lineups_path = dataset_root / lineups_dir

    matches_data = _load_json(matches_path)
    if limit_matches is not None:
        matches_data = matches_data[: max(0, limit_matches)]

    if not matches_data:
        return stats

    season_name = str(matches_data[0].get("season", {}).get("season_name", "unknown"))
    competition_name = str(matches_data[0].get("competition", {}).get("competition_name", "Unknown Competition"))
    competition_country = str(matches_data[0].get("competition", {}).get("country_name", ""))
    competition_external_id = str(matches_data[0].get("competition", {}).get("competition_id", ""))

    with transaction.atomic():
        competition, _ = Competition.objects.get_or_create(
            external_source=PROVIDER,
            external_id=competition_external_id,
            defaults={"name": competition_name, "country": competition_country},
        )
        if competition.name != competition_name or competition.country != competition_country:
            competition.name = competition_name
            competition.country = competition_country
            competition.save(update_fields=["name", "country"])

        season, _ = Season.objects.get_or_create(code=_season_code(season_name))
        competition_season, _ = CompetitionSeason.objects.get_or_create(
            competition=competition,
            season=season,
            defaults={"name": f"{competition_name} {season_name}", "num_rounds": 38},
        )

    team_cache: dict[str, TeamSeason] = {}
    player_cache: dict[str, Player] = {
        str(p.external_id): p for p in Player.objects.filter(external_source=PROVIDER)
    }

    for m in matches_data:
        home = m.get("home_team", {})
        away = m.get("away_team", {})
        week = m.get("match_week")

        home_team_ext_id = str(home.get("home_team_id"))
        away_team_ext_id = str(away.get("away_team_id"))

        home_team, home_created = Team.objects.get_or_create(
            external_source=PROVIDER,
            external_id=home_team_ext_id,
            defaults={"name": str(home.get("home_team_name", home_team_ext_id))},
        )
        if home_created:
            stats = stats.add(teams=1)

        away_team, away_created = Team.objects.get_or_create(
            external_source=PROVIDER,
            external_id=away_team_ext_id,
            defaults={"name": str(away.get("away_team_name", away_team_ext_id))},
        )
        if away_created:
            stats = stats.add(teams=1)

        home_team_season, _ = TeamSeason.objects.get_or_create(competition_season=competition_season, team=home_team)
        away_team_season, _ = TeamSeason.objects.get_or_create(competition_season=competition_season, team=away_team)
        team_cache[home_team_ext_id] = home_team_season
        team_cache[away_team_ext_id] = away_team_season

        kickoff = _parse_kickoff(str(m.get("match_date", "")), m.get("kick_off"))
        match_obj, created = Match.objects.get_or_create(
            external_source=PROVIDER,
            external_id=str(m.get("match_id")),
            defaults={
                "competition_season": competition_season,
                "matchday": int(week) if week is not None else None,
                "kickoff": kickoff,
                "home_team": home_team_season,
                "away_team": away_team_season,
                "home_goals": m.get("home_score"),
                "away_goals": m.get("away_score"),
            },
        )
        if created:
            stats = stats.add(matches=1)
        else:
            changed = False
            for field, value in (
                ("competition_season", competition_season),
                ("matchday", int(week) if week is not None else None),
                ("kickoff", kickoff),
                ("home_team", home_team_season),
                ("away_team", away_team_season),
                ("home_goals", m.get("home_score")),
                ("away_goals", m.get("away_score")),
            ):
                if getattr(match_obj, field) != value:
                    setattr(match_obj, field, value)
                    changed = True
            if changed:
                match_obj.save()

        match_id = str(m.get("match_id"))
        events_file = events_path / f"{match_id}.json"
        events_data = _load_json(events_file) if events_file.exists() else None
        final_seconds = _match_final_elapsed_seconds(events_data)
        interval_exit_constraints = {}
        if events_data is not None:
            interval_exit_constraints = _player_exit_constraints_from_events(events_data)

        lineup_file = lineups_path / f"{match_id}.json"
        if lineup_file.exists():
            stats = _ingest_lineups(
                lineup_file,
                match_obj=match_obj,
                home_team_ext_id=home_team_ext_id,
                away_team_ext_id=away_team_ext_id,
                team_cache=team_cache,
                player_cache=player_cache,
                exit_constraints=interval_exit_constraints,
                final_seconds=final_seconds,
                stats=stats,
            )

        if include_events:
            if events_file.exists():
                stats = _ingest_events_and_features(
                    events_file,
                    match_obj=match_obj,
                    home_team_ext_id=home_team_ext_id,
                    away_team_ext_id=away_team_ext_id,
                    team_cache=team_cache,
                    player_cache=player_cache,
                    zone_cols=zone_cols,
                    zone_rows=zone_rows,
                    safe_writes=safe_writes,
                    data_version=data_version,
                    formula_version=formula_version,
                    stats=stats,
                )

    DataIngestionManifest.objects.update_or_create(
        provider=PROVIDER,
        dataset_key="serie_a_statsbomb",
        data_version=data_version,
        formula_version=formula_version,
        defaults={
            "source_path": str(dataset_root),
            "notes": "feature-only import (raw events stored outside DB)",
        },
    )

    return stats


def import_statsbomb_disciplinary_events(
    dataset_root: Path,
    *,
    events_dir: str = "events",
    limit_matches: int | None = None,
    safe_writes: bool = False,
) -> IngestStats:
    events_path = dataset_root / events_dir
    stats = IngestStats()
    matches = list(
        Match.objects.filter(external_source=PROVIDER)
        .select_related("home_team__team", "away_team__team")
        .order_by("id")
    )
    if limit_matches is not None:
        matches = matches[: max(0, limit_matches)]

    player_cache: dict[str, Player] = {
        str(p.external_id): p for p in Player.objects.filter(external_source=PROVIDER)
    }
    write_batch_size = WRITE_BATCH_SIZE if safe_writes else WRITE_BATCH_SIZE_FAST

    def safe_insert_rows(rows: list[Any]) -> int:
        if not rows:
            return 0
        inserted = 0
        for row in rows:
            try:
                row.save(force_insert=True)
                inserted += 1
            except Exception:
                continue
        return inserted

    for match_obj in matches:
        events_file = events_path / f"{match_obj.external_id}.json"
        if not events_file.exists():
            continue

        home_team_ext_id = str(match_obj.home_team.team.external_id)
        away_team_ext_id = str(match_obj.away_team.team.external_id)
        team_cache = {
            home_team_ext_id: match_obj.home_team,
            away_team_ext_id: match_obj.away_team,
        }

        events = _load_json(events_file)
        rows: list[MatchDisciplinaryEvent] = []
        for event in events:
            event_type_name = str(event.get("type", {}).get("name", "unknown"))
            row = _disciplinary_row_from_statsbomb_event(
                event=event,
                event_type_name=event_type_name,
                match_obj=match_obj,
                home_team_ext_id=home_team_ext_id,
                away_team_ext_id=away_team_ext_id,
                team_cache=team_cache,
                player_cache=player_cache,
                fallback_index=len(rows),
            )
            if row is not None:
                rows.append(row)

        MatchDisciplinaryEvent.objects.filter(match=match_obj, provider=PROVIDER).delete()
        inserted = 0
        if rows:
            if not safe_writes:
                MatchDisciplinaryEvent.objects.bulk_create(
                    rows,
                    batch_size=write_batch_size,
                    ignore_conflicts=True,
                )
                inserted = len(rows)
            else:
                try:
                    MatchDisciplinaryEvent.objects.bulk_create(
                        rows,
                        batch_size=write_batch_size,
                        ignore_conflicts=True,
                    )
                    inserted = len(rows)
                except DatabaseError:
                    inserted = safe_insert_rows(rows)
        stats = stats.add(matches=1, disciplinary_events=inserted)

    return stats


def import_statsbomb_on_pitch_intervals(
    dataset_root: Path,
    *,
    lineups_dir: str = "lineups",
    events_dir: str = "events",
    limit_matches: int | None = None,
) -> IngestStats:
    lineups_path = dataset_root / lineups_dir
    events_path = dataset_root / events_dir
    stats = IngestStats()
    matches = list(
        Match.objects.filter(external_source=PROVIDER)
        .select_related("home_team__team", "away_team__team")
        .order_by("id")
    )
    if limit_matches is not None:
        matches = matches[: max(0, limit_matches)]

    player_cache: dict[str, Player] = {
        str(p.external_id): p for p in Player.objects.filter(external_source=PROVIDER)
    }

    for match_obj in matches:
        lineup_file = lineups_path / f"{match_obj.external_id}.json"
        if not lineup_file.exists():
            continue
        events_file = events_path / f"{match_obj.external_id}.json"
        events_data = _load_json(events_file) if events_file.exists() else None
        final_seconds = _match_final_elapsed_seconds(events_data)
        exit_constraints = {}
        if events_data is not None:
            exit_constraints = _player_exit_constraints_from_events(events_data)

        home_team_ext_id = str(match_obj.home_team.team.external_id)
        away_team_ext_id = str(match_obj.away_team.team.external_id)
        team_cache = {
            home_team_ext_id: match_obj.home_team,
            away_team_ext_id: match_obj.away_team,
        }

        PlayerOnPitchInterval.objects.filter(match=match_obj, provider=PROVIDER).delete()
        interval_rows: list[PlayerOnPitchInterval] = []
        lineups = _load_json(lineup_file)
        for team_entry in lineups:
            team_ext_id = str(team_entry.get("team_id"))
            if team_ext_id == home_team_ext_id:
                side = SIDE_HOME
            elif team_ext_id == away_team_ext_id:
                side = SIDE_AWAY
            else:
                side = SIDE_UNKNOWN

            team_season = team_cache.get(team_ext_id)
            if not team_season:
                continue

            for player_entry in team_entry.get("lineup", []):
                ext_id = str(player_entry.get("player_id"))
                player = player_cache.get(ext_id)
                if not player:
                    player = Player.objects.create(
                        full_name=str(player_entry.get("player_name", f"SB-{ext_id}")),
                        short_name=str(player_entry.get("player_nickname") or player_entry.get("player_name") or f"SB-{ext_id}"),
                        external_source=PROVIDER,
                        external_id=ext_id,
                    )
                    player_cache[ext_id] = player
                    stats = stats.add(players=1)

                positions = player_entry.get("positions") or []
                interval_rows.extend(
                    _on_pitch_intervals_from_positions(
                        positions=player_entry.get("positions") or [],
                        match_obj=match_obj,
                        player=player,
                        team_season=team_season,
                        side=side,
                        provider_player_id=ext_id,
                        exit_constraints=exit_constraints,
                        final_seconds=final_seconds,
                    )
                )

        if interval_rows:
            PlayerOnPitchInterval.objects.bulk_create(
                interval_rows,
                batch_size=WRITE_BATCH_SIZE_FAST,
                ignore_conflicts=True,
            )
        stats = stats.add(matches=1, on_pitch_intervals=len(interval_rows))

    return stats


def _ingest_lineups(
    lineup_file: Path,
    *,
    match_obj: Match,
    home_team_ext_id: str,
    away_team_ext_id: str,
    team_cache: dict[str, TeamSeason],
    player_cache: dict[str, Player],
    exit_constraints: dict[str, tuple[int, str, str]] | None = None,
    final_seconds: int = 90 * 60,
    stats: IngestStats,
) -> IngestStats:
    lineups = _load_json(lineup_file)
    PlayerOnPitchInterval.objects.filter(match=match_obj, provider=PROVIDER).delete()
    interval_rows: list[PlayerOnPitchInterval] = []
    for team_entry in lineups:
        team_ext_id = str(team_entry.get("team_id"))
        if team_ext_id == home_team_ext_id:
            side = SIDE_HOME
        elif team_ext_id == away_team_ext_id:
            side = SIDE_AWAY
        else:
            side = SIDE_UNKNOWN

        team_season = team_cache.get(team_ext_id)
        if not team_season:
            continue

        for p in team_entry.get("lineup", []):
            ext_id = str(p.get("player_id"))
            player = player_cache.get(ext_id)
            if not player:
                player = Player.objects.create(
                    full_name=str(p.get("player_name", f"SB-{ext_id}")),
                    short_name=str(p.get("player_nickname") or p.get("player_name") or f"SB-{ext_id}"),
                    external_source=PROVIDER,
                    external_id=ext_id,
                )
                player_cache[ext_id] = player
                stats = stats.add(players=1)

            positions = p.get("positions") or []
            minutes, is_starter = _extract_minutes_and_starter(positions, final_seconds=final_seconds)
            interval_rows.extend(
                _on_pitch_intervals_from_positions(
                    positions=positions,
                    match_obj=match_obj,
                    player=player,
                    team_season=team_season,
                    side=side,
                    provider_player_id=ext_id,
                    exit_constraints=exit_constraints,
                    final_seconds=final_seconds,
                )
            )
            appearance, created = MatchAppearance.objects.get_or_create(
                match=match_obj,
                player=player,
                defaults={
                    "team_season": team_season,
                    "side": side,
                    "minutes_played": minutes,
                    "is_starter": is_starter,
                },
            )
            if created:
                stats = stats.add(appearances=1)
            else:
                changed = False
                for field, value in (
                    ("team_season", team_season),
                    ("side", side),
                    ("minutes_played", minutes),
                    ("is_starter", is_starter),
                ):
                    if getattr(appearance, field) != value:
                        setattr(appearance, field, value)
                        changed = True
                if changed:
                    appearance.save(update_fields=["team_season", "side", "minutes_played", "is_starter"])
    if interval_rows:
        PlayerOnPitchInterval.objects.bulk_create(interval_rows, batch_size=WRITE_BATCH_SIZE_FAST, ignore_conflicts=True)
        stats = stats.add(on_pitch_intervals=len(interval_rows))
    return stats


def _ingest_events_and_features(
    events_file: Path,
    *,
    match_obj: Match,
    home_team_ext_id: str,
    away_team_ext_id: str,
    team_cache: dict[str, TeamSeason],
    player_cache: dict[str, Player],
    zone_cols: int,
    zone_rows: int,
    safe_writes: bool,
    data_version: str,
    formula_version: str,
    stats: IngestStats,
) -> IngestStats:
    events = _load_json(events_file)
    PlayerZoneFeature.objects.filter(
        match=match_obj,
        provider=PROVIDER,
    ).delete()
    TeamZoneFeature.objects.filter(
        match=match_obj,
        provider=PROVIDER,
    ).delete()
    MatchDisciplinaryEvent.objects.filter(
        match=match_obj,
        provider=PROVIDER,
    ).delete()

    player_zone_acc: dict[tuple[int, str, str, str], float] = defaultdict(float)
    team_zone_acc: dict[tuple[str, str, str], float] = defaultdict(float)
    disciplinary_rows: list[MatchDisciplinaryEvent] = []
    write_batch_size = WRITE_BATCH_SIZE if safe_writes else WRITE_BATCH_SIZE_FAST

    def safe_insert_rows(rows: list[Any]) -> int:
        if not rows:
            return 0
        inserted = 0
        for row in rows:
            try:
                row.save(force_insert=True)
                inserted += 1
            except Exception:
                continue
        return inserted

    def inc_feature(player_id: int | None, side: str, zone: str, key: str, value: float = 1.0):
        team_zone_acc[(side, zone, key)] += float(value)
        if player_id is not None:
            player_zone_acc[(player_id, side, zone, key)] += float(value)

    for event in events:
        event_type_name = str(event.get("type", {}).get("name", "unknown"))
        success = _infer_success(event, event_type_name)

        team_id_raw = event.get("team", {}).get("id")
        team_ext_id = str(team_id_raw) if team_id_raw is not None else ""
        if team_ext_id == home_team_ext_id:
            side = SIDE_HOME
        elif team_ext_id == away_team_ext_id:
            side = SIDE_AWAY
        else:
            side = SIDE_UNKNOWN

        player_obj: Player | None = None
        player_id_raw = event.get("player", {}).get("id")
        if player_id_raw is not None:
            player_ext_id = str(player_id_raw)
            player_obj = player_cache.get(player_ext_id)
            if not player_obj:
                player_obj = Player.objects.create(
                    full_name=str(event.get("player", {}).get("name", f"SB-{player_ext_id}")),
                    short_name=str(event.get("player", {}).get("name", f"SB-{player_ext_id}")),
                    external_source=PROVIDER,
                    external_id=player_ext_id,
                )
                player_cache[player_ext_id] = player_obj
                stats = stats.add(players=1)

        x, y = _norm_xy(event.get("location"))
        x_end, y_end = _event_end_xy(event, event_type_name)

        disciplinary_row = _disciplinary_row_from_statsbomb_event(
            event=event,
            event_type_name=event_type_name,
            match_obj=match_obj,
            home_team_ext_id=home_team_ext_id,
            away_team_ext_id=away_team_ext_id,
            team_cache=team_cache,
            player_cache=player_cache,
            fallback_index=len(disciplinary_rows),
        )
        if disciplinary_row is not None:
            disciplinary_rows.append(disciplinary_row)

        if x is None or y is None or side == SIDE_UNKNOWN:
            continue

        player_id = player_obj.id if player_obj else None
        zone = _zone_key(x, y, zone_cols, zone_rows)
        lower_type = event_type_name.lower()

        # Generic on-ball touch proxy.
        if lower_type in {"pass", "carry", "ball receipt*", "dribble", "duel", "shot"}:
            inc_feature(player_id, side, zone, "touches", 1.0)

        if lower_type == "pass":
            inc_feature(player_id, side, zone, "passes_attempted", 1.0)
            if success:
                inc_feature(player_id, side, zone, "passes_completed", 1.0)
            else:
                inc_feature(player_id, side, zone, "errors_bad_passes", 1.0)
            if _key_pass(event):
                inc_feature(player_id, side, zone, "key_passes", 1.0)
            if success and _progressive(x, x_end):
                inc_feature(player_id, side, zone, "progressive_passes_completed", 1.0)
            if success and _is_box_coord(x_end, y_end):
                inc_feature(player_id, side, zone, "passes_into_box", 1.0)

        elif lower_type == "carry":
            if _progressive(x, x_end):
                inc_feature(player_id, side, zone, "progressive_carries", 1.0)

        elif lower_type == "shot":
            shot = event.get("shot") or {}
            xg = float(shot.get("statsbomb_xg") or 0.0)
            inc_feature(player_id, side, zone, "shots", 1.0)
            inc_feature(player_id, side, zone, "xg_shots", xg)

        elif lower_type == "duel":
            outcome = str((event.get("duel") or {}).get("outcome", {}).get("name", "")).lower()
            if "won" in outcome:
                inc_feature(player_id, side, zone, "duels_won", 1.0)

        elif lower_type == "ball recovery":
            inc_feature(player_id, side, zone, "ball_recoveries", 1.0)

        elif lower_type == "interception":
            inc_feature(player_id, side, zone, "interceptions", 1.0)

        elif lower_type == "block":
            inc_feature(player_id, side, zone, "blocks", 1.0)

        elif lower_type == "clearance":
            inc_feature(player_id, side, zone, "clearances", 1.0)

        elif lower_type == "pressure":
            inc_feature(player_id, side, zone, "pressures", 1.0)

        elif lower_type == "dispossessed":
            inc_feature(player_id, side, zone, "errors_dispossessed", 1.0)

        elif lower_type == "miscontrol":
            inc_feature(player_id, side, zone, "errors_miscontrols", 1.0)

        elif lower_type == "foul committed":
            inc_feature(player_id, side, zone, "errors_fouls_committed", 1.0)

        if _is_box_coord(x, y):
            inc_feature(player_id, side, zone, "touches_in_box", 1.0)

    player_rows = [
        PlayerZoneFeature(
            match=match_obj,
            player_id=player_id,
            team_side=side,
            zone_key=zone_key,
            feature_key=feature_key,
            value=value,
            provider=PROVIDER,
            source_method="event_spatial_exact",
        )
        for (player_id, side, zone_key, feature_key), value in player_zone_acc.items()
    ]
    team_rows = [
        TeamZoneFeature(
            match=match_obj,
            team_side=side,
            zone_key=zone_key,
            feature_key=feature_key,
            value=value,
            provider=PROVIDER,
            source_method="event_spatial_exact",
        )
        for (side, zone_key, feature_key), value in team_zone_acc.items()
    ]

    player_inserted = 0
    if player_rows:
        if not safe_writes:
            PlayerZoneFeature.objects.bulk_create(player_rows, batch_size=write_batch_size, ignore_conflicts=True)
            player_inserted = len(player_rows)
        else:
            try:
                PlayerZoneFeature.objects.bulk_create(player_rows, batch_size=write_batch_size, ignore_conflicts=True)
                player_inserted = len(player_rows)
            except DatabaseError:
                player_inserted = safe_insert_rows(player_rows)

    team_inserted = 0
    if team_rows:
        if not safe_writes:
            TeamZoneFeature.objects.bulk_create(team_rows, batch_size=write_batch_size, ignore_conflicts=True)
            team_inserted = len(team_rows)
        else:
            try:
                TeamZoneFeature.objects.bulk_create(team_rows, batch_size=write_batch_size, ignore_conflicts=True)
                team_inserted = len(team_rows)
            except DatabaseError:
                team_inserted = safe_insert_rows(team_rows)

    disciplinary_inserted = 0
    if disciplinary_rows:
        if not safe_writes:
            MatchDisciplinaryEvent.objects.bulk_create(
                disciplinary_rows,
                batch_size=write_batch_size,
                ignore_conflicts=True,
            )
            disciplinary_inserted = len(disciplinary_rows)
        else:
            try:
                MatchDisciplinaryEvent.objects.bulk_create(
                    disciplinary_rows,
                    batch_size=write_batch_size,
                    ignore_conflicts=True,
                )
                disciplinary_inserted = len(disciplinary_rows)
            except DatabaseError:
                disciplinary_inserted = safe_insert_rows(disciplinary_rows)

    stats = stats.add(
        player_zone_features=player_inserted,
        team_zone_features=team_inserted,
        disciplinary_events=disciplinary_inserted,
    )
    return stats
