"""Il motore delle probabili, e le due cose che possono romperlo in silenzio.

La prima e' l'ORDINE: la partita precedente di una squadra e' quella per data, non
per numero di giornata, e con un recupero le due divergono. Misurato sulla 25-26:
per giornata la regola del rosso risultava vera nel 92,1% dei casi, per data nel
100,0%. Non era il calcio a fare eccezioni.

La seconda e' il 200 VUOTO di SofaScore: ``confirmed: false`` con zero giocatori
non e' una previsione, e chi non conta i giocatori salva una previsione vuota
senza un errore da nessuna parte.
"""
from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.test import SimpleTestCase, TestCase, override_settings

from realdata.models import (
    CARD_RED, CARD_YELLOW, Competition, CompetitionSeason, LineupEvidence,
    LineupForecast, LineupForecastEntry, Match, MatchAppearance,
    MatchDisciplinaryEvent, Player, PlayerTeamStint, Season, Team, TeamSeason,
)
from realdata.services import lineup_forecast as engine
from realdata.services import probable_lineups as probable

UTC = dt_timezone.utc


class _Pitch(TestCase):
    """Due squadre, rose vere, un calendario che si puo' scompaginare."""

    def setUp(self):
        comp = Competition.objects.create(name="Serie A")
        season = Season.objects.create(code="2026-2027")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=season, external_source="sofascore",
            external_id="95836")
        self.ts = {}
        self.squad = {}
        for key in ("A", "B"):
            team = Team.objects.create(name=f"Squadra {key}")
            ts = TeamSeason.objects.create(team=team, competition_season=self.cs)
            self.ts[key] = ts
            self.squad[key] = []
            for i in range(18):
                p = Player.objects.create(
                    full_name=f"{key}{i:02d} Giocatore",
                    external_source="sofascore", external_id=f"{key}{i:02d}",
                    is_goalkeeper=(i < 2))
                PlayerTeamStint.objects.create(player=p, team_season=ts)
                self.squad[key].append(p)

    def _match(self, md, day, *, status=Match.STATUS_FINISHED, home="A", away="B"):
        return Match.objects.create(
            competition_season=self.cs, matchday=md,
            kickoff=datetime(2026, 9, day, 18, 45, tzinfo=UTC),
            home_team=self.ts[home], away_team=self.ts[away], status=status,
            external_source="sofascore", external_id=f"16280{md:03d}")

    def _played(self, match, key, starters):
        for i, p in enumerate(self.squad[key]):
            MatchAppearance.objects.create(
                match=match, player=p, team_season=self.ts[key],
                side="home" if key == "A" else "away",
                is_starter=p in starters, minutes_played=90 if p in starters else 0)

    def _card(self, match, player, key, card):
        MatchDisciplinaryEvent.objects.create(
            match=match, player=player, team_season=self.ts[key],
            card_type=card, provider="sofascore",
            provider_event_id=f"{match.id}-{player.id}-{card}")


class SuspensionTests(_Pitch):
    def test_il_rosso_squalifica(self):
        m = self._match(1, 1)
        self._played(m, "A", self.squad["A"][:11])
        victim = self.squad["A"][5]
        self._card(m, victim, "A", CARD_RED)
        banned = engine.suspensions_for(self.cs, datetime(2026, 9, 8, tzinfo=UTC))
        self.assertIn(victim.id, banned)
        self.assertIn("espulso", banned[victim.id])

    def test_la_quinta_ammonizione_squalifica_la_quarta_no(self):
        victim = self.squad["A"][6]
        for md in range(1, 6):
            m = self._match(md, md)
            self._played(m, "A", self.squad["A"][:11])
            self._card(m, victim, "A", CARD_YELLOW)
            got = engine.suspensions_for(
                self.cs, datetime(2026, 9, md, 20, 0, tzinfo=UTC) + timedelta(days=1))
            if md < 5:
                self.assertNotIn(victim.id, got, f"squalificato alla {md}a gialla")
            else:
                self.assertIn(victim.id, got)
                self.assertIn("5a ammonizione", got[victim.id])

    def test_conta_la_data_non_la_giornata(self):
        """IL BUG. La 20a si gioca come recupero DOPO la 21a: il rosso preso nella
        21a si sconta nel recupero, non 'nella giornata successiva' — che per
        numero sarebbe la 22a e per data non esiste ancora."""
        g21 = self._match(21, 5)              # giocata il 5
        recupero20 = self._match(20, 12)      # la 20a, recuperata il 12
        self._played(g21, "A", self.squad["A"][:11])
        self._played(recupero20, "A", self.squad["A"][:11])
        victim = self.squad["A"][3]
        self._card(g21, victim, "A", CARD_RED)

        # Al 12 (il recupero) la squalifica DEVE valere: e' la partita successiva.
        at_recupero = engine.suspensions_for(self.cs, datetime(2026, 9, 12, 12, 0, tzinfo=UTC))
        self.assertIn(victim.id, at_recupero,
                      "il rosso della 21a non e' stato scontato nel recupero della 20a")
        # E dopo il recupero non deve piu' valere: e' stata scontata.
        after = engine.suspensions_for(self.cs, datetime(2026, 9, 20, tzinfo=UTC))
        self.assertNotIn(victim.id, after)


class ForecastShapeTests(_Pitch):
    def test_la_squadra_schiera_undici(self):
        for md in range(1, 4):
            m = self._match(md, md)
            self._played(m, "A", self.squad["A"][:11])
            self._played(m, "B", self.squad["B"][:11])
        nxt = self._match(4, 10, status=Match.STATUS_SCHEDULED)
        per = engine.forecast_teams(self.cs, nxt.kickoff,
                                    [self.ts["A"].id, self.ts["B"].id], matchday=4)
        rows = per[self.ts["A"].id]
        total = sum(f.probability for f in rows)
        self.assertAlmostEqual(total, 11.0, delta=0.35,
                               msg=f"le probabilita' sommano {total}, non undici")
        self.assertEqual(len(engine.predicted_xi(rows)), 11)
        # Un portiere solo fra i titolari previsti.
        xi = engine.predicted_xi(rows)
        keepers = [f for f in rows if f.is_goalkeeper and f.player_id in xi]
        self.assertEqual(len(keepers), 1)

    def test_chi_gioca_sempre_sta_sopra_chi_non_gioca_mai(self):
        # La finestra intera (FORM_WINDOW), che e' il caso vero: con tre sole
        # giornate il priore di chi non ha mai giocato resta alto per costruzione,
        # ed e' giusto che resti alto — tre partite non bastano a dire di nessuno
        # che non gioca mai.
        for md in range(1, engine.FORM_WINDOW + 1):
            m = self._match(md, md)
            self._played(m, "A", self.squad["A"][:11])
            self._played(m, "B", self.squad["B"][:11])
        nxt = self._match(engine.FORM_WINDOW + 1, 20, status=Match.STATUS_SCHEDULED)
        per = engine.forecast_teams(self.cs, nxt.kickoff,
                                    [self.ts["A"].id, self.ts["B"].id],
                                    matchday=engine.FORM_WINDOW + 1)
        by_id = {f.player_id: f.probability for f in per[self.ts["A"].id]}
        fisso, mai = by_id[self.squad["A"][2].id], by_id[self.squad["A"][15].id]
        self.assertGreater(fisso, 0.8)
        self.assertLess(mai, 0.3)
        self.assertGreater(fisso - mai, 0.5)

    def test_lo_squalificato_e_zero_non_e_un_numero_basso(self):
        for md in range(1, 4):
            m = self._match(md, md)
            self._played(m, "A", self.squad["A"][:11])
            self._played(m, "B", self.squad["B"][:11])
            last = m
        victim = self.squad["A"][2]
        self._card(last, victim, "A", CARD_RED)
        nxt = self._match(4, 10, status=Match.STATUS_SCHEDULED)
        engine.build_forecast(nxt)
        e = LineupForecastEntry.objects.get(forecast__match=nxt,
                                            forecast__source=LineupForecast.SOURCE_VFOOT,
                                            player=victim)
        self.assertEqual(e.probability, 0)
        self.assertEqual(e.status, LineupForecastEntry.STATUS_OUT)
        self.assertIn("espulso", e.reason)


class EvidenceTests(_Pitch):
    def test_un_indizio_sposta_ma_non_decide(self):
        for md in range(1, 4):
            m = self._match(md, md)
            self._played(m, "A", self.squad["A"][:11])
            self._played(m, "B", self.squad["B"][:11])
        nxt = self._match(4, 10, status=Match.STATUS_SCHEDULED)
        starter = self.squad["A"][3]

        def prob():
            per = engine.forecast_teams(self.cs, nxt.kickoff,
                                        [self.ts["A"].id, self.ts["B"].id], matchday=4)
            return {f.player_id: f.probability for f in per[self.ts["A"].id]}[starter.id]

        before = prob()
        LineupEvidence.objects.create(
            competition_season=self.cs, player=starter, matchday=4,
            kind=LineupEvidence.KIND_INTERNAL,
            availability=LineupEvidence.AVAIL_DOUBT, log_odds=-2.0,
            source="admin", note="fuori squadra per litigio")
        after = prob()
        self.assertLess(after, before)
        self.assertGreater(after, 0.0, "un indizio non deve poter azzerare")

    def test_una_certezza_azzera(self):
        for md in range(1, 4):
            m = self._match(md, md)
            self._played(m, "A", self.squad["A"][:11])
            self._played(m, "B", self.squad["B"][:11])
        nxt = self._match(4, 10, status=Match.STATUS_SCHEDULED)
        starter = self.squad["A"][3]
        LineupEvidence.objects.create(
            competition_season=self.cs, player=starter, matchday=4,
            kind=LineupEvidence.KIND_INJURY,
            availability=LineupEvidence.AVAIL_OUT, source="sofascore",
            note="Thigh Injury")
        per = engine.forecast_teams(self.cs, nxt.kickoff,
                                    [self.ts["A"].id, self.ts["B"].id], matchday=4)
        f = {x.player_id: x for x in per[self.ts["A"].id]}[starter.id]
        self.assertTrue(f.out)
        self.assertEqual(f.probability, 0.0)
        self.assertEqual(f.reason, "Thigh Injury")


class SofascorePayloadTests(SimpleTestCase):
    """Il 200 vuoto: l'unico modo di sbagliarsi senza accorgersene."""

    def _payload(self, n_players, confirmed=False):
        half = [{"player": {"id": 1000 + i}, "substitute": False}
                for i in range(n_players // 2)]
        return {"confirmed": confirmed,
                "home": {"formation": "4-3-3", "players": list(half)},
                "away": {"formation": "3-5-2", "players": list(half)}}

    def test_il_duecento_vuoto_non_e_una_previsione(self):
        self.assertFalse(probable.is_usable_prediction(self._payload(0)))
        self.assertFalse(probable.is_usable_prediction({"confirmed": False}))
        self.assertFalse(probable.is_usable_prediction(None))

    def test_una_previsione_piena_lo_e(self):
        self.assertTrue(probable.is_usable_prediction(self._payload(22)))

    def test_la_distinta_ufficiale_e_utilizzabile_e_si_riconosce(self):
        # RIVISTO: prima la rifiutavamo, e cosi' l'ora piu' importante — quella
        # fra la distinta ufficiale e il calcio d'inizio — restava scoperta.
        sheet = self._payload(22, confirmed=True)
        self.assertTrue(probable.is_usable_prediction(sheet))
        self.assertTrue(probable.is_official(sheet))
        self.assertFalse(probable.is_official(self._payload(22)))

    def test_il_peso_della_fonte_viene_dalla_sua_accuratezza(self):
        # 0.85 -> log(0.85/0.15) = 1.7346...
        self.assertAlmostEqual(probable.source_log_odds(0.85), 1.7346, places=3)
        self.assertAlmostEqual(probable.source_log_odds(0.5), 0.0, places=2)
        self.assertGreater(probable.source_log_odds(0.95),
                           probable.source_log_odds(0.85))


class MergeTests(_Pitch):
    def _prepare(self):
        for md in range(1, 4):
            m = self._match(md, md)
            self._played(m, "A", self.squad["A"][:11])
            self._played(m, "B", self.squad["B"][:11])
        nxt = self._match(4, 10, status=Match.STATUS_SCHEDULED)
        engine.build_forecast(nxt)
        return nxt

    def _sofa(self, match, starters_a):
        fc = LineupForecast.objects.create(match=match,
                                           source=LineupForecast.SOURCE_SOFASCORE)
        for p in self.squad["A"]:
            LineupForecastEntry.objects.create(
                forecast=fc, player=p, team_season=self.ts["A"],
                probability=100 if p in starters_a else 0,
                status=(LineupForecastEntry.STATUS_STARTER if p in starters_a
                        else LineupForecastEntry.STATUS_BENCH))
        return fc

    def test_sofascore_sposta_non_sovrascrive(self):
        nxt = self._prepare()
        panchinaro = self.squad["A"][14]
        self._sofa(nxt, self.squad["A"][:10] + [panchinaro])
        got = probable.merged(nxt)
        # promosso, ma non a 100: il nostro motore sa che non gioca mai
        self.assertGreater(got[panchinaro.id]["probability"], 20)
        self.assertLess(got[panchinaro.id]["probability"], 100)
        self.assertEqual(got[panchinaro.id]["sources"], ["vfoot", "sofascore"])

    def test_due_esclusi_non_sono_uguali(self):
        """Cio' che un XI binario perderebbe: fra due panchinari, chi gioca di
        piu' resta davanti anche dopo che SofaScore li ha esclusi entrambi."""
        nxt = self._prepare()
        self._sofa(nxt, self.squad["A"][:11])
        got = probable.merged(nxt)
        quasi = got[self.squad["A"][12].id]["probability"]
        mai = got[self.squad["A"][17].id]["probability"]
        self.assertGreaterEqual(quasi, mai)

    def test_la_squalifica_batte_sofascore(self):
        for md in range(1, 4):
            m = self._match(md, md)
            self._played(m, "A", self.squad["A"][:11])
            self._played(m, "B", self.squad["B"][:11])
            last = m
        victim = self.squad["A"][2]
        self._card(last, victim, "A", CARD_RED)
        nxt = self._match(4, 10, status=Match.STATUS_SCHEDULED)
        engine.build_forecast(nxt)
        self._sofa(nxt, self.squad["A"][:11])       # SofaScore lo da' titolare
        got = probable.merged(nxt)
        self.assertEqual(got[victim.id]["probability"], 0,
                         "una certezza non si compensa con un parere")


class RefreshTests(_Pitch):
    """La cadenza e la rinuncia: le due cose che decidono quanto pesiamo su
    SofaScore, e che non si vedono guardando il codice del tick."""

    def _payload(self, cache: Path, match, n=11):
        home = [{"player": {"id": 900000 + i,
                            "name": p.full_name}, "substitute": i >= n}
                for i, p in enumerate(self.squad["A"][:14])]
        away = [{"player": {"id": 910000 + i,
                            "name": p.full_name}, "substitute": i >= n}
                for i, p in enumerate(self.squad["B"][:14])]
        body = {"confirmed": False,
                "home": {"formation": "4-3-3", "players": home},
                "away": {"formation": "3-5-2", "players": away}}
        (cache / f"api_v1_event_{match.external_id}_lineups.json").write_text(
            json.dumps(body))

    def test_la_cadenza_stringe_avvicinandosi(self):
        now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        far = self._match(5, 3, status=Match.STATUS_SCHEDULED)
        far.kickoff = now + timedelta(hours=48); far.save()
        near = self._match(6, 4, status=Match.STATUS_SCHEDULED, home="B", away="A")
        near.kickoff = now + timedelta(hours=6); near.save()
        # Mai viste: entrambe dovute.
        self.assertEqual({m.id for m in probable.due_matches(now)}, {far.id, near.id})
        # Lette tre ore fa: la vicina e' di nuovo dovuta (2h), la lontana no (12h).
        for m in (far, near):
            LineupForecast.objects.create(
                match=m, source=LineupForecast.SOURCE_SOFASCORE,
                refreshed_at=now - timedelta(hours=3))
        self.assertEqual([m.id for m in probable.due_matches(now)], [near.id])

    def test_una_partita_gia_cominciata_non_e_affar_nostro(self):
        now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        live = self._match(5, 1, status=Match.STATUS_LIVE)
        live.kickoff = now - timedelta(minutes=20); live.save()
        started = self._match(6, 1, status=Match.STATUS_SCHEDULED, home="B", away="A")
        started.kickoff = now - timedelta(minutes=5); started.save()
        self.assertEqual(probable.due_matches(now), [])

    def test_su_un_blocco_si_rinuncia_e_non_si_importa_niente(self):
        now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        m = self._match(5, 3, status=Match.STATUS_SCHEDULED)
        m.kickoff = now + timedelta(hours=6); m.save()
        calls = []

        def blocked(ids):
            calls.append(list(ids))
            return False

        report = probable.refresh(now, fetch=blocked)
        self.assertEqual(calls, [[int(m.external_id)]])
        self.assertTrue(report["blocked"])
        self.assertEqual(report["imported"], 0)
        self.assertFalse(LineupForecast.objects.filter(
            source=LineupForecast.SOURCE_SOFASCORE).exists())

    def test_un_giro_riuscito_importa(self):
        now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        m = self._match(5, 3, status=Match.STATUS_SCHEDULED)
        m.kickoff = now + timedelta(hours=6); m.save()
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            self._payload(cache, m)
            with override_settings(VFOOT_SOFASCORE_CACHE=str(cache)):
                report = probable.refresh(now, fetch=lambda ids: True)
        self.assertEqual(report["due"], 1)
        self.assertEqual(report["imported"], 1)
        self.assertEqual(report["empty"], 0)

    def test_il_nostro_motore_gira_anche_se_sofascore_non_risponde(self):
        """La ragione per cui i due strati sono separati: se l'egress e' occupato
        la pagina non resta vuota, resta grossolana."""
        now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        for md in range(1, 4):
            played = self._match(md, md)
            # PRIMA di ``now``, o il motore non ha storia e — giustamente — non
            # prevede niente: v. NoHistoryTests.
            played.kickoff = now - timedelta(days=4 - md); played.save()
            self._played(played, "A", self.squad["A"][:11])
            self._played(played, "B", self.squad["B"][:11])
        nxt = self._match(5, 3, status=Match.STATUS_SCHEDULED)
        nxt.kickoff = now + timedelta(hours=6); nxt.save()
        report = probable.refresh_all(now, fetch=lambda ids: False)
        self.assertTrue(report["blocked"])
        self.assertEqual(report["built"], 1)
        self.assertTrue(LineupForecast.objects.filter(
            match=nxt, source=LineupForecast.SOURCE_VFOOT).exists())


class NoHistoryTests(_Pitch):
    """Alla PRIMA giornata il motore non sa niente, e deve dirlo.

    Con zero partite in finestra ogni priore vale il fondo: tutti i giocatori
    escono con la stessa probabilita' e ``predicted_xi`` finisce per scegliere gli
    undici ``player_id`` piu' bassi, cioe' l'ordine di importazione. Misurato
    sulla 25-26: un solo valore (0,4762) per tutti, e un 53,6% di XI "azzeccati"
    che e' l'ordine con cui la rosa e' stata caricata. Sembra conoscenza e non lo
    e': e' il modo peggiore di sbagliare, perche' non si vede.
    """

    def test_senza_storia_non_si_prevede(self):
        first = self._match(1, 1, status=Match.STATUS_SCHEDULED)
        per = engine.forecast_teams(self.cs, first.kickoff,
                                    [self.ts["A"].id, self.ts["B"].id], matchday=1)
        self.assertEqual(per, {}, "ha previsto una formazione senza aver visto nulla")
        self.assertIsNone(engine.build_forecast(first))
        self.assertFalse(LineupForecast.objects.filter(match=first).exists())

    def test_una_partita_basta(self):
        # Alla seconda giornata il motore fa l'80,0% sulla stagione vera: una
        # partita di storia e' poca ma non e' zero, e la differenza fra le due
        # cose e' tutta qui.
        played = self._match(1, 1)
        self._played(played, "A", self.squad["A"][:11])
        self._played(played, "B", self.squad["B"][:11])
        second = self._match(2, 8, status=Match.STATUS_SCHEDULED)
        per = engine.forecast_teams(self.cs, second.kickoff,
                                    [self.ts["A"].id, self.ts["B"].id], matchday=2)
        self.assertEqual(len(per), 2)
        rows = per[self.ts["A"].id]
        self.assertGreater(len({round(f.probability, 3) for f in rows}), 1,
                           "tutte uguali: non sta usando la partita giocata")
        # I "titolari" della finta sono i primi undici della rosa, cioe' DUE
        # portieri: un XI legale ne prende uno solo, quindi si controlla che ci
        # siano tutti i nove di movimento che hanno giocato, e che il secondo
        # portiere sia rimasto fuori.
        xi = engine.predicted_xi(rows)
        self.assertEqual(len(xi), 11)
        for p in self.squad["A"][2:11]:
            self.assertIn(p.id, xi)
        self.assertNotIn(self.squad["A"][1].id, xi)

    def test_alla_prima_giornata_la_previsione_la_porta_sofascore(self):
        """Il motivo per cui i due strati sono separati, visto dall'altra parte."""
        first = self._match(1, 1, status=Match.STATUS_SCHEDULED)
        fc = LineupForecast.objects.create(match=first,
                                           source=LineupForecast.SOURCE_SOFASCORE)
        for i, p in enumerate(self.squad["A"][:14]):
            LineupForecastEntry.objects.create(
                forecast=fc, player=p, team_season=self.ts["A"],
                probability=100 if i < 11 else 0,
                status=(LineupForecastEntry.STATUS_STARTER if i < 11
                        else LineupForecastEntry.STATUS_BENCH))
        got = probable.merged(first)
        starters = [pid for pid, v in got.items()
                    if v["status"] == LineupForecastEntry.STATUS_STARTER]
        self.assertEqual(len(starters), 11)
        self.assertEqual(got[self.squad["A"][0].id]["sources"], ["sofascore"])


class OfficialLineupTests(_Pitch):
    """La distinta ufficiale esce un'ora prima del calcio d'inizio, e per un
    giorno l'abbiamo scaricata e buttata via: la finestra live si apre al fischio
    d'inizio e il giro delle probabili la rifiutava perche' "confermata"."""

    def _sheet(self, confirmed):
        home = [{"player": {"id": 900000 + i}, "substitute": i >= 11}
                for i in range(14)]
        away = [{"player": {"id": 910000 + i}, "substitute": i >= 11}
                for i in range(14)]
        return {"confirmed": confirmed,
                "home": {"formation": "4-3-3", "players": home},
                "away": {"formation": "3-5-2", "players": away}}

    def test_la_distinta_ufficiale_e_utilizzabile(self):
        self.assertTrue(probable.is_usable_prediction(self._sheet(True)))
        self.assertTrue(probable.is_official(self._sheet(True)))
        self.assertFalse(probable.is_official(self._sheet(False)))

    def test_il_duecento_vuoto_non_lo_e_mai(self):
        for confirmed in (True, False):
            empty = {"confirmed": confirmed, "home": {"players": []},
                     "away": {"players": []}}
            self.assertFalse(probable.is_usable_prediction(empty))
            self.assertFalse(probable.is_official(empty))

    def _prepared(self, official):
        for md in range(1, 4):
            played = self._match(md, md)
            self._played(played, "A", self.squad["A"][:11])
            self._played(played, "B", self.squad["B"][:11])
        nxt = self._match(5, 10, status=Match.STATUS_SCHEDULED)
        engine.build_forecast(nxt)
        fc = LineupForecast.objects.create(
            match=nxt, source=LineupForecast.SOURCE_SOFASCORE, official=official)
        # SofaScore schiera un panchinaro e lascia fuori un titolare nostro.
        xi = self.squad["A"][:10] + [self.squad["A"][14]]
        for p in self.squad["A"]:
            LineupForecastEntry.objects.create(
                forecast=fc, player=p, team_season=self.ts["A"],
                probability=100 if p in xi else 0,
                status=(LineupForecastEntry.STATUS_STARTER if p in xi
                        else LineupForecastEntry.STATUS_BENCH))
        return nxt

    def test_ufficiale_non_si_fonde_si_sostituisce(self):
        nxt = self._prepared(official=True)
        got = probable.merged(nxt)
        self.assertEqual(got[self.squad["A"][14].id]["probability"], 100)
        # Il nostro titolare che la distinta non nomina non e' "improbabile": e' fuori.
        self.assertEqual(got[self.squad["A"][10].id]["probability"], 0)

    def test_previsione_invece_si_fonde(self):
        nxt = self._prepared(official=False)
        got = probable.merged(nxt)
        promosso = got[self.squad["A"][14].id]["probability"]
        self.assertGreater(promosso, 20)
        self.assertLess(promosso, 100, "una previsione non e' una certezza")

    def test_quando_e_ufficiale_non_si_chiede_piu_niente(self):
        now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        m = self._match(5, 3, status=Match.STATUS_SCHEDULED)
        m.kickoff = now + timedelta(minutes=50); m.save()
        LineupForecast.objects.create(
            match=m, source=LineupForecast.SOURCE_SOFASCORE, official=False,
            refreshed_at=now - timedelta(hours=2))
        self.assertEqual([x.id for x in probable.due_matches(now)], [m.id])
        LineupForecast.objects.filter(match=m).update(official=True)
        self.assertEqual(probable.due_matches(now), [],
                         "continua a chiedere una distinta che e' gia' definitiva")

    def test_sotto_le_due_ore_la_cadenza_si_stringe(self):
        """Senza questa banda l'ultima lettura cadeva a T-2h, un'ora PRIMA che la
        distinta ufficiale esistesse."""
        now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        m = self._match(5, 3, status=Match.STATUS_SCHEDULED)
        m.kickoff = now + timedelta(minutes=80); m.save()
        LineupForecast.objects.create(
            match=m, source=LineupForecast.SOURCE_SOFASCORE,
            refreshed_at=now - timedelta(minutes=20))
        self.assertEqual([x.id for x in probable.due_matches(now)], [m.id])


class RebuildGateTests(_Pitch):
    """Il motore non costa richieste, ma costa query: senza cancello girava per
    ogni partita entro ottantaquattro ore A OGNI MINUTO."""

    def test_se_non_e_cambiato_niente_non_si_ricalcola(self):
        now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        for md in range(1, 4):
            played = self._match(md, md)
            played.kickoff = now - timedelta(days=4 - md)
            played.data_imported_at = now - timedelta(days=4 - md)
            played.save()
            self._played(played, "A", self.squad["A"][:11])
            self._played(played, "B", self.squad["B"][:11])
        nxt = self._match(5, 3, status=Match.STATUS_SCHEDULED)
        nxt.kickoff = now + timedelta(hours=6); nxt.save()

        first = probable.refresh_all(now, fetch=lambda ids: False)
        self.assertEqual(first["built"], 1)
        self.assertEqual(first["unchanged"], 0)

        again = probable.refresh_all(now + timedelta(minutes=1),
                                     fetch=lambda ids: False)
        self.assertEqual(again["built"], 0, "ha ricalcolato senza motivo")
        self.assertEqual(again["unchanged"], 1)

    def test_un_indizio_nuovo_lo_fa_ricalcolare(self):
        now = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        for md in range(1, 4):
            played = self._match(md, md)
            played.kickoff = now - timedelta(days=4 - md)
            played.data_imported_at = now - timedelta(days=4 - md)
            played.save()
            self._played(played, "A", self.squad["A"][:11])
            self._played(played, "B", self.squad["B"][:11])
        nxt = self._match(5, 3, status=Match.STATUS_SCHEDULED)
        nxt.kickoff = now + timedelta(hours=6); nxt.save()
        probable.refresh_all(now, fetch=lambda ids: False)

        LineupEvidence.objects.create(
            competition_season=self.cs, player=self.squad["A"][3], matchday=5,
            kind=LineupEvidence.KIND_INJURY,
            availability=LineupEvidence.AVAIL_OUT, source="sofascore",
            created_at=now + timedelta(seconds=30))
        after = probable.refresh_all(now + timedelta(minutes=1),
                                     fetch=lambda ids: False)
        self.assertEqual(after["built"], 1, "un infortunio nuovo non e' entrato")


class QueryShapeTests(_Pitch):
    """Il costo di leggere una giornata non deve crescere con le partite.

    La prima versione faceva tre query PER PARTITA (trentuno per un turno di
    Serie A): nessuno se ne sarebbe accorto — venti millisecondi — ma una
    crescita lineare che non serve a niente si toglie quando la si vede. Questo
    test è ciò che impedisce di rimetterla senza volerlo.
    """

    def _round(self, md, day):
        """Una giornata giocata da due squadre, con la previsione scritta."""
        played = self._match(md, day)
        self._played(played, "A", self.squad["A"][:11])
        self._played(played, "B", self.squad["B"][:11])
        return played

    def test_una_giornata_costa_quanto_una_partita(self):
        for md in range(1, 4):
            self._round(md, md)
        upcoming = []
        for i, md in enumerate((4, 5, 6)):
            m = self._match(md, 10 + i, status=Match.STATUS_SCHEDULED)
            engine.build_forecast(m)
            upcoming.append(m)

        # Una sola partita e tre insieme: LO STESSO numero di query.
        with self.assertNumQueries(3):
            probable.merged_for_matches(upcoming[:1])
        with self.assertNumQueries(3):
            probable.merged_for_matches(upcoming)

    def test_il_blocco_dice_le_stesse_cose_della_singola(self):
        for md in range(1, 4):
            self._round(md, md)
        m = self._match(4, 10, status=Match.STATUS_SCHEDULED)
        engine.build_forecast(m)
        self.assertEqual(probable.merged_for_matches([m])[m.id], probable.merged(m))

    def test_senza_partite_non_si_interroga_niente(self):
        with self.assertNumQueries(0):
            self.assertEqual(probable.merged_for_matches([]), {})
