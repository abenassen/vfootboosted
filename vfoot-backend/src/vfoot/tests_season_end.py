"""Il fine stagione: cosa finisce, chi vince cosa, e dove lo si legge.

A whole season played through the REAL "Concludi giornata" endpoint — one matchday
at a time, in order, exactly as an admin closes them — until three competitions of
three different shapes run out of football:

* un **campionato** a 8 squadre, andata secca, che assegna sei premi di tipo
  diverso: una posizione singola, una fascia di posizioni, e quattro primati
  (media, attacco, difesa presa da entrambi i lati);
* una **coppa** a eliminazione, dove "chi vince" non e' il primo di una classifica
  ma chi vince l'ultima partita, e "secondo" e' chi la perde;
* **gironi + finali**, che aggiunge il premio letto dalla classifica di UNA fase.

THE RESULTS ARE A RULE, NOT A DRAW
----------------------------------
In every match the lower-indexed team wins, scoring ``GOALS[winner]`` to nil. So
the table is T0 > T1 > ... > T7 by construction, while the goals deliberately are
NOT in that order: T1 wins by five and everyone else by one. A prize that reads
the table and a prize that reads a record therefore land on DIFFERENT teams, and
an implementation that quietly awarded everything to the champion would fail here
instead of looking right.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from realdata.models import Competition, CompetitionSeason, Match, Season, Team, TeamSeason
from vfoot.models import (
    CompetitionPrize,
    CompetitionStage,
    FantasyCompetition,
    FantasyFixture,
    FantasyLeague,
    FantasyMatchday,
    FantasyTeam,
    LeagueMembership,
)
from vfoot.services import honours
from vfoot.services.competition_prizes import prize_winner_team_ids

SEASON_MATCHDAYS = 16
# What the winner of a match scores, by its index. Flat except for T1, whose five
# goals a game make it the best attack and the highest average while the table
# still has it second — which is the whole point of the fixture.
GOALS = [1, 5, 1, 1, 1, 1, 1, 1]


class SeasonEndTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        # Eight real clubs, four matches per real matchday: enough for every fantasy
        # fixture of a round to have its own real match, which is how a result gets
        # into an aura league (the fixture copies the real scoreline).
        sides = [TeamSeason.objects.create(competition_season=self.cs,
                                           team=Team.objects.create(external_id=f"r{i}",
                                                                    name=f"Real {i}"))
                 for i in range(8)]
        # A season already played: every match is over and its data settled, which is
        # what the conclusion asks for. The kickoffs are therefore in the PAST, and a
        # league on such a season is exactly the one that turns the lineup deadline
        # off — see FantasyLeague.enforce_lineup_deadline.
        base = timezone.now() - timedelta(days=7 * SEASON_MATCHDAYS + 1)
        Match.objects.bulk_create([
            Match(competition_season=self.cs, external_id=f"m{md}-{i}", matchday=md,
                  home_team=sides[i * 2], away_team=sides[i * 2 + 1],
                  kickoff=base + timedelta(days=7 * md), kickoff_provisional=False,
                  status=Match.STATUS_FINISHED, data_ready=True)
            for md in range(1, SEASON_MATCHDAYS + 1) for i in range(4)
        ])

        self.admin = User.objects.create_user("admin", "admin@x.it", "x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        r = self.client.post("/api/v1/leagues",
                             {"name": "Lega Fine Stagione", "team_name": "Alpha",
                              "reference_season_id": self.cs.id}, format="json")
        self.league = FantasyLeague.objects.get(id=r.json()["league_id"])
        self.league.enforce_lineup_deadline = False
        self.league.save(update_fields=["enforce_lineup_deadline"])

        self.managers = [self.admin]
        for i in range(1, 8):
            user = User.objects.create_user(f"mgr{i}", f"mgr{i}@x.it", "x")
            m = LeagueMembership.objects.create(league=self.league, user=user, role="manager")
            FantasyTeam.objects.create(league=self.league, manager=m, name=f"Team {i}")
            self.managers.append(user)
        self.team_ids = list(FantasyTeam.objects.filter(league=self.league)
                             .order_by("id").values_list("id", flat=True))
        self.rank = {tid: i for i, tid in enumerate(self.team_ids)}

    # -- building the season ------------------------------------------------ #

    def _wizard(self, **payload):
        r = self.client.post(f"/api/v1/leagues/{self.league.id}/competitions/wizard",
                             payload, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return FantasyCompetition.objects.get(id=r.json()["competition"]["competition_id"])

    def _championship(self):
        return self._wizard(
            name="Campionato", format="league", team_ids=self.team_ids, legs=1,
            start_matchday=1,
            prizes=[
                {"name": "Scudetto", "icon": "🏆", "condition": "winner"},
                {"name": "Zona Europa", "icon": "⭐", "condition": "rank",
                 "rank_from": 2, "rank_to": 4},
                {"name": "Bomber", "icon": "🎯", "condition": "stat",
                 "stat": "avg_score", "direction": "top"},
                {"name": "Miglior difesa", "icon": "🛡️", "condition": "stat",
                 "stat": "goals_against", "direction": "bottom"},
                {"name": "Peggior difesa", "icon": "💩", "condition": "stat",
                 "stat": "goals_against", "direction": "top"},
                {"name": "Attacco spuntato", "icon": "🐐", "condition": "stat",
                 "stat": "goals_for", "direction": "bottom"},
            ])

    def _cup(self):
        return self._wizard(
            name="Coppa", format="cup", team_ids=self.team_ids[:4], start_matchday=8,
            prizes=[
                {"name": "Coppa", "icon": "🏆", "condition": "winner"},
                {"name": "Finalista", "icon": "🥈", "condition": "runner_up"},
            ])

    def _champions(self):
        comp = self._wizard(
            name="Champions", format="groups_knockout", team_ids=self.team_ids,
            groups=2, advance_per_group=2, start_matchday=10,
            prizes=[
                {"name": "Champions", "icon": "👑", "condition": "winner"},
                {"name": "Finalista Champions", "icon": "🥈", "condition": "runner_up"},
            ])
        # The group prize has to be added afterwards: the wizard's vocabulary has no
        # word for "the table of ONE phase", and the stage it points at does not
        # exist until the competition is built.
        group_a = CompetitionStage.objects.filter(competition=comp).order_by("order_index", "id").first()
        r = self.client.post(f"/api/v1/competitions/{comp.id}/prizes",
                             {"name": f"Dominatore {group_a.name}", "icon": "🥇",
                              "condition_type": "stage_table_range",
                              "source_stage_id": group_a.id, "rank_from": 1, "rank_to": 1},
                             format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return comp, group_a

    # -- playing it --------------------------------------------------------- #

    def _arrange(self, md: FantasyMatchday) -> None:
        """Give every fixture of this matchday a real match carrying the score we want."""
        fixtures = list(FantasyFixture.objects.filter(fantasy_matchday=md).order_by("id"))
        reals = list(Match.objects.filter(competition_season=self.cs,
                                          matchday=md.real_matchday).order_by("id"))
        self.assertLessEqual(len(fixtures), len(reals),
                             "the real calendar must have a match per fantasy fixture")
        for fx, real in zip(fixtures, reals):
            home, away = self.rank[fx.home_team_id], self.rank[fx.away_team_id]
            if home < away:
                real.home_goals, real.away_goals = GOALS[home], 0
            else:
                real.home_goals, real.away_goals = 0, GOALS[away]
            real.save(update_fields=["home_goals", "away_goals"])
            fx.source_real_match = real
            fx.save(update_fields=["source_real_match"])

    def _conclude_next(self):
        """Close the matchday the ledger is on, after arranging its results."""
        from vfoot.services import matchday_state
        md = matchday_state.ledger_matchday(self.league)
        self.assertIsNotNone(md, "the ledger is up to date, there is nothing to close")
        self._arrange(md)
        r = self.client.post(
            f"/api/v1/leagues/{self.league.id}/matchdays/{md.id}/conclude", {}, format="json")
        self.assertEqual(r.status_code, 200, r.content)
        return md, r.json()

    def _play_the_season(self) -> list[tuple[FantasyMatchday, dict]]:
        from vfoot.services import matchday_state
        out = []
        while matchday_state.ledger_matchday(self.league) is not None:
            out.append(self._conclude_next())
        return out

    def _prize(self, comp: FantasyCompetition, name: str) -> dict:
        detail = self.client.get(f"/api/v1/competitions/{comp.id}").json()
        for p in detail["prizes"]:
            if p["name"] == name:
                return p
        self.fail(f"premio {name!r} non trovato in {comp.name}")

    def _names(self, indexes) -> list[str]:
        by_id = dict(FantasyTeam.objects.filter(id__in=self.team_ids).values_list("id", "name"))
        return sorted(by_id[self.team_ids[i]] for i in indexes)

    # ---------------------------------------------------------------- tests #

    def test_a_league_title_is_assigned_by_the_last_conclusion(self):
        """Nothing is won until the last round is counted — and then it is."""
        comp = self._championship()
        self.assertEqual(self._prize(comp, "Scudetto")["winner_team_ids"], [])

        rounds = self._play_the_season()
        # Every conclusion but the last one announced nothing at all.
        announced = [(md.real_matchday, res["finished_competitions"]) for md, res in rounds]
        fired = [(rm, fin) for rm, fin in announced if fin]
        self.assertEqual(len(fired), 1, f"una sola competizione doveva chiudersi: {fired}")
        real_matchday, finished = fired[0]
        self.assertEqual(real_matchday, 7, "il campionato finisce alla 7ª, non prima")
        self.assertEqual(finished[0]["name"], "Campionato")
        self.assertEqual(finished[0]["prizes"][0]["name"], "Scudetto")
        self.assertEqual(finished[0]["prizes"][0]["winner_team_names"], ["Alpha"])

        comp.refresh_from_db()
        self.assertEqual(comp.status, FantasyCompetition.STATUS_DONE)

    def test_a_finished_competition_is_announced_once_and_not_again(self):
        """The response is an EVENT. A competition already closed must not fire on
        every later conclusion, or the news feed fills up with the same trophy."""
        self._championship()
        self._cup()
        fired = [res["finished_competitions"] for _, res in self._play_the_season()]
        names = [c["name"] for batch in fired for c in batch]
        self.assertEqual(sorted(names), ["Campionato", "Coppa"])

    def test_every_kind_of_prize_finds_its_own_winner(self):
        """Six conditions, six questions — and deliberately not the same answer."""
        comp = self._championship()
        self._play_the_season()

        self.assertEqual(self._prize(comp, "Scudetto")["winner_team_names"], self._names([0]))
        self.assertEqual(sorted(self._prize(comp, "Zona Europa")["winner_team_names"]),
                         self._names([1, 2, 3]))
        # The records, none of which is the table read again: T1 scores five a game
        # and finishes second, T7 loses every match by one goal.
        self.assertEqual(self._prize(comp, "Bomber")["winner_team_names"], self._names([1]))
        self.assertEqual(self._prize(comp, "Miglior difesa")["winner_team_names"], self._names([0]))
        self.assertEqual(self._prize(comp, "Peggior difesa")["winner_team_names"], self._names([7]))
        self.assertEqual(self._prize(comp, "Attacco spuntato")["winner_team_names"], self._names([7]))

    def test_the_two_ends_of_one_measure_are_two_different_prizes(self):
        """Miglior difesa and peggior difesa read the SAME number from opposite
        sides — the direction lives in the condition, not in the name."""
        comp = self._championship()
        self._play_the_season()
        best = self._prize(comp, "Miglior difesa")
        worst = self._prize(comp, "Peggior difesa")
        self.assertEqual(best["condition_type"], CompetitionPrize.CONDITION_STAT_BOTTOM)
        self.assertEqual(worst["condition_type"], CompetitionPrize.CONDITION_STAT_TOP)
        self.assertEqual(best["stat"], worst["stat"], "stessa misura")
        self.assertNotEqual(best["winner_team_ids"], worst["winner_team_ids"])
        self.assertEqual(best["condition_label"], "miglior difesa")
        self.assertEqual(worst["condition_label"], "peggior difesa")

    def test_a_cup_is_won_on_the_pitch_and_not_in_a_table(self):
        """"Chi vince" means the final in a cup: the prize hangs off the last
        stage, and the runner-up is whoever LOST it — not the second of anything."""
        comp = self._cup()
        final = CompetitionStage.objects.filter(competition=comp).order_by("-order_index", "-id").first()
        self.assertEqual(
            CompetitionPrize.objects.get(competition=comp, name="Coppa").source_stage_id, final.id)
        self.assertEqual(
            CompetitionPrize.objects.get(competition=comp, name="Finalista").condition_type,
            CompetitionPrize.CONDITION_STAGE_LOSER)

        self._play_the_season()
        final_fixture = FantasyFixture.objects.get(competition=comp, stage=final)
        won, lost = ((final_fixture.home_team_id, final_fixture.away_team_id)
                     if final_fixture.home_total > final_fixture.away_total
                     else (final_fixture.away_team_id, final_fixture.home_team_id))
        self.assertEqual(self._prize(comp, "Coppa")["winner_team_ids"], [won])
        self.assertEqual(self._prize(comp, "Finalista")["winner_team_ids"], [lost])
        # Whatever the draw, the team that beats everybody lifts it.
        self.assertEqual(won, self.team_ids[0])

    def test_a_cup_is_not_over_when_only_the_semifinals_are_played(self):
        """Half a bracket is not a bracket: no champion at the semi-final stage."""
        comp = self._cup()
        semis = CompetitionStage.objects.filter(competition=comp).order_by("order_index", "id").first()
        _, res = self._conclude_next()           # matchday 8, the semi-finals
        self.assertFalse(FantasyFixture.objects.filter(competition=comp, stage=semis)
                         .exclude(status=FantasyFixture.STATUS_FINISHED).exists())
        self.assertEqual(res["finished_competitions"], [],
                         "la coppa non e' finita: manca la finale")
        self.assertFalse(honours.is_complete(comp))
        self.assertEqual(self._prize(comp, "Coppa")["winner_team_ids"], [])

    def test_a_final_that_could_not_be_drawn_leaves_the_competition_open(self):
        """The case where "every fixture is finished" is TRUE and the competition
        is nowhere near over — and the only one where the phase test is what stops
        a trophy being handed out.

        The final's matchday is closed before the semi-finals are (out of order,
        which is what ``force`` is for), so when the semis finally resolve there is
        no round left to draw the final onto and ``resolve_stage`` refuses — see
        its ``no_matchdays_left``. The bracket stops there. What must NOT happen is
        the cup being declared won by whoever survived the semi-finals.
        """
        comp = self._cup()
        from vfoot.services import matchday_state
        ledger = matchday_state.league_matchdays(self.league)
        semis_md, final_md = ledger[0], ledger[1]

        forced = self.client.post(
            f"/api/v1/leagues/{self.league.id}/matchdays/{final_md.id}/conclude",
            {"force": True}, format="json")
        self.assertEqual(forced.status_code, 200, forced.content)

        self._arrange(semis_md)
        res = self.client.post(
            f"/api/v1/leagues/{self.league.id}/matchdays/{semis_md.id}/conclude",
            {}, format="json").json()
        self.assertTrue(res["resolved_target_stages"][0]["no_matchdays_left"],
                        "la finale non poteva essere sorteggiata")

        self.assertFalse(FantasyFixture.objects.filter(competition=comp)
                         .exclude(status=FantasyFixture.STATUS_FINISHED).exists())
        self.assertFalse(honours.is_complete(comp),
                         "ogni partita giocata, ma una fase non e' mai stata sorteggiata")
        self.assertEqual(res["finished_competitions"], [])
        self.assertEqual(self._prize(comp, "Coppa")["winner_team_ids"], [])
        feed = self.client.get(f"/api/v1/leagues/{self.league.id}/activity?limit=50").json()
        self.assertEqual([i for i in feed if i["kind"] in ("premio", "competizione")], [])

    def test_a_phase_with_several_rounds_is_won_in_its_last_one(self):
        """A cup built by the wizard is one phase per round, so "vince «Finale»"
        has a single tie to read. A phase built by hand need not be — and one
        holding semi-finals AND final used to award the cup to both semi-finalists
        and to none of the two who reached it."""
        # Built by hand, not by the wizard: the wizard cannot make this shape, and
        # the point is precisely that the data model can.
        comp = FantasyCompetition.objects.create(
            league=self.league, name="Coppa a fase unica",
            competition_type=FantasyCompetition.TYPE_KNOCKOUT,
            format=FantasyCompetition.FORMAT_CUP)
        stage = CompetitionStage.objects.create(
            competition=comp, name="Fase finale",
            stage_type=CompetitionStage.TYPE_KNOCKOUT, order_index=1)
        a, b, c, d = self.team_ids[:4]
        for home, away in ((a, c), (b, d)):
            FantasyFixture.objects.create(
                competition=comp, stage=stage, round_no=1, home_team_id=home,
                away_team_id=away, home_total=2.0, away_total=0.0,
                status=FantasyFixture.STATUS_FINISHED)
        final = FantasyFixture.objects.create(
            competition=comp, stage=stage, round_no=2, home_team_id=a, away_team_id=b,
            home_total=1.0, away_total=3.0, status=FantasyFixture.STATUS_FINISHED)
        won = CompetitionPrize.objects.create(
            competition=comp, name="Coppa", condition_type=CompetitionPrize.CONDITION_STAGE_WINNER,
            source_stage=stage)
        lost = CompetitionPrize.objects.create(
            competition=comp, name="Finalista", condition_type=CompetitionPrize.CONDITION_STAGE_LOSER,
            source_stage=stage)
        self.assertEqual(prize_winner_team_ids(won), [final.away_team_id])
        self.assertEqual(prize_winner_team_ids(lost), [final.home_team_id])

        # E una finale che finisce in parità viene comunque assegnata: la decide
        # la catena di `knockout` (qui, senza tabellino, il fattore campo), la
        # stessa che manda avanti qualcuno nel turno successivo. Una coppa non
        # assegnata lascerebbe la competizione senza fine.
        final.away_total = 1.0
        final.save(update_fields=["away_total"])
        self.assertEqual(prize_winner_team_ids(won), [final.home_team_id])
        self.assertEqual(prize_winner_team_ids(lost), [final.away_team_id])

    def test_a_group_prize_reads_its_own_group_and_not_the_competition(self):
        comp, group_a = self._champions()
        self._play_the_season()
        in_group_a = sorted(
            self.rank[tid] for tid in
            group_a.participants.values_list("team_id", flat=True))
        best_of_the_group = min(in_group_a)
        prize = self._prize(comp, f"Dominatore {group_a.name}")
        self.assertEqual(prize["winner_team_names"], self._names([best_of_the_group]))
        # ...and that is not simply the best team of the competition, unless the
        # draw put it in this group.
        if best_of_the_group != 0:
            self.assertNotEqual(prize["winner_team_ids"],
                                self._prize(comp, "Champions")["winner_team_ids"])

    def test_a_tied_record_is_won_by_everyone_who_tied(self):
        """Two teams with the same average have both got the highest one. Picking
        one of them would be inventing a tie-break nobody declared."""
        comp = self._wizard(name="Mini", format="league", team_ids=self.team_ids[:4],
                            legs=1, start_matchday=1)
        prize = CompetitionPrize.objects.create(
            competition=comp, name="Media", icon="📈",
            condition_type=CompetitionPrize.CONDITION_STAT_TOP,
            stat=CompetitionPrize.STAT_AVG_SCORE)
        # Everyone draws 2-2 except one pairing: three teams end level on average.
        for fx in FantasyFixture.objects.filter(competition=comp):
            fx.home_total, fx.away_total = 2.0, 2.0
            fx.status = FantasyFixture.STATUS_FINISHED
            fx.save(update_fields=["home_total", "away_total", "status"])
        first = FantasyFixture.objects.filter(competition=comp).order_by("id").first()
        first.home_total, first.away_total = 0.0, 0.0
        first.save(update_fields=["home_total", "away_total"])

        winners = set(self.client.get(f"/api/v1/competitions/{comp.id}").json()
                      ["prizes"][0]["winner_team_ids"])
        expected = set(self.team_ids[:4]) - {first.home_team_id, first.away_team_id}
        self.assertEqual(winners, expected)
        self.assertEqual(len(winners), 2, "il primato e' condiviso, non assegnato a caso")
        self.assertEqual(prize.name, "Media")

    def test_the_league_reads_it_all_in_the_news(self):
        comp = self._championship()
        self._play_the_season()
        feed = self.client.get(f"/api/v1/leagues/{self.league.id}/activity?limit=50").json()

        ended = [i for i in feed if i["kind"] == "competizione"]
        self.assertEqual([i["text"] for i in ended], ["Campionato: è finita"])
        self.assertIsNotNone(ended[0]["at"], "la data e' quella della giornata conclusa")

        awarded = {i["text"].split(":")[0] for i in feed if i["kind"] == "premio"}
        self.assertIn("🏆 Scudetto", awarded)
        self.assertIn("🎯 Bomber", awarded)
        scudetto = next(i for i in feed if i["kind"] == "premio" and "Scudetto" in i["text"])
        self.assertEqual(scudetto["text"], "🏆 Scudetto: Alpha")
        self.assertEqual(scudetto["detail"], "Campionato · 1° in classifica finale")
        # Dated from the ledger, so it sits with the matchday that decided it and
        # not at the top of the feed for ever.
        last_round = (FantasyMatchday.objects.filter(league=self.league, real_matchday=7)
                      .first().concluded_at)
        self.assertEqual(scudetto["at"], last_round.isoformat())

    def test_an_undecided_prize_is_not_news(self):
        self._championship()
        self._conclude_next()
        feed = self.client.get(f"/api/v1/leagues/{self.league.id}/activity?limit=50").json()
        self.assertEqual([i for i in feed if i["kind"] in ("premio", "competizione")], [])

    def test_the_albo_doro_of_a_manager_collects_what_he_won(self):
        self._championship()
        self._cup()
        self._play_the_season()

        r = self.client.get(f"/api/v1/managers/{self.admin.id}/honours")
        self.assertEqual(r.status_code, 200, r.content)
        mine = r.json()
        self.assertEqual(mine["username"], "admin")
        won = {(a["name"], a["competition_name"]) for a in mine["awards"]}
        self.assertIn(("Scudetto", "Campionato"), won)
        self.assertIn(("Miglior difesa", "Campionato"), won)
        self.assertIn(("Coppa", "Coppa"), won)
        self.assertNotIn(("Zona Europa", "Campionato"), won, "il primo non e' in zona Europa")
        first = mine["awards"][0]
        self.assertEqual(first["team_name"], "Alpha")
        self.assertEqual(first["league_name"], "Lega Fine Stagione")

        # The runner-up's board is a different board.
        second = self.client.get(f"/api/v1/managers/{self.managers[1].id}/honours").json()
        theirs = {a["name"] for a in second["awards"]}
        self.assertEqual(theirs, {"Zona Europa", "Bomber", "Finalista"})

    def test_a_manager_can_read_the_albo_of_the_others_and_no_one_elses(self):
        self._championship()
        self._play_the_season()
        rival = APIClient()
        rival.force_authenticate(user=self.managers[3])
        self.assertEqual(
            rival.get(f"/api/v1/managers/{self.admin.id}/honours").status_code, 200)

        outsider = User.objects.create_user("nessuno", "n@x.it", "x")
        stranger = APIClient()
        stranger.force_authenticate(user=outsider)
        self.assertEqual(
            stranger.get(f"/api/v1/managers/{self.admin.id}/honours").status_code, 404,
            "un albo d'oro non e' segreto, ma le leghe altrui non sono affari suoi")
        # ...and he can always read his own, empty.
        own = stranger.get(f"/api/v1/managers/{outsider.id}/honours")
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.json()["awards"], [])

    def test_a_rectified_result_moves_the_trophy(self):
        """Nothing is written down, and this is what that buys: an admin who
        corrects the last matchday corrects the honours board with it."""
        comp = self._championship()
        self._play_the_season()
        self.assertEqual(self._prize(comp, "Attacco spuntato")["winner_team_names"],
                         self._names([7]))

        # The last team is awarded a hatful of goals it never scored.
        last = self.team_ids[7]
        for fx in FantasyFixture.objects.filter(competition=comp):
            if fx.home_team_id == last:
                fx.home_total = 9.0
                fx.save(update_fields=["home_total"])
            elif fx.away_team_id == last:
                fx.away_total = 9.0
                fx.save(update_fields=["away_total"])

        self.assertNotIn(self._names([7])[0],
                         self._prize(comp, "Attacco spuntato")["winner_team_names"])
        self.assertEqual(self._prize(comp, "Bomber")["winner_team_names"], self._names([7]))
