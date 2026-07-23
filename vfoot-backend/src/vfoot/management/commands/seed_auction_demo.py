"""Seed a CLASSIC league ready for an AUCTION test: 3 users, empty rosters, a
frozen listone. Prints login credentials + DRF tokens so the room can be driven
from two browsers (or a browser + API).

    python manage.py seed_auction_demo

Idempotent: drops and recreates the league named 'Asta Test' owned by the demo admin.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from rest_framework.authtoken.models import Token

from realdata.models import CompetitionSeason
from vfoot.models import (
    AuctionSession, FantasyLeague, FantasyTeam, LeagueMembership, LeaguePlayerRole,
)
from vfoot.services.league_decisions import accept_all_proposals
from vfoot.services.listone import snapshot_league_listone

USERS = [
    ("asta_admin", "Banditore", LeagueMembership.ROLE_ADMIN),
    ("asta_mario", "Mario", LeagueMembership.ROLE_MANAGER),
    ("asta_luigi", "Luigi", LeagueMembership.ROLE_MANAGER),
]
PASSWORD = "astatest123"
LEAGUE_NAME = "Asta Test"


class Command(BaseCommand):
    help = "Seed a classic league with empty rosters + frozen listone for auction testing."

    def add_arguments(self, parser):
        parser.add_argument("--season", type=int, default=None,
                            help="CompetitionSeason id (default: the one with the most frozen roles).")

    @transaction.atomic
    def handle(self, *args, **opts):
        season_id = opts.get("season")
        if season_id:
            season = CompetitionSeason.objects.filter(id=season_id).first()
        else:
            # Prefer a season that actually has season-wide roles to snapshot.
            season = (CompetitionSeason.objects
                      .filter(player_roles__isnull=False).distinct()
                      .order_by("-id").first())
        if not season:
            raise CommandError("No CompetitionSeason with roles found; import data first.")

        # Users (verified, so they can log in through the SPA).
        users = {}
        for username, first, _role in USERS:
            u, _ = User.objects.get_or_create(
                username=username, defaults={"first_name": first, "email": f"{username}@example.com"})
            u.set_password(PASSWORD)
            u.is_active = True
            u.save()
            users[username] = u

        owner = users["asta_admin"]

        # Fresh league. Teams PROTECT memberships, so drop them before the league.
        for lg in FantasyLeague.objects.filter(name=LEAGUE_NAME, owner=owner):
            AuctionSession.objects.filter(league=lg).delete()
            FantasyTeam.objects.filter(league=lg).delete()
            lg.delete()
        league = FantasyLeague.objects.create(
            name=LEAGUE_NAME, owner=owner, mode=FantasyLeague.MODE_CLASSIC,
            reference_season=season, initial_budget=1000,
            slots_gk=3, slots_def=8, slots_mid=8, slots_fwd=6)

        for username, _first, role in USERS:
            m = LeagueMembership.objects.create(league=league, user=users[username], role=role)
            FantasyTeam.objects.create(league=league, manager=m, name=f"{users[username].first_name} FC")

        summary = snapshot_league_listone(league)
        # Settle any role questions the snapshot opened, so the whole listone is
        # auction-eligible (an undecided player would block the pool otherwise).
        accepted = accept_all_proposals(league, user=owner)
        by_role = {r: LeaguePlayerRole.objects.filter(league=league, role=r).count()
                   for r in ("POR", "DIF", "CEN", "ATT")}

        self.stdout.write(self.style.SUCCESS(
            f"League '{LEAGUE_NAME}' id={league.id} on {season} — listone {sum(by_role.values())} "
            f"(POR {by_role['POR']} / DIF {by_role['DIF']} / CEN {by_role['CEN']} / ATT {by_role['ATT']})"))
        self.stdout.write(f"snapshot: {summary} (auto-accepted {accepted} role decisions)")
        self.stdout.write("")
        self.stdout.write("Users (password: %s):" % PASSWORD)
        for username, _first, role in USERS:
            token, _ = Token.objects.get_or_create(user=users[username])
            self.stdout.write(f"  {username:12s} [{role:7s}] token={token.key}")
        # Make sure no stale active auction lingers from a previous run.
        AuctionSession.objects.filter(league=league).delete()
