"""Le contraddizioni che il modello permette e nessun vincolo puo' vietare.

Tre, e la prima e' quella che ha fatto nascere il modulo: due club nello stesso
momento. Le altre due — la stessa persona scritta due volte, e chi gioca senza
essere in nessuna rosa — hanno la loro sezione piu' sotto.

PERCHE' ESISTE. Una squadra non e' una colonna di ``Player``: e' la relazione
``PlayerTeamStint`` fra giocatore e ``TeamSeason``, valida su un intervallo di
date. Il modello permette quindi di scrivere una cosa che nella realta' non
esiste — lo stesso giocatore tesserato per due club nello stesso giorno — e non
c'e' nessun vincolo di banca dati che lo impedisca, perche' non e' esprimibile:
la stagione non e' una colonna del tesseramento, ci si arriva solo attraversando
``team_season``, e un ``UniqueConstraint`` non attraversa una join.

Il vincolo NON e' stato messo di proposito, e la ragione va protetta se qualcuno
ci ripensa: l'import gira dentro una sola ``transaction.atomic``, e Transfermarkt
in finestra di mercato elenca davvero un giocatore in due rose per qualche ora.
Un vincolo lo trasformerebbe in un ``IntegrityError`` che fa saltare l'INTERA
importazione — scambieremmo un dato sporco e riparabile con la perdita completa
della passata, proprio nel periodo dell'anno in cui il mercato si muove. Quindi
qui si GUARDA e si RIFERISCE, non si corregge.

CHI SE NE ACCORGEREBBE, ALTRIMENTI. Nessuno, ed e' questo il punto.
``match_resolver.player_team_season_id`` risolve il club corrente con un
``.first()`` senza ordinamento: con due tesseramenti aperti non solleva niente,
restituisce uno dei due nell'ordine in cui capita il database. Il giocatore
verrebbe valutato sulla partita sbagliata, in modo non deterministico e
silenzioso. La sovrapposizione non e' disordine estetico: e' un punteggio
attribuito alla partita di un'altra squadra.

L'INTERVALLO E' SEMIAPERTO, [start, end). Chi lascia l'Inter il 15 e firma col
Milan il 15 non si sovrappone: e' un passaggio di consegne pulito, ed e'
esattamente come lo scrive l'import (``end_date = as_of`` sul vecchio,
``start_date = as_of`` sul nuovo). Trattarlo come chiuso a destra farebbe gridare
il controllo a ogni singolo trasferimento, che e' il modo piu' rapido per farlo
spegnere. Una data nulla e' un estremo aperto: ``start`` nullo = da sempre,
``end`` nullo = tuttora.

DENTRO UNA SOLA EDIZIONE. Il confronto e' limitato a una ``CompetitionSeason``.
Appartenere insieme al Milan in Serie A e al Milan in Champions non e' una
contraddizione, e nemmeno esserlo in due edizioni diverse dello stesso
campionato: quella sarebbe una stagione vecchia rimasta aperta, un problema
diverso e con un rimedio diverso. Qui si risponde a una domanda sola, che e' la
domanda che il mercato puo' sporcare.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from realdata.models import PlayerTeamStint


@dataclass(frozen=True)
class Overlap:
    """Due tesseramenti dello stesso giocatore che si sovrappongono nel tempo."""

    player_id: int
    player_name: str
    first: tuple[str, date | None, date | None]   # (club, inizio, fine)
    second: tuple[str, date | None, date | None]

    def describe(self) -> str:
        def span(s):
            club, a, b = s
            return f"{club} ({a or 'da sempre'} -> {b or 'tuttora'})"
        return f"{self.player_name}: {span(self.first)} e {span(self.second)}"


def _intersects(a_start, a_end, b_start, b_end) -> bool:
    """Gli intervalli semiaperti [a_start, a_end) e [b_start, b_end) si toccano?

    Un estremo ``None`` e' infinito dalla sua parte. Il confronto e' stretto (``<``)
    su entrambi i lati: e' quello che rende il subentro del giorno stesso un
    passaggio pulito invece che una sovrapposizione di durata zero.
    """
    if a_start is not None and b_end is not None and a_start >= b_end:
        return False
    if b_start is not None and a_end is not None and b_start >= a_end:
        return False
    return True


def _contains(start, end, day: date) -> bool:
    """L'intervallo semiaperto [start, end) contiene ``day``?"""
    return ((start is None or start <= day)
            and (end is None or day < end))


def overlapping_stints(competition_season_id: int, *,
                       active_on: date | None = None,
                       limit: int | None = None) -> list[Overlap]:
    """Ogni coppia di tesseramenti sovrapposti nell'edizione, la piu' recente prima.

    ``active_on`` tiene solo le sovrapposizioni ancora IN CORSO in quel giorno, ed
    e' quello che passano i due chiamanti automatici. La ragione e' misurata, non
    di gusto: al 12/08/2026 la produzione conteneva una sovrapposizione sola,
    lunga un giorno, gia' chiusa da se' — l'artefatto dello scrape parziale
    dell'11 agosto. Segnalarla ogni mattina per sempre significherebbe insegnare a
    saltare la riga, e con lei quella vera del giorno in cui capitera'.

    Senza ``active_on`` la funzione risponde su tutta la storia: e' la forma
    giusta per un controllo a mano, dove la domanda e' «e' mai successo?» e non
    «sta succedendo?».

    Il confronto e' a coppie ma il costo non e' quadratico sul totale: si raggruppa
    per giocatore, e un giocatore ha una manciata di tesseramenti per stagione. Il
    caso normale — nessuno ne ha piu' di uno — non confronta nulla.
    """
    rows = (PlayerTeamStint.objects
            .filter(team_season__competition_season_id=competition_season_id)
            .select_related("player", "team_season__team")
            .order_by("player_id", "start_date"))

    by_player: dict[int, list[PlayerTeamStint]] = {}
    for st in rows:
        by_player.setdefault(st.player_id, []).append(st)

    found: list[Overlap] = []
    for pid, stints in by_player.items():
        if len(stints) < 2:
            continue
        for i, a in enumerate(stints):
            for b in stints[i + 1:]:
                if a.team_season_id == b.team_season_id:
                    # Due righe per lo stesso club: non e' un doppio tesseramento,
                    # e' un ritorno (prestito rientrato) o una riga duplicata. Non
                    # e' la contraddizione che questo controllo cerca.
                    continue
                if not _intersects(a.start_date, a.end_date,
                                   b.start_date, b.end_date):
                    continue
                if active_on is None or (
                        _contains(a.start_date, a.end_date, active_on)
                        and _contains(b.start_date, b.end_date, active_on)):
                    found.append(Overlap(
                        player_id=pid,
                        player_name=a.player.full_name,
                        first=(str(a.team_season.team), a.start_date, a.end_date),
                        second=(str(b.team_season.team), b.start_date, b.end_date),
                    ))

    # Il piu' recente per primo: una sovrapposizione aperta oggi conta piu' di una
    # chiusa a novembre, e chi legge il rapporto guarda le prime righe.
    found.sort(key=lambda o: (o.first[1] or date.min, o.second[1] or date.min),
               reverse=True)
    return found[:limit] if limit else found


# -- identita' spezzata in due righe -------------------------------------------
#
# L'ALTRA contraddizione che il modello permette e che nessun vincolo puo'
# vietare: la stessa persona scritta due volte, una per fornitore.
#
# Come nasce. L'import rose di Transfermarkt crea la riga di chi in Serie A non
# ha ancora giocato — e quella riga e' quella VERA per l'applicazione: ha il
# tesseramento, il valore, il ruolo congelato, e se qualcuno l'ha comprato lo
# slot in rosa. Poi il giocatore esordisce, SofaScore lo manda dentro col suo id,
# e l'adozione per identita' deve riconoscerlo. Quando non ci riesce conia una
# SECONDA riga, e da quell'istante le due meta' non si parlano piu': la meta'
# comprata non ha nessuna presenza e resta senza voto per sempre, la meta' che
# gioca non e' in nessun listone e non e' di nessuno.
#
# Perche' serve un GUARDIANO e non basta l'adozione. L'adozione e' un'euristica
# su dati di due fornitori che non concordano — Giacomo Calo' e' nato il 5
# febbraio su Transfermarkt e il 2 maggio su SofaScore, giorno e mese scambiati —
# e un'euristica prudente sbaglia per difetto: preferisce lasciare un doppione
# piuttosto che fondere due persone diverse, che e' irreversibile. Il doppione
# che ne resta non fallisce in modo rumoroso: nessuna eccezione, nessuna riga
# rossa, solo un giocatore che non prende mai voto. Questo e' l'unico posto da
# cui qualcuno puo' venirlo a sapere.


@dataclass(frozen=True)
class SplitIdentity:
    """Due righe ``Player`` che sono, con ogni evidenza, la stessa persona."""

    keeper_id: int          # la riga del listone: tesserata, comprabile, comprata
    stray_id: int           # la riga del fornitore delle partite: gioca, non esiste
    name: str
    evidence: str           # su che cosa combaciano
    club: str
    appearances: int        # quante partite sono finite sulla riga sbagliata

    def describe(self) -> str:
        return (f"{self.name} ({self.club}): id {self.keeper_id} e' nel listone, "
                f"id {self.stray_id} ha giocato {self.appearances} partite "
                f"[{self.evidence}]")


def _norm_names(player) -> set[str]:
    from realdata.services.identity import norm_name
    return {norm_name(player.full_name), norm_name(player.short_name)} - {""}


def split_identities(provider: str = "sofascore") -> list[SplitIdentity]:
    """Le identita' spezzate: una riga che gioca, una riga che e' tesserata.

    Si cerca DENTRO la rosa del club per cui la riga del fornitore e' scesa in
    campo, e li' basta una delle tre prove — il nome (i due fornitori scrivono
    date diverse), la data di nascita (i due fornitori scrivono nomi diversi:
    'Manga Foe Ondoa' contro 'Foe Ondoa'), o il cognome coi suoi due testimoni
    quando ne' il nome intero ne' la data sono scritti bene da entrambi ('Rahim
    Alhassane' contro 'Abdel Rahim'). E' la stessa regola dell'adozione in
    ``sofascore_adapter._adopt_by_identity``, di proposito: cosi' questo elenco e'
    esattamente cio' che l'adozione ha mancato, e non un secondo criterio che
    contraddice il primo. Le due vanno cambiate INSIEME, ed e' per questo che la
    prova del cognome sta in ``identity.matches_by_surname`` e non qui.

    La corrispondenza dev'essere UNICA nella rosa. Due omonimi, o due nati lo
    stesso giorno, e la coppia non si riporta: qui si guarda, ma chi legge fonde,
    e una fusione sbagliata non si disfa.
    """
    from realdata.models import MatchAppearance, Player, PlayerAlias
    from realdata.services.identity import (is_placeholder_dob,
                                            is_synthetic_sofascore_id,
                                            matches_by_surname)

    played: dict[int, set[int]] = {}
    counts: dict[int, int] = {}
    for pid, ts_id in (MatchAppearance.objects
                       .values_list("player_id", "team_season_id")):
        played.setdefault(pid, set()).add(ts_id)
        counts[pid] = counts.get(pid, 0) + 1

    squads: dict[int, list] = {}
    clubs: dict[int, str] = {}
    for st in PlayerTeamStint.objects.select_related("player", "team_season__team"):
        squads.setdefault(st.team_season_id, []).append(st.player)
        clubs[st.team_season_id] = str(st.team_season.team)

    # Chi ha gia' un id del fornitore suo non e' una meta' di niente.
    settled = {pid for pid, alias in
               PlayerAlias.objects.filter(source=provider)
               .values_list("player_id", "alias")
               if not is_synthetic_sofascore_id(alias)}

    found: list[SplitIdentity] = []
    for stray in Player.objects.filter(external_source=provider):
        if stray.id not in played:
            continue
        names = _norm_names(stray)
        for ts_id in played[stray.id]:
            squad = [p for p in squads.get(ts_id, [])
                     if p.external_source != provider and p.id not in settled]
            cands = [p for p in squad if _norm_names(p) & names]
            evidence = "stesso nome nella stessa rosa"
            if not cands and stray.date_of_birth and not is_placeholder_dob(stray.date_of_birth):
                cands = [p for p in squad if p.date_of_birth == stray.date_of_birth]
                evidence = "stessa data di nascita nella stessa rosa"
            if not cands:
                cands = [p for p in squad
                         if matches_by_surname(
                             (stray.full_name, stray.short_name), stray.date_of_birth,
                             (p.full_name, p.short_name), p.date_of_birth)]
                evidence = "stesso cognome e iniziale nella stessa rosa"
            if len(cands) == 1:
                found.append(SplitIdentity(
                    keeper_id=cands[0].id, stray_id=stray.id,
                    name=cands[0].full_name, evidence=evidence,
                    club=clubs.get(ts_id, "?"),
                    appearances=counts.get(stray.id, 0)))
                break
    found.sort(key=lambda s: (-s.appearances, s.name))
    return found


# -- chi gioca senza esistere ---------------------------------------------------
#
# La TERZA contraddizione, e la piu' larga delle tre: qualcuno e' sceso in campo
# in un'edizione di cui conosciamo le rose, e in nessuna di quelle rose c'e'.
#
# PERCHE' NON BASTA ``split_identities``. Quel controllo risponde a una domanda
# stretta — «di chi e' la meta' che gioca?» — e per rispondere deve riconoscere
# il gemello: nome, data, o cognome coi suoi testimoni. Quando nessuna delle tre
# prove attacca, tace, e ha taciuto davvero: Rahim Alhassane ha giocato due
# partite col Bologna, una da titolare per novanta minuti, e l'elenco degli
# spezzati era vuoto. Se ne e' accorto un utente da uno screenshot.
#
# Questo controllo non chiede di riconoscere nessuno. Chiede una cosa sola, che
# e' un fatto e non un'euristica: **ha giocato, e non e' in nessuna rosa**. Non
# dice di chi sia — non lo sa — dice che c'e' un buco. E' il guardiano che regge
# quando l'euristica cade, ed e' per questo che i due si SOVRAPPONGONO di
# proposito: chi e' spezzato e riconoscibile compare in tutte e due le righe, una
# volta col rimedio pronto e una volta in mezzo ai suoi simili.
#
# IL GUARDIANO DEL GUARDIANO: le rose devono COPRIRE chi gioca. Su un'edizione di
# cui non abbiamo le rose l'assenza non dice niente del giocatore, e il controllo
# direbbe soltanto, con enorme sicurezza, che le rose non ci sono: in produzione
# la Serie A 25-26 da' 772 orfani su 772.
#
# Non basta pero' chiedere che UN tesseramento esista, ed e' l'errore che questo
# controllo ha fatto per primo: una rosa PARZIALE passa quella soglia e allaga il
# rapporto. Nel database di sviluppo la 25-26 ne ha 536 su 772, e il controllo
# tirava dentro Guendouzi con 1430 minuti e Asllani con 1135 — gente che ha
# giocato mezza stagione in Serie A, non meta' spezzate.
#
# La misura che separa i due casi (31/08/2026, quota di chi ha giocato ed e'
# anche tesserato):
#
#     rose complete    100,0% (sviluppo 26-27) e 97,0% (produzione 26-27)
#     rosa parziale     68,9% (sviluppo 25-26)
#     nessuna rosa       0,0% (produzione 25-26, e la 2015/2016)
#
# Il 90% sta in mezzo al burrone fra 97 e 69, con margine da tutte e due le parti.
# Sotto quella quota l'edizione non si guarda affatto e non si dice niente: il
# canarino non allarma su cio' che non puo' vedere, e la 25-26 senza rose e' una
# scelta, non un guasto.
ROSTER_COVERAGE_FLOOR = 0.90
#
# COSA E' RUMORE, misurato sulla 26-27 al 31/08/2026: 16 orfani in dieci giorni,
# di cui quattordici mai entrati in campo — ragazzi delle giovanili messi in
# distinta e mai usati — e due entrati per 9 e 2 minuti. Nessuno titolare.
#
# IL GIALLO E' PER IL TITOLARE, e la prima versione sbagliava di un gradino: dava
# il giallo a chi avesse messo piede in campo, e quindi lo avrebbe dato a Zulevic
# per nove minuti e a Kulla per due. Il controllo contro il listone di
# fantacalcio.it (Quotazioni 26-27, 526 quotati) dice che quei due non sono un
# buco di nessuno: **sedici orfani su sedici mancano anche li'**, e la nostra rosa
# e' gia' un soprainsieme della loro (598 tesserati contro 526 quotati). Allarmare
# per una comparsata dalla panchina vuol dire allarmare per il funzionamento
# normale del campionato — v. [[roster-boundary-primavera]].
#
# Quello che distingueva Alhassane non erano i minuti: era essere in DISTINTA DA
# TITOLARE in una partita di Serie A senza stare in nessuna rosa. Una squadra non
# schiera dal primo minuto un ragazzo che non ha tesserato, e infatti Alhassane
# non lo era: era tesserato eccome, sotto un'altra riga. Il titolare e' una forma
# che la chiamata dalle giovanili non produce, e per questo fa da soglia meglio di
# qualunque numero di minuti scelto a tavolino.
#
# Chi entra dalla panchina resta contato in ``info``, con nome e minuti: se una
# meta' spezzata giocasse solo da subentrato, la riga la nomina lo stesso e la sua
# rete e' ``split_identities``, che ora ha anche la prova del cognome.


@dataclass(frozen=True)
class Unrostered:
    """Uno che e' sceso in campo in un'edizione di cui conosciamo le rose."""

    player_id: int
    name: str
    club: str
    season: str
    appearances: int
    minutes: int
    started: bool

    @property
    def played(self) -> bool:
        """Ha messo piede in campo, o e' solo stato in distinta?

        NON e' la soglia del giallo — quella e' ``started``. Serve a raccontare la
        riga: chi e' entrato per due minuti va detto, senza svegliare nessuno.
        """
        return self.minutes > 0 or self.started

    def describe(self) -> str:
        campo = (f"{self.minutes}'" + (" da titolare" if self.started else "")
                 if self.played else "mai entrato")
        return (f"{self.name} ({self.club}, id {self.player_id}): "
                f"{self.appearances} presenze, {campo}")


def unrostered_players(*, since, coverage_floor: float = ROSTER_COVERAGE_FLOOR,
                       limit: int | None = None) -> list[Unrostered]:
    """Chi ha giocato dal ``since`` in poi senza essere in nessuna rosa.

    La finestra guarda le PARTITE, non l'esordio: un ragazzo chiamato una volta
    in agosto sparisce da solo dopo dieci giorni, mentre una meta' spezzata —
    che continua a giocare ogni settimana — resta accesa finche' non la si
    ripara. E' la differenza fra un elenco che si svuota e uno che cresce tutto
    l'anno finche' nessuno lo legge piu'.

    La COPERTURA invece si misura su tutta l'edizione e non sulla finestra: e' una
    proprieta' dell'import rose, non del turno, e chiederla a dieci giorni di
    partite la farebbe ballare con chi e' sceso in campo quella settimana.

    Ordinati per minuti giocati: la prima riga e' sempre quella che conta.
    """
    from realdata.models import CompetitionSeason, MatchAppearance

    found: list[Unrostered] = []
    for cs in CompetitionSeason.objects.all():
        rostered = set(PlayerTeamStint.objects
                       .filter(team_season__competition_season=cs)
                       .values_list("player_id", flat=True))
        if not rostered:
            continue          # senza rose l'assenza non dice niente
        played = set(MatchAppearance.objects
                     .filter(match__competition_season=cs)
                     .values_list("player_id", flat=True))
        if not played:
            continue
        if 1 - len(played - rostered) / len(played) < coverage_floor:
            continue          # rose parziali: il buco e' nell'import, non nei nomi
        agg: dict[int, dict] = {}
        for a in (MatchAppearance.objects
                  .filter(match__competition_season=cs, match__kickoff__gt=since)
                  .exclude(player_id__in=rostered)
                  .select_related("player", "team_season__team")):
            d = agg.setdefault(a.player_id, {
                "name": a.player.full_name or a.player.short_name,
                "club": str(a.team_season.team),
                "pres": 0, "min": 0, "tit": False})
            d["pres"] += 1
            d["min"] += a.minutes_played or 0
            d["tit"] = d["tit"] or a.is_starter
        for pid, d in agg.items():
            found.append(Unrostered(
                player_id=pid, name=d["name"], club=d["club"], season=str(cs),
                appearances=d["pres"], minutes=d["min"], started=d["tit"]))

    # Il titolare per primo, e non perche' ha piu' minuti: e' l'unica riga che
    # alza il verdetto, e chi legge il rapporto guarda la prima.
    found.sort(key=lambda u: (not u.started, -u.minutes, -u.appearances, u.name))
    return found[:limit] if limit else found
