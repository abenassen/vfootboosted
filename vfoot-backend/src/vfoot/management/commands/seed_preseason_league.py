"""Seed a PRE-SEASON league on a real championship that hasn't started yet.

Unlike ``seed_classic_demo_league`` (which scores a concluded season), this builds
a league on an UPCOMING season — e.g. Serie A 2026/27 — so the real-data pages can
be exercised before a ball is kicked:

  * Listone  -> the championship pool with ownership (owned vs svincolato)
  * Serie A  -> calendar/results of the reference championship

Squads are snake-drafted from the CURRENT eligible pool (open Transfermarkt
stints), ordered by value = average voto puro of the most recent season WITH data,
so the draft is realistic. No fixtures are scored (the season hasn't started).

    python manage.py seed_preseason_league --competition-season 3 --owner andrea
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from realdata.models import CompetitionSeason, Player
from vfoot.models import (
    CompetitionTeam,
    FantasyCompetition,
    FantasyFixture,
    FantasyLeague,
    FantasyMatchday,
    FantasyRosterSlot,
    FantasyTeam,
    LeagueMembership,
    LeaguePlayerRole,
    SavedLineupSnapshot,
)
from vfoot.services.fantasy_simulation import generate_round_robin_fixtures
from vfoot.services.listone import eligible_player_ids, snapshot_league_listone
from vfoot.services.player_ratings import latest_market_values, player_values

SQUAD = {"POR": 3, "DIF": 8, "CEN": 8, "ATT": 6}  # 25 per team


class Command(BaseCommand):
    help = "Seed a pre-season league (rosters drafted from the current pool)."

    def add_arguments(self, parser):
        parser.add_argument("--owner", default="andrea")
        parser.add_argument("--competition-season", type=int, default=3,
                            help="CompetitionSeason id (default 3 = Serie A 26/27).")
        parser.add_argument("--league-name", default=None,
                            help="Default: 'Lega <competizione> <stagione>'.")
        parser.add_argument("--competition-name", default="Campionato")
        parser.add_argument("--teams", type=int, default=10)
        parser.add_argument("--seed", type=int, default=42)

    # -- draft ------------------------------------------------------------

    def _draft(self, cs, team_count):
        """Snake-draft squads from the eligible pool, best-value first per role."""
        pool = eligible_player_ids(cs.id)
        if not pool:
            raise CommandError(
                f"Pool vuoto per {cs}: esegui prima import_transfermarkt_squads.")
        # Unified value: measured voto where available, else estimated from the
        # market — so newcomers are drafted on their merit instead of last.
        values, _prev_cs, _fit = player_values(cs, latest_market_values(pool))

        by_role: dict[str, list] = {r: [] for r in SQUAD}
        spare: list = []
        for p in Player.objects.filter(id__in=pool).values("id", "classic_role"):
            row = (p["id"], (values.get(p["id"]) or {}).get("estimated_value"))
            if p["classic_role"] in by_role:
                by_role[p["classic_role"]].append(row)
            else:
                spare.append(row)
        for r in by_role:
            by_role[r].sort(key=lambda t: (t[1] is None, -(t[1] or 0)))
        spare.sort(key=lambda t: (t[1] is None, -(t[1] or 0)))

        squads: list[list[dict]] = [[] for _ in range(team_count)]
        for role, per_team in SQUAD.items():
            queue = by_role[role]
            for pick in range(per_team):
                order = range(team_count) if pick % 2 == 0 else reversed(range(team_count))
                for t in order:
                    if not queue:
                        queue = spare  # role exhausted -> fall back to any player
                    if not queue:
                        break
                    pid, val = queue.pop(0)
                    squads[t].append({"player_id": pid,
                                      "price": max(1, int(round((val or 5.5) * 10)) - 50)})
        return squads

    # -- main -------------------------------------------------------------

    @transaction.atomic
    def handle(self, *args, **opts):
        owner = User.objects.filter(username=opts["owner"]).first()
        if not owner:
            raise CommandError(f"Utente '{opts['owner']}' inesistente.")
        try:
            cs = CompetitionSeason.objects.get(id=opts["competition_season"])
        except CompetitionSeason.DoesNotExist:
            raise CommandError(f"CompetitionSeason id={opts['competition_season']} inesistente.")

        team_count = int(opts["teams"])
        league_name = opts["league_name"] or f"Lega {cs}"

        squads = self._draft(cs, team_count)

        # teardown a previous run with the same name+owner
        for prior in FantasyLeague.objects.filter(name=league_name, owner=owner):
            FantasyFixture.objects.filter(competition__league=prior).delete()
            CompetitionTeam.objects.filter(competition__league=prior).delete()
            FantasyRosterSlot.objects.filter(team__league=prior).delete()
            LeaguePlayerRole.objects.filter(league=prior).delete()
            SavedLineupSnapshot.objects.filter(league_id=str(prior.id)).delete()
            FantasyTeam.objects.filter(league=prior).delete()
            LeagueMembership.objects.filter(league=prior).delete()
            FantasyMatchday.objects.filter(league=prior).delete()
            FantasyCompetition.objects.filter(league=prior).delete()
            prior.delete()

        league = FantasyLeague.objects.create(
            name=league_name, owner=owner, market_open=True,
            mode=FantasyLeague.MODE_CLASSIC, reference_season=cs)
        competition = FantasyCompetition.objects.create(
            league=league, name=str(opts["competition_name"]),
            competition_type=FantasyCompetition.TYPE_ROUND_ROBIN)

        for i in range(team_count):
            if i == 0:
                membership, _ = LeagueMembership.objects.get_or_create(
                    league=league, user=owner,
                    defaults={"role": LeagueMembership.ROLE_ADMIN})
            else:
                user, created = User.objects.get_or_create(username=f"preseason_mgr_{i}")
                if created:
                    user.set_unusable_password()
                    user.save()
                membership = LeagueMembership.objects.create(
                    league=league, user=user, role=LeagueMembership.ROLE_MANAGER)
            team = FantasyTeam.objects.create(
                league=league, manager=membership, name=f"Team {i + 1}")
            CompetitionTeam.objects.create(competition=competition, team=team,
                                           source=CompetitionTeam.SOURCE_MANUAL)
            FantasyRosterSlot.objects.bulk_create(
                [FantasyRosterSlot(team=team, player_id=p["player_id"],
                                   purchase_price=p["price"]) for p in squads[i]])

        # freeze the listone (roles fixed at season start; additive)
        snap = snapshot_league_listone(league)
        n_fixtures = generate_round_robin_fixtures(competition, seed=int(opts["seed"]))

        # Map fantasy round N -> real matchday N and link every fixture to it.
        # Without this a fixture has no real matchday, and the UI cannot offer
        # "Imposta formazione" — which is the whole point of a pre-season league.
        rounds = sorted(set(FantasyFixture.objects
                            .filter(competition=competition)
                            .values_list("round_no", flat=True)))
        matchday_by_round = {
            rnd: FantasyMatchday.objects.create(
                league=league, real_competition_season=cs, real_matchday=rnd)
            for rnd in rounds
        }
        for rnd, md in matchday_by_round.items():
            FantasyFixture.objects.filter(competition=competition, round_no=rnd).update(
                fantasy_matchday=md)

        self.stdout.write(self.style.SUCCESS(
            f"Lega '{league.name}' (id {league.id}) creata su {cs}.\n"
            f"  squadre: {team_count} · rose: {sum(len(s) for s in squads)} slot\n"
            f"  listone congelato: {snap}\n"
            f"  competizione '{competition.name}' (id {competition.id}): "
            f"{n_fixtures} partite non giocate\n"
            f"  owner: {owner.username} (Team 1)"))
