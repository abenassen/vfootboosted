"""La sezione dei tiri somma alla riga che la intesta.

Non sommava, e per tre ragioni diverse che si erano accumulate una sull'altra:

* la riga del riassunto è misurata contro il PARI RUOLO, le righe dei tiri contro
  «se quel tiro non ci fosse stato» — due metri, e lo scarto fra i due (quanto
  costa a un attaccante non aver concluso) non compariva da nessuna parte: 0.168
  di mediana, il 96% del buco;
* il leave-one-out non è additivo su una funzione concava, quindi nemmeno fra loro
  i tiri sommavano al proprio effetto congiunto;
* per chi segnava, la riga del tiro-gol portava anche il credito d'impatto, che il
  riassunto mostra già per conto suo — il gol si leggeva due volte.

Questi test fissano l'invariante che le chiude tutte e tre: **somma delle righe +
metro = totale della sezione = la riga del riassunto**. E fissano il motivo per cui
la ripartizione è uno Shapley e non un leave-one-out riscalato, che è la via breve
già misurata e scartata.
"""
from __future__ import annotations

from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Match, MatchAppearance, MatchShot, Player,
    PlayerZoneFeature, Season, Team, TeamSeason,
)
from vfoot.services.classic_pagella import (
    _SHOT_FAMILY, get_role_averages, pagella_for_match, shot_detail,
)
from vfoot.services.classic_rating import DERIVED_FEATURES, TOTAL_WEIGHTS
from vfoot.services.vote_explanation import MERGES


class ShotFamilyContractTests(TestCase):
    """Le due affermazioni su cui la sezione è costruita, dette ad alta voce."""

    def test_the_family_is_the_one_the_summary_merges(self):
        """Se le due liste divergessero, la tabella tornerebbe a non quadrare con
        la riga che la intesta — e nessuno se ne accorgerebbe, perché entrambe
        continuerebbero a sommare a qualcosa."""
        merged = next(keys for keys, *_rest in MERGES if _rest[2] == "conclusioni")
        self.assertEqual(set(_SHOT_FAMILY), set(merged))

    def test_the_family_is_all_totals(self):
        """Il sotto-indice legge i valori direttamente dai totali (v. ``value``),
        e può farlo solo finché nessuna di queste voci è una densità per 90'."""
        self.assertTrue(set(_SHOT_FAMILY) <= set(TOTAL_WEIGHTS) | set(DERIVED_FEATURES))


class ShotSectionAddsUpTests(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=Season.objects.create(code="2025-2026"),
            name="Serie A 2025-2026")
        self.home = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Inter"))
        self.away = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Fiorentina"))
        self.match = Match.objects.create(
            competition_season=self.cs, matchday=1, home_team=self.home,
            away_team=self.away, home_goals=1, away_goals=0,
            status=Match.STATUS_FINISHED)
        self.player = self._player("Attaccante Prolifico")

    def _player(self, name, minutes=90):
        p = Player.objects.create(full_name=name, short_name=name,
                                  classic_role_seed="ATT")
        MatchAppearance.objects.create(
            match=self.match, player=p, side="home", minutes_played=minutes,
            is_starter=True, team_season=self.home)
        PlayerZoneFeature.objects.create(
            match=self.match, player=p, provider="sofascore", feature_key="touches",
            zone_key="Z_0_1", value=40.0, team_side="home")
        return p

    def _shots(self, *specs):
        """Crea i tiri E i totali di zona che li rispecchiano, insieme.

        I due archivi vanno tenuti coerenti a mano perché nella realtà non sempre
        lo sono (3.9% delle righe della 25-26): una fixture incoerente misurerebbe
        quel difetto invece di questo comportamento."""
        n = xg = xgot = on = 0
        for i, (minute, kind, x, xo) in enumerate(specs):
            MatchShot.objects.create(
                match=self.match, player=self.player, team_side="home",
                minute=minute, zone_key="Z_4_1", xg=x, xgot=xo,
                is_goal=kind == "goal", shot_type=kind, situation="regular",
                provider="sofascore", external_id=f"s{i}")
            n += 1
            xg += x
            xgot += xo
            on += 1 if kind in ("goal", "save") else 0
        for feature_key, value in (("shots", float(n)), ("xg_shots", xg),
                                   ("xg_on_target", xgot),
                                   ("shots_on_target", float(on))):
            if value:
                PlayerZoneFeature.objects.create(
                    match=self.match, player=self.player, provider="sofascore",
                    feature_key=feature_key, zone_key="Z_4_1", value=value,
                    team_side="home")

    def _summary_line(self):
        """La riga «conclusioni» del riassunto, quella scritta sopra la tabella."""
        pag = pagella_for_match(self.match, ledger=True)
        line = [l for side in ("home", "away") for grp in ("starters", "bench")
                for l in pag[side][grp] if l["player_id"] == self.player.id][0]
        why = line["explanation"]
        return next(c["points"] for c in why["contributions"]
                    if c.get("family") == "conclusioni")

    # -- l'invariante ------------------------------------------------------
    def test_rows_plus_baseline_make_the_section_total(self):
        self._shots((1, "goal", 0.32, 0.69), (4, "save", 0.14, 0.28),
                    (19, "miss", 0.15, 0.0), (90, "save", 0.10, 0.56))
        d = shot_detail(self.match, self.player.id)
        self.assertAlmostEqual(sum(s["points"] for s in d["shots"]) + d["baseline"],
                               d["total"], places=2)

    def test_the_section_total_is_the_summary_line(self):
        """Il totale della sezione È il numero scritto sopra, non un suo parente."""
        self._shots((1, "goal", 0.32, 0.69), (4, "save", 0.14, 0.28),
                    (19, "miss", 0.15, 0.0))
        d = shot_detail(self.match, self.player.id)
        self.assertAlmostEqual(d["total"], self._summary_line(), places=2)

    def test_it_holds_for_a_single_shot_too(self):
        """Con un tiro solo Shapley e leave-one-out coincidono, ma il metro no:
        è il caso in cui la tabella sembrava contraddire la riga (Thuram)."""
        self._shots((59, "miss", 0.054, 0.0))
        d = shot_detail(self.match, self.player.id)
        self.assertEqual(len(d["shots"]), 1)
        self.assertAlmostEqual(d["shots"][0]["points"] + d["baseline"], d["total"],
                               places=2)
        # il tiro aggiunge, la riga toglie: i due segni convivono e non si
        # contraddicono, perché il metro spiega la differenza
        self.assertGreater(d["shots"][0]["points"], 0.0)
        self.assertLess(d["total"], 0.0)

    # -- il metro ----------------------------------------------------------
    def test_the_baseline_is_the_role_yardstick(self):
        """Non è un residuo: è −(media di ruolo del blocco tiro), in punti di voto,
        e si può ricalcolare da fuori."""
        self._shots((10, "miss", 0.10, 0.0))
        d = shot_detail(self.match, self.player.id)
        mean = get_role_averages(self.cs.id).get("ATT", {})
        expected_sign = -sum(mean.get(k, 0.0) for k in _SHOT_FAMILY)
        self.assertLess(d["baseline"], 0.0)
        self.assertLess(expected_sign, 0.0)

    def test_a_player_who_shot_less_than_his_peers_has_a_negative_line(self):
        """Il caso che rendeva illeggibile la tabella: riga negativa, tiro positivo."""
        self._shots((30, "miss", 0.04, 0.0))
        d = shot_detail(self.match, self.player.id)
        self.assertLess(d["total"], 0.0)
        self.assertLess(d["baseline"], d["total"])   # il metro è il pezzo grosso

    # -- perché Shapley e non leave-one-out --------------------------------
    def test_shapley_charges_a_wasteful_shot_that_loo_let_through(self):
        """Un tiro fuori da 0.15 di xG è sopra il pareggio del modello: TOGLIE.

        Il leave-one-out lo valutava solo in cima alla curva, dove il margine è
        schiacciato, e lo dava per quasi gratis (+0.004 su Esposito). Preso in
        media su tutti gli ordini il segno si raddrizza."""
        self._shots((1, "goal", 0.32, 0.69), (4, "save", 0.14, 0.28),
                    (19, "miss", 0.15, 0.0), (90, "save", 0.10, 0.56))
        rows = {s["minute"]: s for s in shot_detail(self.match, self.player.id)["shots"]}
        self.assertLess(rows[19]["points"], 0.0)
        self.assertGreater(rows[1]["points"], 0.0)

    def test_identical_shots_get_identical_credit(self):
        """Simmetria: due tiri uguali non possono valere diverso per l'ordine in
        cui li abbiamo elencati. È la proprietà che il leave-one-out ha per caso e
        lo Shapley per costruzione."""
        self._shots((20, "save", 0.20, 0.40), (70, "save", 0.20, 0.40))
        rows = shot_detail(self.match, self.player.id)["shots"]
        self.assertAlmostEqual(rows[0]["points"], rows[1]["points"], places=3)

    def test_the_goal_credit_is_not_in_the_shot_row(self):
        """Il gol vale, sulla riga del tiro, il MERITO DELLA CONCLUSIONE e basta.

        Il credito d'impatto (``goal_impact``) vive FUORI dall'indice e ha già una
        riga sua nel riassunto: sommarlo anche qui lo faceva leggere due volte —
        su Koné +0.57 nel riassunto e +1.44 sulla mappa. La prova non è la taglia
        del numero (dipende da quanto era ben calciato il tiro) ma che la sezione
        continui a quadrare con la riga delle CONCLUSIONI: se il credito del gol
        fosse dentro, il totale sfonderebbe quella riga di tutto il suo valore."""
        self._shots((50, "goal", 0.30, 0.90))
        d = shot_detail(self.match, self.player.id)
        self.assertAlmostEqual(sum(s["points"] for s in d["shots"]) + d["baseline"],
                               d["total"], places=2)
        # La riga del riassunto porta DUE DECIMALI, il totale della sezione no:
        # il confronto non puo' essere piu' stretto di mezzo passo di
        # arrotondamento, e con ``places=2`` falliva sui valori che cadono esatti
        # sul bordo (1.055 contro 1.06). La proprieta' difesa e' che la sezione sia
        # QUELLA riga, non che i due numeri abbiano la stessa rappresentazione.
        self.assertAlmostEqual(d["total"], self._summary_line(), delta=0.005 + 1e-9)
