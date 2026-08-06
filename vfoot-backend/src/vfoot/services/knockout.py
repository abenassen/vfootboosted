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
BY_PENALTIES = "rigori"
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
        elif (legs[-1].shootout or {}).get("winner"):
            # I rigori, se sono stati battuti. Si LEGGONO e non si rigiocano: la
            # serie e' deterministica, quindi ricalcolarla darebbe sempre lo
            # stesso esito e rifarla a ogni apertura del tabellone sarebbe solo
            # lavoro sprecato. Li scrive la conclusione (v. `settle_shootouts`).
            side = legs[-1].shootout["winner"]
            winner, reason = (a if side == "home" else b), BY_PENALTIES
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


def settle_shootouts(fixtures) -> int:
    """Batte i rigori delle sfide rimaste in parità, e li SALVA. Idempotente.

    Chiamata dalla conclusione di una giornata, sulle gare della fase appena
    chiusa. Scrive sulla gara che ha chiuso la sfida, perché è lì che i rigori si
    battono. Rifarla non cambia nulla: la serie è deterministica.

    Serve una scrittura, e non un calcolo al volo alla lettura, per la stessa
    ragione per cui i premi si salvano — il tabellone si apre molte volte, la
    sfida si decide una.
    """
    from vfoot.models import FantasyFixtureDetail
    from vfoot.services import penalties

    pending = []
    for legs in _ties(fixtures):
        last = legs[-1]
        if last.shootout:
            continue
        a, b = last.home_team_id, last.away_team_id
        goals = {a: 0.0, b: 0.0}
        score = {a: 0.0, b: 0.0}
        for fx in legs:
            hs, as_ = _score(fx)
            goals[fx.home_team_id] += fx.home_total
            goals[fx.away_team_id] += fx.away_total
            score[fx.home_team_id] += hs
            score[fx.away_team_id] += as_
        if goals[a] != goals[b] or score[a] != score[b]:
            continue                       # decisa prima: niente rigori
        pending.append(last)

    if not pending:
        return 0

    # Il referto serve per intero (i voti puri dei ventidue), quindi qui NON si
    # differisce `payload`: è l'unico posto che lo legge davvero.
    payloads = {d.fixture_id: d.payload for d in
                FantasyFixtureDetail.objects.filter(fixture_id__in=[f.id for f in pending])}
    dice = _dice_for(pending)
    done = 0
    for fx in pending:
        payload = payloads.get(fx.id)
        if not isinstance(payload, dict) or "home" not in payload:
            continue                       # senza referto non ci sono tiratori
        fx.shootout = penalties.shootout(
            penalties.effective_xi(payload["home"]),
            penalties.effective_xi(payload["away"]), dice)
        fx.save(update_fields=["shootout"])
        done += 1
    return done


def _dice_for(fixtures) -> dict[int, tuple[float, int]]:
    """{player_id: (metri palla al piede, tocchi)} della giornata di queste gare.

    Una interrogazione sola per tutte le sfide da decidere: sono rare, ma non c'è
    ragione di chiederle una per volta.
    """
    from realdata.models import MatchAppearance

    keys = {(fx.fantasy_matchday.real_competition_season_id, fx.fantasy_matchday.real_matchday)
            for fx in fixtures if fx.fantasy_matchday_id}
    if not keys:
        return {}
    out: dict[int, tuple[float, int]] = {}
    for csid, md in keys:
        for pid, raw in MatchAppearance.objects.filter(
                match__competition_season_id=csid, match__matchday=md
        ).values_list("player_id", "raw_stats"):
            metres, touches = (raw or {}).get("totalBallCarriesDistance"), (raw or {}).get("touches")
            if metres is not None and touches is not None:
                out[pid] = (float(metres), int(touches))
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
