"""Costruire il blocco ``goal_impact`` della calibrazione da una stagione finita.

Tre pezzi, in quest'ordine obbligato:

1. la tabella xP, dagli esiti osservati;
2. la BANDA, risolta — non scelta — perche' il credito medio totale di una
   marcatura resti quello di prima della modifica. Il credito e' lineare nella
   scala della banda, quindi si risolve in un colpo invece che per tentativi;
3. la MEDIA DI RUOLO del credito, che il voto sottrae per restare a media zero.

Il passo 2 e' il solo che ha bisogno del modello VECCHIO e di quello NUOVO nello
stesso processo: il bersaglio e' «quanto valeva una marcatura prima», e si misura
solo col vettore di pesi che ce l'aveva. Chi ricalibra dopo aver gia' cambiato i
pesi non puo' piu' misurarlo, quindi il bersaglio si passa come parametro
(``target_total``) e il valore misurato una volta sta scritto qui sotto.
"""
from __future__ import annotations

import statistics as st
from collections import defaultdict

from vfoot.services import goal_impact as gi

# Il credito medio TOTALE di una marcatura (gol + sga + volume dello stesso tiro)
# misurato sulla 25-26 col modello che aveva ``shots_goal`` nell'indice, su 810
# marcature. E' il bersaglio che tiene la modifica a somma zero: la banda
# ridistribuisce il valore del gol fra gol pesanti e gol ininfluenti, non lo
# gonfia. Rimisurarlo richiede il vecchio vettore di pesi, quindi e' scritto.
TARGET_TOTAL_25_26 = 1.0160
# La forbice voluta dall'analista, in punti di voto, PRIMA del riscalamento.
BAND_SHAPE = (0.30, 0.70)
# Il credito medio di una PRESENZA con assist col modello che aveva ``assists``
# nell'indice: 546 presenze della 25-26. Stesso ruolo del bersaglio del gol —
# l'assist si ridistribuisce per impatto, non si gonfia.
TARGET_ASSIST = 0.1551


def season_timelines(competition_season_id: int):
    """[(gol_casa, gol_trasferta, [(minuto, lato)])] per le partite la cui
    cronologia dei gol RICONCILIA col risultato finale.

    Il filtro non e' pignoleria: uno stato ricostruito da una cronologia
    incompleta entra nella media come se fosse vero, e la tabella xP e' una media
    di stati. Sulla 25-26 riconciliano 380 partite su 380.
    """
    from realdata.models import Match, MatchShot

    finished = list(Match.objects
                    .filter(competition_season_id=competition_season_id,
                            status=Match.STATUS_FINISHED)
                    .values("id", "home_goals", "away_goals"))
    goals = defaultdict(list)
    for s in (MatchShot.objects
              .filter(match__competition_season_id=competition_season_id, is_goal=True)
              .values("match_id", "minute", "team_side")):
        if s["minute"] is not None:
            goals[s["match_id"]].append((s["minute"], s["team_side"]))
    out, skipped = [], 0
    for m in finished:
        hg, ag = m["home_goals"] or 0, m["away_goals"] or 0
        tl = goals.get(m["id"], [])
        if (sum(1 for _t, side in tl if side == "home") != hg
                or sum(1 for _t, side in tl if side == "away") != ag):
            skipped += 1
            continue
        out.append((hg, ag, sorted(tl)))
    return out, skipped


def season_importances(competition_season_id: int, xp: dict):
    """{(match_id, player_id): [ΔxP]} per la stagione, autogol esclusi."""
    from realdata.models import Match, MatchAppearance, MatchShot

    sides = {(a["match_id"], a["player_id"]): a["side"] for a in
             MatchAppearance.objects
             .filter(match__competition_season_id=competition_season_id)
             .values("match_id", "player_id", "side")}
    finished = set(Match.objects
                   .filter(competition_season_id=competition_season_id,
                           status=Match.STATUS_FINISHED)
                   .values_list("id", flat=True))
    per_match = defaultdict(list)
    for s in (MatchShot.objects
              .filter(match__competition_season_id=competition_season_id, is_goal=True)
              .values("match_id", "player_id", "minute", "team_side")):
        if s["match_id"] in finished and s["minute"] is not None:
            per_match[s["match_id"]].append(s)
    out = defaultdict(list)
    for mid, shots in per_match.items():
        shots.sort(key=lambda s: s["minute"])
        for i, shot in enumerate(shots):
            pid = shot["player_id"]
            if not pid or sides.get((mid, pid)) != shot["team_side"]:
                continue
            own = sum(1 for e in shots[:i] if e["team_side"] == shot["team_side"])
            opp = sum(1 for e in shots[:i] if e["team_side"] != shot["team_side"])
            out[(mid, pid)].append(gi.importance(xp, shot["minute"], own - opp))
    return dict(out)


def solve_band(all_importances, scoring_appearances, residual_mean: float,
               target_total: float = TARGET_TOTAL_25_26):
    """La banda riscalata, e il 95mo percentile che la normalizza.

    ``residual_mean`` e' quanto vale GIA' una marcatura senza il credito del gol —
    l'sga e il volume del tiro che l'ha prodotta, misurati col modello NUOVO. Il
    credito del gol deve valere il resto per arrivare al bersaglio.

    DUE POPOLAZIONI DIVERSE, e non e' una svista.

    Il PERCENTILE si prende su TUTTI i gol della stagione. E' la definizione di
    «il gol piu' importante», e un gol e' un gol anche se chi l'ha fatto ha giocato
    otto minuti e non entra nella popolazione di calibrazione — anzi, il gol del
    subentrato e' esattamente il caso che questa modifica esiste per valorizzare.
    Restringerlo alle presenze valutate portava la p95 da 1.60 a 1.44, cioe'
    schiacciava la banda contro un massimo piu' basso del vero.

    La MEDIA si prende sulle sole presenze VALUTATE, perche' il bersaglio con cui
    si confronta (``target_total``) e' misurato li'. Ed e' una media per PRESENZA e
    non per gol: una doppietta e' una presenza sola con due gol.
    """
    flat = sorted(i for imps in all_importances.values() for i in imps
                  if i is not None)
    if not flat or not scoring_appearances:
        return gi.DEFAULT_BAND, gi.DEFAULT_P95
    p95 = flat[int(0.95 * len(flat))]
    unit = st.fmean([gi.goal_credit(imps, BAND_SHAPE, p95)
                     for imps in scoring_appearances.values()])
    scale = (target_total - residual_mean) / unit if unit else 1.0
    return (round(BAND_SHAPE[0] * scale, 4), round(BAND_SHAPE[1] * scale, 4)), round(p95, 4)


def season_assist_importances(competition_season_id: int, xp: dict):
    """{(match_id, player_id): [ΔxP dei gol che ha servito]}.

    L'importanza e' quella del GOL servito: richiede ``MatchShot.assist_player``
    (v. backfill_shot_assists). Senza quel campo il dizionario esce vuoto e la
    banda ricade sul valore di fallback, che e' meglio di una banda tarata su tre
    assist.
    """
    from realdata.models import Match, MatchAppearance, MatchShot
    from collections import defaultdict as dd

    sides = {(a["match_id"], a["player_id"]): a["side"] for a in
             MatchAppearance.objects
             .filter(match__competition_season_id=competition_season_id)
             .values("match_id", "player_id", "side")}
    finished = set(Match.objects
                   .filter(competition_season_id=competition_season_id,
                           status=Match.STATUS_FINISHED)
                   .values_list("id", flat=True))
    per_match = dd(list)
    for s in (MatchShot.objects
              .filter(match__competition_season_id=competition_season_id, is_goal=True)
              .values("match_id", "player_id", "minute", "team_side",
                      "assist_player_id")):
        if s["match_id"] in finished and s["minute"] is not None:
            per_match[s["match_id"]].append(s)
    out = dd(list)
    for mid, shots in per_match.items():
        shots.sort(key=lambda s: s["minute"])
        for i, shot in enumerate(shots):
            pid, apid = shot["player_id"], shot["assist_player_id"]
            if not pid or not apid or sides.get((mid, pid)) != shot["team_side"]:
                continue
            own = sum(1 for e in shots[:i] if e["team_side"] == shot["team_side"])
            opp = sum(1 for e in shots[:i] if e["team_side"] != shot["team_side"])
            out[(mid, apid)].append(gi.importance(xp, shot["minute"], own - opp))
    return dict(out)


def solve_assist_band(all_importances, assisting_appearances,
                      target: float = TARGET_ASSIST):
    """La banda dell'assist. Stessa forma di ``solve_band``, senza residuo: il
    passaggio non porta con se' un blocco di feature come il tiro del gol, quindi
    il bersaglio e' direttamente il credito medio."""
    flat = sorted(i for imps in all_importances.values() for i in imps if i is not None)
    if not flat or not assisting_appearances:
        return gi.DEFAULT_ASSIST_BAND
    p95 = flat[int(0.95 * len(flat))]
    unit = st.fmean([gi.goal_credit(imps, BAND_SHAPE, p95)
                     for imps in assisting_appearances.values()])
    scale = target / unit if unit else 1.0
    return (round(BAND_SHAPE[0] * scale, 4), round(BAND_SHAPE[1] * scale, 4))


def role_mean_credit(population, importances_by_appearance, band, p95) -> dict:
    """{ruolo: credito medio}, sulla STESSA popolazione che definisce la reference.

    Deve essere quella e non un'altra: e' la media che rende il termine a somma
    zero, e una media presa su un insieme diverso da quello su cui e' calibrato
    l'indice sposterebbe il centro del ruolo di quel tanto che le due differiscono.
    """
    sums, counts = defaultdict(float), defaultdict(int)
    for key, role in population:
        sums[role] += gi.goal_credit(importances_by_appearance.get(key, []), band, p95)
        counts[role] += 1
    return {r: round(sums[r] / counts[r], 4) for r in counts if counts[r]}
