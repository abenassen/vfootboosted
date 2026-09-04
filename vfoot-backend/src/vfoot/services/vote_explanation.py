"""Say, in words, why a voto puro came out where it did.

A number a player cannot interrogate is a number he will not trust — especially
one produced by a weighted index of fifteen-odd measures. The vote itself is
already explainable in principle: it is a sum of weighted terms, z-scored within
the role. This turns that structure into a handful of sentences.

Two choices make the output honest rather than merely plausible:

* contributions are expressed in VOTE POINTS, not in index units. "Duels: +0.35"
  means those duels moved his vote by a third of a point. Index units would be
  unfalsifiable — nobody can tell whether 0.42 of an index is a lot.
* every term is measured AGAINST THE AVERAGE PLAYER IN HIS ROLE, not against
  zero. A defender who made the usual number of clearances did nothing
  remarkable, and saying "clearances +0.4" would be flattery. What explains a
  6.5 rather than a 6 is only where he departed from his peers.

Bonus and malus (goals, assists, cards) are deliberately absent: they are added
after the voto puro, in the open, and the user can already see them.
"""
from __future__ import annotations

from vfoot.services.classic_rating import (
    DERIVED_FEATURES, EXPOSURE_KEY, EXPOSURE_WEIGHT, GK_PER90_WEIGHTS,
    GK_TOTAL_WEIGHTS, GK_WEIGHTS, PER90_WEIGHTS, scale_saturation,
    shrinkage_for, TOTAL_WEIGHTS,
    UNSHRUNK_FEATURES, VOTE_CENTER, VOTE_MAX, VOTE_MIN, WEIGHTS, vote_center_for,
    _feature_z, _raw_vote_from_index, exposure_z, scored_z, feature_scales,
    index_for_role, minute_shift, observed_index, raw_feature_values, spread_k_for,
    weights_for_role,
)
from realdata.models import Player
from vfoot.services import goal_impact

# What each feature is called out loud, and how to quantify it. THREE kinds, chosen
# by how much the number "1" already means for that feature:
#
# COUNT (kind, label, quant): VOLUME stats where 1 is nothing and only the amount
# vs the role average matters — duels, clearances, passes, touches. Announced with
# absolute quantifiers ("tanti/pochi {label}") read against the role average as the
# yardstick; ``quant`` carries the gender/number agreement so we never say "tanti
# respinte".
#
# SIGNAL (kind, positive, negative): the small, high-value continuous quantities
# where even one is notable but there is no clean integer to count — xA and the
# merged shooting/dribbling nets. Announced NEUTRALLY as "una o più ...", the noun
# carrying the sense: net-positive -> "una o più conclusioni pericolose",
# net-negative -> "una o più occasioni fallite". This sidesteps both "molte" (false
# for one big pass) and a dangling "più". ``negative`` may be None — nothing worth
# saying on the low side (below-average creation is a non-event).
#
# EVENT (kind, singular, plural): rare discrete facts we count EXACTLY — reported
# only when they happened, with the real number: "3 interventi da ultimo uomo".
COUNT, SIGNAL, EVENT = "count", "signal", "event"

# Absolute quantifier pairs (many / few) with gender-number agreement.
QUANTIFIERS = {"mp": ("tanti", "pochi"), "fp": ("tante", "poche"),
               "ms": ("tanto", "poco"), "fs": ("tanta", "poca")}

# Come si nomina uno ZERO. "pochi duelli vinti" a chi non ne ha giocato nessuno non
# e' un'imprecisione di stile: implica che qualche duello l'abbia vinto, e chi legge
# il tabellino non ci ritrova niente. Sulla 25-26 la frase mostrata conteneva una
# riga cosi' nel 39,6% dei casi.
#
# Solo per le grandezze che si CONTANO. Un indice normalizzato o un valore atteso
# (``_exposure``, ``sga_post``, ``gk_goals_prevented``) puo' valere zero senza che
# "nessuno" voglia dire niente, e quelli restano fuori: senza una voce qui la
# frase torna al quantificatore di prima, che per una grandezza continua e' giusto.
COUNT_NONE = {
    "key_passes": "nessun passaggio chiave",
    "duels_won": "nessun duello vinto",
    "duels_lost": "nessun duello perso",
    "aerials_won": "nessun duello aereo vinto",
    "aerials_lost": "nessun duello aereo perso",
    "dribbled_past": "nessun dribbling concesso all'avversario",
    "tackles_won": "nessun contrasto vinto",
    "interceptions": "nessun intercetto",
    "ball_recoveries": "nessun pallone recuperato",
    "blocks": "nessuna conclusione murata",
    "clearances": "nessuna respinta",
    "touches_in_box": "nessun pallone toccato in area",
    "passes_opp_half": "nessun passaggio nella meta' campo avversaria",
    "long_balls_completed": "nessun lancio lungo riuscito",
    "crosses_completed": "nessun cross riuscito",
    "passes_completed": "nessun passaggio riuscito",
    "was_fouled": "nessun fallo subito",
    "touches": "nessun pallone giocato",
    "errors_bad_passes": "nessun passaggio sbagliato",
    "errors_dispossessed": "nessun pallone perso in conduzione",
    "errors_miscontrols": "nessun controllo sbagliato",
    "errors_fouls_committed": "nessun fallo commesso",
    "gk_saves": "nessuna parata",
    "gk_saves_inside_box": "nessuna parata su tiri ravvicinati",
    "gk_high_claims": "nessuna uscita alta",
    "gk_punches": "nessuna respinta di pugno",
    "gk_sweeper": "nessuna uscita fuori area",
    "gk_crosses_not_claimed": "nessun cross mancato",
    "xg_shots": "nessuna posizione di tiro conquistata",
    "shots_on_target": "nessun tiro nello specchio",
    "shots": "nessun tiro tentato",
    "shots_blocked": "nessuna conclusione respinta dalla difesa",
    "dribbles_won": "nessun dribbling riuscito",
    "dribbles_attempted": "nessun dribbling tentato",
}

# The narrative is one-sided at the extremes, symmetrically around 6. A clearly
# poor game's "positives" are only its least-bad deviations (faint praise), and a
# clearly good game's "negatives" are trivialities on a fine display — neither is
# worth reading back. In the middle band [5.5, 6.5] (mixed games) both sides show.
# Suppressed items fold into "altre voci", so the breakdown still reconciles.
POSITIVES_MIN_VOTE = 5.5   # below this: only what went wrong
NEGATIVES_MAX_VOTE = 6.5   # above this: only what went well

# An assist is paid as a BONUS (+1 on the fantavoto) and almost nothing in the base
# vote, which reads the PASS and not its outcome. When the pass carried little
# expected value the two readings part company, and that is worth saying out loud —
# it is the single most common reason our base vote sits below a pagella's on a
# player who "did something". Threshold from the distribution of the 581
# assist-carrying appearances of 2025-26: median xA 0.14, first quartile 0.044, and
# 29% of them combine xA < 0.15 with no clear chance created at all.
ASSIST_LOW_XA = 0.15

# QUANTO deve valere una voce per essere chiamata "un motivo del voto". Sotto questa
# soglia la voce non sparisce: scende in "altre voci", dove sta col suo nome e col
# suo numero. Quello che cambia e' che non occupa uno dei tre posti in cima.
#
# Era 0.05, ed era troppo poco per due ragioni. La prima e' aritmetica: il voto si
# legge sulla griglia dei mezzi punti, quindi ci vogliono DIECI voci da 0.05 per
# muovere di un passo il numero scritto accanto al nome — chiamarne una "il
# motivo" la sopravvaluta di un ordine di grandezza. La seconda e' che il riassunto
# ha una quota da riempire (fino a tre per lato) e la riempie con quello che trova:
# abbassando i pesi delle voci grosse — passaggi chiave a zero, conclusioni a 0.45,
# duelli tagliati — i posti liberi sono andati alle minuzie posizionali. Misurato
# sulle 578 presenze delle prime due giornate della 26-27, prima e dopo quella
# ritaratura: "nessun lancio lungo riuscito" da 14 a 71 apparizioni, "poco gioco
# nella meta' campo avversaria" da 19 a 75, e "nessun intercetto" da 0 a 32 — una
# frase che compare SEMPRE a 0.050 esatti, cioe' solo perche' arrivava alla soglia.
# La quota di righe mostrate che valgono meno di un decimo di voto era passata dal
# 41.7% al 45.7%.
NAMEABLE_MIN_POINTS = 0.10

# How a sending-off's reason reads in Italian. The severity that scales the drop is
# RED_CARD_SEVERITY on the same keys; naming the reason is how a reader can tell why
# one sending-off cost 0.6 and another 1.5.
RED_REASON_IT = {
    "Professional foul last man": "fallo tattico da ultimo uomo",
    "Foul": "fallo",
    "Foul Committed": "fallo",
    "Violent conduct": "condotta violenta",
    "Bad Behaviour": "comportamento antisportivo",
    "Argument": "protesta",
}

LABELS = {
    # SIGNAL — small high-value continuous; "una o più ...", (positive, negative)
    "expected_assists": (SIGNAL, "una o più occasioni create per i compagni", None),
    # GENERICO PER FORZA, e la genericita' e' la parte onesta. E' una sintesi di un
    # feed che non abbiamo (ogni duello con posizione, avversario e fase di gioco):
    # non si puo' scomporre in un gesto che il lettore ritrovi nel tabellino, quindi
    # promettergliene uno sarebbe una bugia. Ed e' in parte COLLETTIVO — correla
    # -0.53 con i gol subiti mentre era in campo, piu' del rating che ci fornisce
    # chi lo calcola (-0.32) — per cui "d'insieme" dice il vero due volte.
    #
    # Perche' ora ha una frase, dopo essere stato a lungo senza: puo' essere la voce
    # PIU' GRANDE del voto di un difensore (il 20% in Rrahmani di Genoa-Napoli), e
    # una voce che muove il voto piu' di ogni altra e non compare nel riassunto
    # lascia il lettore davanti a un numero che nessuna delle righe mostrate
    # spiega. Restava muta l'intera spiegazione di 11 presenze sulla 25-26.
    # "prestazione ... sottotono" suonava come un verdetto sulla PARTITA, e su un
    # attaccante da tripletta (Malen col Milan, -0.03) leggeva assurdo. L'indice
    # misura il CONTRIBUTO difensivo, confrontato coi pari ruolo: dirlo cosi' e'
    # accurato e non pretende di giudicare il resto.
    "defensive_value": (SIGNAL, "buon contributo difensivo d'insieme",
                        "poco contributo difensivo d'insieme"),
    # EVENT — counted exactly, (singular, plural)
    "shots_goal": (EVENT, "un gol", "gol"),
    # L'assist entra nel voto base dal 25/08/2026 (peso 0.03, v. TOTAL_WEIGHTS), quindi
    # va NOMINATO: una voce che muove il voto e non compare nella spiegazione e' il
    # difetto che questo modulo esiste per non avere. In italiano e' invariabile —
    # "un assist", "3 assist" — e il plurale della tabella lo rispetta.
    "assists": (EVENT, "un assist", "assist"),
    "big_chance_created": (EVENT, "un'occasione nitida creata", "occasioni nitide create"),
    "big_chance_missed": (EVENT, "un'occasione nitida sprecata", "occasioni nitide sprecate"),
    "shots_post": (EVENT, "un tiro sul palo", "tiri sul palo"),
    "errors_led_to_goal": (EVENT, "un errore che ha portato a un gol",
                           "errori che hanno portato a un gol"),
    "errors_led_to_shot": (EVENT, "un errore che ha concesso un tiro",
                           "errori che hanno concesso un tiro"),
    "penalties_conceded": (EVENT, "un rigore concesso", "rigori concessi"),
    "penalties_won": (EVENT, "un rigore conquistato", "rigori conquistati"),
    "clearances_off_line": (EVENT, "un salvataggio sulla linea", "salvataggi sulla linea"),
    "last_man_tackle": (EVENT, "un intervento da ultimo uomo", "interventi da ultimo uomo"),
    "gk_penalty_saves": (EVENT, "un rigore parato", "rigori parati"),
    # COUNT — volume, "tanti/pochi ...", (label, quant)
    "key_passes": (COUNT, "passaggi chiave", "mp"),
    "duels_won": (COUNT, "duelli vinti", "mp"),
    "duels_lost": (COUNT, "duelli persi", "mp"),
    "aerials_won": (COUNT, "duelli aerei vinti", "mp"),
    "aerials_lost": (COUNT, "duelli aerei persi", "mp"),
    "dribbled_past": (COUNT, "dribbling concessi all'avversario", "mp"),
    "tackles_won": (COUNT, "contrasti vinti", "mp"),
    "interceptions": (COUNT, "intercetti", "mp"),
    "ball_recoveries": (COUNT, "palloni recuperati", "mp"),
    "blocks": (COUNT, "conclusioni murate", "fp"),
    "clearances": (COUNT, "respinte", "fp"),
    "touches_in_box": (COUNT, "palloni toccati in area", "mp"),
    "passes_opp_half": (COUNT, "gioco nella meta' campo avversaria", "ms"),
    "long_balls_completed": (COUNT, "lanci lunghi riusciti", "mp"),
    "crosses_completed": (COUNT, "cross riusciti", "mp"),
    "passes_completed": (COUNT, "passaggi riusciti", "mp"),
    "was_fouled": (COUNT, "falli subiti", "mp"),
    "touches": (COUNT, "palloni giocati", "mp"),
    "errors_bad_passes": (COUNT, "passaggi sbagliati", "mp"),
    "errors_dispossessed": (COUNT, "palloni persi in conduzione", "mp"),
    "errors_miscontrols": (COUNT, "controlli sbagliati", "mp"),
    "errors_fouls_committed": (COUNT, "falli commessi", "mp"),
    "gk_goals_prevented": (COUNT, "gol evitati rispetto ai tiri affrontati", "mp"),
    "gk_saves": (COUNT, "parate", "fp"),
    "gk_saves_inside_box": (COUNT, "parate su tiri ravvicinati", "fp"),
    "gk_high_claims": (COUNT, "uscite alte", "fp"),
    "gk_punches": (COUNT, "respinte di pugno", "fp"),
    "gk_sweeper": (COUNT, "uscite fuori area", "fp"),
    "gk_crosses_not_claimed": (COUNT, "cross non trattenuti", "mp"),
    "_exposure": (COUNT, "pericolo concesso nella sua zona", "ms"),
    # Merged into SIGNAL lines below — labels kept for coverage, never phrased alone.
    "sga_post": (COUNT, "qualita' nelle conclusioni", "fp"),
    "xg_shots": (COUNT, "posizioni di tiro conquistate", "fp"),
    "shots_on_target": (COUNT, "tiri nello specchio", "mp"),
    "shots": (COUNT, "tiri tentati", "mp"),
    "shots_blocked": (COUNT, "conclusioni respinte dalla difesa", "fp"),
    "dribbles_won": (COUNT, "dribbling riusciti", "mp"),
    "dribbles_attempted": (COUNT, "dribbling tentati", "mp"),
}

# Feature families that describe ONE thing through several overlapping terms (a
# "good minus volume" net) and read as nonsense split apart ("Bene: tanti dribbling
# riusciti. Male: tanti dribbling tentati"; "Male: tante posizioni di tiro
# conquistate", because xg_shots is subtracted by design). Merged into a single
# SIGNAL line, phrased "una o più ..." by the sign of the net. Scoring untouched.
# (group_keys, phrase when net-positive, phrase when net-negative, family name.)
#
# The family NAME exists so the merge can be SEEN. Someone reading the full
# per-feature ledger who finds "una o più conclusioni pericolose +0.58" in the
# summary and no such row in the table below is entitled to suspect one of the two
# is wrong; the rows carrying this name are the ones that add up to it.
# La QUARTA frase e' quella di chi non ci ha nemmeno provato. Il netto della
# famiglia si sceglieva col solo segno, e con tutti i tiri a zero il segno e'
# negativo — la media di ruolo e' positiva — per cui la pagina diceva "una o piu'
# occasioni fallite" a chi non aveva tirato mai: il 43,1% delle spiegazioni della
# 25-26. Il valore ZERO non e' un esito peggiore, e' un esito ASSENTE, e va detto
# come tale: la penalizzazione c'e' davvero (il modello addebita il non-tiro) e
# tacerla la nasconderebbe dentro "altre voci".
MERGES = [
    (("sga_post", "xg_shots", "shots_on_target", "shots", "shots_blocked",
      "shots_off"),
     "una o più conclusioni pericolose", "una o più occasioni fallite",
     "conclusioni", "nessuna conclusione tentata"),
    (("dribbles_won", "dribbles_attempted"),
     "uno o più dribbling riusciti", "uno o più dribbling falliti",
     "dribbling", "nessun dribbling tentato"),
    # CREAZIONE: il merito del passaggio (xA) e il suo esito (assist) sono due voci
    # dello stesso gesto, e separate raccontavano la stessa cosa due volte — "una o
    # piu' occasioni create per i compagni" da una parte e "3 assist" dall'altra.
    # Unite dicono la storia intera in una riga, e la precisazione fra parentesi
    # porta i due numeri che stanno nel tabellino (v. ``creation_detail``).
    #
    # Il lato NEGATIVO e' None per la stessa ragione per cui lo era il SIGNAL da cui
    # viene: creare poco non e' una notizia da dire ad alta voce. Con phrase a None
    # la riga esce dal riassunto e resta nel registro col suo nome.
    (("expected_assists", "assists"),
     "una o più occasioni create per i compagni", None, "creazione", None),
    # LE PARATE: quanti tiri gli sono arrivati e come li ha gestiti sono lo stesso
    # gesto contato e pesato, e separate dicevano due volte la stessa cosa — "tanti
    # gol evitati rispetto ai tiri affrontati +0,37" nel riassunto e "3 parate
    # +0,01" trenta righe più sotto. Unite sono una riga sola, ed è quella che la
    # MAPPA DELLE PARATE apre (v. ``classic_pagella.save_detail``): la sezione somma
    # a questa riga, quindi ``_SAVE_FAMILY`` e questo gruppo devono restare la stessa
    # coppia di chiavi.
    #
    # Le frasi sono quelle che gk_goals_prevented aveva già da solo: la riga cambia
    # di che cosa è il netto, non come si legge. Il quarto caso — nessun tiro nello
    # specchio — capita davvero (31 presenze su 765 nella 25-26) e senza una frase
    # sua uscirebbe col segno del netto, che lì è negativo per costruzione.
    (("gk_goals_prevented", "gk_saves"),
     "tanti gol evitati rispetto ai tiri affrontati",
     "pochi gol evitati rispetto ai tiri affrontati",
     "parate", "nessun tiro nello specchio da respingere"),
]
# {feature: family name} — the same table read the other way round.
MERGE_FAMILY = {k: name for keys, _pos, _neg, name, _none in MERGES for k in keys}


# Come si chiamano, nel REGISTRO ESTESO, le voci che la frase parlata non nomina
# mai. Non sono le stesse di TABLE_ONLY_LABELS: quelle descrivono la feature a chi
# legge la tabella tecnica del tuner ("proxy sintetico"), queste vanno sotto gli
# occhi di chi ha appena aperto il dettaglio di un voto.
#
# ``defensive_value`` e' il caso che ha motivato tutto questo, ed e' uscito di qui
# il 24/08/2026: la soluzione vera non era battezzarlo nel registro, era dargli una
# frase parlata (v. LABELS) — se e' la voce piu' grande del voto di un difensore
# deve stare nel riassunto, non sotto la riga ripiegata. Qui resta chi una frase
# non ce l'ha e nel registro un nome deve averlo lo stesso.
LEDGER_LABELS = {
    # Il lato negativo del SIGNAL e' None per scelta (creare poco non e' una
    # notizia da dire ad alta voce): nel registro la riga c'e' lo stesso, quindi
    # serve il sostantivo neutro, che col numero negativo accanto si legge bene.
    "expected_assists": "occasioni create per i compagni",
    "shots_off": "tiri fuori",
}


# --- I GRUPPI DEL REGISTRO ----------------------------------------------------
# Aprendo "altre N voci" si trovavano trenta righe, la meta' delle quali da 0.01,
# e la loro somma non si leggeva: il lettore vedeva un elenco, non una spiegazione.
# Qui le stesse righe stanno in sei famiglie con un subtotale ciascuna, e il
# dettaglio si apre solo dove serve.
#
# I gruppi seguono il SENSO, non i pesi: chi legge cerca "come ha difeso" e "quanti
# palloni ha perso", non "quali feature hanno peso negativo". Le famiglie gia'
# unite nel riassunto (conclusioni, dribbling, creazione) restano una riga sola e
# vanno nel loro gruppo per intero.
LEDGER_GROUPS = (
    ("conclusioni", "Conclusioni",
     ("sga_post", "xg_shots", "shots_on_target", "shots", "shots_off",
      "shots_blocked", "shots_goal", "shots_post")),
    ("creazione", "Creazione",
     ("expected_assists", "assists", "key_passes", "big_chance_created",
      "big_chance_missed")),
    ("duelli", "Duelli",
     ("duels_won", "duels_lost", "aerials_won", "aerials_lost", "dribbles_won",
      "dribbles_attempted", "was_fouled", "penalties_won")),
    ("difesa", "Difesa",
     ("defensive_value", "tackles_won", "interceptions", "ball_recoveries",
      "blocks", "clearances", "clearances_off_line", "last_man_tackle",
      "dribbled_past", EXPOSURE_KEY)),
    ("possesso", "Possesso e passaggi",
     ("passes_completed", "passes_opp_half", "long_balls_completed",
      "crosses_completed", "touches", "touches_in_box")),
    ("errori", "Errori",
     ("errors_bad_passes", "errors_dispossessed", "errors_miscontrols",
      "errors_fouls_committed", "errors_led_to_goal", "errors_led_to_shot",
      "penalties_conceded")),
    # "Porta" da solo non si legge: accanto a "Difesa" e "Errori" sembra un verbo,
    # e comunque nomina il posto invece del mestiere. Qui dentro ci sono i GESTI del
    # portiere — parate, uscite, pugni — e il titolo li dice.
    ("portiere", "Parate e uscite",
     ("gk_goals_prevented", "gk_saves", "gk_saves_inside_box", "gk_high_claims",
      "gk_punches", "gk_sweeper", "gk_crosses_not_claimed", "gk_penalty_saves")),
)
# {feature: (chiave del gruppo, titolo)} — la stessa tabella letta al contrario.
GROUP_OF = {k: (key, title) for key, title, keys in LEDGER_GROUPS for k in keys}
# Le famiglie unite portano il nome della famiglia, non quello della prima feature.
GROUP_OF_FAMILY = {"conclusioni": ("conclusioni", "Conclusioni"),
                   "dribbling": ("duelli", "Duelli"),
                   "creazione": ("creazione", "Creazione"),
                   "parate": ("portiere", "Parate e uscite")}


def group_ledger(rows: list[dict]) -> list[dict]:
    """Le righe del registro raccolte per senso, con il subtotale di ognuna.

    Ordinati per PESO ASSOLUTO del gruppo, non per l'ordine della tabella: chi apre
    il dettaglio vuole sapere prima che cosa ha mosso il voto. Dentro il gruppo
    resta l'ordine per punti che le righe avevano gia'.
    """
    buckets: dict[str, dict] = {}
    for row in rows:
        key, title = (GROUP_OF_FAMILY.get(row.get("family"))
                      or GROUP_OF.get(row.get("key"))
                      or ("altro", "Altro"))
        b = buckets.setdefault(key, {"key": key, "title": title,
                                     "points": 0.0, "terms": []})
        b["points"] += row.get("points", 0.0)
        b["terms"].append(row)
    for b in buckets.values():
        b["points"] = round(b["points"], 2)
    return sorted(buckets.values(), key=lambda b: -abs(b["points"]))


def _weight_of(role: str, key: str) -> float:
    if key == EXPOSURE_KEY:
        return -EXPOSURE_WEIGHT
    return (GK_WEIGHTS if role == Player.ROLE_GK else WEIGHTS).get(key, 0.0)


def _phrase(role: str, key: str, term_delta: float, raw_value: float,
            count: float | None = None) -> str | None:
    """How to name this deviation, or None when it is not worth saying."""
    entry = LABELS.get(key)
    if entry is None:
        return None
    kind = entry[0]
    if kind == EVENT:
        # Only when it happened, with the real count: three last-man tackles are
        # "3 interventi da ultimo uomo", not "un intervento".
        n = int(round(raw_value))
        if n <= 0:
            return None
        return entry[1] if n == 1 else f"{n} {entry[2]}"
    # ``more`` is whether the raw value is ABOVE the role average — a negative-weighted
    # feature improves the index by being SMALLER, so the raw direction is the
    # term-delta sign flipped by the weight's own sign.
    more = (term_delta > 0) == (_weight_of(role, key) > 0)
    if kind == SIGNAL:
        # "una o più ..." — the noun carries the sense; the negative side may be
        # None (nothing worth saying, e.g. below-average creation).
        return entry[1] if more else entry[2]
    # COUNT a ZERO: non e' "poco", e' NIENTE — e i due lati non si dicono allo
    # stesso modo.
    #
    # Se lo zero pesa CONTRO (una cosa utile che non ha fatto) va nominato per quel
    # che e': "nessun duello vinto". "pochi duelli vinti" implica che qualcuno
    # l'abbia vinto, e chi va a cercarlo nel tabellino non lo trova.
    #
    # Se invece lo zero pesa A FAVORE (una cosa dannosa che non ha fatto) si TACE.
    # "Bene: pochi duelli persi" a chi non e' mai entrato in un duello lo elogia per
    # un merito che non ha: sulla 25-26 era l'UNICO lato positivo di 449
    # spiegazioni. I punti restano, e finiscono in "altre voci" come ogni voce non
    # mostrata, quindi il conto torna lo stesso.
    if abs(raw_value) < 0.005:
        if term_delta > 0:
            return None
        none_phrase = COUNT_NONE.get(key)
        if none_phrase:
            return none_phrase
    # POCHE UNITA': si scrive il numero, non "tanti" (v. COUNT_SAY_NUMBER_UPTO).
    # ``count`` e' quello OSSERVATO e lo passa solo chi ce l'ha (il registro):
    # ``raw_value`` per il blocco volumi e' la proiezione sui 90', e "tanti falli
    # commessi · 1,3" non lo puo' verificare nessuno.
    if count is not None and 1 <= round(count) <= COUNT_SAY_NUMBER_UPTO:
        n = int(round(count))
        sing = _singular_of(key)
        if sing:
            # "solo" quando e' SOTTO la media del ruolo — il numero nudo perde la
            # direzione che il quantificatore portava, e senza di essa "3 duelli
            # persi" accanto a un +0,02 sembra una contraddizione. Sopra la media
            # non serve niente: "1 fallo commesso" con un meno accanto si legge
            # da solo, e "ben 1 passaggio chiave" sarebbe ridicolo.
            testa = f"{n} {sing}" if n == 1 else f"{n} {entry[1]}"
            return testa if more else f"solo {testa}"
    # COUNT: absolute quantifier vs the role average (the implicit yardstick).
    label, quant = entry[1], entry[2]
    high, low = QUANTIFIERS.get(quant, QUANTIFIERS["mp"])
    return f"{high if more else low} {label}"


def creation_detail(phrase: str, big_chances: float, xa: float = 0.0,
                    assists: float = 0.0) -> str:
    """Ancora la riga della xA a un numero che sta nel tabellino, nei due versi.

    ``expected_assists`` e' un SIGNAL, quindi si dice "una o piu' occasioni create":
    vago per necessita', perche' un valore atteso non ha un intero da contare. Ma
    ``big_chance_created`` un intero ce l'ha, ed e' il fatto piu' verificabile della
    partita di chi crea. Il suo peso ZERO (v. TOTAL_WEIGHTS) dice quanto quel dato
    VALE nel voto, non se possiamo USARLO per raccontarlo: i punti della riga
    restano interamente della xA, il conteggio la rende leggibile. Va in parentesi
    proprio per questo — e' una precisazione, non un secondo addendo.

    IL VERSO NEGATIVO distingue due partite che la sola xA confonde: tanti palloni
    discreti e una palla-gol vera valgono uguale in valore atteso e non sono la
    stessa prestazione. Si dice SOLO sopra ``ASSIST_LOW_XA``, cioe' dove la riga
    della creazione e' gia' sostanziosa e l'assenza e' una notizia: 613 presenze
    sulla 25-26, il 3.4% del totale, contro le 609 che ricevono il conteggio. Sotto
    quella soglia "nessuna nitida" non informa nessuno, e resta taciuto.

    Il gol che ne e' nato NON si nomina, in nessuno dei due versi: la qualita'
    dell'occasione e' una proprieta' del passaggio, l'esito no, e metterlo sulla
    riga del merito confonderebbe la distinzione su cui il modello e' costruito."""
    if not phrase:
        return phrase
    parti = []
    n = int(round(big_chances or 0))
    if n >= 1:
        parti.append("una nitida" if n == 1 else f"{n} nitide")
    elif xa >= ASSIST_LOW_XA:
        parti.append("nessuna nitida")
    a = int(round(assists or 0))
    if a >= 1:
        parti.append("un assist" if a == 1 else f"{a} assist")
    return f"{phrase} ({', '.join(parti)})" if parti else phrase


# Sopra quanti si puo' dire "tanti". Un quantificatore confronta con la media del
# ruolo, e su un numero piccolo quel confronto produce frasi assurde: "tanti falli
# commessi · 1" dice "molti" di UNO. Su Malen (tripletta col Milan) sei righe su 23
# erano cosi'. Fino a questa soglia si scrive il numero, che e' preciso e non
# discutibile; sopra torna il quantificatore, che li' porta l'informazione in piu'
# ("tanti palloni giocati · 37" dice qualcosa che "37" da solo non dice).
COUNT_SAY_NUMBER_UPTO = 3

# Grandezze che NON si contano: indici normalizzati e valori attesi. Accanto a
# queste il numero non va mai scritto — "pericolo concesso nella sua zona · 0" su
# un'esposizione di 0,004 afferma una precisione che non c'e', e "valore difensivo
# · 0" non spiega niente. La regola c'era gia' nell'intento (v. il commento nel
# registro) ma il test "e' quasi intero" lasciava passare proprio i quasi-zero.
CONTINUOUS_KEYS = frozenset({
    EXPOSURE_KEY, "defensive_value", "sga_post", "expected_assists",
    "xg_shots", "xg_on_target", "gk_goals_prevented", "touches_in_box",
})


def _singular_of(key: str) -> str:
    """"fallo commesso" da "nessun fallo commesso" — il singolare esiste gia' in
    COUNT_NONE, che e' l'unico posto in cui la tabella lo dichiara."""
    none = COUNT_NONE.get(key)
    if not none:
        return ""
    for neg in ("nessun'", "nessuna ", "nessuno ", "nessun "):
        if none.startswith(neg):
            return none[len(neg):]
    return ""


def _never_happened(entry) -> str:
    """"nessun gol", "nessun'occasione nitida creata" — un EVENT che NON e'
    successo. Nella frase parlata questi non si dicono (``_phrase`` restituisce
    None: elencare cio' che uno non ha fatto e' rumore), ma nel registro la riga
    esiste, con i suoi punti — un difensore che non segna perde il piccolo credito
    che il difensore medio prende dai gol, ed e' giusto poterlo leggere.

    Il genere viene dall'articolo del singolare, che e' l'unico posto in cui la
    tabella LABELS lo dichiara: "un gol" -> "nessun gol", "un'occasione nitida
    creata" -> "nessun'occasione nitida creata"."""
    singular = entry[1]
    for art, neg in (("un'", "nessun'"), ("uno ", "nessuno "), ("un ", "nessun ")):
        if singular.startswith(art):
            return neg + singular[len(art):]
    return f"nessun {entry[2]}"


def ledger_phrase(role: str, key: str, term_delta: float, raw_value: float,
                  count: float | None = None) -> str:
    """Il nome della voce nel REGISTRO ESTESO, dove tutto va nominato.

    ``_phrase`` puo' tacere — e tace apposta — su tre casi: un evento che non e'
    successo, il lato negativo di un SIGNAL, e le feature senza riga in LABELS. Nel
    riassunto quel silenzio e' giusto; nel registro no, perche' li' la riga c'e' e
    mostra i suoi punti, e una riga senza nome e' esattamente il buco da cui e'
    nata questa funzione."""
    said = _phrase(role, key, term_delta, raw_value, count)
    if said:
        return said
    entry = LABELS.get(key)
    if entry is not None and entry[0] == EVENT:
        return _never_happened(entry)
    # Uno ZERO che il riassunto ha taciuto (lodare un'assenza e' rumore) nel
    # registro la riga ce l'ha lo stesso, e li' si chiama col suo nome invece che
    # col sostantivo nudo: "nessun duello perso" batte "duelli persi 0".
    if (entry is not None and entry[0] == COUNT and abs(raw_value) < 0.005
            and key in COUNT_NONE):
        return COUNT_NONE[key]
    return LEDGER_LABELS.get(key) or readable_label(key) or key


# Come si chiamano nella TABELLA TECNICA, dove accanto stanno il valore, il peso e
# la sigma: li' serve un NOME, non un giudizio. ``defensive_value`` una frase
# parlata adesso ce l'ha (v. LABELS), ma "buona prestazione difensiva d'insieme"
# come intestazione di riga risponderebbe a una domanda invece di dire di che cosa
# si sta leggendo il peso; ``shots_off`` una frase parlata non ce l'ha affatto,
# perche' compare solo dentro la riga unita delle conclusioni.
TABLE_ONLY_LABELS = {
    "defensive_value": "indice difensivo sintetico",
    "shots_off": "tiri fuori",
}


def red_card_phrase(detail: dict | None) -> str:
    """"espulsione al 63' per condotta violenta (27' in dieci)" — the three things
    that set the size of the drop: WHY (severity), WHEN, and for HOW LONG the team
    then played a man short. Falls back to the bare word when we have no detail."""
    if not detail:
        return "espulsione"
    reason = RED_REASON_IT.get(detail.get("reason") or "", "")
    if detail.get("second_yellow"):
        reason = f"{reason} (secondo giallo)" if reason else "secondo giallo"
    minute = detail.get("minute")
    down = detail.get("man_down")
    parts = ["espulsione"]
    if minute is not None:
        parts.append(f"al {int(round(minute))}'")
    if reason:
        parts.append(f"per {reason}")
    if down:
        parts.append(f"({int(round(down))}' in dieci)")
    return " ".join(parts)


def own_goal_phrase(detail: dict | None) -> str:
    """An own goal turned in off him and an own goal he made himself are the same
    event in the scoreline and different events in a vote — the drop differs by a
    factor of 2.5, so the reason has to travel with it."""
    if not detail:
        return "autogol"
    n = detail.get("count") or 1
    head = "autogol" if n == 1 else f"{n} autogol"
    kind = detail.get("kind")
    if kind == "deflection":
        return f"{head} su deviazione"
    if kind == "solo":
        return f"{head} in prima persona"
    return head          # ungraded: no sub-minute timing, we claim nothing


def assist_note(assists: int, xa: float, big_chances: float) -> str:
    """Why an assist can leave the base vote where it was.

    Not a claim about the finisher — measured on the case that prompted it (McKennie,
    g14) the scorer's own shot quality was only +0.67σ, so "he did the exceptional
    thing" would be inventing a merit. What IS measurable is the pass: an xA of 0.05
    is a ball that did not, by itself, make a goal likely.

    IL NUMERO E' DI TUTTA LA PARTITA, non dei passaggi da assist — per questo la
    frase lo dice di "i suoi passaggi" e non li' accanto all'assist. Nel gruppo che
    riceve questa nota il 75% ha passaggi chiave OLTRE agli assist, mediana 3 contro
    1: isolare la xA del singolo passaggio da assist non si puo', ``MatchShot`` non
    porta il passatore.

    LA NOTA SIMMETRICA E' STATA TOLTA il 25/08/2026, con la ritaratura. Diceva che
    il passaggio valeva ma "non risulta un'occasione nitida", e aveva senso finche'
    ``big_chance_created`` pesava: era la voce mancante che spiegava un credito
    dimezzato. Ora quel peso e' ZERO — e dal 01/09/2026 lo e' anche ``key_passes``:
    la creazione la legge la sola xA, che un Diouf ce l'ha — quindi non c'e' piu'
    niente che non abbia pagato, e la nota avrebbe spiegato un meccanismo che non
    esiste. Il caso che la motivava (Inter-Monza, 2 assist e 6.0) adesso e' 6.5
    senza bisogno di scuse."""
    # ``big_chances > 0`` continua a zittire la nota, ma per un'ALTRA ragione da
    # quando quel peso e' zero: non piu' "il voto l'ha gia' pagata", bensi' che le
    # due prove si contraddicono. Se chi fornisce i dati ha riconosciuto
    # un'occasione nitida, dare del pallone "di poco valore" allo stesso passaggio
    # sceglie una delle due prove e nasconde l'altra. Sono 131 presenze sulle 300
    # con assist e xA bassa: meglio tacere che scegliere.
    if assists < 1 or big_chances > 0 or xa >= ASSIST_LOW_XA:
        return ""
    # Corta apposta: viaggia dentro ``to_sentence``, che nel dettaglio partita e'
    # una riga sola, e chi ha fatto anche autogol ha gia' due clausole davanti.
    #
    # NON dice piu' ne' "conta come bonus, non nel voto base" ne' "il voto base
    # legge il pallone, non il gol". La nota si limita al fatto — il pallone valeva
    # poco — e lascia che siano le righe a mostrare quanto ha fruttato: l'assist ha
    # la sua voce, nominata, graduata dal ΔxP del gol che ne e' nato.
    #
    # AGGIORNATO col 01/09/2026: ``key_passes`` e ``assists`` pesano ORA ZERO
    # nell'indice (v. TOTAL_WEIGHTS), quindi il voto base legge la creazione con la
    # sola xA — che e' esattamente il numero di cui questa nota parla. La frase
    # regge meglio di prima, non peggio: dice che il valore atteso del pallone era
    # basso, ed e' l'unica cosa che il voto base abbia guardato.
    head = f"I suoi passaggi valgono {xa:.2f} di xA"
    if assists == 1:
        return f"{head}: l'assist nasce da un pallone di poco valore."
    return f"{head}: gli assist nascono da palloni di poco valore."


def readable_label(key: str) -> str:
    """The feature's name in words, for a table that also shows its technical name.

    Deliberately the NOUN and not the phrasing ``_phrase`` builds: a sentence wants
    "tanti duelli vinti", a table column wants "duelli vinti".

    TABLE_ONLY_LABELS ha la precedenza dove c'e': una feature puo' avere una frase
    parlata E un nome tecnico diversi, e in una colonna di tabella il giudizio
    ("buona prestazione difensiva d'insieme") non e' un nome, e' una risposta."""
    table = TABLE_ONLY_LABELS.get(key)
    if table:
        return table
    entry = LABELS.get(key)
    if entry is None:
        return ""
    return entry[2] if entry[0] == EVENT else entry[1]


def _all_terms(role: str, terms: dict, mean_terms: dict, unit_of, 
               totals: dict, minutes: int, exposure: float) -> list[dict]:
    """Every feature of the channel, in the terms the weight tables use.

    Same numbers as the summary breakdown, only nothing merged and nothing folded
    into "altre voci": one row per weighted feature, with its technical name (the
    one in the tuner spreadsheet), what the player did, where that sits on the
    population scale, its weight, and what it moved the vote by. The rows sum to
    (voto − 6) exactly, because they are the same slices ``explain`` shows — see the
    reconciliation note in ``explain``."""
    is_gk = role == Player.ROLE_GK
    weights = dict(GK_WEIGHTS if is_gk else WEIGHTS)
    total_keys = set(GK_TOTAL_WEIGHTS if is_gk else TOTAL_WEIGHTS)
    if not is_gk:
        weights[EXPOSURE_KEY] = -EXPOSURE_WEIGHT
    scales = feature_scales(gk=is_gk)
    values = raw_feature_values(totals, minutes, exposure, gk=is_gk)

    out = []
    for key, w in weights.items():
        # Zero-weight features ARE listed: a weight deliberately set to zero (see
        # last_man_tackle) is a decision, and a table that silently dropped it would
        # hide the decision instead of showing it. It contributes 0 to every column
        # that feeds the vote, so nothing else changes.
        value = values.get(key, 0.0)
        kind = ("EXPOS" if key == EXPOSURE_KEY
                else "DERIV" if key in DERIVED_FEATURES
                else "TOT" if key in total_keys else "PER90")
        # The exposure and the credited counts are standardised ASYMMETRICALLY
        # (EXPOSURE_CREDIT / ABSENCE_CREDIT), so the σ has to be read through the
        # same function the index used — otherwise the row shows a σ that does not
        # produce the contribution printed beside it.
        z = scored_z(key, value, scales)
        out.append({
            "key": key,
            "label": readable_label(key),
            "kind": kind,
            # the merged family this feature belongs to, if any: the summary shows
            # one line for all of them, and this is how the two views match up
            "family": MERGE_FAMILY.get(key, ""),
            # For a COUNTED event, what ONE occurrence is worth on the index — the
            # only readable unit for something that happens in 1% of matches, where
            # a σ is a fraction of an occurrence and a per-σ weight reads ten times
            # smaller than it acts. See the note on last_man_tackle.
            "event": (LABELS.get(key) or (None,))[0] == EVENT,
            # NB: il z GREZZO di una occorrenza, senza il credito per l'assenza —
            # e' consumato solo per le voci EVENT (tuner, benchmark) e nessuna
            # delle CREDITED_FEATURES lo e' (sono tutte 'count').
            "z_one": round(_feature_z(key, 1.0, scales), 3),
            "value": round(value, 3),
            "z": round(z, 3),
            "weight": round(w, 4),
            # w·z: what the feature puts into the index, in index points
            "index": round(terms.get(key, 0.0), 4),
            # the same for the AVERAGE player in this role — the yardstick, because
            # what explains a 6.5 rather than a 6 is only the departure from peers
            "index_avg": round(mean_terms.get(key, 0.0), 4),
            "points": round((terms.get(key, 0.0) - mean_terms.get(key, 0.0)) * unit_of(key), 3),
        })
    # Left in the order of the weight tables — the same order the tuner spreadsheet
    # lists them in, so a row here can be found there. Callers that want the drivers
    # first sort by ``points`` themselves.
    return out


def _terms(role: str, totals: dict, minutes: int, exposure: float = 0.0,
           scales: dict | None = None) -> dict:
    """Each feature's contribution to the index, before comparison to the role mean.

    Reads the feature values and the standardisation from ``classic_rating`` rather
    than repeating them: the breakdown has to reconcile to the vote exactly, so any
    divergence between the two pipelines would show up as a broken explanation."""
    if minutes <= 0:
        return {}
    is_gk = role == Player.ROLE_GK
    # weights_for_role, non WEIGHTS: dal 25/08/2026 un peso dipende dal ruolo
    # (ROLE_WEIGHTS), e una spiegazione costruita sul vettore globale non
    # tornerebbe col voto che spiega.
    weights = weights_for_role(role)
    if scales is None:
        scales = feature_scales(gk=is_gk)
    elif "outfield" in scales or "gk" in scales:
        scales = scales.get("gk" if is_gk else "outfield", {})
    values = raw_feature_values(totals, minutes, exposure, gk=is_gk)
    out = {}
    for key, w in weights.items():
        if not w:
            continue
        z = scored_z(key, values.get(key, 0.0), scales)
        if z:
            out[key] = w * z
    if not is_gk:
        # exposure_z, not _feature_z: the asymmetric credit (EXPOSURE_CREDIT) is
        # part of what the index consumed, so the breakdown must apply it too.
        z = exposure_z(values.get(EXPOSURE_KEY, 0.0), scales)
        if z:
            out[EXPOSURE_KEY] = -EXPOSURE_WEIGHT * z
    return out


def role_average_terms(rows, scales: dict | None = None) -> dict:
    """{role: {feature: mean contribution}} — the yardstick every explanation is
    read against. ``rows`` is an iterable of (role, totals, minutes, exposure)."""
    sums: dict[str, dict[str, float]] = {}
    counts: dict[str, int] = {}
    for role, totals, minutes, exposure in rows:
        terms = _terms(role, totals, minutes, exposure, scales)
        if not terms:
            continue
        bucket = sums.setdefault(role, {})
        for key, value in terms.items():
            bucket[key] = bucket.get(key, 0.0) + value
        counts[role] = counts.get(role, 0) + 1
    return {role: {k: v / counts[role] for k, v in bucket.items()}
            for role, bucket in sums.items()}


# Sotto quanti minuti il pannello avverte "con pochi minuti giocati ogni voce pesa
# meno". Era ``SHRINKAGE_MINUTES * 2``, cioe' 50; dal 03/09/2026 lo shrinkage del
# movimento e' 90 e quella formula avrebbe messo l'avvertenza sotto i 180 minuti,
# cioe' SEMPRE. La soglia e' una scelta di prodotto — "quando vale la pena avvisare"
# — e non ha ragione di seguire una costante del modello: sta qui, per conto suo.
SHORT_APPEARANCE_MINUTES = 50


def explain(role: str, totals: dict, minutes: int, reference: dict,
            averages: dict, exposure: float = 0.0, *, top: int = 3,
            result_nudge: float = 0.0, red_adjustment: float = 0.0,
            own_goal_adjustment: float = 0.0, penalty_adjustment: float = 0.0,
            goal_adjustment: float = 0.0, goal_detail: list | None = None,
            assist_adjustment: float = 0.0, assist_detail: list | None = None,
            scale_factor: float = 1.0, scale_base: float | None = None,
            full: bool = False,
            ledger: bool = False,
            red_detail: dict | None = None, own_goal_detail: dict | None = None,
            assists: int = 0) -> dict:
    """Why this vote, decomposed so it ADDS UP to the vote.

    The vote is 6 + spread * shrink * (index - role_mean) / std. Every feature is
    a slice of that (index - role_mean), so once converted to vote points the
    slices sum to (vote - 6) exactly — as long as the yardstick the explanation
    subtracts is the SAME role mean the vote uses. It was not: the vote's mean
    came from build_reference (players over the minutes threshold), the
    explanation's from every appearance, and the two disagreed, so the numbers
    could never reconcile. get_role_averages now filters to match.

    Returns an additive breakdown: ``base`` (6), the largest ``contributions`` in
    vote points, an ``other`` bucket folding the long tail of small ones, and the
    resulting ``voto`` — so 6 + contributions + other rounds to the vote. A short
    appearance shrinks every slice toward zero (little evidence), which is why a
    cameo's terms are all small: that is the honest reason, not a rounding quirk.
    """
    terms = _terms(role, totals, minutes, exposure)
    ref = reference.get(role)
    if not terms or not ref or not ref.get("std"):
        return {"positives": [], "negatives": [], "contributions": [],
                "all_terms": [], "other_terms": [],
                "other_tiny": {"count": 0, "points": 0.0},
                "assist_note": "", "base": (scale_base if scale_base is not None
                                            else vote_center_for(role)),
                "other_points": 0.0, "other_count": 0, "minutes": minutes,
                "low_minutes": False, "flat": False, "note": ""}

    mean_terms = averages.get(role, {})
    # Lo stesso restringimento che applica il voto: quanto ha giocato. Scala ogni
    # fetta, cosi' la scomposizione continua a tornare col voto scritto sopra.
    weight = (minutes / (minutes + shrinkage_for(role)) if minutes > 0 else 0.0)
    # spread_k_for, non VOTE_SPREAD_K: dal 29/08/2026 il portiere ha la sua scala
    # (GK_SPREAD_K 0.8 contro 0.727), e una spiegazione costruita sulla scala di
    # movimento comprimeva ogni fetta del 9,1% — cioe' raccontava a un portiere un
    # voto piu' vicino al 6 di quello scritto accanto al suo nome.
    # LO STADIO FINALE, RICAVATO QUI se il chiamante non l'ha passato. Era un
    # parametro con default 1.0, e il default produceva un pannello incoerente col
    # proprio totale: le fette non riscalate sotto un voto che invece lo era. Il
    # fattore non e' un'opzione, e' una proprieta' della presenza — quindi si
    # calcola, e il parametro serve solo a riusare quello gia' calcolato dallo
    # scorer (stesso numero, una moltiplicazione in meno).
    if scale_base is None:
        _pre = _raw_vote_from_index(
            index_for_role(role, totals, minutes, exposure), role, minutes, reference,
            observed=observed_index(role, totals, minutes, exposure))
        _pre = max(VOTE_MIN, min(VOTE_MAX, _pre + goal_adjustment + assist_adjustment))
        _pre = max(VOTE_MIN, min(VOTE_MAX, _pre + result_nudge + red_adjustment
                                 + own_goal_adjustment + penalty_adjustment))
        _fin, scale_factor = scale_saturation(_pre, role)
        scale_base = _fin - scale_factor * (_pre - vote_center_for(role))
    # ``scale_factor``: lo stadio finale del voto (classic_rating.scale_saturation)
    # comprime il lato alto e riapre la dispersione, e lo fa DOPO che le voci sono
    # state sommate. Una scomposizione additiva non lo puo' rappresentare come una
    # voce a se': o si riscala ogni fetta, o la somma non torna col voto scritto
    # sopra. Riscalando, l'utente legge direttamente i valori giusti e non c'e'
    # nessuna riga misteriosa in fondo da spiegare.
    per_unit = scale_factor * spread_k_for(role) * weight / ref["std"]
    # I FATTI OSSERVATI HANNO LA LORO SCALA, perche' il voto non li attenua (v.
    # classic_rating.UNSHRUNK_FEATURES): un gol segnato entrando all'85' pesa
    # nel pannello quanto pesa nel voto, non un terzo. Senza questa riga la fetta
    # mostrata sarebbe piu' piccola del suo effetto e la differenza finirebbe,
    # muta, dentro «altre N voci».
    per_unit_obs = scale_factor * spread_k_for(role) / ref["std"]
    unit_of = (lambda key: per_unit_obs if key in UNSHRUNK_FEATURES else per_unit)

    points_by_key = {key: (terms.get(key, 0.0) - mean_terms.get(key, 0.0)) * unit_of(key)
                     for key in set(terms) | set(mean_terms)}

    # The full ledger, before the families are merged and the tail folded away —
    # every feature the channel weighs, named as the weight tables name it. Only
    # built on request: it is four times the size of the vote it explains, which is
    # fine for an analysis page and wasteful in a match-detail API response.
    all_terms = (_all_terms(role, terms, mean_terms, unit_of, totals, minutes,
                            exposure) if full else [])

    # The raw value the phrasing quotes comes from the SAME builder the index uses,
    # so a derived feature (sga_post) or the exposure is quoted as what it actually
    # is, not looked up in a totals dict that has never heard of it. Letto PRIMA
    # delle famiglie, che ne hanno bisogno: senza guardare i valori non si distingue
    # "ha tirato male" da "non ha tirato".
    raw_values = raw_feature_values(totals, minutes, exposure,
                                    gk=role == Player.ROLE_GK)

    per90_keys = set(GK_PER90_WEIGHTS if role == Player.ROLE_GK else PER90_WEIGHTS)

    def observed(key):
        """Quante volte l'ha fatto DAVVERO. None per le grandezze che non si
        contano: il ramo numerico non deve toccarle."""
        if key in CONTINUOUS_KEYS:
            return None
        return totals.get(key, 0.0) if key in per90_keys else raw_values.get(key, 0.0)

    # L'ASSIST HA GIA' UNA RIGA SUA? Allora la parentesi della creazione NON ripete
    # il conteggio. Con la riga d'impatto accesa il pannello di Dybala (Roma-Bologna)
    # diceva "3 assist +0.50" e subito sotto "una o piu' occasioni create per i
    # compagni (3 nitide, 3 assist) +0.83": due numeri diversi accanto alle stesse
    # tre parole, che si legge come un doppio pagamento. Non lo e' — ``assists``
    # pesa ZERO nell'indice (v. TOTAL_WEIGHTS), quindi quei +0.83 sono tutti di xA e
    # i +0.50 sono il ΔxP dei gol che ne sono nati — ma la riga da sola non lo puo'
    # spiegare, e la parentesi serviva ad ancorare la xA a un numero verificabile
    # proprio quando quel numero non era gia' scritto una riga piu' su.
    #
    # Le occasioni nitide restano: quelle una riga loro non ce l'hanno.
    assist_line = abs(assist_adjustment * scale_factor) >= 0.005 and bool(assist_detail)

    scored = []
    # Collapse the overlapping feature families (see MERGES) into one net line each.
    # ``family`` travels with the line so a reader can find the rows it stands for.
    for group, label_pos, label_neg, family, label_none in MERGES:
        present = [k for k in group if k in points_by_key]
        net = sum(points_by_key.pop(k, 0.0) for k in group)
        if abs(net) >= 1e-9:
            # Il segno non basta: se in tutta la famiglia non c'e' un solo tentativo,
            # il netto e' negativo soltanto perche' il pari ruolo medio qualcosa fa.
            # Vedi la nota su MERGES.
            attempted = sum(abs(raw_values.get(k, 0.0)) for k in group)
            phrase = (label_none if attempted < 0.005
                      else label_pos if net > 0 else label_neg)
            if family == "creazione" and phrase:
                phrase = creation_detail(
                    phrase, raw_values.get("big_chance_created", 0.0),
                    raw_values.get("expected_assists", 0.0),
                    0.0 if assist_line else raw_values.get("assists", 0.0))
            scored.append((net, group[0], phrase, (family, len(present))))
    for key, pts in points_by_key.items():
        phrase = _phrase(role, key, pts, raw_values.get(key, 0.0), observed(key))
        scored.append((pts, key, phrase, None))

    # The subtotal is the vote's OWN raw value, computed exactly as the scorer
    # computes it (index z-scored against the reference mean), not re-derived from
    # the sum of slices — otherwise float drift near a rounding boundary would let
    # the explanation show a different vote than the one on the row. The "other"
    # line then absorbs whatever the shown slices don't account for, so the visible
    # numbers still reconcile to this subtotal.
    #
    # E «esattamente come lo calcola lo scorer» vuol dire CHIAMANDO LO SCORER, non
    # riscrivendone la formula qui: la copia era rimasta indietro di una scala (il
    # portiere, GK_SPREAD_K) e le stesse operazioni in ordine diverso divergevano
    # comunque sull'ultimo bit, che sulla griglia dei mezzi punti vale mezzo voto.
    # Le fette qui sopra restano una scomposizione dell'indice; il NUMERO viene da
    # una funzione sola, che e' quella che ha scritto il voto sulla riga.
    # vote_center_for, non VOTE_CENTER: il centro dipende dal ruolo (v.
    # ROLE_VOTE_CENTER), e una spiegazione che partisse dal 6 per tutti mostrerebbe
    # un "altre N voci" gonfio dell'offset invece del vero resto.
    # IL VOTO DI PARTENZA, non piu' il centro secco del ruolo. Il minutaggio spiega
    # gia' una parte dell'indice (v. classic_rating.MINUTE_CONDITIONING) e quella
    # parte non e' merito di nessuno: sta qui dentro, cosi' le voci qui sotto
    # restano tutte e sole cio' che il giocatore ha aggiunto. E' anche il modo di
    # dirlo senza spiegarlo — il numero di partenza e' gia' quello giusto.
    centre = vote_center_for(role) - spread_k_for(role) * (
        weight * minute_shift(role, minutes, reference)
        + (1.0 - weight) * minute_shift(role, minutes, reference,
                                        "observed_by_minute", "observed_mean")
    ) / ref["std"]
    # La base nella scala finale. Il voto grezzo parte da ``vote_center_for``, ma lo
    # stadio finale comprime attorno a un ALTRO punto (il baricentro misurato del
    # ruolo): la differenza fra i due, riscalata, e' una costante che appartiene alla
    # base. Dimenticarla sposta la scomposizione di quella costante, e le voci
    # sembrano non tornare col voto senza che si capisca perche'.
    centre = ((scale_base if scale_base is not None else vote_center_for(role))
              + scale_factor * (centre - vote_center_for(role)))
    raw = _raw_vote_from_index(
        index_for_role(role, totals, minutes, exposure), role, minutes, reference,
        observed=observed_index(role, totals, minutes, exposure))
    # Same order as the scorer: clamp the merit vote, add the (divergence-only)
    # result nudge, the red-card drop and the own-goal drop, then clamp back.
    # Stesso ordine dello scorer: il credito dei GOL entra nel voto grezzo (e' merito,
    # quindi la mitigazione del risultato deve poterlo temperare), poi il resto.
    raw = max(VOTE_MIN, min(VOTE_MAX, raw + goal_adjustment + assist_adjustment))
    subtotal = max(VOTE_MIN, min(VOTE_MAX,
                   raw + result_nudge + red_adjustment + own_goal_adjustment
                   + penalty_adjustment))
    # ...e poi lo stadio finale, esattamente dove lo mette lo scorer.
    subtotal = max(VOTE_MIN, min(VOTE_MAX, scale_saturation(subtotal, role)[0]))
    voto = round(subtotal * 2) / 2
    # Le correzioni post-indice, nella scala in cui si MOSTRANO: sono state sommate
    # prima dello stadio finale, quindi nel voto finito valgono ``scale_factor``
    # volte tanto. I nomi originali restano quelli non riscalati, che servono al
    # conto qui sopra.
    p_goal = goal_adjustment * scale_factor
    p_assist = assist_adjustment * scale_factor
    p_nudge = result_nudge * scale_factor
    p_red = red_adjustment * scale_factor
    p_og = own_goal_adjustment * scale_factor
    p_pen = penalty_adjustment * scale_factor

    # The key travels with the line (it used to be dropped here): the ledger below
    # lists the entries that did NOT make it into the summary, and without an
    # identity there is no way to tell which ones those are.
    nameable = [(pts, key, ph, fam) for pts, key, ph, fam in scored if ph]
    nameable.sort(key=lambda x: x[0], reverse=True)
    named = [x for x in nameable if abs(x[0]) >= NAMEABLE_MIN_POINTS]
    # One-sided at the extremes (see POSITIVES_MIN_VOTE / NEGATIVES_MAX_VOTE): a bad
    # game's "positives" are faint praise, a fine game's "negatives" are nitpicks.
    # Suppressed items fold into "altre voci", so the breakdown still reconciles.
    positives = ([] if voto < POSITIVES_MIN_VOTE
                 else [x for x in named[:top] if x[0] > 0])
    negatives = ([] if voto > NEGATIVES_MAX_VOTE
                 else [x for x in (named[-top:][::-1]) if x[0] < 0])
    shown = positives + negatives

    # PARTITA PIATTA: nessuna voce arriva al ventesimo di voto, e il pannello
    # restava muto — 113 volte sulla 25-26, fra cui portieri che avevano giocato
    # novanta minuti. Il silenzio non e' piu' onesto della soglia: si mostrano le
    # due voci piu' grandi qualunque sia la loro taglia, e ``flat`` dice a chi
    # scrive la frase di NON spacciarle per un giudizio (v. ``to_sentence``).
    # GUARDIA: "piatta" vuol dire che non c'e' NIENTE di grosso, non che il pezzo
    # grosso non ha un nome. ``defensive_value`` non e' nominabile in una frase e
    # puo' valere il 20% del voto di un difensore: promuovere al suo posto due voci
    # da 0,01 direbbe che la partita e' stata insignificante mentre il voto lo
    # muoveva quella. In quel caso si tace come prima, e la voce sta nel registro
    # col suo nome — v. LEDGER_LABELS.
    flat = not shown and not any(abs(pts) >= NAMEABLE_MIN_POINTS for pts, _k, _ph, _f in scored)
    # IL RIPIEGO SCATTA SU ``not shown``, non su ``flat``: il pannello muto e' il
    # caso peggiore di tutti e non deve dipendere dal perche' e' rimasto vuoto.
    # Con la soglia a 0.10 se ne aggiungeva un secondo tipo — 16 presenze sulle 578
    # delle prime due giornate, tutti difensori entrati fra il 14' e il 31' — dove
    # QUALCOSA supera la soglia ma non ha una frase: sono gli zeri che pagano a
    # favore (nessun duello perso, mai saltato, nessun errore), che ``_phrase``
    # tace apposta per non elogiare chi in campo non e' quasi entrato. Il conto
    # torna lo stesso, ma il lettore apriva il dettaglio e non trovava niente.
    #
    # ``flat`` resta piu' stretto della condizione che promuove, e per questo la
    # NOTA la scrive solo lui: "nessuna voce si stacca" e' vero quando davvero non
    # c'e' niente di grosso, e sarebbe falso quando il pezzo grosso c'e' e non si
    # puo' nominare. In quel secondo caso si mostra comunque la voce piu' grande di
    # ogni lato — piccola, col suo numero accanto — senza raccontarci sopra niente.
    if not shown:
        positives = [x for x in nameable[:1] if x[0] > 0]
        negatives = [x for x in nameable[-1:] if x[0] < 0]
        shown = positives + negatives

    def entry(pts, label, family=None, kind=None):
        """One visible line. ``family`` is set when the line is the NET of several
        features (see MERGES): without it the summary shows a number that matches no
        single row of the full ledger, which reads as an inconsistency. ``kind`` marks
        the vote-level adjustments, which are not features at all."""
        out = {"label": label, "points": round(pts, 2)}
        if family:
            out["family"], out["family_size"] = family
        if kind:
            out["kind"] = kind
        return out

    contributions = [entry(pts, ph, fam) for pts, _key, ph, fam in shown]
    # The result adjustment is a vote-level term, not a feature, so it rides on top
    # of the feature contributions and is named explicitly.
    # ``kind`` rides along so ``to_sentence`` (and any caller) can recognise these
    # lines without matching on their text — the labels now carry minute, reason and
    # man-down time, and string-matching them was a trap waiting to spring.
    # IL GOL PER PRIMO, e con la sua storia. Dal 29/08/2026 non e' piu' una feature
    # dell'indice ma una voce a livello di voto, graduata da quanto il gol ha
    # cambiato la partita: e' quasi sempre la voce piu' grande del tabellino di chi
    # segna, quindi apre l'elenco invece di accodarsi alle correzioni.
    if abs(p_goal) >= 0.005 and goal_detail:
        contributions.insert(0, entry(p_goal,
                                      goal_impact.goal_phrase(goal_detail),
                                      kind="goal"))
    # L'ASSIST subito dopo il gol, e con la stessa forma: e' lo stesso evento visto
    # dall'altro lato del passaggio, e dal 29/08/2026 vale quanto quel gol pesava.
    if abs(p_assist) >= 0.005 and assist_detail:
        contributions.insert(1 if any(c.get("kind") == "goal" for c in contributions) else 0,
                             entry(p_assist,
                                   goal_impact.assist_phrase(assist_detail),
                                   kind="assist"))
    if abs(p_nudge) >= 0.005:
        contributions.append(entry(p_nudge,
                                   "adeguamento al risultato di squadra",
                                   kind="result"))
    if abs(p_red) >= 0.005:
        contributions.append(entry(p_red, red_card_phrase(red_detail),
                                   kind="red"))
    if abs(p_og) >= 0.005:
        contributions.append(entry(p_og,
                                   own_goal_phrase(own_goal_detail),
                                   kind="own_goal"))
    if abs(p_pen) >= 0.005:
        # "decisivo" when converting it would have flipped the result (the larger
        # drop); a plain miss when the result was already decided.
        # LA PAROLA SI DECIDE SUL VALORE NON RISCALATO. La soglia distingue le due
        # costanti dello scorer (-1.0 decisivo, -0.5 ininfluente), che stanno in
        # punti PRIMA dello stadio finale; applicarla al valore riscalato faceva
        # chiamare "decisivo" un rigore da -0.5, perche' 0.5 x 1.55 supera 0.75.
        # Il numero mostrato resta quello riscalato: e' quanto e' costato davvero.
        pen_label = ("rigore decisivo sbagliato" if penalty_adjustment <= -0.75
                     else "rigore sbagliato")
        contributions.append(entry(p_pen, pen_label, kind="penalty"))
    shown_rounded = sum(c["points"] for c in contributions)
    other_points = round(subtotal - centre - shown_rounded, 2)

    # THE LEDGER BEHIND "altre N voci". The summary keeps three lines; on a game
    # that was good at everything the rest is not a tail but most of the vote —
    # Rrahmani, Genoa-Napoli: +0.56 shown, +0.81 unshown, and the biggest single
    # slice of the lot (the defensive index, +0.28) sitting inside the fold with no
    # name on it. So the fold has to be openable, and this is what is under it: the
    # same entries the summary chose from, minus the ones it showed, each one named.
    #
    # Built only on request (see ``ledger``) because it rides in the match payload
    # of twenty-two players, which is re-fetched on every live push.
    other_terms, tiny_count = [], 0
    if ledger:
        shown_keys = {key for _p, key, _ph, _f in shown}
        for pts, key, _ph, fam in sorted(scored, key=lambda x: x[0], reverse=True):
            if key in shown_keys:
                continue
            # Under a hundredth of a vote there is nothing to read: those are
            # counted and summed at the bottom instead of printing thirty "+0.00".
            if abs(round(pts, 2)) < 0.005:
                tiny_count += 1
                continue
            # QUANTE volte l'ha fatto, come si conta nel tabellino — letto PRIMA
            # dell'etichetta, che ne ha bisogno per non dire "tanti" di uno solo.
            count = None if fam else observed(key)
            row = {"key": key,
                   "label": ledger_phrase(role, key, pts, raw_values.get(key, 0.0),
                                          count),
                   "points": round(pts, 2)}
            if fam:
                # A merged family is one row here too, as in the summary; the count
                # says how many features it stands for.
                row["family"], row["family_size"] = fam
            elif count is not None:
                # QUANTE volte l'ha fatto, come si conta nel tabellino: il numero
                # osservato, non quello che l'indice consuma. Per il blocco dei
                # volumi i due differiscono — l'indice ragiona per densita' e
                # proietta sui 90' — e "4,14 respinte" e' un numero che nessuno
                # puo' verificare da nessuna parte, mentre 4 sta nel tabellino.
                #
                # "nessun gol (0)" e "nessun duello aereo perso (0)" hanno lo
                # zero scritto due volte: quando la frase DICE gia' che non e'
                # successo, il numero accanto e' rumore. Lo stesso vale per il ramo
                # numerico ("2 falli subiti · 2").
                n = round(count)
                # Un EVENT porta SEMPRE il conteggio dentro la frase ("3 gol",
                # "nessun assist"), a qualunque numero; una COUNT solo sotto la
                # soglia numerica. In entrambi i casi la colonna accanto tace.
                is_event = (LABELS.get(key) or (None,))[0] == EVENT
                already_says_number = (
                    is_event
                    or (n == 0 and key in COUNT_NONE)
                    or (1 <= n <= COUNT_SAY_NUMBER_UPTO and _singular_of(key)))
                if abs(count - n) < 0.01 and not already_says_number:
                    # "nessun gol" non ha bisogno di uno zero accanto: lo zero e'
                    # gia' tutta la frase.
                    row["value"] = int(round(count))
            other_terms.append(row)
    # The remainder is what the printed rows do not account for: the sub-hundredth
    # entries AND the rounding of everything above them. It is carried as one line
    # so the open ledger still adds up to the fold it opened.
    tiny_points = round(other_points - sum(r["points"] for r in other_terms), 2)
    low = minutes < SHORT_APPEARANCE_MINUTES
    note = ("Con pochi minuti giocati ogni voce pesa meno: il voto resta piu' "
            "vicino al 6.") if low else ""
    if flat:
        # Le due voci promosse sono minuscole per costruzione. Il pannello le
        # mostra senza sapere quanto valgono, e senza questa riga sembrerebbero i
        # motivi del voto invece che il poco che c'e' da leggere. Viaggia in
        # ``note``, che il dettaglio partita gia' stampa.
        note = ((note + " ") if note else "") + (
            "Nessuna voce si stacca dalla media del suo ruolo: quelle qui sopra "
            "sono le piu' grandi di una prestazione senza sporgenze.")
    return {
        # perche' un assist puo' non muovere il voto base: e' la ragione piu' comune
        # per cui stiamo sotto una pagella su un giocatore che "ha fatto qualcosa"
        "assist_note": assist_note(assists, raw_values.get("expected_assists", 0.0),
                                   raw_values.get("big_chance_created", 0.0)),
        "positives": [entry(p, ph, fam) for p, _k, ph, fam in positives],
        "negatives": [entry(p, ph, fam) for p, _k, ph, fam in negatives],
        "contributions": contributions,
        "all_terms": all_terms,
        # Le voci NON mostrate, una per una (solo con ``ledger``): la riga "altre N
        # voci" del pannello si apre su queste, e insieme a ``other_tiny`` fanno
        # esattamente ``other_points``.
        "other_terms": other_terms,
        # Le stesse righe raccolte per senso, col subtotale di ogni gruppo: e' la
        # forma in cui "altre N voci" si legge invece di elencarsi.
        "other_groups": group_ledger(other_terms) if ledger else [],
        "other_tiny": {"count": tiny_count, "points": tiny_points},
        # vote points per index point for THIS appearance (it carries both
        # shrinkages): the scale that turns the index into the vote.
        "per_unit": round(per_unit, 6),
        "base": centre,
        "other_points": other_points,
        "other_count": max(0, len(scored) - len(shown)),
        "subtotal": round(subtotal, 2),
        "voto": voto,
        "minutes": minutes,
        "low_minutes": low,
        # nessuna voce sopra la soglia: le due mostrate sono le piu' grandi di una
        # prestazione senza sporgenze, non i motivi del voto
        "flat": flat,
        "note": note,
    }


def to_sentence(explanation: dict) -> str:
    """One readable line, for places with no room for a breakdown."""
    def names(entries):
        return ", ".join(e["label"] for e in entries)
    pos, neg = explanation.get("positives", []), explanation.get("negatives", [])
    if explanation.get("flat") and (pos or neg):
        # Niente supera la soglia: dire "Bene: ..." su un centesimo di voto
        # spaccerebbe per giudizio quello che e' rumore. Si nomina la prestazione
        # per quello che e', e le voci si offrono come il poco che c'e' da leggere.
        core = ("Prestazione in linea con la media del suo ruolo; le voci che piu' "
                f"si avvicinano a spostarla: {names(pos + neg)}.")
    elif pos and neg:
        core = f"Bene: {names(pos)}. Male: {names(neg)}."
    elif pos:
        core = f"Bene: {names(pos)}."
    elif neg:
        core = f"Male: {names(neg)}."
    else:
        core = "Prestazione in linea con la media del suo ruolo."
    # The vote-level facts (sending-off, own goal, missed penalty) are not features,
    # so they are absent from positives/negatives — call them out, WITH the reason
    # that set their size and the points they cost. Matched on ``kind``, not on the
    # label text: the labels now carry minute and reason and would break a match.
    by_kind = {c["kind"]: c for c in explanation.get("contributions", [])
               if c.get("kind")}
    for kind in ("red", "own_goal", "penalty"):
        c = by_kind.get(kind)
        if c:
            core += f" {c['label'].capitalize()} ({c['points']:+.2f})."
    note = explanation.get("assist_note")
    if note:
        core += " " + note
    return core
