"""La rosa di una giornata e' quella del suo primo calcio d'inizio.

Il punteggio di una giornata non puo' dipendere dal GIORNO IN CUI L'ADMIN LA
CHIUDE. E' la proprieta' che ``lineup_repair`` dichiara in cima («una giornata
rinviata segna lo stesso che la si concluda in orario o sei settimane dopo») e
che rende confrontabili due leghe che giocano lo stesso calendario.

Qui sotto il caso che la rompe: la formazione EREDITATA — quella di chi non ha
schierato, cioe' il caso normale — viene ripulita sulla rosa di ADESSO
(``team_lines_for_conclusion``), non su quella del blocco. Fra la fine della
giornata e la sua conclusione il mercato lavora, e uno svincolo validato in
quella finestra apre un buco a ritroso in una giornata gia' giocata.
"""
from __future__ import annotations

from datetime import datetime, timezone as dttz

from django.utils import timezone

from datetime import timedelta

from realdata.models import Match, Player, PlayerTeamStint
from vfoot.models import FantasyRosterSlot, SavedLineupSnapshot
from vfoot.services.classic_matchday_scoring import team_lines_for_conclusion
from vfoot.tests_defense_lock import _ClassicRound


class InheritedLineupIsJudgedOnTheRosterAtTheLockTests(_ClassicRound):

    # L'asta e' stata battuta a gennaio, la giornata 22 si gioca a febbraio: la
    # forma di una lega vera. Senza questo i contratti nascono ADESSO, cioe' dopo
    # il turno, e si finisce nella via di fuga di ``owned_for_matchday`` (rosa
    # storica vuota -> vale quella di oggi) invece che nel caso da collaudare.
    AUCTION = datetime(2026, 1, 10, 12, 0, tzinfo=dttz.utc)

    def setUp(self):
        super().setUp()
        FantasyRosterSlot.objects.filter(team=self.team).update(acquired_at=self.AUCTION)

    def _inherit_from_round_21(self):
        """Nessuna formazione per la 22: vale quella della 21 (source=previous)."""
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="21",
            lineup_id=f"team{self.team.id}",
            gk_player_id=str(self.pid["gk"]),
            starter_player_ids=self._xi(*self.OUTFIELD),
            bench_player_ids=self._xi("dbench", "abench"))

    def _lines(self):
        return team_lines_for_conclusion(self.league, self.team, None, 22, {}, None)

    def _release(self, key, when):
        FantasyRosterSlot.objects.filter(
            team=self.team, player_id=self.pid[key]).update(released_at=when)

    def test_the_inherited_lineup_is_whole_when_nothing_moved(self):
        """Il metro: senza mercato di mezzo, undici titolari e nessun posto vuoto."""
        self._inherit_from_round_21()
        starters, _, meta = self._lines()
        self.assertEqual(meta["source"], "previous")
        self.assertEqual(len(starters), 11)
        self.assertEqual(meta["stale"], 0)

    def test_a_release_after_the_kickoff_does_not_reopen_a_played_round(self):
        """IL CASO. La 22 e' stata giocata a febbraio; oggi, prima che l'admin la
        concluda, un'offerta viene validata e svincola un titolare. Era suo
        quando la giornata e' cominciata, quindi la sua riga resta."""
        self._inherit_from_round_21()
        self._release("d1", timezone.now())
        starters, _, meta = self._lines()
        self.assertEqual(
            meta["stale"], 0,
            "uno svincolo successivo al primo calcio d'inizio ha aperto un buco "
            "in una giornata gia' giocata: il punteggio dipende da quando si conclude")
        self.assertEqual(len(starters), 11)

    def test_a_release_before_the_kickoff_still_leaves_the_slot_vacant(self):
        """Lo specchio, perche' il test sopra non passi anche da rotto: chi era
        gia' fuori rosa al blocco non era schierabile, e il posto resta vuoto."""
        self._inherit_from_round_21()
        self._release("d1", datetime(2026, 2, 1, 12, 0, tzinfo=dttz.utc))
        _, _, meta = self._lines()
        self.assertEqual(meta["stale"], 1)


class WhereThereIsNoHistoryTodaysRosterAnswersTests(_ClassicRound):
    """Le due vie di fuga di ``owned_for_matchday``, che sono silenziose e quindi
    vanno inchiodate: senza, un'intera classe di leghe verrebbe scorata su una
    rosa vuota — ogni titolare trattato come venduto, e nessun errore."""

    def _inherit_from_round_21(self):
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="21",
            lineup_id=f"team{self.team.id}",
            gk_player_id=str(self.pid["gk"]),
            starter_player_ids=self._xi(*self.OUTFIELD),
            bench_player_ids=self._xi("dbench", "abench"))

    def test_a_roster_assembled_after_the_round_falls_back_to_today(self):
        """La lega seminata a stagione in corso: i contratti nascono DOPO la 22.
        La risposta storica sarebbe "non aveva nessuno"; quella giusta e' "non lo
        so", e allora vale la rosa di adesso."""
        self._inherit_from_round_21()
        _, _, meta = team_lines_for_conclusion(self.league, self.team, None, 22, {}, None)
        self.assertEqual(meta["stale"], 0)

    def test_a_league_replaying_a_finished_season_never_freezes(self):
        """``enforce_lineup_deadline`` falso vuol dire "stagione gia' finita": li'
        ogni calcio d'inizio e' passato e congelare non vuol dire niente."""
        from vfoot.services import frozen_roster

        self.league.enforce_lineup_deadline = False
        self.league.save(update_fields=["enforce_lineup_deadline"])
        FantasyRosterSlot.objects.filter(team=self.team).update(
            acquired_at=datetime(2026, 1, 10, 12, 0, tzinfo=dttz.utc))
        self.assertEqual(
            frozen_roster.owned_for_matchday(self.league, self.team, 22),
            frozen_roster.owned_now(self.team))


class YouCannotFieldSomeoneWhoArrivedMidRoundTests(_ClassicRound):
    """R4 al salvataggio — un controllo che prima non esisteva affatto.

    La lega e' in modalita' «sempre aperta» (``player``): la formazione della 22
    resta modificabile fino all'ultimo calcio d'inizio, e con un rinvio fino al
    recupero, settimane dopo. In quella finestra il mercato lavora, e senza
    questo controllo si comprava un giocatore e lo si schierava in un turno per
    il resto gia' scorato.
    """

    AUCTION = datetime(2026, 1, 10, 12, 0, tzinfo=dttz.utc)

    def setUp(self):
        super().setUp()
        FantasyRosterSlot.objects.filter(team=self.team).update(acquired_at=self.AUCTION)
        # Il lunedi' non ha ancora giocato: la 22 e' cominciata ma non chiusa.
        now = timezone.now()
        Match.objects.filter(external_id="sat22").update(kickoff=now - timedelta(hours=2))
        Match.objects.filter(external_id="mon22").update(kickoff=now + timedelta(days=1))

    def _newcomer(self, role="MID", when="lun"):
        """Un acquisto validato a giornata gia' cominciata."""
        p = Player.objects.create(full_name="Arrivato", short_name="Arrivato",
                                  classic_role_seed=self.ROLE_SEED[role])
        PlayerTeamStint.objects.create(player=p, team_season=self.ts[when])
        FantasyRosterSlot.objects.create(
            team=self.team, player=p, purchase_price=10, acquired_at=timezone.now())
        return p

    def test_the_roster_the_page_serves_is_the_one_from_the_kickoff(self):
        newcomer = self._newcomer()
        r = self._client().get(f"/api/v1/leagues/{self.league.id}/lineup?matchday=22")
        self.assertEqual(r.status_code, 200)
        served = {row["player_id"] for row in r.data["roster"]}
        self.assertNotIn(newcomer.id, served)
        self.assertIn(self.pid["m4"], served)
        self.assertIsNotNone(r.data["lineup_lock"]["roster_frozen_at"])

    def test_fielding_him_is_refused_and_says_why(self):
        newcomer = self._newcomer()
        r = self._client().post(
            f"/api/v1/leagues/{self.league.id}/lineup/save",
            {"matchday": 22, "gk_player_id": self.pid["gk"],
             "starter_player_ids": self._xi("d1", "d2", "d3", "d4",
                                            "m1", "m2", "m3") + [newcomer.id]
                                   + self._xi("a1", "a2"),
             "bench_player_ids": []},
            format="json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("Arrivato", " ".join(r.json()["errors"]))

    def test_the_one_sold_mid_round_can_still_be_fielded(self):
        """L'altra meta' dell'invariante: chi era tuo al calcio d'inizio resta
        schierabile per QUESTO turno anche se nel frattempo l'hai ceduto."""
        # La formazione della 21, da cui la 22 eredita: senza, sotto la scadenza
        # per giocatore ogni titolare che ha gia' giocato risulta venire "da
        # fuori" e l'invio viene rifiutato in blocco (v. il salvataggio).
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="21",
            lineup_id=f"team{self.team.id}",
            gk_player_id=str(self.pid["gk"]),
            starter_player_ids=self._xi(*self.OUTFIELD),
            bench_player_ids=self._xi("dbench", "abench"))
        FantasyRosterSlot.objects.filter(
            team=self.team, player_id=self.pid["m4"]).update(released_at=timezone.now())
        r = self._client().post(
            f"/api/v1/leagues/{self.league.id}/lineup/save",
            {"matchday": 22, "gk_player_id": self.pid["gk"],
             "starter_player_ids": self._xi(*self.OUTFIELD),
             "bench_player_ids": self._xi("dbench", "abench")},
            format="json")
        self.assertEqual(r.status_code, 200, r.data)


class TheWalletIsNotFrozenWithTheRosterTests(_ClassicRound):
    """IL PORTAFOGLIO NON SI CONGELA CON LA ROSA.

    Segnalato in produzione il 31/08/2026: la pagina Rose dichiarava 138 crediti
    e quella Mercato 124, cioe' proprio i due acquisti validati quel giorno a
    turno gia' cominciato. Il residuo si contava sulla rosa MOSTRATA — quella
    della giornata, dove chi e' appena arrivato non c'e' ancora — e la pagina
    prometteva crediti che il mercato rifiutava di far spendere.

    R4 congela CHI PUO' GIOCARE, non quanto hai in tasca: i contratti sono
    aperti, i crediti sono usciti, e non c'e' nessuna giornata a cui riferire un
    portafoglio.
    """

    AUCTION = datetime(2026, 1, 10, 12, 0, tzinfo=dttz.utc)

    def setUp(self):
        super().setUp()
        FantasyRosterSlot.objects.filter(team=self.team).update(acquired_at=self.AUCTION)
        # La 22 e' cominciata (il sabato ha giocato) ma non e' finita.
        now = timezone.now()
        Match.objects.filter(external_id="sat22").update(kickoff=now - timedelta(hours=2))
        Match.objects.filter(external_id="mon22").update(kickoff=now + timedelta(days=1))

    def _newcomer(self, price=14):
        p = Player.objects.create(full_name="Arrivato", short_name="Arrivato",
                                  classic_role_seed="CEN")
        PlayerTeamStint.objects.create(player=p, team_season=self.ts["lun"])
        FantasyRosterSlot.objects.create(
            team=self.team, player=p, purchase_price=price, acquired_at=timezone.now())
        return p

    def _lineup(self, query=""):
        r = self._client().get(f"/api/v1/leagues/{self.league.id}/lineup?matchday=22{query}")
        self.assertEqual(r.status_code, 200)
        return r.data

    def test_a_purchase_validated_mid_round_leaves_the_page_immediately(self):
        """IL CASO. L'acquisto non e' schierabile in questa giornata, ma e'
        pagato: il residuo deve scendere subito, o la pagina promette crediti che
        il mercato non lascia spendere."""
        before = self._lineup()["budget"]["remaining"]
        self._newcomer(price=14)
        after = self._lineup()
        self.assertEqual(
            after["budget"]["remaining"], before - 14,
            "il residuo si conta sulla rosa schierabile invece che sui contratti")
        self.assertEqual(after["budget"]["spent"], 130 + 14)

    def test_the_wallet_matches_the_market_engine(self):
        """L'unico numero possibile e' quello con cui il mercato giudica le
        offerte: due pagine, un portafoglio."""
        from vfoot.services.auction_engine import team_budgets

        self._newcomer(price=14)
        FantasyRosterSlot.objects.filter(
            team=self.team, player_id=self.pid["m4"]).update(
                released_at=timezone.now(), sale_price=4)
        self.assertEqual(self._lineup()["budget"]["remaining"],
                         team_budgets(self.league)[self.team.id].remaining)

    def test_the_squad_page_asks_for_the_roster_it_owns(self):
        """``?roster=now``: la pagina Rose mostra i contratti — chi e' appena
        arrivato c'e', chi e' stato ceduto no — e la divergenza con la giornata
        viaggia coi nomi, non come regola da dedurre."""
        newcomer = self._newcomer()
        FantasyRosterSlot.objects.filter(
            team=self.team, player_id=self.pid["m4"]).update(released_at=timezone.now())

        owned = self._lineup("&roster=now")
        served = {row["player_id"] for row in owned["roster"]}
        self.assertIn(newcomer.id, served)
        self.assertNotIn(self.pid["m4"], served)
        self.assertEqual(owned["roster_scope"], "now")
        self.assertEqual([r["player_id"] for r in owned["roster_freeze"]["arriving"]],
                         [newcomer.id])
        self.assertEqual([r["player_id"] for r in owned["roster_freeze"]["leaving"]],
                         [self.pid["m4"]])
        self.assertEqual(owned["roster_freeze"]["leaving"][0]["name"], "m4")

    def test_the_formation_page_still_gets_the_matchday_roster(self):
        """Lo specchio: senza il parametro non cambia niente: chi schiera vede
        chi puo' giocare questo turno, che e' la domanda di quella pagina."""
        newcomer = self._newcomer()
        served = {row["player_id"] for row in self._lineup()["roster"]}
        self.assertNotIn(newcomer.id, served)
        self.assertEqual(self._lineup()["roster_scope"], "matchday")

    def test_the_note_speaks_of_the_round_being_played(self):
        """La pagina Rose non chiede una giornata, e la prima del calendario non
        e' una risposta: contro quella, a stagione avanzata, ogni acquisto
        dell'anno risulterebbe «appena arrivato»."""
        from vfoot.models import FantasyMatchday

        old_kickoff = timezone.now() - timedelta(days=7)
        for code, home, away in (("sat21", "sab", "terzo"), ("mon21", "lun", "quarto")):
            Match.objects.create(
                competition_season=self.cs, matchday=21, kickoff=old_kickoff,
                kickoff_provisional=False, home_team=self.ts[home], away_team=self.ts[away],
                status=Match.STATUS_FINISHED, external_source="sofascore", external_id=code)
        FantasyMatchday.objects.create(
            league=self.league, real_competition_season=self.cs, real_matchday=21)
        self._newcomer()

        r = self._client().get(f"/api/v1/leagues/{self.league.id}/lineup?roster=now")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data["roster_freeze"]["matchday"], 22)

    def test_before_the_round_starts_there_is_nothing_to_explain(self):
        """Fuori dalla finestra le due rose coincidono, e la pagina non deve
        spiegare una divergenza che non c'e'."""
        Match.objects.filter(matchday=22).update(kickoff=timezone.now() + timedelta(days=2))
        self._newcomer()
        data = self._lineup("&roster=now")
        self.assertIsNone(data["roster_freeze"])
        self.assertEqual(data["roster_scope"], "now")


class TheWalletCountsWhatIsPromisedToOffersTests(_ClassicRound):
    """Il residuo e' quanto possiedi, il disponibile quanto puoi ancora offrire.

    L'altra meta' della stessa segnalazione: con un'offerta aperta le due pagine
    direbbero di nuovo due numeri diversi — «residuo» qui, «disponibili» la' —
    senza che nessuna delle due dica perche'. Il conto e' quello di
    ``MarketTeamState.available``, e adesso lo fanno tutte e due.
    """

    def test_a_live_offer_reserves_credits_on_the_squad_page_too(self):
        from vfoot.models import MarketOffer, MarketSession

        target = Player.objects.create(full_name="Obiettivo", short_name="Obiettivo",
                                       classic_role_seed="CEN")
        session = MarketSession.objects.create(
            league=self.league, name="Sessione", status=MarketSession.STATUS_OPEN,
            created_by=self.owner)
        MarketOffer.objects.create(
            session=session, team=self.team, target_player=target,
            release_player_id=self.pid["m4"], amount=20, recovery_amount=5,
            role="CEN", status=MarketOffer.STATUS_LEADING,
            deadline_at=timezone.now() + timedelta(hours=24))

        budget = self._client().get(
            f"/api/v1/leagues/{self.league.id}/lineup").data["budget"]
        self.assertEqual(budget["remaining"], 870)
        self.assertEqual(budget["reserved"], 15)
        self.assertEqual(budget["available"], 855)


class ASaveCannotUndoTheRepairTests(_ClassicRound):
    """La giornata NON e' ancora cominciata, quindi R4 non congela niente — ma la
    proprieta' va verificata lo stesso, contro la rosa di adesso.

    Il salvataggio non l'ha mai fatto: verificava scadenza, ruoli, giocatori gia'
    in campo e numero di difensori, mai che i nomi spediti fossero tuoi. Con il
    mercato fermo tutta la giornata (R3) la finestra era stretta; ora che si
    valida a turno in corso e' quella fra il caricamento della pagina e il
    salvataggio, ed e' larga quanto basta.

    Il danno non e' il ritardo: e' che l'invio DISFA la riparazione di R2, e il
    ceduto torna in una formazione che al calcio d'inizio non potra' schierarlo —
    dove verra' contato lo stesso, perche' una formazione spedita non si filtra.
    """

    AUCTION = datetime(2026, 1, 10, 12, 0, tzinfo=dttz.utc)

    def setUp(self):
        super().setUp()
        FantasyRosterSlot.objects.filter(team=self.team).update(acquired_at=self.AUCTION)
        Match.objects.create(
            competition_season=self.cs, matchday=23,
            kickoff=timezone.now() + timedelta(days=3), kickoff_provisional=False,
            home_team=self.ts["sab"], away_team=self.ts["terzo"],
            status=Match.STATUS_SCHEDULED, external_source="sofascore", external_id="sat23")
        SavedLineupSnapshot.objects.create(
            league_id=str(self.league.id), matchday_id="23",
            lineup_id=f"team{self.team.id}",
            gk_player_id=str(self.pid["gk"]),
            starter_player_ids=self._xi(*self.OUTFIELD),
            bench_player_ids=self._xi("dbench", "abench"))

    def _settle(self):
        """L'admin valida: m4 esce, l'acquisto entra. R2 ripara la 23."""
        from vfoot.services import lineup_repair

        newcomer = Player.objects.create(full_name="Arrivato", short_name="Arrivato",
                                         classic_role_seed="CEN")
        PlayerTeamStint.objects.create(player=newcomer, team_season=self.ts["sab"])
        FantasyRosterSlot.objects.filter(
            team=self.team, player_id=self.pid["m4"]).update(released_at=timezone.now())
        FantasyRosterSlot.objects.create(
            team=self.team, player=newcomer, purchase_price=10, acquired_at=timezone.now())
        touched = lineup_repair.swap_player(
            self.league, self.team.id, self.pid["m4"], newcomer.id)
        self.assertEqual(touched, [23], "R2 deve riparare un turno non cominciato")
        return newcomer

    def _save_the_stale_page(self):
        return self._client().post(
            f"/api/v1/leagues/{self.league.id}/lineup/save",
            {"matchday": 23, "gk_player_id": self.pid["gk"],
             "starter_player_ids": self._xi(*self.OUTFIELD),
             "bench_player_ids": self._xi("dbench", "abench")},
            format="json")

    def test_a_stale_page_is_refused_instead_of_undoing_the_repair(self):
        newcomer = self._settle()
        r = self._save_the_stale_page()
        self.assertEqual(r.status_code, 409)
        self.assertIn("ricarica", r.json()["detail"].lower())
        snap = SavedLineupSnapshot.objects.get(matchday_id="23")
        ids = [int(x) for x in snap.starter_player_ids]
        self.assertIn(newcomer.id, ids, "la riparazione di R2 e' stata disfatta")
        self.assertNotIn(self.pid["m4"], ids)

    def test_a_player_who_was_never_yours_is_refused_too(self):
        """L'altra faccia: non solo il ritardo, anche l'invio costruito a mano.
        Prima passava — e veniva scorato."""
        outsider = Player.objects.create(full_name="Estraneo", short_name="Estraneo",
                                         classic_role_seed="CEN")
        PlayerTeamStint.objects.create(player=outsider, team_season=self.ts["sab"])
        r = self._client().post(
            f"/api/v1/leagues/{self.league.id}/lineup/save",
            {"matchday": 23, "gk_player_id": self.pid["gk"],
             "starter_player_ids": self._xi("d1", "d2", "d3", "d4", "m1", "m2", "m3")
                                   + [outsider.id] + self._xi("a1", "a2"),
             "bench_player_ids": []},
            format="json")
        self.assertEqual(r.status_code, 409)
        self.assertIn("Estraneo", " ".join(r.json()["errors"]))

    def test_the_normal_save_still_goes_through(self):
        """Il metro: senza mercato di mezzo si salva come sempre."""
        self.assertEqual(self._save_the_stale_page().status_code, 200)
