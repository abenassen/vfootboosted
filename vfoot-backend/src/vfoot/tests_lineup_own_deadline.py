"""La modalita' «alla prima partita di un tuo giocatore» (``own``), e il mercato
che non si muove per tutta la giornata.

Il venerdi' gioca il club A, il sabato il club B, il lunedi' il club C. Una
squadra che non ha nessuno nel club A ha tempo fino a sabato; una che ci ha anche
un solo panchinaro, no — e' il test che conta, perche' la scadenza si calcola sui
venticinque e non sugli undici.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
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
from vfoot.services import lineup_repair, matchday_state

ROLE_SEED = {"GK": "POR", "DEF": "DIF", "MID": "CEN", "ATT": "ATT"}


class _OwnRound(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        season = Season.objects.create(code="2026-2027")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=season, name="Serie A 2026-2027")
        self.owner = User.objects.create_user("owner", "o@x.it", "pw")
        self.league = FantasyLeague.objects.create(
            name="Lega", owner=self.owner, mode=FantasyLeague.MODE_CLASSIC,
            reference_season=self.cs, lineup_lock_mode=FantasyLeague.LOCK_OWN,
            defense_bonus_enabled=True)
        self.membership = LeagueMembership.objects.create(
            league=self.league, user=self.owner, role=LeagueMembership.ROLE_ADMIN)
        self.team = FantasyTeam.objects.create(
            league=self.league, manager=self.membership, name="Squadra")

        self.ts = {}
        for code in ("ven", "sab", "lun", "x1", "x2", "x3"):
            club = Team.objects.create(name=code.title(), short_name=code.title())
            self.ts[code] = TeamSeason.objects.create(competition_season=self.cs, team=club)
        now = timezone.now()
        self.FRI = now - timedelta(hours=12)     # gia' giocata
        self.SAT = now + timedelta(hours=6)      # deve ancora cominciare
        self.MON = now + timedelta(days=2)
        for code, opp, when, ext in (("ven", "x1", self.FRI, "fri"),
                                     ("sab", "x2", self.SAT, "sat"),
                                     ("lun", "x3", self.MON, "mon")):
            Match.objects.create(
                competition_season=self.cs, matchday=5, kickoff=when,
                kickoff_provisional=False, home_team=self.ts[code], away_team=self.ts[opp],
                status=Match.STATUS_FINISHED if when < now else Match.STATUS_SCHEDULED,
                data_ready=when < now,
                external_source="sofascore", external_id=ext)
        FantasyMatchday.objects.create(
            league=self.league, real_competition_season=self.cs, real_matchday=5)
        self.pid: dict[str, int] = {}

    def add(self, key, role, club, acquired_at=None):
        p = Player.objects.create(full_name=key, short_name=key, classic_role_seed=ROLE_SEED[role])
        PlayerTeamStint.objects.create(player=p, team_season=self.ts[club])
        kw = {"acquired_at": acquired_at} if acquired_at else {}
        FantasyRosterSlot.objects.create(team=self.team, player=p, purchase_price=10, **kw)
        self.pid[key] = p.id
        return p

    def saturday_roster(self):
        """Undici e panchina tutti del sabato e del lunedi': niente del venerdi'."""
        self.add("gk", "GK", "sab")
        for i in range(1, 5):
            self.add(f"d{i}", "DEF", "sab")
        for i in range(1, 5):
            self.add(f"m{i}", "MID", "sab")
        for i in range(1, 3):
            self.add(f"a{i}", "ATT", "lun")
        self.add("dbench", "DEF", "lun")
        self.add("abench", "ATT", "lun")

    def _client(self):
        token, _ = Token.objects.get_or_create(user=self.owner)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return c

    def _xi(self, *names):
        return [self.pid[n] for n in names]

    OUTFIELD = ("d1", "d2", "d3", "d4", "m1", "m2", "m3", "m4", "a1", "a2")

    def _post(self, outfield=None, bench=("dbench", "abench")):
        return self._client().post(
            f"/api/v1/leagues/{self.league.id}/lineup/save",
            {"matchday": 5, "gk_player_id": self.pid["gk"],
             "starter_player_ids": self._xi(*(outfield or self.OUTFIELD)),
             "bench_player_ids": self._xi(*bench)},
            format="json")

    def _get(self):
        return self._client().get(
            f"/api/v1/leagues/{self.league.id}/lineup?matchday=5").data


class TheDeadlineIsTheTeamsOwnTests(_OwnRound):
    def test_without_a_friday_player_saturday_morning_is_still_open(self):
        self.saturday_roster()
        r = self._post()
        self.assertEqual(r.status_code, 200, r.data)

    def test_a_benched_friday_player_closes_it(self):
        """IL TEST CHE CONTA: il giocatore del venerdi' e' in PANCHINA, non fra i
        titolari. Se la scadenza guardasse gli undici, il suo voto sarebbe sul
        tabellone mentre si schiera — ed e' proprio la falla che la modalita'
        deve chiudere."""
        self.saturday_roster()
        self.add("fribench", "MID", "ven")
        r = self._post(bench=("dbench", "abench", "fribench"))
        self.assertEqual(r.status_code, 409, r.data)
        self.assertIn("Ven-X1", r.data["detail"])

    def test_the_payload_names_the_match_that_closes_it(self):
        self.saturday_roster()
        d = self._get()
        lock = d["lineup_lock"]
        self.assertEqual(lock["mode"], "own")
        self.assertFalse(lock["closed"])
        self.assertEqual(lock["closes_with"], {"home": "Sab", "away": "X2"})
        self.assertEqual(lock["closes_at"][:16], self.SAT.isoformat()[:16])

    def test_a_postponement_moves_the_deadline_to_the_recovery(self):
        self.saturday_roster()
        Match.objects.filter(external_id="sat").update(status=Match.STATUS_POSTPONED)
        deadline, closing = matchday_state.team_deadline(self.league, self.team, 5)
        self.assertEqual(deadline, self.MON)
        self.assertEqual(closing.external_id, "mon")

    def test_the_defender_count_rule_does_not_exist_here(self):
        """R1 e' il prezzo della sola modalita' 3: qui, quando salvo, nessuno
        dei miei ha un voto. La giornata e' cominciata (il venerdi'), io no."""
        self.saturday_roster()
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="5",
            lineup_id=f"team{self.team.id}", gk_player_id=str(self.pid["gk"]),
            starter_player_ids=self._xi(*self.OUTFIELD),
            bench_player_ids=self._xi("dbench", "abench"))
        # Da 4 a 3 difensori: fuori d4, dentro l'attaccante di riserva.
        r = self._post(("d1", "d2", "d3", "m1", "m2", "m3", "m4", "abench", "a1", "a2"),
                       bench=("dbench", "d4"))
        self.assertEqual(r.status_code, 200, r.data)

    def test_without_a_team_the_round_closes_at_its_latest(self):
        """Calendario, viste di lega, admin: senza squadra la risposta e' la
        scadenza piu' tarda, o una giornata risulterebbe chiusa mentre qualcuno
        puo' ancora schierare."""
        self.assertEqual(matchday_state.closed_matchdays(self.league), set())
        later = self.MON + timedelta(minutes=1)
        self.assertEqual(matchday_state.closed_matchdays(self.league, later), {5})

    def test_next_fieldable_is_per_team(self):
        self.saturday_roster()
        self.add("fribench", "MID", "ven")
        FantasyMatchday.objects.create(
            league=self.league, real_competition_season=self.cs, real_matchday=6)
        Match.objects.create(
            competition_season=self.cs, matchday=6, kickoff=self.MON + timedelta(days=4),
            kickoff_provisional=False, home_team=self.ts["ven"], away_team=self.ts["x1"],
            status=Match.STATUS_SCHEDULED, external_source="sofascore", external_id="fri6")
        self.assertEqual(matchday_state.next_fieldable_matchday(self.league, team=self.team), 6)
        self.assertEqual(matchday_state.next_fieldable_matchday(self.league), 5)


class TheMarketCannotReopenAClosedRoundTests(_OwnRound):
    """Le due mosse di mercato che la scadenza «sui posseduti adesso» lascerebbe
    passare. Il mercato vero e' fermo per tutta la giornata (v. sotto), ma la
    rosa la puo' muovere anche l'admin a mano: la scadenza deve reggere da sola.
    """

    def test_selling_a_man_who_already_played_does_not_reopen_the_lineup(self):
        """Venduto dopo il suo calcio d'inizio: era mio quando contava, e il suo
        4.5 resta mio. Senza questo, la riparazione lo scambierebbe con uno che
        gioca domenica."""
        self.saturday_roster()
        fri = self.add("fri", "MID", "ven", acquired_at=self.FRI - timedelta(days=30))
        snap = SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="5",
            lineup_id=f"team{self.team.id}", gk_player_id=str(self.pid["gk"]),
            starter_player_ids=self._xi("d1", "d2", "d3", "d4", "fri", "m2", "m3", "m4", "a1", "a2"),
            bench_player_ids=self._xi("dbench", "abench", "m1"))
        deadline, _ = matchday_state.team_deadline(self.league, self.team, 5)
        self.assertEqual(deadline, self.FRI)
        # La vendita, un'ora dopo la partita.
        FantasyRosterSlot.objects.filter(team=self.team, player=fri).update(
            released_at=self.FRI + timedelta(hours=3))
        deadline, _ = matchday_state.team_deadline(self.league, self.team, 5)
        self.assertEqual(deadline, self.FRI, "chiusa resta chiusa")
        touched = lineup_repair.swap_player(self.league, self.team.id, fri.id, self.pid["m1"])
        self.assertEqual(touched, [])
        snap.refresh_from_db()
        self.assertIn(fri.id, [int(x) for x in snap.starter_player_ids])

    def test_selling_a_man_before_his_kickoff_does_not_bind(self):
        self.saturday_roster()
        fri = self.add("fri", "MID", "ven")
        FantasyRosterSlot.objects.filter(team=self.team, player=fri).update(
            acquired_at=self.FRI - timedelta(days=3),
            released_at=self.FRI - timedelta(hours=1))
        deadline, _ = matchday_state.team_deadline(self.league, self.team, 5)
        self.assertEqual(deadline, self.SAT)

    def test_buying_a_man_who_already_played_closes_rather_than_pays(self):
        """Comprato sabato uno che ha preso 8 venerdi': la sua partita e' la mia
        scadenza, quindi la formazione e' chiusa e il voto noto non entra."""
        self.saturday_roster()
        self.add("fri", "MID", "ven", acquired_at=self.FRI + timedelta(hours=5))
        deadline, _ = matchday_state.team_deadline(self.league, self.team, 5)
        self.assertEqual(deadline, self.FRI)
        self.assertEqual(self._post().status_code, 409)


class TheMarketFreezesForTheWholeRoundTests(_OwnRound):
    """«Giornata in corso» e' la giornata, non ciascuna partita: fra il venerdi'
    e il sabato il mercato resta fermo."""

    def test_between_friday_and_saturday_the_round_is_still_playing(self):
        self.assertEqual(matchday_state.playing_matchday(self.league), 5)
        self.assertTrue(matchday_state.is_matchday_in_progress(self.league))

    def test_before_the_first_kickoff_nothing_is_playing(self):
        self.assertIsNone(matchday_state.playing_matchday(
            self.league, self.FRI - timedelta(hours=1)))

    def test_after_the_last_match_has_settled_it_is_over(self):
        after = self.MON + timedelta(hours=4)
        Match.objects.filter(matchday=5).update(status=Match.STATUS_FINISHED, data_ready=True)
        self.assertIsNone(matchday_state.playing_matchday(self.league, after))

    def test_a_recovery_weeks_later_does_not_keep_the_round_on_the_pitch(self):
        Match.objects.filter(external_id="mon").update(kickoff=self.MON + timedelta(days=30))
        Match.objects.filter(external_id="sat").update(
            kickoff=self.FRI + timedelta(hours=20), status=Match.STATUS_FINISHED, data_ready=True)
        a_week_on = self.FRI + timedelta(days=7)
        self.assertIsNone(matchday_state.playing_matchday(self.league, a_week_on))
        # ...and it is playing again on the day of the recovery.
        self.assertEqual(matchday_state.playing_matchday(
            self.league, self.MON + timedelta(days=30, hours=1)), 5)


class ChangingTheModeTests(_OwnRound):
    """Un cambio di modalita' vale dalla prossima giornata, mai da quella in
    corso — e il regolamento di una giornata e' quello in vigore al suo primo
    calcio d'inizio, non quello del momento in cui l'admin preme Concludi."""

    def _patch(self, **data):
        return self._client().patch(
            f"/api/v1/leagues/{self.league.id}/settings", data, format="json")

    def test_before_the_first_kickoff_the_mode_can_change_and_saved_lineups_follow(self):
        """Il caso della lega in produzione: formazioni inserite in «own», poi il
        passaggio a «player» prima di stasera. Lo snapshot non porta la modalita'
        — solo portiere, undici e ordine della panchina — quindi tutto cio' che
        dipende dalla modalita' si rilegge dal vivo e resta coerente."""
        self.saturday_roster()
        Match.objects.filter(matchday=5).update(kickoff=timezone.now() + timedelta(days=1))
        self.assertEqual(self._post().status_code, 200)
        r = self._patch(lineup_lock_mode="player")
        self.assertEqual(r.status_code, 200, r.data)
        self.league.refresh_from_db()
        self.assertEqual(self.league.lineup_lock_mode, "player")
        d = self._get()
        self.assertEqual(d["lineup_lock"]["mode"], "player")
        self.assertEqual(d["lineup_source"]["kind"], "saved")
        self.assertEqual(len(d["saved_lineup"]["starter_player_ids"]), 10)
        # E le due passate sono accese, da ora, per tutti: regola di lega.
        from vfoot.services.classic_scoring import Ruleset
        self.assertTrue(Ruleset.from_league(self.league).defence_first)

    def test_during_the_round_the_mode_cannot_change(self):
        """Il venerdi' e' stato giocato, il sabato no: giornata in corso."""
        r = self._patch(lineup_lock_mode="player")
        self.assertEqual(r.status_code, 409, r.data)
        self.assertIn("in corso", r.data["detail"])
        r = self._patch(enforce_lineup_deadline=False)
        self.assertEqual(r.status_code, 409, r.data)
        self.league.refresh_from_db()
        self.assertEqual(self.league.lineup_lock_mode, "own")
        self.assertTrue(self.league.enforce_lineup_deadline)

    def test_resending_the_same_mode_during_the_round_is_not_a_change(self):
        """La pagina manda tutto il modulo: un valore uguale non e' un cambio."""
        r = self._patch(lineup_lock_mode="own", enforce_lineup_deadline=True)
        self.assertEqual(r.status_code, 200, r.data)

    def test_after_the_round_has_settled_the_mode_can_change_again(self):
        Match.objects.filter(matchday=5).update(
            kickoff=timezone.now() - timedelta(days=3), status=Match.STATUS_FINISHED,
            data_ready=True)
        r = self._patch(lineup_lock_mode="player")
        self.assertEqual(r.status_code, 200, r.data)

    def test_the_rules_of_a_round_are_frozen_at_its_first_kickoff(self):
        """Il regolamento si congela la prima volta che la giornata viene
        calcolata dopo il calcio d'inizio, e la conclusione legge quello: un
        cambio di impostazioni a giornata in corso — qui il voto d'ufficio —
        non riscrive una giornata gia' giocata."""
        from vfoot.services.classic_matchday_scoring import ruleset_for_round

        md = FantasyMatchday.objects.get(league=self.league, real_matchday=5)
        rs = ruleset_for_round(self.league, md)
        self.assertEqual(rs.sv_office_vote, 0.0)
        md.refresh_from_db()
        self.assertTrue(md.ruleset_snapshot, "congelato: il venerdi' e' gia' stato giocato")
        self.league.sv_office_vote = 4.0
        self.league.save(update_fields=["sv_office_vote"])
        self.assertEqual(ruleset_for_round(self.league, md).sv_office_vote, 0.0)

    def test_before_the_kickoff_nothing_is_frozen(self):
        from vfoot.services.classic_matchday_scoring import ruleset_for_round

        Match.objects.filter(matchday=5).update(kickoff=timezone.now() + timedelta(days=1))
        md = FantasyMatchday.objects.get(league=self.league, real_matchday=5)
        ruleset_for_round(self.league, md)
        md.refresh_from_db()
        self.assertFalse(md.ruleset_snapshot)
