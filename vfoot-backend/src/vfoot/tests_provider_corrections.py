"""Una rettifica del fornitore su una giornata che la lega ha GIA' concluso.

La regola (30/10/2026): un FATTO corretto segna la giornata e avvisa gli admin con
le sfide che si muoverebbero; il risultato congelato non cambia finche' l'admin non
ricalcola. Il solo xG rivisto non arriva fin qui (``live_ingest.fact_changes``).
"""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from realdata.models import Competition, CompetitionSeason, Match, Season, Team, TeamSeason
from realdata.services import live_ingest
from vfoot.models import (
    FantasyCompetition, FantasyFixture, FantasyFixtureDetail, FantasyLeague,
    FantasyMatchday, FantasyTeam, LeagueMembership,
)
from vfoot.services import provider_corrections

FACTS = ["Thorstvedt (#1): gol 1 -> 0", "Sutalo (#2): autogol 0 -> 1"]
MOVING = [{"fixture_id": 1, "home": "I Miei", "away": "I Loro",
           "before": {"totals": (68.0, 66.5), "goals": (1, 1)},
           "after": {"totals": (65.0, 66.5), "goals": (0, 1)}}]


@override_settings(VFOOT_NOTIFY_EMAILS=True)
class ProviderCorrectionTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        self.admin = User.objects.create_user("mario", "m@x.it", "pw")
        self.league = self._league("Classica", FantasyLeague.MODE_CLASSIC)
        home = TeamSeason.objects.create(competition_season=self.cs,
                                         team=Team.objects.create(name="Sassuolo"))
        away = TeamSeason.objects.create(competition_season=self.cs,
                                         team=Team.objects.create(name="Lazio"))
        self.match = Match.objects.create(
            competition_season=self.cs, matchday=9, home_team=home, away_team=away,
            kickoff=timezone.now() - timedelta(days=2), kickoff_provisional=False,
            status=Match.STATUS_FINISHED, data_ready=True,
            external_source="sofascore", external_id="16285065")

    def _league(self, name, mode):
        league = FantasyLeague.objects.create(name=name, owner=self.admin, mode=mode,
                                              reference_season=self.cs)
        LeagueMembership.objects.create(league=league, user=self.admin,
                                        role=LeagueMembership.ROLE_ADMIN)
        return league

    def _round(self, league=None, status=FantasyMatchday.STATUS_CONCLUDED, matchday=9):
        return FantasyMatchday.objects.create(
            league=league or self.league, real_competition_season=self.cs,
            real_matchday=matchday, status=status)

    def _flag(self, facts=FACTS, moving=MOVING):
        with mock.patch.object(provider_corrections, "fixtures_that_would_move",
                               return_value=moving), \
             self.captureOnCommitCallbacks(execute=True):
            return provider_corrections.flag_concluded_rounds(self.match, facts)

    def test_una_giornata_conclusa_viene_segnata_e_l_admin_avvisato(self):
        md = self._round()
        flagged = self._flag()
        md.refresh_from_db()
        self.assertIsNotNone(md.correction_pending_at)
        self.assertIn("Sassuolo-Lazio", md.correction_note)
        self.assertIn("Sutalo", md.correction_note)
        self.assertIn("I Miei-I Loro: 68-66.5 -> 65-66.5 (risultato 1-1 -> 0-1)",
                      md.correction_note)
        self.assertEqual(flagged[0]["fixtures_moving"], 1)
        (msg,) = mail.outbox
        self.assertEqual(msg.to, ["m@x.it"])
        self.assertIn("giornata 9", msg.subject)
        self.assertIn("regole congelate", msg.body)

    def test_una_giornata_non_conclusa_non_ne_ha_bisogno(self):
        """Si calcola dal vivo: legge gia' i dati corretti."""
        md = self._round(status=FantasyMatchday.STATUS_PLANNED)
        self.assertEqual(self._flag(), [])
        md.refresh_from_db()
        self.assertIsNone(md.correction_pending_at)
        self.assertEqual(mail.outbox, [])

    def test_le_leghe_aura_restano_fuori(self):
        aura = self._league("Aura", FantasyLeague.MODE_AURA)
        md = self._round(league=aura)
        self._flag()
        md.refresh_from_db()
        self.assertIsNone(md.correction_pending_at)

    def test_un_altra_giornata_non_e_toccata(self):
        md = self._round(matchday=8)
        self._flag()
        md.refresh_from_db()
        self.assertIsNone(md.correction_pending_at)

    def test_niente_fatti_niente_segnale(self):
        md = self._round()
        self.assertEqual(self._flag(facts=[]), [])
        md.refresh_from_db()
        self.assertIsNone(md.correction_pending_at)

    def test_una_seconda_rettifica_si_aggiunge_alla_prima(self):
        md = self._round()
        self._flag()
        self._flag(facts=["risultato 1-1 -> 1-2"], moving=[])
        md.refresh_from_db()
        self.assertIn("Sutalo", md.correction_note)
        self.assertIn("risultato 1-1 -> 1-2 — nessuna sfida cambierebbe",
                      md.correction_note)

    def test_un_anteprima_fallita_non_ferma_il_segnale(self):
        md = self._round()
        with mock.patch.object(provider_corrections, "fixtures_that_would_move",
                               side_effect=RuntimeError("boom")), \
             self.assertLogs("vfoot.services.provider_corrections", "ERROR"):
            flagged = provider_corrections.flag_concluded_rounds(self.match, FACTS)
        md.refresh_from_db()
        self.assertIsNotNone(md.correction_pending_at)
        self.assertIsNone(flagged[0]["fixtures_moving"])

    def test_il_ricalcolo_la_cancella(self):
        md = self._round()
        self._flag()
        md.refresh_from_db()
        provider_corrections.clear(md)
        md.refresh_from_db()
        self.assertIsNone(md.correction_pending_at)
        self.assertEqual(md.correction_note, "")

    def test_l_elenco_delle_giornate_la_mostra_all_admin(self):
        md = self._round()
        self._flag()
        client = APIClient()
        client.credentials(
            HTTP_AUTHORIZATION=f"Token {Token.objects.create(user=self.admin).key}")
        r = client.get(f"/api/v1/leagues/{self.league.id}/matchdays")
        self.assertEqual(r.status_code, 200, r.content)
        row = next(x for x in r.json() if x["fantasy_matchday_id"] == md.id)
        self.assertIn("Sutalo", row["correction_pending"]["note"])


class PreviewTests(TestCase):
    """L'anteprima vera, senza finte: una sfida il cui punteggio congelato non e'
    quello che il motore da' oggi risulta fra quelle che si muoverebbero."""

    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2026-2027"),
            name="Serie A 2026-2027")
        user = User.objects.create_user("mario", "m@x.it", "pw")
        self.league = FantasyLeague.objects.create(
            name="Lega", owner=user, mode=FantasyLeague.MODE_CLASSIC,
            reference_season=self.cs)
        m1 = LeagueMembership.objects.create(league=self.league, user=user,
                                             role=LeagueMembership.ROLE_ADMIN)
        m2 = LeagueMembership.objects.create(
            league=self.league, user=User.objects.create_user("luigi", "l@x.it", "pw"))
        self.md = FantasyMatchday.objects.create(
            league=self.league, real_competition_season=self.cs, real_matchday=9,
            status=FantasyMatchday.STATUS_CONCLUDED)
        comp_ = FantasyCompetition.objects.create(league=self.league, name="Campionato")
        self.fx = FantasyFixture.objects.create(
            competition=comp_, fantasy_matchday=self.md, round_no=9,
            home_team=FantasyTeam.objects.create(league=self.league, manager=m1, name="A"),
            away_team=FantasyTeam.objects.create(league=self.league, manager=m2, name="B"),
            status=FantasyFixture.STATUS_FINISHED, home_total=1, away_total=0)

    def test_il_congelato_diverso_da_oggi_si_muove(self):
        from vfoot.services.classic_matchday_scoring import live_scorer, ruleset_for_round
        today = live_scorer(self.league, self.md, ruleset_for_round(self.league, self.md))(self.fx)
        FantasyFixtureDetail.objects.create(
            fixture=self.fx, vfoot_home=today["home_total"] + 3,
            vfoot_away=today["away_total"], payload={})
        (moving,) = provider_corrections.fixtures_that_would_move(self.league, self.md)
        self.assertEqual(moving["fixture_id"], self.fx.id)

    def test_il_congelato_uguale_a_oggi_resta_fermo(self):
        from vfoot.services.classic_matchday_scoring import live_scorer, ruleset_for_round
        today = live_scorer(self.league, self.md, ruleset_for_round(self.league, self.md))(self.fx)
        FantasyFixtureDetail.objects.create(
            fixture=self.fx, vfoot_home=today["home_total"],
            vfoot_away=today["away_total"], payload={})
        self.assertEqual(provider_corrections.fixtures_that_would_move(self.league, self.md), [])


class FactChangesTests(TestCase):
    def test_il_solo_xg_rivisto_non_e_un_fatto(self):
        changes = ["Sutalo (#2): autogol 0 -> 1",
                   f"{live_ingest.REVISION_PREFIX} su 4 tiri (il piu' grosso 0.076)"]
        self.assertEqual(live_ingest.fact_changes(changes), changes[:1])
