"""Transform SofaScore data (fetched via ScraperFC) into the zone-feature schema.

ScraperFC's ``Sofascore`` class handles the fragile fetch/anti-bot layer and
exposes exactly the three pieces we need per match:

* ``scrape_player_match_stats(match_id) -> DataFrame``  — per-player AGGREGATE
  stat totals (columns are SofaScore stat keys: totalPass, accuratePass, ...).
* ``scrape_match_shots(match_id) -> DataFrame``         — shotmap rows (nested
  ``player`` dict, ``isHome``, ``xg``, ``playerCoordinates``).
* ``scrape_heatmaps(match_id) -> dict``                 — ``{player_name:
  {'id': pid, 'heatmap': [(x, y), ...]}}`` for every player, in one call.

None of these are labelled spatial events, so this adapter reconstructs
``PlayerZoneFeature`` rows with a hybrid, honest ``source_method`` per row:

* ``touches`` / ``touches_in_box`` per zone -> from the heatmap distribution
  scaled by the lineup ``touches`` total (``heatmap_points``).
* ``shots`` / ``xg_shots`` per zone         -> exact from the shotmap
  (``shotmap_exact``).
* every other quality stat                  -> the aggregate total DISTRIBUTED
  across zones in proportion to heatmap presence (``heatmap_interpolated``).

Four StatsBomb features have no SofaScore /lineups equivalent and stay absent:
``pressures``, ``progressive_passes_completed``, ``passes_into_box``,
``progressive_carries`` (ball-carry stats live only in the richer per-player
statistics endpoint — not worth a second request per player) — so the SofaScore
provider needs its own scoring-weight calibration.

ScraperFC is passed in (duck-typed), so this module imports without it; only
the management command needs ScraperFC installed.

Coordinate frame: SofaScore coords are 0-100, assumed already in each team's
attacking direction (toward x=100), matching the StatsBomb importer. If a pilot
match shows away-team zones mirrored, pass ``flip_away=True``.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from django.db import transaction

from realdata.models import (
    CARD_RED,
    CARD_SECOND_YELLOW,
    CARD_UNKNOWN,
    CARD_YELLOW,
    Competition,
    CompetitionSeason,
    Match,
    MatchAppearance,
    MatchDisciplinaryEvent,
    MatchShot,
    Player,
    PlayerAlias,
    PlayerZoneFeature,
    PROVIDER_SOFASCORE,
    SIDE_AWAY,
    SIDE_HOME,
    Season,
    Team,
    TeamSeason,
    TeamZoneFeature,
)
# Reuse the exact zone-binning the StatsBomb importer uses, so both providers land
# features in identical zones. We do NOT reuse ``_is_box_coord`` for touches_in_box:
# it flags BOTH penalty areas, and the heatmap is in the player's own attacking
# frame, so it would count a centre-back's defensive own-box touches as box
# presence. We test the ATTACKING box only (see the box_count loop).
from realdata.services.statsbomb_adapter import (
    BOX_X_MIN, BOX_Y_MIN, BOX_Y_MAX, _zone_key)
from realdata.services.sofascore_client import SofaScoreBlocked
from realdata.services.identity import is_placeholder_dob, norm_name

PROVIDER = PROVIDER_SOFASCORE
# SofaScore card incidentClass -> our card taxonomy
_CARD_CLASS = {"yellow": CARD_YELLOW, "red": CARD_RED, "yellowRed": CARD_SECOND_YELLOW}
LEAGUE_KEY = "Italy Serie A"  # ScraperFC comps.yaml key (SOFASCORE id 23)

# Where a player's numbers go when nobody has measured WHERE he was — the light
# round of a live match, which does not pull heatmaps. The totals are still true:
# the scorer sums each feature over all zones, and the sum of a distributed stat is
# the stat. Only the POSITION is missing, so it is declared twice over:
#
# * ``METHOD_UNPLACED`` is the declaration a reader filters on — "this row says
#   nothing about where he was";
# * ``ZONE_UNPLACED`` is deliberately not a cell of the grid, so a positional
#   reader that forgot the filter breaks loudly instead of quietly standing the
#   player in the corner of the pitch.
ZONE_UNPLACED = "Z_NA"
METHOD_UNPLACED = "totals_unplaced"

# our feature_key -> SofaScore stat column(s); a tuple sums columns.
# These totals are distributed across zones in proportion to heatmap presence.
DISTRIBUTED_STAT_MAP: dict[str, Any] = {
    "passes_completed": "accuratePass",
    "key_passes": "keyPass",
    # duelWon is the TOTAL duels won (ground + aerial); aerialWon is its aerial
    # subset, so summing them double-counts aerials. Use duelWon alone.
    "duels_won": "duelWon",
    "ball_recoveries": "ballRecovery",
    "interceptions": "interceptionWon",
    "blocks": "outfielderBlock",
    "clearances": "totalClearance",
    "errors_dispossessed": "dispossessed",
    "errors_fouls_committed": "fouls",
    "errors_miscontrols": "unsuccessfulTouch",
    # Quality / end-product signals — outcome-INDEPENDENT performance (a shot's xA or
    # a missed big chance reflects the player's game regardless of the goal bonus).
    # Shared store: these enrich both the Aura zone duel and the classic voto puro.
    "expected_assists": "expectedAssists",
    "big_chance_created": "bigChanceCreated",
    "dribbles_won": "wonContest",
    "shots_on_target": "onTargetScoringAttempt",
    "xg_on_target": "expectedGoalsOnTarget",  # post-shot xG = shot EXECUTION merit
    "errors_led_to_goal": "errorLeadToAGoal",
    "big_chance_missed": "bigChanceMissed",
    "errors_led_to_shot": "errorLeadToAShot",
    # Goalkeeper channel. Without these a keeper has NO measurable output: the
    # outfield features above are near-empty for them, which is why keepers had no
    # voto at all. All non-negative counts.
    # Denominators. duels_won and dribbles_won were stored as bare counts, which
    # makes a defender who won 5 duels of 6 indistinguishable from one who won 5 of
    # 20; against the provider's own rating the SUCCESS RATE tracks performance
    # better than the count (+0.387 vs +0.348). The losing side of each contest is
    # what makes that rate computable.
    "duels_lost": "duelLost",
    "aerials_won": "aerialWon",
    "aerials_lost": "aerialLost",
    "dribbles_attempted": "totalContest",
    "dribbled_past": "challengeLost",       # he got beaten: the individual
                                            # defensive failure our features could
                                            # not see at all
    "tackles": "totalTackle",
    "tackles_won": "wonTackle",
    "last_man_tackle": "lastManTackle",
    "clearances_off_line": "clearanceOffLine",
    # Progression in possession. The old weights named passes_into_box and
    # progressive_passes_completed, which SofaScore never sends; passes completed
    # in the opponent half is the proxy it does send, and it correlates +0.240 with
    # the provider rating.
    "passes_opp_half": "accurateOppositionHalfPasses",
    "long_balls_completed": "accurateLongBalls",
    "crosses_completed": "accurateCross",
    "possession_lost": "possessionLostCtrl",
    "was_fouled": "wasFouled",
    # Conceding a penalty carries NO fantacalcio malus, so unlike a missed penalty
    # it is invisible unless the base vote accounts for it. Winning one is likewise
    # unrewarded: the goal bonus goes to whoever converts.
    "penalties_conceded": "penaltyConceded",
    "penalties_won": "penaltyWon",
    "gk_saves": "saves",
    "gk_saves_inside_box": "savedShotsFromInsideTheBox",
    "gk_penalty_saves": "penaltySave",
    "gk_high_claims": "goodHighClaim",
    "gk_punches": "punches",
    "gk_crosses_not_claimed": "crossNotClaimed",
    "gk_sweeper": "accurateKeeperSweeper",
}

# Stats that are legitimately SIGNED: a keeper conceding more than the xG on target
# he faced is a real NEGATIVE performance, so these must bypass the ">0" filter that
# (correctly) drops empty counts.
SIGNED_DISTRIBUTED_STAT_MAP: dict[str, Any] = {
    # xG-on-target faced minus goals conceded: the cleanest "better/worse than
    # expected" measure of shot-stopping.
    "gk_goals_prevented": "goalsPrevented",
}

KNOWN_FEATURE_KEYS = [
    "duels_lost", "aerials_won", "aerials_lost", "dribbles_attempted",
    "dribbled_past", "tackles", "tackles_won", "last_man_tackle",
    "clearances_off_line", "passes_opp_half", "long_balls_completed",
    "crosses_completed", "possession_lost", "was_fouled", "penalties_conceded",
    "penalties_won",
    "touches", "touches_in_box", "shots", "xg_shots",
    "passes_completed", "errors_bad_passes", "key_passes", "duels_won",
    "ball_recoveries", "interceptions", "blocks", "clearances",
    "errors_dispossessed", "errors_fouls_committed", "errors_miscontrols",
    "expected_assists", "big_chance_created", "dribbles_won", "shots_on_target",
    "xg_on_target", "errors_led_to_goal", "big_chance_missed", "errors_led_to_shot",
    "gk_saves", "gk_saves_inside_box", "gk_penalty_saves", "gk_high_claims",
    "gk_punches", "gk_crosses_not_claimed", "gk_sweeper", "gk_goals_prevented",
]


@dataclass(frozen=True)
class SofaIngestResult:
    matches: int = 0
    teams: int = 0
    players: int = 0
    appearances: int = 0
    cards: int = 0
    player_zone_features: int = 0
    team_zone_features: int = 0
    # Players whose totals were written without a position: no heatmap this pass
    # AND nothing to carry over from a previous one. See ZONE_UNPLACED.
    players_unplaced: int = 0
    skipped_not_finished: int = 0
    skipped_existing: int = 0
    # Matches whose own /event/{id} did not answer with something usable, so the
    # caller must fall back to resolving them from the schedule. See
    # ``ingest_sofascore_matches``.
    unresolved: int = 0

    def add(self, **kwargs: int) -> "SofaIngestResult":
        values = self.__dict__.copy()
        for k, v in kwargs.items():
            values[k] = values.get(k, 0) + int(v)
        return SofaIngestResult(**values)


# -- season / value helpers ----------------------------------------------


def season_code_from_year(year: str) -> str:
    """SofaScore ``year`` ("25/26") -> our Season.code ("2025-2026")."""
    year = str(year).strip()
    if "/" in year:
        a, b = year.split("/")
        return f"20{int(a):02d}-20{int(b):02d}"
    return year


def _num(value: Any) -> float:
    """Coerce a possibly-NaN/None DataFrame cell to a float (0.0 if empty)."""
    if value is None:
        return 0.0
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(f) else f


def _stat(row: dict[str, Any], key: Any) -> float:
    if isinstance(key, tuple):
        return sum(_stat(row, k) for k in key)
    return _num(row.get(key))


def _first(row: dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in row and row[k] is not None:
            v = row[k]
            if isinstance(v, float) and math.isnan(v):
                continue
            return v
    return None


def _norm_point(x: Any, y: Any, side: str, flip_away: bool) -> tuple[float, float] | None:
    try:
        nx = float(x) / 100.0
        ny = float(y) / 100.0
    except (TypeError, ValueError):
        return None
    if math.isnan(nx) or math.isnan(ny):
        return None
    if flip_away and side == SIDE_AWAY:
        nx, ny = 1.0 - nx, 1.0 - ny
    return min(1.0, max(0.0, nx)), min(1.0, max(0.0, ny))


def _shot_point_xy(coords: Any) -> tuple[Any, Any]:
    """Shot coordinates, brought into the SAME frame as the heatmap.

    SofaScore's two payloads do not agree. A heatmap point is already expressed in
    the player's attacking direction (own goal at x=0), which is why keepers sit
    at x~10 and forwards at x~64. The shotmap's ``playerCoordinates`` instead
    measure from the goal being ATTACKED: every shot, for both teams, lands at
    x~15 — which read in the heatmap frame would put every strike inside the
    shooter's own six-yard box.

    It is a 180 degree rotation, not a mirror of the long axis alone: comparing
    1295 shots with their taker's own heatmap, the y correlation is -0.47, and
    562 of 761 shots by clearly wide players fell on the opposite flank. So BOTH
    axes are inverted.

    Consequence of not doing this, which is why it went unnoticed for so long:
    the voto puro sums xg_shots across zones, so a shot in the wrong zone changed
    no vote. Only spatial consumers — the Aura zone vectors — were affected.
    """
    x, y = _point_xy(coords)
    try:
        return 100.0 - float(x), 100.0 - float(y)
    except (TypeError, ValueError):
        return None, None


def _point_xy(pt: Any) -> tuple[Any, Any]:
    if isinstance(pt, (list, tuple)) and len(pt) >= 2:
        return pt[0], pt[1]
    if isinstance(pt, dict):
        return pt.get("x"), pt.get("y")
    return None, None


# -- entity upserts (mirror statsbomb_adapter patterns) ------------------


def _get_or_create_competition_season(season_code: str) -> CompetitionSeason:
    competition, _ = Competition.objects.get_or_create(
        external_source=PROVIDER, external_id="23",
        defaults={"name": "Serie A", "country": "Italy"},
    )
    season, _ = Season.objects.get_or_create(code=season_code)
    competition_season, _ = CompetitionSeason.objects.get_or_create(
        competition=competition, season=season,
        defaults={"name": f"Serie A {season_code}", "num_rounds": 38},
    )
    return competition_season


def _team_season(team_dict: dict[str, Any], competition_season: CompetitionSeason,
                 cache: dict[str, TeamSeason]) -> TeamSeason:
    ext_id = str(team_dict.get("id"))
    if ext_id in cache:
        return cache[ext_id]
    team, _ = Team.objects.get_or_create(
        external_source=PROVIDER, external_id=ext_id,
        defaults={"name": str(team_dict.get("name", ext_id)),
                  "short_name": str(team_dict.get("shortName", "") or "")},
    )
    team_season, _ = TeamSeason.objects.get_or_create(
        competition_season=competition_season, team=team)
    cache[ext_id] = team_season
    return team_season


def _dob_from_ts(ts: Any):
    """SofaScore ``dateOfBirthTimestamp`` (epoch seconds, UTC) -> date | None."""
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).date()
    except (TypeError, ValueError, OSError):
        return None


def _should_set_dob(existing, new) -> bool:
    """Only FILL a missing/placeholder DOB — never clobber a good date.

    SofaScore ships Jan-1 placeholders and the odd off-by date, and the
    Transfermarkt importer may have corrected a player's DOB from the authoritative
    source; a later match re-import must not overwrite that with a worse value.
    """
    if not new or existing == new:
        return False
    return existing is None or is_placeholder_dob(existing)


def _adopt_by_identity(name: str, dob) -> Player | None:
    """Find an EXISTING canonical player (from another provider) for this human.

    Enforces "one Player across providers": before minting a new SofaScore row,
    check whether this person already exists — e.g. a Transfermarkt-sourced squad
    member who just made their debut. Matched on (exact normalised name + DOB);
    DOB is required (precise, and StatsBomb rows carry none so they're untouched),
    and the match must be unique. The SofaScore id is then attached as an alias so
    future imports resolve straight to the same entity.
    """
    if not dob:
        return None
    nm = norm_name(name)
    if not nm:
        return None
    cands = [
        c for c in Player.objects.filter(date_of_birth=dob).exclude(external_source=PROVIDER)
        if (norm_name(c.full_name) == nm or norm_name(c.short_name) == nm)
        and not PlayerAlias.objects.filter(player=c, source=PROVIDER).exists()
    ]
    return cands[0] if len(cands) == 1 else None


def _player(player_id: Any, name: str, short_name: str,
            cache: dict[str, Player], dob_ts: Any = None) -> Player:
    ext_id = str(player_id)
    dob = _dob_from_ts(dob_ts)
    if ext_id in cache:
        player = cache[ext_id]
        # backfill DOB on a player we first saw without it (e.g. from a shotmap)
        if _should_set_dob(player.date_of_birth, dob):
            player.date_of_birth = dob
            player.save(update_fields=["date_of_birth"])
        return player
    # Resolve an existing identity: this provider's id (primary, or an alias from a
    # prior adoption) before falling back to cross-provider adoption, then creation.
    player = (Player.objects.filter(external_source=PROVIDER, external_id=ext_id).first()
              or _player_by_alias(ext_id))
    if player is None:
        adopted = _adopt_by_identity(name, dob)
        if adopted is not None:
            PlayerAlias.objects.get_or_create(
                player=adopted, source=PROVIDER, alias=ext_id)
            print(f"  [identity] adopted existing player '{adopted.full_name}' "
                  f"({adopted.external_source}/{adopted.external_id}) for SofaScore "
                  f"id {ext_id} — no duplicate created")
            player = adopted
        else:
            player = Player.objects.create(
                external_source=PROVIDER, external_id=ext_id,
                full_name=str(name or f"SS-{ext_id}"),
                short_name=str(short_name or ""), date_of_birth=dob)
    # player may have existed without a DOB (or with a placeholder) -> fill it
    if _should_set_dob(player.date_of_birth, dob):
        player.date_of_birth = dob
        player.save(update_fields=["date_of_birth"])
    cache[ext_id] = player
    return player


def _player_by_alias(ext_id: str) -> Player | None:
    a = (PlayerAlias.objects.filter(source=PROVIDER, alias=ext_id)
         .select_related("player").first())
    return a.player if a else None


def _kickoff(event: dict[str, Any]) -> datetime | None:
    ts = event.get("startTimestamp")
    if not ts:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


def _upsert_match(event: dict[str, Any], competition_season: CompetitionSeason,
                  home_ts: TeamSeason, away_ts: TeamSeason) -> Match:
    matchday = (event.get("roundInfo") or {}).get("round")
    defaults = {
        "competition_season": competition_season,
        "matchday": int(matchday) if matchday is not None else None,
        "kickoff": _kickoff(event),
        "home_team": home_ts, "away_team": away_ts,
        "home_goals": (event.get("homeScore") or {}).get("current"),
        "away_goals": (event.get("awayScore") or {}).get("current"),
    }
    match, created = Match.objects.get_or_create(
        external_source=PROVIDER, external_id=str(event.get("id")), defaults=defaults)
    if not created:
        changed = False
        for field, value in defaults.items():
            # Never replace something we have with a None the payload did not
            # carry. A round entry always ships roundInfo/startTimestamp; the
            # per-match /event/{id} the live path resolves from is thinner, and
            # an update from it must not erase the matchday the schedule
            # established.
            if value is None and getattr(match, field) is not None:
                continue
            if getattr(match, field) != value:
                setattr(match, field, value)
                changed = True
        if changed:
            match.save()
    return match


# -- per-match ingestion -------------------------------------------------


def _ingest_cards(incidents_rows, match, home_ts, away_ts, player_cache) -> int:
    """Create MatchDisciplinaryEvent rows from a match's incidents (cards only).
    Idempotent: drops this match's sofascore card events, then bulk-inserts."""
    MatchDisciplinaryEvent.objects.filter(match=match, provider=PROVIDER).delete()
    rows = []
    for inc in incidents_rows:
        if inc.get("incidentType") != "card":
            continue
        pdata = inc.get("player") or {}
        pid = pdata.get("id")
        if pid is None:
            continue
        player = _player(pid, pdata.get("name", ""), pdata.get("shortName", ""),
                         player_cache, dob_ts=pdata.get("dateOfBirthTimestamp"))
        minute = int(inc.get("time") or 0)
        cls = inc.get("incidentClass")
        side = SIDE_HOME if inc.get("isHome") else SIDE_AWAY
        rows.append(MatchDisciplinaryEvent(
            match=match, player=player,
            team_season=home_ts if side == SIDE_HOME else away_ts,
            team_side=side, minute=minute,
            card_type=_CARD_CLASS.get(cls, CARD_UNKNOWN),
            reason=(inc.get("reason") or "")[:80],
            provider=PROVIDER, provider_event_id=f"card:{minute}:{pid}:{cls}",
            source_event_type="card", source_card_name=cls or "", payload=inc,
        ))
    MatchDisciplinaryEvent.objects.bulk_create(rows, ignore_conflicts=True)
    return len(rows)


def _carried_presence(match) -> dict[int, tuple[dict[str, float], dict[str, float]]]:
    """{player_id: (presence share per zone, box share per zone)} as the last pass
    that DID have heatmaps measured them.

    A light round has no heatmap of its own, and a player's distribution over the
    pitch barely moves in the couple of minutes since the last heavy one. Reusing it
    is not a nicety: ``_upsert_zone_features`` removes whatever stops arriving, so a
    light round that dropped everyone into the unplaced zone would delete the
    positions the heavy pass had just measured — and the defensive exposure, which
    is built from them, would blink out and back every k rounds, sawing every
    defender's vote up and down with it.

    The shares are read against the touches TOTAL, which is exactly how the heavy
    pass wrote both rows (``touches[zone] = zone_share * total``, ``touches_in_box
    [zone] = box_share * total``), so multiplying them by this minute's total
    reproduces the same arithmetic against fresher numbers.
    """
    out: dict[int, tuple[dict[str, float], dict[str, float]]] = {}
    raw: dict[int, dict[str, dict[str, float]]] = defaultdict(
        lambda: {"touches": {}, "touches_in_box": {}})
    for pid, zone, key, value in (
            PlayerZoneFeature.objects
            .filter(match=match, provider=PROVIDER,
                    feature_key__in=("touches", "touches_in_box"))
            .exclude(source_method=METHOD_UNPLACED)
            .values_list("player_id", "zone_key", "feature_key", "value")):
        raw[pid][key][zone] = float(value or 0.0)
    for pid, rows in raw.items():
        total = sum(rows["touches"].values())
        if total <= 0:
            continue
        out[pid] = ({z: v / total for z, v in rows["touches"].items()},
                    {z: v / total for z, v in rows["touches_in_box"].items()})
    return out


def _ingest_match(
    *, scraper, event: dict[str, Any], competition_season: CompetitionSeason,
    team_cache: dict[str, TeamSeason], player_cache: dict[str, Player],
    zone_cols: int, zone_rows: int, flip_away: bool,
    feature_totals: dict[str, float], stat_keys_seen: set[str],
    diagnostics: dict[str, bool], log: Callable[[str], None],
    with_heatmaps: bool = True,
) -> SofaIngestResult:
    """Import one match. ``with_heatmaps=False`` is the LIGHT round of a live
    match: it skips the request-per-player heatmaps and places each player's totals
    where the last heavy round measured him, or in ``ZONE_UNPLACED`` if it never
    did (a substitute who came on since). The shot map keeps its exact coordinates
    either way — that one is a single request."""
    match_id = int(event["id"])
    home_team = event["homeTeam"]
    away_team = event["awayTeam"]
    # Fetch first so a block raises before we create an empty Match shell.
    stats_rows = scraper.player_stats_records(match_id)
    shots_rows = scraper.shots_records(match_id)
    incidents_rows = scraper.incidents_records(match_id)
    home_ts = _team_season(home_team, competition_season, team_cache)
    away_ts = _team_season(away_team, competition_season, team_cache)
    match = _upsert_match(event, competition_season, home_ts, away_ts)
    # Read before anything is written for this match, and only when it is needed.
    carried = _carried_presence(match) if not with_heatmaps else {}

    first_match = not diagnostics.get("logged")
    if first_match:
        diagnostics["logged"] = True
        log("  [diagnostics] player-stats keys: "
            + ", ".join(sorted(stats_rows[0].keys())) if stats_rows else "  [diagnostics] no stat rows")
        log("  [diagnostics] shots keys: "
            + ", ".join(sorted(shots_rows[0].keys())) if shots_rows else "  [diagnostics] no shot rows")
    # (side, position) -> [sum of binned normalized-x, point count]
    orient_acc: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0])

    player_zone: dict[tuple[int, str, str, str], float] = defaultdict(float)
    team_zone: dict[tuple[str, str, str], float] = defaultdict(float)

    def inc(player_id: int, side: str, zone: str, key: str, value: float) -> None:
        if value == 0.0:
            return
        player_zone[(player_id, side, zone, key)] += value
        team_zone[(side, zone, key)] += value
        feature_totals[key] = feature_totals.get(key, 0.0) + value

    appearances = 0
    no_heatmap = 0

    for row in stats_rows:
        stat_keys_seen.update(row.keys())
        pid_raw = _first(row, "id", "playerId", "player_id")
        if pid_raw is None:
            continue
        side = SIDE_HOME if row.get("side") == "home" else SIDE_AWAY
        name = _first(row, "name", "shortName") or ""
        short_name = _first(row, "shortName") or ""
        player = _player(pid_raw, name, short_name, player_cache,
                         dob_ts=_first(row, "dateOfBirthTimestamp"))

        minutes = int(_stat(row, "minutesPlayed"))
        substitute = _first(row, "substitute")
        is_starter = (not bool(substitute)) if substitute is not None else False
        team_ts = home_ts if side == SIDE_HOME else away_ts
        raw_stats = {k: v for k, v in row.items()
                     if isinstance(v, (int, float, bool))}
        # Keep the coarse lineup position (F/M/D/G, a string) too: it disambiguates
        # the role of players with too few minutes to cluster. See role_inference.
        _pos = _first(row, "position")
        if _pos:
            raw_stats["position"] = str(_pos)
        MatchAppearance.objects.update_or_create(
            match=match, player=player,
            defaults={"team_season": team_ts, "side": side,
                      "minutes_played": minutes, "is_starter": is_starter,
                      "goals": int(_stat(row, "goals")),
                      "assists": int(_stat(row, "goalAssist")),
                      "raw_stats": raw_stats},
        )
        appearances += 1

        # Heatmap (one request per player) -> per-zone presence distribution.
        # Skip players with no minutes (unused subs have no heatmap data), and the
        # whole lot on a light round: that request per player IS the cost the heavy
        # pass exists to ration.
        points = (scraper.heatmap(match_id, int(pid_raw))
                  if with_heatmaps and minutes > 0 else [])
        if first_match and not diagnostics.get("hm_sample") and points:
            diagnostics["hm_sample"] = True
            log(f"  [diagnostics] heatmap sample: {str(points[:8])[:160]}")
        zone_count: dict[str, int] = defaultdict(int)
        box_count: dict[str, int] = defaultdict(int)
        total = 0
        for pt in points:
            px, py = _point_xy(pt)
            norm = _norm_point(px, py, side, flip_away)
            if norm is None:
                continue
            zone = _zone_key(norm[0], norm[1], zone_cols, zone_rows)
            zone_count[zone] += 1
            # touches_in_box = ATTACKING-box presence only. The raw heatmap is in
            # the player's own attacking frame (own goal at x=0), so the opponent
            # box is the HIGH-x box; testing the unflipped point avoids crediting a
            # defender for touches in his OWN box while under pressure.
            raw = _norm_point(px, py, side, False)
            if raw is not None and raw[0] >= BOX_X_MIN and BOX_Y_MIN <= raw[1] <= BOX_Y_MAX:
                box_count[zone] += 1
            total += 1
            if first_match:
                acc = orient_acc[(side, str(_first(row, "position") or "?"))]
                acc[0] += norm[0]
                acc[1] += 1

        if total:
            presence = {z: c / total for z, c in zone_count.items()}
            box_presence = {z: c / total for z, c in box_count.items()}
        else:
            # No heatmap for him this pass. His totals are still true — the scorer
            # sums them over all zones — so they are written either where the last
            # heavy round placed him or, failing that, unplaced and saying so.
            presence, box_presence = carried.get(player.id, ({}, {}))
            if not presence:
                no_heatmap += 1
                presence, box_presence = {ZONE_UNPLACED: 1.0}, {}

        touches_total = _stat(row, "touches") or float(total)

        for zone, frac in presence.items():
            inc(player.id, side, zone, "touches", touches_total * frac)
        for zone, frac in box_presence.items():
            inc(player.id, side, zone, "touches_in_box", frac * touches_total)

        bad_passes = max(0.0, _stat(row, "totalPass") - _stat(row, "accuratePass"))
        for feature_key, src in DISTRIBUTED_STAT_MAP.items():
            tot = _stat(row, src)
            if tot <= 0:
                continue
            for zone, frac in presence.items():
                inc(player.id, side, zone, feature_key, tot * frac)
        for feature_key, src in SIGNED_DISTRIBUTED_STAT_MAP.items():
            tot = _stat(row, src)
            if tot == 0:
                continue  # only skip "no signal"; negatives are meaningful
            for zone, frac in presence.items():
                inc(player.id, side, zone, feature_key, tot * frac)
        if bad_passes > 0:
            for zone, frac in presence.items():
                inc(player.id, side, zone, "errors_bad_passes", bad_passes * frac)

    if first_match:
        log("  [orientation] mean normalized-x by side/position "
            "(F should exceed D on BOTH sides; if the away side inverts, "
            "re-run with --flip-away):")
        for (side, pos), (sx, n) in sorted(orient_acc.items()):
            if n:
                log(f"    {side:<5} {pos:<3} meanx={sx / n:.2f} n={n}")

    # Shotmap -> exact shots / xG per zone, AND one event row per shot.
    shot_rows: list[MatchShot] = []
    for shot in shots_rows:
        pdata = shot.get("player") or {}
        if not isinstance(pdata, dict) or "id" not in pdata:
            continue
        side = SIDE_HOME if shot.get("isHome") else SIDE_AWAY
        coords = shot.get("playerCoordinates") or {}
        px, py = _shot_point_xy(coords)
        norm = _norm_point(px, py, side, flip_away)
        if norm is None:
            continue
        zone = _zone_key(norm[0], norm[1], zone_cols, zone_rows)
        player = _player(pdata["id"], pdata.get("name", ""), pdata.get("shortName", ""),
                         player_cache, dob_ts=pdata.get("dateOfBirthTimestamp"))
        inc(player.id, side, zone, "shots", 1.0)
        inc(player.id, side, zone, "xg_shots", _num(shot.get("xg")))
        # The event itself: the zone aggregate loses the minute, and anything that
        # must respect who was actually on the pitch needs it.
        shot_rows.append(MatchShot(
            match=match, player=player, team_side=side, zone_key=zone,
            minute=(int(shot["time"]) if isinstance(shot.get("time"), (int, float))
                    else None),
            # Seconds from kick-off — kept for OG↔shot linking (see MatchShot).
            elapsed_seconds=(int(shot["timeSeconds"])
                             if isinstance(shot.get("timeSeconds"), (int, float))
                             else None),
            xg=_num(shot.get("xg")), xgot=_num(shot.get("xgot")),
            is_goal=(str(shot.get("shotType") or "").lower() == "goal"),
            shot_type=str(shot.get("shotType") or "")[:24],
            # Play type (penalty/set-piece/…); a missed penalty needs it (see MatchShot).
            situation=str(shot.get("situation") or "")[:24],
            provider=PROVIDER, external_id=str(shot.get("id") or "")))

    # Incidents -> disciplinary events (cards). Cards live ONLY here, not in the
    # /lineups statistics, so they must be ingested as part of every import.
    cards = _ingest_cards(incidents_rows, match, home_ts, away_ts, player_cache)

    # MatchShot stays delete-and-reinsert: its unique constraint is CONDITIONAL
    # (~Q(external_id="")), which update_conflicts cannot key on, and it is ~25 rows
    # a match — nothing worth the complication.
    MatchShot.objects.filter(match=match, provider=PROVIDER).delete()
    MatchShot.objects.bulk_create(shot_rows, batch_size=500, ignore_conflicts=True)

    def method_for(zone: str, key: str) -> str:
        # Read off the ZONE, so a player and his team's aggregate agree without
        # threading per-player state down here: whatever landed unplaced says so.
        if zone == ZONE_UNPLACED:
            return METHOD_UNPLACED
        if key in ("shots", "xg_shots"):
            return "shotmap_exact"
        if key in ("touches", "touches_in_box"):
            return "heatmap_points"
        return "heatmap_interpolated"

    player_written, player_total = _upsert_zone_features(
        PlayerZoneFeature, match,
        attnames=("player_id", "team_side", "zone_key", "feature_key"),
        unique_names=("player", "team_side", "zone_key", "feature_key"),
        rows={k: (v, method_for(k[2], k[3])) for k, v in player_zone.items()})
    team_written, team_total = _upsert_zone_features(
        TeamZoneFeature, match,
        attnames=("team_side", "zone_key", "feature_key"),
        unique_names=("team_side", "zone_key", "feature_key"),
        rows={k: (v, method_for(k[1], k[2])) for k, v in team_zone.items()})

    log(f"  match {match_id} {home_team.get('name')} v {away_team.get('name')}: "
        f"{'heavy' if with_heatmaps else 'light'} "
        f"appearances={appearances} cards={cards} "
        f"player_rows={player_written}/{player_total} unplaced={no_heatmap}")

    return SofaIngestResult(
        matches=1, appearances=appearances, cards=cards,
        player_zone_features=player_total, team_zone_features=team_total,
        players_unplaced=no_heatmap,
    )


def _upsert_zone_features(model, match, *, attnames: tuple[str, ...],
                          unique_names: tuple[str, ...],
                          rows: dict[tuple, tuple[float, str]]) -> tuple[int, int]:
    """Write a match's zone features WITHOUT dropping and re-inserting them.

    Delete-and-reinsert is the natural way to be idempotent and it was right while
    a match was imported once, after full time. It is wrong when the same match is
    imported every ten minutes for two hours: each pass rebuilds ~4.800 rows and
    every index over them, to change a few hundred numbers.

    So: upsert on the natural key, and — since the read costs one query and saves
    most of the writes — send only the rows whose value actually moved. During a
    match the eleven on the pitch keep growing, so the saving is on whoever has
    already come off and on the dead spells; it is free either way.

    Returns (rows written, rows the match has). ``attnames`` are the column-level
    names (``player_id``), ``unique_names`` the field-level ones the constraint is
    declared with (``player``) — Django wants each in its own place.

    The delete at the end is the part that is easy to forget: an upsert never
    removes what stopped arriving. In a live match values only grow, so it should
    find nothing — but a re-import after a provider correction (a shot reassigned
    to another player) would otherwise leave the old row behind for ever, and a
    stale row in a long-format table is indistinguishable from a real one.
    """
    existing: dict[tuple, tuple[int, float]] = {
        tuple(row[:-2]): (row[-2], row[-1])
        for row in model.objects.filter(match=match, provider=PROVIDER)
        .values_list(*attnames, "id", "value")
    }
    changed = [key for key, (value, _method) in rows.items()
               if key not in existing or existing[key][1] != value]
    if changed:
        model.objects.bulk_create(
            [model(match=match, provider=PROVIDER, value=rows[k][0],
                   source_method=rows[k][1], **dict(zip(attnames, k)))
             for k in changed],
            batch_size=1000, update_conflicts=True,
            update_fields=["value", "source_method"],
            unique_fields=["match", *unique_names, "provider"],
        )
    gone = [rid for key, (rid, _v) in existing.items() if key not in rows]
    if gone:
        model.objects.filter(id__in=gone).delete()
    return len(changed), len(rows)


# -- orchestrator --------------------------------------------------------


def _event_by_id(scraper, match_id: int) -> dict[str, Any] | None:
    """One match's event dict from its OWN address, ``/event/{id}``.

    The season schedule is the way to find out WHICH matches exist; it is not the
    only way to reach one we already know. A match being played has a static
    address, and pulling seasons -> rounds -> every round's events to rediscover it
    is the single most expensive part of a live import.

    Returns None when the payload cannot stand in for a schedule entry — the teams
    are what the import cannot invent — so the caller can fall back to the
    calendar. That fallback is the safety net, not the main road: the address is
    static, but it can still change.
    """
    try:
        data = scraper.get(f"/api/v1/event/{match_id}")
    except SofaScoreBlocked:
        return None
    event = data.get("event") if isinstance(data, dict) else None
    if not isinstance(event, dict) or event.get("id") is None:
        return None
    for side in ("homeTeam", "awayTeam"):
        if not isinstance(event.get(side), dict) or event[side].get("id") is None:
            return None
    return event


def ingest_sofascore_matches(
    *, scraper, year: str, match_ids: list[int], season_code: str | None = None,
    only_finished: bool = True, skip_existing: bool = True,
    zone_cols: int = 5, zone_rows: int = 4, flip_away: bool = False,
    with_heatmaps: bool = True, logger: Callable[[str], None] = print,
) -> SofaIngestResult:
    """Ingest specific matches resolved BY ID, without reading the schedule.

    Same work as ``ingest_sofascore_season`` per match; only the way the fixture is
    found differs. ``result.unresolved`` counts the ids whose event did not answer
    usably — the caller decides whether to retry through the calendar.

    ``with_heatmaps=False`` is the light round of a live match: see ``_ingest_match``.
    """
    log = logger
    events: list[dict[str, Any]] = []
    unresolved = 0
    for mid in match_ids:
        event = _event_by_id(scraper, int(mid))
        if event is None:
            log(f"  match {mid}: /event/{mid} did not resolve it")
            unresolved += 1
            continue
        events.append(event)

    result = _ingest_events(
        scraper=scraper, events=events,
        season_code=season_code or season_code_from_year(year),
        only_finished=only_finished, skip_existing=skip_existing,
        limit_matches=None, zone_cols=zone_cols, zone_rows=zone_rows,
        flip_away=flip_away, with_heatmaps=with_heatmaps, log=log)
    return result.add(unresolved=unresolved)


def ingest_sofascore_season(
    *, scraper, year: str, season_code: str | None = None,
    only_finished: bool = True, skip_existing: bool = True,
    limit_matches: int | None = None, match_ids: list[int] | None = None,
    zone_cols: int = 5, zone_rows: int = 4, flip_away: bool = False,
    logger: Callable[[str], None] = print,
) -> SofaIngestResult:
    """Ingest a SofaScore Serie A season via a ``SofaScoreClient`` instance.

    ``year`` is the SofaScore year string (e.g. "25/26"). ``match_ids`` limits
    the run to specific matches (pilot mode); otherwise the whole season's
    finished matches are processed. Request throttling lives in the client.
    """
    log = logger

    log(f"Fetching match list for Serie A {year} ...")
    events = scraper.get_match_dicts(year)
    log(f"Season has {len(events)} matches in the schedule.")

    if match_ids is not None:
        wanted = {int(m) for m in match_ids}
        events = [e for e in events if int(e.get("id")) in wanted]
        log(f"Pilot mode: {len(events)} of the requested matches found.")

    return _ingest_events(
        scraper=scraper, events=events,
        season_code=season_code or season_code_from_year(year),
        only_finished=only_finished, skip_existing=skip_existing,
        limit_matches=limit_matches, zone_cols=zone_cols, zone_rows=zone_rows,
        flip_away=flip_away, with_heatmaps=True, log=log)


def _ingest_events(
    *, scraper, events: list[dict[str, Any]], season_code: str,
    only_finished: bool, skip_existing: bool, limit_matches: int | None,
    zone_cols: int, zone_rows: int, flip_away: bool, with_heatmaps: bool,
    log: Callable[[str], None],
) -> SofaIngestResult:
    """Ingest a list of already-resolved event dicts. Shared by both entry points,
    which differ only in HOW they got the list."""
    with transaction.atomic():
        competition_season = _get_or_create_competition_season(season_code)

    team_cache: dict[str, TeamSeason] = {}
    player_cache: dict[str, Player] = {
        str(p.external_id): p for p in Player.objects.filter(external_source=PROVIDER)
    }
    feature_totals: dict[str, float] = {}
    stat_keys_seen: set[str] = set()
    diagnostics: dict[str, bool] = {}

    result = SofaIngestResult()
    processed = 0
    for event in events:
        status_type = (event.get("status") or {}).get("type", "")
        if only_finished and status_type != "finished":
            result = result.add(skipped_not_finished=1)
            continue
        if limit_matches is not None and processed >= limit_matches:
            log(f"Reached limit_matches={limit_matches}; stopping.")
            break
        if skip_existing and PlayerZoneFeature.objects.filter(
            match__external_source=PROVIDER, match__external_id=str(event.get("id")),
            provider=PROVIDER,
        ).exists():
            result = result.add(skipped_existing=1)
            continue

        try:
            result = result.add(**_ingest_match(
                scraper=scraper, event=event, competition_season=competition_season,
                team_cache=team_cache, player_cache=player_cache,
                zone_cols=zone_cols, zone_rows=zone_rows, flip_away=flip_away,
                feature_totals=feature_totals, stat_keys_seen=stat_keys_seen,
                diagnostics=diagnostics, log=log, with_heatmaps=with_heatmaps,
            ).__dict__)
        except SofaScoreBlocked as exc:
            log(f"  !! SofaScore is blocking ({exc}); stopping cleanly. "
                f"Re-run the same command to resume from cache.")
            break
        except Exception as exc:  # noqa: BLE001 - skip one bad match, keep going
            log(f"  !! match {event.get('id')} failed: {type(exc).__name__}: {exc}")
        processed += 1

    result = result.add(teams=len(team_cache), players=len(player_cache))
    _log_diagnostics(feature_totals, stat_keys_seen, log)
    return result


def _log_diagnostics(feature_totals: dict[str, float], stat_keys_seen: set[str],
                     log: Callable[[str], None]) -> None:
    log("Feature totals (0.0 => not provided / mapping mismatch):")
    for key in KNOWN_FEATURE_KEYS:
        log(f"  {key:<28} {feature_totals.get(key, 0.0):.1f}")
    missing = ["pressures", "progressive_passes_completed", "passes_into_box",
               "progressive_carries"]
    log(f"Absent by design (no SofaScore equivalent): {', '.join(missing)}")
    unmapped = sorted(stat_keys_seen - _mapped_keys())
    if unmapped:
        log("Unmapped stat columns seen (extend DISTRIBUTED_STAT_MAP if useful):")
        log("  " + ", ".join(unmapped))


def _mapped_keys() -> set[str]:
    keys = {"minutesPlayed", "touches", "totalPass", "accuratePass",
            "id", "name", "shortName", "teamId", "teamName", "substitute"}
    for src in DISTRIBUTED_STAT_MAP.values():
        keys.update(src if isinstance(src, tuple) else (src,))
    return keys
