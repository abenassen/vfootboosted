"""Andata e ritorno, e cosa vale giocare in casa.

Due cose che si tengono per mano e vanno provate insieme:

* un turno a eliminazione può giocarsi su DUE gare, e quindi su due giornate;
* la lega può assegnare un bonus a chi gioca in casa — ma solo dove giocare in
  casa vuol dire qualcosa.

Il secondo punto è il più facile da sbagliare, ed è per questo che il campo sta
sulla PARTITA e non sulla lega: in un girone di sola andata, o nella tornata
dispari in più di un campionato, chi ospita l'ha deciso il sorteggio. Un bonus
lì non premia niente, sorteggia tre punti.
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
    FantasyTeam,
    LeagueMembership,
)
from vfoot.services.classic_scoring import Ruleset, resolve_fixture, score_team
from vfoot.services.competition_stages import home_advantage_for_leg
from vfoot.services.knockout import BY_GOALS, BY_SCORE, tie_outcomes


def _season(matchdays: int = 38) -> CompetitionSeason:
    comp = Competition.objects.create(external_id="23", name="Serie A")
    cs = CompetitionSeason.objects.create(
        competition=comp, season=Season.objects.create(code="2026-2027"),
        name="Serie A 2026-2027")
    home = TeamSeason.objects.create(
        team=Team.objects.create(external_id="h", name="Home FC"), competition_season=cs)
    away = TeamSeason.objects.create(
        team=Team.objects.create(external_id="a", name="Away FC"), competition_season=cs)
    base = timezone.now() + timedelta(days=1)
    Match.objects.bulk_create([
        Match(competition_season=cs, external_id=f"m{md}", matchday=md,
              home_team=home, away_team=away, kickoff=base + timedelta(days=7 * md))
        for md in range(1, matchdays + 1)
    ])
    return cs


class CampoNeutroTests(TestCase):
    """Quali partite hanno un campo, e quali no."""

    def test_le_tornate_pari_hanno_un_campo_e_la_dispari_in_piu_no(self):
        self.assertEqual([home_advantage_for_leg(l, 1) for l in (1,)], [False])
        self.assertEqual([home_advantage_for_leg(l, 2) for l in (1, 2)], [True, True])
        self.assertEqual([home_advantage_for_leg(l, 3) for l in (1, 2, 3)],
                         [True, True, False])
        self.assertEqual([home_advantage_for_leg(l, 4) for l in (1, 2, 3, 4)],
                         [True] * 4)


class WizardTests(TestCase):
    def setUp(self):
        self.season = _season()
        self.admin = User.objects.create_user("admin", "a@x.it", "x")
        self.client = APIClient()
        self.client.force_authenticate(user=self.admin)
        r = self.client.post("/api/v1/leagues",
                             {"name": "Prova", "team_name": "Alpha",
                              "reference_season_id": self.season.id}, format="json")
        self.league = FantasyLeague.objects.get(id=r.json()["league_id"])
        for i in range(7):
            user = User.objects.create_user(f"m{i}", f"m{i}@x.it", "x")
            m = LeagueMembership.objects.create(league=self.league, user=user, role="manager")
            FantasyTeam.objects.create(league=self.league, manager=m, name=f"Team {i}")
        self.team_ids = list(FantasyTeam.objects.filter(league=self.league)
                             .order_by("id").values_list("id", flat=True))

    def _wizard(self, **payload):
        r = self.client.post(f"/api/v1/leagues/{self.league.id}/competitions/wizard",
                             payload, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        return FantasyCompetition.objects.get(id=r.json()["competition"]["competition_id"])

    # -- campionato --------------------------------------------------------- #

    def test_un_campionato_di_sola_andata_e_tutto_campo_neutro(self):
        comp = self._wizard(name="Solo andata", format="league",
                            team_ids=self.team_ids, legs=1)
        self.assertEqual(FantasyFixture.objects.filter(competition=comp).count(), 28)
        self.assertFalse(FantasyFixture.objects.filter(competition=comp,
                                                       home_advantage=True).exists())

    def test_andata_e_ritorno_danno_il_campo_a_tutti(self):
        comp = self._wizard(name="A/R", format="league", team_ids=self.team_ids, legs=2)
        fx = FantasyFixture.objects.filter(competition=comp)
        self.assertEqual(fx.count(), 56)
        self.assertEqual(fx.filter(home_advantage=True).count(), 56)
        # ...e ognuno ospita esattamente quante volte è ospitato.
        for tid in self.team_ids:
            self.assertEqual(fx.filter(home_team_id=tid).count(),
                             fx.filter(away_team_id=tid).count())

    def test_con_tre_tornate_l_ultima_si_gioca_in_campo_neutro(self):
        """Il caso che il fantacalcio vero conosce bene: tre giri non si
        bilanciano, e allora l'ultimo non vale come campo."""
        comp = self._wizard(name="Tre giri", format="league",
                            team_ids=self.team_ids, legs=3)
        fx = FantasyFixture.objects.filter(competition=comp)
        self.assertEqual(fx.count(), 84)
        self.assertEqual(fx.filter(leg_no=3, home_advantage=True).count(), 0)
        self.assertEqual(fx.filter(leg_no__lt=3, home_advantage=False).count(), 0)

    # -- coppa -------------------------------------------------------------- #

    def test_una_coppa_in_gara_secca_e_campo_neutro(self):
        comp = self._wizard(name="Secca", format="cup", team_ids=self.team_ids[:4])
        self.assertFalse(FantasyFixture.objects.filter(competition=comp,
                                                       home_advantage=True).exists())

    def test_una_coppa_andata_e_ritorno_occupa_due_giornate_per_turno(self):
        comp = self._wizard(name="Coppa A/R", format="cup", team_ids=self.team_ids[:4],
                            knockout_legs=2, start_matchday=1)
        semis = CompetitionStage.objects.get(competition=comp, name="Semifinali")
        self.assertEqual(semis.planned_rounds, 2)
        legs = FantasyFixture.objects.filter(stage=semis).order_by("round_no", "id")
        self.assertEqual(legs.count(), 4, "due sfide, due gare ciascuna")
        self.assertEqual(sorted({f.round_no for f in legs}), [1, 2])
        self.assertTrue(all(f.home_advantage for f in legs))
        # Due turni della competizione = due GIORNATE reali distinte.
        mds = {f.round_no: f.fantasy_matchday.real_matchday for f in legs}
        self.assertNotEqual(mds[1], mds[2])
        # E il ritorno è la stessa sfida a campi invertiti.
        andata = [f for f in legs if f.round_no == 1]
        ritorno = [f for f in legs if f.round_no == 2]
        self.assertEqual({frozenset((f.home_team_id, f.away_team_id)) for f in andata},
                         {frozenset((f.home_team_id, f.away_team_id)) for f in ritorno})
        for a in andata:
            gemella = next(r for r in ritorno
                           if {r.home_team_id, r.away_team_id} == {a.home_team_id, a.away_team_id})
            self.assertEqual(gemella.home_team_id, a.away_team_id)

    def test_la_finale_puo_restare_in_gara_unica(self):
        """Come si giocano quasi tutte le coppe vere."""
        comp = self._wizard(name="Coppa mista", format="cup", team_ids=self.team_ids[:4],
                            knockout_legs=2, final_legs=1, start_matchday=1)
        semis = CompetitionStage.objects.get(competition=comp, name="Semifinali")
        finale = CompetitionStage.objects.get(competition=comp, name="Finale")
        self.assertEqual((semis.planned_rounds, finale.planned_rounds), (2, 1))
        self.assertEqual(finale.round_offset, 2, "la finale viene dopo le due gare")

    def test_l_anteprima_conta_le_giornate_che_la_coppa_occuperà(self):
        """Un'anteprima che promette tre giornate per una cosa che ne prende
        cinque è peggio di nessuna anteprima."""
        def rounds(**extra):
            r = self.client.post(
                f"/api/v1/leagues/{self.league.id}/competitions/wizard/preview",
                {"format": "cup", "team_ids": self.team_ids[:8], **extra}, format="json")
            self.assertEqual(r.status_code, 200, r.content)
            return r.json()["total_rounds"]

        self.assertEqual(rounds(), 3)                                   # quarti, semi, finale
        self.assertEqual(rounds(knockout_legs=2), 6)                    # tutto andata e ritorno
        self.assertEqual(rounds(knockout_legs=2, final_legs=1), 5)      # finale secca

        built = self._wizard(name="Verifica", format="cup", team_ids=self.team_ids[:8],
                             knockout_legs=2, final_legs=1, start_matchday=1)
        spans = {s.name: s.planned_rounds for s in
                 CompetitionStage.objects.filter(competition=built)}
        self.assertEqual(sum(spans.values()), 5, spans)

    def test_a_mano_si_ottiene_lo_stesso_risultato_del_wizard(self):
        """La modalità manuale non è una scorciatoia di serie B: una fase creata
        a mano con due gare deve comportarsi come quella del wizard."""
        comp = self._wizard(name="Contenitore", format="league",
                            team_ids=self.team_ids[:2], legs=1)
        r = self.client.post(
            f"/api/v1/competitions/{comp.id}/stages/create",
            {"name": "Spareggio", "stage_type": "knockout", "order_index": 2,
             "legs": 2, "team_ids": self.team_ids[:2]}, format="json")
        self.assertEqual(r.status_code, 201, r.content)
        stage = CompetitionStage.objects.get(competition=comp, name="Spareggio")
        self.assertEqual(stage.planned_rounds, 2)
        legs = list(FantasyFixture.objects.filter(stage=stage).order_by("round_no"))
        self.assertEqual(len(legs), 2)
        self.assertTrue(all(f.home_advantage for f in legs))
        self.assertEqual(legs[0].home_team_id, legs[1].away_team_id)


class SfidaSuDueGareTests(TestCase):
    """La sfida di andata e ritorno è UNA, e si somma."""

    def setUp(self):
        owner = User.objects.create_user("owner", "o@x.it", "pw")
        self.league = FantasyLeague.objects.create(name="Lega", owner=owner)
        self.teams = []
        for i in range(2):
            user = owner if i == 0 else User.objects.create_user(f"u{i}", f"u{i}@x.it", "pw")
            m = LeagueMembership.objects.create(league=self.league, user=user, role="manager")
            self.teams.append(FantasyTeam.objects.create(league=self.league, manager=m, name=f"T{i}"))
        self.comp = FantasyCompetition.objects.create(
            league=self.league, name="Coppa", format=FantasyCompetition.FORMAT_CUP)
        self.stage = CompetitionStage.objects.create(
            competition=self.comp, name="Finale", legs=2,
            stage_type=CompetitionStage.TYPE_KNOCKOUT, order_index=1)

    def _leg(self, home, away, hg, ag, *, leg, round_no):
        return FantasyFixture.objects.create(
            competition=self.comp, stage=self.stage, round_no=round_no, leg_no=leg,
            home_team=home, away_team=away, home_total=float(hg), away_total=float(ag),
            home_advantage=True, status=FantasyFixture.STATUS_FINISHED)

    def test_le_due_gare_su_turni_diversi_restano_una_sfida_sola(self):
        """Il ritorno sta su un altro turno — è così che finisce su un'altra
        giornata — e il turno quindi non può fare da chiave del raggruppamento."""
        a, b = self.teams
        self._leg(a, b, 0, 1, leg=1, round_no=1)
        self._leg(b, a, 0, 2, leg=2, round_no=2)
        out = tie_outcomes(list(FantasyFixture.objects.filter(stage=self.stage)))
        self.assertEqual(len(out), 1, "una sfida, non due")
        self.assertEqual((out[0].winner_id, out[0].reason), (a.id, BY_GOALS))
        self.assertEqual(out[0].last_round, 2)

    def test_il_premio_legge_la_sfida_intera_e_non_solo_il_ritorno(self):
        """Filtrare le gare all'ultimo turno darebbe il ritorno senza la sua
        andata: la coppa a chi ha vinto una partita invece che il confronto."""
        from vfoot.models import CompetitionPrize
        from vfoot.services.competition_prizes import prize_winner_team_ids

        a, b = self.teams
        self._leg(a, b, 3, 0, leg=1, round_no=1)   # a vince nettamente l'andata
        self._leg(b, a, 1, 0, leg=2, round_no=2)   # b vince il ritorno, ma non basta
        coppa = CompetitionPrize.objects.create(
            competition=self.comp, name="Coppa", source_stage=self.stage,
            condition_type=CompetitionPrize.CONDITION_STAGE_WINNER)
        self.assertEqual(prize_winner_team_ids(coppa), [a.id], "3-1 nel doppio confronto")


class FattoreCampoTests(TestCase):
    """Il bonus: quanto vale, e soprattutto DOVE vale."""

    def _xi(self, voto: float) -> list[dict]:
        roles = ["GK"] + ["DEF"] * 4 + ["MID"] * 4 + ["ATT"] * 2
        return [{"player_id": i, "name": f"P{i}", "lineup_role": r, "role": r,
                 "voto_puro": voto, "fantavoto": voto, "sv": False, "conceded": 0,
                 "entered": False, "entered_for": None, "replaced_by": None}
                for i, r in enumerate(roles, start=1)]

    def _score(self, rs, home_advantage):
        home = score_team(self._xi(6.0), [], rs)
        away = score_team(self._xi(6.0), [], rs)
        return resolve_fixture(home, away, rs, home_advantage)

    def test_senza_bonus_configurato_non_cambia_niente(self):
        rs = Ruleset(defense_enabled=False, home_advantage_bonus=0.0)
        out = self._score(rs, home_advantage=True)
        self.assertEqual(out["home_total"], out["away_total"])

    def test_col_bonus_la_squadra_di_casa_parte_avanti(self):
        rs = Ruleset(defense_enabled=False, home_advantage_bonus=2.0)
        out = self._score(rs, home_advantage=True)
        self.assertEqual(out["home_total"] - out["away_total"], 2.0)
        self.assertEqual(out["home"]["applied"], 2.0)

    def test_in_campo_neutro_il_bonus_non_si_applica_neanche_se_configurato(self):
        """Il punto di tutto il meccanismo: la lega dice QUANTO, la partita dice
        SE. Una gara secca non ha un campo, e chi 'ospita' l'ha deciso il
        sorteggio del tabellone."""
        rs = Ruleset(defense_enabled=False, home_advantage_bonus=2.0)
        out = self._score(rs, home_advantage=False)
        self.assertEqual(out["home_total"], out["away_total"])
        self.assertEqual(out["home"]["applied"], 0.0)

    def test_il_bonus_e_nella_fotografia_delle_regole(self):
        """Se non fosse nello snapshot, ricalcolare una giornata conclusa la
        rifarebbe con regole diverse da quelle con cui è stata chiusa."""
        rs = Ruleset(home_advantage_bonus=1.5)
        self.assertEqual(Ruleset.from_snapshot(rs.to_snapshot()).home_advantage_bonus, 1.5)

    def test_il_bonus_puo_decidere_una_sfida_in_parita(self):
        """E quando lo fa, lo fa attraverso il punteggio — cioè la stessa catena
        che il tabellone usa per mandare avanti qualcuno."""
        owner = User.objects.create_user("o2", "o2@x.it", "pw")
        league = FantasyLeague.objects.create(name="L2", owner=owner, home_advantage_bonus=2.0)
        teams = []
        for i in range(2):
            user = owner if i == 0 else User.objects.create_user(f"z{i}", f"z{i}@x.it", "pw")
            m = LeagueMembership.objects.create(league=league, user=user, role="manager")
            teams.append(FantasyTeam.objects.create(league=league, manager=m, name=f"Z{i}"))
        comp = FantasyCompetition.objects.create(league=league, name="C",
                                                 format=FantasyCompetition.FORMAT_CUP)
        stage = CompetitionStage.objects.create(
            competition=comp, name="Finale", legs=2,
            stage_type=CompetitionStage.TYPE_KNOCKOUT, order_index=1)
        a, b = teams
        from vfoot.models import FantasyFixtureDetail
        for leg, (home, away, hs, as_) in enumerate(
                [(a, b, 70.0, 70.0), (b, a, 70.0, 72.0)], start=1):
            fx = FantasyFixture.objects.create(
                competition=comp, stage=stage, round_no=leg, leg_no=leg,
                home_team=home, away_team=away, home_total=1.0, away_total=1.0,
                home_advantage=True, status=FantasyFixture.STATUS_FINISHED)
            FantasyFixtureDetail.objects.create(fixture=fx, vfoot_home=hs, vfoot_away=as_)
        out = tie_outcomes(list(FantasyFixture.objects.filter(stage=stage)
                                .select_related("detail")))
        self.assertEqual(len(out), 1)
        # gol 2-2; punteggi a = 70 + 72 = 142, b = 70 + 70 = 140.
        self.assertEqual((out[0].winner_id, out[0].reason), (a.id, BY_SCORE))
