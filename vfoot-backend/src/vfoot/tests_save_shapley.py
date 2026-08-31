"""La mappa delle parate somma alla riga che la intesta.

È la mappa dei tiri (v. ``tests_shot_shapley``) letta dalla porta, e regge sugli
stessi tre pilastri: la riga del riassunto misura contro il PARI RUOLO mentre le
righe della tabella misurano contro «se quel tiro non ci fosse stato», lo scarto
fra i due è il METRO e ha un nome, e la ripartizione è uno Shapley perché il
conteggio delle parate passa per la compressione e per il credito d'assenza.

Qui però ci sono due cose che i tiri non hanno, e sono quelle che questi test
difendono davvero:

* IL GOL SUBITO vale −(1 − xGOT). Uno su un tiro imparabile quasi non costa, uno
  su un tiro parabile costa quasi un gol intero: è la cosa che questo modello sa
  dire meglio di una pagella, e prima non si vedeva da nessuna parte.
* L'AUTOGOL DI UN COMPAGNO non è un gol intero: al portiere viene restituita la
  difficoltà del tiro (v. ``_merge_own_goal_relief``), e la mappa deve contarlo con
  quello o la sezione perde 0.834 esatti dentro il metro.
"""
from __future__ import annotations

from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, MatchShot, Player,
    PlayerZoneFeature, Season, Team, TeamSeason,
)
from vfoot.services.classic_pagella import (
    _SAVE_FAMILY, pagella_for_match, save_detail,
)
from vfoot.services.classic_rating import (
    GK_PER90_WEIGHTS, GK_TOTAL_WEIGHTS, OWN_GOAL_KEEPER_XGOT_DEFAULT,
)
from vfoot.services.vote_explanation import MERGES


class SaveFamilyContractTests(TestCase):
    def test_the_family_is_the_one_the_summary_merges(self):
        """Se le due liste divergessero la tabella tornerebbe a non quadrare con la
        riga che la intesta, e nessuno se ne accorgerebbe: entrambe continuerebbero
        a sommare a qualcosa."""
        merged = next(keys for keys, *rest in MERGES if rest[2] == "parate")
        self.assertEqual(set(_SAVE_FAMILY), set(merged))

    def test_the_family_is_mixed_totals_and_per_ninety(self):
        """La ragione per cui ``value`` passa da ``raw_feature_values`` invece di
        leggere i totali nudi come fa la mappa dei tiri. Se un giorno le due voci
        finissero sullo stesso piano, la scorciatoia tornerebbe lecita — ma finché
        sono miste, toglierla sbaglia solo su chi NON gioca i novanta, cioè quasi
        mai, cioè nel modo peggiore."""
        self.assertIn("gk_goals_prevented", GK_TOTAL_WEIGHTS)
        self.assertIn("gk_saves", GK_PER90_WEIGHTS)


class SaveSectionAddsUpTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2025-2026"),
            name="Serie A 2025-2026")
        self.home = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Verona"))
        self.away = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Inter"))
        self.match = Match.objects.create(
            competition_season=self.cs, matchday=1, home_team=self.home,
            away_team=self.away, home_goals=0, away_goals=0,
            status=Match.STATUS_FINISHED)
        self.striker = Player.objects.create(full_name="Attaccante Avversario",
                                             short_name="Avversario",
                                             classic_role_seed="ATT")
        MatchAppearance.objects.create(
            match=self.match, player=self.striker, side="away", minutes_played=90,
            is_starter=True, team_season=self.away)

    def _keeper(self, minutes=90):
        p = Player.objects.create(full_name="Portiere Titolare", short_name="Portiere",
                                  is_goalkeeper=True, classic_role_seed="POR")
        MatchAppearance.objects.create(
            match=self.match, player=p, side="home", minutes_played=minutes,
            is_starter=True, team_season=self.home)
        PlayerZoneFeature.objects.create(
            match=self.match, player=p, provider="sofascore", feature_key="touches",
            zone_key="Z_0_1", value=25.0, team_side="home")
        self.keeper = p
        return p

    def _faced(self, *specs, scorer=None):
        """I tiri subiti E i totali di zona che li rispecchiano, insieme.

        Vanno tenuti coerenti a mano perché nella realtà non sempre lo sono (il 5%
        circa delle presenze da portiere): una fixture incoerente misurerebbe quel
        difetto invece di questo comportamento.
        """
        saves = 0.0
        gp = 0.0
        for i, (minute, kind, xgot) in enumerate(specs):
            shooter = scorer if (kind == "own" and scorer is not None) else self.striker
            MatchShot.objects.create(
                match=self.match, player=shooter, team_side="away", minute=minute,
                zone_key="Z_4_1", xg=0.1, xgot=xgot, is_goal=kind in ("goal", "own"),
                shot_type="goal" if kind in ("goal", "own") else kind,
                situation="regular", provider="sofascore", external_id=f"f{i}")
            if kind == "save":
                saves += 1
                gp += xgot
            elif kind == "goal":
                gp += xgot - 1.0
            elif kind == "own":
                # il provider lo conta fra i gol subiti; il credito lo rimette a
                # posto dentro ``_per_match_player_totals``, non qui
                gp -= 1.0
        for key, value in (("gk_saves", saves), ("gk_goals_prevented", gp)):
            if value:
                PlayerZoneFeature.objects.create(
                    match=self.match, player=self.keeper, provider="sofascore",
                    feature_key=key, zone_key="Z_0_1", value=value, team_side="home")

    def _summary_line(self):
        """La voce «parate» del pannello. Deve ESSERCI: sotto il 5.5 il pannello
        ripiega i positivi deboli dentro «altro» (elogio fiacco per una brutta
        partita), quindi gli scenari qui sotto vanno tenuti sopra quella soglia —
        altrimenti si finisce a confrontare il totale con un «resto» che contiene
        anche altro, e l'invariante non direbbe piu' niente."""
        pag = pagella_for_match(self.match, ledger=True)
        line = [l for side in ("home", "away") for grp in ("starters", "bench")
                for l in pag[side][grp] if l["player_id"] == self.keeper.id][0]
        return next(c["points"] for c in line["explanation"]["contributions"]
                    if c.get("family") == "parate")

    # -- l'invariante ------------------------------------------------------
    def test_rows_plus_baseline_make_the_section_total(self):
        self._keeper()
        self._faced((12, "save", 0.64), (40, "save", 0.05), (77, "save", 0.17))
        d = save_detail(self.match, self.keeper.id)
        self.assertEqual(len(d["saves"]), 3)
        self.assertAlmostEqual(sum(s["points"] for s in d["saves"]) + d["baseline"],
                               d["total"], places=2)

    def test_the_section_total_is_the_summary_line(self):
        self._keeper()
        self._faced((12, "save", 0.64), (40, "save", 0.05), (77, "save", 0.17))
        # La riga del riassunto è arrotondata al CENTESIMO e la sezione al
        # millesimo (v. ``entry`` in vote_explanation): l'uguaglianza è esatta fino
        # a lì, e `places=2` la sbaglia su un totale che cade sul mezzo centesimo.
        self.assertAlmostEqual(save_detail(self.match, self.keeper.id)["total"],
                               self._summary_line(), delta=0.0051)

    def test_it_still_adds_up_for_a_keeper_who_did_not_play_ninety(self):
        """``gk_saves`` è una densità per 90': con la scorciatoia che legge i totali
        nudi questa sezione sbagliava di un terzo, e su chi gioca i novanta — cioè
        quasi tutti — non sbagliava affatto."""
        self._keeper(minutes=60)
        self._faced((12, "save", 0.64), (40, "save", 0.05))
        d = save_detail(self.match, self.keeper.id)
        self.assertAlmostEqual(sum(s["points"] for s in d["saves"]) + d["baseline"],
                               d["total"], places=2)
        self.assertAlmostEqual(d["total"], self._summary_line(), delta=0.0051)

    # -- quello che la mappa dice e la riga non diceva ----------------------
    def _goal_worth(self, xgot, matchday):
        """Quanto costa un gol subito su un tiro di quella difficoltà.

        Una PARTITA NUOVA ogni volta, e non è pignoleria da fixture: il valore di un
        tiro dipende da quelli che ha accanto (è uno Shapley), quindi due gol messi
        nella stessa partita non si possono confrontare fra loro.
        """
        self.match = Match.objects.create(
            competition_season=self.cs, matchday=matchday, home_team=self.home,
            away_team=self.away, home_goals=0, away_goals=1,
            status=Match.STATUS_FINISHED)
        self.striker = Player.objects.create(
            full_name=f"Attaccante {matchday}", short_name=f"Att{matchday}",
            classic_role_seed="ATT")
        MatchAppearance.objects.create(
            match=self.match, player=self.striker, side="away", minutes_played=90,
            is_starter=True, team_season=self.away)
        self.keeper = None
        p = Player.objects.create(full_name=f"Portiere {matchday}",
                                  short_name=f"Por{matchday}", is_goalkeeper=True,
                                  classic_role_seed="POR")
        MatchAppearance.objects.create(
            match=self.match, player=p, side="home", minutes_played=90,
            is_starter=True, team_season=self.home)
        PlayerZoneFeature.objects.create(
            match=self.match, player=p, provider="sofascore", feature_key="touches",
            zone_key="Z_0_1", value=25.0, team_side="home")
        self.keeper = p
        self._faced((12, "save", 0.30), (55, "goal", xgot))
        rows = {s["minute"]: s for s in save_detail(self.match, self.keeper.id)["saves"]}
        self.assertEqual(rows[55]["outcome"], "gol subito")
        return rows[55]["points"]

    def test_a_goal_costs_the_keeper_what_it_was_worth_saving(self):
        """Il gol vale −(1 − xGOT): su un tiro imparabile quasi non costa, su uno
        parabile costa quasi un gol intero. È la cosa che questo modello sa dire e
        una pagella no, e dalla riga «gol evitati» da sola non si vedeva.

        I due casi si confrontano fra loro invece che contro una soglia: quanto
        valga un decimo di gol in punti di voto dipende dalla taratura, il fatto che
        il gol imparabile costi MOLTO MENO no."""
        imparabile = self._goal_worth(0.97, matchday=2)
        parabile = self._goal_worth(0.10, matchday=3)
        self.assertGreater(imparabile, -0.1)
        self.assertLess(parabile, imparabile - 0.2)

    def test_a_teammates_own_goal_is_counted_at_its_difficulty(self):
        """Senza questo, la sezione perdeva esattamente OWN_GOAL_KEEPER_XGOT_DEFAULT
        e lo nascondeva nel metro — che è come il difetto si è presentato."""
        scorer = Player.objects.create(full_name="Difensore Sfortunato",
                                       short_name="Sfortunato", classic_role_seed="DIF")
        MatchAppearance.objects.create(
            match=self.match, player=scorer, side="home", minutes_played=90,
            is_starter=True, team_season=self.home)
        PlayerZoneFeature.objects.create(
            match=self.match, player=scorer, provider="sofascore",
            feature_key="touches", zone_key="Z_0_1", value=40.0, team_side="home")
        self._keeper()
        # Due parate e non una: senza lo smorzamento sull'evidenza (tolto il
        # 31/08/2026) una sola parata piu' un autogol porta il voto sotto il 5.5,
        # e li' il pannello ripiega i positivi in «altro» — v. _summary_line.
        self._faced((12, "save", 0.30), (33, "save", 0.55), (55, "own", 0.0),
                    scorer=scorer)
        d = save_detail(self.match, self.keeper.id)
        rows = {s["minute"]: s for s in d["saves"]}
        self.assertEqual(rows[55]["outcome"], "autogol di un compagno")
        self.assertAlmostEqual(rows[55]["xgot"], OWN_GOAL_KEEPER_XGOT_DEFAULT, places=3)
        self.assertAlmostEqual(sum(s["points"] for s in d["saves"]) + d["baseline"],
                               d["total"], places=2)
        self.assertAlmostEqual(d["total"], self._summary_line(), delta=0.0051)

    # -- che cosa NON è nella mappa ----------------------------------------
    def test_shots_that_never_reached_the_goal_are_not_his(self):
        """Quindici conclusioni alte sono comunque un pomeriggio tranquillo: il
        canale del portiere legge quello che è arrivato in porta (v. gk_evidence)."""
        self._keeper()
        self._faced((12, "save", 0.30))
        for i, minute in enumerate((20, 33, 61)):
            MatchShot.objects.create(
                match=self.match, player=self.striker, team_side="away", minute=minute,
                zone_key="Z_4_1", xg=0.2, xgot=0.0, is_goal=False, shot_type="miss",
                situation="regular", provider="sofascore", external_id=f"off{i}")
        d = save_detail(self.match, self.keeper.id)
        self.assertEqual([s["minute"] for s in d["saves"]], [12])

    def test_an_outfielder_has_no_save_map(self):
        self._keeper()
        self._faced((12, "save", 0.30))
        self.assertEqual(save_detail(self.match, self.striker.id)["saves"], [])
