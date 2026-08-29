"""Contraddizioni nella storia dei tesseramenti: due club nello stesso momento.

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
    campo, e li' basta una delle due prove — il nome (i due fornitori scrivono
    date diverse) o la data di nascita (i due fornitori scrivono nomi diversi:
    'Manga Foe Ondoa' contro 'Foe Ondoa'). E' la stessa regola dell'adozione in
    ``sofascore_adapter._adopt_by_identity``, di proposito: cosi' questo elenco e'
    esattamente cio' che l'adozione ha mancato, e non un secondo criterio che
    contraddice il primo.

    La corrispondenza dev'essere UNICA nella rosa. Due omonimi, o due nati lo
    stesso giorno, e la coppia non si riporta: qui si guarda, ma chi legge fonde,
    e una fusione sbagliata non si disfa.
    """
    from realdata.models import MatchAppearance, Player, PlayerAlias
    from realdata.services.identity import is_placeholder_dob, is_synthetic_sofascore_id

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
            if len(cands) == 1:
                found.append(SplitIdentity(
                    keeper_id=cands[0].id, stray_id=stray.id,
                    name=cands[0].full_name, evidence=evidence,
                    club=clubs.get(ts_id, "?"),
                    appearances=counts.get(stray.id, 0)))
                break
    found.sort(key=lambda s: (-s.appearances, s.name))
    return found
