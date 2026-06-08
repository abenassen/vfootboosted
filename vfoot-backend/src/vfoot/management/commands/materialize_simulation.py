"""Materialize the historical Vfoot dry-run simulation into the real league
tables, so the app manages it as an actual league.

Creates: a FantasyLeague (owner = --owner, default simviewer, who also manages
the first team), one User+membership per other manager, FantasyTeams + rosters,
a round-robin FantasyCompetition with matchdays and finished fixtures (goals in
home_total/away_total), per-team lineup submissions, and a rich
FantasyFixtureDetail payload per fixture for the match-detail UI.

Idempotent: re-running replaces the previously materialized league of the same
name owned by the same user.
"""

from __future__ import annotations

import json
import os

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from realdata.models import CompetitionSeason, Player
from vfoot.models import (
    CompetitionTeam,
    FantasyCompetition,
    FantasyFixture,
    FantasyFixtureDetail,
    FantasyLeague,
    FantasyLineupSubmission,
    FantasyMatchday,
    FantasyRosterSlot,
    FantasyTeam,
    LeagueMembership,
)


class Command(BaseCommand):
    help = "Materialize the historical dry-run simulation artifact into real league tables."

    def add_arguments(self, parser):
        parser.add_argument("--owner", default="simviewer", help="Username that owns/admins the league and manages the first team.")
        parser.add_argument("--artifact", default="calibration/historical_vfoot_league_dry_run.json")
        parser.add_argument("--league-name", default="Lega Storica · Serie A 2015/16")
        parser.add_argument("--competition-name", default="Campionato")

    @transaction.atomic
    def handle(self, *args, **options):
        report = self._load_artifact(str(options["artifact"]))
        season = CompetitionSeason.objects.order_by("id").first()
        if season is None:
            raise CommandError("No CompetitionSeason found; import StatsBomb data first.")

        owner, _ = User.objects.get_or_create(username=str(options["owner"]))
        league_name = str(options["league_name"])

        # Idempotent: drop any prior materialization with the same name+owner.
        # PROTECT FKs (team↔fixture, membership↔team) force an explicit order.
        for prior in FantasyLeague.objects.filter(name=league_name, owner=owner):
            FantasyFixture.objects.filter(competition__league=prior).delete()  # cascades detail + lineups
            CompetitionTeam.objects.filter(competition__league=prior).delete()
            FantasyRosterSlot.objects.filter(team__league=prior).delete()
            FantasyTeam.objects.filter(league=prior).delete()
            LeagueMembership.objects.filter(league=prior).delete()
            FantasyMatchday.objects.filter(league=prior).delete()
            FantasyCompetition.objects.filter(league=prior).delete()
            prior.delete()

        league = FantasyLeague.objects.create(name=league_name, owner=owner, market_open=False)
        competition = FantasyCompetition.objects.create(
            league=league,
            name=str(options["competition_name"]),
            competition_type=FantasyCompetition.TYPE_ROUND_ROBIN,
            status=FantasyCompetition.STATUS_DONE,
        )

        now = timezone.now()
        real_matchdays = sorted({int(fx["real_matchday"]) for fx in report["fixtures"]})
        matchday_by_real = {
            rm: FantasyMatchday.objects.create(
                league=league,
                real_competition_season=season,
                real_matchday=rm,
                status=FantasyMatchday.STATUS_CONCLUDED,
                concluded_at=now,
                concluded_by=owner,
            )
            for rm in real_matchdays
        }

        valid_player_ids = set(Player.objects.values_list("id", flat=True))

        # Teams: first team -> owner (admin); the rest -> generated manager users.
        team_by_name: dict[str, FantasyTeam] = {}
        for index, sim_team in enumerate(report["teams"]):
            name = str(sim_team["name"])
            if index == 0:
                membership, _ = LeagueMembership.objects.get_or_create(
                    league=league, user=owner, defaults={"role": LeagueMembership.ROLE_ADMIN}
                )
            else:
                username = "sim_" + name.lower().replace(" ", "_")
                user, created = User.objects.get_or_create(username=username)
                if created:
                    user.set_unusable_password()
                    user.save()
                membership = LeagueMembership.objects.create(
                    league=league, user=user, role=LeagueMembership.ROLE_MANAGER
                )
            team = FantasyTeam.objects.create(league=league, manager=membership, name=name)
            team_by_name[name] = team
            CompetitionTeam.objects.create(
                competition=competition, team=team, source=CompetitionTeam.SOURCE_MANUAL
            )
            FantasyRosterSlot.objects.bulk_create(
                [
                    FantasyRosterSlot(team=team, player_id=p["player_id"], purchase_price=int(p["price"]))
                    for p in sim_team.get("roster", [])
                    if p["player_id"] in valid_player_ids
                ]
            )

        # Fixtures + rich detail + lineup submissions.
        fixtures = 0
        for fx in report["fixtures"]:
            home = team_by_name[str(fx["home_team"])]
            away = team_by_name[str(fx["away_team"])]
            fixture = FantasyFixture.objects.create(
                competition=competition,
                fantasy_matchday=matchday_by_real[int(fx["real_matchday"])],
                round_no=int(fx["fantasy_round"]),
                leg_no=1,
                home_team=home,
                away_team=away,
                status=FantasyFixture.STATUS_FINISHED,
                home_total=float(fx["home_goals"]),  # standings use goals
                away_total=float(fx["away_goals"]),
            )
            payload = dict(fx)
            payload["fixture_id"] = fixture.id
            payload["result"] = (
                "home" if fx["home_goals"] > fx["away_goals"] else "away" if fx["away_goals"] > fx["home_goals"] else "draw"
            )
            FantasyFixtureDetail.objects.create(
                fixture=fixture,
                vfoot_home=float(fx["home_score"]),
                vfoot_away=float(fx["away_score"]),
                payload=payload,
            )
            for side_key, team in (("home_lineup", home), ("away_lineup", away)):
                lineup = fx[side_key]
                gk_id = next((s["player_id"] for s in lineup["starters"] if s.get("is_goalkeeper")), None)
                FantasyLineupSubmission.objects.create(
                    fixture=fixture,
                    team=team,
                    gk_player_id=gk_id if gk_id in valid_player_ids else None,
                    starter_player_ids=[s["player_id"] for s in lineup["starters"]],
                    bench_player_ids=[s["player_id"] for s in lineup["bench"]],
                    submitted_by=owner,
                )
            fixtures += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Materialized league '{league.name}' (id {league.id}): "
                f"{len(team_by_name)} teams, {len(matchday_by_real)} matchdays, {fixtures} fixtures. "
                f"Owner/admin: {owner.username} (manages '{report['teams'][0]['name']}')."
            )
        )

    def _load_artifact(self, path: str) -> dict:
        if not os.path.isabs(path):
            path = os.path.join(os.path.dirname(str(settings.BASE_DIR)), path)
        if not os.path.exists(path):
            raise CommandError(f"Artifact not found: {path}. Run simulate_historical_vfoot_league first.")
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
