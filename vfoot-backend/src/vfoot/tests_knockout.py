"""Chi passa il turno quando finisce in parità.

Prima di questa regola una sfida pari non aveva vincitore: il turno successivo
non trovava un campo, non veniva sorteggiato, e la competizione restava aperta
per sempre. Le prove qui sotto sono la catena — gol, poi somma dei punteggi, poi
fattore campo — e soprattutto l'invariante che la rende sensata: il tabellone e
l'albo d'oro devono dire lo stesso nome.
"""
from __future__ import annotations

from django.contrib.auth.models import User
from django.test import TestCase

from vfoot.models import (
    CompetitionPrize,
    CompetitionStage,
    CompetitionStageParticipant,
    CompetitionStageRule,
    FantasyCompetition,
    FantasyFixture,
    FantasyFixtureDetail,
    FantasyLeague,
    FantasyTeam,
    LeagueMembership,
)
from vfoot.services.competition_prizes import prize_winner_team_ids
from vfoot.services.competition_stages import resolve_stage
from vfoot.services.knockout import BY_GOALS, BY_HOME, BY_SCORE, tie_outcomes


class KnockoutTieTests(TestCase):
    def setUp(self):
        owner = User.objects.create_user("owner", "o@x.it", "pw")
        self.league = FantasyLeague.objects.create(name="Lega", owner=owner)
        self.teams = []
        for i in range(4):
            user = owner if i == 0 else User.objects.create_user(f"u{i}", f"u{i}@x.it", "pw")
            m = LeagueMembership.objects.create(league=self.league, user=user, role="manager")
            self.teams.append(FantasyTeam.objects.create(league=self.league, manager=m, name=f"T{i}"))
        self.comp = FantasyCompetition.objects.create(
            league=self.league, name="Coppa", format=FantasyCompetition.FORMAT_CUP,
            competition_type=FantasyCompetition.TYPE_KNOCKOUT)
        self.stage = CompetitionStage.objects.create(
            competition=self.comp, name="Finale",
            stage_type=CompetitionStage.TYPE_KNOCKOUT, order_index=1)

    def _leg(self, home, away, hg, ag, *, leg=1, round_no=1, scores=None):
        fx = FantasyFixture.objects.create(
            competition=self.comp, stage=self.stage, round_no=round_no, leg_no=leg,
            home_team=home, away_team=away, home_total=float(hg), away_total=float(ag),
            status=FantasyFixture.STATUS_FINISHED)
        if scores is not None:
            FantasyFixtureDetail.objects.create(
                fixture=fx, vfoot_home=scores[0], vfoot_away=scores[1])
        return fx

    def _tie(self):
        fixtures = list(FantasyFixture.objects.filter(stage=self.stage).select_related("detail"))
        out = tie_outcomes(fixtures)
        self.assertEqual(len(out), 1, "una sola sfida")
        return out[0]

    # -- la catena --------------------------------------------------------- #

    def test_i_gol_decidono_quando_dicono_qualcosa(self):
        a, b = self.teams[0], self.teams[1]
        self._leg(a, b, 2, 1, scores=(60.0, 99.0))
        t = self._tie()
        self.assertEqual((t.winner_id, t.loser_id, t.reason), (a.id, b.id, BY_GOALS))

    def test_in_parita_passa_chi_ha_il_punteggio_piu_alto(self):
        """1-1 non vuol dire "hanno giocato uguale": 78.5 contro 71 è una
        differenza che i gol non vedono e il punteggio sì."""
        a, b = self.teams[0], self.teams[1]
        self._leg(a, b, 1, 1, scores=(71.0, 78.5))
        t = self._tie()
        self.assertEqual((t.winner_id, t.loser_id, t.reason), (b.id, a.id, BY_SCORE))

    def test_senza_tabellino_e_senza_gol_passa_chi_gioca_in_casa(self):
        """Una lega aura segna dal risultato reale e non ha i fantavoto: il
        secondo criterio non ha nulla da leggere. L'ultima spiaggia esiste perché
        un tabellone bloccato è peggio di un criterio discutibile."""
        a, b = self.teams[0], self.teams[1]
        self._leg(a, b, 1, 1)
        t = self._tie()
        self.assertEqual((t.winner_id, t.loser_id, t.reason), (a.id, b.id, BY_HOME))

    # -- andata e ritorno --------------------------------------------------- #

    def test_i_gol_si_sommano_sulle_due_gare(self):
        """Perde 0-2 in casa e vince 3-0 fuori: passa lui, 3-2."""
        a, b = self.teams[0], self.teams[1]
        self._leg(a, b, 0, 2, leg=1)
        self._leg(b, a, 0, 3, leg=2)
        t = self._tie()
        self.assertEqual((t.winner_id, t.reason), (a.id, BY_GOALS))

    def test_col_totale_dei_gol_pari_si_sommano_i_punteggi_delle_due_gare(self):
        a, b = self.teams[0], self.teams[1]
        self._leg(a, b, 1, 2, leg=1, scores=(70.0, 74.0))
        self._leg(b, a, 0, 1, leg=2, scores=(66.0, 80.0))
        # gol 2-2; punteggi: a = 70 + 80 = 150, b = 74 + 66 = 140
        t = self._tie()
        self.assertEqual((t.winner_id, t.reason), (a.id, BY_SCORE))

    def test_il_fattore_campo_e_quello_del_ritorno(self):
        a, b = self.teams[0], self.teams[1]
        self._leg(a, b, 1, 1, leg=1, scores=(70.0, 70.0))
        self._leg(b, a, 2, 2, leg=2, scores=(70.0, 70.0))
        t = self._tie()
        self.assertEqual((t.winner_id, t.reason), (b.id, BY_HOME),
                         "in casa nel ritorno c'è b, non a")

    def test_due_turni_diversi_restano_due_sfide(self):
        """Il raggruppamento è per TURNO e coppia: due gare fra le stesse squadre
        in turni diversi non si sommano fra loro."""
        a, b = self.teams[0], self.teams[1]
        self._leg(a, b, 1, 0, round_no=1)
        self._leg(a, b, 0, 1, round_no=2)
        fixtures = list(FantasyFixture.objects.filter(stage=self.stage).select_related("detail"))
        out = tie_outcomes(fixtures)
        self.assertEqual([t.winner_id for t in out], [a.id, b.id])

    # -- l'invariante ------------------------------------------------------- #

    def test_il_tabellone_e_l_albo_doro_dicono_lo_stesso_nome(self):
        """Il motivo per cui la regola sta in un modulo solo.

        Chi passa il turno e chi vince il premio sono due domande fatte da due
        pezzi di codice diversi; se rispondessero in modo diverso, il tabellone
        manderebbe avanti una squadra e la coppa la alzerebbe un'altra.
        """
        a, b = self.teams[0], self.teams[1]
        self._leg(a, b, 1, 1, scores=(70.0, 82.0))
        avanti = CompetitionStage.objects.create(
            competition=self.comp, name="Turno dopo",
            stage_type=CompetitionStage.TYPE_KNOCKOUT, order_index=2)
        CompetitionStageRule.objects.create(
            target_stage=avanti, source_stage=self.stage,
            mode=CompetitionStageRule.MODE_WINNERS)
        resolve_stage(avanti, seed=1)
        qualificata = list(CompetitionStageParticipant.objects
                           .filter(stage=avanti).values_list("team_id", flat=True))

        coppa = CompetitionPrize.objects.create(
            competition=self.comp, name="Coppa",
            condition_type=CompetitionPrize.CONDITION_STAGE_WINNER, source_stage=self.stage)
        self.assertEqual(qualificata, [b.id])
        self.assertEqual(prize_winner_team_ids(coppa), qualificata)

    def test_una_semifinale_pari_non_blocca_piu_la_finale(self):
        """Il guasto vero: la fase successiva si sorteggia solo quando la sua
        regola produce un campo, e una sfida senza vincitore non ne produceva."""
        semis = self.stage
        semis.name = "Semifinali"
        semis.save(update_fields=["name"])
        a, b, c, d = self.teams
        self._leg(a, b, 1, 1, scores=(75.0, 70.0))
        self._leg(c, d, 2, 2, scores=(68.0, 90.0))
        finale = CompetitionStage.objects.create(
            competition=self.comp, name="Finale vera",
            stage_type=CompetitionStage.TYPE_KNOCKOUT, order_index=2)
        CompetitionStageRule.objects.create(
            target_stage=finale, source_stage=semis, mode=CompetitionStageRule.MODE_WINNERS)

        result = resolve_stage(finale, seed=7)
        self.assertEqual(result["resolved_rule_participants"], 2)
        self.assertEqual(result["fixtures_created"], 1, "la finale è stata sorteggiata")
        self.assertEqual(
            set(CompetitionStageParticipant.objects.filter(stage=finale)
                .values_list("team_id", flat=True)),
            {a.id, d.id})
