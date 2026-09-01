"""Quanto pesa un gol: non quanti minuti ha giocato chi l'ha fatto, ma che cosa
ha cambiato.

Fino al 29/08/2026 il gol era una feature dell'indice (``shots_goal``), e come
ogni altra voce veniva scalata dallo shrinkage sui minuti: lo stesso gol valeva
+0.618 a un titolare e +0.132 a chi entrava al 90'. La motivazione dello
shrinkage e' bayesiana e vale per le DENSITA' — «non mi fido di una media per
90' estrapolata da un cameo» — ma un gol non e' una densita': e' un fatto
discreto e concluso, senza rumore campionario, e se mai e' piu' difficile
farlo in dieci minuti che in novanta. Il commento dei pesi lo diceva gia'
("TOTALS are NOT rescaled to 90': a decisive action's value does not scale with
how few minutes you played") e poi lo shrinkage lo disfaceva.

Al suo posto: l'IMPATTO, misurato come punti in classifica attesi guadagnati
dallo stato che il gol ha creato.

    ΔxP = xP(minuto, differenza reti + 1) − xP(minuto, differenza reti)

``xP(stato)`` non e' un modello: e' la media osservata dei punti effettivamente
raccolti a fine partita da chi si e' trovato in quello stato, misurata su una
stagione intera e congelata in ``vote_reference.json`` insieme al resto della
calibrazione. Uno stato sono due sole coordinate — fascia di dieci minuti e
differenza reti tagliata a ±3 — e ogni partita ne offre 91 x 2 campioni.

Tre proprieta' che contano quanto il numero:

* si conosce NELL'ISTANTE del gol e non cambia piu'. Un criterio tipo «gol
  vittoria» si saprebbe solo al 90', e farebbe muovere voti gia' mostrati:
  inservibile per il punteggio in diretta.
* e' simmetrica. Quello che il marcatore guadagna, l'avversario lo perde; se un
  giorno servira' un malus per chi subisce, e' lo stesso numero col segno opposto.
* si spiega da sola. «un gol che sblocca lo 0-0» dice a chi legge perche' quel
  numero e' quello, cosa che «un gol · +0.51» non ha mai fatto.

DUE LIMITI, dichiarati: il taglio a ±3 rende identici (e nulli) tutti i gol oltre
il terzo di scarto; e xP=3.00 sugli stati estremi riflette in parte la forza della
squadra, non solo lo stato — chi va sul 3-0 e' forte a prescindere. Il secondo e'
un bias verso l'alto proprio sugli stati che vogliamo schiacciare, quindi qui
lavora nella direzione giusta.
"""
from __future__ import annotations

import math
from collections import defaultdict

# Uno stato: fascia di MINUTE_BIN minuti, differenza reti tagliata a ±GD_CAP.
MINUTE_BIN = 10
GD_CAP = 3
# Sotto questo numero di campioni uno stato non si dichiara: meglio nessuna
# importanza (e il gol ricade sul fondo della banda) che una media di sei partite.
MIN_SAMPLES = 25

# La banda, in PUNTI DI VOTO. Il gol meno importante della stagione ne vale
# BAND_LO, il piu' importante BAND_HI, e in mezzo si sale come la radice
# dell'importanza normalizzata — non linearmente, perche' la distribuzione di ΔxP
# ha la mediana SOPRA la media (0.872 contro 0.779) con una coda alta sottile, e
# una mappa lineare spenderebbe meta' del suo campo su gol rari lasciando quello
# tipico schiacciato in basso.
#
# I tre numeri sono CALIBRATI, non scelti: [0.30, 0.70] e' la forbice voluta
# dall'analista, riscalata dal fattore che tiene invariato il credito medio TOTALE
# di una marcatura (1.016 punti di voto sulla 25-26, sga e volume compresi) — cioe'
# la modifica ridistribuisce il valore del gol, non lo gonfia. Stanno nel file di
# calibrazione; questi sono solo il fallback per un checkout senza calibrazione.
DEFAULT_BAND = (0.2562, 0.5979)
DEFAULT_P95 = 1.6036

# La banda dell'ASSIST, sulla stessa importanza. Il ΔxP e' una proprieta' del GOL,
# non di chi lo segna: il passaggio che manda in porta sullo 0-0 al 90' ha cambiato
# la partita quanto la conclusione. Fino al 29/08/2026 il gol era graduato per
# impatto e il passaggio che lo aveva reso possibile no — una asimmetria che si
# vedeva a occhio nudo in Frosinone-Juventus, dove Bremer prendeva il credito del
# gol vittoria e Conceicao, che gliel'aveva servito, un forfait di 0.153.
#
# Calibrata come quella del gol e contro lo stesso principio: il credito MEDIO di
# un assist resta quello di prima (0.1551 per presenza, misurato sulle 546 presenze
# con assist della 25-26), quindi la modifica ridistribuisce e non gonfia.
DEFAULT_ASSIST_BAND = (0.085, 0.198)
# L'importanza MEDIA di un gol della stagione. Serve alla RICADUTA: un assist che
# non si riesce ad agganciare a un gol non deve valere zero -- varrebbe zero solo
# perche' non sappiamo, e "non lo so" non e' "non e' successo". Gli si da' il
# credito del gol medio, che e' l'unica risposta onesta senza il legame.
DEFAULT_MEAN_IMPORTANCE = 0.779


def state_key(minute: int, goal_difference: int) -> str:
    """La chiave dello stato. Stringa e non tupla perche' questa tabella viaggia
    dentro un JSON, e le chiavi di un JSON sono stringhe: tenerla cosi' anche in
    memoria evita che la tabella salvata e quella letta si somiglino soltanto."""
    b = min(int(minute) // MINUTE_BIN, (90 // MINUTE_BIN))
    return f"{b}:{max(-GD_CAP, min(GD_CAP, int(goal_difference)))}"


def build_xp_table(matches) -> dict[str, float]:
    """{stato: punti attesi}, dagli esiti osservati.

    ``matches`` e' un iterabile di ``(gol_casa, gol_trasferta, [(minuto, lato)])``
    con il lato per cui il gol CONTA (che per un autogol non e' quello di chi lo
    segna). Chi chiama filtra le partite la cui cronologia non riconcilia col
    risultato finale: uno stato ricostruito male e' peggio di uno stato mancante.
    """
    samples: dict[str, list[int]] = defaultdict(list)
    for home_goals, away_goals, timeline in matches:
        ph = 3 if home_goals > away_goals else 1 if home_goals == away_goals else 0
        pa = 3 if away_goals > home_goals else 1 if home_goals == away_goals else 0
        for minute in range(0, 91):
            hg = sum(1 for m, side in timeline if side == "home" and m <= minute)
            ag = sum(1 for m, side in timeline if side == "away" and m <= minute)
            samples[state_key(minute, hg - ag)].append(ph)
            samples[state_key(minute, ag - hg)].append(pa)
    return {k: sum(v) / len(v) for k, v in samples.items() if len(v) >= MIN_SAMPLES}


def importance(xp: dict, minute: int, goal_difference_before: int) -> float | None:
    """ΔxP del gol che porta la differenza da ``goal_difference_before`` a +1.

    None quando uno dei due stati non e' campionato abbastanza: chi chiama
    decide, e ``goal_credit`` lo tratta come importanza nulla (fondo della banda),
    perche' un gol vale sempre qualcosa anche quando non sappiamo dire quanto.
    """
    before = xp.get(state_key(minute, goal_difference_before))
    after = xp.get(state_key(minute, goal_difference_before + 1))
    if before is None or after is None:
        return None
    return after - before


def goal_credit(importances, band=DEFAULT_BAND, p95: float = DEFAULT_P95) -> float:
    """I punti di voto per i gol di un giocatore in una partita.

    ADDITIVO fra i gol, e la compressione della doppietta viene GRATIS
    dall'importanza stessa: il secondo gol della stessa partita e' quasi sempre
    meno pesante del primo (spesso e' il raddoppio, che sposta poco), quindi
    sommando si ottiene la curva che prima andava imposta a mano con ``scored_z``.
    Misurato sulla 25-26: doppietta +0.900 di media contro i +0.972 del vecchio
    conteggio compresso, tripletta +1.214 contro +1.220.
    """
    lo, hi = band
    total = 0.0
    for imp in importances:
        u = max(0.0, min(1.0, (imp or 0.0) / p95)) if p95 else 0.0
        total += lo + (hi - lo) * (u ** 0.5)
    return total


def assists_by_player(match) -> dict[int, list[dict]]:
    """{player_id: [un record per assist]} — gli stessi record dei gol serviti.

    L'importanza e' quella del GOL: chi ha fatto il passaggio ha contribuito a
    creare quello stato, e il numero e' gia' li'. Richiede ``assist_player`` sul
    tiro (v. backfill_shot_assists): senza, un assist non si puo' legare al gol
    che ha prodotto e questa funzione non restituisce niente per quella partita.
    """
    from realdata.models import MatchShot

    by_goal = {}
    for pid, recs in goals_by_player(match).items():
        for r in recs:
            by_goal[(r["minute"], pid)] = r
    assisted = defaultdict(list)
    for s in (MatchShot.objects.filter(match=match, is_goal=True)
              .exclude(assist_player=None)
              .values("player_id", "minute", "assist_player_id")):
        rec = by_goal.get((s["minute"], s["player_id"]))
        if rec is not None:
            assisted[s["assist_player_id"]].append(rec)

    # LA RICADUTA. ``MatchAppearance.assists`` e' il conteggio del fornitore ed e'
    # l'autorita' su QUANTI: se un assist non si e' agganciato a un gol -- partita
    # importata prima del campo, minuto con due gol dello stesso lato, passatore
    # non riconosciuto -- riceve comunque il credito del gol medio. Senza questo,
    # un dato mancante si presenterebbe come un assist che non e' stato fatto, che
    # e' il modo peggiore di sbagliare: silenzioso e a danno del giocatore.
    from realdata.models import MatchAppearance

    mean = mean_importance()
    for pid, n in (MatchAppearance.objects.filter(match=match, assists__gt=0)
                   .values_list("player_id", "assists")):
        missing = int(n) - len(assisted.get(pid, ()))
        for _ in range(max(0, missing)):
            assisted[pid].append({"minute": None, "own_after": None,
                                  "opp_after": None, "importance": mean,
                                  "unlinked": True})
    return dict(assisted)


def assist_credit(records, band=DEFAULT_ASSIST_BAND, p95: float = DEFAULT_P95) -> float:
    """Come ``goal_credit``, sulla banda dell'assist."""
    return goal_credit(importances_of(records), band, p95)


def assist_phrase(records) -> str:
    recs = list(records or [])
    if not recs:
        return ""
    if len(recs) > 1:
        return f"{len(recs)} assist"
    r = recs[0]
    if r.get("unlinked"):
        # Sappiamo che l'assist c'e', non quale gol ha servito: si dice cosi' e
        # basta, invece di inventare uno stato di partita.
        return "un assist"
    own, opp, minute = r["own_after"], r["opp_after"], r["minute"]
    if own == 1 and opp == 0:
        what = "l'assist del gol che sblocca lo 0-0"
    elif own == opp:
        what = f"l'assist del pareggio ({own}-{opp})"
    elif own < opp:
        what = f"l'assist del gol che accorcia ({opp}-{own})"
    else:
        what = f"l'assist del {own}-{opp}"
    if minute is not None:
        what += f", al {int(minute)}'"
    imp = r.get("importance")
    if imp is not None and imp < DEAD_RUBBER:
        what += " a partita ormai decisa"
    return what


def goals_by_player(match) -> dict[int, list[dict]]:
    """{player_id: [un record per gol]} per una partita.

    Ogni record porta il minuto, il punteggio DAL SUO PUNTO DI VISTA subito dopo
    il gol e l'importanza. Il punteggio serve alla frase — «un gol che sblocca lo
    0-0» si puo' dire solo sapendo che era 0-0 — e senza di esso la spiegazione
    avrebbe un numero senza il fatto che lo giustifica, che e' il difetto che
    tutta questa modifica esiste per togliere.

    Ricostruisce il punteggio minuto per minuto dalla mappa dei tiri e legge, per
    ogni gol, lo stato che c'era PRIMA. Sulla 25-26 la cronologia riconcilia col
    risultato finale in 380 partite su 380.

    GLI AUTOGOL NON SONO SUOI. Il fornitore archivia un autogol come un gol del
    marcatore ma lo attribuisce al lato per cui CONTA, cioe' quello avversario:
    un gol il cui ``team_side`` non e' il lato in cui il giocatore era schierato
    e' un autogol e non gli porta nessun credito (il suo malus e' un'altra cosa,
    v. own_goal_adjustments).
    """
    from realdata.models import MatchAppearance, MatchShot
    # Locale: ``classic_rating`` importa questo modulo in cima, quindi la
    # dipendenza puo' andare in un verso solo senza chiudere il cerchio.
    from vfoot.services.classic_rating import is_own_goal

    xp = fixed_xp_table()
    if not xp:
        return {}
    side_of = dict(MatchAppearance.objects.filter(match=match)
                   .values_list("player_id", "side"))
    timeline = sorted(
        (s for s in MatchShot.objects.filter(match=match, is_goal=True)
         .values("player_id", "minute", "team_side", "shot_type")
         if s["minute"] is not None),
        key=lambda s: s["minute"])
    out: dict[int, list[float | None]] = defaultdict(list)
    for i, shot in enumerate(timeline):
        pid = shot["player_id"]
        # ``is_own_goal``, non il confronto scritto a mano: la stessa domanda si
        # pone in cinque posti di questo codice e fino al 30/08/2026 ognuno se la
        # rispondeva da solo — due su cinque sbagliando.
        if not pid or is_own_goal(shot["shot_type"], shot["team_side"],
                                  side_of.get(pid)):
            continue
        own = sum(1 for e in timeline[:i] if e["team_side"] == shot["team_side"])
        opp = sum(1 for e in timeline[:i] if e["team_side"] != shot["team_side"])
        out[pid].append({
            "minute": shot["minute"],
            "own_after": own + 1,
            "opp_after": opp,
            "importance": importance(xp, shot["minute"], own - opp),
        })
    return dict(out)


# --- IL GOL SUBITO, dal punto di vista del portiere ---------------------------
# Il gol lo pesiamo per quanto ha CAMBIATO la partita da quando esiste
# ``goal_credit`` — ma solo a credito di chi lo segna. A debito di chi lo subisce
# valeva uno come tutti gli altri, e le due letture dello stesso evento non
# possono essere diverse: il pallonetto che al 90' rompe uno 0-0 non e' il quarto
# gol di un 4-0.
#
# CHE COSA MOLTIPLICA, e perche' non il gol intero: il peso moltiplica la GRAVITA'
# dell'errore, cioe' la parte del tiro che il portiere non ha preso (1 - xGOT), non
# l'unita' intera. ``gk_goals_prevented`` e' gia' "xGOT parato meno la gravita' dei
# gol presi" (la somma dell'xGOT affrontato include quello dei gol), quindi qui si
# scala esattamente quel termine. Un gol decisivo ma IMPARABILE (xGOT 0.9, gravita'
# 0.1) resta quasi gratis, com'e' giusto: il fattore dice quanto e' pesato
# l'errore, non quanto e' pesato il gol.
#
# LA FORMA e' quella della banda del gol — lo stesso u = sqrt(imp/p95) — ma il
# bersaglio e' 1.0 invece di un credito in punti: e' un MOLTIPLICATORE, e la
# ridistribuzione dev'essere a somma zero sulla popolazione. Da cui ``lo`` non e'
# libero: fissata la forbice, lo = 1 - forbice * u_medio.
#
# MEAN_U e' misurato: 0.6021 sui 917 gol subiti della 25-26 con l'importanza letta
# dal lato che li subisce. Sta scritto qui, come DEFAULT_MEAN_IMPORTANCE, perche'
# rimisurarlo richiede la stagione intera.
CONCEDED_MEAN_U = 0.6021
# La forbice, scelta dall'analista. 0.8 mette il gol ininfluente a 0.518 e quello
# decisivo a 1.318 — rapporto 2.54, in linea col 2.33 fra i due estremi della banda
# del gol (0.202 / 0.4714), cioe' la stessa severita' che usiamo a credito.
CONCEDED_SPREAD = 0.8


def conceded_weight(importance: float | None, p95: float = DEFAULT_P95) -> float:
    """Quanto pesa QUESTO gol subito, in multipli di un gol medio (media 1.0).

    ``importance`` None (stato non campionato) -> 1.0: non sappiamo dire quanto ha
    cambiato, e l'unica risposta onesta e' "come un gol qualunque"."""
    if importance is None or not p95:
        return 1.0
    u = math.sqrt(max(0.0, min(1.0, importance / p95)))
    lo = 1.0 - CONCEDED_SPREAD * CONCEDED_MEAN_U
    return lo + CONCEDED_SPREAD * u


def conceded_by_side(match) -> dict[str, list[dict]]:
    """{lato_che_subisce: [{minute, xgot, weight, own_goal}]} per una partita.

    L'importanza e' letta DAL LATO CHE SUBISCE: la differenza reti passa da d a
    d-1, quindi e' ``importance(minuto, d-1)`` — la stessa funzione del gol, un
    gradino piu' in basso.

    L'AUTOGOL RESTA FUORI: la sua difficolta' e' gia' restituita al portiere da
    ``_merge_own_goal_relief``, e pesarlo anche qui vorrebbe dire graduare due
    volte lo stesso pallone con due regole diverse.
    """
    from realdata.models import MatchAppearance, MatchShot
    from vfoot.services.classic_rating import is_own_goal

    xp = fixed_xp_table()
    if not xp:
        return {}
    _band, p95 = fixed_band()
    side_of = dict(MatchAppearance.objects.filter(match=match)
                   .values_list("player_id", "side"))
    timeline = sorted(
        (s for s in MatchShot.objects.filter(match=match, is_goal=True)
         .values("player_id", "minute", "team_side", "shot_type", "xgot")
         if s["minute"] is not None),
        key=lambda s: s["minute"])
    out: dict[str, list[dict]] = defaultdict(list)
    for i, shot in enumerate(timeline):
        if is_own_goal(shot["shot_type"], shot["team_side"],
                       side_of.get(shot["player_id"])):
            continue
        conceding = "away" if shot["team_side"] == "home" else "home"
        own = sum(1 for e in timeline[:i] if e["team_side"] == conceding)
        opp = sum(1 for e in timeline[:i] if e["team_side"] != conceding)
        imp = importance(xp, shot["minute"], own - opp - 1)
        out[conceding].append({"minute": shot["minute"],
                               "xgot": float(shot["xgot"] or 0.0),
                               "importance": imp,
                               "weight": conceded_weight(imp, p95)})
    return dict(out)


def importances_of(records) -> list:
    return [r["importance"] for r in records or []]


def credit_by_player(match) -> dict[int, float]:
    """{player_id: punti di voto} — quanto valgono i gol di ognuno in questa partita."""
    band, p95 = fixed_band()
    return {pid: goal_credit(importances_of(recs), band, p95)
            for pid, recs in goals_by_player(match).items()}


# Sotto questa importanza il gol non ha cambiato niente e la frase deve dirlo,
# altrimenti «il gol del 4-0 · +0.25» sembra un errore di calcolo invece che il
# giudizio che e'. Il valore e' il primo quartile della 25-26 (ΔxP 0.303).
DEAD_RUBBER = 0.30


def goal_phrase(records) -> str:
    """Come si chiama, ad alta voce, il credito dei gol di questo giocatore.

    Una frase per un gol solo («un gol che sblocca lo 0-0, al 69'»), il conteggio
    per piu' di uno: elencare tre stati di partita in una riga di riassunto non si
    legge, e il dettaglio sta comunque nella tabella tiro per tiro.
    """
    recs = list(records or [])
    if not recs:
        return ""
    if len(recs) > 1:
        return f"{len(recs)} gol"
    r = recs[0]
    own, opp, minute = r["own_after"], r["opp_after"], r["minute"]
    if own == 1 and opp == 0:
        what = "un gol che sblocca lo 0-0"
    elif own == opp:
        what = f"il gol del pareggio ({own}-{opp})"
    elif own < opp:
        what = f"il gol che accorcia ({opp}-{own})"
    else:
        what = f"il gol del {own}-{opp}"
    if minute is not None:
        what += f", al {int(minute)}'"
    imp = r.get("importance")
    if imp is not None and imp < DEAD_RUBBER:
        what += " a partita ormai decisa"
    return what


def fixed_xp_table() -> dict:
    from vfoot.services.vote_reference import fixed_goal_impact
    return (fixed_goal_impact() or {}).get("xp") or {}


def fixed_band() -> tuple[tuple[float, float], float]:
    from vfoot.services.vote_reference import fixed_goal_impact
    data = fixed_goal_impact() or {}
    band = data.get("band") or DEFAULT_BAND
    return (float(band[0]), float(band[1])), float(data.get("p95") or DEFAULT_P95)


def fixed_assist_band() -> tuple[tuple[float, float], float]:
    from vfoot.services.vote_reference import fixed_goal_impact
    data = fixed_goal_impact() or {}
    band = data.get("assist_band") or DEFAULT_ASSIST_BAND
    return (float(band[0]), float(band[1])), float(data.get("p95") or DEFAULT_P95)


def mean_importance() -> float:
    from vfoot.services.vote_reference import fixed_goal_impact
    return float((fixed_goal_impact() or {}).get("mean_importance")
                 or DEFAULT_MEAN_IMPORTANCE)


def role_mean_assist_credit() -> dict[str, float]:
    from vfoot.services.vote_reference import fixed_goal_impact
    return (fixed_goal_impact() or {}).get("role_mean_assist_credit") or {}


def role_mean_credit() -> dict[str, float]:
    """La media di ruolo del credito, che va SOTTRATTA.

    Il gol e' uscito dall'indice, e l'indice era zero-medio per costruzione: ogni
    voce e' misurata contro il pari ruolo medio. Un credito solo positivo appiccicato
    dopo non lo e', e senza questa sottrazione alzava la media di TUTTI i ruoli che
    segnano (ATT +0.09) e allargava il sigma. Sottratta, lo SCARTO fra chi segna e
    chi no resta esattamente la banda e la popolazione non si muove.
    """
    from vfoot.services.vote_reference import fixed_goal_impact
    return (fixed_goal_impact() or {}).get("role_mean_credit") or {}
