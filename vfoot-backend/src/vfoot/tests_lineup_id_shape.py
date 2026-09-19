"""Gli id di una formazione sono NUMERI, chiunque la scriva.

IL DIFETTO CHE HA FATTO SCRIVERE QUESTO FILE (19/09/2026, segnalato da un utente
della lega «Quelli che il fanta»). La riparazione del mercato — R2, il pezzo che
rimette l'acquistato al posto del ceduto — riscriveva l'undici convertendo
l'intera lista in stringhe. Nel database la giornata 5 di quella squadra aveva
dieci titolari come ``'888'`` e il portiere come ``598``, perche' il portiere
viaggia in un campo a parte. A schermo: un giocatore solo in campo, il contatore
che diceva 11/11 accanto a «ne hai 1», e l'allenatore che non poteva piu'
schierare a giornata in corso.

PERCHE' NESSUN TEST L'HA PRESO, che e' la parte da non ripetere:

* **Il server perdona.** Una formazione viene riletta in una ventina di punti, e
  ognuno di quei punti fa ``int(x)``. Il punteggio, il live, il tabellino: tutti
  giusti, con i dati storti. Non c'era nessun comportamento del server da cui il
  difetto si vedesse.
* **I test perdonavano come lui.** Le due prove che toccavano una formazione
  riparata leggevano ``[int(x) for x in snap.starter_player_ids]``. Convertire
  nell'asserzione e' mettersi la stessa benda del codice sotto esame: qualunque
  forma avesse avuto quella lista, quelle prove sarebbero passate.
* **L'unico lettore severo non e' il server.** E' il client, che cerca i
  titolari in una mappa con chiavi numeriche, e nessun test guardava la FORMA di
  cio' che l'API gli spedisce — solo i nomi che conteneva.

Da qui le tre famiglie di prove qui sotto: la forma che il DATABASE accetta
(``PlayerIdListField``, che la impone a monte di ogni chiamante), la forma che
ogni SCRITTORE produce, e la forma che l'API CONSEGNA. La prima rende il difetto
impossibile da riscrivere; le altre due lo rendono visibile se qualcuno
aggirasse la prima.
"""
from __future__ import annotations

from vfoot.models import SavedLineupSnapshot
from vfoot.services import lineup_baseline, lineup_repair
from vfoot.tests_defense_lock import _ClassicRound
from vfoot.tests_frozen_roster import _RepairedRound


def _shapes(value) -> set:
    return {type(x).__name__ for x in value}


class TheFieldImposesTheShapeTests(_ClassicRound):
    """Il livello che non si puo' aggirare: qualunque scrittore, qualunque via."""

    def _fetch(self):
        return SavedLineupSnapshot.objects.get(lineup_id=f"team{self.team.id}")

    def test_strings_written_by_anybody_come_back_as_numbers(self):
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{self.team.id}",
            gk_player_id=str(self.pid["gk"]),
            starter_player_ids=[str(x) for x in self._xi(*self.OUTFIELD)],
            bench_player_ids=[str(x) for x in self._xi("dbench", "abench")])
        snap = self._fetch()
        self.assertEqual(snap.starter_player_ids, self._xi(*self.OUTFIELD))
        self.assertEqual(snap.bench_player_ids, self._xi("dbench", "abench"))

    def test_the_object_in_memory_says_the_same_as_the_database(self):
        """Senza questo l'invariante varrebbe solo dopo un giro di andata e
        ritorno, e chi salva e rilegge l'attributo vedrebbe un'altra cosa."""
        snap = SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="22",
            lineup_id=f"team{self.team.id}",
            starter_player_ids=["7", 8, "9"], bench_player_ids=[])
        self.assertEqual(snap.starter_player_ids, [7, 8, 9])
        self.assertEqual(snap.starter_player_ids, self._fetch().starter_player_ids)

    def test_a_queryset_update_is_normalised_too(self):
        """La via che salta ``pre_save``. E' proprio come la riparazione del
        mercato potrebbe essere riscritta domani."""
        self._save_snapshot()
        SavedLineupSnapshot.objects.filter(lineup_id=f"team{self.team.id}").update(
            starter_player_ids=[str(x) for x in self._xi(*self.OUTFIELD)])
        self.assertEqual(self._fetch().starter_player_ids, self._xi(*self.OUTFIELD))

    def test_the_prototype_ids_are_left_alone(self):
        """Questa tabella serve due mondi. Gli id sintetici del prototipo
        (``api/data_builders``) non sono numeri e non devono diventarlo: se
        passassero da qui mutilati, il difetto sarebbe solo cambiato di posto."""
        snap = SavedLineupSnapshot.objects.create(
            league_id="L1", matchday_id="MD24", lineup_id="LU-1",
            starter_player_ids=["P101", "P102"], bench_player_ids=[])
        snap.refresh_from_db()
        self.assertEqual(snap.starter_player_ids, ["P101", "P102"])


class EveryWriterProducesNumbersTests(_RepairedRound):
    """Le tre vie per cui una formazione finisce nel database, una per una.

    Elencarle non e' pedanteria: il difetto e' nato perche' UNA di queste tre
    scriveva diverso dalle altre, e nessuna prova le confrontava.

    Sulla 23, non sulla 22: la 22 di ``_ClassicRound`` si e' giocata a febbraio,
    quindi il salvataggio la rifiuta e la riparazione non la tocca. Le due prove
    sarebbero passate senza eseguire cio' che devono misurare."""

    def test_the_save_endpoint(self):
        r = self._client().post(
            f"/api/v1/leagues/{self.league.id}/lineup/save",
            {"matchday": 23, "gk_player_id": self.pid["gk"],
             "starter_player_ids": [str(x) for x in self._xi(*self.OUTFIELD)],
             "bench_player_ids": [str(x) for x in self._xi("dbench", "abench")]},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)
        snap = SavedLineupSnapshot.objects.get(matchday_id="23")
        self.assertEqual(_shapes(snap.starter_player_ids), {"int"})
        self.assertEqual(_shapes(snap.bench_player_ids), {"int"})

    def test_the_baseline_writer(self):
        snap = lineup_baseline.write_baseline(self.league, self.team, 23)
        self.assertEqual(_shapes(snap.starter_player_ids), {"int"})
        self.assertEqual(_shapes(snap.bench_player_ids), {"int"})

    def test_the_market_repair_removing_a_player(self):
        """Lo svincolo senza acquisto: l'altro ramo di ``swap_player``, quello
        che accorcia la lista invece di sostituirci dentro."""
        touched = lineup_repair.swap_player(
            self.league, self.team.id, self.pid["m4"], None)
        self.assertEqual(touched, [23], "la riparazione non ha toccato niente")
        snap = SavedLineupSnapshot.objects.get(matchday_id="23")
        self.assertEqual(_shapes(snap.starter_player_ids), {"int"})
        self.assertNotIn(self.pid["m4"], snap.starter_player_ids)


class TheMarketRepairKeepsTheShapeTests(_RepairedRound):
    """IL CASO ESATTO CHE E' ANDATO IN PRODUZIONE: acquisto valida, l'entrante
    prende il posto dell'uscente negli undici, la giornata non e' cominciata."""

    def test_the_repaired_eleven_is_still_a_list_of_numbers(self):
        newcomer = self._settle()
        snap = SavedLineupSnapshot.objects.get(matchday_id="23")
        self.assertEqual(
            _shapes(snap.starter_player_ids), {"int"},
            f"la riparazione ha cambiato il tipo degli id: {snap.starter_player_ids!r}")
        self.assertIn(newcomer.id, snap.starter_player_ids)


class TheApiDeliversNumbersTests(_RepairedRound):
    """LA FORMA DI CIO' CHE IL CLIENT RICEVE, che e' il lettore severo.

    Si parte da una riga volutamente storta — scritta aggirando il campo — per
    due ragioni: nel database di produzione le righe scritte prima del campo
    esistono ancora, e un contratto che vale solo finche' i dati sono puliti non
    e' un contratto."""

    def _dirty_the_row(self):
        snap = SavedLineupSnapshot.objects.get(matchday_id="23")
        # Sotto il campo, con una UPDATE cruda: e' l'unico modo di rimettere in
        # piedi lo stato del 18/09, e serve che ci sia.
        from django.db import connection
        import json
        with connection.cursor() as c:
            c.execute(
                "UPDATE vfoot_savedlineupsnapshot SET starter_player_ids = %s, "
                "bench_player_ids = %s WHERE id = %s",
                [json.dumps([str(x) for x in snap.starter_player_ids]),
                 json.dumps([str(x) for x in snap.bench_player_ids]),
                 snap.id])
        return snap

    def test_the_eleven_is_numbers_even_from_a_row_written_before_the_field(self):
        self._dirty_the_row()
        saved = self._client().get(
            f"/api/v1/leagues/{self.league.id}/lineup?matchday=23").json()["saved_lineup"]
        self.assertEqual(_shapes(saved["starter_player_ids"]), {"int"})
        self.assertEqual(_shapes(saved["bench_player_ids"]), {"int"})

    def test_the_eleven_the_page_gets_can_be_found_in_the_roster_it_gets(self):
        """LA GIUNZIONE CHE SI ERA ROTTA, detta come la vede l'allenatore: la
        pagina incrocia i titolari con la rosa, e se l'incrocio non si chiude il
        campo resta vuoto. Nessun errore da nessuna parte — ed e' per questo che
        va scritta come prova, invece di fidarsi dei tipi."""
        self._dirty_the_row()
        d = self._client().get(
            f"/api/v1/leagues/{self.league.id}/lineup?matchday=23").json()
        roster = {p["player_id"] for p in d["roster"]}
        xi = [d["saved_lineup"]["gk_player_id"], *d["saved_lineup"]["starter_player_ids"]]
        self.assertEqual(len(xi), 11)
        self.assertEqual([p for p in xi if p not in roster], [],
                         "un titolare non si ritrova nella rosa: il campo resterebbe vuoto")
