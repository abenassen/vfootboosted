"""Chi passa il turno quando la partita finisce in parità.

UNA sfida, non una partita: in un turno a eliminazione due squadre si incontrano
una volta (gara secca) o due (andata e ritorno), e la domanda "chi passa" si fa
sulla SFIDA. Qui si raggruppano le gare in sfide (v. ``_ties``), si sommano, e si
risponde.

LA CATENA, IN ORDINE
--------------------
1. **I gol**, sommati sulle due gare. È il risultato: se dice qualcosa, decide lui.
2. **La somma dei punteggi** — i fantavoto delle due formazioni (``vfoot_home`` /
   ``vfoot_away`` del tabellino), anch'essi sommati sulla sfida. Due squadre che
   pareggiano 1-1 non hanno affatto giocato allo stesso modo: 78.5 contro 71.0 è
   una differenza che il punteggio vede e i gol no. Dove il tabellino non c'è
   (una lega aura, che segna dal risultato reale) questo passo non aggiunge nulla
   e si scende al terzo.
3. **La squadra di casa**, quella dell'ULTIMA gara della sfida — il ritorno, dove
   si gioca in casa per convenzione di chi ha fatto meglio prima. È l'ultima
   spiaggia e capita raramente, ma esiste per una ragione precisa: senza, un
   tabellone può restare BLOCCATO per sempre. Prima di questo modulo era proprio
   ciò che succedeva — una semifinale pari non mandava nessuno in finale, la
   finale non veniva sorteggiata, e la competizione non finiva più.

Questa catena è l'unico posto in cui si decide un turno secco: la leggono sia il
sorteggio del turno successivo (``competition_stages``) sia i premi «vince la
finale» / «perde la finale» (``competition_prizes``). Se le due risposte potessero
divergere, il tabellone direbbe che è passato uno e la coppa la vincerebbe un
altro.
"""
from __future__ import annotations

from dataclasses import dataclass

from vfoot.models import FantasyFixture

BY_GOALS = "gol"
BY_SCORE = "punteggio"
BY_HOME = "fattore campo"


@dataclass(frozen=True)
class TieOutcome:
    """Come è finita una sfida: chi passa, chi esce, e per quale delle tre regole."""
    winner_id: int
    loser_id: int
    reason: str
    # The lowest fixture id of the tie: the order the bracket was drawn in, kept so
    # that the teams handed to the next round come out in the same order they used
    # to before ties were resolved at all.
    order: int
    # Il turno dell'ULTIMA gara della sfida. Una sfida di andata e ritorno sta su
    # due turni, e quella che chiude una fase è quella che finisce più tardi — non
    # quella che comincia più tardi.
    last_round: int
    # Le partite che la compongono, per chi deve dire a schermo "questa gara fa
    # parte di quella sfida".
    fixture_ids: tuple[int, ...] = ()


def _score(fixture) -> tuple[float, float]:
    """(casa, trasferta) in punteggio: il fantavoto se c'è il tabellino, i gol se no."""
    detail = getattr(fixture, "detail", None)
    if detail is None:
        return fixture.home_total, fixture.away_total
    return detail.vfoot_home, detail.vfoot_away


def _ties(fixtures) -> list[list]:
    """Raggruppa le gare in SFIDE: una gara secca, o andata e ritorno.

    Le due gare di un confronto stanno su turni diversi (è così che finiscono su
    due giornate), quindi il turno non può fare da chiave. Le distingue il numero
    di gara: ``leg_no`` 1 apre una sfida, 2 la chiude. Così due incontri fra le
    stesse squadre che siano due sfide distinte — entrambi ``leg_no`` 1 — restano
    due, e un'andata col suo ritorno diventa una.
    """
    by_pair: dict[frozenset, list] = {}
    for fx in sorted(fixtures, key=lambda f: (f.round_no, f.leg_no, f.id)):
        if fx.status != FantasyFixture.STATUS_FINISHED:
            continue
        pair = frozenset((fx.home_team_id, fx.away_team_id))
        if len(pair) != 2:                    # una squadra contro sé stessa: non è una sfida
            continue
        by_pair.setdefault(pair, []).append(fx)

    out: list[list] = []
    for legs in by_pair.values():
        current: list = []
        for fx in legs:
            if fx.leg_no == 1 and current:
                out.append(current)
                current = []
            current.append(fx)
        if current:
            out.append(current)
    return out


def tie_outcomes(fixtures) -> list[TieOutcome]:
    """Le sfide di una fase, risolte, nell'ordine in cui sono state sorteggiate."""
    out: list[TieOutcome] = []
    for legs in _ties(fixtures):
        pair = {legs[0].home_team_id, legs[0].away_team_id}
        goals: dict[int, float] = dict.fromkeys(pair, 0.0)
        score: dict[int, float] = dict.fromkeys(pair, 0.0)
        for fx in legs:
            hs, as_ = _score(fx)
            goals[fx.home_team_id] += fx.home_total
            goals[fx.away_team_id] += fx.away_total
            score[fx.home_team_id] += hs
            score[fx.away_team_id] += as_

        a, b = legs[-1].home_team_id, legs[-1].away_team_id   # casa del ritorno per prima
        if goals[a] != goals[b]:
            winner, reason = (a if goals[a] > goals[b] else b), BY_GOALS
        elif score[a] != score[b]:
            winner, reason = (a if score[a] > score[b] else b), BY_SCORE
        else:
            winner, reason = a, BY_HOME
        out.append(TieOutcome(
            winner_id=winner, loser_id=b if winner == a else a, reason=reason,
            order=min(f.id for f in legs),
            last_round=max(f.round_no for f in legs),
            fixture_ids=tuple(f.id for f in legs),
        ))

    out.sort(key=lambda t: t.order)
    return out


def deciding_ties(fixtures) -> list[TieOutcome]:
    """Le sfide che CHIUDONO la fase: quelle che finiscono nell'ultimo turno.

    È ciò che legge un premio «vince la finale». Filtrare le GARE all'ultimo turno
    e poi raggrupparle darebbe il ritorno senza la sua andata, e la coppa a chi ha
    vinto una gara invece che la sfida.
    """
    outcomes = tie_outcomes(fixtures)
    if not outcomes:
        return []
    last = max(t.last_round for t in outcomes)
    return [t for t in outcomes if t.last_round == last]
