"""The two clocks: what is being played vs what has been counted.

The scenario every test here is built around is the real one — Serie A 2025-26
matchday 16, four matches postponed on 21 December and recovered on 14-15 January,
with matchdays 17 to 20 played in between.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dttz

from django.contrib.auth.models import User
from django.test import TestCase

from realdata.models import (
    Competition,
    CompetitionSeason,
    Match,
    Player,
    PlayerTeamStint,
    Season,
    Team,
    TeamSeason,
)
from vfoot.models import FantasyLeague, FantasyMatchday, SavedLineupSnapshot
from vfoot.services import lineup_repair, matchday_state
from vfoot.services.classic_matchday_scoring import compose_team_lines
from vfoot.services.classic_scoring import Ruleset, score_team
from vfoot.services.match_resolver import pending_player_ids

DEC20 = datetime(2025, 12, 20, 17, 0, tzinfo=dttz.utc)   # matchday 16 kicks off
DEC27 = datetime(2025, 12, 27, 17, 0, tzinfo=dttz.utc)   # matchday 17 kicks off
JAN14 = datetime(2026, 1, 14, 17, 30, tzinfo=dttz.utc)   # the recovery


class TwoClocksTests(TestCase):
    """The ledger may lag; the calendar may not wait for it."""

    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        season = Season.objects.create(code="2025-2026")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=season, name="Serie A 2025-2026")
        self.owner = User.objects.create_user("owner", "o@x.it", "pw")
        self.league = FantasyLeague.objects.create(
            name="Lega", owner=self.owner, mode=FantasyLeague.MODE_CLASSIC,
            reference_season=self.cs)
        a, b, c, d = (Team.objects.create(name=n) for n in ("Como", "Milan", "Lazio", "Roma"))
        self.tsa = TeamSeason.objects.create(competition_season=self.cs, team=a)
        self.tsb = TeamSeason.objects.create(competition_season=self.cs, team=b)
        self.tsc = TeamSeason.objects.create(competition_season=self.cs, team=c)
        self.tsd = TeamSeason.objects.create(competition_season=self.cs, team=d)

        # md16: Lazio-Roma played, Como-Milan postponed (distinct pairings — the
        # same pairing twice is how a REPLAY looks, and would count as complete).
        # md17: both played.
        self._match(16, DEC20, Match.STATUS_FINISHED, ready=True, goals=(1, 0), ext="a16",
                    pair=("c", "d"))
        self.postponed = self._match(
            16, DEC20 + timedelta(days=1), Match.STATUS_POSTPONED, ready=False, ext="b16")
        self._match(17, DEC27, Match.STATUS_FINISHED, ready=True, goals=(2, 2), ext="a17")
        self._match(17, DEC27, Match.STATUS_FINISHED, ready=True, goals=(0, 1), ext="b17",
                    pair=("c", "d"))

        self.md16 = FantasyMatchday.objects.create(
            league=self.league, real_competition_season=self.cs, real_matchday=16)
        self.md17 = FantasyMatchday.objects.create(
            league=self.league, real_competition_season=self.cs, real_matchday=17)

    def _match(self, matchday, kickoff, status, ready, ext, goals=(None, None), pair=("a", "b")):
        home, away = ({"a": self.tsa, "b": self.tsb, "c": self.tsc, "d": self.tsd}[p]
                      for p in pair)
        return Match.objects.create(
            competition_season=self.cs, matchday=matchday, kickoff=kickoff,
            kickoff_provisional=False, home_team=home, away_team=away,
            status=status, data_ready=ready, home_goals=goals[0], away_goals=goals[1],
            external_source="sofascore", external_id=ext)

    # -- the calendar clock ------------------------------------------------- #
    def test_fieldable_matchday_ignores_a_forgotten_conclusion(self):
        """The whole point: nobody has concluded 16, yet 17 is what you can field."""
        after_md16 = DEC20 + timedelta(days=2)
        self.assertEqual(matchday_state.next_fieldable_matchday(self.league, after_md16), 17)
        self.assertEqual(self.md16.status, FantasyMatchday.STATUS_PLANNED)

    def test_nothing_is_fieldable_once_every_round_has_kicked_off(self):
        self.assertIsNone(matchday_state.next_fieldable_matchday(self.league, JAN14))

    def test_locked_matchdays_come_from_kickoffs_not_from_the_ledger(self):
        locked = matchday_state.locked_matchdays(self.cs.id, DEC20 + timedelta(hours=1))
        self.assertEqual(locked, {16})

    def test_playing_matchday_is_the_one_on_the_pitch(self):
        self.assertEqual(matchday_state.playing_matchday(self.league, DEC20 + timedelta(hours=1)), 16)
        # ...and nothing between rounds, three hours after the last kickoff.
        self.assertIsNone(matchday_state.playing_matchday(self.league, DEC20 + timedelta(days=2)))

    def test_a_postponed_shell_does_not_keep_the_round_on_the_pitch(self):
        """Its window has passed; only the recovery row can make 16 'playing' again."""
        during_shell = DEC20 + timedelta(days=1, hours=1)
        self.assertIsNone(matchday_state.playing_matchday(self.league, during_shell))

    # -- the ledger clock --------------------------------------------------- #
    def test_ledger_pointer_is_the_first_unscored_matchday(self):
        self.assertEqual(matchday_state.ledger_matchday(self.league).id, self.md16.id)

    def test_awaiting_lets_the_ledger_step_over_a_postponement(self):
        self.md16.status = FantasyMatchday.STATUS_AWAITING
        self.md16.save()
        self.assertEqual(matchday_state.ledger_matchday(self.league).id, self.md17.id)
        self.assertEqual([m.id for m in matchday_state.awaiting_matchdays(self.league)],
                         [self.md16.id])

    def test_conclusion_is_in_order_but_a_parked_matchday_is_the_exception(self):
        allowed, reason = matchday_state.can_conclude(self.league, self.md17)
        self.assertFalse(allowed)
        self.assertIn("16", reason)

        self.md16.status = FantasyMatchday.STATUS_AWAITING
        self.md16.save()
        # Parked: 17 becomes closeable, and 16 stays closeable out of order for
        # whenever its recovery is finally played.
        self.assertTrue(matchday_state.can_conclude(self.league, self.md17)[0])
        self.assertTrue(matchday_state.can_conclude(self.league, self.md16)[0])

    def test_conclusion_queue_holds_only_completed_rounds(self):
        # md16 has a postponement outstanding, md17 is complete.
        self.assertEqual([m.real_matchday for m in matchday_state.conclusion_queue(self.league)],
                         [17])


class PendingPlayerTests(TestCase):
    """A postponement is not a senza voto, and the bench must not cover it."""

    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        season = Season.objects.create(code="2025-2026")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=season, name="Serie A 2025-2026")
        a, b, c, d = (Team.objects.create(name=n) for n in ("Como", "Milan", "Lazio", "Roma"))
        self.tsa = TeamSeason.objects.create(competition_season=self.cs, team=a)
        self.tsb = TeamSeason.objects.create(competition_season=self.cs, team=b)
        self.tsc = TeamSeason.objects.create(competition_season=self.cs, team=c)
        self.tsd = TeamSeason.objects.create(competition_season=self.cs, team=d)
        # Como-Milan postponed; Lazio-Roma played.
        Match.objects.create(competition_season=self.cs, matchday=16, home_team=self.tsa,
                             away_team=self.tsb, status=Match.STATUS_POSTPONED,
                             data_ready=False, external_source="sofascore", external_id="p16")
        Match.objects.create(competition_season=self.cs, matchday=16, home_team=self.tsc,
                             away_team=self.tsd, status=Match.STATUS_FINISHED,
                             data_ready=True, home_goals=1, away_goals=1,
                             external_source="sofascore", external_id="f16")
        self.como = Player.objects.create(full_name="Como Guy", classic_role_seed="DIF")
        self.lazio = Player.objects.create(full_name="Lazio Guy", classic_role_seed="DIF")
        PlayerTeamStint.objects.create(player=self.como, team_season=self.tsa, end_date=None)
        PlayerTeamStint.objects.create(player=self.lazio, team_season=self.tsc, end_date=None)

    def test_only_the_player_of_the_unplayed_match_is_pending(self):
        pending = pending_player_ids(self.cs.id, 16, [self.como.id, self.lazio.id])
        self.assertEqual(pending, {self.como.id})


class PendingScoringTests(TestCase):
    """Pure: how a pending line behaves against a plain s.v. one."""

    # A legal 3-4-3: 1 GK, 2-4 DEF, 5-8 MID, 9-11 ATT, plus a MID on the bench so
    # bringing him on for 5 keeps the module legal.
    ROLES = {1: "GK", 2: "DEF", 3: "DEF", 4: "DEF", 5: "MID", 6: "MID", 7: "MID",
             8: "MID", 9: "ATT", 10: "ATT", 11: "ATT", 20: "MID"}

    def _lines(self, pending_ids):
        index = {
            pid: {"player_id": pid, "name": f"P{pid}", "lineup_role": role, "role": None,
                  "voto_puro": 6.0, "fantavoto": 6.0, "sv": False, "conceded": 0,
                  "entered": False, "entered_for": None, "replaced_by": None}
            # everyone has a vote except 5, the slot under test
            for pid, role in self.ROLES.items()
            if pid != 5
        }
        return compose_team_lines(1, list(range(2, 12)), [20], index, self.ROLES,
                                  pending=pending_ids)

    def test_a_plain_sv_starter_is_covered_by_the_bench(self):
        starters, bench = self._lines(set())
        team = score_team(starters, bench, Ruleset(max_substitutions=5))
        self.assertEqual([(s["out"]["player_id"], s["in"]["player_id"]) for s in team["substitutions"]],
                         [(5, 20)])
        self.assertEqual(team["pending"], [])

    def test_a_pending_starter_is_left_alone_and_scores_nothing(self):
        starters, bench = self._lines({5})
        team = score_team(starters, bench, Ruleset(max_substitutions=5))
        self.assertEqual(team["substitutions"], [], "un rinvio non si copre dalla panchina")
        self.assertEqual(team["pending"], [5])
        self.assertNotIn(5, team["unresolved_sv"], "non è un s.v. irrisolto: è un'altra cosa")
        # 10 votes counted, the 11th slot contributes nothing.
        self.assertEqual(team["base_total"], 60.0)

    def test_a_pending_bench_player_never_comes_on(self):
        starters, bench = self._lines({20})   # 5 is s.v., 20 (the sub) is pending
        team = score_team(starters, bench, Ruleset(max_substitutions=5))
        self.assertEqual(team["substitutions"], [])
        self.assertEqual(team["unresolved_sv"], [5])


class LineupRepairTests(TestCase):
    """A settlement repairs what is still open and never touches what has locked."""

    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        season = Season.objects.create(code="2025-2026")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=season, name="Serie A 2025-2026")
        owner = User.objects.create_user("owner2", "o2@x.it", "pw")
        self.league = FantasyLeague.objects.create(
            name="Lega", owner=owner, mode=FantasyLeague.MODE_CLASSIC,
            reference_season=self.cs)
        a, b = Team.objects.create(name="A"), Team.objects.create(name="B")
        tsa = TeamSeason.objects.create(competition_season=self.cs, team=a)
        tsb = TeamSeason.objects.create(competition_season=self.cs, team=b)
        # md16 has kicked off (locked); md17 has not.
        Match.objects.create(competition_season=self.cs, matchday=16, kickoff=DEC20,
                             kickoff_provisional=False, home_team=tsa, away_team=tsb,
                             status=Match.STATUS_FINISHED, data_ready=True,
                             external_source="sofascore", external_id="m16")
        Match.objects.create(competition_season=self.cs, matchday=17, kickoff=DEC27,
                             kickoff_provisional=False, home_team=tsa, away_team=tsb,
                             status=Match.STATUS_SCHEDULED, data_ready=False,
                             external_source="sofascore", external_id="m17")
        self.now = DEC20 + timedelta(days=2)   # after 16, before 17

    def _snap(self, matchday, lineup_id="team1", gk="99", starters=("5", "6"), bench=("20",)):
        return SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id=str(matchday), lineup_id=lineup_id,
            gk_player_id=gk, starter_player_ids=list(starters), bench_player_ids=list(bench),
            starter_backups=[{"starter_player_id": "5", "backup_player_ids": ["20"]}])

    def test_the_incoming_player_takes_the_exact_place_of_the_outgoing_one(self):
        snap = self._snap(17)
        touched = lineup_repair.swap_player(self.league, 1, 5, 77, self.now)
        snap.refresh_from_db()
        self.assertEqual(touched, [17])
        self.assertEqual(snap.starter_player_ids, ["77", "6"], "stessa posizione nell'XI")
        self.assertEqual(snap.bench_player_ids, ["20"], "panchina intatta")
        self.assertEqual(snap.starter_backups[0]["starter_player_id"], "77")

    def test_a_goalkeeper_is_swapped_in_goal(self):
        snap = self._snap(17)
        lineup_repair.swap_player(self.league, 1, 99, 88, self.now)
        snap.refresh_from_db()
        self.assertEqual(snap.gk_player_id, "88")

    def test_a_locked_lineup_is_never_touched(self):
        """R1: past the kickoff the lineup is frozen — that is what makes it fa fede."""
        snap = self._snap(16)
        touched = lineup_repair.swap_player(self.league, 1, 5, 77, self.now)
        snap.refresh_from_db()
        self.assertEqual(touched, [])
        self.assertEqual(snap.starter_player_ids, ["5", "6"])

    def test_a_manual_removal_vacates_the_slot(self):
        snap = self._snap(17)
        lineup_repair.swap_player(self.league, 1, 5, None, self.now)
        snap.refresh_from_db()
        self.assertEqual(snap.starter_player_ids, ["6"])
        self.assertEqual(snap.starter_backups, [], "niente titolare fantasma nei backup")

    def test_another_team_with_a_similar_id_is_not_touched(self):
        """team1 and team12 share a prefix; the boundary must be respected."""
        other = self._snap(17, lineup_id="team12")
        lineup_repair.swap_player(self.league, 1, 5, 77, self.now)
        other.refresh_from_db()
        self.assertEqual(other.starter_player_ids, ["5", "6"])

    def test_every_competition_of_the_same_matchday_is_repaired(self):
        cup = self._snap(17, lineup_id="team1:comp3")
        league_snap = self._snap(17, lineup_id="team1:comp2")
        lineup_repair.swap_player(self.league, 1, 5, 77, self.now)
        cup.refresh_from_db()
        league_snap.refresh_from_db()
        self.assertEqual(cup.starter_player_ids, ["77", "6"])
        self.assertEqual(league_snap.starter_player_ids, ["77", "6"])


class OfficeVoteTests(TestCase):
    """The imposed vote: a ruling on the vote, not fabricated data."""

    ROLES = PendingScoringTests.ROLES

    def _lines(self, pending_ids, office):
        index = {
            pid: {"player_id": pid, "name": f"P{pid}", "lineup_role": role, "role": None,
                  "voto_puro": 6.0, "fantavoto": 6.0, "sv": False, "conceded": 0,
                  "entered": False, "entered_for": None, "replaced_by": None}
            for pid, role in self.ROLES.items()
            if pid not in (1, 5)      # 1 (the GK) and 5 are the slots under test
        }
        return compose_team_lines(1, list(range(2, 12)), [20], index, self.ROLES,
                                  pending=pending_ids, office=office)

    def test_the_ruling_replaces_a_pending_slot_and_counts(self):
        starters, bench = self._lines({1, 5}, {1: 6.0, 5: 6.0})
        team = score_team(starters, bench, Ruleset(max_substitutions=5))
        self.assertEqual(team["pending"], [], "il voto d'ufficio chiude il caso")
        self.assertEqual(team["substitutions"], [], "non è un s.v.: la panchina non entra")
        self.assertEqual(team["base_total"], 66.0, "11 voti, due dei quali d'ufficio")

    def test_an_office_keeper_gets_no_clean_sheet(self):
        """conceded=0 on a match nobody played is not an unbeaten keeper."""
        starters, bench = self._lines({1, 5}, {1: 6.0, 5: 6.0})
        team = score_team(starters, bench,
                          Ruleset(max_substitutions=5, keeper_clean_sheet_enabled=True))
        cs = next(m for m in team["modifiers"] if m.key == "keeper_clean_sheet")
        self.assertFalse(cs.eligible)
        self.assertEqual(cs.value, 0.0)

    def test_the_imposed_vote_counts_towards_the_defence_modifier(self):
        """Deciso: un 6 d'ufficio è un voto puro come gli altri."""
        starters, _ = self._lines(set(), {2: 7.0})
        defender = next(l for l in starters if l["player_id"] == 2)
        self.assertEqual(defender["voto_puro"], 7.0)
        self.assertTrue(defender["office"])
        self.assertFalse(defender["sv"])
