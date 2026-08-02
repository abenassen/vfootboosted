"""What gets pushed while a match is being played, and to whom.

The rule the tests defend is that a push costs the reader's attention: it goes out
for a goal by one of HIS players, a sending-off, and full time — and never for a
vote that moved, which during a round would be a notification every ten minutes per
match and the fastest way to have the permission revoked.

The second rule is that it goes to whoever FIELDED the player, from the saved
lineup. Owning someone you left out is not a reason to be woken up.
"""
from __future__ import annotations

from datetime import datetime, timezone as dttz
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from realdata.models import (
    CARD_RED, CARD_YELLOW, Competition, CompetitionSeason, Match, MatchAppearance,
    MatchDisciplinaryEvent, Player, Season, Team, TeamSeason,
)
from vfoot.models import (
    FantasyLeague, FantasyMatchday, FantasyTeam, LeagueMembership, PushSubscription,
    SavedLineupSnapshot,
)
from vfoot.services import live_updates

KEYS = dict(VFOOT_VAPID_PUBLIC_KEY="BPub", VFOOT_VAPID_PRIVATE_KEY="priv")
SAT = datetime(2027, 1, 30, 14, 0, tzinfo=dttz.utc)


@override_settings(**KEYS)
class LiveEventPushTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"))
        self.owner = User.objects.create_user("mario", "m@x.it", "pw")
        self.league = FantasyLeague.objects.create(
            name="Lega", owner=self.owner, mode=FantasyLeague.MODE_CLASSIC,
            reference_season=self.cs)
        mem = LeagueMembership.objects.create(
            league=self.league, user=self.owner, role=LeagueMembership.ROLE_ADMIN)
        self.team = FantasyTeam.objects.create(
            league=self.league, manager=mem, name="I Miei")
        PushSubscription.objects.create(
            user=self.owner, endpoint="https://push/1", p256dh="k", auth="a")

        home = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Napoli"))
        away = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Inter"))
        self.match = Match.objects.create(
            competition_season=self.cs, matchday=22, kickoff=SAT,
            kickoff_provisional=False, home_team=home, away_team=away,
            status=Match.STATUS_LIVE, home_goals=1, away_goals=0,
            external_source="sofascore", external_id="900")
        self.md = FantasyMatchday.objects.create(
            league=self.league, real_competition_season=self.cs, real_matchday=22)

        self.striker = Player.objects.create(full_name="Un Attaccante")
        self.benched = Player.objects.create(full_name="Un Panchinaro")
        self.stranger = Player.objects.create(full_name="Uno Di Un'Altra Rosa")
        for p in (self.striker, self.benched, self.stranger):
            MatchAppearance.objects.create(
                match=self.match, player=p, team_season=home, side="home",
                minutes_played=45, goals=0)
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{self.team.id}",
            starter_player_ids=[self.striker.id],
            bench_player_ids=[self.benched.id])

    def _score(self, player, goals=1):
        MatchAppearance.objects.filter(match=self.match, player=player).update(
            goals=goals)

    def test_a_goal_by_a_fielded_player_is_pushed(self):
        before = live_updates.snapshot_events(self.match)
        self._score(self.striker)
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1) as send:
            self.assertEqual(live_updates.announce_events(self.match, before), 1)
        self.assertEqual(send.call_args.args[0], self.owner)
        self.assertIn("Un Attaccante", send.call_args.kwargs["title"])

    def test_a_goal_by_a_benched_player_is_pushed_too(self):
        """He may have come on, and if he has he is scoring for that manager."""
        before = live_updates.snapshot_events(self.match)
        self._score(self.benched)
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1) as send:
            live_updates.announce_events(self.match, before)
        send.assert_called_once()

    def test_a_goal_by_somebody_nobody_fielded_is_not_pushed(self):
        before = live_updates.snapshot_events(self.match)
        self._score(self.stranger)
        with patch.object(live_updates.push_channel, "send_to_user") as send:
            self.assertEqual(live_updates.announce_events(self.match, before), 0)
        send.assert_not_called()

    def test_the_same_goal_is_not_pushed_twice(self):
        """The second import sees it in both snapshots and stays quiet — which is the
        whole reason the events are read off a difference and not off the data."""
        self._score(self.striker)
        before = live_updates.snapshot_events(self.match)
        with patch.object(live_updates.push_channel, "send_to_user") as send:
            self.assertEqual(live_updates.announce_events(self.match, before), 0)
        send.assert_not_called()

    def test_a_sending_off_is_pushed_and_a_booking_is_not(self):
        before = live_updates.snapshot_events(self.match)
        MatchDisciplinaryEvent.objects.create(
            match=self.match, player=self.striker, team_side="home", minute=30,
            card_type=CARD_YELLOW, provider="sofascore")
        with patch.object(live_updates.push_channel, "send_to_user") as send:
            live_updates.announce_events(self.match, before)
        send.assert_not_called()

        MatchDisciplinaryEvent.objects.create(
            match=self.match, player=self.striker, team_side="home", minute=70,
            card_type=CARD_RED, provider="sofascore")
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1) as send:
            self.assertEqual(live_updates.announce_events(self.match, before), 1)
        self.assertIn("espulso", send.call_args.kwargs["title"])

    def test_a_vote_that_moved_is_not_an_event(self):
        """Nothing about the votes reaches the push channel: an import with no goal
        and no red card is silent, however much it changed."""
        before = live_updates.snapshot_events(self.match)
        MatchAppearance.objects.filter(match=self.match).update(minutes_played=90)
        with patch.object(live_updates.push_channel, "send_to_user") as send:
            self.assertEqual(live_updates.announce_events(self.match, before), 0)
        send.assert_not_called()

    def test_full_time_reaches_whoever_had_players_in_the_match(self):
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1) as send:
            self.assertEqual(live_updates.announce_full_time(self.match), 1)
        self.assertIn("Finita", send.call_args.kwargs["title"])
        self.assertIn("Napoli 1-0 Inter", send.call_args.kwargs["title"])

    def test_a_concluded_matchday_is_never_notified(self):
        """It is frozen: whatever happens in a recovery of it is the admin's business."""
        self.md.status = FantasyMatchday.STATUS_CONCLUDED
        self.md.save(update_fields=["status"])
        before = live_updates.snapshot_events(self.match)
        self._score(self.striker)
        with patch.object(live_updates.push_channel, "send_to_user") as send:
            self.assertEqual(live_updates.announce_events(self.match, before), 0)
            self.assertEqual(live_updates.announce_full_time(self.match), 0)
        send.assert_not_called()

    def test_a_failure_in_the_push_channel_does_not_reach_the_tick(self):
        before = live_updates.snapshot_events(self.match)
        self._score(self.striker)
        with patch.object(live_updates.push_channel, "send_to_user",
                          side_effect=RuntimeError("boom")), \
             self.assertLogs("vfoot.services.live_updates", level="ERROR"):
            self.assertEqual(live_updates.announce_events(self.match, before), 0)


class BroadcastTests(TestCase):
    def test_only_the_leagues_on_this_championship_are_nudged(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"))
        other = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2025-2026"))
        owner = User.objects.create_user("mario", "m@x.it", "pw")
        FantasyLeague.objects.create(name="Questa", owner=owner,
                                     mode=FantasyLeague.MODE_CLASSIC,
                                     reference_season=cs)
        FantasyLeague.objects.create(name="Un'altra", owner=owner,
                                     mode=FantasyLeague.MODE_CLASSIC,
                                     reference_season=other)
        ts = TeamSeason.objects.create(
            competition_season=cs, team=Team.objects.create(name="Napoli"))
        match = Match.objects.create(competition_season=cs, matchday=22,
                                     home_team=ts, away_team=ts,
                                     external_source="sofascore", external_id="900")
        with patch("vfoot.services.live_realtime.broadcast_live") as nudge:
            self.assertEqual(live_updates.broadcast_match(match), 1)
        nudge.assert_called_once()
