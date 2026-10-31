"""«Con tutti a 6»: la terza lettura di un turno in corso.

Chi deve ancora giocare prende un 6 d'ufficio, le partite in corso si leggono come
se finissero adesso, e chi sappiamo che non giochera' resta un senza voto che la
panchina copre. Queste prove circoscrivono le tre cose, e la quarta che le rende
innocue: e' una lettura, e il punteggio vero non si muove.
"""
from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from realdata.models import (
    LineupEvidence, LineupForecast, LineupForecastEntry, Match, Player,
    PlayerTeamStint,
)
from vfoot.models import FantasyFixtureDetail
from vfoot.services.round_simulation import unavailable_for_simulation
from vfoot.tests_live_projection import LiveProjectionTests as _Base

TONIGHT = timezone.now() + timedelta(hours=5)


class RoundSimulationTests(_Base):
    # Le prove della lettura «se finisse adesso» girano gia' nella loro classe:
    # qui si eredita solo l'impianto.
    for _name in [n for n in vars(_Base) if n.startswith("test_")]:
        locals()[_name] = None
    del _name

    def setUp(self):
        super().setUp()
        self._squad()
        self.tonight = self._club("Lazio")
        self.rival = self._club("Roma")
        self.later = Match.objects.create(
            competition_season=self.cs, matchday=22, kickoff=TONIGHT,
            kickoff_provisional=False, home_team=self.tonight, away_team=self.rival,
            status=Match.STATUS_SCHEDULED, data_ready=False,
            external_source="sofascore", external_id="901")

    def _tonight(self, name: str, role: str) -> Player:
        p = Player.objects.create(full_name=name, short_name=name, classic_role_seed=role)
        PlayerTeamStint.objects.create(player=p, team_season=self.tonight)
        return p

    def _six(self):
        res = self.client.get(f"/api/v1/fixtures/{self.fixture.id}?projection=six")
        self.assertEqual(res.status_code, 200)
        return res.data

    def _with_tonight(self, *players, bench=()):
        """Gli attaccanti titolari diventano giocatori di stasera."""
        atts = list(players) + self.atts[len(players):]
        self._field(self.gk, self.defs + self.mids + atts, [self.reserve, *bench])

    def test_who_has_still_to_play_gets_a_six_that_says_it_is_simulated(self):
        late = self._tonight("Stasera", "ATT")
        self._with_tonight(late)
        line = self._line(self._six(), late)
        self.assertFalse(line["sv"])
        self.assertEqual(line["fantavoto"], 6.0)
        self.assertTrue(line["simulated"])
        self.assertIsNone(line["replaced_by"])

    def test_it_contains_the_other_reading(self):
        """Le partite in corso si leggono come se finissero adesso: il titolare
        mai entrato e' gia' sostituito."""
        d = self._six()
        self.assertTrue(d["projected"])
        self.assertTrue(d["sufficiency"])
        self.assertIn(self.not_entered.id,
                      [s["out"]["player_id"] for s in d["home"]["substitutions"]])

    def test_a_suspended_player_stays_out_and_the_bench_covers_him(self):
        """Squalificato dai cartellini: niente 6, e la panchina entra per lui con
        il SUO 6 se gioca stasera."""
        late = self._tonight("Squalificato", "ATT")
        sub = self._tonight("Panchinaro", "ATT")
        before = Match.objects.create(
            competition_season=self.cs, matchday=21,
            kickoff=timezone.now() - timedelta(days=7), kickoff_provisional=False,
            home_team=self.tonight, away_team=self._club("Genoa"),
            status=Match.STATUS_FINISHED, data_ready=True,
            external_source="sofascore", external_id="800")
        from realdata.models import MatchDisciplinaryEvent
        MatchDisciplinaryEvent.objects.create(match=before, player=late, card_type="red")
        self._with_tonight(late, bench=[sub])
        d = self._six()
        line = self._line(d, late)
        self.assertTrue(line["sv"])
        self.assertEqual(line["sv_reason"], "indisponibile")
        self.assertIn("espulso", line["absence"])
        self.assertEqual(self._line(d, sub)["fantavoto"], 6.0)
        self.assertTrue(self._line(d, sub)["entered"])

    def test_a_declared_absence_excludes_but_a_doubt_does_not(self):
        out = self._tonight("Infortunato", "ATT")
        doubt = self._tonight("In Dubbio", "ATT")
        for p, avail in ((out, LineupEvidence.AVAIL_OUT), (doubt, LineupEvidence.AVAIL_DOUBT)):
            LineupEvidence.objects.create(
                competition_season=self.cs, player=p, matchday=22,
                kind=LineupEvidence.KIND_INJURY, availability=avail,
                source="sofascore", note="lesione muscolare")
        got = unavailable_for_simulation(self.cs.id, 22, {out.id, doubt.id})
        self.assertEqual(got, {out.id: "lesione muscolare"})

    def test_the_official_squad_excludes_who_is_not_on_it(self):
        listed = [self._tonight(f"Convocato{i}", "CEN") for i in range(18)]
        left_out = self._tonight("Tribuna", "CEN")
        fc = LineupForecast.objects.create(
            match=self.later, source=LineupForecast.SOURCE_SOFASCORE, official=True)
        LineupForecastEntry.objects.bulk_create(
            LineupForecastEntry(forecast=fc, player=p, team_season=self.tonight)
            for p in listed)
        ids = {p.id for p in listed} | {left_out.id}
        self.assertEqual(unavailable_for_simulation(self.cs.id, 22, ids),
                         {left_out.id: "non convocato"})

    def test_a_partial_official_squad_excludes_nobody(self):
        """Pochi agganciati: chi manca puo' essere un nome non risolto, e dargli il
        6 e' l'errore piccolo."""
        listed = [self._tonight(f"Convocato{i}", "CEN") for i in range(12)]
        left_out = self._tonight("Forse", "CEN")
        fc = LineupForecast.objects.create(
            match=self.later, source=LineupForecast.SOURCE_SOFASCORE, official=True)
        LineupForecastEntry.objects.bulk_create(
            LineupForecastEntry(forecast=fc, player=p, team_season=self.tonight)
            for p in listed)
        self.assertEqual(unavailable_for_simulation(self.cs.id, 22, {left_out.id}), {})

    def test_the_leagues_own_office_vote_wins_over_the_simulation(self):
        from vfoot.models import OfficeOverride
        late = self._tonight("Rinviato", "ATT")
        self._with_tonight(late)
        OfficeOverride.objects.create(league=self.league, fantasy_matchday=self.md,
                                      match=self.later, voto=5.0, created_by=self.user)
        line = self._line(self._six(), late)
        self.assertEqual(line["fantavoto"], 5.0)
        self.assertFalse(line.get("simulated"))

    def test_it_is_a_reading_and_says_whether_it_has_anything_to_say(self):
        late = self._tonight("Stasera", "ATT")
        self._with_tonight(late)
        before = self._detail()
        self.assertTrue(before["has_unplayed"])
        d = self._six()
        self.assertNotEqual(d["home_total"], before["home_total"])
        self.assertEqual(d["actual"]["home_total"], before["home_total"])
        self.assertEqual(self._detail()["home_total"], before["home_total"])
        self.assertFalse(FantasyFixtureDetail.objects.filter(fixture=self.fixture).exists())

    def test_nobody_left_to_play_means_nothing_to_simulate(self):
        self.assertFalse(self._detail()["has_unplayed"])
