"""What gets pushed while a match is being played, and to whom.

The rule the tests defend is that a push costs the reader's attention: it goes out
for a goal by one of HIS players, a sending-off, and full time — and never for a
vote that moved, which during a round would be a notification every ten minutes per
match and the fastest way to have the permission revoked.

The second rule is that it goes to whoever FIELDED the player, from the saved
lineup. Owning someone you left out is not a reason to be woken up.

La terza e la quarta sono del 31/08/2026, e nascono da due difetti reali trovati
insieme: un gol si annuncia solo se lo confermano DUE testimoni (il tabellino e la
mappa dei tiri), e cio' che e' stato annunciato sta in una tabella invece che in una
differenza fra istantanee — cosi' un annuncio saltato non perde il gol per sempre, e
un gol tolto dal fornitore si puo' smentire.
"""
from __future__ import annotations

from datetime import datetime, timezone as dttz
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings

from realdata.models import (
    CARD_RED, CARD_YELLOW, Competition, CompetitionSeason, Match, MatchAppearance,
    MatchDisciplinaryEvent, MatchShot, Player, Season, Team, TeamSeason,
)
from vfoot.models import (
    FantasyLeague, FantasyMatchday, FantasyTeam, LeagueMembership, LiveEventNotice,
    PushSubscription, SavedLineupSnapshot,
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

    def _score(self, player, goals=1, corroborated=True):
        """Segna, e per difetto lo CONFERMA anche sulla mappa dei tiri.

        I due testimoni si scrivono insieme perche' nella realta' arrivano insieme:
        e' la loro DISCORDANZA che e' l'anomalia, e ha il suo test apposta.
        """
        MatchAppearance.objects.filter(match=self.match, player=player).update(
            goals=goals)
        if not corroborated:
            return
        have = MatchShot.objects.filter(match=self.match, player=player,
                                        is_goal=True).count()
        for i in range(have, goals):
            MatchShot.objects.create(
                match=self.match, player=player, team_side="home", minute=10 + i,
                is_goal=True, shot_type="goal", provider="sofascore")

    def test_a_goal_by_a_fielded_player_is_pushed(self):
        self._score(self.striker)
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1) as send:
            self.assertEqual(live_updates.announce_events(self.match), 1)
        self.assertEqual(send.call_args.args[0], self.owner)
        self.assertIn("Un Attaccante", send.call_args.kwargs["title"])

    def test_a_goal_is_urgent(self):
        """Un gol scade: fra due minuti non e' piu' una notizia, e senza chiederlo
        il servizio del dispositivo e' libero di rimandarlo a schermo spento."""
        self._score(self.striker)
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1) as send:
            live_updates.announce_events(self.match)
        self.assertEqual(send.call_args.kwargs["urgency"], "high")

    def test_a_goal_by_a_benched_player_is_pushed_too(self):
        """He may have come on, and if he has he is scoring for that manager."""
        self._score(self.benched)
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1) as send:
            live_updates.announce_events(self.match)
        send.assert_called_once()

    def test_a_goal_by_somebody_nobody_fielded_is_not_pushed(self):
        self._score(self.stranger)
        with patch.object(live_updates.push_channel, "send_to_user") as send:
            self.assertEqual(live_updates.announce_events(self.match), 0)
        send.assert_not_called()

    def test_a_goal_nobody_was_waiting_for_is_still_written_down(self):
        """«E' successo e non interessava a nessuno» e «non e' ancora stato
        valutato» sono fatti opposti: senza distinguerli ogni round riesaminerebbe
        in eterno gli stessi eventi."""
        self._score(self.stranger)
        with patch.object(live_updates.push_channel, "send_to_user"):
            live_updates.announce_events(self.match)
        notice = LiveEventNotice.objects.get(match=self.match,
                                             player=self.stranger)
        self.assertEqual(notice.recipients, [])

    def test_the_same_goal_is_not_pushed_twice(self):
        self._score(self.striker)
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1):
            self.assertEqual(live_updates.announce_events(self.match), 1)
        with patch.object(live_updates.push_channel, "send_to_user") as send:
            self.assertEqual(live_updates.announce_events(self.match), 0)
        send.assert_not_called()

    def test_a_goal_the_shot_map_does_not_confirm_is_not_pushed(self):
        """Il caso Guðmundsson del 29/08/2026: il tabellino gli attribui' per
        qualche minuto un gol che non esisteva — punteggio fermo, tiro respinto
        sulla mappa — e la notifica falsa parti'. Un testimone non basta."""
        self._score(self.striker, corroborated=False)
        with patch.object(live_updates.push_channel, "send_to_user") as send:
            self.assertEqual(live_updates.announce_events(self.match), 0)
        send.assert_not_called()
        self.assertFalse(LiveEventNotice.objects.exists())

    def test_a_goal_the_shot_map_confirms_late_is_pushed_at_the_next_round(self):
        """Tenere fermo l'annuncio non costa il gol: costa il round successivo.
        E' la differenza fra il registro e la vecchia differenza fra istantanee."""
        self._score(self.striker, corroborated=False)
        with patch.object(live_updates.push_channel, "send_to_user") as send:
            live_updates.announce_events(self.match)
        send.assert_not_called()
        self._score(self.striker)          # arriva la mappa dei tiri
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1) as send:
            self.assertEqual(live_updates.announce_events(self.match), 1)

    def test_a_goal_whose_announcement_never_ran_is_not_lost(self):
        """IL difetto che il registro esiste per chiudere. Prima: l'import scriveva
        il gol, l'annuncio non girava (tick ucciso, import a meta'), e il giro dopo
        il gol era gia' nell'istantanea «prima» — muto per sempre, senza una riga."""
        self._score(self.striker)          # scritto, e nessuno ha annunciato
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1) as send:
            self.assertEqual(live_updates.announce_events(self.match), 1)
        send.assert_called_once()

    def test_a_second_goal_is_its_own_notification(self):
        """Due gol sono due notizie, e la seconda non cancella la prima: il tag
        porta l'occorrenza. «Doppietta» adesso e' un fatto della partita — prima era
        il delta di un round, cioe' un fatto della nostra cadenza."""
        self._score(self.striker)
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1):
            live_updates.announce_events(self.match)
        self._score(self.striker, goals=2)
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1) as send:
            self.assertEqual(live_updates.announce_events(self.match), 1)
        self.assertIn("doppietta", send.call_args.kwargs["title"])
        tags = {n.occurrence for n in LiveEventNotice.objects.filter(
            match=self.match, player=self.striker)}
        self.assertEqual(tags, {1, 2})

    def test_a_goal_taken_back_by_the_provider_is_denied(self):
        """VAR, o un errore del fornitore. Chi legge ha in tendina una notizia
        falsa: la smentita va alle STESSE persone e sullo STESSO tag, cosi' prende
        il posto della notifica invece di affiancarla."""
        self._score(self.striker)
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1) as send:
            live_updates.announce_events(self.match)
        tag = send.call_args.kwargs["tag"]

        MatchAppearance.objects.filter(match=self.match,
                                       player=self.striker).update(goals=0)
        MatchShot.objects.filter(match=self.match, player=self.striker).delete()
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1) as send:
            self.assertEqual(live_updates.announce_events(self.match), 1)
        self.assertEqual(send.call_args.args[0], self.owner)
        self.assertEqual(send.call_args.kwargs["tag"], tag)
        self.assertIn("Annullato", send.call_args.kwargs["title"])
        self.assertIsNotNone(LiveEventNotice.objects.get(
            match=self.match, player=self.striker).retracted_at)

    def test_a_denial_is_sent_once(self):
        self._score(self.striker)
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1):
            live_updates.announce_events(self.match)
        MatchAppearance.objects.filter(match=self.match,
                                       player=self.striker).update(goals=0)
        MatchShot.objects.filter(match=self.match, player=self.striker).delete()
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1):
            live_updates.announce_events(self.match)
        with patch.object(live_updates.push_channel, "send_to_user") as send:
            self.assertEqual(live_updates.announce_events(self.match), 0)
        send.assert_not_called()

    def test_a_goal_given_back_is_announced_again(self):
        """Il VAR che si rimangia il VAR. Chi si e' visto arrivare «annullato» ha
        diritto di sapere che invece quel gol vale."""
        self._score(self.striker)
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1):
            live_updates.announce_events(self.match)
        MatchAppearance.objects.filter(match=self.match,
                                       player=self.striker).update(goals=0)
        MatchShot.objects.filter(match=self.match, player=self.striker).delete()
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1):
            live_updates.announce_events(self.match)
        self._score(self.striker)                      # ...e invece era buono
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1) as send:
            self.assertEqual(live_updates.announce_events(self.match), 1)
        self.assertIn("Gol di", send.call_args.kwargs["title"])
        self.assertIsNone(LiveEventNotice.objects.get(
            match=self.match, player=self.striker).retracted_at)

    def test_who_it_went_to_is_written_down(self):
        """L'unica cosa che permette di rispondere, un mese dopo, a «non mi e'
        arrivata»: prima il contatore diceva «due consegne», non a chi ne' quale."""
        self._score(self.striker)
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1):
            live_updates.announce_events(self.match)
        notice = LiveEventNotice.objects.get(match=self.match,
                                             player=self.striker, kind="goal")
        self.assertEqual(notice.recipients,
                         [{"user_id": self.owner.id, "username": "mario",
                           "devices": 1, "delivered": 1}])
        self.assertEqual(notice.delivered, 1)

    def test_a_sending_off_is_pushed_and_a_booking_is_not(self):
        MatchDisciplinaryEvent.objects.create(
            match=self.match, player=self.striker, team_side="home", minute=30,
            card_type=CARD_YELLOW, provider="sofascore")
        with patch.object(live_updates.push_channel, "send_to_user") as send:
            live_updates.announce_events(self.match)
        send.assert_not_called()

        MatchDisciplinaryEvent.objects.create(
            match=self.match, player=self.striker, team_side="home", minute=70,
            card_type=CARD_RED, provider="sofascore")
        with patch.object(live_updates.push_channel, "send_to_user",
                          return_value=1) as send:
            self.assertEqual(live_updates.announce_events(self.match), 1)
        self.assertIn("espulso", send.call_args.kwargs["title"])

    def test_a_vote_that_moved_is_not_an_event(self):
        """Nothing about the votes reaches the push channel: an import with no goal
        and no red card is silent, however much it changed."""
        MatchAppearance.objects.filter(match=self.match).update(minutes_played=90)
        with patch.object(live_updates.push_channel, "send_to_user") as send:
            self.assertEqual(live_updates.announce_events(self.match), 0)
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
        self._score(self.striker)
        with patch.object(live_updates.push_channel, "send_to_user") as send:
            self.assertEqual(live_updates.announce_events(self.match), 0)
            self.assertEqual(live_updates.announce_full_time(self.match), 0)
        send.assert_not_called()

    def test_a_failure_in_the_push_channel_does_not_reach_the_tick(self):
        self._score(self.striker)
        with patch.object(live_updates.push_channel, "send_to_user",
                          side_effect=RuntimeError("boom")), \
             self.assertLogs("vfoot.services.live_updates", level="ERROR"):
            self.assertEqual(live_updates.announce_events(self.match), 0)


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
