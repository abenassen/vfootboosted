"""Build exact on-pitch intervals for a SofaScore season, from cached incidents.

``PlayerOnPitchInterval`` is the project's canonical answer to "was he playing at
minute X", and it was populated only for the StatsBomb season. Without it the
SofaScore season had to guess: a starter assumed to run from kick-off for as many
minutes as he played, a substitute assumed to finish the match. That guess is
unbiased on average yet misattributes more than 20 percentage points of a match's
conceded danger for one defender in seven — which matters as soon as anything is
charged to a player for events in a window, as the defensive-exposure term is.

The cached ``*_incidents.json`` carries every substitution and card with its
minute, so the intervals can be reconstructed exactly, including the case a guess
cannot represent at all: a substitute who is himself later withdrawn.

A red card ends an interval too — he is off the pitch just as surely.

Offline; the scrape is the only network step. Idempotent per match.

    python manage.py import_sofascore_intervals --competition-season 2
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from realdata.models import (
    INTERVAL_FINAL_WHISTLE, INTERVAL_RED_CARD, INTERVAL_STARTING_XI,
    INTERVAL_SUBSTITUTION_OFF, INTERVAL_SUBSTITUTION_ON,
    Match, MatchAppearance, Player, PlayerOnPitchInterval, PROVIDER_SOFASCORE,
    SIDE_AWAY, SIDE_HOME,
)

FULL_TIME = 90


class Command(BaseCommand):
    help = "Build PlayerOnPitchInterval for a SofaScore season from cached incidents."

    def add_arguments(self, parser):
        parser.add_argument("--competition-season", type=int, required=True)
        parser.add_argument("--cache-dir", default=None)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **o):
        cache = Path(o["cache_dir"] or settings.VFOOT_SOFASCORE_CACHE)
        matches = list(Match.objects.filter(competition_season_id=o["competition_season"])
                       .exclude(external_id="")
                       .select_related("home_team", "away_team"))
        if not matches:
            raise CommandError(f"No matches for season {o['competition_season']}")

        made = missing = skipped = 0
        subs_seen = reds_seen = 0
        for match in matches:
            path = cache / f"api_v1_event_{match.external_id}_incidents.json"
            if not path.exists():
                missing += 1
                continue
            raw = json.loads(path.read_text())
            rows = raw if isinstance(raw, list) else raw.get("incidents", [])

            # side -> {player_id: (start, start_reason)} while we walk the timeline
            appearances = {(a["player_id"]): a for a in MatchAppearance.objects
                           .filter(match=match).values("player_id", "side",
                                                       "is_starter", "minutes_played")}
            ext_to_local = {}
            for pid, ext in (Player.objects.filter(id__in=appearances)
                             .exclude(external_id="")
                             .values_list("id", "external_id")):
                ext_to_local[str(ext)] = pid

            start = {pid: (0, INTERVAL_STARTING_XI)
                     for pid, a in appearances.items() if a["is_starter"]}
            end: dict[int, tuple[int, str]] = {}
            for inc in sorted(rows, key=lambda r: (r.get("time") or 0)):
                kind = inc.get("incidentType")
                minute = inc.get("time")
                if minute is None:
                    continue
                if kind == "substitution":
                    subs_seen += 1
                    pin = ext_to_local.get(str((inc.get("playerIn") or {}).get("id")))
                    pout = ext_to_local.get(str((inc.get("playerOut") or {}).get("id")))
                    if pin is not None:
                        start[pin] = (int(minute), INTERVAL_SUBSTITUTION_ON)
                    if pout is not None:
                        end[pout] = (int(minute), INTERVAL_SUBSTITUTION_OFF)
                elif kind == "card" and str(inc.get("incidentClass", "")).lower() in (
                        "red", "redyellow", "yellowred"):
                    reds_seen += 1
                    pid = ext_to_local.get(str((inc.get("player") or {}).get("id")))
                    if pid is not None:
                        end[pid] = (int(minute), INTERVAL_RED_CARD)

            rows_out = []
            for pid, (s_min, s_reason) in start.items():
                a = appearances.get(pid)
                if a is None:
                    continue
                e_min, e_reason = end.get(pid, (FULL_TIME, INTERVAL_FINAL_WHISTLE))
                if e_min < s_min:          # provider inconsistency: trust nothing
                    skipped += 1
                    continue
                ts = match.home_team if a["side"] == SIDE_HOME else match.away_team
                rows_out.append(PlayerOnPitchInterval(
                    match=match, player_id=pid, team_season=ts, team_side=a["side"],
                    start_minute=s_min, start_elapsed_seconds=s_min * 60,
                    end_minute=e_min, end_elapsed_seconds=e_min * 60,
                    start_reason=s_reason, end_reason=e_reason,
                    provider=PROVIDER_SOFASCORE))
            if not o["dry_run"]:
                with transaction.atomic():
                    PlayerOnPitchInterval.objects.filter(
                        match=match, provider=PROVIDER_SOFASCORE).delete()
                    PlayerOnPitchInterval.objects.bulk_create(rows_out, batch_size=500)
            made += len(rows_out)

        self.stdout.write(f"partite trattate      : {len(matches) - missing}")
        self.stdout.write(f"incidents mancanti    : {missing}")
        self.stdout.write(f"sostituzioni lette    : {subs_seen}")
        self.stdout.write(f"espulsioni lette      : {reds_seen}")
        self.stdout.write(f"intervalli {'da creare' if o['dry_run'] else 'creati'}  : {made}")
        if skipped:
            self.stdout.write(self.style.WARNING(
                f"scartati per incoerenza del provider: {skipped}"))
