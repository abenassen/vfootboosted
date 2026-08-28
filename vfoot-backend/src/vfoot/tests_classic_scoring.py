"""Unit tests for the shared classic scoring engine (services/classic_scoring.py).

Pure computation, no DB — SimpleTestCase. Fantavoto is set equal to voto puro in
these fixtures (no bonus/malus) so the expected totals are easy to read.
"""

from django.test import SimpleTestCase

from vfoot.services.classic_scoring import (
    Ruleset,
    score_team,
    resolve_fixture,
)
from vfoot.services.defense_bonus import defense_bonus_value
from vfoot.services.scoring_engine import fantavote_to_goals


class DefenseBandsTest(SimpleTestCase):
    """+1 every 0.25 above 6.00, linear and uncapped (inclusive upper bound)."""

    def test_bands(self):
        cases = {
            6.00: 0.0, 6.10: 1.0, 6.25: 1.0, 6.26: 2.0, 6.50: 2.0,
            6.75: 3.0, 7.00: 4.0, 7.25: 5.0, 7.50: 6.0, 8.00: 8.0,
        }
        for avg, expected in cases.items():
            self.assertEqual(defense_bonus_value(avg), expected, f"avg={avg}")


def line(pid, role, vp, sv=False, conceded=0):
    """A per-player line; fantavoto == voto_puro (no bonus/malus) for readable sums."""
    return {
        "player_id": pid,
        "name": f"P{pid}",
        "lineup_role": role,           # GK/DEF/MID/ATT
        "voto_puro": None if sv else float(vp),
        "fantavoto": None if sv else float(vp),
        "sv": sv,
        "conceded": conceded,
    }


def legal_xi(vp=6.0, gk_conceded=0, n_def=4, n_mid=4, n_att=2):
    """A legal starting XI (1 GK + n_def + n_mid + n_att = 11) all rated `vp`."""
    assert 1 + n_def + n_mid + n_att == 11
    xi = [line(1, "GK", vp, conceded=gk_conceded)]
    pid = 2
    for _ in range(n_def):
        xi.append(line(pid, "DEF", vp)); pid += 1
    for _ in range(n_mid):
        xi.append(line(pid, "MID", vp)); pid += 1
    for _ in range(n_att):
        xi.append(line(pid, "ATT", vp)); pid += 1
    return xi


class ClassicScoringTest(SimpleTestCase):
    def test_base_total_is_sum_of_fantavoti(self):
        rs = Ruleset(defense_enabled=False)
        team = score_team(legal_xi(6.0), [], rs)
        self.assertEqual(team["base_total"], 66.0)  # 11 x 6.0

    def test_sv_starter_is_substituted_by_bench(self):
        rs = Ruleset(defense_enabled=False, max_substitutions=5)
        starters = legal_xi(6.0)
        # Make one MID starter s.v. (pid 6 is a MID: GK=1, DEF=2..5, MID=6..9).
        starters[5] = line(6, "MID", 0, sv=True)
        bench = [line(20, "MID", 7.0)]  # priority bench MID with a vote
        team = score_team(starters, bench, rs)
        # 10 rated starters x6 (=60) + bench 7.0 = 67
        self.assertEqual(team["base_total"], 67.0)
        self.assertEqual(len(team["substitutions"]), 1)
        self.assertEqual(team["unresolved_sv"], [])

    def test_unresolved_sv_is_excluded_not_zero_not_six(self):
        rs = Ruleset(defense_enabled=False, max_substitutions=5)
        starters = legal_xi(6.0)
        starters[5] = line(6, "MID", 0, sv=True)  # s.v. MID
        team = score_team(starters, [], rs)  # no bench -> cannot substitute
        # The s.v. contributes NOTHING: 10 rated x6 = 60 (not 66, not 54).
        self.assertEqual(team["base_total"], 60.0)
        self.assertEqual(team["unresolved_sv"], [6])

    def test_max_substitutions_cap(self):
        rs = Ruleset(defense_enabled=False, max_substitutions=1)
        starters = legal_xi(6.0)
        starters[5] = line(6, "MID", 0, sv=True)
        starters[6] = line(7, "MID", 0, sv=True)  # two s.v. MIDs
        bench = [line(20, "MID", 7.0), line(21, "MID", 7.0)]
        team = score_team(starters, bench, rs)
        # cap=1: one sub applied (+7), the other s.v. excluded. 9x6=54 +7 = 61.
        self.assertEqual(team["base_total"], 61.0)
        self.assertEqual(len(team["substitutions"]), 1)
        self.assertEqual(team["unresolved_sv"], [7])

    def test_defense_bonus_add_own(self):
        rs = Ruleset(defense_enabled=True, defense_mode="add_own")
        home = score_team(legal_xi(6.5), [], rs)   # 4 DEF starters -> eligible
        away = score_team(legal_xi(6.5, n_def=3, n_mid=5), [], rs)  # 3 DEF -> not eligible
        out = resolve_fixture(home, away, rs)
        # avg = (6.5*3 + 6.5)/4 = 6.5 -> band +2. Home 71.5 + 2 = 73.5.
        self.assertTrue(home["defense"]["eligible"])
        self.assertEqual(home["defense"]["bonus"], 2.0)
        self.assertEqual(home["total"], 73.5)
        self.assertFalse(away["defense"]["eligible"])
        self.assertEqual(away["total"], 71.5)
        self.assertEqual(out["home_goals"], fantavote_to_goals(73.5))

    def test_defense_bonus_subtract_opponent(self):
        rs = Ruleset(defense_enabled=True, defense_mode="subtract_opponent")
        home = score_team(legal_xi(6.5), [], rs)                    # eligible +2
        away = score_team(legal_xi(6.5, n_def=3, n_mid=5), [], rs)  # not eligible
        resolve_fixture(home, away, rs)
        # Home's +2 is taken OFF the opponent: away 71.5 - 2 = 69.5; home unchanged.
        self.assertEqual(home["total"], 71.5)
        self.assertEqual(away["total"], 69.5)
        self.assertEqual(away["applied"], -2.0)

    def test_defense_gate_effective_counts_the_lineup_that_played(self):
        """End-to-end through score_team: the gate is a Ruleset knob, and what it
        moves is eligibility only — the average is the effective XI's either way."""
        starters = legal_xi(6.5, n_def=3, n_mid=5)      # 3-5-2 schierato
        starters[4] = line(5, "MID", 0, sv=True)        # un centrocampista s.v.
        bench = [line(20, "DEF", 6.5)]                  # entra un difensore: 4-4-2
        for gate, eligible in (("starters", False), ("effective", True)):
            team = score_team([dict(l) for l in starters], [dict(l) for l in bench],
                              Ruleset(defense_enabled=True, defense_gate=gate))
            self.assertEqual(team["defense"]["eligible"], eligible, gate)
            self.assertEqual(len(team["substitutions"]), 1, gate)
        # E il valore, quando scatta, e' quello dei difensori che hanno giocato.
        team = score_team([dict(l) for l in starters], [dict(l) for l in bench],
                          Ruleset(defense_enabled=True, defense_gate="effective"))
        self.assertAlmostEqual(team["defense"]["avg"], 6.5)
        self.assertEqual(team["defense"]["bonus"], 2.0)

    def test_defense_gate_is_read_from_the_league(self):
        from types import SimpleNamespace
        league = SimpleNamespace(max_substitutions=5, defense_bonus_enabled=True,
                                 defense_bonus_mode="add_own",
                                 defense_bonus_gate="effective")
        self.assertEqual(Ruleset.from_league(league).defense_gate, "effective")
        # Una lega piu' vecchia del campo (o un doppio di prova che non ce l'ha)
        # gioca la regola storica, non un cancello vuoto.
        del league.defense_bonus_gate
        self.assertEqual(Ruleset.from_league(league).defense_gate, "starters")

    def test_defense_gate_survives_the_ruleset_snapshot(self):
        """A concluded matchday is re-scored from its snapshot: the gate has to be
        in there, and a snapshot written before it existed must keep meaning
        'the XI as sent'."""
        rs = Ruleset(defense_gate="effective")
        self.assertEqual(Ruleset.from_snapshot(rs.to_snapshot()).defense_gate, "effective")
        self.assertEqual(Ruleset.from_snapshot({"defense_mode": "add_own"}).defense_gate,
                         "starters")

    # -- voto d'ufficio sui buchi ---------------------------------------------

    def test_hole_is_worth_nothing_by_default(self):
        rs = Ruleset(defense_enabled=False, max_substitutions=5)
        starters = legal_xi(6.0)
        starters[5] = line(6, "MID", 0, sv=True)     # s.v., panchina vuota
        team = score_team(starters, [], rs)
        self.assertEqual(team["base_total"], 60.0)
        self.assertEqual(team["unresolved_sv"], [6])
        self.assertEqual(team["sv_filled"], [])

    def test_the_league_can_fill_a_hole_with_an_office_vote(self):
        rs = Ruleset(defense_enabled=False, max_substitutions=5, sv_office_vote=4.0)
        starters = legal_xi(6.0)
        starters[5] = line(6, "MID", 0, sv=True)
        team = score_team(starters, [], rs)
        self.assertEqual(team["base_total"], 64.0)   # 10x6 + 4
        # Il buco resta un buco nel referto; quel che cambia e' quanto vale.
        self.assertEqual(team["unresolved_sv"], [6])
        self.assertEqual(team["sv_filled"], [6])
        filled = team["starters"][5]
        self.assertFalse(filled["sv"])
        self.assertTrue(filled["office"])            # lo stesso canale del voto d'ufficio
        self.assertEqual((filled["bonus"], filled["malus"]), (0.0, 0.0))

    def test_a_filled_keeper_feeds_the_defence_modifier_but_never_a_clean_sheet(self):
        """Il caso che ha motivato la regola: nessun portiere schierabile."""
        rs = Ruleset(defense_enabled=True, keeper_clean_sheet_enabled=True,
                     max_substitutions=5, sv_office_vote=4.0)
        starters = legal_xi(7.0)
        starters[0] = line(1, "GK", 0, sv=True, conceded=0)   # portiere s.v., niente riserva
        team = score_team(starters, [], rs)
        self.assertEqual(team["sv_filled"], [1])
        # Senza il voto d'ufficio il modificatore sarebbe morto (portiere senza
        # voto); con esso si calcola, e la media lo paga: (7+7+7+4)/4 = 6.25 -> +1.
        self.assertTrue(team["defense"]["eligible"])
        self.assertAlmostEqual(team["defense"]["avg"], 6.25)
        self.assertEqual(team["defense"]["bonus"], 1.0)
        # Ma imbattuto no: nessuno ha giocato quella partita.
        cs = next(m for m in team["modifiers"] if m.key == "keeper_clean_sheet")
        self.assertFalse(cs.eligible)

    def test_a_line_still_being_played_is_not_a_hole_yet(self):
        """Mid-round ogni giocatore in campo e' momentaneamente senza voto: coprirli
        mostrerebbe una squadra in vantaggio su undici voti d'ufficio al 5'."""
        rs = Ruleset(defense_enabled=False, max_substitutions=5, sv_office_vote=4.0)
        starters = legal_xi(6.0)
        starters[5] = {**line(6, "MID", 0, sv=True),
                       "provisional": True, "in_progress": True}
        team = score_team(starters, [], rs)
        self.assertEqual(team["sv_filled"], [])
        self.assertEqual(team["base_total"], 60.0)

    def test_a_line_still_being_played_is_not_substituted_either(self):
        """IL CASO DEL CALCIO D'INIZIO. Nei primi minuti il fornitore non ha ancora
        dati sui giocatori, quindi chi e' regolarmente in campo risulta senza voto:
        la panchina lo copriva subito, e il cambio si disfaceva da solo qualche
        minuto dopo. Un cambio e' la risposta a «non ha giocato», che di una partita
        cominciata da cinque minuti non si sa ancora."""
        rs = Ruleset(defense_enabled=False, max_substitutions=5)
        starters = legal_xi(6.0)
        starters[5] = {**line(6, "MID", 0, sv=True),
                       "provisional": True, "in_progress": True}
        team = score_team(starters, [line(99, "MID", 7.0)], rs)
        self.assertEqual(team["substitutions"], [])
        self.assertFalse(any(l["player_id"] == 99 for l in team["starters"]))

    def test_after_the_whistle_a_moving_line_is_a_hole_again(self):
        """Fra il fischio finale e la conferma del fornitore passa un'ora, e in
        quell'ora la partita che ha fatto il buco E' finita: la panchina copre e il
        voto d'ufficio riempie. Prima, legati a ``provisional``, arrivavano
        entrambi con un'ora di ritardo."""
        rs = Ruleset(defense_enabled=False, max_substitutions=5, sv_office_vote=4.0)
        starters = legal_xi(6.0)
        starters[5] = {**line(6, "MID", 0, sv=True), "provisional": True}
        team = score_team(starters, [], rs)
        self.assertEqual(team["sv_filled"], [6])

    def test_a_vacant_slot_is_filled_like_any_other_hole(self):
        """IL POSTO DEL CEDUTO. Prima restava scoperto — «non e' un buco in una
        squadra schierata, e' l'assenza di una» — e la conseguenza era doppia: niente
        voto d'ufficio E un difensore in meno sotto il cancello del modificatore, che
        quindi saltava. Cinque punti e un gol per una dimenticanza amministrativa,
        misurati su una lega vera. Ora e' un senza voto come gli altri; chi lo vuole
        piu' severo spegne il voto d'ufficio di lega."""
        rs = Ruleset(defense_enabled=False, max_substitutions=5, sv_office_vote=4.0)
        starters = legal_xi(6.0)
        starters[5] = {**line(6, "MID", 0, sv=True), "vacant": True}
        team = score_team(starters, [], rs)
        self.assertEqual(team["sv_filled"], [6])
        self.assertEqual(team["base_total"], 64.0)   # 10 x 6.0 + il voto d'ufficio

    def test_a_vacant_slot_is_covered_by_the_bench_like_any_other_sv(self):
        """IL VENDUTO RIMASTO IN FORMAZIONE. Chi cede un giocatore e non rischiera
        se la ritrova ereditata col posto vuoto, e quel posto lo copre la panchina
        come qualunque senza voto: il divieto di scavalco vincola le MODIFICHE
        dell'allenatore, non il motore che assegna i punti, quindi un panchinaro
        dietro a un chiodo entra lo stesso quando i conti si fanno.

        Costa un cambio del budget, non l'intero slot — che e' il punto: senza
        questo la dimenticanza si pagherebbe due volte."""
        rs = Ruleset(defense_enabled=False, max_substitutions=5, sv_office_vote=4.0)
        starters = legal_xi(6.0)
        starters[5] = {**line(6, "MID", 0, sv=True), "vacant": True}
        team = score_team(starters, [line(90, "MID", 7.0)], rs)
        self.assertEqual([(s["out"]["player_id"], s["in"]["player_id"])
                          for s in team["substitutions"]], [(6, 90)])
        self.assertEqual(team["base_total"], 67.0)   # 10 x 6.0 + il subentrato a 7.0
        # E il voto d'ufficio resta fuori anche qui: non serve, il posto e' coperto.
        self.assertEqual(team["sv_filled"], [])

    def test_a_hole_waits_for_the_last_whistle_of_the_round(self):
        """IL SABATO SERA. Con una sola partita giocata nessun panchinaro ha un
        voto, quindi nessuno e' utilizzabile e ogni titolare senza voto risulta
        «scoperto»: il voto d'ufficio arrivava subito, dicendo per due giorni una
        cosa — «questo non sara' sostituito» — che alla domenica sera era falsa,
        perche' il cambio si faceva e il voto d'ufficio spariva."""
        rs = Ruleset(defense_enabled=False, max_substitutions=5, sv_office_vote=4.0)
        starters = legal_xi(6.0)
        starters[5] = line(6, "MID", 0, sv=True)
        team = score_team(starters, [], rs, round_open=True)
        self.assertEqual(team["sv_filled"], [])
        self.assertEqual(team["base_total"], 60.0)
        # Il posto e' scoperto ADESSO, e il referto continua a dirlo: quel che
        # aspetta e' il conto da pagare, non la constatazione.
        self.assertEqual(team["unresolved_sv"], [6])

    def test_at_the_end_of_the_round_the_same_hole_is_paid(self):
        """La stessa formazione, un'ora dopo l'ultimo fischio."""
        rs = Ruleset(defense_enabled=False, max_substitutions=5, sv_office_vote=4.0)
        starters = legal_xi(6.0)
        starters[5] = line(6, "MID", 0, sv=True)
        team = score_team(starters, [], rs, round_open=False)
        self.assertEqual(team["sv_filled"], [6])
        self.assertEqual(team["base_total"], 64.0)

    def test_an_open_round_still_makes_the_substitutions_it_can(self):
        """Il rinvio riguarda il voto d'ufficio e nient'altro: un panchinaro che ha
        gia' giocato entra subito, perche' quel cambio non afferma niente sulle
        partite che restano — al massimo lo ridecide un panchinaro migliore, che e'
        gia' come funziona a giornata chiusa."""
        rs = Ruleset(defense_enabled=False, max_substitutions=5, sv_office_vote=4.0)
        starters = legal_xi(6.0)
        starters[5] = line(6, "MID", 0, sv=True)
        team = score_team(starters, [line(90, "MID", 7.0)], rs, round_open=True)
        self.assertEqual([(s["out"]["player_id"], s["in"]["player_id"])
                          for s in team["substitutions"]], [(6, 90)])
        self.assertEqual(team["base_total"], 67.0)
        self.assertEqual(team["unresolved_sv"], [])

    def test_a_pending_starter_is_not_a_hole(self):
        """Partita non ancora giocata: si aspetta (o la lega decide), non si tappa."""
        rs = Ruleset(defense_enabled=False, max_substitutions=5, sv_office_vote=4.0)
        starters = legal_xi(6.0)
        starters[5] = {**line(6, "MID", 0, sv=True), "pending": True}
        team = score_team(starters, [], rs)
        self.assertEqual(team["sv_filled"], [])
        self.assertEqual(team["unresolved_sv"], [])
        self.assertEqual(team["pending"], [6])

    def test_the_office_vote_survives_the_ruleset_snapshot(self):
        rs = Ruleset(sv_office_vote=4.0)
        self.assertEqual(Ruleset.from_snapshot(rs.to_snapshot()).sv_office_vote, 4.0)
        # Una giornata conclusa prima che l'opzione esistesse non ne aveva.
        self.assertEqual(Ruleset.from_snapshot({"defense_mode": "add_own"}).sv_office_vote, 0.0)

    def test_keeper_clean_sheet_bonus(self):
        rs = Ruleset(defense_enabled=False, keeper_clean_sheet_enabled=True)
        clean = score_team(legal_xi(6.0, gk_conceded=0), [], rs)
        conceded = score_team(legal_xi(6.0, gk_conceded=2), [], rs)
        resolve_fixture(clean, conceded, rs)
        self.assertEqual(clean["total"], 67.0)     # 66 + 1 clean sheet
        self.assertEqual(conceded["total"], 66.0)  # no bonus

    def test_keeper_clean_sheet_disabled_by_default(self):
        rs = Ruleset(defense_enabled=False)  # keeper_clean_sheet_enabled defaults False
        team = score_team(legal_xi(6.0, gk_conceded=0), [], rs)
        resolve_fixture(team, score_team(legal_xi(6.0), [], rs), rs)
        self.assertEqual(team["total"], 66.0)


class ComposeLinesTest(SimpleTestCase):
    """Pure lineup composition: sold players -> s.v. slots, absent players -> s.v.,
    sold bench players dropped."""

    def _index_and_roles(self):
        # Full XI present at 6.0 (1 GK + 4 DEF + 4 MID + 2 ATT), plus two DEF bench at 7.0.
        roles = ["GK"] + ["DEF"] * 4 + ["MID"] * 4 + ["ATT"] * 2  # players 1..11
        role_map, index = {}, {}
        for pid, r in enumerate(roles, start=1):
            role_map[pid] = r
            index[pid] = {"player_id": pid, "name": f"P{pid}", "lineup_role": r,
                          "voto_puro": 6.0, "fantavoto": 6.0, "sv": False, "conceded": 0}
        for b in (20, 21):
            role_map[b] = "DEF"
            index[b] = {"player_id": b, "name": f"B{b}", "lineup_role": "DEF",
                        "voto_puro": 7.0, "fantavoto": 7.0, "sv": False, "conceded": 0}
        return index, role_map

    def test_absent_player_is_sv_and_the_lineup_is_taken_as_sent(self):
        """The submitted lineup is authoritative: only "did he play" decides a line.

        It used to be filtered against the CURRENT roster, so a player sold after the
        matchday was silently turned into an s.v. slot — which made the same round
        score differently depending on WHEN the admin got round to concluding it.
        Ownership is now enforced where it belongs: at the transfer, which repairs
        every lineup still open and never touches one already locked
        (services/lineup_repair).
        """
        from vfoot.services.classic_matchday_scoring import compose_team_lines
        index, role_map = self._index_and_roles()
        del index[4]  # player 4 did NOT play (absent from the index)
        starters, bench = compose_team_lines(
            1, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11], [20, 21], index, role_map)
        self.assertEqual(len(starters), 11)
        by = {l["player_id"]: l for l in starters}
        self.assertTrue(by[4]["sv"])    # absent -> s.v.
        self.assertFalse(by[5]["sv"])   # played -> scores, whoever owns him today
        self.assertFalse(by[2]["sv"])
        self.assertEqual([l["player_id"] for l in bench], [20, 21])

    def test_compose_then_score(self):
        from vfoot.services.classic_matchday_scoring import (
            compose_team_lines,
            score_composed_fixture,
        )
        index, role_map = self._index_and_roles()
        # Home: DEF player 5 did not play -> s.v.; bench 20 (DEF) subs in (7.0).
        # 10 played at 6.0 (=60) + 7.0 = 67. Away: full XI at 6.0 = 66.
        home_index = {k: v for k, v in index.items() if k != 5}
        home = compose_team_lines(1, list(range(2, 12)), [20, 21], home_index, role_map)
        away = compose_team_lines(1, list(range(2, 12)), [20, 21], index, role_map)
        rs = Ruleset(defense_enabled=False, max_substitutions=5)
        payload = score_composed_fixture(home, away, rs, {
            "fixture_id": 7, "fantasy_round": 1, "real_matchday": 3,
            "home_team": "Alpha", "away_team": "Beta", "stage": None,
        })
        self.assertEqual(payload["mode"], "classic")
        self.assertEqual(payload["home_total"], 67.0)  # sold DEF replaced by bench DEF 7.0
        self.assertEqual(payload["away_total"], 66.0)  # full XI at 6.0
        self.assertIn("home", payload)
        self.assertIsInstance(payload["home"]["modifiers"], list)


class VoteCenteringReportTests(SimpleTestCase):
    """The arithmetic behind `manage.py check_vote_centering`.

    The check itself needs a real season and lives as a command, not a test — a
    test that skips itself on an empty database protects nothing. What IS testable
    here is the decomposition it prints, because that is what tells whoever reads a
    failure WHERE to look: a drift in the centre term means the index being scored
    has stopped matching the one the reference was calibrated on (an argument not
    passed, a feature not arriving), while the covariance term is structural.
    """

    def test_a_centred_role_reports_no_drift(self):
        from vfoot.management.commands.check_vote_centering import centering_report
        # z averaging zero, w constant -> the vote sits on 6 and both terms vanish.
        rows = [(-1.0, 0.8, 5.5), (0.0, 0.8, 6.0), (1.0, 0.8, 6.5)]
        r = centering_report({"DIF": rows}, 0.8)["DIF"]
        self.assertEqual(r["n"], 3)
        self.assertAlmostEqual(r["mean"], 6.0)
        self.assertAlmostEqual(r["drift"], 0.0)
        self.assertAlmostEqual(r["centre_term"], 0.0)
        self.assertAlmostEqual(r["cov_term"], 0.0)

    def test_an_off_centre_index_shows_up_in_the_centre_term(self):
        """Every z shifted up by the same amount — the signature of scoring an
        index the reference was not calibrated on. This is the exposure bug."""
        from vfoot.management.commands.check_vote_centering import centering_report
        rows = [(0.5, 0.8, 6.5), (0.5, 0.8, 6.5)]
        r = centering_report({"DIF": rows}, 0.8)["DIF"]
        self.assertAlmostEqual(r["centre_term"], 0.8 * 0.8 * 0.5)
        self.assertAlmostEqual(r["cov_term"], 0.0)   # no spread in w, nothing to correlate

    def test_minutes_correlated_with_z_show_up_in_the_covariance_term(self):
        """Long games earning a higher z is structural, not a defect — so it has to
        land in its own term rather than be mistaken for a miscalibration."""
        from vfoot.management.commands.check_vote_centering import centering_report
        rows = [(-1.0, 0.4, 5.5), (1.0, 0.9, 6.5)]   # E[z] = 0, but w tracks z
        r = centering_report({"DIF": rows}, 0.8)["DIF"]
        self.assertAlmostEqual(r["centre_term"], 0.0)
        self.assertGreater(r["cov_term"], 0.0)

    def test_roles_are_reported_independently(self):
        from vfoot.management.commands.check_vote_centering import centering_report
        out = centering_report({"DIF": [(0.0, 0.8, 6.0)],
                                "POR": [(0.0, 0.8, 5.0)]}, 0.8)
        self.assertAlmostEqual(out["DIF"]["drift"], 0.0)
        self.assertAlmostEqual(out["POR"]["drift"], -1.0)
