"""Uno scrape parziale non deve costare piu' di quello che ha mancato.

L'11/08/2026 tre club su venti sono andati persi per un timeout di Transfermarkt,
e il giro intero ha rinunciato a chiudere le partenze — non 3/20 del lavoro, ma
tutto. La guardia c'era per una ragione giusta (un club non letto, se lo si
trattasse come vuoto, svincolerebbe in massa la sua rosa) ma era globale, e
trattava come ambiguo anche il dato dei diciassette club letti benissimo.

L'asimmetria che questi test fissano:

* per un club **letto**, l'assenza di un giocatore dalla rosa E' una prova che se
  n'e' andato;
* per un club **non letto**, la stessa assenza non e' un fatto suo, e' un buco
  nostro;
* vederlo **altrove** e' una prova positiva, e vale in entrambi i casi.

L'ultimo punto e' quello che copre il caso peggiore: il Milan lo compra
dall'Inter e noi leggiamo solo il Milan. Senza la regola della presenza il
giocatore resterebbe tesserato per due club, e — cosa che nessuno vedrebbe —
verrebbe valutato sulla partita di una delle due, a caso.
"""
from __future__ import annotations

import json
import tempfile
from datetime import date
from io import StringIO
from pathlib import Path
from unittest import mock

import httpx
from django.core.management import call_command
from django.test import TestCase

from realdata.models import (
    Competition, CompetitionSeason, Player, PlayerTeamStint, Season, Team,
    TeamSeason, PROVIDER_SOFASCORE,
)


def _player_row(tm_id: str, name: str, dob: str, position="Centre-Back"):
    return {"tm_id": tm_id, "name": name, "dob": dob, "shirt": "5",
            "position": position, "nationality": ["Italy"],
            "market_value": "€5.00m"}


class Ritentativo(TestCase):
    """Perche' i tre club erano mancati: un tetto fisso e nessun secondo tentativo.

    L'11/08/2026 Transfermarkt stava rispondendo in 10-15 secondi anche alle
    richieste RIUSCITE (di norma sta sotto il secondo); il tetto a venti secondi
    ha tagliato le tre piu' lente. Non era un blocco — ogni risposta arrivata era
    un 200 — ed e' esattamente la categoria di guasto che il tempo ripara.

    Il confine da difendere e' l'altro: si ritenta cio' che il tempo ripara, non
    una risposta. Un 404 ritentato tre volte e' solo la stessa notizia data con
    un minuto di ritardo.
    """

    def _tm(self, attempts=3):
        from realdata.services.scrape_transfermarkt_squads import TM
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # min_delay=0: il throttle e' provato altrove e qui allungherebbe e basta.
        return TM(Path(tmp.name), min_delay=0, jitter=0, logger=lambda *_: None,
                  attempts=attempts)

    def test_un_timeout_passeggero_non_perde_la_pagina(self):
        tm = self._tm()
        ok = httpx.Response(200, text="<html>rosa</html>",
                            request=httpx.Request("GET", "https://x.invalid"))
        tm._client = mock.Mock(get=mock.Mock(side_effect=[
            httpx.ReadTimeout("timeout"), ok]))
        with mock.patch("time.sleep"):
            self.assertEqual(tm._get_html("https://x.invalid"), "<html>rosa</html>")
        self.assertEqual(tm._client.get.call_count, 2)

    def test_dopo_l_ultimo_tentativo_il_guasto_risale(self):
        """Il club si perde comunque, ma il chiamante lo deve sapere: e' lui che
        lo conta come fallito e lo toglie dai club di cui ci si fida."""
        tm = self._tm(attempts=2)
        tm._client = mock.Mock(get=mock.Mock(side_effect=httpx.ReadTimeout("t")))
        with mock.patch("time.sleep"), self.assertRaises(httpx.ReadTimeout):
            tm._get_html("https://x.invalid")
        self.assertEqual(tm._client.get.call_count, 2)

    def test_un_404_non_si_ritenta(self):
        tm = self._tm()
        req = httpx.Request("GET", "https://x.invalid")
        tm._client = mock.Mock(get=mock.Mock(
            return_value=httpx.Response(404, text="", request=req)))
        with mock.patch("time.sleep"), self.assertRaises(httpx.HTTPStatusError):
            tm._get_html("https://x.invalid")
        self.assertEqual(tm._client.get.call_count, 1,
                         "un 404 e' una risposta, non un guasto")

    def test_un_429_si_ritenta(self):
        tm = self._tm()
        req = httpx.Request("GET", "https://x.invalid")
        tm._client = mock.Mock(get=mock.Mock(side_effect=[
            httpx.Response(429, text="", request=req),
            httpx.Response(200, text="ok", request=req)]))
        with mock.patch("time.sleep"):
            self.assertEqual(tm._get_html("https://x.invalid"), "ok")
        self.assertEqual(tm._client.get.call_count, 2)

    def test_senza_guasti_si_chiama_una_volta_sola(self):
        tm = self._tm()
        req = httpx.Request("GET", "https://x.invalid")
        tm._client = mock.Mock(get=mock.Mock(
            return_value=httpx.Response(200, text="ok", request=req)))
        self.assertEqual(tm._get_html("https://x.invalid"), "ok")
        self.assertEqual(tm._client.get.call_count, 1)


class ScrapeParziale(TestCase):

    def setUp(self):
        comp = Competition.objects.create(name="Serie A")
        seas = Season.objects.create(code="2026-2027")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=seas, name="Serie A 2026-2027")
        self.inter = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Inter"))
        self.milan = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Milan"))
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _write_club(self, tm_id: str, name: str, players: list[dict]):
        (self.cache / f"club_{tm_id}.json").write_text(json.dumps({
            "club": {"id": tm_id, "name": name, "slug": name.lower(),
                     "url": f"https://example.invalid/{tm_id}"},
            "players": players,
        }))

    def _squad(self, n: int, first: dict | None = None, prefix="x"):
        """Una rosa plausibile: --min-squad vuole almeno 15 nomi."""
        rows = [first] if first else []
        rows += [_player_row(f"{prefix}{i}", f"Tale {prefix}{i}",
                             f"199{i % 10}-01-0{i % 9 + 1}")
                 for i in range(n - len(rows))]
        return rows

    def _run(self, **kw):
        out = StringIO()
        call_command("import_transfermarkt_squads", cache_dir=str(self.cache),
                     competition_season=self.cs.id, stdout=out, stderr=out, **kw)
        return out.getvalue()

    def _make_player(self, name: str, dob: date, ts: TeamSeason, tm_id: str):
        p = Player.objects.create(full_name=name, date_of_birth=dob,
                                  external_source=PROVIDER_SOFASCORE,
                                  external_id=f"ss{tm_id}")
        PlayerTeamStint.objects.create(player=p, team_season=ts,
                                       start_date=date(2026, 7, 1))
        return p

    # -- il caso che ha rotto ------------------------------------------------

    def test_il_club_letto_chiude_le_partenze_anche_se_un_altro_e_mancato(self):
        """Diciassette club letti non devono pagare per i tre che non lo sono.

        Qui l'Inter non ha risposto (nessun file in cache) e il Milan si': un
        giocatore sparito dalla rosa del Milan e' partito davvero, e il suo
        tesseramento va chiuso. Prima non succedeva.
        """
        uscito = self._make_player("Uscito Dal Milan", date(1995, 3, 3),
                                   self.milan, "999")
        rimasto = self._make_player("Rimasto All Inter", date(1996, 4, 4),
                                    self.inter, "998")
        self._write_club("5", "Milan", self._squad(16, prefix="m"))

        report = self._run()

        uscito.refresh_from_db()
        rimasto.refresh_from_db()
        self.assertEqual(
            PlayerTeamStint.objects.get(player=uscito).end_date, date.today(),
            "il giocatore assente da una rosa LETTA doveva essere chiuso")
        self.assertIsNone(
            PlayerTeamStint.objects.get(player=rimasto).end_date,
            "l'Inter non e' stata letta: la sua rosa non e' una prova di niente")
        self.assertIn("Partenze non controllate per 1 club", report)

    def test_visto_nella_rosa_nuova_chiude_la_vecchia_anche_se_non_letta(self):
        """La prova positiva non chiede completezza.

        Il Milan lo compra dall'Inter e leggiamo solo il Milan. Vederlo in rosa
        rossonera dice che non e' piu' nerazzurro, e lo dice comunque: un
        giocatore ha un club per volta.

        Il controllo partenze e' spento di proposito (``no_close_departures``):
        cosi' l'unica cosa che puo' chiudere il tesseramento nerazzurro e' la
        prova positiva, e il test misura quella e non l'altra macchina.
        """
        comprato = self._make_player("Comprato Dal Milan", date(1997, 5, 5),
                                     self.inter, "777")
        riga = _player_row("777", "Comprato Dal Milan", "1997-05-05")
        self._write_club("5", "Milan", self._squad(16, first=riga, prefix="m"))

        self._run(no_close_departures=True)

        stints = PlayerTeamStint.objects.filter(player=comprato)
        self.assertEqual(stints.count(), 2)
        self.assertEqual(stints.get(team_season=self.inter).end_date,
                         date.today(),
                         "il vecchio club andava chiuso: l'abbiamo visto altrove")
        self.assertIsNone(stints.get(team_season=self.milan).end_date)

    def test_nessun_giocatore_resta_in_due_club(self):
        """L'invariante, verificato dove conta: dopo l'import."""
        from realdata.services import roster_integrity
        comprato = self._make_player("Comprato Dal Milan", date(1997, 5, 5),
                                     self.inter, "777")
        riga = _player_row("777", "Comprato Dal Milan", "1997-05-05")
        self._write_club("5", "Milan", self._squad(16, first=riga, prefix="m"))

        self._run()

        self.assertEqual(roster_integrity.overlapping_stints(self.cs.id), [],
                         f"{comprato} risulta in due club insieme")

    # -- l'errore del fornitore: si riferisce, non si indovina ---------------

    def test_elencato_in_due_rose_lette_non_si_indovina(self):
        """Transfermarkt in finestra di mercato lo tiene in entrambe le rose.

        Qui la prova positiva si annulla: non sappiamo quale delle due valga.
        Chiuderne una a caso sarebbe peggio del problema — si lascia com'e' e lo
        si dice.
        """
        doppio = self._make_player("Doppio Tesserato", date(1998, 6, 6),
                                   self.inter, "555")
        riga = _player_row("555", "Doppio Tesserato", "1998-06-06")
        self._write_club("46", "Inter", self._squad(16, first=riga, prefix="i"))
        self._write_club("5", "Milan", self._squad(16, first=riga, prefix="m"))

        report = self._run()

        aperti = PlayerTeamStint.objects.filter(player=doppio, end_date=None)
        self.assertEqual(aperti.count(), 2, "nessuna delle due andava chiusa")
        self.assertIn("ELENCATI IN DUE ROSE LETTE", report)
        self.assertIn("TESSERAMENTI SOVRAPPOSTI", report)

    def test_la_rosa_implausibile_esce_dal_controllo_partenze(self):
        """Una pagina che e' ancora una pagina e non e' piu' una rosa.

        Il club ha risposto, quindi il file c'e' — ma con otto nomi. Trattarlo
        come completo svincolerebbe due terzi della squadra.
        """
        superstite = self._make_player("Superstite Dell Inter", date(1999, 7, 7),
                                       self.inter, "444")
        self._write_club("46", "Inter", self._squad(8, prefix="i"))
        self._write_club("5", "Milan", self._squad(16, prefix="m"))

        report = self._run()

        self.assertIsNone(
            PlayerTeamStint.objects.get(player=superstite).end_date,
            "una rosa da 8 non e' una prova che gli altri se ne siano andati")
        self.assertIn("Rose implausibili", report)

    def test_lo_scrape_completo_si_comporta_come_prima(self):
        """La rete di sicurezza: a dato completo il risultato non cambia."""
        partito = self._make_player("Partito All Estero", date(1994, 2, 2),
                                    self.inter, "333")
        self._write_club("46", "Inter", self._squad(16, prefix="i"))
        self._write_club("5", "Milan", self._squad(16, prefix="m"))

        report = self._run()

        self.assertEqual(
            PlayerTeamStint.objects.get(player=partito).end_date, date.today())
        self.assertNotIn("Partenze non controllate", report)
        self.assertIn("Tesseramenti sovrapposti     : 0", report)


class MappaturaClub(TestCase):
    """Il 20/11/2026 la pagina del Milan non ha risposto e la rosa dell'Inter e'
    stata importata COME il Milan: 24 trasferimenti e 28 partenze mai avvenuti.

    «Inter Milan» vale 0.62 sia contro «Inter» sia contro «AC Milan». Finche' il
    Milan di TM c'era, si prendeva il Milan a 1.00 e il pareggio non si vedeva;
    senza, l'abbinamento greedy l'ha sciolto dalla parte sbagliata. Tre difese,
    una per test: l'elenco completo, il margine, l'id registrato.
    """

    def setUp(self):
        comp = Competition.objects.create(name="Serie A")
        seas = Season.objects.create(code="2026-2027")
        self.cs = CompetitionSeason.objects.create(
            competition=comp, season=seas, name="Serie A 2026-2027")
        # Il Milan PRIMA dell'Inter, come in produzione: a pari punteggio il
        # vecchio abbinamento sceglieva la prima squadra incontrata.
        self.milan = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="AC Milan"))
        self.inter = TeamSeason.objects.create(
            competition_season=self.cs, team=Team.objects.create(name="Inter"))
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        # Un nerazzurro e un rossonero gia' tesserati, con il loro id TM.
        self.bastoni = self._make_player("Alessandro Bastoni", date(1999, 4, 13),
                                         self.inter, "315853")
        self.maignan = self._make_player("Mike Maignan", date(1995, 7, 3),
                                         self.milan, "182906")

    def _make_player(self, name, dob, ts, tm_id):
        from realdata.models import PlayerAlias
        p = Player.objects.create(full_name=name, date_of_birth=dob,
                                  external_source=PROVIDER_SOFASCORE,
                                  external_id=f"ss{tm_id}")
        PlayerAlias.objects.create(player=p, source="transfermarkt", alias=tm_id)
        PlayerTeamStint.objects.create(player=p, team_season=ts,
                                       start_date=date(2026, 7, 1))
        return p

    def _club(self, tm_id, name):
        return {"id": tm_id, "name": name, "slug": name.lower().replace(" ", "-"),
                "url": f"https://example.invalid/{tm_id}"}

    def _write_list(self, *clubs):
        (self.cache / "clubs.json").write_text(json.dumps(list(clubs)))

    def _write_inter_roster(self, name="Inter Milan"):
        rows = [_player_row("315853", "Alessandro Bastoni", "1999-04-13")]
        rows += [_player_row(f"i{i}", f"Nerazzurro {i}", f"199{i % 10}-02-0{i % 9 + 1}")
                 for i in range(16)]
        (self.cache / "club_46.json").write_text(json.dumps(
            {"club": self._club("46", name), "players": rows}))

    def _run(self, **kw):
        out = StringIO()
        call_command("import_transfermarkt_squads", cache_dir=str(self.cache),
                     competition_season=self.cs.id, stdout=out, stderr=out, **kw)
        return out.getvalue()

    def _open_team(self, player):
        return list(PlayerTeamStint.objects.filter(player=player, end_date=None)
                    .values_list("team_season_id", flat=True))

    def test_la_mattina_del_20_novembre(self):
        """Elenco completo, rosa del Milan mancante: l'Inter resta Inter."""
        inter, milan = self._club("46", "Inter Milan"), self._club("5", "AC Milan")
        self._write_list(inter, milan)
        self._write_inter_roster()

        report = self._run(min_map_score=0.5)

        self.assertEqual(self._open_team(self.bastoni), [self.inter.id],
                         "Bastoni e' stato spostato al Milan")
        self.assertEqual(self._open_team(self.maignan), [self.milan.id],
                         "il Milan non e' stato letto: Maignan non e' partito")
        self.assertIn("TM 'Inter Milan' -> 'Inter'", report)
        # Elenco completo e abbinamento netto: gli id si registrano.
        from realdata.models import TeamAlias
        self.assertEqual(
            dict(TeamAlias.objects.values_list("alias", "team__name")),
            {"46": "Inter", "5": "AC Milan"})

    def test_senza_elenco_il_pareggio_si_salta_non_si_indovina(self):
        """Una cache vecchia, senza clubs.json: il campo e' parziale e «Inter
        Milan» e' a pari merito fra le due squadre. Si salta il club, il resto
        prosegue, e nessun id viene registrato su un campo incompleto."""
        self._write_inter_roster()

        report = self._run(min_map_score=0.5)

        self.assertEqual(self._open_team(self.bastoni), [self.inter.id])
        self.assertEqual(self._open_team(self.maignan), [self.milan.id])
        self.assertIn("CLUB NON ABBINATI (1)", report)
        self.assertIn("nome ambiguo", report)
        from realdata.models import TeamAlias
        self.assertFalse(TeamAlias.objects.exists())
        skipped = json.loads((self.cache / "mapping_skipped.json").read_text())
        self.assertEqual([s["id"] for s in skipped], ["46"])

    def test_l_id_registrato_regge_un_cambio_di_nome(self):
        """TM rinomina il club: con l'id in archivio il nome non conta piu'."""
        from realdata.models import TeamAlias
        TeamAlias.objects.create(team=self.inter.team, source="transfermarkt",
                                 alias="46")
        self._write_inter_roster(name="FC Internazionale Milano")

        report = self._run(min_map_score=0.5)

        self.assertEqual(self._open_team(self.bastoni), [self.inter.id])
        self.assertIn("-> 'Inter' [id 1.00]", report)

    def test_una_squadra_con_id_non_si_prende_per_nome(self):
        """Il Milan ha gia' il suo id (5): «Inter Milan», sconosciuto, non puo'
        prenderselo per somiglianza, anche se il Milan stamattina manca."""
        from realdata.models import TeamAlias
        TeamAlias.objects.create(team=self.milan.team, source="transfermarkt",
                                 alias="5")
        self._write_inter_roster()

        self._run(min_map_score=0.5)

        self.assertEqual(self._open_team(self.bastoni), [self.inter.id])
        self.assertEqual(self._open_team(self.maignan), [self.milan.id])

    def test_un_nome_irriconoscibile_non_ferma_gli_altri(self):
        """Sotto la soglia un club si salta; prima si buttava via l'import intero."""
        from realdata.models import TeamAlias
        TeamAlias.objects.create(team=self.inter.team, source="transfermarkt",
                                 alias="46")
        self._write_inter_roster()
        (self.cache / "club_999.json").write_text(json.dumps(
            {"club": self._club("999", "Pisa Sporting Club"),
             "players": [_player_row("p1", "Pisano Uno", "1990-01-01")]}))

        report = self._run(min_map_score=0.5)

        self.assertIn("CLUB NON ABBINATI (1)", report)
        self.assertIn("Pisa Sporting Club", report)
        self.assertFalse(Player.objects.filter(full_name="Pisano Uno").exists())
        self.assertEqual(self._open_team(self.bastoni), [self.inter.id])
