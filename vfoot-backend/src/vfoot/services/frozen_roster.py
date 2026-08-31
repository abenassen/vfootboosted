"""La rosa di una giornata: chi era sotto contratto al suo primo calcio d'inizio.

«La rosa» ha smesso di essere una domanda con una risposta sola, e questo modulo
e' il posto dove la seconda risposta ha un nome.

* **La rosa di adesso** — i contratti aperti — e' quella del mercato, dell'asta,
  degli scambi, del budget e della bacheca. Chi chiede "cosa possiede questa
  squadra" chiede questa, e continua a leggerla come sempre
  (``released_at__isnull=True``).
* **La rosa di una giornata** — i contratti aperti al suo primo calcio d'inizio —
  e' quella della formazione e del punteggio. Chi chiede "chi puo' scendere in
  campo in questo turno", o "chi c'era quando questo turno e' cominciato", chiede
  QUESTA, ed e' l'unica corretta dal momento in cui il turno comincia.

PERCHE' NE SERVONO DUE. Finche' il mercato restava fermo per tutta la giornata
(R3) le due coincidevano sempre, e una sola bastava. Con le validazioni ammesse a
turno iniziato la rosa cambia sotto una giornata che si sta giocando, e allora
«chi puo' giocare la 5» e «chi possiedi oggi» sono due insiemi diversi per
qualche giorno al turno.

L'ISTANTE E' IL PRIMO CALCIO D'INIZIO DEL TURNO, in tutte e tre le modalita' di
scadenza. Non la scadenza della singola squadra (modalita' ``own``) e non quella
del singolo giocatore (``player``): quelle dicono FINO A QUANDO SI SALVA, che e'
un'altra domanda: R1. Qui si risponde a CHI E' SCHIERABILE, e tenerlo uno solo
per tutta la lega e' cio' che rende la regola spiegabile in una riga — «la rosa
di inizio giornata» — e verificabile con un canarino solo
(``_warn_about_unrepaired_lineups`` misura gia' esattamente questo confine).

L'INVARIANTE CHE NE ESCE, e che prima non esisteva: in una giornata ogni
giocatore e' schierabile da AL PIU' UNA squadra, quella che lo aveva al primo
calcio d'inizio. Chi lo cede lo tiene per quel turno, chi lo prende lo ha dal
successivo, chi era svincolato in quel momento non e' di nessuno. Vale identico
per gli scambi di lega, e senza doverli trattare a parte.

Prima che il turno cominci non c'e' niente da congelare e la risposta e' la rosa
di adesso: e' quella che sta ancora cambiando, ed e' quella su cui il mercato
ripara le formazioni (R2).
"""
from __future__ import annotations

from django.utils import timezone

from vfoot.models import FantasyRosterSlot
from vfoot.services import matchday_state


def lock_instant(league, real_matchday: int, now=None):
    """Il primo calcio d'inizio confermato del turno, se e' gia' passato.

    ``None`` significa "il turno non e' cominciato" — non c'e' ancora una rosa da
    congelare — e copre anche il caso in cui il turno non ha nemmeno un orario
    confermato, dove congelare vorrebbe dire farlo su un istante inventato.
    """
    csid = getattr(league, "reference_season_id", None)
    if csid is None:
        return None
    lock = matchday_state.lineup_lock_at(csid, real_matchday)
    if lock is None or lock > (now or timezone.now()):
        return None
    return lock


def owned_at(team, instant) -> set[int]:
    """I giocatori sotto contratto con questa squadra a ``instant``.

    Un contratto vale da ``acquired_at`` (incluso) a ``released_at`` (escluso):
    chi e' stato svincolato ESATTAMENTE al calcio d'inizio non c'era piu', e chi
    e' stato acquistato in quell'istante c'era gia'. Il confine e' arbitrario ma
    deve essere uno solo, e questo e' lo stesso che usa ``team_first_kickoff``.
    """
    return {
        pid
        for pid, acquired_at, released_at in FantasyRosterSlot.objects.filter(
            team_id=getattr(team, "id", team)
        ).values_list("player_id", "acquired_at", "released_at")
        if (acquired_at is None or acquired_at <= instant)
        and (released_at is None or released_at > instant)
    }


def owned_now(team) -> set[int]:
    """La rosa di adesso. Sta qui accanto all'altra apposta: chi arriva a
    scegliere fra le due le trova nello stesso posto, con scritto quando serve
    l'una e quando l'altra."""
    return set(
        FantasyRosterSlot.objects.filter(
            team_id=getattr(team, "id", team), released_at__isnull=True
        ).values_list("player_id", flat=True)
    )


def owned_for_matchday(league, team, real_matchday: int, now=None) -> set[int]:
    """La rosa da usare per QUESTA giornata: congelata se il turno e' cominciato,
    quella di adesso se non lo e' ancora. E' la funzione che il ramo
    formazione/punteggio deve chiamare al posto di ``owned_now``.

    LE VIE DI FUGA (v. ``frozen_ids``) non sono rifiniture: senza, un'intera lega
    verrebbe giudicata su una rosa vuota — cioe' con ogni giocatore schierato
    trattato come venduto, in silenzio e a punteggio gia' fatto.

    * **La lega che non impone scadenze** (``enforce_lineup_deadline`` falso) e'
      per definizione quella che rigioca una stagione GIA' FINITA, dove ogni
      calcio d'inizio e' nel passato. Li' "il turno e' cominciato" e' vero
      sempre e non vuol dire niente, e non c'e' niente da congelare.
    * **La squadra che a quell'istante non aveva NESSUN contratto**: il turno e'
      anteriore alla formazione della sua rosa (una lega seminata a stagione in
      corso, un'asta battuta dopo). La risposta storica non e' "non aveva
      nessuno", e' "non lo so" — e allora vale quella di adesso, che e' la
      stessa cautela che ``team_first_kickoff`` applica a chi non ha contratti.

    Nessuna delle due tocca il caso per cui il congelamento esiste: una squadra
    vera, in un turno vero, ha i suoi venticinque al calcio d'inizio, e li' la
    rosa congelata e' non vuota e vince.
    """
    frozen = frozen_ids(league, team, real_matchday, now)
    return owned_now(team) if frozen is None else frozen


def frozen_ids(league, team, real_matchday: int, now=None) -> set[int] | None:
    """La rosa congelata, oppure ``None`` quando non e' congelabile.

    Il ``None`` e' la parte importante, e va tenuto distinto dall'insieme vuoto:
    dice «di questa giornata non so dirti la rosa storica», e chi legge deve
    ricadere sulla propria risposta prudente invece di concludere che la squadra
    non aveva nessuno. Le tre ragioni sono quelle spiegate in
    ``owned_for_matchday``, piu' il turno non ancora cominciato.
    """
    if not getattr(league, "enforce_lineup_deadline", True):
        return None
    lock = lock_instant(league, real_matchday, now)
    if lock is None:
        return None
    return owned_at(team, lock) or None
