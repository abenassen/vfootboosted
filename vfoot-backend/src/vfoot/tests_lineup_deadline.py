"""The two deadlines a league can play under.

The scenario is the ordinary shape of a Serie A round, which is what makes the
difference visible at all: Saturday 15:00 Como-Milan, Monday 20:45 Lazio-Roma. A
manager holding players from all four clubs is, on Sunday morning, half decided and
half not — and the whole question is whether the page tells him so or shuts.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone as dttz

from django.utils import timezone

from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

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
from vfoot.models import (
    FantasyLeague,
    FantasyMatchday,
    FantasyRosterSlot,
    FantasyTeam,
    LeagueMembership,
    SavedLineupSnapshot,
)
from vfoot.services import lineup_deadline, lineup_repair, matchday_state

SAT = datetime(2026, 2, 7, 14, 0, tzinfo=dttz.utc)    # Como-Milan
MON = datetime(2026, 2, 9, 19, 45, tzinfo=dttz.utc)   # Lazio-Roma
SUNDAY = SAT + timedelta(days=1)                      # in between: half a round played


class _Season(TestCase):
    """A four-club matchday split across the weekend, and one manager holding
    players from each of them."""

    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        season = Season.objects.create(code="2025-2026")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=season, name="Serie A 2025-2026")
        self.owner = User.objects.create_user("owner", "o@x.it", "pw")
        # Aura, deliberately: the deadline is not a classic rule, and the classic
        # role validator would demand a legal eleven from every request here — a
        # constraint that has nothing to do with what is being tested.
        self.league = FantasyLeague.objects.create(
            name="Lega", owner=self.owner, mode=FantasyLeague.MODE_AURA,
            reference_season=self.cs, lineup_lock_mode=FantasyLeague.LOCK_PLAYER)
        self.membership = LeagueMembership.objects.create(
            league=self.league, user=self.owner, role=LeagueMembership.ROLE_ADMIN)
        self.team = FantasyTeam.objects.create(
            league=self.league, manager=self.membership, name="Squadra")

        self.ts = {}
        for code in ("como", "milan", "lazio", "roma"):
            club = Team.objects.create(name=code.title())
            self.ts[code] = TeamSeason.objects.create(competition_season=self.cs, team=club)

        Match.objects.create(
            competition_season=self.cs, matchday=22, kickoff=SAT, kickoff_provisional=False,
            home_team=self.ts["como"], away_team=self.ts["milan"],
            status=Match.STATUS_SCHEDULED, external_source="sofascore", external_id="sat22")
        Match.objects.create(
            competition_season=self.cs, matchday=22, kickoff=MON, kickoff_provisional=False,
            home_team=self.ts["lazio"], away_team=self.ts["roma"],
            status=Match.STATUS_SCHEDULED, external_source="sofascore", external_id="mon22")
        FantasyMatchday.objects.create(
            league=self.league, real_competition_season=self.cs, real_matchday=22)

        # Two players per club, so a lineup can hold a Saturday man and a Monday one.
        self.pid = {}
        for code in self.ts:
            for n in (1, 2):
                p = Player.objects.create(full_name=f"{code}{n}", short_name=f"{code.title()} {n}")
                PlayerTeamStint.objects.create(player=p, team_season=self.ts[code])
                FantasyRosterSlot.objects.create(
                    team=self.team, player=p, purchase_price=10)
                self.pid[f"{code}{n}"] = p.id

    def _client(self):
        token, _ = Token.objects.get_or_create(user=self.owner)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return c


class LockedPlayersTests(_Season):
    def test_only_the_clubs_that_kicked_off_are_locked(self):
        locked = matchday_state.locked_players(
            self.league, 22, list(self.pid.values()), now=SUNDAY)
        self.assertEqual(
            locked, {self.pid["como1"], self.pid["como2"],
                     self.pid["milan1"], self.pid["milan2"]})

    def test_nobody_is_locked_before_the_first_kickoff(self):
        self.assertEqual(
            matchday_state.locked_players(self.league, 22, list(self.pid.values()),
                                          now=SAT - timedelta(hours=1)),
            set())

    def test_the_matchday_mode_never_names_a_player(self):
        """It locks as a block; a per-player answer there would be a lie."""
        self.league.lineup_lock_mode = FantasyLeague.LOCK_MATCHDAY
        self.assertEqual(
            matchday_state.locked_players(self.league, 22, list(self.pid.values()),
                                          now=SUNDAY),
            set())

    def test_no_deadline_locks_nobody(self):
        self.league.enforce_lineup_deadline = False
        self.assertEqual(
            matchday_state.locked_players(self.league, 22, list(self.pid.values()),
                                          now=MON + timedelta(hours=1)),
            set())

    def test_a_postponed_match_moves_the_players_deadline_to_the_replay(self):
        """His club is not playing on Saturday any more, so he is not decided."""
        Match.objects.filter(external_id="sat22").update(status=Match.STATUS_POSTPONED)
        Match.objects.create(
            competition_season=self.cs, matchday=22, kickoff=MON + timedelta(days=30),
            kickoff_provisional=False, home_team=self.ts["como"], away_team=self.ts["milan"],
            status=Match.STATUS_SCHEDULED, external_source="sofascore", external_id="rep22")
        self.assertEqual(
            matchday_state.locked_players(self.league, 22, list(self.pid.values()),
                                          now=SUNDAY),
            set())


class ClosedMatchdayTests(_Season):
    def test_per_player_the_round_closes_at_the_last_kickoff(self):
        self.assertEqual(matchday_state.closed_matchdays(self.league, SUNDAY), set())
        self.assertEqual(
            matchday_state.closed_matchdays(self.league, MON + timedelta(minutes=1)), {22})

    def test_matchday_mode_closes_at_the_first(self):
        self.league.lineup_lock_mode = FantasyLeague.LOCK_MATCHDAY
        self.assertEqual(matchday_state.closed_matchdays(self.league, SUNDAY), {22})

    def test_no_deadline_never_closes(self):
        self.league.enforce_lineup_deadline = False
        self.assertEqual(
            matchday_state.closed_matchdays(self.league, MON + timedelta(days=7)), set())

    def test_the_fieldable_round_is_still_this_one_on_sunday(self):
        """The bug this mode would otherwise have: sent forward to matchday 23 with
        two clubs still to play."""
        self.assertEqual(matchday_state.next_fieldable_matchday(self.league, SUNDAY), 22)
        self.league.lineup_lock_mode = FantasyLeague.LOCK_MATCHDAY
        self.assertIsNone(matchday_state.next_fieldable_matchday(self.league, SUNDAY))


class ViolationRulesTests(TestCase):
    """The placement rule, on its own — no database, no calendar."""

    def _lineup(self, gk, xi, bench):
        return {"gk_player_id": gk, "starter_player_ids": xi, "bench_player_ids": bench}

    def test_an_untouched_locked_player_is_fine(self):
        old = self._lineup(1, [2, 3], [4, 5])
        self.assertEqual(lineup_deadline.violations(old, dict(old), {2, 4}), [])

    def test_a_locked_starter_cannot_be_benched(self):
        old = self._lineup(1, [2, 3], [4])
        new = self._lineup(1, [3, 4], [2])
        errs = lineup_deadline.violations(old, new, {2})
        self.assertEqual(len(errs), 1)
        self.assertIn("titolari a panchina", errs[0])

    def test_a_locked_player_cannot_be_added(self):
        old = self._lineup(1, [2, 3], [])
        new = self._lineup(1, [2, 3], [9])
        self.assertIn("non può entrare in formazione",
                      lineup_deadline.violations(old, new, {9})[0])

    def test_with_no_previous_lineup_a_locked_player_cannot_be_fielded(self):
        new = self._lineup(1, [2, 3], [])
        self.assertTrue(lineup_deadline.violations(None, new, {2}))

    def test_an_unlocked_player_moves_freely(self):
        old = self._lineup(1, [2, 3], [4])
        new = self._lineup(4, [2, 3], [1])
        self.assertEqual(lineup_deadline.violations(old, new, {2, 3}), [])

    def test_locked_bench_players_keep_their_slot(self):
        old = self._lineup(1, [2], [4, 5])
        new = self._lineup(1, [2], [5, 4])
        errs = lineup_deadline.violations(old, new, {4, 5})
        self.assertEqual(len(errs), 2)
        self.assertTrue(all("in panchina" in e for e in errs))

    def test_nobody_may_be_slipped_above_a_locked_bench_player(self):
        """The slot is his: pushing him from 1st to 2nd is a demotion, and the
        reason for wanting it is that his vote is already on the screen."""
        old = self._lineup(1, [2], [4])
        new = self._lineup(1, [2], [7, 4])
        self.assertIn("dal posto 1 al posto 2 in panchina",
                      lineup_deadline.violations(old, new, {4})[0])

    def test_the_free_ones_do_not_swap_over_a_frozen_head(self):
        """Slots 2 and 4 exchanging occupants used to be "the only reordering a
        half-played bench still allows". It is the fourth door: the 4th has his
        vote on the board, and swapping 8 and 9 around him is choosing — with
        that vote known — which of the two reaches the pitch first."""
        old = self._lineup(1, [2], [7, 8, 4, 9])
        new = self._lineup(1, [2], [7, 9, 4, 8])
        errs = lineup_deadline.violations(old, new, {4})
        self.assertEqual(len(errs), 2)
        self.assertTrue(any("davanti a" in e for e in errs))
        self.assertTrue(any("dietro a" in e for e in errs))

    def test_the_free_ones_swap_inside_their_own_stretch(self):
        old = self._lineup(1, [2], [7, 8, 4, 9, 10])
        new = self._lineup(1, [2], [8, 7, 4, 10, 9])
        self.assertEqual(lineup_deadline.violations(old, new, {4}), [])

    def test_a_change_of_module_with_frozen_starters_is_not_an_overtaking(self):
        """The eleven are ONE place: frozen starters 2 and 3 stay in the XI while
        the free ones around them move in and out, and the bench head is frozen
        too. Nothing flips a strict order, so nothing is refused."""
        old = self._lineup(1, [2, 3, 5, 6], [7, 4, 8])
        new = self._lineup(1, [3, 7, 2, 5], [6, 4, 8])
        self.assertEqual(lineup_deadline.violations(old, new, {2, 3, 4}), [])

    def test_a_starter_may_drop_ahead_of_a_frozen_bench_player_but_not_behind(self):
        old = self._lineup(1, [2, 5], [7, 4, 8])
        ahead = self._lineup(1, [2, 7], [5, 4, 8])
        behind = self._lineup(1, [2, 7], [8, 4, 5])
        self.assertEqual(lineup_deadline.violations(old, ahead, {4}), [])
        errs = lineup_deadline.violations(old, behind, {4})
        self.assertTrue(any("5 non può passare dietro a" in e.replace("giocatore ", "") for e in errs), errs)

    def test_only_the_stretch_ahead_of_a_frozen_man_can_reach_the_xi(self):
        """The figure in the managers' document: the striker at 3 and the
        defender at 4 have not played, and still cannot come up — to let them in,
        the starter who leaves would have to go UNDER the 7.0 at slot 2."""
        old = self._lineup(1, [2, 5], [7, 4, 8, 9])
        from_ahead = self._lineup(1, [2, 7], [5, 4, 8, 9])
        from_behind = self._lineup(1, [2, 8], [7, 4, 5, 9])
        self.assertEqual(lineup_deadline.violations(old, from_ahead, {4}), [])
        self.assertTrue(lineup_deadline.violations(old, from_behind, {4}))

    def test_the_goalkeeper_is_his_own_place(self):
        old = self._lineup(1, [2, 3], [])
        new = self._lineup(2, [1, 3], [])
        self.assertTrue(lineup_deadline.violations(old, new, {1}))

    def test_the_xi_order_is_not_policed_here(self):
        """It is DERIVED instead — see NormaliseXiTests. Nothing a manager chose,
        so nothing to refuse him for."""
        old = self._lineup(1, [2, 3, 4], [])
        new = self._lineup(1, [4, 3, 2], [])
        self.assertEqual(lineup_deadline.violations(old, new, {2, 3, 4}), [])


class NormaliseXiTests(TestCase):
    """The stored XI: always P-D-C-A, frozen players kept inside their own role."""

    ROLES = {1: "DEF", 2: "DEF", 3: "DEF", 4: "DEF", 20: "DEF",
             5: "MID", 6: "MID", 7: "MID",
             8: "ATT", 9: "ATT", 10: "ATT"}
    PREV = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]

    def _norm(self, ids, prev=None, locked=None):
        return lineup_deadline.normalise_xi(ids, self.ROLES, prev, locked)

    def test_a_promoted_substitute_no_longer_lands_at_the_end(self):
        """The bug this exists for: he appeared among his own on screen and sat
        last in the list the substitutions actually read."""
        self.assertEqual(self._norm([1, 2, 3, 4, 6, 7, 8, 9, 10, 5]),
                         [1, 2, 3, 4, 6, 7, 5, 8, 9, 10])

    def test_a_frozen_starter_keeps_his_number_inside_his_role(self):
        # The 6th (a midfielder) is replaced by a defender; the frozen 5th is still
        # the FIRST midfielder, even though the deeper defence pushes him down one.
        out = self._norm([1, 2, 3, 4, 20, 5, 7, 8, 9, 10], self.PREV, {5})
        self.assertEqual(out, [1, 2, 3, 4, 20, 5, 7, 8, 9, 10])
        self.assertEqual(out.index(5) - out.index(20), 1)

    def test_two_frozen_starters_cannot_be_swapped(self):
        """Undone rather than refused: the order is the server's to decide."""
        self.assertEqual(self._norm([1, 2, 3, 4, 6, 5, 7, 8, 9, 10], self.PREV, {5, 6}),
                         self.PREV)

    def test_a_role_that_shrinks_under_him_gives_the_last_place_it_has(self):
        prev = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
        # 4th defender frozen, and the module drops to three at the back.
        out = self._norm([1, 2, 4, 5, 6, 7, 20, 8, 9, 10], prev, {4})
        self.assertEqual(out[:4], [1, 2, 20, 4])

    def test_it_is_idempotent(self):
        once = self._norm([1, 2, 3, 4, 6, 7, 8, 9, 10, 5], self.PREV, {5})
        self.assertEqual(self._norm(once, self.PREV, {5}), once)

    def test_an_unknown_role_keeps_the_tail_instead_of_vanishing(self):
        out = self._norm([1, 5, 8, 999], {**self.ROLES})
        self.assertEqual(len(out), 4)
        self.assertIn(999, out)



class SaveEndpointTests(_Season):
    """The rule as the manager meets it: an HTTP call that is or is not allowed."""

    def _payload(self, gk, xi, bench):
        return {"matchday": 22, "gk_player_id": gk,
                "starter_player_ids": xi, "bench_player_ids": bench}

    def _save(self, gk, xi, bench):
        return self._client().post(
            f"/api/v1/leagues/{self.league.id}/lineup/save",
            self._payload(gk, xi, bench), format="json")

    def setUp(self):
        super().setUp()
        # The lineup as it stood before the weekend: a Saturday keeper, one player
        # from each club, a Monday man on the bench.
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{self.team.id}",
            gk_player_id=str(self.pid["como1"]),
            starter_player_ids=[str(self.pid["milan1"]), str(self.pid["lazio1"])],
            bench_player_ids=[str(self.pid["roma1"]), str(self.pid["como2"])],
        )

    def _played_the_saturday_match(self):
        """Move the calendar so that Saturday is past and Monday is not.

        The endpoint reads the real clock, so the fixture's own dates (a round in
        February) cannot be used as they stand — the whole weekend is behind us and
        every case would collapse into "the round is over"."""
        now = self._now()
        Match.objects.filter(external_id="sat22").update(kickoff=now - timedelta(hours=2))
        Match.objects.filter(external_id="mon22").update(kickoff=now + timedelta(days=1))

    @staticmethod
    def _now():
        from django.utils import timezone
        return timezone.now()

    def test_a_player_already_on_the_pitch_cannot_be_benched(self):
        self._played_the_saturday_match()
        resp = self._save(self.pid["como1"],
                          [str(self.pid["como2"]), str(self.pid["lazio1"])],
                          [str(self.pid["roma1"]), str(self.pid["milan1"])])
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertTrue(any("Milan 1" in e for e in resp.data["errors"]), resp.data)

    def test_the_rest_of_the_lineup_is_still_editable(self):
        self._played_the_saturday_match()
        resp = self._save(self.pid["como1"],
                          [str(self.pid["milan1"]), str(self.pid["roma1"])],
                          [str(self.pid["lazio1"]), str(self.pid["como2"])])
        self.assertEqual(resp.status_code, 200, resp.data)
        snap = SavedLineupSnapshot.objects.get(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{self.team.id}")
        self.assertEqual(snap.bench_player_ids,
                         [str(self.pid["lazio1"]), str(self.pid["como2"])])

    def test_the_matchday_mode_shuts_the_whole_thing(self):
        self.league.lineup_lock_mode = FantasyLeague.LOCK_MATCHDAY
        self.league.save(update_fields=["lineup_lock_mode"])
        self._played_the_saturday_match()
        resp = self._save(self.pid["como1"],
                          [str(self.pid["milan1"]), str(self.pid["roma1"])],
                          [str(self.pid["lazio1"]), str(self.pid["como2"])])
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertIn("già iniziata", resp.data["detail"])

    def test_once_the_last_club_has_kicked_off_the_round_is_shut(self):
        now = self._now()
        Match.objects.filter(external_id="sat22").update(kickoff=now - timedelta(days=2))
        Match.objects.filter(external_id="mon22").update(kickoff=now - timedelta(minutes=5))
        resp = self._save(self.pid["como1"],
                          [str(self.pid["milan1"]), str(self.pid["lazio1"])],
                          [str(self.pid["roma1"]), str(self.pid["como2"])])
        self.assertEqual(resp.status_code, 409, resp.data)
        self.assertIn("già iniziata", resp.data["detail"])

    def test_the_page_says_who_is_frozen(self):
        self._played_the_saturday_match()
        resp = self._client().get(
            f"/api/v1/leagues/{self.league.id}/lineup?matchday=22")
        self.assertEqual(resp.status_code, 200)
        lock = resp.data["lineup_lock"]
        self.assertEqual(lock["mode"], FantasyLeague.LOCK_PLAYER)
        self.assertFalse(lock["closed"])
        self.assertEqual(set(lock["locked_player_ids"]),
                         {self.pid["como1"], self.pid["como2"],
                          self.pid["milan1"], self.pid["milan2"]})
        frozen = {r["player_id"] for r in resp.data["roster"] if r["locked"]}
        self.assertEqual(frozen, set(lock["locked_player_ids"]))


class RepairTests(_Season):
    """R2: la riparazione si ferma al primo calcio d'inizio del turno.

    Non «alla scadenza della formazione», che nella modalita' per giocatore
    arriva il lunedi' sera: in mezzo c'e' una giornata gia' in campo, dove la
    rosa e' quella congelata (R4) e quindi non c'e' niente da riparare — il
    ceduto e' ancora schierabile, l'acquistato non lo e' ancora.
    """

    def setUp(self):
        super().setUp()
        self._snapshot("22")
        now = timezone.now()
        Match.objects.filter(external_id="sat22").update(kickoff=now - timedelta(hours=2))
        Match.objects.filter(external_id="mon22").update(kickoff=now + timedelta(days=1))

    def _snapshot(self, matchday: str):
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id=matchday,
            lineup_id=f"team{self.team.id}",
            gk_player_id=str(self.pid["como1"]),
            starter_player_ids=[str(self.pid["milan1"]), str(self.pid["lazio1"])],
            bench_player_ids=[],
        )

    def test_a_player_on_the_pitch_is_not_swapped_out(self):
        touched = lineup_repair.swap_player(
            self.league, self.team.id, self.pid["milan1"], self.pid["roma2"])
        self.assertEqual(touched, [])
        snap = SavedLineupSnapshot.objects.get(matchday_id="22")
        self.assertIn(str(self.pid["milan1"]), snap.starter_player_ids)

    def test_nor_is_one_who_has_not_kicked_off_yet(self):
        """IL CAMBIO. Il lunedi' non ha ancora giocato e la formazione della 22 e'
        ancora modificabile, ma il turno E' COMINCIATO: la sua rosa e' quella del
        sabato, e il mercato non la tocca piu'. Prima qui la riparazione passava,
        e con essa passava un giocatore comprato a giornata in corso."""
        touched = lineup_repair.swap_player(
            self.league, self.team.id, self.pid["lazio1"], self.pid["roma2"])
        self.assertEqual(touched, [])
        snap = SavedLineupSnapshot.objects.get(matchday_id="22")
        self.assertIn(str(self.pid["lazio1"]), snap.starter_player_ids)
        self.assertNotIn(str(self.pid["roma2"]), snap.starter_player_ids)

    def test_a_round_that_has_not_begun_is_repaired_as_always(self):
        """E il mestiere di R2 resta: sul turno successivo, che non e' cominciato,
        l'acquisto prende il posto del ceduto come ha sempre fatto."""
        Match.objects.create(
            competition_season=self.cs, matchday=23,
            kickoff=timezone.now() + timedelta(days=7), kickoff_provisional=False,
            home_team=self.ts["lazio"], away_team=self.ts["roma"],
            status=Match.STATUS_SCHEDULED, external_source="sofascore", external_id="sat23")
        self._snapshot("23")
        touched = lineup_repair.swap_player(
            self.league, self.team.id, self.pid["lazio1"], self.pid["roma2"])
        self.assertEqual(touched, [23])
        self.assertIn(str(self.pid["roma2"]),
                      SavedLineupSnapshot.objects.get(matchday_id="23").starter_player_ids)
        self.assertIn(str(self.pid["lazio1"]),
                      SavedLineupSnapshot.objects.get(matchday_id="22").starter_player_ids)
