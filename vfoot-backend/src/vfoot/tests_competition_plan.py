"""The half of a calendar that has no teams in it yet.

A competition's rounds exist as reserved matchdays long before there are fixtures
to hang on them — that is what a cup fed by a table IS — and a calendar read off
the fixtures cannot show them at all. So a cup whose semifinals were being played
had nothing at all under "Finale" and read as finished.

What is pinned down here:

1. a planned, undrawn round is in the calendar, named, with the RULE that will
   fill it ("Le vincenti di «Semifinali»");
2. a whole undrawn PHASE is one entry, not six identical placeholders;
3. concluding a matchday actually triggers the draw — the mechanism the whole
   thing rests on;
4. and the two ways it can quietly stop: a matchday parked for a postponement,
   and one the admin never closed. Both are named, and when a phase's own dates go
   by while it waits, it is MOVED rather than drawn onto a round nobody can field.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from realdata.models import Competition, CompetitionSeason, Match, Season, Team, TeamSeason
from vfoot.models import (
    CompetitionStage,
    FantasyCompetition,
    FantasyFixture,
    FantasyLeague,
    FantasyMatchday,
    FantasyTeam,
    LeagueMembership,
)
from vfoot.services import competition_calendar, competition_plan


class CompetitionPlanTests(TestCase):
    """A season whose matchdays are all still to come, so nothing is locked until a
    test says so — every claim here is about WHEN something can be played."""

    MATCHDAYS = 38

    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.home = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(external_id="h", name="Home FC"))
        self.away = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(external_id="a", name="Away FC"))
        self.now = timezone.now()
        Match.objects.bulk_create([
            Match(competition_season=self.cs, external_id=f"m{md}", matchday=md,
                  home_team=self.home, away_team=self.away,
                  kickoff=self.now + timedelta(days=md), kickoff_provisional=False)
            for md in range(1, self.MATCHDAYS + 1)
        ])

        self.admin = User.objects.create_user("admin", password="x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        r = self.client.post(
            "/api/v1/leagues",
            {"name": "Prova", "team_name": "Alpha", "reference_season_id": self.cs.id},
            format="json",
        )
        self.league = FantasyLeague.objects.get(id=r.json()["league_id"])
        for i in range(7):
            user = User.objects.create_user(f"m{i}", password="x")
            m = LeagueMembership.objects.create(league=self.league, user=user, role="manager")
            FantasyTeam.objects.create(league=self.league, manager=m, name=f"Team {i}")
        self.team_ids = list(
            FantasyTeam.objects.filter(league=self.league).values_list("id", flat=True))

    # -- helpers -----------------------------------------------------------
    def _wizard(self, **payload):
        r = self.client.post(
            f"/api/v1/leagues/{self.league.id}/competitions/wizard", payload, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return FantasyCompetition.objects.get(id=r.json()["competition"]["competition_id"])

    def _championship(self, legs=1):
        comp = self._wizard(name="Campionato", format="league", team_ids=self.team_ids,
                            legs=legs, start_matchday=1)
        return comp, CompetitionStage.objects.get(competition=comp)

    def _cup_from_table(self, champ_stage, *, source_round=7, name="Coppa", fmt="cup", **extra):
        return self._wizard(
            name=name, format=fmt,
            qualification={"source_stage_id": champ_stage.id, "mode": "table_range",
                           "source_round": source_round, "rank_from": 1, "rank_to": 4},
            **extra,
        )

    def _play_real_matchdays(self, up_to: int):
        """Serie A itself has been played: every match settled, which is what makes a
        fantasy matchday concludable."""
        Match.objects.filter(competition_season=self.cs, matchday__lte=up_to).update(
            status=Match.STATUS_FINISHED, data_ready=True, home_goals=2, away_goals=1,
            kickoff=self.now - timedelta(hours=3))

    def _map_sources(self, competition):
        """Point each fantasy fixture at the real match of its matchday, so the
        ordinary conclusion has something to score."""
        by_md = {m.matchday: m for m in Match.objects.filter(competition_season=self.cs)}
        for fx in FantasyFixture.objects.filter(competition=competition).select_related(
                "fantasy_matchday"):
            if fx.fantasy_matchday_id:
                fx.source_real_match = by_md.get(fx.fantasy_matchday.real_matchday)
                fx.save(update_fields=["source_real_match"])

    def _conclude_through(self, real_matchday: int):
        """Close the ledger in order, exactly as the admin's button does."""
        mds = FantasyMatchday.objects.filter(
            league=self.league, real_matchday__lte=real_matchday).order_by("real_matchday")
        for md in mds:
            r = self.client.post(
                f"/api/v1/leagues/{self.league.id}/matchdays/{md.id}/conclude", {}, format="json")
            self.assertEqual(r.status_code, 200, r.content)

    def _plan_for(self, competition, stage_name):
        return next(p for p in competition_plan.stage_plan(competition)
                    if p["name"] == stage_name)

    # -- 1. the rule, said out loud ----------------------------------------
    def test_the_final_is_in_the_calendar_before_it_has_teams(self):
        cup = self._wizard(name="Coppa", format="cup", team_ids=self.team_ids[:4])
        rows = competition_plan.round_plan_rows(cup)

        semis = next(r for r in rows if r["stage_name"] == "Semifinali")
        final = next(r for r in rows if r["stage_name"] == "Finale")
        self.assertEqual(semis["fixtures"], 2)
        self.assertFalse(semis["pending"])
        # The round that was invisible: planned, dated, and with nobody in it yet.
        self.assertEqual(final["fixtures"], 0)
        self.assertTrue(final["pending"])
        self.assertEqual(final["rule_text"], "Le vincenti di «Semifinali»")
        self.assertEqual(final["expected_fixtures"], 1)
        self.assertIsNotNone(final["real_matchday"])

    def test_a_table_rule_names_the_places_and_the_cut(self):
        champ, champ_stage = self._championship()
        cup = self._cup_from_table(champ_stage)

        plan = self._plan_for(cup, "Semifinali")
        self.assertTrue(plan["pending"])
        self.assertEqual(plan["rule_text"], "Le prime 4 di «Campionato» dopo il turno 7")

    # -- 2. a whole phase, not a list of placeholders -----------------------
    def test_an_undrawn_group_phase_is_one_rule_over_all_its_rounds(self):
        champ, champ_stage = self._championship()
        cup = self._cup_from_table(champ_stage, name="Champions", fmt="groups_knockout",
                                   groups=1, advance_per_group=2, legs=1)

        group = self._plan_for(cup, "Girone unico")
        self.assertTrue(group["pending"])
        # Four teams in one group is three rounds — three rounds of the SAME promise,
        # which is exactly why they must not be shown as three empty calendars.
        self.assertEqual(group["planned_rounds"], 3)
        self.assertEqual(group["expected_fixtures_per_round"], 2)
        covered = competition_plan.pending_rounds(cup)
        self.assertEqual(
            sorted(r for r, p in covered.items() if p["stage_id"] == group["stage_id"]),
            [1, 2, 3],
        )
        # ...and the bracket behind it is pending too, on its own rule.
        final = self._plan_for(cup, "Finale")
        self.assertTrue(final["pending"])
        self.assertEqual(final["rule_text"], "Le prime 2 di «Girone unico»")

    # -- 3. the mechanism: closing a matchday draws what it decides ---------
    def test_concluding_the_deciding_matchday_draws_the_cup(self):
        champ, champ_stage = self._championship()
        cup = self._cup_from_table(champ_stage)
        self.assertEqual(FantasyFixture.objects.filter(competition=cup).count(), 0)

        self._play_real_matchdays(7)
        self._map_sources(champ)
        self._conclude_through(7)

        semis = FantasyFixture.objects.filter(competition=cup)
        self.assertEqual(semis.count(), 2, "quattro qualificate = due semifinali")
        for fx in semis:
            self.assertIsNotNone(fx.fantasy_matchday_id)
        self.assertFalse(self._plan_for(cup, "Semifinali")["pending"])

    # -- 4a. the admin who forgets ------------------------------------------
    def test_a_matchday_played_and_not_counted_is_named_as_the_blocker(self):
        """The league advances past an unclosed round by design. A competition that
        reads its table does not — and nothing used to say so."""
        champ, champ_stage = self._championship()
        cup = self._cup_from_table(champ_stage)

        self._play_real_matchdays(7)  # football is done; the ledger is not
        plan = self._plan_for(cup, "Semifinali")
        blocker = plan["blocker"]
        self.assertIsNotNone(blocker)
        self.assertEqual(blocker["kind"], "da_conteggiare")
        # The FIRST unclosed round, not the last one the rule reads: conclusions go
        # in order, so that is the one the admin has to click, and naming round 7
        # would send him at something he cannot close yet.
        self.assertEqual(blocker["real_matchday"], int(champ.round_calendar["1"]))

        impacts = competition_plan.matchday_impacts(self.league)
        waiting = impacts[int(champ.round_calendar["1"])]
        self.assertEqual([w["stage_name"] for w in waiting], ["Semifinali"])
        self.assertEqual(waiting[0]["competition_name"], "Coppa")

    def test_a_round_still_to_be_played_is_not_reported_as_a_problem(self):
        champ, champ_stage = self._championship()
        cup = self._cup_from_table(champ_stage)

        blocker = self._plan_for(cup, "Semifinali")["blocker"]
        self.assertEqual(blocker["kind"], "da_giocare")

    # -- 4b. the postponement -----------------------------------------------
    def test_a_parked_matchday_is_named_as_such(self):
        champ, champ_stage = self._championship()
        cup = self._cup_from_table(champ_stage)

        self._play_real_matchdays(7)
        self._map_sources(champ)
        self._conclude_through(6)
        md7 = FantasyMatchday.objects.get(league=self.league, real_matchday=champ.round_calendar["7"])
        r = self.client.post(
            f"/api/v1/leagues/{self.league.id}/matchdays/{md7.id}/await",
            {"awaiting": True, "reason": "Napoli-Inter rinviata"}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

        blocker = self._plan_for(cup, "Semifinali")["blocker"]
        self.assertEqual(blocker["kind"], "recupero")
        self.assertIn("recupero", blocker["detail"])
        # And the admin is told, at the moment he parks it, what he is stalling.
        self.assertEqual([d["stage_name"] for d in r.json()["decides"]], ["Semifinali"])

    def test_a_phase_that_missed_its_dates_is_moved_rather_than_drawn_in_the_past(self):
        """The paradox in full: the round that decides the cup is stuck waiting for a
        recovery, and the cup's own matchdays go by in the meantime. Drawing it where
        the plan said would produce a semifinal whose lineups locked before it
        existed."""
        champ, champ_stage = self._championship()
        cup = self._cup_from_table(champ_stage)
        planned = min(int(v) for v in cup.round_calendar.values())

        # Weeks pass: the cup's own matchdays have kicked off with nobody in them.
        Match.objects.filter(competition_season=self.cs,
                             matchday__lte=planned + 2).update(
            kickoff=self.now - timedelta(days=1))
        self._play_real_matchdays(7)
        self._map_sources(champ)
        self._conclude_through(7)

        semis = list(FantasyFixture.objects.filter(competition=cup)
                     .select_related("fantasy_matchday"))
        self.assertEqual(len(semis), 2)
        landed = {fx.fantasy_matchday.real_matchday for fx in semis}
        self.assertTrue(
            all(md > planned + 2 for md in landed),
            f"le semifinali sono finite su giornate gia' iniziate: {landed}",
        )
        # The PLAN itself was rewritten, not only the fixtures: a calendar that still
        # promised the old dates would contradict the tie hanging off it.
        cup.refresh_from_db()
        self.assertEqual(int(cup.round_calendar["1"]), min(landed))

    def test_the_cup_simply_starts_later_when_nobody_closed_the_rounds_in_time(self):
        """The sequence in full, told from the outside: the admin does not close the
        rounds that decide the cup; the matchdays the cup was booked for arrive and go
        by; then he closes.

        What must be true in the middle is that NOTHING happened — no half-drawn tie,
        no fixture on a round nobody could field, no lineup owed for a match that does
        not exist. The cup does not lose its rounds, it starts later.
        """
        champ, champ_stage = self._championship()
        cup = self._cup_from_table(champ_stage)
        booked = sorted(int(v) for v in cup.round_calendar.values())

        # Weeks of football: the championship is played, the cup's own matchdays come
        # and go, and the ledger has not moved at all.
        self._play_real_matchdays(booked[-1] + 2)
        self._map_sources(champ)

        # In the middle: the cup has no fixtures, so there was never anything to
        # field, to score, or to miss.
        self.assertEqual(FantasyFixture.objects.filter(competition=cup).count(), 0)
        self.assertEqual(
            FantasyFixture.objects.filter(
                competition=cup, fantasy_matchday__real_matchday__in=booked).count(), 0)
        blocker = self._plan_for(cup, "Semifinali")["blocker"]
        self.assertEqual(blocker["kind"], "da_conteggiare")

        # He finally closes. Only now does the cup exist — and not where it was booked.
        self._conclude_through(7)
        semis = list(FantasyFixture.objects.filter(competition=cup)
                     .select_related("fantasy_matchday"))
        self.assertEqual(len(semis), 2)
        landed = {fx.fantasy_matchday.real_matchday for fx in semis}
        self.assertTrue(all(md not in booked for md in landed),
                        f"le giornate prenotate erano gia' passate: {landed}")
        self.assertTrue(all(md > booked[-1] for md in landed))

        # No round was lost on the way: the cup still has all of them, in order.
        cup.refresh_from_db()
        plan = sorted(int(v) for v in cup.round_calendar.values())
        self.assertEqual(len(plan), len(booked))
        self.assertEqual(plan, sorted(set(plan)), "due turni sulla stessa giornata")
        # And the declared window followed, so the next `schedule` cannot drag it back.
        if cup.end_matchday is not None:
            self.assertGreaterEqual(cup.end_matchday, plan[-1])

    def test_the_declared_window_follows_the_competition_that_overran_it(self):
        """A cup told to end by matchday 9 and drawn at 12 has outlived its window.
        The window has to move with it — the admin's own calendar page re-runs
        `schedule`, which keeps only rounds INSIDE the span, so a stale end would
        drag the cup back onto rounds that have already been played."""
        champ, champ_stage = self._championship()
        cup = self._cup_from_table(champ_stage, end_matchday=9)
        self.assertEqual(cup.end_matchday, 9)

        self._play_real_matchdays(11)
        self._map_sources(champ)
        self._conclude_through(7)

        cup.refresh_from_db()
        last = max(int(v) for v in cup.round_calendar.values())
        self.assertGreater(last, 9)
        self.assertGreaterEqual(cup.end_matchday, last)
        # And the guarantee that motivates it: re-scheduling now leaves it alone.
        competition_calendar.schedule(cup)
        cup.refresh_from_db()
        self.assertEqual(max(int(v) for v in cup.round_calendar.values()), last)

    def test_a_recovery_finally_played_draws_the_phase_it_was_holding(self):
        """The postponement, end to end. The matchday is parked, the league runs on
        past it, and the cup stays undrawn the whole time — no half draw from an
        incomplete table. The recovery is played, the admin closes the parked round
        OUT of order (which is exactly what the awaiting state is for), and only then
        does the cup exist."""
        champ, champ_stage = self._championship()
        cup = self._cup_from_table(champ_stage)

        self._play_real_matchdays(7)
        self._map_sources(champ)
        self._conclude_through(6)
        md7 = FantasyMatchday.objects.get(
            league=self.league, real_matchday=int(champ.round_calendar["7"]))
        self.client.post(f"/api/v1/leagues/{self.league.id}/matchdays/{md7.id}/await",
                         {"awaiting": True, "reason": "rinviata"}, format="json")

        # The league advances past it: later rounds close, the cup does NOT fill.
        self.assertEqual(FantasyFixture.objects.filter(competition=cup).count(), 0)
        self.assertEqual(self._plan_for(cup, "Semifinali")["blocker"]["kind"], "recupero")

        # The recovery is played and the parked round is closed at last.
        r = self.client.post(
            f"/api/v1/leagues/{self.league.id}/matchdays/{md7.id}/conclude", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

        self.assertEqual(FantasyFixture.objects.filter(competition=cup).count(), 2)
        self.assertFalse(self._plan_for(cup, "Semifinali")["pending"])

    def test_the_rounds_are_compacted_not_shifted_by_a_fixed_amount(self):
        """A competition booked on 8-9-11 does not come out as 12-13-15. Each round
        asks for the FIRST free matchday after the previous one, so the gaps of the
        original plan survive only where they are still usable — which is what lets a
        three-round phase fit into the last three matchdays of a season."""
        champ, champ_stage = self._championship()
        cup = self._cup_from_table(champ_stage, name="Coppa", fmt="groups_knockout",
                                   groups=1, advance_per_group=2, legs=1)
        # Book the group's three rounds with a hole in the middle: 8, 9, 11 (+ final).
        cup.round_calendar = {"1": 8, "2": 9, "3": 11, "4": 12}
        cup.save(update_fields=["round_calendar"])

        # Everything up to 11 has kicked off: the whole phase has to move.
        self._play_real_matchdays(11)
        competition_calendar.reflow_pending_rounds(cup)

        cup.refresh_from_db()
        plan = [int(cup.round_calendar[str(r)]) for r in (1, 2, 3, 4)]
        self.assertEqual(plan, [12, 13, 14, 15], "i turni vanno compattati, non traslati")

    def test_a_phase_with_no_matchdays_left_is_refused_not_drawn_in_the_past(self):
        """The end of the line. Only ONE matchday of the season is still fieldable and
        the cup needs two, so its final has nowhere to go — and drawing it on a round
        that kicked off weeks ago would produce a tie nobody could field, hanging off
        a matchday the ledger has already closed, which nothing would ever score. It
        is refused and it says so; calling the competition off is the admin's
        decision, not a side effect."""
        champ, champ_stage = self._championship()
        cup = self._cup_from_table(champ_stage)

        # Everything up to the second-to-last matchday has kicked off: one slot left,
        # two rounds to place.
        Match.objects.filter(competition_season=self.cs,
                             matchday__lt=self.MATCHDAYS).update(
            kickoff=self.now - timedelta(days=1))
        self._play_real_matchdays(7)
        self._map_sources(champ)
        self._conclude_through(7)

        cup.refresh_from_db()
        # The semifinals fit in the last slot; the final does not, and is left alone.
        final = self._plan_for(cup, "Finale")
        self.assertTrue(final["pending"])
        self.assertEqual(final["blocker"]["kind"], "senza_giornate")
        self.assertEqual(
            FantasyFixture.objects.filter(competition=cup, stage__name="Finale").count(), 0,
            "meglio nessun sorteggio che un sorteggio su un turno gia' chiuso")

    def test_a_league_with_no_lineup_deadline_draws_normally(self):
        """The one league where "this matchday has kicked off" says nothing.

        A league played over an ALREADY FINISHED season — which is a testing setup,
        not something anyone runs for real — has every kickoff in the past, including
        the matchdays it has not reached yet, and turns `enforce_lineup_deadline` off
        precisely for that. The fieldability check has to go inert there, or every
        round of every competition is "impossible" and no cup can ever be drawn.

        It is the FLAG that decides this, not a guess about the season: the same
        state in a real league (the season has genuinely run out) is a real
        end-of-season and must still be refused.
        """
        self.league.enforce_lineup_deadline = False
        self.league.save(update_fields=["enforce_lineup_deadline"])
        champ, champ_stage = self._championship()
        cup = self._cup_from_table(champ_stage)
        Match.objects.filter(competition_season=self.cs).update(
            kickoff=self.now - timedelta(days=1))
        self._play_real_matchdays(7)
        self._map_sources(champ)
        self._conclude_through(7)

        self.assertEqual(FantasyFixture.objects.filter(competition=cup).count(), 2)
        # ...and they are on rounds the ledger has NOT counted, which is the whole
        # difference from the case below.
        for fx in FantasyFixture.objects.filter(competition=cup).select_related(
                "fantasy_matchday"):
            self.assertGreater(fx.fantasy_matchday.real_matchday, 7)

    def test_a_phase_whose_matchdays_the_league_already_counted_is_refused(self):
        """The guard that still works where the other one is switched off.

        With `enforce_lineup_deadline` off the fieldability check is inert by design
        — so on its own it would let a very late cup be drawn onto rounds the ledger
        CLOSED weeks ago. Nothing rescores a concluded matchday, so those ties would
        sit at 0-0 for ever in a competition that can no longer finish. The ledger
        asks a question that is true either way, and catches exactly what the
        fieldability check cannot see.
        """
        self.league.enforce_lineup_deadline = False
        self.league.save(update_fields=["enforce_lineup_deadline"])
        champ, champ_stage = self._championship()
        cup = self._cup_from_table(champ_stage)
        booked = sorted(int(v) for v in cup.round_calendar.values())

        # A season entirely in the past — so the fieldability check is inert — and a
        # postponement on the very round that decides the cup.
        Match.objects.filter(competition_season=self.cs).update(
            kickoff=self.now - timedelta(days=1))
        self._play_real_matchdays(self.MATCHDAYS)
        self._map_sources(champ)
        self._conclude_through(6)
        md7 = FantasyMatchday.objects.get(
            league=self.league, real_matchday=int(champ.round_calendar["7"]))
        self.client.post(f"/api/v1/leagues/{self.league.id}/matchdays/{md7.id}/await",
                         {"awaiting": True, "reason": "rinviata"}, format="json")

        # The league runs on and counts right past the matchdays the cup was booked
        # for — they are closed now, and nothing goes back over a closed round.
        for md in FantasyMatchday.objects.filter(
                league=self.league, real_matchday__lte=booked[-1] + 1,
                status=FantasyMatchday.STATUS_PLANNED).order_by("real_matchday"):
            r = self.client.post(
                f"/api/v1/leagues/{self.league.id}/matchdays/{md.id}/conclude", {}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(FantasyFixture.objects.filter(competition=cup).count(), 0)

        # Only now is the recovery counted, and the draw finally becomes possible —
        # too late.
        r = self.client.post(
            f"/api/v1/leagues/{self.league.id}/matchdays/{md7.id}/conclude", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)

        self.assertEqual(FantasyFixture.objects.filter(competition=cup).count(), 0,
                         "una partita agganciata a una giornata conclusa non verra' mai calcolata")
        plan = self._plan_for(cup, "Semifinali")
        self.assertTrue(plan["pending"])
        self.assertEqual(plan["blocker"]["kind"], "senza_giornate")

    def test_a_drawn_round_is_never_moved(self):
        """Reflow may only touch rounds nobody could have fielded. A round that has
        fixtures may already carry lineups, and a played one must keep the matchday
        its performances came from."""
        champ, _ = self._championship()
        before = dict(champ.round_calendar)
        Match.objects.filter(competition_season=self.cs).update(
            kickoff=self.now - timedelta(days=1))

        competition_calendar.reflow_pending_rounds(champ)

        champ.refresh_from_db()
        self.assertEqual(champ.round_calendar, before)
