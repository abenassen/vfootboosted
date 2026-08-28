"""La formazione di partenza: scritta quando la rosa si completa, mai a una
scadenza; e il suggeritore, che ora vive nel backend."""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
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
    LeaguePlayerRole,
    SavedLineupSnapshot,
)
from vfoot.services import lineup_baseline
from vfoot.services.formation_rules import CLASSIC_CONSTRAINTS
from vfoot.services.lineup_suggest import bench_after, suggest_xi

ROLE_SEED = {"GK": "POR", "DEF": "DIF", "MID": "CEN", "ATT": "ATT"}


class SuggesterTests(SimpleTestCase):
    """Il porto di ``suggest()`` della pagina, riga per riga."""

    def _roster(self):
        rows = []
        pid = 1
        for role, n in (("GK", 3), ("DEF", 8), ("MID", 8), ("ATT", 6)):
            for i in range(n):
                rows.append({"player_id": pid, "role": role, "form": float(n - i)})
                pid += 1
        return rows

    def test_a_4_4_2_by_form_with_the_best_keeper(self):
        xi = suggest_xi(self._roster(), CLASSIC_CONSTRAINTS)
        self.assertEqual(xi["gk_player_id"], 1)
        roles = {}
        for r in self._roster():
            roles[r["player_id"]] = r["role"]
        counts = {}
        for p in xi["starter_player_ids"]:
            counts[roles[p]] = counts.get(roles[p], 0) + 1
        self.assertEqual(counts, {"DEF": 4, "MID": 4, "ATT": 2})
        self.assertEqual(len(xi["starter_player_ids"]), 10)
        # I migliori per forma di ogni reparto.
        self.assertEqual(xi["starter_player_ids"][:4], [4, 5, 6, 7])

    # --- la titolarita' ------------------------------------------------------
    #
    # Il suggeritore proponeva gente che la pagina accanto segnava OUT, e la
    # stessa schermata si contraddiceva. Questi test tengono chiuse le due meta'
    # della correzione: la titolarita' decide per prima, ma solo dove dice
    # qualcosa — dove non dice niente, decide la forma come ha sempre fatto.

    def _odds(self, **by_id):
        """{player_id: probabilita'} -> righe con `starting` addosso."""
        rows = self._roster()
        for r in rows:
            p = by_id.get(str(r["player_id"]))
            r["starting"] = None if p is None else {"probability": p, "status": "bench"}
        return rows

    def test_un_indisponibile_non_si_propone(self):
        rows = self._roster()
        for r in rows:
            r["starting"] = {"probability": 90, "status": "bench"}
        # Il miglior difensore per forma e' squalificato.
        best = next(r for r in rows if r["role"] == "DEF")
        best["starting"] = {"probability": 0, "status": "out"}
        xi = suggest_xi(rows, CLASSIC_CONSTRAINTS)
        self.assertNotIn(best["player_id"], xi["starter_player_ids"])

    def test_un_indisponibile_gia_in_campo_resta(self):
        """Se la sua partita e' cominciata non si puo' piu' muovere: `pinned`
        batte tutto, altrimenti la proposta sarebbe irrealizzabile."""
        rows = self._roster()
        fermo = next(r for r in rows if r["role"] == "DEF")
        fermo["starting"] = {"probability": 0, "status": "out"}
        xi = suggest_xi(rows, CLASSIC_CONSTRAINTS, pinned=[fermo["player_id"]])
        self.assertIn(fermo["player_id"], xi["starter_player_ids"])

    def test_chi_gioca_batte_chi_ha_la_forma_migliore(self):
        """IL CASO CHE HA FATTO NASCERE LA CORREZIONE, coi numeri veri di una
        rosa: tre portieri a 0.0 (2%), -0.072 (92%) e 0.0 (4%). Moltiplicare la
        forma per la probabilita' non basta — un negativo per uno resta peggiore
        di uno zero per niente — e l'unico che gioca perdeva."""
        rows = [
            {"player_id": 1, "role": "GK", "form": 0.0,
             "starting": {"probability": 2, "status": "bench"}},
            {"player_id": 2, "role": "GK", "form": -0.072,
             "starting": {"probability": 92, "status": "bench"}},
            {"player_id": 3, "role": "GK", "form": 0.0,
             "starting": {"probability": 4, "status": "bench"}},
        ]
        rows += [{"player_id": 10 + i, "role": r, "form": 1.0,
                  "starting": {"probability": 90, "status": "bench"}}
                 for i, r in enumerate(["DEF"] * 4 + ["MID"] * 4 + ["ATT"] * 2)]
        xi = suggest_xi(rows, CLASSIC_CONSTRAINTS)
        self.assertEqual(xi["gk_player_id"], 2)

    def test_dentro_la_stessa_fascia_decide_la_forma(self):
        """La correzione non deve buttare via il giudizio sul rendimento: fra due
        che giocano entrambi, un punto percentuale non ribalta niente."""
        rows = self._roster()
        for i, r in enumerate(rows):
            # Il peggiore per forma ha la probabilita' piu' alta: non basta.
            r["starting"] = {"probability": 80 + (i % 15), "status": "bench"}
        xi = suggest_xi(rows, CLASSIC_CONSTRAINTS)
        self.assertEqual(xi["starter_player_ids"][:4], [4, 5, 6, 7])

    def test_un_ballottaggio_perde_contro_un_titolare(self):
        rows = self._roster()
        for r in rows:
            r["starting"] = {"probability": 90, "status": "bench"}
        dubbio = next(r for r in rows if r["role"] == "DEF")   # il migliore per forma
        dubbio["starting"] = {"probability": 55, "status": "bench"}
        xi = suggest_xi(rows, CLASSIC_CONSTRAINTS)
        self.assertNotIn(dubbio["player_id"], xi["starter_player_ids"])

    def test_senza_previsioni_niente_cambia(self):
        """Il suggeritore gira anche ad agosto, prima che una fonte abbia
        pubblicato: assenza di notizia non e' notizia di assenza."""
        senza = suggest_xi(self._roster(), CLASSIC_CONSTRAINTS)
        vuote = suggest_xi(self._odds(), CLASSIC_CONSTRAINTS)
        self.assertEqual(senza, vuote)

    def test_the_top_up_never_passes_a_ceiling(self):
        """Una linea corta veniva riempita con un sesto centrocampista, e la
        proposta stessa era una formazione che il salvataggio rifiutava."""
        roster = [{"player_id": 1, "role": "GK", "form": 1.0}]
        roster += [{"player_id": 10 + i, "role": "DEF", "form": 1.0} for i in range(2)]
        roster += [{"player_id": 20 + i, "role": "MID", "form": 1.0} for i in range(9)]
        roster += [{"player_id": 30 + i, "role": "ATT", "form": 1.0} for i in range(1)]
        xi = suggest_xi(roster, CLASSIC_CONSTRAINTS)
        mids = [p for p in xi["starter_player_ids"] if 20 <= p < 30]
        self.assertEqual(len(mids), CLASSIC_CONSTRAINTS["per_role"]["MID"]["max"])
        self.assertLess(len(xi["starter_player_ids"]), 10, "meglio corta che illegale")

    def test_frozen_players_are_a_fact_before_a_preference(self):
        roster = self._roster()
        # Il peggior difensore e' gia' in campo: resta. Il miglior attaccante ha la
        # partita iniziata ed e' fuori dagli undici: non si tocca.
        xi = suggest_xi(roster, CLASSIC_CONSTRAINTS, pinned=[11], locked=[20])
        self.assertIn(11, xi["starter_player_ids"])
        self.assertNotIn(20, xi["starter_player_ids"])

    def test_the_bench_is_everybody_else_in_role_then_form_order(self):
        roster = self._roster()
        xi = suggest_xi(roster, CLASSIC_CONSTRAINTS)
        bench = bench_after(roster, [xi["gk_player_id"]] + xi["starter_player_ids"])
        self.assertEqual(len(bench), 14)
        self.assertEqual(bench[:2], [2, 3], "i due portieri di riserva aprono la panchina")


class _League(TestCase):
    def setUp(self):
        comp = Competition.objects.create(external_id="23", name="Serie A")
        season = Season.objects.create(code="2026-2027")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=season, name="Serie A 2026-2027")
        self.owner = User.objects.create_user("owner", "o@x.it", "pw")
        self.league = FantasyLeague.objects.create(
            name="Lega", owner=self.owner, mode=FantasyLeague.MODE_CLASSIC,
            reference_season=self.cs, lineup_lock_mode=FantasyLeague.LOCK_OWN)
        self.membership = LeagueMembership.objects.create(
            league=self.league, user=self.owner, role=LeagueMembership.ROLE_ADMIN)
        self.team = FantasyTeam.objects.create(
            league=self.league, manager=self.membership, name="Squadra")
        a = TeamSeason.objects.create(competition_season=self.cs, team=Team.objects.create(name="A"))
        b = TeamSeason.objects.create(competition_season=self.cs, team=Team.objects.create(name="B"))
        self.ts = a
        self.kick = timezone.now() + timedelta(days=1)
        Match.objects.create(
            competition_season=self.cs, matchday=1, kickoff=self.kick, kickoff_provisional=False,
            home_team=a, away_team=b, status=Match.STATUS_SCHEDULED,
            external_source="sofascore", external_id="m1")
        Match.objects.create(
            competition_season=self.cs, matchday=2, kickoff=self.kick + timedelta(days=7),
            kickoff_provisional=False, home_team=b, away_team=a, status=Match.STATUS_SCHEDULED,
            external_source="sofascore", external_id="m2")
        for md in (1, 2):
            FantasyMatchday.objects.create(
                league=self.league, real_competition_season=self.cs, real_matchday=md)
        self.players = []

    def fill(self, short=0):
        for role, n in (("GK", 3), ("DEF", 8), ("MID", 8), ("ATT", 6)):
            for i in range(n):
                if short and role == "ATT" and i >= n - short:
                    continue
                p = Player.objects.create(full_name=f"{role}{i}", classic_role_seed=ROLE_SEED[role])
                PlayerTeamStint.objects.create(player=p, team_season=self.ts)
                LeaguePlayerRole.objects.create(league=self.league, player=p, role=ROLE_SEED[role])
                FantasyRosterSlot.objects.create(team=self.team, player=p, purchase_price=1)
                self.players.append(p)

    def _snaps(self):
        return SavedLineupSnapshot.objects.filter(league_id=str(self.league.id))


class BaselineTests(_League):
    def test_a_complete_roster_gets_its_starting_lineup(self):
        self.fill()
        snap = lineup_baseline.ensure_for(self.team)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.matchday_id, "1")
        self.assertEqual(snap.lineup_id, f"team{self.team.id}")
        self.assertEqual(snap.origin, SavedLineupSnapshot.ORIGIN_BASELINE)
        self.assertIsNotNone(snap.gk_player_id)
        self.assertEqual(len(snap.starter_player_ids), 10)
        self.assertEqual(len(snap.bench_player_ids), 14)

    def test_a_second_call_rewrites_nothing(self):
        self.fill()
        first = lineup_baseline.ensure_for(self.team)
        self.assertIsNone(lineup_baseline.ensure_for(self.team))
        self.assertEqual(self._snaps().count(), 1)
        self.assertEqual(self._snaps().get().starter_player_ids, first.starter_player_ids)

    def test_an_incomplete_roster_gets_nothing(self):
        """Resta il caso dell'admin: una rosa incompleta non ammette un undici
        per costruzione."""
        self.fill(short=1)
        self.assertIsNone(lineup_baseline.ensure_for(self.team))
        self.assertEqual(self._snaps().count(), 0)

    def test_a_team_that_already_fielded_is_left_alone(self):
        self.fill()
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="1",
            lineup_id=f"team{self.team.id}:comp7", gk_player_id="1",
            starter_player_ids=[], bench_player_ids=[])
        self.assertIsNone(lineup_baseline.ensure_for(self.team))

    def test_never_written_for_a_round_that_has_closed_on_the_team(self):
        """Rosa completata a giornata cominciata: la prima formazione sarebbe
        scelta da una macchina coi voti sul tabellone. Si passa alla giornata
        dopo, e la 1 resta il caso dell'admin."""
        self.fill()
        Match.objects.filter(external_id="m1").update(kickoff=timezone.now() - timedelta(hours=1))
        snap = lineup_baseline.ensure_for(self.team)
        self.assertIsNotNone(snap)
        self.assertEqual(snap.matchday_id, "2")

    def test_the_conclusion_reads_it_as_a_lineup(self):
        from vfoot.services.classic_matchday_scoring import team_lines_for_conclusion

        self.fill()
        lineup_baseline.ensure_for(self.team)
        starters, _, meta = team_lines_for_conclusion(self.league, self.team, None, 1, {}, None)
        self.assertEqual(meta["source"], "lineup")
        self.assertEqual(len(starters), 11)

    def test_matchday_two_inherits_it(self):
        from vfoot.services.classic_matchday_scoring import read_previous_lineup

        self.fill()
        lineup_baseline.ensure_for(self.team)
        prev = read_previous_lineup(self.league.id, 2, self.team.id, None)
        self.assertIsNotNone(prev)
        self.assertEqual(prev.matchday_id, "1")


class ThePageTests(_League):
    def _client(self):
        token, _ = Token.objects.get_or_create(user=self.owner)
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
        return c

    def test_the_get_writes_the_baseline_as_a_safety_net_and_says_so(self):
        self.fill()
        d = self._client().get(f"/api/v1/leagues/{self.league.id}/lineup?matchday=1").data
        self.assertEqual(d["lineup_source"]["kind"], "baseline")
        self.assertEqual(len(d["saved_lineup"]["starter_player_ids"]), 10)
        self.assertEqual(self._snaps().count(), 1)
        self.assertEqual(len(d["suggested_lineup"]["starter_player_ids"]), 10)

    def test_after_the_deadline_the_get_only_proposes(self):
        self.fill()
        Match.objects.filter(external_id="m1").update(kickoff=timezone.now() - timedelta(hours=1))
        d = self._client().get(f"/api/v1/leagues/{self.league.id}/lineup?matchday=1").data
        self.assertIsNone(d["saved_lineup"])
        self.assertEqual(d["lineup_source"]["kind"], "none")
        self.assertEqual(len(d["suggested_lineup"]["starter_player_ids"]), 10)
        # ...and the baseline went to matchday 2, not 1.
        self.assertEqual(self._snaps().get().matchday_id, "2")

    def test_the_auction_hammer_writes_it(self):
        """Il punto in cui una rosa si completa davvero: l'ultima assegnazione."""
        self.fill(short=1)
        last = Player.objects.create(full_name="ATT5", classic_role_seed="ATT")
        PlayerTeamStint.objects.create(player=last, team_season=self.ts)
        LeaguePlayerRole.objects.create(league=self.league, player=last, role="ATT")
        r = self._client().post(
            f"/api/v1/leagues/{self.league.id}/teams/{self.team.id}/roster/add",
            {"player_id": last.id, "purchase_price": 1}, format="json")
        self.assertEqual(r.status_code, 201, r.data)
        self.assertEqual(self._snaps().count(), 1)
        self.assertEqual(self._snaps().get().origin, "baseline")
