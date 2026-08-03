"""The three shapes a league actually builds, end to end.

1. a championship: everyone against everyone, over N tornate;
2. a cup whose field is the top of the championship at a given round;
3. a group followed by a play-off, fed the same way.

What is checked is what used to break: round numbers colliding between stages,
"tornate" being stuck at two, a qualification pointing at a round that does not
exist, and a cup scheduled to start before the round that decides who plays it.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from realdata.models import Competition, CompetitionSeason, Season, Team, TeamSeason, Match
from vfoot.models import (
    CompetitionStage,
    FantasyCompetition,
    FantasyFixture,
    FantasyLeague,
    FantasyTeam,
    LeagueMembership,
)
from vfoot.services import competition_calendar
from vfoot.services.competition_stages import competition_round_rows


def _make_season(matchdays: int = 38) -> CompetitionSeason:
    comp = Competition.objects.create(external_id="23", name="Serie A")
    cs = CompetitionSeason.objects.create(
        competition=comp, season=Season.objects.create(code="2025-2026"), name="Serie A 2025-2026"
    )
    home = TeamSeason.objects.create(
        team=Team.objects.create(external_id="h", name="Home FC"), competition_season=cs
    )
    away = TeamSeason.objects.create(
        team=Team.objects.create(external_id="a", name="Away FC"), competition_season=cs
    )
    # RELATIVE to now, and in the future. These tests are about structure — round
    # numbering, qualification rules, calendar constraints — and none of them means
    # to describe a season that has already been played. With a fixed 2025 date they
    # did exactly that as soon as the wall clock passed it, and a season entirely in
    # the past is a different thing with different rules (nothing can be fielded any
    # more), which is not what any assertion here is checking.
    base = timezone.now() + timedelta(days=1)
    Match.objects.bulk_create(
        [
            Match(
                competition_season=cs,
                external_id=f"m{md}",
                matchday=md,
                home_team=home,
                away_team=away,
                kickoff=base + timedelta(days=7 * md),
            )
            for md in range(1, matchdays + 1)
        ]
    )
    return cs


class CompetitionWizardTests(TestCase):
    def setUp(self):
        self.season = _make_season()
        self.admin = User.objects.create_user("admin", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(
            "/api/v1/leagues",
            {"name": "Prova", "team_name": "Alpha", "reference_season_id": self.season.id},
            format="json",
        )
        self.league = FantasyLeague.objects.get(id=r.json()["league_id"])
        # Seven more managers, for eight teams in all.
        for i in range(7):
            user = User.objects.create_user(f"m{i}", password="x")
            m = LeagueMembership.objects.create(league=self.league, user=user, role="manager")
            FantasyTeam.objects.create(league=self.league, manager=m, name=f"Team {i}")
        self.team_ids = list(FantasyTeam.objects.filter(league=self.league).values_list("id", flat=True))

    # -- helpers ---------------------------------------------------------

    def _wizard(self, **payload):
        return self.client.post(
            f"/api/v1/leagues/{self.league.id}/competitions/wizard", payload, format="json"
        )

    def _play_through(self, comp: FantasyCompetition, up_to_round: int, winners_first=True):
        """Give every fixture up to a round a result, best team first."""
        order = {tid: i for i, tid in enumerate(self.team_ids)}
        for fx in FantasyFixture.objects.filter(competition=comp, round_no__lte=up_to_round):
            home_better = order[fx.home_team_id] < order[fx.away_team_id]
            fx.home_total = 3.0 if home_better == winners_first else 1.0
            fx.away_total = 1.0 if home_better == winners_first else 3.0
            fx.status = FantasyFixture.STATUS_FINISHED
            fx.save(update_fields=["home_total", "away_total", "status"])

    # -- 1. championship -------------------------------------------------

    def test_league_with_three_legs(self):
        r = self._wizard(
            name="Campionato",
            format="league",
            team_ids=self.team_ids,
            legs=3,
            start_matchday=1,
            prizes=[{"name": "Scudetto", "icon": "🏆", "condition": "winner"}],
        )
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        # 8 teams: 7 rounds per leg, three legs over.
        self.assertEqual(body["competition"]["rounds"][-1]["round_no"], 21)
        self.assertEqual(len(body["competition"]["rounds"]), 21)
        self.assertEqual(body["stages"][0]["legs"], 3)
        self.assertEqual(body["stages"][0]["planned_rounds"], 21)
        # Every pairing played three times, home and away swapping each leg.
        comp = FantasyCompetition.objects.get(id=body["competition"]["competition_id"])
        self.assertEqual(FantasyFixture.objects.filter(competition=comp).count(), 28 * 3)
        first = FantasyFixture.objects.filter(competition=comp, round_no=1).first()
        ret = FantasyFixture.objects.filter(
            competition=comp, round_no=8, home_team_id=first.away_team_id, away_team_id=first.home_team_id
        )
        self.assertTrue(ret.exists(), "la seconda tornata deve invertire il campo")
        # One real matchday per round, never two rounds on the same one.
        calendar = comp.round_calendar
        self.assertEqual(len(set(calendar.values())), 21)
        self.assertEqual(body["competition"]["prizes"][0]["name"], "Scudetto")

    def test_legs_cannot_exceed_the_cap(self):
        r = self._wizard(name="Troppo", format="league", team_ids=self.team_ids, legs=9)
        self.assertEqual(r.status_code, 400)

    # -- 2. cup fed by the championship ----------------------------------

    def _championship(self, legs=2, start=1):
        r = self._wizard(
            name="Campionato", format="league", team_ids=self.team_ids, legs=legs, start_matchday=start
        )
        self.assertEqual(r.status_code, 201, r.content)
        comp = FantasyCompetition.objects.get(id=r.json()["competition"]["competition_id"])
        stage = CompetitionStage.objects.get(competition=comp)
        return comp, stage

    def test_cup_qualified_from_the_table_after_a_round(self):
        champ, champ_stage = self._championship()
        r = self._wizard(
            name="Coppa dei Campioni",
            format="cup",
            qualification={
                "source_stage_id": champ_stage.id,
                "mode": "table_range",
                "source_round": 7,
                "rank_from": 1,
                "rank_to": 4,
            },
            prizes=[{"name": "Coppa", "icon": "🏆", "condition": "winner"}],
        )
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        cup = FantasyCompetition.objects.get(id=body["competition"]["competition_id"])

        # A bracket for four: semifinals then final, two rounds, no fixtures yet.
        self.assertEqual([s["name"] for s in body["stages"]], ["Semifinali", "Finale"])
        self.assertEqual(body["competition"]["fixtures"]["total"], 0)
        # ...but a calendar already, and one that cannot start before round 7 of
        # the championship has been played.
        champ_md_7 = champ.round_calendar["7"]
        self.assertTrue(cup.round_calendar, "la coppa deve avere un calendario anche senza partecipanti")
        self.assertGreater(min(int(v) for v in cup.round_calendar.values()), champ_md_7)
        self.assertEqual(body["competition"]["dependencies"][0]["source_round"], 7)

    def test_cup_cannot_point_at_a_round_that_does_not_exist(self):
        _, champ_stage = self._championship(legs=1)  # 7 rounds only
        r = self._wizard(
            name="Coppa",
            format="cup",
            qualification={
                "source_stage_id": champ_stage.id,
                "mode": "table_range",
                "source_round": 19,
                "rank_from": 1,
                "rank_to": 4,
            },
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn("19", r.json()["detail"])

    def test_cup_start_is_pushed_past_its_qualification(self):
        champ, champ_stage = self._championship()
        r = self._wizard(
            name="Coppa",
            format="cup",
            qualification={
                "source_stage_id": champ_stage.id,
                "mode": "table_range",
                "source_round": 7,
                "rank_from": 1,
                "rank_to": 4,
            },
            # Asking for matchday 2 — before the round that decides the field.
            start_matchday=2,
        )
        self.assertEqual(r.status_code, 201, r.content)
        cup = FantasyCompetition.objects.get(id=r.json()["competition"]["competition_id"])
        self.assertGreater(cup.start_matchday, champ.round_calendar["7"])
        floor, reasons = competition_calendar.earliest_start_matchday(cup)
        self.assertEqual(floor, champ.round_calendar["7"] + 1)
        self.assertTrue(reasons)

    def test_cup_fills_itself_when_the_source_round_is_played(self):
        champ, champ_stage = self._championship()
        r = self._wizard(
            name="Coppa",
            format="cup",
            qualification={
                "source_stage_id": champ_stage.id,
                "mode": "table_range",
                "source_round": 7,
                "rank_from": 1,
                "rank_to": 4,
            },
        )
        cup = FantasyCompetition.objects.get(id=r.json()["competition"]["competition_id"])
        self.assertEqual(FantasyFixture.objects.filter(competition=cup).count(), 0)

        self._play_through(champ, 7)
        from vfoot.services.competition_stages import resolve_pending_stages

        resolve_pending_stages(cup)
        semis = FantasyFixture.objects.filter(competition=cup)
        self.assertEqual(semis.count(), 2, "quattro qualificate = due semifinali")
        # And they land on the matchdays the plan had already reserved.
        for fx in semis:
            self.assertIsNotNone(fx.fantasy_matchday_id)
            self.assertEqual(
                fx.fantasy_matchday.real_matchday, int(cup.round_calendar[str(fx.round_no)])
            )

    def test_partial_source_does_not_qualify_anybody(self):
        champ, champ_stage = self._championship()
        r = self._wizard(
            name="Coppa",
            format="cup",
            qualification={
                "source_stage_id": champ_stage.id,
                "mode": "table_range",
                "source_round": 7,
                "rank_from": 1,
                "rank_to": 4,
            },
        )
        cup = FantasyCompetition.objects.get(id=r.json()["competition"]["competition_id"])
        self._play_through(champ, 3)  # round 7 still unplayed
        from vfoot.services.competition_stages import resolve_pending_stages

        resolve_pending_stages(cup)
        self.assertEqual(FantasyFixture.objects.filter(competition=cup).count(), 0)

    # -- 3. group + play-off ---------------------------------------------

    def test_group_then_playoff_numbers_its_rounds_in_sequence(self):
        champ, champ_stage = self._championship()
        r = self._wizard(
            name="Champions",
            format="groups_knockout",
            qualification={
                "source_stage_id": champ_stage.id,
                "mode": "table_range",
                "source_round": 7,
                "rank_from": 1,
                "rank_to": 4,
            },
            groups=1,
            advance_per_group=2,
            legs=1,
            prizes=[
                {"name": "Champions", "icon": "🏆", "condition": "winner"},
                {"name": "Finalista", "icon": "🥈", "condition": "runner_up"},
            ],
        )
        self.assertEqual(r.status_code, 201, r.content)
        body = r.json()
        self.assertEqual([s["name"] for s in body["stages"]], ["Girone unico", "Finale"])

        cup = FantasyCompetition.objects.get(id=body["competition"]["competition_id"])
        rows = competition_round_rows(cup)
        # Four in a group is three rounds; the final is the fourth. The bug this
        # guards: the final used to be numbered round 1 again, colliding with the
        # group's first round on the same calendar slot.
        self.assertEqual([row["round_no"] for row in rows], [1, 2, 3, 4])
        group, final = CompetitionStage.objects.filter(competition=cup).order_by("order_index")
        self.assertEqual(group.round_offset, 0)
        self.assertEqual(group.planned_rounds, 3)
        self.assertEqual(final.round_offset, 3)
        self.assertEqual(len(set(cup.round_calendar.values())), 4)

        # Play the championship: the group fills, then the final fills from it.
        self._play_through(champ, 7)
        from vfoot.services.competition_stages import resolve_pending_stages

        resolve_pending_stages(cup)
        self.assertEqual(FantasyFixture.objects.filter(stage=group).count(), 6)
        self.assertEqual(
            sorted(FantasyFixture.objects.filter(stage=group).values_list("round_no", flat=True).distinct()),
            [1, 2, 3],
        )
        self._play_through(cup, 3)
        resolve_pending_stages(cup)
        final_fixtures = FantasyFixture.objects.filter(stage=final)
        self.assertEqual(final_fixtures.count(), 1)
        self.assertEqual(final_fixtures.first().round_no, 4)

    def test_two_groups_share_their_rounds(self):
        r = self._wizard(
            name="Mondiale",
            format="groups_knockout",
            team_ids=self.team_ids,
            groups=2,
            advance_per_group=2,
            legs=1,
        )
        self.assertEqual(r.status_code, 201, r.content)
        comp = FantasyCompetition.objects.get(id=r.json()["competition"]["competition_id"])
        a, b = CompetitionStage.objects.filter(competition=comp, stage_type="round_robin").order_by("id")
        # Played side by side: same rounds, same real matchdays.
        self.assertEqual(a.round_offset, b.round_offset)
        self.assertEqual(a.planned_rounds, b.planned_rounds)
        rounds = competition_round_rows(comp)
        self.assertEqual([row["round_no"] for row in rounds], [1, 2, 3, 4, 5])
        self.assertEqual(rounds[0]["stage_name"], "Girone A / Girone B")

    # -- editing ---------------------------------------------------------

    def test_structure_is_frozen_once_a_result_exists(self):
        comp, stage = self._championship(legs=1)
        self._play_through(comp, 1)
        r = self.client.patch(f"/api/v1/stages/{stage.id}", {"legs": 2}, format="json")
        self.assertEqual(r.status_code, 400)
        self.assertIn("locked_fields", r.json())
        # The name is still free.
        r = self.client.patch(f"/api/v1/stages/{stage.id}", {"name": "Serie A Lega"}, format="json")
        self.assertEqual(r.status_code, 200)

    def test_calendar_fine_tuning_keeps_rounds_in_order(self):
        comp, _ = self._championship(legs=1)
        # Ask for round 3 to be played before round 2: refused and re-placed.
        r = self.client.post(
            f"/api/v1/competitions/{comp.id}/schedule",
            {"round_mapping": {"3": 1}},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        mapping = r.json()["mapped_rounds"]
        matchdays = [mapping[str(k)] if str(k) in mapping else mapping[k] for k in sorted(map(int, mapping))]
        self.assertEqual(matchdays, sorted(matchdays))
        self.assertEqual(len(set(matchdays)), len(matchdays))
        self.assertTrue(r.json()["warnings"])

    def test_a_cup_with_a_final_prize_can_still_be_deleted(self):
        _, champ_stage = self._championship()
        r = self._wizard(
            name="Coppa",
            format="cup",
            qualification={
                "source_stage_id": champ_stage.id,
                "mode": "table_range",
                "source_round": 7,
                "rank_from": 1,
                "rank_to": 4,
            },
            prizes=[{"name": "Coppa", "icon": "🏆", "condition": "winner"}],
        )
        cup_id = r.json()["competition"]["competition_id"]
        # The prize points at the final, and both cascade from the competition:
        # with the FK on PROTECT this was an integrity error, not a 204.
        delete = self.client.delete(f"/api/v1/competitions/{cup_id}")
        self.assertEqual(delete.status_code, 204)
        self.assertFalse(FantasyCompetition.objects.filter(id=cup_id).exists())

    def test_open_ended_competitions_run_back_to_back(self):
        r = self._wizard(name="Campionato", format="league", team_ids=self.team_ids, legs=1, start_matchday=1)
        comp = FantasyCompetition.objects.get(id=r.json()["competition"]["competition_id"])
        self.assertEqual([comp.round_calendar[str(n)] for n in range(1, 8)], [1, 2, 3, 4, 5, 6, 7])

    def test_an_explicit_end_spreads_the_rounds(self):
        r = self._wizard(
            name="Coppa lunga",
            format="league",
            team_ids=self.team_ids,
            legs=1,
            start_matchday=1,
            end_matchday=38,
        )
        comp = FantasyCompetition.objects.get(id=r.json()["competition"]["competition_id"])
        matchdays = [comp.round_calendar[str(n)] for n in range(1, 8)]
        self.assertEqual(matchdays[0], 1)
        self.assertEqual(matchdays[-1], 38)
        self.assertEqual(matchdays, sorted(matchdays))

    def test_a_play_in_bracket_waits_for_its_play_in(self):
        # 6 teams: 2 ties to get to 4, then semis and final. The stage that holds
        # the two byes must NOT be drawn between them while the play-in is unplayed.
        r = self._wizard(name="Coppa 6", format="cup", team_ids=self.team_ids[:6])
        self.assertEqual(r.status_code, 201, r.content)
        comp = FantasyCompetition.objects.get(id=r.json()["competition"]["competition_id"])
        stages = list(CompetitionStage.objects.filter(competition=comp).order_by("order_index"))
        self.assertEqual([s.name for s in stages], ["Turno preliminare", "Semifinali", "Finale"])
        self.assertEqual(FantasyFixture.objects.filter(stage=stages[0]).count(), 2)
        self.assertEqual(FantasyFixture.objects.filter(stage=stages[1]).count(), 0)

        self._play_through(comp, stages[0].round_offset + 1)
        from vfoot.services.competition_stages import resolve_pending_stages

        resolve_pending_stages(comp)
        self.assertEqual(FantasyFixture.objects.filter(stage=stages[1]).count(), 2)

    def test_rescheduling_never_moves_a_played_round(self):
        comp, _ = self._championship(legs=1, start=1)
        self._play_through(comp, 2)
        before = {
            fx.id: fx.fantasy_matchday_id
            for fx in FantasyFixture.objects.filter(competition=comp, round_no__lte=2)
        }
        r = self.client.post(
            f"/api/v1/competitions/{comp.id}/schedule",
            {"start_matchday": 10, "end_matchday": 38},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        after = {
            fx.id: fx.fantasy_matchday_id
            for fx in FantasyFixture.objects.filter(competition=comp, round_no__lte=2)
        }
        self.assertEqual(before, after)

    def test_prizes_are_awarded_only_once_they_are_decided(self):
        r = self._wizard(
            name="Campionato",
            format="league",
            team_ids=self.team_ids,
            legs=1,
            prizes=[{"name": "Scudetto", "icon": "🏆", "condition": "winner"}],
        )
        comp = FantasyCompetition.objects.get(id=r.json()["competition"]["competition_id"])
        detail = self.client.get(f"/api/v1/competitions/{comp.id}").json()
        self.assertEqual(detail["prizes"][0]["winner_team_ids"], [])
        self.assertEqual(detail["prizes"][0]["condition_label"], "1° in classifica finale")

        self._play_through(comp, 7)
        detail = self.client.get(f"/api/v1/competitions/{comp.id}").json()
        self.assertEqual(len(detail["prizes"][0]["winner_team_ids"]), 1)
        self.assertEqual(detail["prizes"][0]["winner_team_names"][0], "Alpha")

    def test_wizard_preview_matches_what_gets_built(self):
        r = self.client.post(
            f"/api/v1/leagues/{self.league.id}/competitions/wizard/preview",
            {"format": "league", "team_ids": self.team_ids, "legs": 2},
            format="json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["total_rounds"], 14)

        built = self._wizard(name="C", format="league", team_ids=self.team_ids, legs=2)
        self.assertEqual(len(built.json()["competition"]["rounds"]), 14)
