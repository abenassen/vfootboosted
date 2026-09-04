"""Heuristic 'voto puro' (base pagella vote) for classic-mode leagues.

Classic fantacalcio scores each player as: fantavoto = voto puro + bonus/malus
(gol/assist/cartellini). The voto puro is the performance grade a pagella would give,
independent of the discrete bonus events. We don't have an external rating provider,
so we DERIVE it from the per-player zone features we already store (the user's choice:
a heuristic from our own data).

Design:
  * Aggregate a player's PlayerZoneFeature values across all 20 zones for the match
    into feature totals, converting the volume block to a per-90 rate (so a sub is
    compared fairly to a starter).
  * STANDARDISE every feature by its own spread, compress, and standardise again —
    see ``_feature_z``. This is what makes the weights readable: a weight IS the
    contribution to the index of ONE SIGMA of that feature. Under the older scheme
    (raw values, weights absorbing whatever scale the provider happened to use)
    that reading was impossible, and hand-tuning was guesswork: halving the xA
    weight did NOT halve its effect relative to a goal, because the two live on
    distributions of very different width.
  * Sum the weighted standardised features into a *performance index*, then z-score
    the index WITHIN the player's classic role (POR/DIF/CEN/ATT) over the season —
    so every role centres on 6 and a defender isn't dragged down by an attacker's
    shot volume. Only the RELATIVE weighting matters: scaling every weight by the
    same constant is a no-op.
  * Map z -> vote: 6 + K*z, then regress short cameos toward 6 (few minutes = little
    evidence), clamp to a pagella range and round to the 0.5 grid.

Goalkeepers (POR) have their OWN feature channel and weights (anchored on
goals-prevented) but go through the same z-score-within-role pipeline, so a keeper's
voto is on the same pagella scale (its mean sitting a little lower than outfield is
expected and fine — the UI filters by role). ``REFERENCE`` (per-role mean/std of the per-90 index) is
computed once over a season and reused.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict

from django.db.models import Sum

from realdata.models import (
    CARD_RED, CARD_SECOND_YELLOW,
    MatchAppearance, Match, MatchDisciplinaryEvent, MatchShot, Player,
    PlayerOnPitchInterval, PlayerZoneFeature, PROVIDER_SOFASCORE,
)
from realdata.services.sofascore_adapter import METHOD_UNPLACED
from vfoot.services import goal_impact

log = logging.getLogger(__name__)

# EVERY WEIGHT BELOW IS IN THE SAME UNIT: the contribution to the index of ONE
# STANDARD DEVIATION of that feature, measured over the calibration population (see
# ``_feature_z`` and FEATURE_SCALES). Errors are negative. Only ratios matter — the
# index is z-scored downstream — so scaling the whole table by a constant is a no-op.
#
# Why that unit and not the raw provider scale (which is what these were until
# 2026-07-29): with raw values a weight had to absorb whatever units the provider
# happened to use, so two weights were never comparable and hand-tuning could not
# express an intent. The xA case made it concrete: the analyst wanted a created
# chance to be worth about half a goal and halved the weight to get there — which
# did not work, because xA and goals live on distributions of very different width,
# so half the weight was nowhere near half the effect. Now it is: to make feature A
# count half of feature B, give it half the weight.
#
# TOTALS are NOT rescaled to 90': a decisive action's value does not scale with how
# few minutes you played. The PER90 volume block below is (density is the signal).
#
# NOTE (hand-tuning 2026-07-27, model v2): the RELATIVE magnitudes are the analyst's,
# from the ``build_voto_tuner`` spreadsheet, not a machine fit. A constrained NNLS fit
# on SofaScore confirmed every SIGN but wanted ~4x more xA (SofaScore's known
# offensive bias); the analyst keeps a flatter, less offense-heavy hand set instead.
#
# THE SHOOTING BLOCK is one formula, not a free list:
#
#     shooting credit = S·(xGOT − xG + woodwork)  +  β·xG
#                       └──── execution: sga_post ────┘  └ mass of chances ┘
#
# Until the standardisation this was stored EXPANDED, as w(xg_on_target)=S and
# w(xg_shots)=β−S. That is no longer possible: the compression is non-linear, so
# f(xGOT) − f(xG) is not f(xGOT − xG) and the SGA cannot be reconstructed from two
# separately-transformed parts. It is therefore a DERIVED feature of its own,
# ``sga_post`` (see ``derived_features``), and the mass of chances keeps its own
# positive weight — which also reads better than the old +0.48/−0.32 pair.
#
#   * sga_post — post-shot xG over pre-shot xG: where the shot ended up, over where
#     it was taken from. Plus the woodwork, at SGA_POST_WOODWORK, because the
#     provider gives a shot off the frame no xGOT at all and its execution merit
#     would otherwise vanish.
#   * β/S = 1/3 — the mass of chances is worth a third of the execution. This ratio
#     decides WHICH GOAL scores highest and the benchmark cannot arbitrate it
#     (agreement is flat for β/S between 1/3 and 1): it is a design choice, judged on
#     the ordering it produces. At the previous 2/3 a tap-in (xG 0.70, xGOT 0.80)
#     outscored a hard finish (xG 0.055, xGOT 0.513) — an easy chance carries a high
#     xGOT by construction. At 1/3 the ordering inverts, and the correlation between
#     a goal's credit and how EASY the chance was drops from +0.41 to +0.11 over the
#     season's 841 open-play goals.
#   * The block was scaled x1.6 on 2026-07-29. Measured against the external base
#     votes, a goal used to lift an ATTACKER's vote by 0.82 against 1.23 for
#     fantacalcio and 1.32 for the Statistico — a 35% shortfall; it is now 0.96, and
#     the error on scorers falls from 0.488 to 0.398 (ATT r 0.730 -> 0.760). KNOWN
#     COST: the same scaling overpays a DEFENDER's goal (1.31 against ~1.05
#     externally) because the tighter defender index divides the same gain by a
#     smaller σ — accepted deliberately, since fixing it properly needs a per-role
#     shooting scale and this model keeps ONE global outfield weight vector.
# DROPPED: big_chance_missed — the miss is already in the SGA (a missed big chance
# has high xg_shots, low xg_on_target), so weighting it double-penalised the same
# shot. Its sibling big_chance_created is NOT the same statistic and is weighted
# below: that earlier removal conflated the two faces of one event.
# --- GLI EVENTI RARI SI TARANO IN PUNTI DI VOTO, E LA SIGMA LI SPOSTA ------------
# I pesi degli eventi rari (qui sotto e ``clearances_off_line``) non sono tarati
# "per 1 sd" come tutti gli altri: sono tarati su QUANTO VALE UNA OCCORRENZA,
# perche' per un evento che capita nell'1% delle presenze la sd e' un decimo di
# occorrenza e il numero per sd non si legge (v. il commento lungo piu' sotto).
#
# Ma il peso vive nell'INDICE, e il voto divide l'indice per la sigma del ruolo.
# Quindi il valore in voti di un evento raro cambia da solo ogni volta che una
# ritaratura muove quella sigma, senza che nessuno abbia toccato il peso — ed e'
# successo il 01/09/2026: la ritaratura del voto ha portato la sigma dei ruoli di
# movimento da 0.4273 a 0.2811 e ha gonfiato OGNI evento raro di **x1.52**.
#
#   evento                          prima     dopo    corretto
#   salvataggio sulla linea        +0.355   +0.539      +0.300
#   rigore conquistato             +0.510   +0.776      +0.510
#   rigore concesso                -0.850   -1.292      -0.850
#   errore che porta a un gol      -0.596   -0.906      -0.596
#   errore che concede un tiro     -0.170   -0.259      -0.170
#
# Il metro per giudicarli: un GOL vale fra +0.34 e +0.79 (v. goal_impact). Un
# rigore concesso a -1.29 costava piu' di quanto renda qualunque gol, e un pallone
# tolto dalla linea valeva quanto segnare il gol decisivo. Il salvataggio non
# torna al valore di prima ma alla PROVA ESTERNA gia' citata piu' sotto (+0.30 su
# 63 presenze): e' il caso che ha fatto scoprire tutto, segnalato su Dybala.
#
# I numeri sono stati risolti DOPO il taglio del possesso e DOPO la ricalibrazione,
# in due giri, perche' anche quel taglio muove la sigma: l'ordine e' tagliare,
# ricalibrare, poi risolvere questi. E c'e' un test che li tiene fermi
# (tests_rare_events.py): se una ritaratura futura li rigonfia, se ne accorge lui.
# --------------------------------------------------------------------------------
TOTAL_WEIGHTS = {
    # xA: la creazione, accreditata a CHI FA IL PASSAGGIO.
    # 0.11 -> 0.07 il 01/09/2026, insieme all'azzeramento di ``key_passes`` qui
    # sotto e al rialzo della banda dell'assist (TARGET_ASSIST): sono UNA modifica
    # sola, perche' il vettore dei pesi e' scala-invariante — abbassare un peso e
    # alzare tutti gli altri sono la stessa operazione, quindi la creazione si
    # taratura come BLOCCO e non voce per voce.
    #
    # IL BUDGET. Misurato sulla 25-26 (n=6848 presenze >=60'), pagamento della
    # creazione in punti di voto = coef xA (1 sd) + 0.25 x coef assist + coef key
    # pass, gol e minuti controllati. I tre giudici sono D'ACCORDO sul totale e
    # litigano solo su come dividerlo:
    #
    #                    xA      assist   key pass   TOTALE
    #   Redazione     +0.028     +0.575    +0.044    +0.215
    #   Statistico    +0.033     +0.593    +0.061    +0.242
    #   SofaScore     +0.153     +0.211    +0.034    +0.240
    #   noi, prima    +0.156     +0.176    +0.182    +0.381   <- +60%
    #   noi, ora      +0.132     +0.184    +0.073    +0.251
    #
    # Spendevamo per la creazione il 60% piu' di chiunque, e l'eccesso era tutto
    # sui passaggi chiave. La xA NON era il problema (il nostro +0.156 era il
    # +0.153 di SofaScore); scende a 0.07 perche' togliendo key_passes la σ
    # dell'indice si restringe e il suo coefficiente salirebbe da solo a +0.245.
    #
    # PERCHE' 0.07 E NON 0.06 (che centrerebbe il totale a +0.239): il pavimento
    # dei passaggi chiave (v. sotto) si mangia 0.04 di budget senza che nessun peso
    # possa toglierlo, e centrare il totale costringerebbe la xA sotto il livello
    # che il giudice della creazione le riconosce. 0.07 tiene il totale entro il 5%
    # del consenso e migliora tutti e tre i giudici.
    # RITARATO IL 04/09/2026: 0.0700 -> 0.0490. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "expected_assists": 0.049,
    # The DISCRETE counterpart of xA, and the creator's side of a big chance —
    # verified as the PASSER's stat, not the shooter's: it never exceeds the
    # player's own key passes (0 violations in 10,067 player-matches), 36% of the
    # matches carrying one have no shot by that player at all, and it correlates
    # +0.48 with key passes against +0.13 with his own shots. Its mirror image
    # big_chance_missed is the opposite (+0.41 with shots, +0.06 with key passes).
    # Why it is here: 64% of created big chances never become assists, so this
    # rewards the gesture where the outcome never arrives.
    #
    # BOTH creation weights were raised on 2026-07-29 (xA 0.0168 -> 0.11, this one
    # 0.0363 -> 0.07) because the block was below the resolution of the output. At
    # the old weights xA never moved a single vote by half a grid step in 9,303
    # player-matches — max 0.199 points — so it only ever tipped roundings; and the
    # whole creation block was relevant (worth >= half a step) in 3.6% of matches
    # against 25.4% for the shooting block and 61.7% for volume. It is now 17.7%,
    # roughly three quarters of the shooting block: creating counts less than
    # finishing, which is right, but not seven times less.
    # KNOWN COST, accepted as a design choice: agreement falls, and unlike the
    # earlier creation experiments it falls on EVERY role (DIF r 0.627 -> 0.603,
    # CEN 0.698 -> 0.693, ATT 0.770 -> 0.764). Part of that is expected — neither
    # benchmark pays for creation that the finisher wastes, so diverging there is
    # the point — but the monotone decline says some of it is noise, mostly a
    # defender's xA being the residue of a hopeful cross. If the defender vote ever
    # needs recovering, this is the first weight to look at.
    #
    # BOTH LOWERED AGAIN on 2026-07-30 (xA 0.11 -> 0.05, this one 0.07 -> 0.045), and
    # this time not on agreement but on INTERNAL COHERENCE. The two terms overlap by
    # construction — a pass that creates a clear chance has a high xA, and one big
    # chance carries +0.18 of xA on average (r 0.58 between them) — so the same
    # gesture was paid twice. Together they had reached 1.33 GOALS for a single
    # created chance (xA 0.45 alone was 0.88 of a goal), while every external judge
    # puts the pair at half a goal to two thirds: Redazione 0.47, Statistico 0.54,
    # SofaScore rating 0.69. Creating a chance may reasonably be worth a large
    # fraction of a goal; it cannot be worth more than one. Now: pair 0.69 of a goal,
    # xA at 0.45 = 0.40, one big chance = 0.29.
    #
    # Which of the two was over-paid could NOT be settled by the linear fits — with
    # r 0.58 between the regressors the ridge splits the credit by its own penalty,
    # and it wrongly exonerated big_chance_created. The groups that SEPARATE them
    # settled it: on appearances with a big chance and low xA (n=257, isolating this
    # weight) we sat +0.22 above the pagelle; on appearances with high xA and no big
    # chance (n=140, isolating xA) +0.36. Both were high.
    # They differ in what the weight BUYS, and that is why only one moved far: xA is
    # pure cost (lowering it improves MAE, r and the defender r monotonically),
    # while big_chance_created earns its keep (dropping it to 0 costs 0.01 of r) —
    # 0.045 is the value that beats 0.035 on all four criteria at once.
    # OPEN, and known: the SofaScore rating — the one judge that does price xA —
    # prefers the OLD 0.11 (r 0.7718 against 0.7676 here). Lowering xA is justified
    # by the coherence argument, not by that judge, and 0.07 would have kept the
    # pair under a goal at a third of the cost. 0.05 is the user's call.
    # AZZERATO il 25/08/2026. Misurato: due terzi di quel che le pagelle sembrano
    # pagare per un'occasione creata e' il bonus ASSIST che passa attraverso il
    # flag — a parita' di xA scatta ~3 volte piu' spesso quando l'assist e' arrivato
    # (20%->63% nella banda xA [0.10,0.20)). Il peso era stato tarato contro giudici
    # che l'assist lo pagano, e il risultato era un'inversione: a parita' di xA E di
    # assist pagavamo il flag +0.133 contro +0.080 della Redazione, +0.093 dello
    # Statistico e +0.015 di SofaScore — il piu' alto del panel. Tenuto a zero e non
    # cancellato: la feature si legge ancora e lo zero e' una decisione visibile.
    # Tabelle in docs/voto_questioni_aperte.md §2.
    "big_chance_created": 0.0,
    # L'ASSIST, come il gol. La simmetria mancava: ``shots_goal`` sta qui col suo
    # peso "on top of +3 bonus", quindi l'esito di una CONCLUSIONE il voto base lo
    # pagava gia', quello di un PASSAGGIO no — e non c'era una ragione scritta per la
    # differenza, solo che il gol arrivava dalla mappa dei tiri e l'assist da nessuna
    # parte (ora da ``_merge_assists``).
    #
    # PICCOLO DI PROPOSITO. Caricarlo comprerebbe accordo con le pagelle — che
    # l'assist lo pagano +0.57 — e sarebbe l'appiattimento su fantacalcio.it che
    # questo modello esiste per evitare. Misurato sulla 25-26: portandolo da 0.03 a
    # 0.05 l'accordo con la Redazione sale (0.660 -> 0.672) e quello con SofaScore
    # SUI CREATORI scende (0.764 -> 0.751), cioe' si guadagna col giudice che legge
    # l'esito e si perde con quello che legge la creazione. A 0.03 l'esito porta il
    # 19% del credito di Dybala e il 28% di quello di Diouf: il merito resta padrone.
    # Sotto (0.02) si perde su ENTRAMBI i giudici — un assist e' pur sempre un
    # indizio, debole, che il passaggio era buono, e buttarlo via non compra purezza.
    # USCITO DALL'INDICE il 29/08/2026, come ``shots_goal`` e per la stessa ragione:
    # il suo valore dipende da quanto pesava il gol che ha servito, e quel numero
    # non passa per lo shrinkage sui minuti (v. services/goal_impact). Tenuto a zero
    # e non cancellato: la feature si legge ancora nel registro e nel tuner.
    "assists": 0.0,
    # IL GOL NON E' PIU' UNA FEATURE DELL'INDICE. Il suo credito dipende ora da
    # QUANTO E' PESATO — lo stato di partita che ha cambiato — e non dai minuti
    # giocati, quindi non puo' passare per l'indice, che i minuti li scala tutti
    # insieme (v. goal_impact e ``goal_credit_for_match``). Lasciato a zero e non
    # cancellato perche' la feature si legge ancora nel registro e nel tuner, e lo
    # zero e' una decisione visibile. 29/08/2026.
    "shots_goal": 0.0,
    # = S: EXECUTION merit, derived (xGOT − xG + legno + murati).
    # x1.6 il 29/08/2026, insieme a x0.7 sul blocco del VOLUME qui sotto: sbagliare
    # un'occasione costava troppo poco. Il pareggio — l'xG oltre il quale un tiro
    # fuori toglie invece di aggiungere — scende da 0.137 a 0.053, e un'occasione
    # da 0.40 di xG passa da -0.117 a -0.381 punti di voto.
    # RITARATO IL 04/09/2026: 0.0652 -> 0.0335. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "sga_post": 0.0335,
    # = β: the mass of chances occupied. NON rialzato insieme a S, quindi β/S passa
    # da 1/3 a 1/4.5. E' una deroga consapevole al rapporto scritto sopra: β/S
    # esiste per l'ORDINAMENTO dei gol (un gol difficile deve battere un tap-in) e
    # quella proprieta' regge anche qui (gran gol +1.042 contro tap-in +0.870).
    # Tenendolo a 1/3 avremmo restituito un terzo della severita' appena comprata,
    # perche' questo peso paga l'essersi PROCURATI la posizione comunque sia finita.
    # RITARATO IL 04/09/2026: 0.0145 -> 0.0050. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "xg_shots": 0.005,
    # RIAZZERATO il 01/09/2026, dopo essere stato acceso a 0.100 il 25/08 (e prima
    # ancora 0.181, poi 0 senza motivazione scritta).
    #
    # E' LA STESSA COSA DELLA xA, CONTATA DUE VOLTE. La xA e' la somma degli xG dei
    # tiri nati da quei passaggi: pesa per qualita' esattamente gli eventi che
    # questa feature conta. r = 0.613 grezza, 0.635 in punti di voto, 0.681 sui
    # difensori. E' l'argomento di coerenza interna che il 25/08 aveva gia' azzerato
    # ``big_chance_created``, applicato alla coppia rimasta.
    #
    # MISURATO (25-26, presenze >=60' senza gol ne' assist, l'una controllata per
    # l'altra), coefficiente per 1 sd in sigma del giudice:
    #
    #                     xA      key pass
    #   noi, prima     +0.221      +0.257     <- il conteggio pagato PIU' della qualita'
    #   Redazione      +0.037      +0.074
    #   Statistico     +0.034      +0.094
    #   SofaScore      +0.212      +0.050     <- la qualita' 4x il conteggio
    #
    # A 0.100 lo pagavamo 5 volte SofaScore e invertivamo il rapporto fra qualita' e
    # conteggio. Sulla griglia 4x4 (xA 0.11..0.07 x kp 0.100..0) la coppia di prima
    # e' il vertice PEGGIORE: nessuna delle 16 fa peggio ne' sulla Redazione ne' su
    # SofaScore, e la riga kp=0.100 costa ~0.010 di correlazione SofaScore
    # qualunque sia il peso della xA.
    #
    # LA RIDONDANZA PER CUI ERA STATO ACCESO C'E' GIA' SENZA DI LUI, ed e' il motivo
    # per cui zero e' difendibile invece che estremo: a peso nullo il coefficiente
    # dei passaggi chiave non scende sotto ~+0.10 — arrivano al voto via
    # ``passes_opp_half`` e ``crosses_completed``, e controllando quelle due il
    # coefficiente cala del 42% (+0.127 -> +0.074). Il PAVIMENTO resta sopra il
    # +0.034 di SofaScore: se un giorno va tolto, si interviene li', non qui.
    #
    # Lasciato a zero e non cancellato: la feature si legge ancora nel registro e
    # nel tuner, e lo zero e' una decisione visibile.
    "key_passes": 0.0,
    # IL BLOCCO DEL VOLUME, x0.7 il 29/08/2026 (v. la nota su sga_post). Tirare
    # tanto restava creditato quanto l'esecuzione, e le due cose si compensavano
    # quasi tiro per tiro: sprecare era gratis sotto 0.137 di xG, cioe' sulla
    # maggioranza dei tiri. Continuano a pesare — provarci vale — ma meno di come
    # si e' calciato.
    "shots_on_target": 0.0175,
    # RITARATO IL 04/09/2026: 0.0176 -> 0.0053. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "shots": 0.0053,              # shot ACTIVITY still rewarded, not penalised
    # RITARATO IL 04/09/2026: azzerato (era 0.0062). Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "shots_off": 0,          # even an off-target attempt: small credit for shooting
    # RISOLTO CONTRO IL GIUDICE, non ottimizzato (03/09/2026). L'ottimizzazione lo
    # aveva messo a -0.0264, che e' il punto di massima correlazione: sulle 75
    # presenze con l'errore il nostro voto stava 0.383 sotto lo Statistico piu' di
    # quanto ci stia in generale. Toglierlo COSTA 0.0006 di correlazione e vale
    # 0.054 di errore su quei giocatori — la Pearson non vede uno scostamento
    # sistematico su 75 righe di 7696, l'utente che apre il pannello si'.
    "errors_led_to_goal": -0.0181,  # una occorrenza: -0.84 di voto
    # Conceding a penalty hands over roughly 0.78 expected goals through a clear
    # individual foul, and — unlike a missed penalty — carries NO fantacalcio
    # malus, so the base vote is the only place it can register at all.
    # UNA FRAZIONE DI GOL, non un gol. Concedere un rigore non e' subire una rete:
    # nella 25-26 sono 106 rigori e 81 segnati, cioe' **76,4%** di conversione (e
    # 0.788 di xG medio, che e' la stessa cosa detta dal fornitore). Il costo giusto
    # e' quindi 0.764 volte quello di CAUSARE un gol, che il modello gia' quota:
    # ``errors_led_to_goal``, -0.596 per occorrenza. Da cui -0.455.
    #
    # Prima stava a -0.850, cioe' PIU' di un errore che porta al gol davvero — un
    # rigore concesso costava piu' del gol che non sempre ne segue. Verificato che
    # non c'e' doppio addebito: sulle 105 presenze con un rigore concesso, UNA sola
    # e' anche marcata come errore che porta a un gol.
    # Stessa storia (v. errors_led_to_goal): l'ottimizzazione lo portava a -0.0409,
    # con 0.312 di scarto sulle 76 presenze che concedono un rigore.
    "penalties_conceded": -0.0341,  # una occorrenza: -1.58 di voto
    # Winning one is the mirror image and equally unrewarded: the bonus goes to
    # whoever converts, never to the player who earned it.
    # RITARATO IL 04/09/2026: 0.0146 -> 0.0241. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "penalties_won": 0.0241,  # una occorrenza: +0.78 -> +0.51 (era 0.0244)
    # Interventions in a dangerous position. Kept as impact totals, not per-90:
    # their value does not scale with how long you played.
    #
    # THE TWO ARE NOT THE SAME EVENT, and the provider's own fields say so.
    # ``clearanceOffLine`` comes with an ``outfielderBlock`` in 64 cases out of 64:
    # it IS a shot stopped on the line, a goal prevented. ``lastManTackle`` is
    # <= ``totalTackle`` in 103 cases out of 103: it is a TACKLE, flagged as made by
    # the last defender — not an independent goal-saving event. Which is why it never
    # turns up in the highlights: it is an ordinary defensive duel in a bad place, and
    # the duel is ALREADY paid through tackles_won / duels_won. The "last man" flag
    # adds nothing to it.
    #
    # Three independent judges price one occurrence like this (a goal = +1.0 for all
    # three, which is what makes them comparable):
    #                        Redazione  Statistico  SofaScore rating
    #   goal                    +1.05      +1.10        +1.01
    #   clearance off the line  +0.13      +0.08        +0.48
    #   last-man tackle         -0.30      -0.36        -0.11
    # Both events happen under siege (danger conceded in his zone 2.4x the average;
    # goals conceded on the pitch 1.24 and 1.66 against 0.95), which is why the
    # pagelle read them as symptoms rather than feats.
    #
    # So: the goal-line clearance keeps a real value, at 0.28 of a vote per
    # occurrence — between the pagelle's ~0.10 and SofaScore's 0.48, the two
    # defensible readings of the same act. The last-man tackle goes to ZERO, which is
    # also the measured optimum of the whole pipeline (overall r 0.663 and defenders
    # 0.641, both the best of the range; residual differential on the 102 appearances
    # +0.065). Negative — what the linear fits above suggest — makes every metric
    # worse (r 0.662, defenders 0.638) and would mean punishing a last-ditch tackle,
    # which is not what the number says: it says the flag carries no information the
    # tackle and the exposure do not already carry.
    #
    # SET BY WHAT ONE OCCURRENCE IS WORTH, NOT BY 1σ — and that distinction is the
    # whole story of these two numbers. Every weight here means "index points per 1σ
    # of the feature", which is the right unit for a quantity that varies
    # continuously. For an event that happens in 1% of appearances σ is a TENTH of an
    # occurrence (0.109 for a last-man tackle), so one occurrence is ~9.8σ and the
    # weight gets multiplied by ten on its way to the vote. Raised by hand to 0.05
    # and 0.035 while reading the tuner's σ column, they made ONE last-man tackle
    # worth +0.65 of a vote and one goal-line clearance +0.56 — against +0.63 for a
    # GOAL, and with the ladder inverted (clearing off the line prevents a goal, a
    # last-man tackle prevents a chance).
    #
    # Measured on 2025-26: on the 102 appearances with a last-man tackle our vote sat
    # +0.55 above fantacalcio's relative to our own average bias (9 standard errors),
    # and on the 63 with a goal-line clearance +0.30 (4.3 σ). The tuner's
    # "1 EVENTO in VOTI" column and the benchmark's per-feature table both show that
    # figure: read THAT one when hand-tuning a rare event, never the σ column.
    #
    # Kept at weight 0 rather than deleted: the feature is still fetched, still shown
    # in the per-feature table with its value, and its zero is a DECISION anyone can
    # see and revisit — deleting the key would hide the question instead of answering
    # it.
    # RITARATO IL 04/09/2026: 0.0089 -> 0.0037. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "clearances_off_line": 0.0037,  # una occorrenza: +0.54 -> +0.30 (era 0.0175)
    "last_man_tackle": 0.0,
    # An error that let the opponent SHOOT, without a goal following.
    # RITARATO IL 04/09/2026: -0.0113 -> -0.0057. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "errors_led_to_shot": -0.0057,  # una occorrenza: -0.26 -> -0.17 (era -0.0189)
    # RITARATO IL 04/09/2026: 0.0088 -> 0.0016. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "shots_blocked": 0.0016,      # the defence intervened (x0.7 col blocco volume)
    # PROVIDER PROXY, and the only one in the model — read the note below before
    # touching it.
    # RITARATO IL 04/09/2026: 0.0850 -> 0.1089. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "defensive_value": 0.1089,
}

# --- The one feature we do not measure ourselves ------------------------------
# ``defensive_value`` is SofaScore's own ``defensiveValueNormalized``, shipped with
# the per-player statistics and until now discarded along with 28 other fields.
#
# Why it is here. Most of a defender's job is invisible in an event feed: holding
# the line, the position taken, the tackle that never had to happen. Measured on
# defenders with neither goal nor assist, our vote agreed with the human pagella at
# r 0.493 — against 0.566 for SofaScore's own rating, and 0.818 between fantacalcio's
# two columns. This single column, alone, correlates 0.590 with that pagella: more
# than our whole model did. It is a synthesis of a feed we do not have (every duel
# with its location, opponent and phase), not a repackaging of what we already hold
# — our own features explain only 62% of it for defenders.
#
# Why this is NOT importing their rating. We take one INPUT dimension and weigh it
# ourselves among forty others; we do not take their ``rating``, which is the model
# output and carries their offensive bias wholesale. The distinction is the reason
# it is acceptable at all, and it stops being true the moment this weight grows
# large enough to dominate.
#
# What it costs, and the guardrail that fixes the weight. The field is heavily
# outcome-loaded: it correlates -0.530 with goals conceded while on the pitch, MORE
# than SofaScore's own rating does (-0.320). So part of what it buys is not defensive
# reading but the scoreline, which the exposure term already models deliberately and
# with a cap. The weight is therefore set by the same guardrail: at 0.10 the defender
# vote correlates -0.552 with goals conceded, still under the -0.578 of the external
# sources; at 0.16 it overshoots them. Within that ceiling the gain is most of what
# is available — agreement on goalless defenders goes 0.493 -> 0.582, past SofaScore's
# own 0.566, and 0.10 is also where the curve flattens (+0.089 up to it, +0.018 after).
#
# OPERATIONAL RISK. Unlike every other feature this one cannot be rebuilt from
# anything else: if SofaScore renames or drops the field, defenders silently lose
# ~0.09 of correlation and nothing raises an alarm. ``_merge_defensive_value`` logs
# when coverage collapses, and a test pins the field name. Coverage measured on
# 25-26: 99.9% above 15 minutes, 84.6% below (shrinkage already mutes those votes),
# absent for unused subs — a missing value reads as 0.0, which is the population
# median, i.e. "an ordinary defensive game" rather than a penalty.
#
# 0.10 -> 0.085 il 25/08/2026, e la ragione e' l'ESPOSIZIONE, non la taratura.
# Dare il peso piu' alto del modello a un numero che il fornitore calcola con un
# metodo che non conosciamo, e che puo' sparire senza preavviso (v. il RISCHIO
# OPERATIVO qui sopra), e' una dipendenza che vale la pena ridurre anche pagandola.
# E si paga: misurato sulla 25-26, 0.10 -> 0.085 costa Redazione -0.0033,
# Statistico -0.0040, SofaScore -0.0051, e sui soli difensori due-tre volte tanto
# (-0.0076 / -0.0100 / -0.0126). A 0.070 il conto raddoppia ancora.
#
# QUELLO CHE NON FA, e per cui era stato proposto: NON abbassa il livello dei
# difensori. La loro media resta 6.002 a 0.100, 6.003 a 0.085, 6.002 a 0.070 —
# la z-standardizzazione per ruolo inchioda ogni ruolo al 6 per costruzione e la
# ricalibrazione se lo riassorbe. I difensori SONO piu' generosi degli altri ruoli
# (+0.080 dalla Redazione contro +0.018 dei CEN e +0.014 degli ATT), ma quello e'
# un problema di CENTRO, e l'offset di ruolo e' stato deciso e chiuso il
# 02/08/2026. Un peso ordina, non alza.
DEFENSIVE_VALUE_SOURCE = "defensiveValueNormalized"

# VOLUME / involvement — rescaled to PER-90 (density is the signal: 120 touches in 90'
# != 30 in 20'), with a floor so a short cameo isn't projected to 90'.
#
# THE WHOLE BLOCK WAS SCALED x0.8 on 2026-07-29. It was winning on breadth: 23
# features against the 7 of the shooting block, each small but almost all moving
# together in a dominant game (whoever touches many balls wins many duels, loses
# few, plays high up the pitch). Summed, that carried more weight than scoring —
# De Ketelaere's best match took +1.03 from volume against +1.27 from two goals,
# and a third of that volume edge came from things he did NOT do (zero duels lost,
# zero times dribbled past: a negative-weighted feature at zero pays, because the
# average player carries its malus). No per-feature transform can address that:
# compression tames ONE extreme value, it has no grip on the sum of many moderate
# ones. Only the block's total weight does. Measured: r improves on every role
# (DIF 0.622->0.627, CEN 0.692->0.699, ATT 0.757->0.768) and the attacker MAE
# falls 0.395->0.388. It does NOT fix the ceiling inversion (defenders and
# midfielders still reach 9.0 where attackers stop at 8.0) — that one is the
# per-role z-scoring, not the weights.
#
# Every key here must be one the provider actually supplies (see
# ``sofascore_adapter.KNOWN_FEATURE_KEYS``; enforced by a test). This table used to
# carry ``passes_into_box``, ``progressive_passes_completed``, ``progressive_carries``
# and ``pressures``, which contributed exactly zero while reading as if progression
# and pressing were rewarded, so they were removed.
#
# CORRECTION (2026-07-29): that removal was right for three of the four and WRONG
# about carrying. SofaScore does not report passes into the box, progressive passes
# or pressures — but it does report the carry, under names nobody thought to look
# for: ``totalProgression``, ``ballCarriesCount``, ``progressiveBallCarriesCount``,
# ``totalBallCarriesDistance``, ``totalProgressiveBallCarriesDistance`` and
# ``bestBallCarryProgression``. They arrive on 15-45% of appearances (the provider
# omits the field rather than sending a zero) and land in
# ``MatchAppearance.raw_stats`` like everything else, so no re-scrape is needed to
# start using them. Carrying the ball forward is currently worth nothing in this
# model, and that is an omission we chose by accident, not on purpose. Measured
# against the human pagella the raw signal is thin on its own (``totalProgression``
# correlates 0.069 with it for defenders), which is why it has not simply been
# added: it needs its own calibration, not a weight guessed here.
# NOTA SUL BLOCCO DELLE CONCLUSIONI: i pesi qui sotto sono a **x0.45** di come
# nascono (x0.50 il 01/09/2026 perche' li pagavamo 3-5 volte tutti e tre i giudici,
# poi un ulteriore x0.90 lo stesso giorno). Il secondo taglio serviva a tenere
# Piotrowski sotto la soglia dopo l'alleggerimento dei duelli dei difensori — che
# lo alzava — e vale la pena saperlo: da solo non avrebbe una motivazione propria.
#
# --- I SOTTOINSIEMI DEL DUELLO, x0.5 il 01/09/2026 ----------------------------
# ``aerials_won``, ``aerials_lost`` e ``tackles_won`` non sono eventi ACCANTO al
# duello: sono duelli, contati una seconda volta sotto un altro nome. Un contrasto
# vinto e' un duello vinto, un aereo vinto pure. Correlazioni fra le voci del
# blocco, solo DIF >=60' (n=3096): duelli vinti contro aerei vinti **0.66**, contro
# contrasti vinti **0.49**; tutto il resto sta fra -0.11 e 0.43, e la prima
# componente principale del blocco spiega solo il 34.3% — il blocco NON e' una cosa
# sola, ma quelle due voci si' che stanno dentro la terza.
#
# E' lo stesso difetto della xA coi passaggi chiave, dall'altra parte del campo, ed
# era gia' un appunto aperto nel codice per il lato dei duelli PERSI (v. la nota
# sotto ``duels_lost``: "duels_lost CONTIENE i duelli aerei persi, zero violazioni
# su 10.950 presenze"). Qui si chiude anche per il lato vinto.
#
# IL CASO: Rrahmani in Genoa-Napoli della 1a giornata 26-27 a 7.5 — 13 duelli
# vinti, 8 aerei, 12 respinte, 4 contrasti, tutti sopra 4 sigma. Gli 8 aerei e i 4
# contrasti SONO dentro i 13 duelli: lo pagavamo tre volte per gli stessi
# interventi. A 0.5 fa 7.0 (grezzo 7.19).
#
# PERCHE' 0.5 E NON ZERO: l'attributo non e' nullo — vincere di testa contro un
# centravanti e vincere un rimpallo non sono la stessa cosa, e il fornitore la
# distinzione la porta. Meta' peso dice "conta, ma come sfumatura del duello che ho
# gia' contato". A 0.3 il voto di Rrahmani scende ancora (7.15) e l'accordo peggiora
# su tutti e tre i giudici: 0.5 e' il punto in cui il doppio conteggio sparisce e il
# segnale no.
#
# MISURATO contro il tagliare INVECE l'intero blocco (dieci voci x0.78, che era la
# prima versione di questa correzione e non aveva altra motivazione che il voto di
# Rrahmani): i sottoinsiemi vincono su OGNI criterio — Redazione 0.6841 contro
# 0.6834, Statistico 0.6941 contro 0.6923, SofaScore **0.7639 contro 0.7570**, MAE
# 0.3598 contro 0.3613 — e portano Rrahmani allo stesso 7.0. Il prezzo rispetto al
# non toccare niente scende da -0.012 a -0.005 di correlazione con SofaScore.
PER90_WEIGHTS = {
    # 0.0252 -> 0.0132 il 29/08/2026, insieme a ``dribbles_attempted`` che sale
    # della stessa cifra: e' UNA modifica sola in due righe, e separarle non ha
    # senso. Il motivo sta li' sotto.
    # RITARATO IL 04/09/2026: 0.0132 -> 0.0483. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "dribbles_won": 0.0483,
    # x0.70 il 01/09/2026 — e questo peso ormai vale SOLO per CEN e ATT, perche' i
    # difensori hanno un valore assoluto in ROLE_WEIGHTS. Coefficiente per 1 sd dopo
    # il taglio: CEN +0.151, ATT +0.211, contro Redazione +0.089/+0.144 e Statistico
    # +0.131/+0.176 — restiamo SOPRA entrambe le pagelle e sotto SofaScore
    # (+0.251/+0.330), cioe' dentro la forbice.
    #
    # ONESTA' SUL PERCHE': a differenza del taglio ai difensori, qui NON c'e' un
    # argomento di gioco — per una punta vincere un duello e' un modo di creare, e
    # infatti i giudici glielo pagano piu' che a un difensore. C'e' solo "due pagelle
    # su tre dicono di abbassare", con SofaScore che dice il contrario di parecchio.
    # Il caso che l'ha chiesto: Laurienté, Sassuolo, 2a giornata — "solo 1 duello
    # vinto" era la terza voce del suo pannello e ne cancellava meta' del positivo.
    # Passa da 6.0 a 6.5 (grezzo 6.26).
    #
    # IL PREZZO CUMULATO di tutto il lavoro sui duelli: SofaScore 0.7950 -> 0.7847,
    # Redazione ferma a ~0.696, errore medio invariato. Dieci millesimi su un solo
    # giudice, lo stesso ordine di grandezza che altrove abbiamo giudicato
    # significativo. Se un domani si torna indietro, si torna indietro da qui.
    # RITARATO IL 04/09/2026: 0.0442 -> 0.0164. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "duels_won": 0.0164,
    # RITARATO IL 04/09/2026: -0.0631 -> -0.1011. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "duels_lost": -0.1011,          # the losing side of the contests we reward
    # RITARATO IL 04/09/2026: azzerato (era -0.0341). Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "dribbled_past": 0,       # subset of duels_lost: beaten one-on-one is worse
                                    # ...ma SOLO per un difensore: v. ROLE_WEIGHTS
    # IL BLOCCO DEL POSSESSO, x0.50 il 01/09/2026 — questo peso, ``passes_completed``
    # e ``touches``. Sono TRE MODI DI CONTARE LA STESSA COSA: r(palloni giocati,
    # passaggi riusciti) = 0.92, r(palloni giocati, passaggi in meta' campo
    # avversaria) = 0.76, e la prima componente principale del blocco spiega il
    # 48.9% della sua varianza — contro il 34.3% del blocco dei duelli, che proprio
    # per quella cifra avevamo giudicato NON essere una cosa sola.
    #
    # E lo pagavamo come tre. Coefficiente per 1 sd in punti di voto, controllato
    # per le altre venti voci del modello (5.775 presenze >=60' senza gol ne'
    # assist, 25-26): il blocco intero valeva +0.283 per noi contro +0.039 della
    # Redazione, +0.063 dello Statistico e +0.197 di SofaScore. Sette volte una
    # pagella, quattro e mezzo l'altra.
    #
    # Misurato lo sweep sulla scala del trio: la Redazione sale monotona
    # (0.6922 -> 0.7016 a 0.50 -> 0.7055 a 0.20), lo Statistico pure
    # (0.7064 -> 0.7137 -> 0.7174), l'errore medio cala (0.3674 -> 0.3640 ->
    # 0.3593), e SofaScore cala piano (0.7811 -> 0.7762 -> 0.7726). x0.50 e' il
    # punto in cui il blocco resta FRA le pagelle e SofaScore invece di scavalcare
    # SofaScore verso il basso: si toglie il doppio conteggio, non il possesso.
    #
    # ``long_balls_completed``, ``crosses_completed`` e ``touches_in_box`` NON sono
    # nel taglio: le loro correlazioni col trio stanno fra -0.17 e +0.46, sono
    # un'altra cosa, e su una di quelle (i lanci lunghi) siamo gia' sotto SofaScore.
    #
    # IL CASO: Dybala in Lecce-Roma prendeva 8.0 — sopra Malen e Soule' che avevano
    # segnato — con +0.53 di possesso, di cui +0.35 per aver toccato la palla 47
    # volte nella meta' campo avversaria in una partita vinta 4-0 dalla sua squadra.
    # Cioe' il merito di stare nella squadra che aveva il pallone. Ora 7.5.
    # RITARATO IL 04/09/2026: azzerato (era 0.0548). Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "passes_opp_half": 0,      # progression: a pass in the opponent half is worth more
    # APPUNTO APERTO (29/08/2026), rimandato di proposito. ``duels_lost`` CONTIENE
    # i duelli aerei persi: verificato su 10.950 presenze della 25-26 con zero
    # violazioni su entrambi i lati (duels_lost >= aerials_lost, duels_won >=
    # aerials_won + dribbles_won), residuo mai negativo, ed esattamente uguale in
    # 950 casi su 5.829 — che con conteggi separati sarebbe una coincidenza assurda.
    # Sono il 30,4% dei duelli persi della stagione.
    #
    # NON e' pero' lo stesso caso dei dribbling, e la differenza e' il motivo per
    # cui qui non si e' toccato niente. Li' un tentativo fallito costava PIU' di un
    # duello perso qualunque, il che era assurdo di suo; qui il peso e' gia' la
    # parametrizzazione giusta — ``aerials_lost`` E' il sovrapprezzo dell'aereo
    # rispetto a uno a terra, e -0.0314 potrebbe benissimo essere corretto: un
    # pallone alto perso e' spesso in area, su un cross. Si sposta un peso solo e
    # si misura l'accordo coi giudici, come per i dribbling. Finche' non lo si fa,
    # non c'e' un difetto accertato: c'e' una domanda senza risposta.
    # RITARATO IL 04/09/2026: azzerato (era 0.0159). Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "aerials_won": 0,
    # RITARATO IL 04/09/2026: -0.0157 -> -0.0086. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "aerials_lost": -0.0086,
    # RITARATO IL 04/09/2026: 0.0107 -> 0.0190. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "tackles_won": 0.019,          # a committed, deliberate intervention
    # RITARATO IL 04/09/2026: 0.0117 -> 0.0324. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "was_fouled": 0.0324,           # an opponent had to stop you illegally
    # RITARATO IL 04/09/2026: 0.0331 -> 0.0268. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "long_balls_completed": 0.0268,
    # RITARATO IL 04/09/2026: azzerato (era 0.0222). Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "crosses_completed": 0,    # (reactivated by the hand-tuning)
    # RITARATO IL 04/09/2026: azzerato (era 0.0072). Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "touches_in_box": 0,
    "interceptions": 0.0298,
    # RITARATO IL 04/09/2026: 0.0187 -> 0.0067. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "ball_recoveries": 0.0067,
    # RITARATO IL 04/09/2026: azzerato (era 0.0116). Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "blocks": 0,
    # RITARATO IL 04/09/2026: 0.0226 -> 0.0647. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "clearances": 0.0647,
    # passes_completed/touches held at 0.01: the earlier kurtosis-gradient nudge
    # (0.01 -> 0.02, with passes_opp_half 0.05 -> 0.06) flattened the distribution
    # toward Statistico's, but that low kurtosis is a symptom of Statistico being
    # result-driven, not a target — and the possession up-weight worked against
    # tempering high votes in defeats (Koopmeiners). Reverted; result-awareness is
    # instead carried by the (stronger) result mitigation below.
    "passes_completed": 0.0192,
    # RITARATO IL 04/09/2026: 0.0125 -> 0.0347. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "touches": 0.0347,
    # RITARATO IL 04/09/2026: -0.0189 -> -0.0510. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "errors_bad_passes": -0.051,
    # RITARATO IL 04/09/2026: -0.0163 -> -0.0217. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "errors_dispossessed": -0.0217,
    # RITARATO IL 04/09/2026: -0.0190 -> -0.0281. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "errors_miscontrols": -0.0281,
    # RITARATO IL 04/09/2026: -0.0114 -> -0.0249. Le righe qui sopra raccontano come si
    # era arrivati al valore PRECEDENTE; il ragionamento calcistico resta
    # valido, la cifra a cui conduceva no. Il modello vecchio con tutte le
    # sue motivazioni sta in experiments-scrape-whoscored/dati_modello/
    # modello_precedente_2026-09-01.py.
    "errors_fouls_committed": -0.0249,
    # dribbles_won(+) / dribbles_attempted(-) is a deliberate RATE pairing, like
    # duels_won/duels_lost: the negative on the superset makes the net contribution
    # turn negative below a break-even success rate, so many failed take-ons cost
    # even if a few come off. NOT here: possession_lost (possessionLostCtrl) — it is
    # 79% the SAME losses already penalised by errors_dispossessed/miscontrols/
    # bad_passes (same sign, no rate counterpart), so it just doubled the malus on
    # one event and made those weights un-interpretable. Raise the specific errors_*
    # to weigh ball loss more, not this aggregate.
    #
    # -0.0194 -> -0.012 on 2026-08-25. What sets this number is the RATIO to
    # dribbles_won, and at -0.0194 ours was -0.77 — far harsher on the attempt than
    # either external judge. Fitted on 25-26 against the pagella and the SofaScore
    # rating (n=6829 appearances over 60', goals and assists controlled), per σ:
    #
    #             riusciti   tentati   rapporto
    #   Redazione   +0.069    -0.022     -0.32
    #   SofaScore   +0.162    -0.083     -0.51
    #   noi (era)   +0.0252   -0.0194    -0.77
    #   noi (ora)   +0.0252   -0.012     -0.48   <- dentro la forbice dei due
    #
    # A SECOND argument was checked and is WEAKER than it was remembered: the
    # failed take-on is only partly double-counted as a lost ball. Measured, one
    # failed dribble adds +0.232 registered ``dispossessed`` (0 failed -> 0.51 of
    # them, >=3 failed -> 1.28), i.e. about one in four. The 79% figure above is
    # about possessionLostCtrl, an aggregate we do NOT carry — it is not this.
    # The overlap justifies a nudge; the ratio is what justifies the size.
    # -0.012 -> 0.0000 il 29/08/2026. ``dribbles_attempted`` CONTIENE i riusciti
    # (verificato: >= dribbles_won in 5.247 casi su 5.247), quindi alzarlo da solo
    # avrebbe premiato anche chi il dribbling lo completa — che e' gia' pagato da
    # ``dribbles_won`` e dal duello vinto. Alzandolo di 0.012 e abbassando
    # ``dribbles_won`` della stessa cifra il netto del RIUSCITO resta identico
    # (+0.0764) e a guadagnare e' solo il FALLITO.
    #
    # E il fallito passa da -0.0751 a -0.0631, cioe' esattamente quanto un duello
    # perso qualunque. E' la frase che questo numero adesso dice: tentare un
    # dribbling non e' di per se' ne' un merito ne' una colpa, conta il duello che
    # vince o perde. Prima costava PIU' di un duello perso generico, perche' lo
    # stesso evento veniva addebitato due volte — i dribbling falliti sono il 15,2%
    # dei duelli persi della stagione e stanno tutti dentro ``duels_lost``.
    #
    # PERCHE' NON PIU' IN LA'. Il netto del riuscito e' invariante alla
    # compensazione, quindi si potrebbe salire fino a rendere il fallito positivo;
    # ma da +0.045 in su ``dribbles_won`` diventa NEGATIVO, e una tabella dei pesi
    # che dice "completare un dribbling vale -0.02" e' falsa letta da sola anche se
    # il netto torna. E l'accordo coi giudici cala in modo monotono a ogni passo
    # (Redazione 0.6347 -> 0.6303, Statistico 0.6597 -> 0.6507, SofaScore 0.7826 ->
    # 0.7694 fra 0 e +0.077), quindi fra i valori ammessi il piu' piccolo che fa il
    # lavoro e' il migliore: qui costa -0.0003, -0.0011 e -0.0016.
    "dribbles_attempted": 0.0000,
}

WEIGHTS = {**TOTAL_WEIGHTS, **PER90_WEIGHTS}  # union, for feature fetch / breakdowns

# --- Pesi PER RUOLO ------------------------------------------------------------
# Il modello ha UN vettore di pesi per tutti i ruoli di movimento: i ruoli si
# distinguono solo per la media e la dispersione contro cui l'indice viene
# z-scorato. Questa tabella e' la prima e unica eccezione, e va tenuta tale — ogni
# voce qui e' un pezzo di modello che va tarato e verificato tre volte invece di
# una.
#
# ``dribbled_past`` (SofaScore ``challengeLost``, v. la nota sul suo peso): essere
# saltati uno contro uno e' un evento di mestiere per un difensore e un non-evento
# per un attaccante che perde una palla in ripartenza. Le due pagelle umane la
# leggono cosi', e in modo netto. Coefficienti per 1σ sulla 25-26 (n=6829
# presenze ≥60'), controllati per il duello perso ORDINARIO — di cui questo e' un
# sottoinsieme — piu' duelli vinti, tocchi, gol e assist:
#
#                        DIF               CEN               ATT
#   Redazione     -0.040 ±0.011     +0.004 ±0.010     +0.026 ±0.012
#   Statistico    -0.035 ±0.012     -0.007 ±0.010     +0.003 ±0.013
#   SofaScore     -0.006 ±0.009     +0.010 ±0.007     +0.008 ±0.010
#
# Il difensore lo paga con tre-quattro sigma di margine; il centrocampista no;
# per l'attaccante la Redazione ha perfino il segno positivo. SofaScore non lo
# distingue per nessuno: addebita il duello perso e si ferma. Quanto capita:
# 0.50 volte a partita per un DIF (14.9% dei suoi duelli persi), 0.33 per un ATT
# (6.0%).
#
# ONESTA' SULLA MISURA. Il guadagno d'accordo NON si vede: fra il peso globale di
# prima, questa tabella, e l'azzeramento totale della feature, l'intero spettro e'
# 0.003 di correlazione, e l'arm nominalmente migliore sulla Redazione era
# azzerarla del tutto (0.6475 contro 0.6445). Nessun arm muove un solo voto dei
# casi in esame. La ragione probabile e' che ``duels_lost`` pesa da noi -0.102 di
# voto per σ contro il -0.034 della Redazione, cioe' tre volte: il posto che il
# giudice riempie col dribbling subito, noi lo abbiamo gia' occupato col duello
# perso. Se questa voce va rivista, il numero da guardare e' il LIVELLO di
# ``duels_lost``, non un altro split per ruolo. Questa tabella e' tenuta per il
# senso calcistico dell'evento, con la misura che non la contraddice ma nemmeno la
# conferma — deciso il 25/08/2026.
# ``duels_lost`` (01/09/2026). Per un attaccante il duello e' un TENTATIVO, per un
# difensore un DOVERE: perderlo non e' lo stesso evento. I tre giudici lo dicono
# tutti, con lo stesso ordinamento e senza eccezioni — coefficiente per 1 sd
# (sigma globale), n=6848 presenze >=60', controllato per duelli vinti, aerei
# vinti/persi, gol, assist e minuti:
#
#                      DIF       CEN       ATT
#   Redazione       -0.087    -0.049    +0.007
#   Statistico      -0.144    -0.130    -0.018
#   SofaScore       -0.217    -0.193    -0.153
#   noi, prima      -0.076    -0.080    -0.068   <- PIATTO
#
# Per le due pagelle un duello perso da un attaccante costa ZERO. E l'attaccante ne
# perde di piu' (5.42 a partita contro 3.34 di un difensore), quindi col peso unico
# lo punivamo due volte: per il numero e per il prezzo.
#
# I rapporti sono la media dei tre giudici normalizzata sul centrocampista (DIF
# 1.35, CEN 1.0, ATT 0.35), riscalati perche' la media pesata sulla popolazione
# resti quella di prima: e' una RIPARTIZIONE fra ruoli, non un taglio.
#
# SOLO ``duels_lost``, e non il duello vinto: li' l'ordinamento dei giudici (ATT
# sopra DIF) il modello lo riproduce GIA' da solo — noi +0.167 / +0.133 / +0.226
# contro il +0.080 / +0.089 / +0.144 della Redazione — perche' i duelli di un
# attaccante viaggiano con le altre voci offensive. Una seconda tabella per ruolo
# dove la misura non la chiede sarebbe peso morto da ritarare tre volte.
# ``duels_won`` PER I DIFENSORI (01/09/2026), che completa l'asimmetria aperta con
# ``duels_lost``: per chi difende perderne uno che porta al gol conta piu' che
# vincerne nove, quindi le due meta' del duello non possono avere lo stesso peso.
# Coefficiente per 1 sd sul duello VINTO: noi +0.167 contro il +0.080 della
# Redazione e il +0.123 dello Statistico (ma il +0.256 di SofaScore).
#
# DUE COSE DA SAPERE, e sono il motivo per cui questa riga va guardata per prima se
# un giorno il modello va rivisto:
#
# 1. Il coefficiente RISULTANTE e' +0.146, non il +0.067 che il conto lineare
#    prometteva: la sigma si stringe e ne riassorbe gran parte (misurato dopo, sul
#    modello vero — il conto a mano su un peso solo NON vale mai in questo modello,
#    e' la terza volta che se ne ha la prova). Quindi il taglio NON esce dal recinto
#    dei giudici: atterra fra lo Statistico (+0.123) e SofaScore (+0.256).
#    Il prezzo misurato: SofaScore 0.7950 -> 0.7908, Redazione 0.6955 -> 0.6964,
#    errore medio invariato a 0.3295.
# 2. Il valore (0.0210, sceso da 0.02528 quando il globale e' passato a x0.70) e'
#    stato scelto per far scendere UN VOTO di due centesimi: Rrahmani in
#    Genoa-Napoli, che resta a 7.24 con la soglia a 7.24. E' un margine di un
#    centesimo, e la prima revisione dei dati puo' rimandarlo a 7.5. Provati anche
#    0.0240 (non basta) e 0.0225 (basta ma per MENO di mezzo centesimo: due valori
#    che stampano entrambi "7.25" danno voti mostrati opposti). Piotrowski invece
#    ha guadagnato margine da solo col taglio a CEN+ATT: da 7.75 a 7.72.
#
# Cioe': la modifica ha un argomento calcistico che regge da solo, ma la TARATURA
# fine e' su due nomi e su due centesimi. Se un domani i numeri si muovono, non
# inseguirli: rileggere questa nota e decidere di nuovo.
ROLE_WEIGHTS = {
    Player.ROLE_MID: {"duels_lost": -0.0975, "duels_won": 0.0257},
    Player.ROLE_FWD: {"duels_lost": 0, "duels_won": 0.0238},
}


def weights_for_role(role: str) -> dict:
    """Il vettore dei pesi che l'indice usa per QUESTO ruolo.

    Una funzione sola, perche' il voto e la sua SPIEGAZIONE devono leggere lo
    stesso vettore: una spiegazione costruita sui pesi globali non tornerebbe col
    voto che spiega."""
    if role == Player.ROLE_GK:
        return GK_WEIGHTS
    over = ROLE_WEIGHTS.get(role)
    return {**WEIGHTS, **over} if over else WEIGHTS


# Shot-outcome detail lives in the event-level shot map (``MatchShot.shot_type``),
# not the per-zone features, so it is fetched and merged separately (see
# ``_merge_shot_detail``). Solo ``shots_blocked`` e ``shots_off`` hanno un peso
# proprio; ``shots_post`` e ``shots_goal`` non ne hanno (il primo entra solo dentro
# sga_post, il secondo e' uscito dall'indice) e ``shots_saved`` e' mappato per
# completezza e ispezione. Il commento diceva il contrario fino al 29/08/2026.
SHOT_TYPE_TO_FEATURE = {"post": "shots_post", "goal": "shots_goal",
                        "save": "shots_saved", "miss": "shots_off",
                        "block": "shots_blocked"}
SHOT_DETAIL_FEATURES = frozenset(SHOT_TYPE_TO_FEATURE.values())

# --- Derived features ---------------------------------------------------------
# The execution term has to be built BEFORE the compression (see the shooting-block
# note above): once each part is transformed separately it can no longer be
# recombined. A woodwork strike gets no xGOT from the provider, so its execution
# merit — a shot that beat the keeper and hit the frame — would read as zero; it is
# credited here at the rate our own weights gave it relative to an xGOT unit.
# RICALATO da 0.73 a 0.40 il 29/08/2026, e il numero adesso ha un significato che
# si puo' controllare: e' la SOGLIA DI xGOT sopra la quale una parata vale piu' di
# un palo. A parita' di occasione l'xG si semplifica — SGA(parata) = xGOT − xG,
# SGA(palo) = W − xG — quindi W e' letteralmente "quanto vale, in xGOT, aver preso
# il legno". A 0.73 batteva il 97,4% dei tiri parati della 25-26: piu' della
# MEDIANA DI UN GOL (0.626), e in punti di voto il palo prendeva +0.592 di SGA
# medio contro i +0.274 di un gol vero. A 0.40 sta all'85° percentile delle parate:
# lo batte una buona parata, non gli arriva un tiro debole e centrale — che e' il
# giudizio che si voleva.
SGA_POST_WOODWORK = 0.40
# UN TIRO MURATO NON VALE NIENTE, e la ragione non e' una scelta di gusto: e' che
# l'xG ha GIA' scontato il rischio di essere murati, quindi qualunque imputazione
# positiva conta due volte la stessa cosa.
#
# La costante valeva 0.1378, cioe' P(in porta | NON murato) x E[xGOT | in porta].
# L'errore sta nel condizionamento: "non murato" e' un evento favorevole che il
# modello dell'xG mette gia' nel prezzo, e ridare il valore pieno di chi al muro e'
# scampato significa pagare due volte quella fortuna. Tre misure sulla 25-26, tutte
# nella stessa direzione (31/08/2026):
#
#  1. un tiro murato porta gia' META' xG: 0.056 di media contro 0.111, e 0.057
#     contro 0.113 a parita' di zona di campo. Se il modello ignorasse i difensori
#     porterebbe lo STESSO xG di uno non murato dalla stessa posizione;
#  2. i tiri non murati rendono il 113% del loro xG (gol/xG 1.130, contro 0.947 su
#     tutti i tiri). Quel 13% in eccesso e' esattamente l'xG che siede sui murati e
#     non si converte mai. Se l'xG fosse condizionato al "non murato", i non murati
#     renderebbero ~1.00;
#  3. Sigma xGOT / Sigma xG su TUTTI i tiri, con murati e fuori a zero, fa 0.965 —
#     il sistema torna gia' da solo. Ogni imputazione positiva e' un surplus che il
#     modello non aveva: con 0.1378 i murati mettevano +208.9 di SGA sulla stagione
#     invece di toglierne 143.6, e sga_post complessivo valeva +392.8 invece di
#     +40.3.
#
# RESTA UN ARGOMENTO DALL'ALTRA PARTE, ed e' quello che aveva fatto nascere la
# costante: farsi murare non sarebbe una qualita' ripetibile del tiratore
# (correlazione meta'-meta' -0.006 su 143 giocatori contro +0.174 dei tiri fuori),
# quindi addebitarlo sarebbe addebitare rumore. Due obiezioni: giustificherebbe la
# NEUTRALITA' (imputazione = xG, SGA zero), mai un premio; e la sua premessa non si
# riproduce — su meta' stagione contro meta', >=15 tiri per meta', 67 giocatori, la
# quota di murati correla +0.051 e quella dei tiri fuori +0.062, cioe' nessuna
# delle due sembra ripetibile a quel campione. Se un giorno si volesse tornare
# sulla neutralita', la leva e' questa costante messa a "xG del tiro murato" e non
# a un numero fisso — il che richiede la somma degli xG dei murati, che
# ``_merge_shot_detail`` puo' produrre senza ri-estrarre niente.
SGA_POST_BLOCKED = 0.0

# --- LA CONVESSITA' DELLA SGA -------------------------------------------------
# ``sga_post`` nasce come DIFFERENZA DI SOMME (xGOT totale meno xG totale), quindi
# e' lineare nei tiri: dieci mezze conclusioni sbilenche possono valere quanto una
# grande occasione messa dentro. Con un esponente > 1 applicato al singolo tiro —
# f(d) = segno(d) * |d|^p — le deltas piccole si schiacciano verso lo zero e le
# grandi restano, per cui la stessa somma pesa di piu' quando viene da un colpo solo
# che quando viene da molti tentativi.
#
# 1.0 = la somma esatta. La scala della feature viene ricalibrata dopo, quindi
# l'esponente cambia la FORMA e non il livello.
#
# PROVATO E RESPINTO il 01/09/2026, e vale la pena sapere PERCHE' invece di
# riproporlo: l'idea era separare chi accumula mezze conclusioni da chi ne ha una
# grande e la mette dentro. La prima meta' non succede e la seconda non discrimina.
#
#   esponente | bersagli | Raimondo (2 gol) | Piotrowski (1 gol) | Tavares (5 tiri)
#       1.0   |    11    |      6.92        |       7.86         |      7.43
#       1.3   |     9    |      7.23        |       8.17         |      7.43
#       1.6   |     8    |      7.19        |       8.25         |      7.42
#
# Raimondo sale (+0.31), ma sale ESATTAMENTE INSIEME a Piotrowski, perche' per il
# singolo tiro sono lo stesso evento — una grande occasione convertita. Cio' che li
# distingue e' che Raimondo l'ha fatta due volte, e una convessita' PER TIRO non
# puo' vederlo. Dall'altro lato Tavares, cinque conclusioni, non si muove di un
# centesimo: le sue deltas non sono abbastanza piccole perche' l'esponente le
# schiacci, e la ricalibrazione della sigma riassorbe il resto.
#
# La macchina resta (il calcolo TIRO PER TIRO, che gli aggregati non possono dare)
# perche' e' il substrato di qualunque lavoro futuro sul singolo tiro, e a 1.0 la
# strada vecchia e' ancora quella percorsa: nessun comportamento cambia.
SGA_CONVEXITY = 1.0
DERIVED_FEATURES = ("sga_post",)
# Weighted features that are neither zone features nor computed: folded in from
# elsewhere in the DB (see ``_merge_defensive_value``). Kept apart from
# DERIVED_FEATURES so "computed from other features" keeps meaning that.
MERGED_FEATURES = ("defensive_value", "assists")
# Inputs consumed by ``derived_features`` that carry no weight of their own and so
# would otherwise never be fetched.
DERIVED_INPUTS = frozenset({"xg_on_target", "shots_post"})


def derived_features(totals: dict) -> dict:
    """{feature: value} for features computed FROM the provider totals, not stored.

    ``sga_post`` = xGOT − xG + legno: the shot's post-strike value over its
    pre-strike value, i.e. what the player added by hitting it the way he did. It is
    legitimately NEGATIVE for a wasteful shooter (five shots off target: xGOT 0, xG
    0.4) and the compression preserves that sign.

    Il legno ha un addendo suo perche' il fornitore da' xGOT solo ai tiri in porta:
    a un tiro sul palo assegna zero, non perche' valesse zero ma perche' non e'
    misurabile, e SGA_POST_WOODWORK e' l'xGOT che avrebbe avuto. Il tiro MURATO
    non ha piu' un addendo (SGA_POST_BLOCKED = 0): li' lo zero e' la risposta
    giusta, non un buco di misura — v. il commento della costante."""
    # Con l'esponente a 1 si usa la differenza di aggregati, che e' la definizione
    # storica e NON dipende dalla mappa dei tiri: cosi' una riga senza mappa (o un
    # test che costruisce i totali a mano) continua a funzionare identica.
    if SGA_CONVEXITY != 1.0 and "_sga_shots" in totals:
        return {"sga_post": totals["_sga_shots"]}
    return {
        "sga_post": (totals.get("xg_on_target", 0.0) - totals.get("xg_shots", 0.0)
                     + SGA_POST_WOODWORK * (totals.get("shots_post") or 0.0)
                     + SGA_POST_BLOCKED * (totals.get("shots_blocked") or 0.0)),
    }

# --- Goalkeeper channel ------------------------------------------------------
# Keepers produce almost none of the outfield features above, so they need their own
# index. The anchor is goals_prevented (xG-on-target faced MINUS goals conceded): the
# cleanest "did he do better or worse than expected" measure, and the only one that
# accounts for shot difficulty. Saves from inside the box (harder) weigh more than
# saves overall.
# NOTE the raw goal count is NOT here: conceding goals is handled by the classic
# -1/goal MALUS in the bonus layer, exactly as the voto-puro/bonus split requires.
#
# Reweighted 2026-07-29 against both fantacalcio sheets over the 764 keeper-matches
# of 2025-26 (see build_voto_benchmark). The keeper channel was the model's weakest
# (agreement r 0.60 against 0.64-0.74 for the outfield roles), and the diagnosis was
# not that a term was missing but that ONE term was doing everything: goals_prevented
# carried 87% of the channel, so the vote tracked the raw goal count harder than
# either external vote does (our correlation with goals conceded -0.52, theirs -0.31
# and -0.37) — and the -1/goal malus is then applied on top of that, as it is for
# them, which is where the double count showed.
#
# A ridge fit of both external base votes on this same feature basis says what the
# hand weights had wrong, and it says it twice with the same sign:
#   * save VOLUME is worth ~0.15-0.29 of the anchor to them, 0.07 to us -> doubled;
#   * an error leading to a goal is worth ~0.7-0.8 of the anchor to them, 0.16 to us
#     -> tripled (the "papera"). Held at 0.60 rather than the fitted 1.2 because the
#     season carries only 30 such matches: 0.60 is where the residual bias on those
#     matches meets the channel's own average bias, i.e. where a keeper who lets one
#     in is treated no differently from anyone else. Fitting it harder inverted the
#     sign of that bias (-0.33) on 30 samples, which is chasing noise;
#   * a keeper's "inaccurate passes" are mostly long distribution, a style, not an
#     error: the external fit prices it POSITIVE (+0.06). We do not reward a misplaced
#     ball, but we stop punishing it -> 0.
GK_TOTAL_WEIGHTS = {
    "gk_goals_prevented": 1.0655,     # SIGNED: negative when he underperforms the xG faced
    # ZERO ON PURPOSE, and this one is a matter of principle rather than of fit.
    #
    # The model's rule everywhere else is: do not pay the FACT of an event, read the
    # MERIT inside it — that is why a goal is priced through the shot's post-strike
    # value (sga_post) and not by counting goals. A saved penalty already obeys that
    # rule without any help: the penalty's xGOT enters xGOT-faced, so saving one adds
    # its xGOT to gk_goals_prevented, GRADED BY DIFFICULTY — the 22 saved penalties of
    # 2025-26 range from 0.587 to 0.899 of xGOT, so a well-placed one credits half
    # again as much as a weak one, which is exactly the "was he good or was it a bad
    # penalty?" question. In vote points that merit is already worth +0.50 for a
    # keeper on zero goals prevented. A penalty missed WITHOUT a save (3 in the
    # season) carries no xGOT and so credits nothing: right by construction.
    #
    # Anything on top of that is a blind prize for the outcome, and it is already
    # paid in the open by the +3 fantavoto bonus. Briefly set to 0.357 on 2026-07-30
    # chasing the pagelle, which price the fact at +0.63/+0.66 on top of the merit;
    # reverted the same day. The cost of the principle, measured: MAE 0.3296 ->
    # 0.3407, r 0.6517 -> 0.6271 against the Redazione and 0.6804 -> 0.6649 against
    # the Statistico, and we sit 0.44 below them on those 22 appearances. The judge
    # that reads EVENTS rather than outcomes agrees with the principle: SofaScore's
    # rating correlates 0.7821 without the prize against 0.7808 with it.
    #
    # Kept as an explicit 0 rather than deleted: the feature is still fetched and
    # still listed in the per-feature table, so the choice stays visible.
    "gk_penalty_saves": 0.0404,
    "errors_led_to_goal": -0.5659,    # the papera — see above
    "errors_led_to_shot": -0.1123,
    # THE KEEPER WHO GIFTS A CHANCE, verified 2026-07-30 rather than assumed. These
    # two are how a misplaced ball from the keeper registers: 30 keeper-matches carry
    # an error that led to a GOAL (3.9%, worth -0.87 of a vote each) and 29 an error
    # that led to a SHOT (3.8%, -0.14 each). Both land within 0.04 of neutral against
    # the pagelle on exactly those appearances (-0.03 and +0.04), and both are at the
    # optimum of the range tested: dropping the goal one to -0.45 or -0.30 pushes the
    # residual to +0.12 and +0.29 and costs 0.005-0.022 of correlation, while raising
    # the shot one to -0.20/-0.30 overshoots to -0.08/-0.22. They need nothing.
    # NB it is these two, and NOT ``errors_bad_passes``, that read the gift:
    # inaccurate passes fire in 97.5% of keeper-matches (7,667 of them in a season) —
    # that is long distribution, a style, which is why it carries no keeper weight.
}
GK_PER90_WEIGHTS = {
    "gk_saves_inside_box": 0.4666,
    "gk_saves": 0.2795,
    "gk_high_claims": 0.1135,       # command of the area
    "gk_sweeper": 0.0703,           # sweeper-keeper interventions
    "gk_punches": 0.0547,
    "gk_crosses_not_claimed": -0.0616,
    "passes_completed": 0.0036,     # distribution, marginal
}
GK_WEIGHTS = {**GK_TOTAL_WEIGHTS, **GK_PER90_WEIGHTS}

# --- L'AUTOGOL DI UN COMPAGNO, dal punto di vista del portiere ----------------
# ``gk_goals_prevented`` arriva dal provider come "xGOT dei tiri affrontati meno i
# gol subiti", e i gol subiti includono gli autogol. Un pallone messo dentro da un
# proprio difensore non è un tiro affrontato: non entra nella somma a credito, ma
# pesa per intero a debito. Il risultato è che l'autogol costa al portiere un'unità
# intera nella misura che pesa il 60% del suo canale — cioè lo accusiamo di un gol
# su cui poteva poco, o niente.
#
# Il caso che l'ha portato alla luce (Inter-Verona 1-1, 37ª giornata 2025-26):
# Montipò para 5 tiri su 6, l'unico gol è l'autogol di Edmundsson su corner, e il
# campo del provider vale 0.642 (xGOT delle sue parate) − 1 = −0.358, a fronte di
# un autogol il cui xGOT è 0.915 — un pallone che nessun portiere prende. Voto 6.0
# contro il 7.5 di entrambe le pagelle e il 7.4 del rating SofaScore.
#
# LA CORREZIONE non è esentare il portiere: un retropassaggio che lui liscia è un
# autogol del difensore e una papera sua. È restituire all'autogol la sua
# DIFFICOLTÀ, come per qualsiasi altro pallone che finisce in porta — che è la
# regola del modello anche in positivo (un gol vale per come è stato calciato, un
# rigore parato per quanto era difficile).
#
# Dove l'xGOT dell'autogol c'è si usa quello, e i casi si graduano da soli: 0.915
# per Montipò (voto 6.0 -> 6.5), mentre l'autogol da 0.468 di Napoli-Cremonese
# lascia Audero a 6.0, perché quel pallone si parava.
#
# IL DEFAULT esiste perché su 22 autogol del 2025-26 l'xGOT c'è solo in 2: il
# provider non attribuisce un valore post-tiro a un autogol (e nessun xG a nessuno
# dei 22 — probabilmente non lo considera un tiro). 0.834 è l'xGOT MEDIANO di un
# gol da occasione chiara (xG > 0.3, n=349), scelto su tre argomenti:
#   * tutti gli autogol misurati sono eventi da distanza ravvicinata, dove la
#     mediana dei gol veri sale (0.663 nella fascia più vicina alla porta contro
#     0.626 in generale);
#   * un tiro che arriva da un compagno è più difficile a parità di xGOT, perché il
#     portiere non se lo aspetta — non lo possiamo misurare, ma spinge nella stessa
#     direzione, quindi si sta all'estremo alto della forbice difendibile invece di
#     inventare un premio;
#   * NON 1.0: la neutralizzazione completa dichiarerebbe il portiere estraneo per
#     definizione. Con 0.834 gli resta addosso un residuo di 0.166 — e quando è
#     davvero colpevole paga già altrove, con ``errors_led_to_goal`` a −0.60 (che
#     nelle 23 presenze con autogol dei compagni si accende una volta sola).
# Misurato: 0.834 muove 20 delle 22 presenze, +0.45 di voto in media; 1.0 ne
# muoverebbe 20 con +0.48. Fra le due cambia UNA presenza su ventidue, quindi la
# scelta è di principio e non di numeri.
OWN_GOAL_KEEPER_XGOT_DEFAULT = 0.834

# QUI STAVA GK_EVIDENCE_FULL, lo smorzamento del voto del portiere quando gli
# erano arrivati meno di quattro tiri in porta. Rimosso il 31/08/2026, e le tre
# misure che l'hanno chiuso vanno tenute perche' l'idea e' seducente e tornera'.
#
#  1. NON SERVIVA PIU' AL CASO PER CUI ERA NATO. Era stato introdotto per il
#     portiere inoperoso che finiva sotto il 6 senza colpe. Con zero tiri
#     affrontati, acceso e spento davano lo STESSO identico risultato: media
#     6.00, nessuno sotto il 6, in accordo con la Redazione (6.02, 0%). Il
#     centro di ruolo (POR 6.15) e il credito d'assenza fanno gia' tutto il
#     lavoro; il freno non contribuiva niente.
#
#  2. COMPRAVA ACCORDO PEGGIORANDO L'ORDINAMENTO. Nel gruppo dove agiva (meno
#     di 4 tiri, n=344) il MAE contro la Redazione scendeva da 0.250 a 0.198,
#     ma la CORRELAZIONE peggiorava: 0.547 -> 0.538 con la Redazione, 0.581 ->
#     0.538 con lo Statistico. E' la firma della riduzione di varianza, non
#     dell'informazione: spingendo verso un centro dove il bersaglio e' gia'
#     ammucchiato, l'errore medio cala mentre si dice meno. La nostra sigma in
#     quel gruppo passava da 0.415 — praticamente identica al loro 0.401 — a
#     0.272, cioe' un terzo piu' stretta di chi stavamo cercando di imitare.
#
#     La verifica che l'aveva promosso guardava la popolazione sbagliata: la
#     sigma GLOBALE restava larga (0.603 contro 0.545) solo perche' la tengono
#     su le partite con 4+ tiri, che il freno non toccava.
#
#  3. I GIUDIZI CHE SOPPRIMEVA ERANO IN MAGGIORANZA GIUSTI. Nei 45 casi in cui
#     senza freno bocciamo un portiere che la Redazione promuove, tre arbitri
#     che non dipendono dal nostro modello stanno con noi: rating SofaScore
#     6.40 (contro 7.02 di chi promuovono entrambi e 6.21 di chi bocciano
#     entrambi) e Statistico 6.00 contro 6.24. Nella cella specchio — noi
#     promuoviamo, loro bocciano — i casi sono 11, un quarto, e li' lo
#     Statistico sta con loro: non siamo giusti in ogni direzione, ma di gran
#     lunga piu' spesso in una.
#
# Il prezzo pagato, che va detto: sui portieri con 2-3 tiri mandiamo sotto il 6
# il 21.9% contro il 10.1% della Redazione. Non e' ampiezza — la nostra sigma e
# la loro coincidono — e' che le redazioni un portiere non testato quasi mai lo
# bocciano. Su quella asimmetria abbiamo deciso di non inseguirle.
#
# La papera resta punita dove deve: ``errors_led_to_goal`` a -0.60 quando il
# fornitore la marca, e ``gk_goals_prevented`` (xGOT affrontato meno gol subiti,
# gia' pesato per la difficolta') quando non la marca — che e' il caso piu'
# frequente, ed e' esattamente quello che il freno dimezzava.

# --- Tail compression ---------------------------------------------------------
# Applied to EVERY feature, in units of that feature's own spread (see
# ``_feature_z``). The shape is
#
#     f(u) = K · log(1 + |u| / K) · sign(u)
#
# which is the identity to first order at the origin (f'(0) = 1) and logarithmic
# far out: it shortens tails WITHOUT the defect of the √ it replaces, whose
# derivative is infinite at zero and therefore inflated every small value — the
# known problem with √ on quantities living in [0, 1] like xG and xGOT, where a
# 0.02 chance was magnified to 0.14. Being odd, it also handles the features that
# are legitimately negative (goals prevented, and now sga_post) without the special
# case ``_compress_signed`` used to carry.
#
# K is in SIGMA units, and that is the whole point of doing it after the first
# standardisation: compression starts at the same distance from the mean for every
# feature. Applied to raw values instead — the literal 2·log(1 + x/2) — the same
# constant means 0.09σ for touches and 18σ for xA, so it would crush the
# well-behaved volume features and leave the fat-tailed ones untouched, which is
# backwards. Measured over the season, K = 2 takes xA's maximum from 13.1σ to 6.6σ
# and its excess kurtosis from 16.0 to 4.5, while touches moves only 4.5σ -> 3.2σ.
# Rare binary events (an error leading to a goal) are untouched by construction, as
# they should be: nothing about a 1-in-70 event is a "tail" to be tamed.
#
# Lowered 2.0 -> 1.0 on 2026-07-29. The effect sits inside the noise on agreement
# (defender r -0.004, midfielder -0.003, attacker +0.005) but moves the one thing
# it can move in the right direction: the attackers' share of votes >= 8 falls from
# 3.5% to 2.9% against 1.2% externally, and their excess kurtosis from +0.3 to +0.1.
# It cannot do more, and it is worth knowing why. The >= 8 tail is 100% goalscorers,
# and for an attacker who scored exactly once our mean matches fantacalcio's to two
# decimals (7.01 against 7.03) while our spread is 0.55 against their 0.33 — they
# put 187 of 265 such matches on exactly 7.0 and stop, we read the rest of the game
# on top. Closing that gap would mean compressing the performance reading
# CONDITIONAL on the goal, i.e. converging on "a goal is worth 7 whatever else
# happened" — the outcome-driven behaviour this model deliberately avoids. The
# residual is therefore a choice, not a defect.
# ALZATO 1.0 -> 3.0 il 25/08/2026. La compressione accorciava le code di tutti, ma
# su quelle grasse mordeva troppo: a u = 9,7 (Dybala, xA 1,09) tratteneva il 24% del
# valore, per cui una prestazione tre volte piu' creativa ne ricavava 1,7 volte il
# credito. Alzare K libera le code IN PROPORZIONE invece di esentare una feature
# sola, che e' la stessa cura applicata a tutti — merito del passaggio e merito
# della conclusione insieme.
#
# Quanto trattiene ora la xA: 94% al 50° percentile, 74% al 90°, 51% al 99°, 30% al
# massimo di stagione. Cioe' morde dove deve, sopra il novantesimo.
#
# Misurato sulla 25-26 con i pesi di oggi: massimo di campionato 9.0, voti >= 8 allo
# 0.83% e >= 9 allo 0.04% (esternamente 1.2% e 0.05%) — la coda alta degli
# attaccanti, che l'abbassamento a 1.0 del 29/07 era servito a chiudere, NON si
# riapre. Accordo: Redazione 0.660, Statistico 0.692, SofaScore 0.775.
COMPRESS_K = 1.7567

# Features that are NOT compressed. The compression exists to shorten FAT tails —
# the xA that motivated it reached 13σ with excess kurtosis +16. Applied to a
# well-behaved variable it does the opposite of its job: it removes resolution at
# both ends and buys nothing.
#
# ``gk_goals_prevented`` is the one place where that mattered, for two reasons
# together. Its raw excess kurtosis over the reference population is **+0.87** —
# essentially Gaussian, against +12.5 for shots_goal, +16.0 for xA, +17.6 for
# xg_shots — and the compression drives it to **-0.63**, i.e. BELOW Gaussian, with
# its maximum falling from 3.74σ to 2.58σ. And it carries 60% of the keeper channel,
# so its squashed tail was the keeper's squashed tail: no keeper could reach 8.0
# because an 8.5 needs 3.99σ of index and the channel could not produce it.
#
# Measured, exempting it alone: both agreements improve (r 0.6293 -> 0.6330 against
# the Redazione, 0.6669 -> 0.6690 against the Statistico) and the high tail lands
# exactly on theirs (>= 7.5: 2.2% against 2.2%; >= 8.0: 0.7% against 0.7%), at a cost
# of 0.003 in MAE. This is NOT a prize for an outcome — it is the same merit measure
# (xGOT faced minus goals conceded, graded by shot difficulty) read without being
# flattened.
#
# Deliberately NOT a blanket rule on kurtosis: a < 1.5 threshold would also catch
# touches, ball_recoveries and duels_won in the outfield channel, which is calibrated
# and asks for nothing. And exempting the two save-volume features as well was
# measured and REJECTED — it overshoots (>= 7.5 to 3.0%) and makes both correlations
# worse than this single exemption.
# RIENTRATA la xA il 25/08/2026, poche ore dopo esserne uscita: v. la nota a
# COMPRESS_K, alzato a 3.0. Esentare UNA delle due misure di merito (la xA del
# passaggio) lasciando compressa l'altra (SGA, il merito della conclusione) era
# un'asimmetria che il voto pagava subito — Malen, tripletta col Milan, perdeva
# mezzo punto mentre Dybala ne guadagnava uno e mezzo, invertendoli rispetto a
# ENTRAMBI i giudizi esterni. La compressione piu' mite li libera insieme.
#
# (storia) Il difetto originale non era
# nella coda della distribuzione (la kurtosi compressa resta +3.15, quindi NON
# sovra-corretta) ma nell'ORDINAMENTO: a u = 9.7 la compressione tratteneva il 24%
# del valore, per cui una prestazione tre volte piu' creativa ne ricavava 1.7 volte
# il credito — Dybala in Roma-Fiorentina, 3 assist e 3 occasioni nitide, si fermava
# a 6.5 mentre le pagelle gli davano 8.5 e il rating del fornitore 9.1.
#
# Perche' la LINEARIZZAZIONE e non solo un peso piu' alto: alzare il peso sulla
# curva compressa moltiplica ogni partita di ogni creativo e INCLINA la scala (il
# gradiente del nostro scarto dalle pagelle passa da 0.127 a 0.271); linearizzare
# agisce sull'alto della curva. Misurato sulla 25-26: Dybala a 8.0, massimo di
# campionato e quota dei voti >= 8 invariati, dispersione 0.564 -> 0.562.
#
# ATTENZIONE per chi rimisura: ``feature_scales()`` NON ricalcola, legge le scale
# congelate nel file. Cambiare la FORMA (questa lista, COMPRESS_K) e chiamare
# ``build_reference`` senza rifare le scale con ``build_feature_scales`` misura un
# modello che non esiste — per i soli PESI la scorciatoia invece e' corretta.
NO_COMPRESS_FEATURES = frozenset({"gk_goals_prevented"})


def _compression_of(key: str):
    """The compression this feature goes through: the identity for the exempt ones."""
    return (lambda u: u) if key in NO_COMPRESS_FEATURES else _compress

# --- One spread for every outfield role ---------------------------------------
# Each role keeps its own CENTRE (so a 6 means the same thing everywhere, which the
# pagelle agree with: their per-role means are 5.95 / 6.05 / 6.10) but they SHARE
# one spread instead of each being normalised to unit variance.
#
# Normalising per role looks neutral and is not: it makes the same event worth more
# to whoever's peers never do it. A goal adds roughly the same absolute amount to
# any index, but dividing by the role's own spread (DIF 0.368, CEN 0.418, ATT 0.478)
# made it 1.30σ for a defender and 1.00σ for an attacker — so we paid +1.34 for a
# defender's goal against fantacalcio's +1.02, and +0.96 for an attacker's against
# their +1.23. Exactly inverted. And self-reinforcing: an attacker scores in 23% of
# his matches against a defender's 4%, so goals are already inside the attacker's
# spread — the very spread that then divides them.
#
# The pagelle do the opposite: same centre for everyone, but a MUCH wider scale for
# attackers (their vote std is 0.606 / 0.614 / 0.752 for DIF / CEN / ATT). They
# treat a goal as an absolute value, not one relative to the role. Sharing the
# spread reproduces that almost exactly (0.560 / 0.614 / 0.708) because the index's
# own per-role dispersion turns out to be the right one — forcing each role to unit
# variance was destroying real signal.
#
# Measured: defender max 9.0 -> 8.5 and votes >= 8 from 1.2% to 0.9% (externally
# 0.2%), defender MAE 0.407 -> 0.388, attacker r 0.768 -> 0.770, and the goal
# premium flattens toward the external ordering. KNOWN COST: attackers reach >= 8 in
# 3.5% of matches against 1.2% externally — we go from too few to too many. The
# midfielder ceiling (9.0) is untouched by this and remains open: it is a breadth
# effect (a goal AND high volume in the same match), not a spread one.
POOLED_ROLE_SPREAD = True

# Tunables (calibrate against the real distribution before fixing).
VOTE_CENTER = 6.0
# RIDOTTO da 0.8 a 0.727 il 29/08/2026, e il numero non e' scelto: e' 0.8 x
# (0.4347 / 0.4781), il rapporto fra la sigma dell'indice dopo e prima l'uscita
# di ``shots_goal``. Togliendo il gol dall'indice se ne va anche la sua varianza,
# la sigma scende del 9,1%, e ogni deviazione dal centro finisce divisa per un
# numero piu' piccolo: il voto di CHI NON HA SEGNATO veniva amplificato del 10%
# senza che il giocatore avesse fatto niente per meritarlo (misurato su Yildiz,
# Frosinone-Juventus: +0.073 di puro riscalamento). Questo riporta il non-marcatore
# esattamente dov'era e chiude anche l'allargamento della sigma del voto che il
# credito del gol, sommato fuori dalla normalizzazione, introduceva.
#
# NB: il credito del gol e' in punti di voto e NON passa di qui, quindi abbassare
# K lo rende relativamente piu' pesante; la banda va risolta di nuovo, e
# ``calibrate_vote_reference`` lo fa da solo contro lo stesso bersaglio.
VOTE_SPREAD_K = 0.727      # vote points per 1 std of within-role index
# ...MA NON PER IL PORTIERE. La riduzione sopra compensa una varianza che l'indice
# di MOVIMENTO ha perso; il canale del portiere ``shots_goal`` non l'ha mai avuto,
# la sua sigma e' rimasta 2.2172 identica, e applicargli lo stesso taglio gli
# comprimeva i voti del 9% per una modifica che non lo riguarda (sigma del voto
# 0.625 -> 0.568, e 2 pagelle su 22 mosse nelle prime due giornate).
GK_SPREAD_K = 0.8013266957001832


def spread_k_for(ref_key: str, default: float = VOTE_SPREAD_K) -> float:
    """Quanti punti di voto vale una sigma dell'indice, per questo canale."""
    return GK_SPREAD_K if ref_key == Player.ROLE_GK and default == VOTE_SPREAD_K else default

# --- Il centro PER RUOLO -------------------------------------------------------
# Fino al 25/08/2026 il centro era 6.0 per tutti, e la questione era stata chiusa
# (02/08/2026) con l'argomento che il portiere basso compensa la coda alta dei
# difensori. La riapre un riscontro degli utenti — «i difensori sono valutati
# troppo generosamente» — che la misura conferma: sulla 25-26 la nostra media DIF
# e' 6.003 contro il 5.9225 della Redazione (+0.080), mentre i CEN stanno a +0.018
# e gli ATT a +0.014.
#
# E' un problema di CENTRO, non di pesi. Nessun peso lo muove: la
# z-standardizzazione per ruolo inchioda ogni ruolo al suo centro per costruzione,
# e la ricalibrazione riassorbe qualunque cambio di peso (misurato: abbassando
# `defensive_value` da 0.100 a 0.070 la media DIF resta 6.002). L'unica leva e'
# questa.
#
# PERCHE' 5.91 E NON 5.920. Due cose, e nessuna e' un dettaglio.
#
# (a) Il centro non e' la media: e' il punto attorno a cui il voto e' costruito, e
#     l'arrotondamento a mezzo punto su una distribuzione non simmetrica lo sposta
#     di ~+0.008. Misurato sulla 25-26 (3908 presenze DIF):
#
#       centro 6.000 -> media 6.0026     centro 5.920 -> media 5.9278
#       centro 5.905 -> media 5.9130     centro 5.930 -> media 5.9365
#
#     Se si ritocca, si guarda la media REALIZZATA, mai il centro.
#
# (b) IL CENTRO DEVE STARE SULLA GRIGLIA DEI CENTESIMI. La spiegazione del voto
#     riconcilia a due decimali (`base` + le voci mostrate + `other_points` deve
#     fare `subtotal`), e tutte le sue voci sono arrotondate al centesimo. Un
#     centro a tre decimali lascia un residuo che nessuna di quelle voci assorbe:
#     con 5.912 quattro test della riconciliazione fallivano di 0.008 esatti. Se
#     serve una taratura piu' fine del centesimo, va prima resa robusta la
#     riconciliazione — non alzata la tolleranza dei test.
#
# DUE CONSEGUENZE, entrambe volute e decise il 25/08/2026:
#
# 1. Il MODIFICATORE DIFESA scatta meno spesso. La sua soglia e' 6.00 assoluto —
#    un numero FISSO del regolamento, che NON insegue il centro del ruolo — quindi
#    se un difensore ordinario non vale piu' 6, la difesa che prende il bonus deve
#    essere piu' brava. Misurato: bonus medio +1.071 -> +0.915, squadre a zero
#    bonus dal 38.9% al 44.5%. Una compensazione era stata scritta e poi TOLTA:
#    non riproporla.
#
# 2. La scala 66/+6 che converte i punti in gol e' anch'essa assoluta, e ogni
#    squadra perde ~0.25 di totale (3-4 difensori x 0.08). E' uniforme, quindi non
#    favorisce nessuno, ma rende i gol marginalmente piu' rari. Compensarla
#    romperebbe la somma VISIBILE del tabellino (voto + bonus = fantavoto), quindi
#    non si compensa.
#
# L'accordo non ci perde: una traslazione non muove una correlazione, ma
# riallinea l'arrotondamento, e la Redazione GUADAGNA (0.6425 -> 0.6455) perche'
# eravamo sistematicamente sopra di lei. Statistico -0.0006, SofaScore -0.0007.
#
# IL PORTIERE, 6.15, dal 30/08/2026. Stessa diagnosi dei difensori letta al
# contrario: sulla 25-26 (765 presenze POR, tutte con voto Redazione E Statistico)
# stavamo sotto di 0.129 e 0.132. Non e' rumore ed e' la stessa cifra da mesi.
#
# Lo sweep del centro, contro i DUE fogli separatamente, cade sullo stesso punto a
# un centesimo di distanza — che e' la ragione per cui ci si puo' credere: sono due
# redazioni diverse.
#
#   centro   Redazione: scarto  |scarto|  entro 0.5      Statistico: idem
#    6.00      -0.129    0.333    87.8%                   -0.132  0.346  86.9%
#    6.10      -0.037    0.321    88.4%                   -0.041  0.324  88.4%
#    6.15      +0.012    0.308    89.7%                   +0.009  0.316  89.7%
#    6.20      +0.054    0.318    89.5%                   +0.051  0.320  89.7%
#
# LA CONSEGUENZA VA NELLA DIREZIONE OPPOSTA a quella dei difensori. La soglia del
# modificatore difesa e' un 6.00 fisso, il portiere pesa per un quarto della media di
# reparto, quindi alzarlo di 0.15 alza quella media di 0.0375 e il bonus scatta PIU'
# spesso. Misurato sulle 760 difese della 25-26 (portiere + i tre difensori migliori,
# coi nostri voti):
#
#   bonus medio  +0.976 -> +1.066     difese a zero bonus  43.2% -> 39.5%
#   69 difese salgono di una banda, 3 scendono
#
# VA DETTO CHIARO: i due centri di ruolo quasi si annullano su questo modificatore.
# Il 25/08 i difensori l'avevano portato da +1.071 a +0.920; questo lo rimette a
# +1.066, cioe' praticamente al punto di partenza. Non e' una svista ed e' l'esito
# giusto: ognuno dei due centri e' tarato sul suo ruolo contro le pagelle, e il
# modificatore e' una CONSEGUENZA di quei due numeri, non un obiettivo. Chi volesse
# governarlo lo faccia dalla sua tabella di bande, non spostando un centro.
# Non si compensa, per la stessa ragione di allora: la soglia e' del regolamento e
# non insegue i nostri centri.
#
# QUELLO CHE IL CENTRO NON RISOLVE, e non deve sembrare che risolva: lo scarto medio
# e' la media di due errori opposti. A >=6 parate stiamo +0.31 SOPRA la Redazione, a
# >=4 tiri con >=2 gol subiti -0.09 sotto, e sono le due popolazioni con la
# dispersione piu' alta (0.54 contro 0.27-0.42 altrove). La scala e' troppo ripida
# sulle partite piene. Una traslazione non tocca una pendenza: resta aperto.
ROLE_VOTE_CENTER = {Player.ROLE_DEF: 5.91, Player.ROLE_GK: 6.180503465289575}


# --- LA SATURAZIONE DELLA SCALA (movimento) ------------------------------------
# Ultimo stadio del voto, DOPO la mitigazione e i cartellini: la parte del voto che
# sta SOPRA il centro del ruolo viene compressa da una curva logaritmica, e poi tutto
# il ruolo viene riportato su media e dispersione delle pagelle.
#
#     voto = centro'_r + a_r * sat(v - centro_pre_r)      sat(d) = T*log1p(d/T), d>0
#                                                         sat(d) = d,            d<=0
#
# A che serve. Il voto grezzo ha la coda alta piu' lunga di quella di una pagella: chi
# fa una grande partita prende, da noi, piu' di quanto un giudice umano gli darebbe, e
# il grosso della differenza sta li'. Comprimere solo il lato alto accorcia quella coda
# senza toccare i voti bassi, che invece erano gia' giusti; il fattore ``a_r`` che segue
# riapre la dispersione fino a quella delle pagelle. Il risultato e' un ordinamento
# quasi identico e una FORMA molto piu' simile.
#
# ``centro_pre`` NON e' ``vote_center_for``: e' la media empirica del voto del ruolo
# prima di questo stadio, cioe' il punto attorno a cui si comprime. Sono cose diverse e
# vanno tenute separate — il centro del ruolo e' un prior, questo e' un baricentro
# misurato.
#
# IL PORTIERE NON PASSA DI QUI. La curva e' tarata sulla dispersione del movimento e sul
# portiere fa il danno opposto: la sua coda alta era gia' piu' corta di quella del
# giudice, e comprimerla dimezzava i voti sopra il 7,5 (32 -> 16) tappando la stagione a
# 7,5. Il portiere prende la stessa correzione come CENTRO e DISPERSIONE (v.
# ROLE_VOTE_CENTER e GK_SPREAD_K), che sono lineari e non toccano la forma.
VOTE_SATURATION_T = 1.0
ROLE_SATURATION = {          # ruolo: (centro_pre, centro_dopo, fattore)
    # Per intero, non per vezzo: v. la nota sulla riproducibilita' sopra.
    Player.ROLE_DEF: (5.955666852686118, 6.061230791524389, 1.5485834273858712),
    Player.ROLE_MID: (6.052875763317001, 6.1238237595148695, 1.596370972734363),
    Player.ROLE_FWD: (6.097521915325461, 6.155905316629372, 1.676461101184294),
}


def scale_saturation(vote: float, ref_key: str) -> tuple[float, float]:
    """Il voto dopo lo stadio finale, e DI QUANTO e' stato riscalato.

    Il secondo valore serve alla spiegazione: la scomposizione del voto e' additiva
    (base + una fetta per voce) e una curva non lineare in fondo la farebbe non
    tornare. Moltiplicando ogni fetta per questo fattore, e usando ``centro_dopo``
    come base, la somma torna esatta — perche' il fattore e' definito proprio come
    "quanto e' diventato lo scostamento dal centro".
    """
    p = ROLE_SATURATION.get(ref_key)
    if not p:
        return vote, 1.0
    pre, dopo, a = p
    d = vote - pre
    compresso = VOTE_SATURATION_T * math.log1p(d / VOTE_SATURATION_T) if d > 0 else d
    out = dopo + a * compresso
    return out, (a * compresso / d if abs(d) > 1e-12 else a)


def vote_center_for(role: str) -> float:
    """Il centro attorno a cui il voto di QUESTO ruolo e' costruito.

    E' anche il prior verso cui l'attenuazione sui minuti fa regredire una
    presenza breve: per un difensore «non abbiamo visto abbastanza» significa
    5.92, non 6.0."""
    return ROLE_VOTE_CENTER.get(role, VOTE_CENTER)

# --- Il voto di partenza dipende da QUANTO HAI GIOCATO ------------------------
# L'indice non e' neutro rispetto ai minuti: chi gioca poco ne accumula meno, e
# non solo nel blocco dei totali (dove sarebbe per costruzione) ma anche nei
# TASSI per-90, che dovrebbero esserlo. Misurato sulla 25-26, indice medio per
# fascia di minuti: CEN da -0.02 (1-15') a +0.40 (90'), ATT da -0.04 a +0.42.
# L'attenuazione sui minuti non lo cura — moltiplica lo scostamento per w<1,
# quindi RIDUCE un numero negativo invece di portarlo a zero.
#
# NON E' UN ARTEFATTO DELLA COMPRESSIONE. L'ipotesi Jensen (trasformazione
# concava + tassi piu' rumorosi sugli spezzoni) e' stata testata e RESPINTA: il
# costo della compressione e' costante fra le fasce (-0.18 / -0.14 / -0.15 /
# -0.18) e senza compressione la pendenza e' identica. I tassi per-90 di chi
# entra sono davvero piu' bassi — chi subentra impiega tempo a entrare nel
# match, e spesso entra a partita decisa. E' una circostanza, non un demerito.
#
# L'EFFETTO SUL VOTO, e perche' e' un difetto e non una scelta: premiavamo i
# minuti +0.0443 punti ogni 10', contro +0.0224 della Redazione e +0.0271 dello
# Statistico — il DOPPIO. Separando titolari e subentrati si vede dove: sui
# titolari eravamo a 0.91 volte la Redazione (corretti), sui subentrati la loro
# pendenza e' NEGATIVA (-0.027: al cameo piu' corto danno il voto piu' alto,
# perche' dieci minuti non si giudicano) e la nostra positiva (+0.037). Segno
# opposto.
#
# LA CURA: si sottrae all'indice una frazione dello scostamento della media
# condizionata ai minuti (``by_minute`` nella reference). Condizionare sui
# MINUTI e non sullo stato titolare/subentrato e' deliberato: e' continuo,
# quindi non crea il gradino del subentrato precoce (l'entrato al 5' finisce in
# una fascia popolata da titolari e viene giudicato come loro), e a 56-75
# minuti le due popolazioni convergono da sole (scarto +0.012).
#
# LA DOSE E' PIENA (1.0), e il bersaglio su cui e' stata scelta NON e' "quanti
# stanno sotto il 6". Quella misura mescola due popolazioni e porta fuori strada:
# la media alta che le redazioni danno al cameo (6.14 a 1-15') non e' un livello
# di partenza generoso, e' tutta figlia dei PRODUTTORI. Scomposta:
#
#   cameo 1-15'      n     Redazione
#   ha segnato       36      6.88
#   assist, no gol   29      6.53
#   NIENTE          143      5.87     <- il vero bersaglio
#
# A chi entra e non combina niente danno 5.87, cioe' SOTTO il 6. Su quella cella:
#
#   assetto            1-15' niente   1-15' segna   16-30' niente   16-30' segna
#   oggi                   5.66           6.35          5.70            6.56
#   lambda 0.5             5.77           6.76          5.77            6.96
#   lambda 0.8             5.83           6.82          5.84            7.05
#   lambda 1.0             5.86           6.83          5.88            7.12
#   Redazione              5.87           6.88          5.82            7.03
#
# A 1.0 il cameo che non fa niente cade a UN CENTESIMO dal loro numero. Non c'e'
# sfondamento: alzando lambda si alza il pavimento, e il tetto lo alza beta.
#
# LA FORBICE SI APRE, che e' il contrario dell'appiattimento che il condizionamento
# sembrerebbe promettere. Distanza fra le due celle estreme del cameo: loro 1.01
# (5.87 -> 6.88), noi oggi 0.69 (5.66 -> 6.35), noi dopo 0.97 (5.86 -> 6.83).
# Togliendo l'effetto MECCANICO dei minuti resta la differenziazione VERA fra chi
# ha prodotto e chi no, e quella si allarga.
#
# LE STORTURE, cercate apposta: il titolare tolto presto e punito passa da 9 a 8
# casi su 52 (Redazione 11 su 47), e sopra il 7.5 nei cameo si arriva a 4 casi su
# 260 contro i 29 sopra il 7 della Redazione. L'attenuazione sui minuti resta e
# continua a schiacciare le code: si sposta DOVE si viene schiacciati, non QUANTO.
#
# PREZZO: 1.6 punti di accordo (90.2% -> 88.6% entro mezzo voto), con la
# CORRELAZIONE in salita (0.68 -> 0.69 contro la Redazione). E' la stessa firma
# del fattore evidenza del portiere, al contrario: li' si comprava accordo
# peggiorando l'ordinamento, qui si paga accordo per ordinare meglio.
# 1.0 -> 0.75 il 01/09/2026. A 1.0 si toglieva TUTTO cio' che il minutaggio
# spiega, e si toglieva troppo: il modello diventava piu' generoso di chi giudica
# con chi entra, e piu' severo con chi gioca tutta la partita.
#
# COME SI VEDE, e perche' non si era visto prima: non nella media degli spezzoni
# (che a qualunque lambda resta 5.94) ma nello SCARTO DALLA REDAZIONE FASCIA PER
# FASCIA. Sulla 25-26, presenze di movimento con voto esterno:
#
#   lambda | 20-45'  46-70'  71-89'  90-120' | oscillazione |  MAE
#     1.00 | +0.058  +0.089  -0.056  -0.071  |    0.160     | 0.3463
#     0.75 | +0.025  +0.086  -0.038  -0.054  |    0.140     | 0.3416  <-
#     0.50 | -0.006  +0.077  -0.021  -0.042  |    0.119     | 0.3418
#     0.25 | -0.035  +0.072  -0.003  -0.026  |    0.107     | 0.3425
#     0.00 | -0.066  +0.067  +0.013  -0.008  |    0.133     | 0.3438
#
# 1.0 e' il punto PEGGIORE sull'errore medio e il minimo cade a 0.75. Nessuno dei
# quindici casi di taratura si rompe scendendo (restano 11 centrati a 0.75 come a
# 1.0), e il difensore che segna due volte guadagna qualche centesimo.
#
# 0.50 e' un'alternativa legittima e misurata: stesso errore medio (+0.0002) con
# l'inclinazione piu' piatta (0.119 contro 0.140). Si e' scelto 0.75 perche' e' il
# minimo dell'errore, ma la scelta e' fra due valori quasi equivalenti, non fra
# giusto e sbagliato.
#
# RESTA APERTO: la fascia 46-70' e' positiva (+0.067) anche a lambda ZERO, quindi
# quella parte dell'inclinazione non e' opera del condizionamento e ha un'altra
# causa, non ancora cercata.
MINUTE_CONDITIONING = 0.75
# ...e il portiere ha il suo. Il canale del portiere e' tarato a parte (v.
# GK_SHRINKAGE_MINUTES) e vuole il condizionamento PIENO: la curva dei minuti del
# portiere e' quasi piatta — gioca 90' quasi sempre — quindi condizionarla al 75%
# non protegge nessuno spezzone e toglie solo segnale ai pochi che ci sono.
GK_MINUTE_CONDITIONING = 1.0


def minute_conditioning_for(ref_key: str) -> float:
    """Quanto dell'effetto-minuti si toglie dall'indice, per QUESTO canale."""
    return (GK_MINUTE_CONDITIONING if ref_key == Player.ROLE_GK
            else MINUTE_CONDITIONING)

# --- I FATTI OSSERVATI NON SI ATTENUANO ---------------------------------------
# L'attenuazione sui minuti esiste per una ragione precisa: un TASSO per-90
# estrapolato da dieci minuti e' una stima pessima, e non ci si puo' fidare.
# Quella ragione non vale per un FATTO: un tiro difficile messo all'incrocio e'
# accaduto, l'abbiamo visto per intero, e non c'e' nessuna incertezza campionaria
# da smorzare. Oggi invece ``w`` moltiplicava tutto l'indice, questi compresi.
#
# IL DIFETTO, misurato sulla 25-26. Chi entra e segna in 1-15 minuti prendeva in
# media 6.35 con UN SOLO caso su 36 sopra il 7; la Redazione gli dava 6.88 e 26
# su 36. A partita intera invece eravamo allineati (7.02 contro 7.06). Il credito
# del gol (``goal_adjustment``) non c'entra: quello e' gia' sommato DOPO
# l'attenuazione. A essere schiacciata era l'impronta del gol dentro l'indice —
# il tiro, l'xG, e soprattutto ``sga_post``, che col suo 0.1448 e' il peso piu'
# alto del modello. Il gol portava +0.34 dall'indice nel cameo contro +0.67 a
# partita intera: la meta' mancante era tutta li'.
#
# PERCHE' SOLO QUESTE E NON TUTTI I TOTALI. Scorporando l'intero blocco dei
# totali la dispersione degli spezzoni si allargava in modo SIMMETRICO: salivano
# i cameo sopra il 7 (bene) ma anche quelli sotto il 6 (male), e il guadagno del
# condizionamento spariva — sotto il 6 a <=30' tornava da 37.0% a 53.8%, cioe'
# al punto di partenza. Limitandolo ai fatti passa l'evento e non il rumore
# d'accumulo: chi entra e segna sale, chi entra e tocca quattro palloni no.
# Misurato: cameo che segnano sopra il 7 da 1/36 a 20/36, e sotto il 6 comunque
# in miglioramento (53.1% -> 43.4%).
#
# ``defensive_value`` RESTA FUORI, ed e' stato provato: e' un aggregato, non un
# evento, e scorporarlo portava i titolari tolti presto e puniti da 8 a 15 casi
# (la Redazione ne ha 11). Stessa ragione per ``key_passes``, ``expected_assists``
# e i conteggi di tiro grezzi (``shots``, ``shots_off``, ``shots_blocked``): sono
# accumulo, e da dieci minuti dicono poco.
#
# CENTRI E DISPERSIONI, dopo (contro Redazione / Statistico): i centri si
# spostano al massimo di 0.014 e ogni ruolo resta fra i due fogli (DIF 5.890 su
# 5.923/5.947, CEN 5.985 su 5.994/5.975, ATT 5.987 su 6.009/5.963). Le
# dispersioni crescono da SOTTO entrambi a dentro la forcella, piu' vicine allo
# Statistico: DIF 0.563 -> 0.591 (0.583/0.633), CEN 0.578 -> 0.615
# (0.579/0.618), ATT 0.644 -> 0.702 (0.681/0.726). Prezzo: 1.0 punti di accordo
# (90.2% -> 89.2% entro mezzo voto), accettato il 01/09/2026.
# QUANTO dei fatti osservati sfugge all'attenuazione. 1.0 = per intero, 0.0 =
# niente (il comportamento di prima dello scorporo). Esposto come costante il
# 01/09/2026 per poterlo MISURARE, e la misura ha confermato l'1.0.
#
# ATTENZIONE A COME SI MISURA: serve la reference con le CURVE DEI MINUTI
# attaccate (``build_minute_curves``, che chiama solo il comando di
# calibrazione). ``build_reference`` da solo non le mette, e senza ``observed_mean``
# questa costante non fa NIENTE: si misura un modello che non esiste, e il sintomo
# e' che ogni valore di gamma da' gli stessi identici numeri.
#
# LE DUE CELLE CHE LO SCORPORO ESISTE PER CURARE, sulla 25-26:
#
#   gamma | subentrato che segna | spezzoni <=30': sotto il 6 | Redaz  Sofa    MAE
#         |   noi contro 6.98    |   noi contro il 29.0%      |
#    1.00 |   7.05   (centrato)  |   29.7%   (centrato)       | 0.6820 0.7515 0.3793
#    0.25 |   6.71   (-0.27)     |   24.5%   (troppo buoni)   | 0.6807 0.7583 0.3663
#    0.00 |   6.63   (-0.35)     |   23.4%                    | 0.6829 0.7623 0.3614
#
# A 1.0 ENTRAMBE le celle sono centrate sulla Redazione. Abbassarlo non "protegge"
# gli spezzoni — fa il contrario di quel che sembra: stringe la dispersione, quindi
# ne manda MENO sotto il 6 e ci allontana dal giudice invece di avvicinarci.
# Chi protegge davvero lo spezzone e' MINUTE_CONDITIONING, che sposta il punto di
# partenza: a lambda=0 il sotto-il-6 salta al 54.6%.
#
# IL PREZZO, noto e accettato: 1.0 e' il punto peggiore sulle misure D'INSIEME
# (SofaScore 0.7515 contro 0.7623 a zero, MAE 0.3793 contro 0.3614). Compra
# precisione su 79 presenze al prezzo di 5300. E' la stessa scelta del commit che
# lo scorporo l'ha introdotto, che dichiarava 0.9 punti d'accordo: qui si vede su
# tutti e tre i giudici invece che su uno.
#
# NON usarlo per curare un voto alto singolo: provato il 01/09/2026 su N. Tavares
# (Lazio-Genoa, 2a giornata 26-27, difensore, 63', 5 tiri, a 8.0). Il suo grezzo si
# muove di 0.22 su TUTTO l'intervallo di gamma — il suo voto non viene da qui, ma
# dal blocco delle conclusioni letto con un vettore di pesi unico per tutti i ruoli
# (v. il "KNOWN COST" in TOTAL_WEIGHTS: serve una scala delle conclusioni per
# ruolo). Abbassare gamma per lui avrebbe rotto due celle tarate bene.
UNSHRINK_GAMMA = 0.0774

UNSHRUNK_FEATURES = frozenset({
    # La finitura: quanto e' valso il modo in cui ha colpito, e da dove.
    "sga_post", "xg_shots", "shots_on_target",
    # Eventi discreti, rari e pesanti: accaduti o non accaduti.
    "penalties_won", "penalties_conceded", "errors_led_to_goal",
    "errors_led_to_shot", "clearances_off_line",
})

VOTE_MIN, VOTE_MAX = 3.0, 10.0
MIN_MINUTES_REFERENCE = 20  # only games >= this define the reference distribution

# --- Result-mitigation (v2 stage 2) ------------------------------------------
# A mild nudge toward the team's result WHILE THE PLAYER WAS ON THE PITCH, acting
# ONLY on DIVERGENT cases: a high vote in a defeat comes down, a low vote in a win
# goes up — never the other way. It deliberately leaves aligned votes alone (a high
# vote in a win is untouched), which is what a symmetric additive term got wrong: it
# further exalted a De Ketelaere already high in a win. Calibrated by the
# SofaScore-merit correlation, not the result-based Statistico (which would be
# circular). Outfield only — the GK channel already reflects the result through
# goals-prevented. gd_on is the on-pitch goal difference (see on_pitch_goal_difference).
#
# The severity of the result scales as BASE + K·|gd_on|: K is the per-goal margin
# ("i gol successivi", weighted fine already), BASE is the discrete "a loss is a
# loss / a win is a win" that fires on the FIRST goal — so crossing draw→defeat
# weighs BASE+K, each further goal only K. Still divergence-only (it multiplies how
# far the vote is from the target), so an aligned vote is untouched.
#
# I DUE LATI NON SONO PIU' SIMMETRICI (30/08/2026) — v. RESULT_MITIGATION_LOSS_ANCHOR:
# nella sconfitta il bersaglio della tirata scende sotto il centro di ruolo, nella
# vittoria resta il centro. Le costanti qui sotto sono quelle del LATO VITTORIA e
# non sono state toccate: un voto basso in una goleada inflitta arriva al massimo
# al 6, mai oltre.
RESULT_MITIGATION_K = 0.15
RESULT_MITIGATION_BASE = 0.40
RESULT_MITIGATION_CAP = 1.0
# QUANTA PARTE dello scostamento dal centro il risultato può cancellare, al massimo
# — DAL LATO VITTORIA (dal 30/08/2026 la sconfitta ha la sua, più larga).
# Il tetto sopra è in punti di voto; questo è una quota, e serve a due cose che il
# solo cap non copriva.
#
# 1. BASE + K·|scarto| arriva esattamente a 1.00 a QUATTRO gol di differenza, cioè
#    cancellava il 100% dello scostamento: in una partita da 4+ gol nessuno poteva
#    prendere più di 6.0, qualunque cosa avesse fatto. In stagione 2025-26 sono 45
#    presenze inchiodate esattamente sul 6.0 — fra cui Moreo, due gol nel 6-2
#    dell'Inter, voto grezzo 6.876 e mitigazione −0.876 (pagelle 7.5 entrambe,
#    rating a eventi 8.7). «In una disfatta nessuno ha giocato bene» è il
#    ragionamento collettivo da cui il resto del modello si tiene lontano
#    deliberatamente — v. l'esposizione, che addebita per zona e non alla difesa.
#
# 2. Oltre i quattro gol la severità SUPERAVA 1 (1.15 a cinque, 1.30 a sei) e la
#    correzione scavalcava il centro: un 6.876 a −5 diventava 5.876, cioè una buona
#    prestazione in una disfatta finiva SOTTO il neutro, e specularmente un voto
#    basso in una vittoria larga finiva sopra. Contraddiceva l'invariante dichiarato
#    dal meccanismo ("sempre verso il 6, mai oltre"): mordeva su 7 presenze e su
#    nessuna cambiava il voto mostrato (l'eccesso stava sotto il mezzo punto
#    dell'arrotondamento), quindi era un difetto latente. Con una quota < 1 non può
#    più accadere per costruzione.
#
# 0.70 misurato sulle 834 presenze con almeno 3 gol di scarto appaiate ai due fogli:
# MAE 0.384 -> 0.385 contro la Redazione (bias +0.082 -> +0.084), invariato contro
# lo Statistico. Cioè non costa NIENTE in accordo — mentre togliere la mitigazione
# del tutto lo peggiora netto (0.411), per cui il meccanismo si guadagna il posto e
# solo la sua ampiezza era una scelta non fatta.
#
# QUANTO PESA DAVVERO, misurato e non stimato: sulle 6.866 presenze di movimento con
# un risultato non di parità il tetto cambia **5 voti** (4 in su di mezzo punto, 1 in
# giù: un voto basso in una vittoria larga che prima veniva rialzato di più). Le "45
# presenze inchiodate sul 6.0" non si riaprono quasi tutte, perché la maggior parte
# aveva un grezzo già vicino al 6 e l'arrotondamento le riporta lì comunque: quello
# che cambia sono i casi con uno scostamento vero, cioè Moreo (6.876 grezzo, da 6.0 a
# 6.5). Un tetto a 0.85 non ne avrebbe mosso nessuno. Il valore di questa modifica
# sta quindi nel principio e nell'invariante che ripristina, non nel numero di voti
# che sposta — e il benchmark lo conferma: divergenze 595 -> 596, tutto il resto
# identico alla terza cifra.
RESULT_MITIGATION_MAX_SHARE = 0.70

# --- Il lato SCONFITTA: l'ancora scende sotto il centro (30/08/2026) ----------
# Fino a qui il bersaglio della tirata era il centro di ruolo da entrambe le parti,
# quindi il risultato poteva SCHIACCIARE un voto alto sul 6 ma non portarlo sotto:
# in una goleada subita nessuno poteva prendere meno di quanto le sue statistiche
# valevano. Adesso, nella sola sconfitta, il bersaglio è ``centro − ANCHOR``.
#
# PERCHE'. Lo scarto residuo del voto finale contro la Redazione, per differenza
# reti in campo (2025-26, 9.774 presenze di movimento appaiate a entrambi i fogli,
# escluse quelle con rosso/autogol/rigore sbagliato, dove la contabilità dei due
# metodi diverge di suo):
#
#     scarto   −4     −3     −2     −1      0     +1     +2     +3
#     bias   +0.22  +0.21  +0.09  +0.02  −0.01  −0.04  −0.07  −0.20
#
# Sistematico, e la mitigazione di prima non lo toccava: il suo effetto MEDIO era
# −0.073 a un gol di scarto, −0.052 a due, −0.044 a tre, −0.042 a quattro. Cioè
# faceva MENO proprio nelle disfatte — perché in una goleada subita solo il 17%
# delle presenze sta sopra il centro (contro il 31% a un gol) e il meccanismo, che
# moltiplica lo scostamento, non ha su cosa mordere. Alzare BASE/K non serviva:
# provate tutte le combinazioni fino a quota 1.00, cambiano al massimo 29 voti su
# 9.933 in tutta la stagione e lasciano il bias a −3 esattamente a +0.21. Il
# tetto teorico della vecchia forma — azzerare OGNI scostamento — vale −0.06 di
# media sulle sconfitte da 3+ gol, contro i +0.21 da chiudere. Non era una
# taratura sbagliata, era la leva sbagliata.
#
# QUANTO E' MERITO E QUANTO E' LETTURA COLLETTIVA. A parità di nostro voto grezzo,
# la Redazione applica −0.47 a tre gol di scarto e lo Statistico −0.49; il rating
# SofaScore — giudice a eventi, riscalato alla stessa σ — applica −0.06. Cioè la
# severità delle pagelle nella sconfitta NON è merito misurabile. Prendendone una
# parte importiamo consapevolmente un pezzo di quel ragionamento collettivo da cui
# il resto del modello si tiene lontano (v. l'esposizione, che addebita per zona).
# La scelta è stata fatta sapendo questo, e per questo la parte presa è parziale.
#
# LE TRE COSTANTI, e il vincolo che le lega. Chiesto esplicitamente: a UN gol di
# scarto non deve cambiare niente di sostanziale. Misurando lo scostamento da
# ``centro − 0.35`` invece che dal centro, la severità che riproduce ESATTAMENTE
# l'effetto medio di prima a un gol (0.1719 punti di voto) è 0.35, non 0.55 —
# da cui BASE 0.15 + K 0.20. La media a un gol resta identica; la forma no, ed è
# l'unico effetto collaterale vero: cambiano 250 voti su 4.183 (6,0%), 159 in giù
# e 91 in su. Le prestazioni buone in una sconfitta di misura vengono punite MENO
# di prima (il grezzo 7.45 di Comuzzo in un 1-2 tiene il 7.0 invece di scendere a
# 6.5), quelle mediocri un po' di più. Sembra il verso giusto per entrambe.
#
# La QUOTA a 0.85 e non 0.70 è quel che rende visibile il resto: la caduta massima
# è quota·ANCHOR per chi sta esattamente sul centro, e con 0.70 fa 0.245, che non
# scavalca mai il bordo dell'arrotondamento — il 6.0 resterebbe 6.0 anche in un
# 0-4. Con 0.85 il centrocampista da grezzo 6.0 arriva a 5.5 dal terzo gol, che è
# lo scopo dichiarato della modifica. Restando SOTTO 1 nessuno viene inchiodato
# esattamente sull'ancora, quindi l'ordine di merito dentro la squadra sconfitta
# sopravvive: è la stessa ragione per cui la quota del lato vittoria è < 1.
#
# COSA PRODUCE, misurato sulla 25-26 (attuale -> nuovo): MAE 0.3482 -> 0.3425
# contro la Redazione e 0.3583 -> 0.3514 contro lo Statistico, voti entro mezzo
# punto 89,5% -> 90,1%, divergenze (fuori da ENTRAMBE le letture di almeno un
# punto) 597 -> 560. Il bias residuo nelle sconfitte si chiude quasi del tutto
# (−3: +0.21 -> +0.11, −2: +0.09 -> +0.03) e il lato vittoria resta dov'era, per
# costruzione. Si spostano 343 voti su 9.933: 323 giù di mezzo punto e 20 su.
# Nelle sconfitte da 3+ gol le insufficienze passano dal 73% al 90% (Redazione
# 89%) e la dispersione DENTRO la squadra sconfitta resta 0.447 contro 0.512 loro
# — cioè il merito individuale continua a vedersi, che era il vincolo. Tarato
# sulle giornate dispari e verificato sulle pari (0.3397 / 0.3454 contro 0.3456 /
# 0.3507 di prima), quindi non è sovradattamento.
#
# LO STESSO GIRO SULLO STRUMENTO UFFICIALE (``build_voto_benchmark``, che include
# anche portieri ed episodi e quindi dà numeri più grossi): divergenze **658 ->
# 619**, entro mezzo voto 89.2% -> 89.8% contro la Redazione e 88.6% -> 89.2%
# contro lo Statistico, corr 0.66 -> 0.67 e 0.68 -> 0.69, e il picco dei nostri
# voti esattamente sul 6 dal 42.5% al 39.7% (Redazione 36.4%) — la distribuzione
# si allarga verso la loro. Il bias generale scivola da −0.00 a −0.02, ed è la
# centratura di cui sopra. ATTENZIONE a confrontarsi con i numeri scritti altrove:
# il "595 divergenze" dell'11/08 è di prima del centro di ruolo e del modello a
# impatto, e sullo stesso codice di oggi il "prima" vale 658. Il confronto va
# rifatto, non citato.
#
# IL PREZZO ACCETTATO. (1) Togliendo da un lato senza restituire dall'altro la
# centratura scivola: medie realizzate DIF 5.912 -> 5.893, CEN 5.999 -> 5.987,
# ATT 6.009 -> 5.996, e il listone da 5.9569 a 5.9413. Un centesimo e mezzo, che
# si può compensare solo alzando ROLE_VOTE_CENTER (v. weights-rank-not-level) —
# ma quello sposterebbe anche i voti dei pareggi per rimettere a posto un
# centesimo, e non vale lo scambio. L'invariante dichiarato non è più "il voto
# puro è centrato sul 6" senza riserve: è centrato sul 6 nei pareggi, e mezzo
# centesimo sotto sul totale di stagione. (2) Moreo nella 22ª (due gol nel 2-6
# dell'Inter, grezzo 6.955) torna da 6.5 a 6.0 contro il 7.5 di entrambi i fogli:
# è il caso che aveva motivato RESULT_MITIGATION_MAX_SHARE l'11/08, e questa
# modifica lo ripaga. Succede per qualunque ancora ≥ 0.05 perché il suo grezzo è
# a cavallo del bordo dell'arrotondamento, quindi è il costo della direzione, non
# della taratura.
#
# NUOVO INVARIANTE, da tenere: il risultato non può mai portare un voto sotto
# ``centro_di_ruolo − ANCHOR`` (5.65 per un centrocampista, 5.56 per un difensore),
# né sopra il centro dal lato vittoria. Sostituisce "sempre verso il 6, mai oltre",
# che ora vale solo per le vittorie.
RESULT_MITIGATION_LOSS_ANCHOR = 0.35
RESULT_MITIGATION_LOSS_BASE = 0.15
RESULT_MITIGATION_LOSS_K = 0.20
RESULT_MITIGATION_LOSS_MAX_SHARE = 0.85

# --- Red-card performance adjustment (v2 stage 3) ----------------------------
# A sending-off is a PERFORMANCE fact the base vote must reflect, over and above
# the flat -1 fantacalcio malus in the bonus layer (which stays — real pagelle both
# drop the vote AND the malus applies). Two parts:
#   * a BASELINE that a sending-off always costs, itself graded by how justifiable
#     the offence was: RED_CARD_BASE + RED_CARD_SEV_BASE·sev. Being sent off is a
#     ruined performance whatever the clock says, and a violent conduct is a worse
#     one than a DOGSO.
#   * severity × man-down on top: how long the team then played a man short,
#     (match_end - red_minute)/90 — the part that reads the damage done.
# Gated ON THE PITCH: a post-match/bench card (minute < 0 or outside the player's
# window) had no in-game impact and adds nothing.
#     red_adj = -(BASE + SEV_BASE·sev + K·sev·down/90)
#
# LE COSTANTI SONO IN PUNTI DI VOTO, e ``voto_puro_for_match`` le divide per il
# fattore dello stadio finale prima di applicarle (v. ROLE_SATURATION). Senza quella
# divisione una correzione post-indice vale ~1,6 volte la sua costante sul movimento
# e 1,0 sul portiere: due significati diversi per lo stesso numero, e una ritaratura
# della scala che le sposta tutte in silenzio.
#
# PERCHE' QUESTA FORMA E QUESTI NUMERI (misurato il 04/09/2026 sui 64 espulsi in
# campo della 25-26, contro lo Statistico, col contro-fattuale senza il malus come
# stima della prestazione). La forma precedente — K·sev·down/90 + un fisso sui motivi
# indifendibili — non aveva BASELINE: un rosso al 90' costava 0,13 punti, cioe'
# praticamente si annullava, mentre il giudice ne toglie comunque ~0,9. Di li' veniva
# quasi tutto l'errore: nella fascia 85'+ eravamo +0,53 sopra di lui, e nel complesso
# 20 espulsi su 64 fuori di un punto pieno. Il vecchio RED_CARD_K = 2.0 NON era
# sbagliato: rifacendo la ricerca dentro la sua stessa forma riesce di nuovo 2.0. Era
# la forma a mancare di un pezzo.
# La punizione implicita del giudice, regredita sugli stessi 64:
#     -0,598(±0,245) - 0,885(±0,242)·(down/90) - 0,288(±0,273)·sev
# cioe' una baseline che noi non avevamo, meta' della nostra pendenza sul minuto, e
# una gravita' che LUI non legge affatto (per gruppo toglie -1,12 / -1,11 / -1,12 a
# DOGSO, fallo e condotta violenta). La gravita' resta comunque nostra, e resta di
# proposito: il voto puro deve leggere il GESTO, non limitarsi a duplicare il malus
# forfettario che il fantavoto aggiunge gia' per conto suo. Il prezzo di tenerla e'
# misurato ed e' piccolo — v. sotto.
# Il malus che ne esce, in punti di voto: 0,82 per un DOGSO al 90', 1,15 per un fallo
# a meta' partita, 1,85 per una condotta violenta al 1'. Ampiezza 1,03 contro i 3,05
# di prima; il rapporto fra il caso piu' lieve e il piu' grave passa da 30:1 a 2,3:1.
# Fuori campione (tarato sulle giornate dispari, verificato sulle pari, n=35):
# espulsi fuori di un punto 13 -> 7, fuori di un punto e mezzo 8 -> 0, divergenze
# (fuori da ENTRAMBE le letture) 12 -> 2.
# L'AMPIEZZA E' GRATIS FINO A ~1,0 E POI COSTA: tenendone 1,6 invece di 1,03 riporta
# gli errori da un punto e mezzo da 0 a 2 su 35. Non allargarla senza rimisurare.
# RED_CARD_FIXED e' stato tolto e non va rimesso: la gravita' e' gia' dentro la
# baseline via RED_CARD_SEV_BASE, e la ricerca lo azzera da sola ogni volta che lo si
# lascia libero.
RED_CARD_BASE = 0.7        # quanto costa un'espulsione comunque
RED_CARD_SEV_BASE = 0.35   # quanto di quella baseline dipende dalla gravita'
RED_CARD_K = 0.8           # e quanto si aggiunge per il tempo giocati in dieci
RED_CARD_SEVERITY = {
    "Professional foul last man": 0.3,   # DOGSO: tactical, least culpable
    "Foul": 0.6,
    "Foul Committed": 0.6,
    "Violent conduct": 1.0,
    "Bad Behaviour": 1.0,
    "Argument": 1.0,
}
RED_CARD_SEVERITY_DEFAULT = 0.6

# --- Own-goal performance adjustment -----------------------------------------
# An own goal is a negative performance event a real pagella reflects in the vote.
# We grade it by fault ONLY when we have the precision to do so reliably: with
# sub-minute timing (MatchShot.elapsed_seconds), an own goal that shares the moment
# of an opponent shot (within OWN_GOAL_DEFLECTION_WINDOW_S) deflected it in —
# unlucky, light penalty; otherwise it is a solo error — heavier. WITHOUT seconds
# (rows imported before we captured them) a minute is too coarse to tell a deflection
# from a coincidental shot, so we fall back to a single FLAT penalty rather than
# claim a gravity we cannot measure. The flat -2 fantacalcio malus applies ON TOP in
# the bonus layer regardless. Re-scrape to backfill elapsed_seconds and unlock grading.
#
# HALVED TWICE on 2026-07-30: the drop had grown to weigh more than a SCORED GOAL,
# which no reading of the game supports. In the base vote a goal is worth +0.69, and
# a solo own goal was costing -1.50 — and the -2 fantacalcio malus lands on top of
# that, so an own goal was a 3.5-point event against a goal's 3.7.
# Measured on the 22 own goals of 2025-26 (12 solo, 10 deflections, none ungraded):
# at -1.50/-0.75 our vote on those appearances averaged 4.57 against the pagelle's
# 5.30, a differential of -0.75 relative to our own average bias; at -0.50/-0.20 it
# is 5.36 against 5.30, differential +0.04, and both the MAE (0.3375 -> 0.3367) and
# the agreement (r 0.6690 -> 0.6696) are at their best over the range.
# The penalty is NOT dropped to zero, and that was measured too: with no adjustment
# at all we land at 5.73 against their 5.30 (+0.41), so the pagelle do read the own
# goal in the base vote — about 0.7 below their own average — they simply do not
# read it as the catastrophe we did.
# In punti di VOTO (v. RED_CARD_BASE). La taratura del 30/07/2026 qui sotto resta
# valida — sono gli stessi numeri, riportati sulla scala su cui erano stati misurati:
# lo stadio finale della scala (ROLE_SATURATION, 04/09/2026) li aveva portati a
# -0.78/-0.31 senza che nessuno li toccasse, e su quella scala lo scostamento contro
# lo Statistico era tornato a -0,341 (-0,597 sui soli autogol in solitaria). Il
# rapporto 2,5:1 fra errore in solitaria e deviazione e' conservato esattamente.
# Misurato sui 22 autogol della 25-26: fuori di un punto 5 -> 2, scostamento -0,341
# -> -0,136.
OWN_GOAL_VOTE_DEFLECTION = -0.16
OWN_GOAL_VOTE_SOLO = -0.40
OWN_GOAL_VOTE_FLAT = -0.24         # when sub-minute timing is unavailable
OWN_GOAL_DEFLECTION_WINDOW_S = 3   # seconds between the OG and the shot it deflected;
# kept tight (deflections sit at Δ1-2s, solo errors at Δ40s+) so a hectic sequence
# with an unrelated close-by shot is not mistaken for a deflection.
# A missed penalty (shot situation='penalty', not scored). The -3 fantavoto malus
# lives in the bonus layer (classic_pagella); THIS is the added voto-puro drop, kept
# small because the voto puro already reads the penalty as a good on-target shot via
# the SGA and we deliberately keep that (the strike itself was well hit). Scaled by
# whether converting it would have changed the result — see penalty_missed_adjustments.
# In punti di VOTO, come le altre correzioni post-indice (v. RED_CARD_BASE): erano
# -1.0/-0.5 PRIMA della saturazione, che sul movimento le portava a -1.65/-0.83 —
# contro il -1.07/-0.77 del giudice. Il rapporto 2:1 fra i due casi non era il
# problema e resta quasi intatto (1,86:1); era il livello. Misurato sui 24 rigori
# sbagliati della 25-26: fuori di un punto 6 -> 2, scostamento -0,229 -> 0,000.
PENALTY_MISSED_VOTE_RELEVANT = -1.3    # +1 goal would have flipped the final result
PENALTY_MISSED_VOTE_IRRELEVANT = -0.7  # result already decided
# Bayesian shrinkage strength: a per-90 rate from few minutes is noisy and fat-tailed
# low-count features (xG, key passes) explode when extrapolated to 90'. The evidence
# weight minutes/(minutes+this) pulls short cameos toward the role prior (vote 6); a
# full game keeps almost all its signal. Higher value = more distrust of short games.
# (Was briefly lowered to 18 alongside the kurtosis nudge to keep spread up; reverted
# to the well-reasoned 25 when that nudge was undone — 18 also inflated full-game
# bases like Koopmeiners' by trusting the sample slightly more than warranted.)
SHRINKAGE_MINUTES = 25
# Il MOVIMENTO ne vuole molti di piu'. Il 25 sopra resta il valore del PORTIERE, che
# e' dove era stato ragionato; per DIF/CEN/ATT la taratura del 03/09/2026 lo porta a
# 90, cioe' "una presenza vale per intero solo a partita intera". Sono due canali con
# due popolazioni diverse: il portiere gioca 90' quasi sempre e lo spezzone e' raro,
# il movimento e' pieno di mezz'ore che non vanno lette come tassi per-90.
OUTFIELD_SHRINKAGE_MINUTES = 90.0


def shrinkage_for(ref_key: str) -> float:
    """I minuti di sfiducia di QUESTO canale (v. SHRINKAGE_MINUTES)."""
    return (float(SHRINKAGE_MINUTES) if ref_key == Player.ROLE_GK
            else OUTFIELD_SHRINKAGE_MINUTES)
# Extrapolation floor: never project a per-90 rate from FEWER than this many minutes
# as if the player had played 90'. A 26' cameo that created one big chance must not be
# read as a 3.5x/90 rate — we cap the projection at this minute baseline. This tackles
# the fat-tailed-cameo problem at its source (the per-90 blow-up), before shrinkage.
EXTRAP_FLOOR_MINUTES = 55

# --- Exposure: danger conceded where AND while a player was on the pitch ------
# An outfielder's index is otherwise built from clearances, interceptions, blocks
# and duels — the VOLUME of defending. Under siege those all rise while the team
# concedes, so the two signals cancel and the vote ends up blind to the outcome.
#
# The fix is deliberately NOT "the team conceded, so the back four all drop". That
# is collective punishment, and it is demonstrably what the external sources do:
# among defenders with no recorded individual error at all, their vote still falls
# from 6.28 to 5.12 as the team goes from 0 to 4 conceded. Instead each conceded
# shot is charged to the players who were IN ITS ZONE, and only to them.
#
# Three decisions, each measured against the external base votes over a full
# season (agreement of the DEFENDER vote with fantacalcio's Statistico):
#
# * WHAT is charged. The first version charged raw xG, which barely moved the
#   vote (r 0.510 without the term, 0.506 with it): a defensive error that yields
#   a low-xG goal is invisible, and most conceded xG never becomes anything. What
#   works is the OUTCOME — but charging goals alone erases every error the keeper
#   bailed out, and 44% of the xGOT conceded in a season dies in a save. So the
#   charge splits a FIXED budget between the two (EXPOSURE_LAMBDA):
#       amount = λ·outcome + (1−λ)·xGOT
#   λ=0.5 is a true half-and-half because xGOT is calibrated on goals (940 vs 922
#   over 25-26), so the two halves carry the same total mass and no goal is
#   counted twice. A saved shot is charged its own xGOT: 8% of an average goal at
#   the median, 31% at the 90th percentile, 51% at the 99th — the weak shot costs
#   nothing, the sitter the keeper had to fly for costs half a goal. Woodwork gets
#   no xGOT from the provider, so it is charged on the OUTCOME side at the rate
#   our own attacking weights already assign it (shots_post / shots_goal).
#   This also composes cleanly with the keeper channel, which scores him on
#   xGOT-faced MINUS goals: the defence answers for the danger allowed, the keeper
#   for the part he failed to stop, and the two sum to the goals conceded.
#
# * TO WHOM. Presence is the player's heatmap share of the zone (see
#   ``_zone_presence``), but taken RELATIVE to his team-mates on the pitch at that
#   minute rather than absolute. Absolute presence answers "what fraction of MY
#   match did I spend there", which dilutes exactly the ball-playing defender we
#   want to charge — Bastoni had 2.4% of his heatmap in the zone all of Verona's
#   shots came from — and hands the danger to whoever lives in the box, i.e. the
#   keeper. The relative share instead sums to 1 over the outfielders on the pitch,
#   so every shot is distributed in full and no more than in full. The keeper is
#   excluded from the split: his own channel already answers for the save.
#   EXPOSURE_KERNEL blurs the presence into the adjacent zones, so a shot landing
#   just across a grid boundary is not charged to the wrong man.
#
# * TO WHICH ROLES. Every outfield role, attackers included. They are the ones who
#   lost the ball or failed to track back, and exempting them was an asymmetry with
#   no argument behind it: they were computing a share and not paying it.
#
# Result: the defender vote goes from r 0.517 to 0.621 against the Statistico
# (MAE 0.448 -> 0.406), and its correlation with goals conceded while on the pitch
# from -0.23 to -0.53 — against -0.578 for the Statistico itself. It stays a
# reading of the individual, not of the scoreline: 43% of the term's variance
# still separates defenders of the SAME back line (a purely collective measure
# has 4%).
#
# EXPOSURE_WEIGHT is the knee of the curve AND the last value that stays under the
# external sources' own dependence on the scoreline; past it both criteria break
# together (at 1.5 the correlation with goals conceded overshoots the Statistico's,
# at 2.0 the term is 70% of the defender index and no defender can earn above 8.5).
# Applied LINEARLY, unlike the √-compressed volume block: it is already a small
# goal-equivalent figure, not a fat-tailed count.
EXPOSURE_WEIGHT = 0.1314    # same unit as every other weight: index points per 1σ
EXPOSURE_KEY = "_exposure"  # its name in the scales/breakdowns (it is not a provider stat)
EXPOSURE_LAMBDA = 0.50      # share of the charge carried by the OUTCOME; 1−λ by xGOT
EXPOSURE_KERNEL = 0.30      # weight of the four adjacent zones in the presence
# A woodwork strike carries no provider xGOT, so it is charged on the outcome side
# at the value our OWN attacking weights give it relative to a goal — the same
# event, read the same way from both ends of the pitch.
EXPOSURE_POST_OUTCOME = SGA_POST_WOODWORK
_NEIGHBOURS = ((-1, 0), (1, 0), (0, -1), (0, 1))

# How much CREDIT a player earns for danger that never arrived. 1.0 = the charge is
# symmetric (below-average exposure earns as much as above-average exposure costs);
# 0.0 = the danger conceded is charged in full and its absence earns nothing.
#
# Why it is not symmetric. The exposure is a TEAM quantity divided among the players
# on the pitch, so a low value says two things at once — he defended his zone, and
# the opponent never came. Measured on 2025-26, within a role the second dominates:
# 53.7% of the variance of a defender's exposure is which team-match he was in
# (59.2% for a midfielder, 76.0% for a forward), and a team's conceded danger
# correlates 0.63 with the opponent's xG. The case that prompted this: Juventus 4-0
# Pisa, where the whole Juventus side conceded 0.087 of danger against a league
# average of 1.062 per team-match — every one of the eleven collected the credit, and
# none of them had earned it individually.
#
# The obvious repair is the wrong one: subtracting the team average (making exposure
# purely relative to team-mates) moves us away from ALL THREE external judges at once
# and monotonically — MAE 0.340 -> 0.353, Redazione r 0.673 -> 0.647, defenders
# 0.654 -> 0.613 at full removal — because the pagelle grade the collective too. A
# defence that concedes nothing IS a merit in their eyes; the context is not noise to
# them.
#
# The asymmetry is what works, and it is the honest statement of the asymmetry in the
# evidence: danger that came through your zone is about you, danger that never came
# may be about the opponent. At 0.0 the MAE improves (0.3400 -> 0.3378), agreement
# with the SofaScore rating gains 0.013 (0.7676 -> 0.7804, the largest single gain of
# the reweighting session — that rating is event-based and does not credit events that
# did not happen either), the Redazione is flat (-0.0006), and the vote's tie to the
# scoreline loosens (defender vote vs goals conceded -0.562 -> -0.522, further from
# the -0.578 of the external references). It costs 0.005 of defender agreement with
# the Redazione, which is precisely the collective clean-sheet credit being dropped.
#
# NOTE what it does NOT do: it does not zero the term for a clean match. Compressing
# the lower half onto the mean RAISES the population mean of the feature (0.948 ->
# 1.351 in σ units), so sitting at the mean still beats the average slightly: every
# clean appearance gets the SAME +0.10 of a vote instead of up to +0.22. What goes to
# zero is the spread WITHIN the clean group — the model stops distinguishing clean
# from spotless, which is the point. It also softens the charge itself by ~17% for the
# same reason (a shot-heavy match: -0.47 -> -0.39 of a vote); restoring the charge
# exactly would need EXPOSURE_WEIGHT ~0.198, which was measured and is slightly worse
# on every judge (MAE 0.3398, sofa 0.7723), so the softer charge is kept.
EXPOSURE_CREDIT = 0.0

# --- Il credito per l'assenza -------------------------------------------------
# Lo stesso meccanismo dell'esposizione, applicato ai conteggi negativi del blocco
# volume: la metà SOTTO la media è schiacciata sulla media invece di pagare.
#
# Perché. Una feature a peso negativo che vale zero PAGA, perché il giocatore medio
# ne porta il malus: chi non ha perso un duello incassa il malus medio che non ha
# subito. Su ``duels_lost`` quel premio vale 0.18 di voto — più di quanto valga
# vincerne quattro — e lo incassa chi al duello non è mai andato. È il difetto che
# la riduzione ×0.8 del blocco volume aveva individuato ma non poteva curare
# ("un terzo del vantaggio veniva da cose che NON aveva fatto"): nessuna
# trasformazione per-feature lo tocca, perché non è una coda, è il livello.
#
# Quanto valeva, in punti di voto, il credito di chi ha zero (|w|·mu_z·K/σ):
#   duels_lost 0.182 · errors_bad_passes 0.063 · errors_miscontrols 0.026
#   errors_dispossessed 0.019 · aerials_lost 0.029 · dribbled_past 0.023
#   errors_fouls_committed 0.019
#
# Costo misurato sulla 25-26 (n=6829, giornata per giornata): Redazione
# -0.003, SofaScore -0.006, difensori sulla Redazione -0.011. Si paga: quel
# credito è in parte la porta inviolata collettiva, che le pagelle premiano
# davvero (stessa ragione per cui l'esposizione non si rende relativa alla
# squadra). Si paga volentieri perché il caso che lo apre è un'inversione:
# Yıldız 2 duelli su 2 e 0 persi finiva SOPRA Conceição, 5 su 16 con 4 dribbling
# riusciti, e quel sorpasso era tutto credito per l'assenza (-0.145 contro
# +0.028 quando lo si toglie — il differenziale più grande di ogni leva provata).
#
# Che cosa NON è in questo insieme, e perché:
# * ``dribbles_attempted``: non è un evento negativo, è il denominatore di un
#   tasso (v. la nota sul suo peso). Creditarlo o no interagisce con
#   ``dribbles_won``, che qui non si tocca. Misurato: pareggio (Redazione +0.0004,
#   SofaScore -0.0022).
# * ``errors_led_to_goal``, ``penalties_conceded``, ``errors_led_to_shot``: eventi
#   rari, mu_z ~0.1, il credito vale 0.006 di voto a testa. Toglierlo sarebbe
#   coerente e impercettibile; resta fuori perché non è stato misurato a parte.
# * il canale del portiere: la frase che stava qui — «nessuna delle sue voci
#   negative è un conteggio di volume» — era vera e guardava un lato solo. V. sotto.
#
# IL PORTIERE C'È DAL 30/08/2026. Il suo caso è SPECULARE a quelli qui sopra: non
# sono le voci a peso negativo che valgono zero a regalare un credito, sono quelle a
# peso POSITIVO che, valendo zero, PUNISCONO chi non è stato tirato. Stessa cura,
# stesso ``_asymmetric_z``, verso opposto.
#
# Il difetto, misurato a evidenza piena sui sei portieri della 25-26 che hanno
# affrontato UN tiro solo e l'hanno parato (xGOT >= 0.35):
#
#   gol evitati  +0.20 / +0.34      tutto il resto  -0.13 / -0.28
#
# e la voce più pesante del «resto» è gk_saves_inside_box a -0.186: diciannove
# centesimi tolti per le parate ravvicinate che nessuno l'ha costretto a fare.
#
# COSA COMPRA (765 presenze POR della 25-26, contro la Redazione, al centro 6.15):
# * la fascia «poco lavoro ma una parata vera» (<=2 tiri, imbattuto, almeno una da
#   0.40 di xGOT, n=18): da 6.36 a 6.39 contro il loro 6.39, e 18 casi su 18 entro
#   mezzo punto — il risultato migliore di ogni variante provata;
# * la riga assurda sparisce dal pannello: a chi non è stato tirato la spiegazione
#   non scrive più «nessuna parata su tiri ravvicinati -0.19».
#
# COSA COSTA, e non è gratis: il portiere bombardato e battuto (>=4 tiri, >=2 gol,
# n=228) passa da -0.090 a -0.178. Viene dalla RICALIBRAZIONE, non dal freno:
# schiacciando il fondo la media dell'indice sale (1.304 -> 1.737) e chi sta sotto
# scivola. Nessun centro lo assorbe, perché è uno spostamento relativo dentro la
# popolazione mentre un offset muove tutti insieme. Sul totale: |scarto| 0.308 ->
# 0.313, entro mezzo punto 89.7% -> 89.3%.
#
# QUELLO CHE NON COMPRA: i sei casi a un tiro solo restano 6.0 (arrivano a
# 6.19-6.25, e la soglia è 6.25) — lì il freno sull'evidenza si riprende i tre
# quarti del credito. Toglierlo li porterebbe tutti a 6.5, azzeccandone 4 su 6
# invece di 2, al prezzo di 1.1 punti di accordo su tutta la popolazione: misurato
# (88.2%) e SCARTATO il 30/08/2026.
#
# Fuori restano, deliberatamente: ``gk_goals_prevented``, che è la misura del MERITO
# e deve poter punire in pieno chi incassa un tiro parabile; e
# ``gk_crosses_not_claimed``, a peso negativo, dove il credito è misurato identico a
# non metterlo (0.341 in entrambi i casi) e non è il difetto in questione.
ABSENCE_CREDIT = 0.0
CREDITED_FEATURES = frozenset({
    "duels_lost", "aerials_lost", "dribbled_past", "errors_dispossessed",
    "errors_miscontrols", "errors_bad_passes", "errors_fouls_committed",
    # Il canale del portiere: conteggi di volume a peso POSITIVO (v. sopra).
    "gk_saves", "gk_saves_inside_box", "gk_high_claims", "gk_punches",
    "gk_sweeper",
})

# 'A voto' vs 'senza voto' (s.v.): classic fantacalcio rates a player only if he
# played enough AND was involved enough; below that he gets NO vote (a bench player
# replaces him), not a 6. Involvement is proxied by ball touches. Both tunable.
# NB: this is only the MINUTES/INVOLVEMENT gate. A player involved in a decisive
# event (goal, assist, own goal, penalty, sending-off on the pitch — but NOT a
# plain booking, see ``_SENDING_OFF_TYPES``) is
# rated regardless — that override lives in ``voto_puro_for_match`` via
# ``rating_forcing_event_players``, because those events are not in the zone totals.
# La casella del portiere nella distinta SofaScore (v. ``match_lineup_keepers``).
SOFA_GK_POSITION = "G"

# Decimali a cui si arrotondano le somme che arrivano dal database.
#
# Perché serve: quasi tutti i contatori del provider sono INTERI (tocchi, duelli,
# passaggi) e quelli continui hanno sei decimali (xG, xA). Ma li sommiamo in SQL su
# colonne float, e la somma in virgola mobile dipende dall'ORDINE degli addendi:
# PostgreSQL restituisce 9.999999999999998 dove SQLite dà 10.0. Confrontando i voti
# della 2025-26 fra portatile e produzione, con dati bit-identici, quel rumore ha
# prodotto quattro «senza voto» diversi — un giocatore con esattamente 6 tocchi che
# in produzione ne aveva 5.999999999999999, sotto la soglia MIN_TOUCHES_RATED — e
# uno scarto di ruolo su un giocatore di confine, perché anche la matrice del
# clustering nasce da queste somme.
#
# Sei decimali tengono tutta la precisione che il provider dichiara e buttano solo
# la coda che nessuno dei due database sa riprodurre.
PROVIDER_SUM_DECIMALS = 6


def _round_sum(value):
    """Una somma del database, ripulita dal rumore dell'ordine degli addendi."""
    return value if value is None else round(float(value), PROVIDER_SUM_DECIMALS)

MIN_MINUTES_RATED = 14
MIN_TOUCHES_RATED = 6
# Above this many minutes, minutes ALONE decide: the touch count is a proxy for
# "was he involved enough to judge", and that question only makes sense for a
# cameo. Anyone who is on the pitch this long has been judged by every pagella
# that exists, however little he saw of the ball — he gets a LOW vote, not no
# vote. Without this, 119 appearances a season (four of them full 90') were
# declared unrated purely on a touch count.
ALWAYS_RATED_MINUTES = 16
# Set 2026-07-29 from the only evidence that can settle it: WHO fantacalcio leaves
# without a vote, over the 11.819 appearances of 2025-26 we can match to their
# sheet. Read as a rule, their s.v. rate by minutes played is
#     1-10'  93-98%   10-12'  87%   12-15'  55%   15-18'  13%   18-20'  2%   20'+  0%
# i.e. the cut sits at about a quarter of an hour and the tail is short. Ours sat at
# 12'/12 touches with the minutes override at 20', which said s.v. for 53% of the
# 15-18' band and 45% of the 18-20' one against their 13% and 2% — 348 appearances a
# season silenced that they graded, nearly all substitutes (166 attackers, 109
# midfielders).
# 14 / 6 / 16 raises the agreement on WHO gets a vote from 96.2% to 98.0% (F1 on the
# s.v. class 81.6% -> 89.3%) with the two error directions balanced (143 s.v. only
# ours, 95 only theirs). It also improves the VOTES, which is the check that
# mattered: the 231 appearances that stop being silent get our 5.77 against their
# 5.86, MAE 0.214 — better than our season average of 0.34 — so the overall vote MAE
# ticks down to 0.342 on 205 more comparisons. We were withholding the easy ones.
# The touch gate survives, narrowed to the 14-16' window: a player who comes on for a
# quarter of an hour and touches the ball five times has genuinely not been seen.

# Reference bucket for a player we could rate but whose ROLE we don't know (his
# Player row has no classic_role_seed because the squad import never matched him).
# See ``resolve_role``: s.v. is a statement about the PLAYER'S MATCH, so a hole in
# our master data must never be dressed up as one.
POOLED_OUTFIELD = "_OUTFIELD"


def resolve_role(classic_role_seed: str, totals: dict, is_goalkeeper: bool) -> tuple[str, bool]:
    """(role, role_is_known) for scoring purposes.

    Returns the declared classic_role_seed when we have one. When we don't, we do NOT
    give up: a keeper is identifiable from his own match data (only keepers
    produce ``gk_*`` features), and any other player can still be scored on the
    outfield index against the pooled outfield reference. The second element says
    whether the role is declared, so callers can flag an estimate as such instead
    of presenting it as fact.
    """
    if classic_role_seed:
        return classic_role_seed, True
    if is_goalkeeper or any(k.startswith("gk_") for k in totals):
        return Player.ROLE_GK, False
    return "", False


def current_role_map(*, only_declared: bool = False) -> dict:
    """pid -> classic role. THE canonical role source for scoring the voto puro.

    Any code that computes the voto puro / its reference MUST get roles from here,
    never from ``Player.classic_role_seed`` directly. That raw field is only
    Transfermarkt's provider seed, under which every winger is a midfielder by
    convention — reading it for scoring pools wide attackers (Leão, Berardi,
    Neres...) into the CEN reference and z-scores them against the wrong peers.
    This helper instead returns the DISAMBIGUATED current role from the k-means
    style inference (``CurrentPlayerRole.role_mitigated``, written by ``manage.py
    compute_classic_roles``), so Leão is scored as the 'punta d'area' he plays as.
    It falls back to the raw seed only for players the inference never covered.

    Role hierarchy across the app (do not confuse the layers):
      * ``Player.classic_role_seed`` – raw TM seed; SEEDS the rest, never scores.
      * ``CurrentPlayerRole``        – TM + k-means disambiguation, one row per
                                       player, recomputed on a fresh scrape; THIS,
                                       for scoring. No season dimension.
      * ``LeaguePlayerRole``         – a league's frozen snapshot; authority INSIDE
                                       a league (overrides this for that league's
                                       pagella display / lineup legality).

    NB: calibrate a season's reference while the current roles still reflect that
    season's play (i.e. at season end), since there is no per-season role history.

    With ``only_declared`` empty roles are dropped, which is what the reference-
    population builders want (a role has to be known to bucket a sample).
    """
    from vfoot.models import CurrentPlayerRole
    roles = dict(Player.objects.values_list("id", "classic_role_seed"))
    for pid, role in (CurrentPlayerRole.objects
                      .values_list("player_id", "role_mitigated")):
        if role:
            roles[pid] = role
    if only_declared:
        return {pid: r for pid, r in roles.items() if r}
    return roles


def is_rated(minutes: int, totals: dict) -> bool:
    """Minutes/involvement gate for 'a voto' vs senza voto. NOT the whole story:
    a player involved in a decisive event is rated even below this — see
    ``rating_forcing_event_players`` and how ``voto_puro_for_match`` combines them."""
    if minutes >= ALWAYS_RATED_MINUTES:
        return True
    return (minutes >= MIN_MINUTES_RATED
            and totals.get("touches", 0.0) >= MIN_TOUCHES_RATED)


# A SENDING-OFF forces a rating; a plain booking does NOT. Measured, not assumed:
# among the 2025-26 appearances below our minutes/touches gate, fantacalcio rates
# 29/29 scorers, 26/26 assist-men, 5/5 sent-off players and 2/2 penalty takers — but
# only 7 of the 39 whose sole event was a yellow card (17.9%). The convention makes
# sense from their side: an s.v. player is replaced by a bench player, so his booking
# never scores, and rating a ten-minute cameo BECAUSE he was booked invents a
# performance reading in order to attach a -0.5 the pagella declined to attach.
# Dropping the plain yellow moved agreement on who gets a vote from 97.99% to 98.19%
# (31 disagreements resolved, 7 created) and left the Statistico untouched.
_SENDING_OFF_TYPES = (CARD_SECOND_YELLOW, CARD_RED)


def rating_forcing_event_players(match_id: int) -> set:
    """player_ids whose match carried a decisive event that forces a rating no
    matter how few minutes/touches they had — fantacalcio never leaves such a player
    'senza voto', and that claim is now measured rather than assumed (see
    ``_SENDING_OFF_TYPES``). Covers a goal, assist or own goal, and a SENDING-OFF
    taken ON THE PITCH (the card's minute falls inside the player's on-pitch window,
    which drops the post-match/bench card anomalies at minute -5). A plain booking
    does NOT force a rating: on that one the pagelle disagree with us, 39 cases to 7.
    Penalties won/conceded are handled by the caller from the zone totals it already
    holds. Own goals live in ``MatchAppearance.raw_stats``."""
    apps = list(MatchAppearance.objects.filter(match_id=match_id)
                .values("player_id", "side", "is_starter", "goals", "assists",
                        "minutes_played", "raw_stats"))
    if not apps:
        return set()
    forcing = set()
    for a in apps:
        rs = a.get("raw_stats") or {}
        if a["goals"] or a["assists"] or (rs.get("ownGoals") or 0) > 0:
            forcing.add(a["player_id"])

    minutes = {(match_id, a["player_id"]): a["minutes_played"] for a in apps}
    appearances = {(match_id, a["player_id"]): (a["side"], a["is_starter"])
                   for a in apps}
    windows = on_pitch_windows([match_id], minutes, appearances)
    for pid, minute in (MatchDisciplinaryEvent.objects
                        .filter(match_id=match_id, card_type__in=_SENDING_OFF_TYPES)
                        .values_list("player_id", "minute")):
        lo, hi = windows.get((match_id, pid), (0.0, 0.0))
        if minute is not None and lo <= minute <= hi:
            forcing.add(pid)
    return forcing


def red_card_details(match_id: int) -> dict:
    """{player_id: {reason, minute, man_down, severity, base, penalty}} for a
    sending-off taken ON THE PITCH.

    The ingredients, not just the number: a vote dropped by 1.2 for a sending-off
    needs to be able to say WHICH sending-off and why that much (see RED_CARD_* and
    ``red_card_penalty``). Gated on the pitch — a post-match/bench card (minute < 0,
    or a minute outside the player's on-pitch window) had no in-game impact and is
    skipped, which drops the minute -5 anomalies."""
    events = list(MatchDisciplinaryEvent.objects
                  .filter(match_id=match_id,
                          card_type__in=(CARD_RED, CARD_SECOND_YELLOW))
                  .values_list("player_id", "minute", "reason", "card_type"))
    if not events:
        return {}
    apps = list(MatchAppearance.objects.filter(match_id=match_id)
                .values("player_id", "side", "is_starter", "minutes_played"))
    minutes = {(match_id, a["player_id"]): a["minutes_played"] for a in apps}
    appearances = {(match_id, a["player_id"]): (a["side"], a["is_starter"])
                   for a in apps}
    windows = on_pitch_windows([match_id], minutes, appearances)
    match_end = max((hi for _lo, hi in windows.values()), default=95.0)
    out = {}
    for pid, minute, reason, card_type in events:
        lo, hi = windows.get((match_id, pid), (0.0, 0.0))
        if minute is None or minute < 0 or not (lo <= minute <= hi):
            continue
        out[pid] = {
            "reason": reason or "",
            "second_yellow": card_type == CARD_SECOND_YELLOW,
            "minute": minute,
            "man_down": max(0.0, match_end - minute),
            "severity": RED_CARD_SEVERITY.get(reason, RED_CARD_SEVERITY_DEFAULT),
            "base": (RED_CARD_BASE + RED_CARD_SEV_BASE
                     * RED_CARD_SEVERITY.get(reason, RED_CARD_SEVERITY_DEFAULT)),
            "penalty": red_card_penalty(reason, minute, match_end),
        }
    return out


def red_card_adjustments(match_id: int) -> dict:
    """{player_id: voto-puro adjustment (<= 0) for a sending-off taken on the pitch}.

    A baseline every sending-off costs, graded by how justifiable the reason was,
    plus severity times how long it left the team a man down (see RED_CARD_*). This is separate from and additive to the flat fantacalcio red
    malus applied in the bonus layer. The reasoning behind each number is in
    ``red_card_details``, which this delegates to so the two cannot diverge."""
    return {pid: -d["penalty"] for pid, d in red_card_details(match_id).items()}


def own_goal_details(match_id: int) -> dict:
    """{player_id: {kind, count, penalty}} for own goals, graded by fault.

    ``kind`` is what the grading concluded — ``deflection`` (he turned in an
    opponent's shot: unlucky), ``solo`` (no opponent shot at that moment: his own
    error), ``ungraded`` (no sub-minute timing, so we decline to claim a gravity we
    cannot measure). The vote drop differs by a factor of 2.5 between the first two,
    so an explanation that only said "autogol" would be hiding the reason for most of
    the number it reports."""
    sides = appearance_sides([match_id])
    shots = list(MatchShot.objects.filter(match_id=match_id)
                 .values_list("player_id", "team_side", "is_goal", "shot_type",
                              "elapsed_seconds"))
    own_goals = [(pid, sec) for pid, ts, isg, st, sec in shots
                 if is_own_goal(st, ts, sides.get((match_id, pid)))]
    out = {}
    for pid, og_sec in own_goals:
        if og_sec is None:
            kind, pen = "ungraded", OWN_GOAL_VOTE_FLAT
        else:
            opp = "away" if sides.get((match_id, pid)) == "home" else "home"
            deflection = any(ts == opp and sp != pid and sec is not None
                             and abs(sec - og_sec) <= OWN_GOAL_DEFLECTION_WINDOW_S
                             for sp, ts, _isg, _st, sec in shots)
            kind = "deflection" if deflection else "solo"
            pen = (OWN_GOAL_VOTE_DEFLECTION if deflection else OWN_GOAL_VOTE_SOLO)
        prev = out.get(pid)
        out[pid] = {"kind": kind if prev is None else prev["kind"],
                    "count": (prev["count"] + 1) if prev else 1,
                    "penalty": (prev["penalty"] if prev else 0.0) + pen}
    return out


def own_goal_adjustments(match_id: int) -> dict:
    """{player_id: voto-puro penalty for an own goal}, graded by fault when possible.

    An own goal is a 'goal' shot tagged with the OPPONENT's side (the side it counts
    for), so a goal-shot whose team_side differs from the scorer's own side is an own
    goal. Gravity, ONLY with sub-minute timing (elapsed_seconds): an opponent shot
    within OWN_GOAL_DEFLECTION_WINDOW_S seconds is the shot it deflected in — unlucky
    (OWN_GOAL_VOTE_DEFLECTION); none near reads as a solo error (OWN_GOAL_VOTE_SOLO).
    WITHOUT seconds, a minute is too coarse to tell them apart, so a single FLAT
    penalty (OWN_GOAL_VOTE_FLAT) applies. Additive to the -2 fantacalcio malus.

    Delegates to ``own_goal_details`` so the number and the reason given for it can
    never disagree."""
    return {pid: d["penalty"] for pid, d in own_goal_details(match_id).items()}


def penalty_missed_adjustments(match_id: int) -> dict:
    """{player_id: voto-puro drop for a missed penalty}, scaled by result relevance.

    A missed penalty is a shot with ``situation='penalty'`` that is not a goal (saved,
    off target, woodwork). Magnitude: RELEVANT (-1) if converting it would have flipped
    the final result — the taker's team drew (gd 0 → win) or lost by one (gd -1 → draw);
    IRRELEVANT (-0.5) if the result was already decided. Additive to the -3 fantacalcio
    malus in the bonus layer, and ON TOP of the SGA (the strike stays a good on-target
    shot in the index — we only add this performance drop for the miss itself)."""
    m = (Match.objects.filter(id=match_id)
         .values("home_goals", "away_goals").first())
    if not m:
        return {}
    hg, ag = int(m["home_goals"] or 0), int(m["away_goals"] or 0)
    out: dict = {}
    for pid, side in (MatchShot.objects
                      .filter(match_id=match_id, situation="penalty", is_goal=False)
                      .exclude(player__isnull=True)
                      .values_list("player_id", "team_side")):
        gd = (hg - ag) if side == "home" else (ag - hg)
        relevant = gd in (0, -1)
        out[pid] = out.get(pid, 0.0) + (PENALTY_MISSED_VOTE_RELEVANT if relevant
                                        else PENALTY_MISSED_VOTE_IRRELEVANT)
    return out


def red_card_penalty(reason: str, minute: float, match_end: float) -> float:
    """Positive magnitude of a sending-off's voto-puro drop, IN VOTE POINTS: a
    baseline every sending-off costs (itself graded by how justifiable the reason
    was) plus severity times the man-down fraction (match_end - minute)/90. Pure —
    the on-pitch gating and sign live in ``red_card_adjustments``, and the division
    by the final-stage factor in ``voto_puro_for_match`` (see RED_CARD_BASE)."""
    minutes_down = max(0.0, match_end - minute)
    sev = RED_CARD_SEVERITY.get(reason, RED_CARD_SEVERITY_DEFAULT)
    return (RED_CARD_BASE + RED_CARD_SEV_BASE * sev
            + RED_CARD_K * sev * (minutes_down / 90.0))


def _compress(u: float) -> float:
    """Odd, unit-slope-at-zero, log-tailed compression (see COMPRESS_K).

    ``u`` is already in units of the feature's own standard deviation, so the same
    constant means the same thing for every feature. f(0)=0, f'(0)=1 — a small value
    passes through essentially untouched, which is exactly what the √ it replaces
    got wrong."""
    if u == 0:
        return 0.0
    return math.copysign(COMPRESS_K * math.log1p(abs(u) / COMPRESS_K), u)


def raw_feature_values(totals: dict, minutes: int, exposure: float = 0.0,
                       *, gk: bool = False) -> dict:
    """{feature: value} in the units the weights are calibrated against.

    One place decides what a feature's value IS — per-90 scaling for the volume
    block, derived features folded in, exposure included as a feature so it is
    standardised like everything else. Everything downstream (the index, the
    explanation, the tuner, the calibration) reads from here, so they cannot drift
    apart."""
    if minutes <= 0:
        return {}
    total_w = GK_TOTAL_WEIGHTS if gk else TOTAL_WEIGHTS
    per90_w = GK_PER90_WEIGHTS if gk else PER90_WEIGHTS
    scale = 90.0 / max(minutes, EXTRAP_FLOOR_MINUTES)
    derived = {} if gk else derived_features(totals)
    out = {k: derived.get(k, totals.get(k, 0.0)) for k in total_w}
    out.update({k: totals.get(k, 0.0) * scale for k in per90_w})
    if not gk:
        out[EXPOSURE_KEY] = exposure
    return out


def _feature_z(key: str, value: float, scales: dict) -> float:
    """Standardise -> compress -> standardise again.

    The first division puts every feature on a common σ scale (so COMPRESS_K means
    the same distance from the mean everywhere, and so a WEIGHT means the same
    thing everywhere); the compression shortens the tail; the second division
    restores unit spread, which is what makes a weight literally "the contribution
    of one sigma". Both σ come from the frozen calibration, never from the match
    being scored."""
    s = scales.get(key)
    if not s or not s.get("sigma_raw") or not s.get("sigma_z"):
        return 0.0
    return _compression_of(key)(value / s["sigma_raw"]) / s["sigma_z"]


def _asymmetric_z(key: str, value: float, scales: dict, credit: float) -> float:
    """The z with its BELOW-average half squeezed onto the average by ``credit``.

    1.0 leaves it symmetric, 0.0 makes every below-average value score exactly as
    the average does. ``mu_z`` comes from the frozen calibration, never from the
    match being scored: what "average" means is a property of the population."""
    z = _feature_z(key, value, scales)
    mu = (scales.get(key) or {}).get("mu_z")
    if mu is None or credit >= 1.0:
        return z          # no frozen mean (fresh checkout) -> symmetric, as before
    d = z - mu
    return mu + (d if d >= 0 else credit * d)


def exposure_z(value: float, scales: dict) -> float:
    """The standardised exposure as the INDEX consumes it: charged in full above the
    average, credited only ``EXPOSURE_CREDIT`` of the way below it."""
    return _asymmetric_z(EXPOSURE_KEY, value, scales, EXPOSURE_CREDIT)


def scored_z(key: str, value: float, scales: dict) -> float:
    """The z of a feature AS THE INDEX CONSUMES IT — credit applied.

    Lives here, in one function, because the vote and the vote's EXPLANATION both
    have to apply the same transform: a breakdown built on the raw ``_feature_z``
    would not add up to the vote it explains."""
    if key == EXPOSURE_KEY:
        return exposure_z(value, scales)
    if key in CREDITED_FEATURES:
        return _asymmetric_z(key, value, scales, ABSENCE_CREDIT)
    return _feature_z(key, value, scales)


def index_for_role(role: str, totals: dict, minutes: int, exposure: float = 0.0,
                   scales: dict | None = None) -> float:
    """Weighted performance index for a player's match.

    Goalkeepers go through their own feature channel and weights; every outfield
    role shares one weight vector (the roles differ only in the mean/σ the index is
    z-scored against). ``exposure`` — the danger the opponent created in the zones
    this player occupied — applies to every outfield role, an attacker included,
    and to none of the keeper's, whose own channel already answers for what
    reached him.
    """
    if minutes <= 0:
        return 0.0
    gk = role == Player.ROLE_GK
    weights = weights_for_role(role)
    scales = feature_scales(gk=gk) if scales is None else scales
    values = raw_feature_values(totals, minutes, exposure, gk=gk)
    idx = sum(w * scored_z(k, values.get(k, 0.0), scales)
              for k, w in weights.items() if w)
    if not gk:
        idx -= EXPOSURE_WEIGHT * exposure_z(values.get(EXPOSURE_KEY, 0.0), scales)
    return idx


def observed_index(role: str, totals: dict, minutes: int, exposure: float = 0.0,
                   scales: dict | None = None) -> float:
    """La parte dell'indice fatta di FATTI, non di tassi (v. UNSHRUNK_FEATURES).

    Stessi pesi, stesse scale e stessa formula di ``index_for_role``, ristretta a
    quelle voci: e' un ADDENDO dell'indice, non un secondo indice, ed e' cio' che
    permette al voto di sottrarle l'attenuazione sui minuti senza ricalcolare
    niente. Zero per il portiere, che ha un canale suo.
    """
    if minutes <= 0 or role == Player.ROLE_GK:
        return 0.0
    weights = weights_for_role(role)
    scales = feature_scales(gk=False) if scales is None else scales
    values = raw_feature_values(totals, minutes, exposure, gk=False)
    return sum(w * scored_z(k, values.get(k, 0.0), scales)
               for k, w in weights.items() if w and k in UNSHRUNK_FEATURES)


def _per_match_player_totals(match_ids):
    """{(match_id, player_id): {feature_key: total_over_zones}} for sofascore.

    Fetches the union of the outfield AND goalkeeper weight keys: restricting it to
    the outfield set silently starved the GK index of every keeper feature, leaving
    it driven by inaccurate long balls alone (good sweeper-keepers ranked worst).
    """
    rows = (PlayerZoneFeature.objects
            .filter(match_id__in=match_ids, provider=PROVIDER_SOFASCORE,
                    feature_key__in=sorted((set(WEIGHTS) | set(GK_WEIGHTS)
                                            | DERIVED_INPUTS)
                                           - set(DERIVED_FEATURES)
                                           - set(MERGED_FEATURES)))
            .values("match_id", "player_id", "feature_key")
            .annotate(v=Sum("value")))
    out = defaultdict(dict)
    covered = set()
    for r in rows:
        # arrotondata: v. PROVIDER_SUM_DECIMALS — due database che sommano le stesse
        # righe in un ordine diverso non danno lo stesso float, e quel rumore arriva
        # fino alle soglie del «senza voto»
        out[(r["match_id"], r["player_id"])][r["feature_key"]] = _round_sum(r["v"])
        covered.add(r["match_id"])

    # A match with no zone row at all is NOT a match where nobody did anything:
    # it is a database that cannot answer the question. The distinction matters
    # because the two merges below read from tables a slim copy keeps
    # (``MatchShot``, ``MatchAppearance.raw_stats``) while ``export_dev_db``
    # empties the zone tables — so they would rebuild a row per appearance
    # carrying two features out of forty, and the scorer cannot tell that apart
    # from a real player who barely touched the ball. The index then lands near
    # zero, which is BELOW the frozen per-role mean (DIF 0.17, CEN 0.28, ATT
    # 0.32, POR 1.41), so every vote comes out at or under 6: a full, ordered,
    # entirely plausible listone that is uniformly wrong, with nothing to signal
    # it. Refusing to score is the promise export_dev_db already makes.
    #
    # Restricted to the matches that ARE covered rather than all-or-nothing, so
    # one failed import degrades one matchday instead of the season. On the full
    # 25-26 database the merges invent exactly 0 keys, so this changes nothing
    # where the data is there.
    uncovered = [m for m in match_ids if m not in covered]
    if uncovered:
        # A match with no APPEARANCES either has simply not been played yet, and
        # saying anything about it would make the alarm meaningless through sheer
        # noise. What has to be loud is the other case: eleven players took the
        # field and the features that describe them are gone.
        played = set(MatchAppearance.objects.filter(match_id__in=uncovered)
                     .values_list("match_id", flat=True).distinct())
        if played:
            log.error("no %s zone features for %d matches that WERE played — they "
                      "cannot be scored and are skipped rather than scored on "
                      "zeroes (a database with emptied zone tables would otherwise "
                      "produce a complete listone capped at 6). First ids: %s",
                      PROVIDER_SOFASCORE, len(played), sorted(played)[:5])
    if not covered:
        return {}
    _merge_shot_detail(out, sorted(covered))
    _drop_own_goal_shots(out, sorted(covered))
    _fill_missing_xgot(out, sorted(covered))
    _merge_defensive_value(out, sorted(covered))
    _merge_own_goal_relief(out, sorted(covered))
    _merge_keeper_moment(out, sorted(covered))
    _merge_assists(out, sorted(covered))
    return out


def appearance_sides(match_ids) -> dict:
    """{(match_id, player_id): side} — da che parte del campo stava chi ha giocato.

    Serve solo a riconoscere un autogol (v. ``is_own_goal``), ed e' una query sola
    perche' i posti che quella domanda se la pongono sono cinque."""
    return {(a["match_id"], a["player_id"]): a["side"]
            for a in MatchAppearance.objects.filter(match_id__in=match_ids)
            .values("match_id", "player_id", "side")}


def is_own_goal(shot_type: str, team_side: str, player_side: str | None) -> bool:
    """Questo tiro e' un autogol?

    UNA FUNZIONE SOLA, e non e' pedanteria: la stessa domanda si pone in CINQUE
    posti — il conteggio dei gol, il malus graduato, il credito al portiere, il
    credito d'impatto e la mappa dei tiri del pannello — piu' il conteggio dei
    TIRI, che fino al 30/08/2026 non se la poneva affatto. Ognuno se la rispondeva
    per conto proprio, ripetendo lo stesso confronto (una docstring prometteva
    perfino di identificarlo "exactly as ``_merge_shot_detail`` does", *ricopiando*
    il test): due letture su sei sbagliavano. L'autogol contava come conclusione
    tentata — un CREDITO di +0.048 di voto in media, 22 casi su 22 della 25-26 — e
    nel pannello si leggeva "gol", con un valore fabbricato fino a +0.95.

    SofaScore archivia l'autogol come un tiro 'goal' di chi l'ha segnato, ma
    taggato con la squadra PER CUI conta — l'avversaria. Il tiro il cui
    ``team_side`` non e' quello del giocatore e' quindi un autogol. Senza la sua
    presenza a referto (``player_side`` assente) non si afferma niente: meglio
    trattarlo come un tiro normale che inventare un autogol.
    """
    return (shot_type == "goal" and player_side is not None
            and player_side != team_side)


def _merge_shot_detail(out: dict, match_ids) -> None:
    """Fold the SGA_Pali shot-outcome counts (shots_post / shots_blocked / ...) into
    the per-player totals. They live in the event-level shot map, not the zone
    features, so they are counted from ``MatchShot.shot_type`` and added in place.
    Only the mapped types are counted; unmapped ones are ignored.

    OWN GOALS are dropped (v. ``is_own_goal``): they must not count as a goal for
    him — it would otherwise pollute shots_goal (used as a goals-scored proxy when
    tuning)."""
    sides = appearance_sides(match_ids)
    counts = defaultdict(lambda: defaultdict(float))
    for mid, pid, st, ts, xg, xgot in (MatchShot.objects
                                       .filter(match_id__in=match_ids)
                                       .values_list("match_id", "player_id", "shot_type",
                                                    "team_side", "xg", "xgot")):
        feat = SHOT_TYPE_TO_FEATURE.get(st)
        if not feat:
            continue
        if is_own_goal(st, ts, sides.get((mid, pid))):
            continue
        counts[(mid, pid)][feat] += 1.0
        # La SGA TIRO PER TIRO, che la somma degli aggregati non puo' dare: serve
        # alla forma convessa (v. SGA_CONVEXITY). Il legno prende il suo addendo qui
        # come lo prendeva nella versione aggregata.
        d = float(xgot or 0.0) - float(xg or 0.0)
        if st == "post":
            d += SGA_POST_WOODWORK
        elif st == "block":
            d += SGA_POST_BLOCKED
        counts[(mid, pid)]["_sga_shots"] += (
            d if SGA_CONVEXITY == 1.0
            else math.copysign(abs(d) ** SGA_CONVEXITY, d))
    for key, feats in counts.items():
        row = out[key]  # defaultdict(dict): materialises a shots-only player too
        for feat, n in feats.items():
            row[feat] = row.get(feat, 0.0) + n


def _drop_own_goal_shots(out: dict, match_ids) -> None:
    """Un autogol non e' una conclusione tentata: toglilo dal conteggio dei tiri.

    ``_merge_shot_detail`` lo tiene fuori da ``shots_goal``, ma ``shots`` e
    ``xg_shots`` non passano di li' — arrivano dalle zone del fornitore, che
    l'autogol lo conta come un tiro qualunque. Misurato sulla 25-26: 22 autogol su
    22 dentro ``shots``, e siccome il volume di tiro e' creditato, ognuno valeva al
    suo autore un REGALO di +0.048 di voto in media (max +0.054). Il segno e'
    quello che rende la cosa grave, non la taglia: chi vede un contributo positivo
    accanto a un autogol smette di credere al resto del pannello.

    Solo ``shots`` e ``xg_shots``, e non per prudenza generica: sugli stessi 22
    casi il canale dello SPECCHIO non lo conta mai — 0 su 22 in
    ``shots_on_target``, 0 su 22 dentro ``xg_on_target``, anche per i due autogol a
    cui il fornitore allega un xGOT. Sottrarre li' porterebbe i totali sotto zero.
    Il pavimento a zero e' comunque tenuto: se un giorno il fornitore cambiasse
    idea, il conto sbaglia per difetto invece di diventare negativo.

    Il MALUS dell'autogol non c'entra e resta dov'e': e' una voce a livello di
    voto, graduata (deviazione o errore in prima persona), non una feature.
    """
    sides = appearance_sides(match_ids)
    for mid, pid, st, ts, xg in (MatchShot.objects
                                 .filter(match_id__in=match_ids)
                                 .values_list("match_id", "player_id", "shot_type",
                                              "team_side", "xg")):
        if not is_own_goal(st, ts, sides.get((mid, pid))):
            continue
        row = out.get((mid, pid))
        if row is None:
            continue
        row["shots"] = max(0.0, (row.get("shots") or 0.0) - 1.0)
        row["xg_shots"] = max(0.0, (row.get("xg_shots") or 0.0) - (xg or 0.0))


def missing_xgot_rows(match_ids) -> dict:
    """{(match_id, player_id): xGOT dalla mappa dei tiri} per le righe a cui il
    campo del fornitore MANCA del tutto, e che ne avrebbero uno.

    Separata dalla riparazione perche' la stessa domanda serve al canarino, che
    deve poterla porre senza calcolare nessun voto (v. ``health._check_missing_xgot``).

    «Manca» vuol dire ASSENTE, non zero: uno zero misurato su un giocatore che ha
    tirato solo fuori e' il dato giusto — sono 2929 righe della 25-26, ed e' la
    lettura corretta. Qui si cerca il caso opposto, la riga senza nemmeno una voce
    ``xg_on_target`` mentre i tiri dicono che un valore c'era.
    """
    sides = appearance_sides(match_ids)
    got: dict[tuple, float] = defaultdict(float)
    for mid, pid, st, ts, xgot in (MatchShot.objects
                                   .filter(match_id__in=match_ids,
                                           player_id__isnull=False)
                                   .values_list("match_id", "player_id", "shot_type",
                                                "team_side", "xgot")):
        if is_own_goal(st, ts, sides.get((mid, pid))):
            continue
        got[(mid, pid)] += xgot or 0.0
    have = set(PlayerZoneFeature.objects
               .filter(match_id__in=match_ids, provider=PROVIDER_SOFASCORE,
                       feature_key="xg_on_target")
               .values_list("match_id", "player_id").distinct())
    return {k: v for k, v in got.items() if v > 0.0 and k not in have}


def _fill_missing_xgot(out: dict, match_ids) -> None:
    """L'xGOT D'UFFICIO: dove il fornitore non lo manda, lo si legge dai tiri.

    ``sga_post`` sottrae due grandezze che NON vengono dallo stesso posto (lo dice
    l'adapter in cima a se stesso): ``xg_shots`` e' ``shotmap_exact``, somma esatta
    dei tiri, mentre ``xg_on_target`` e' ``heatmap_interpolated``, cioe' l'aggregato
    ``expectedGoalsOnTarget`` del fornitore spalmato sulla heatmap. Quando
    l'aggregato non arriva, la sua assenza si legge come uno ZERO, e la sottrazione
    racconta una partita di conclusioni buttate via.

    IL CASO CHE L'HA MOTIVATA. Moro, Torino-Bologna g25: i totali dicevano
    ``shots_goal`` 1 e ``xg_on_target`` 0 nella stessa riga — un pallone che e'
    entrato senza valore dopo il tiro, che non e' un giudizio severo ma una
    contraddizione. ``sga_post`` veniva −0.880 e il pannello scriveva «una o piu'
    occasioni fallite −0.57» a chi aveva segnato da 0.74 di xG calciando a 0.995.
    Una riga su 11903 in tutta la 25-26: raro, e proprio per questo mai scoperto.

    NON E' UN NUMERO INVENTATO. E' lo stesso evento letto dall'altro archivio, che
    e' gia' la fonte dell'altra meta' della sottrazione: si toglie una discordanza,
    non si aggiunge una stima. Ed e' la stessa logica del voto d'ufficio — un buco
    si tappa dichiarandolo, non si finge misurato.

    SOLO DOVE IL CAMPO E' ASSENTE. Le 204 righe della 25-26 in cui c'e' ma non
    coincide con la somma dei tiri (mediana 0.081) restano intatte: li' le due
    fonti non sono d'accordo e non ho stabilito quale abbia ragione, quindi
    sceglierne una sarebbe una taratura mascherata da riparazione. Quelle le
    segnala ``shot_detail`` a chi apre il pannello, e la fonte unica per tutti e'
    una decisione da prendere col benchmark.
    """
    filled = missing_xgot_rows(match_ids)
    for key, xgot in filled.items():
        row = out.get(key)
        if row is None:
            continue
        row["xg_on_target"] = _round_sum(xgot)
    if filled:
        log.warning("expectedGoalsOnTarget missing for %d player-matches: filled "
                    "from the shot map (worst %.3f). The provider dropped the "
                    "field; without this the vote reads their shooting as wasted.",
                    len(filled), max(filled.values()))


def _merge_defensive_value(out: dict, match_ids) -> None:
    """Fold the provider's defensive value into the per-player totals.

    It lives in ``MatchAppearance.raw_stats``, not in the zone features, and it is
    read from there rather than being spread over the heatmap at import time. That
    split is deliberate: the zone distribution exists for the AURA mode's zone
    duels, and this feature belongs to the classic channel only — spreading a
    normalised scalar across zones and summing it back would be a round trip for
    nothing, and would need the whole season re-imported to boot.

    Absent for a player means 0.0, the population median: an ordinary defensive
    game, not a punishment (see the DEFENSIVE_VALUE_SOURCE note).
    """
    rows = list(MatchAppearance.objects.filter(match_id__in=match_ids)
                .values_list("match_id", "player_id", "minutes_played", "raw_stats"))
    seen = 0
    eligible = 0
    for mid, pid, mins, raw in rows:
        if (mins or 0) >= 15:
            eligible += 1
        value = (raw or {}).get(DEFENSIVE_VALUE_SOURCE)
        if value is None:
            continue
        seen += 1
        out[(mid, pid)]["defensive_value"] = float(value)
    # The field is a provider proxy we cannot rebuild: if it stops arriving the
    # defender vote quietly degrades, so say so rather than scoring on zeroes.
    if eligible and seen / eligible < 0.5:
        log.warning("%s present on only %d of %d appearances over 15 minutes — the "
                    "defensive proxy is degraded and defender votes with it.",
                    DEFENSIVE_VALUE_SOURCE, seen, eligible)


def _merge_assists(out: dict, match_ids) -> None:
    """L'ASSIST nei totali, come il gol.

    Simmetria mancante, non feature nuova: ``shots_goal`` sta nell'indice col suo
    peso ("on top of +3 bonus"), quindi l'esito di una CONCLUSIONE il voto base lo
    paga gia'. L'esito di un PASSAGGIO no, e non c'era una ragione scritta per la
    differenza — solo il fatto che il gol arrivava dalla mappa dei tiri e l'assist
    da nessuna parte.

    Sta in ``MatchAppearance.assists``, non nelle zone, per la stessa ragione di
    ``defensive_value``: e' uno scalare del canale classic, e spargerlo sulla
    heatmap per poi risommarlo sarebbe un giro a vuoto con un reimport dietro.

    Assente = 0: nessun assist, che e' il caso normale.
    """
    for mid, pid, n in (MatchAppearance.objects.filter(match_id__in=match_ids)
                        .values_list("match_id", "player_id", "assists")):
        if n:
            out[(mid, pid)]["assists"] = float(n)


def match_lineup_keepers(match_ids) -> dict:
    """{match_id: {player_id}} di chi, IN DISTINTA, era il portiere.

    Terza risposta alla domanda "questo è un portiere?", e serve perché le altre due
    dipendono da dati che possono non esserci. ``Player.is_goalkeeper`` viene dal
    cartellino Transfermarkt e c'è solo per chi è in una rosa che abbiamo importato;
    il ruolo dichiarato viene dall'inferenza, che di quel tag si fida. Su una
    installazione senza le rose della stagione misurata — la produzione all'11/08/2026
    — sette portieri della 2025-26 avevano il tag a False, nessun ruolo, e per questo
    sono finiti nel clustering dei giocatori di movimento: uscivano CEN, venivano
    valutati sul canale sbagliato (Montipò 5.0 invece di 6.0) e si prendevano una
    fetta del pericolo concesso che spetta ai difensori, spostando di mezzo voto 218
    presenze di compagni di squadra.

    La distinta, invece, c'è sempre dove c'è una partita, e per il portiere non è
    un'inferenza: è la casella in cui il provider lo ha schierato. Per partita e non
    per stagione, così un cambio in porta resta due persone diverse.
    """
    out: dict[int, set] = defaultdict(set)
    for mid, pid, raw in (MatchAppearance.objects.filter(match_id__in=match_ids)
                          .values_list("match_id", "player_id", "raw_stats")):
        if (raw or {}).get("position") == SOFA_GK_POSITION:
            out[mid].add(pid)
    return out


def own_goal_shots(match_ids) -> dict:
    """{(match_id, conceding_side): [(minute, xgot)]} for the own goals of a match.

    Identified by ``is_own_goal``, like every other reading of the same event: the
    docstring used to say "exactly as ``_merge_shot_detail`` does" while repeating
    the test inline, and a promise of agreement kept by copy-paste is the reason
    two other places did NOT agree. The side returned is the one that CONCEDED it
    (the scorer's own), which is the side whose keeper the relief belongs to.
    """
    sides = appearance_sides(match_ids)
    out: dict[tuple, list] = defaultdict(list)
    for mid, pid, st, ts, minute, xgot in (MatchShot.objects
                                           .filter(match_id__in=match_ids, is_goal=True)
                                           .values_list("match_id", "player_id",
                                                        "shot_type", "team_side",
                                                        "minute", "xgot")):
        own = sides.get((mid, pid))
        if not is_own_goal(st, ts, own):
            continue                     # a real goal for the side it counts for
        out[(mid, own)].append((minute, xgot or 0.0))
    return out


def _merge_own_goal_relief(out: dict, match_ids) -> None:
    """Give the keeper back the DIFFICULTY of an own goal scored by his own side.

    See OWN_GOAL_KEEPER_XGOT_DEFAULT for why, and why the credit is the own goal's
    own xGOT rather than a blanket exemption. Added to ``gk_goals_prevented``, which
    is where the provider charged the goal in the first place.

    Gated on the pitch, like the sending-off drop: a keeper who came on after the
    own goal must not collect a credit for a goal that was already in. Whoever was
    in goal at that minute gets it — with a substitution in between, each of the two
    answers only for what happened on his watch.
    """
    own_goals = own_goal_shots(match_ids)
    if not own_goals:
        return
    # Il tag Transfermarkt più la distinta: senza la seconda, il credito non
    # arrivava proprio ai portieri che il tag non copre — cioè quelli che di questa
    # correzione hanno più bisogno (v. ``match_lineup_keepers``).
    keepers = set(Player.objects.filter(is_goalkeeper=True).values_list("id", flat=True))
    lineup_keepers = match_lineup_keepers(match_ids)
    minutes = _minutes_map(match_ids)
    apps = {(a["match_id"], a["player_id"]): (a["side"], a["is_starter"])
            for a in MatchAppearance.objects.filter(match_id__in=match_ids)
            .values("match_id", "player_id", "side", "is_starter")}
    windows = on_pitch_windows(match_ids, minutes, apps)
    for (mid, side), goals in own_goals.items():
        for (m2, pid), (side2, _starter) in apps.items():
            if m2 != mid or side2 != side:
                continue
            if pid not in keepers and pid not in lineup_keepers.get(mid, ()):
                continue
            key = (mid, pid)
            # A keeper with no zone features at all is a match we cannot score (see
            # the note in ``_per_match_player_totals``): materialising a row holding
            # only this credit would invent a scoreable player out of nothing.
            if key not in out:
                continue
            lo, hi = windows.get(key, (0.0, 0.0))
            credit = sum(xgot if xgot else OWN_GOAL_KEEPER_XGOT_DEFAULT
                         for minute, xgot in goals
                         if minute is not None and lo <= minute <= hi)
            if credit:
                out[key]["gk_goals_prevented"] = (
                    out[key].get("gk_goals_prevented", 0.0) + credit)


# Quanto conta che l'intervento sia arrivato nel minuto decisivo. UNO SOLO, con segno.
# La stima libera su questo termine, controllata per tutto il canale, e' +0.0270 +/-
# 0.0173 in punti di voto per deviazione standard; 0.275 e' il valore in unita' della
# feature che le corrisponde.
KEEPER_MOMENT_LAMBDA = 0.275

def _merge_keeper_moment(out: dict, match_ids) -> None:
    """Pesa gli interventi del portiere per QUANTO CONTAVA il momento.

    ``gk_goals_prevented`` e' ``somma (xgot - gol)`` sui tiri affrontati: una parata
    vale ``+xgot`` (merito), un gol vale ``-(1 - xgot)`` (colpa). SONO LO STESSO
    TERMINE COL SEGNO OPPOSTO, quindi il peso del momento e' UNO SOLO e si applica
    alla quantita' con segno, su TUTTI i tiri affrontati:

        somma_tiri  lambda * (peso - 1) * (xgot - gol)

    Fino al 03/09/2026 questa correzione esisteva ma era ASIMMETRICA — pesava solo i
    GOL, e con un coefficiente implicito di +0.0795 punti di voto per 1 sd, cioe' tre
    volte il bordo superiore dell'intervallo stimato. Il portiere pagava il momento
    delle reti subite e non incassava quello delle parate decisive: la stessa
    grandezza letta con due metri diversi a seconda del segno. Quasi tutto il
    guadagno della correzione viene dall'aver tolto quell'asimmetria, non
    dall'aggiungere il momento — che vale +0.001 di accordo e si tiene per la
    simmetria fra i due lati e perche' «intervento in un momento decisivo» e' una
    voce che la pagella puo' nominare.

    ``peso`` ha media 1 (v. ``goal_impact.conceded_weight``), quindi la correzione
    RIDISTRIBUISCE fra momenti pesanti e ininfluenti: non gonfia ne' sgonfia il conto
    complessivo dei portieri.

    Gated on the pitch: chi entra dopo non risponde di un tiro gia' affrontato.
    L'autogol resta fuori — la sua difficolta' e' gia' restituita da
    ``_merge_own_goal_relief``.
    """
    ids = list(match_ids)
    if not ids or not KEEPER_MOMENT_LAMBDA:
        return
    keepers = set(Player.objects.filter(is_goalkeeper=True).values_list("id", flat=True))
    lineup_keepers = match_lineup_keepers(ids)
    minutes = _minutes_map(ids)
    apps = {(a["match_id"], a["player_id"]): (a["side"], a["is_starter"])
            for a in MatchAppearance.objects.filter(match_id__in=ids)
            .values("match_id", "player_id", "side", "is_starter")}
    windows = on_pitch_windows(ids, minutes, apps)
    xp = goal_impact.fixed_xp_table()
    _band, p95 = goal_impact.fixed_band()
    for match in Match.objects.filter(id__in=ids):
        side_of = dict(MatchAppearance.objects.filter(match=match)
                       .values_list("player_id", "side"))
        shots = [s for s in MatchShot.objects.filter(match=match)
                 .values("player_id", "minute", "team_side", "shot_type", "xgot", "is_goal")
                 if s["minute"] is not None]
        if not shots:
            continue
        shots.sort(key=lambda s: s["minute"])
        goals = [s for s in shots if s["is_goal"]]
        for shot in shots:
            # Il lato che SUBISCE questo tiro, e il punteggio prima che partisse:
            # e' quello che decide quanto contava (v. goal_impact.importance).
            against = "away" if shot["team_side"] == "home" else "home"
            own = is_own_goal(shot["shot_type"], shot["team_side"],
                              side_of.get(shot["player_id"]))
            if shot["is_goal"] and own:
                continue
            subiti = sum(1 for g in goals
                         if g["team_side"] == against and g["minute"] < shot["minute"])
            fatti = sum(1 for g in goals
                        if g["team_side"] != against and g["minute"] < shot["minute"])
            peso = goal_impact.conceded_weight(
                goal_impact.importance(xp, shot["minute"], subiti - fatti - 1), p95)
            if peso == 1.0:
                continue
            xgot = float(shot["xgot"] or 0.0)
            firmato = xgot - (1.0 if shot["is_goal"] else 0.0)
            delta = KEEPER_MOMENT_LAMBDA * (peso - 1.0) * firmato
            if not delta:
                continue
            for (m2, pid), (side2, _starter) in apps.items():
                if m2 != match.id or side2 != against:
                    continue
                if pid not in keepers and pid not in lineup_keepers.get(match.id, ()):
                    continue
                key = (match.id, pid)
                if key not in out:
                    continue
                lo, hi = windows.get(key, (0.0, 0.0))
                if not (lo <= shot["minute"] <= hi):
                    continue
                out[key]["gk_goals_prevented"] = (
                    out[key].get("gk_goals_prevented", 0.0) + delta)


def _fallback_window(minutes: int, is_starter: bool) -> tuple[float, float]:
    """Last-resort on-pitch window when no interval was recorded for the match.

    A starter is assumed to run from kick-off, a substitute to finish the match.
    Wrong whenever a substitute is himself withdrawn later — a case this shape
    cannot express at all — which is exactly why PlayerOnPitchInterval exists and
    is preferred wherever it has been built.
    """
    minutes = max(0, min(int(minutes or 0), 95))
    if is_starter:
        return 0.0, float(minutes)
    return float(max(0, 95 - minutes)), 95.0


def on_pitch_windows(match_ids, minutes: dict, appearances: dict) -> dict:
    """{(match_id, player_id): (from_minute, to_minute)}.

    Prefers the recorded interval — built from the provider's substitution and
    red-card incidents, so it is exact and covers the substitute who is himself
    replaced — and falls back to the crude assumption only for matches where no
    interval exists.
    """
    windows = {(mid, pid): (float(a), float(b)) for mid, pid, a, b in
               (PlayerOnPitchInterval.objects
                .filter(match_id__in=match_ids)
                .values_list("match_id", "player_id", "start_minute", "end_minute"))}
    for key, (side, is_starter) in appearances.items():
        if key not in windows:
            windows[key] = _fallback_window(minutes.get(key, 0), is_starter)
    return windows


def _zone_presence(match_ids) -> dict:
    """{(match_id, player_id): {(col, row): share}}, shares summing to 1.

    The provider gives a positional heatmap per player, and the importer spreads
    his touch total over the zones in proportion to it — so dividing the per-zone
    touches by their total recovers the heatmap itself: what fraction of his time
    on the pitch he spent in each zone. It is a POSITIONAL measure, not a
    ball-contact one, which is what charging conceded danger requires (a defender
    beaten in his own box touches nothing at all).

    Which is exactly why the UNPLACED rows are excluded rather than read as a
    position. A live match's light round writes a player's totals without knowing
    where he was; taken at face value they would stand him in one cell of the grid
    and charge him for whatever the opposition did there. Nobody's exposure is
    better than no exposure at all — see ``sofascore_adapter.METHOD_UNPLACED``.
    """
    zones: dict[tuple, dict] = defaultdict(dict)
    for mid, pid, zk, v in (PlayerZoneFeature.objects
                            .filter(match_id__in=match_ids, provider=PROVIDER_SOFASCORE,
                                    feature_key="touches")
                            .exclude(source_method=METHOD_UNPLACED)
                            .values_list("match_id", "player_id", "zone_key")
                            .annotate(v=Sum("value"))
                            .values_list("match_id", "player_id", "zone_key", "v")):
        _, col, row = zk.split("_")
        zones[(mid, pid)][(int(col), int(row))] = _round_sum(v)
    out = {}
    for key, z in zones.items():
        total = sum(z.values())
        if total > 0:
            out[key] = {k: v / total for k, v in z.items()}
    return out


def _presence_at(zones: dict, zone: tuple) -> float:
    """Presence in a zone, blurred into its four neighbours by EXPOSURE_KERNEL.

    The 5x4 grid is coarse: a shot two metres the other side of a boundary would
    otherwise be charged entirely to the next man along. The blur is deliberately
    NOT normalised — it is a similarity kernel, and the relative share it feeds
    divides it out anyway."""
    v = zones.get(zone, 0.0)
    if EXPOSURE_KERNEL:
        v += EXPOSURE_KERNEL * sum(zones.get((zone[0] + dc, zone[1] + dr), 0.0)
                                   for dc, dr in _NEIGHBOURS)
    return v


def _charge_of_shot(is_goal: bool, xgot, shot_type: str) -> float:
    """Goal-equivalent danger a single conceded shot puts on the defence.

    ``λ·outcome + (1−λ)·xGOT`` (see EXPOSURE_LAMBDA). Off-target and blocked shots
    carry no xGOT and no outcome, so they charge exactly nothing — the defence
    dealt with them."""
    outcome = 1.0 if is_goal else (EXPOSURE_POST_OUTCOME if shot_type == "post" else 0.0)
    return EXPOSURE_LAMBDA * outcome + (1.0 - EXPOSURE_LAMBDA) * (xgot or 0.0)


def defensive_exposure(match_ids, minutes: dict) -> dict:
    """{(match_id, player_id): danger conceded where AND WHILE this player played}.

    Each conceded shot carries a charge (``_charge_of_shot``) that is split across
    the outfielders on the pitch in proportion to their presence in the zone it
    came from — so a shot is always distributed in full, and a player answers for
    the danger born where he was standing, not for his team's scoreline. See the
    EXPOSURE_* block for what is charged, to whom, and why.

    Two frames have to line up, and both are verified rather than assumed:

    * the two teams' zone grids are a 180 degree rotation of each other, so an
      attacking zone (col, row) is (4-col, 3-row) for the defence. Attributing
      with the row mirrored puts more conceded danger on the defenders who
      actually committed a shot-conceding error (1.21x vs 1.14x unmirrored),
      matching the rotation independently established for the shot map;
    * only shots struck while he was on the pitch count, for the shooter's side
      AND for every team-mate the charge is split with. Scaling a whole-match
      total by minutes played, which is what this did first, is unbiased on
      average (-0.005) yet misattributes more than 20 percentage points of a
      match's danger for one defender in seven. A defender must not answer for a
      goal conceded after he came off.

    Penalties are skipped outright: zone presence says nothing about who stands
    near the spot, and the foul itself is already charged to whoever conceded it
    (``penalties_conceded``).
    """
    conceded: dict[tuple, list] = defaultdict(list)
    for mid, side, minute, zk, xgot, is_goal, situation, shot_type in (
            MatchShot.objects
            .filter(match_id__in=match_ids, provider=PROVIDER_SOFASCORE)
            .values_list("match_id", "team_side", "minute", "zone_key", "xgot",
                         "is_goal", "situation", "shot_type")):
        if situation == "penalty":
            continue
        charge = _charge_of_shot(is_goal, xgot, shot_type)
        if charge <= 0:
            continue
        _, col, row = zk.split("_")
        # stored already mirrored into the DEFENDING side's frame
        conceded[(mid, side)].append((minute, (4 - int(col), 3 - int(row)), charge))
    if not conceded:
        return {}

    appearances = {(a["match_id"], a["player_id"]): (a["side"], a["is_starter"])
                   for a in MatchAppearance.objects.filter(match_id__in=match_ids)
                   .values("match_id", "player_id", "side", "is_starter")}
    presence = _zone_presence(match_ids)
    windows = on_pitch_windows(match_ids, minutes, appearances)
    # The keeper is excluded from the split, not merely spared the charge: his
    # heatmap sits entirely in the zone the danger arrives in, so leaving him in
    # would swallow the share the defenders in front of him should carry.
    #
    # TRE prove, in OR, perché le prime due possono mancare: il tag Transfermarkt
    # esiste solo per chi sta in una rosa importata, il ruolo dichiarato si fida di
    # quel tag, e la distinta invece c'è sempre (v. ``match_lineup_keepers``). Senza
    # la terza, un portiere che il tag non copre si prendeva una fetta del pericolo
    # concesso e la sottraeva ai difensori davanti a lui.
    keepers = set(Player.objects.filter(is_goalkeeper=True).values_list("id", flat=True))
    keepers |= {pid for pid, role in current_role_map().items() if role == Player.ROLE_GK}
    lineup_keepers = match_lineup_keepers(match_ids)

    # who can be charged, per (match, side), with their window and presence map
    squads: dict[tuple, list] = defaultdict(list)
    for key, zones in presence.items():
        mid, pid = key
        if pid in keepers or pid in lineup_keepers.get(mid, ()):
            continue
        side, is_starter = appearances.get(key, (None, False))
        if not side:
            continue
        lo, hi = windows.get(key, _fallback_window(minutes.get(key, 0), is_starter))
        squads[(mid, side)].append((pid, lo, hi, zones))

    opposite = {"home": "away", "away": "home"}
    out: dict = {}
    for (mid, shooting_side), shots in conceded.items():
        defending = opposite.get(shooting_side)
        squad = squads.get((mid, defending))
        if not squad:
            continue
        for minute, zone, charge in shots:
            on_pitch = [(pid, _presence_at(zones, zone)) for pid, lo, hi, zones in squad
                        if minute is None or lo <= minute <= hi]
            total = sum(v for _pid, v in on_pitch)
            if total <= 0:
                continue
            for pid, v in on_pitch:
                if v:
                    out[(mid, pid)] = out.get((mid, pid), 0.0) + v / total * charge
    return out


def on_pitch_goal_difference(match_ids, minutes: dict) -> dict:
    """{(match_id, player_id): goals_for - goals_against WHILE he was on the pitch}.

    The mitigation nudges a vote toward the team's fortunes, but only for the
    minutes the player actually shared: a defender must not be tempered for goals
    conceded after he came off, nor a sub credited for a lead built before he came
    on. Goals are timed from the shot map (is_goal); presence from the same on-pitch
    windows the exposure uses. Only non-zero differences are returned."""
    return {k: gf - ga for k, (gf, ga) in _on_pitch_goals(match_ids, minutes).items()
            if gf != ga}


def on_pitch_goals_against(match_ids, minutes: dict) -> dict:
    """{(match_id, player_id): goals conceded WHILE he was on the pitch}.

    The keeper's half of the same count, never a penalty of its own — conceding is
    priced by goals_prevented in the index and by the -1/goal malus in the bonus
    layer, and a third charge here would be the double count we are removing."""
    return {k: ga for k, (_gf, ga) in _on_pitch_goals(match_ids, minutes).items() if ga}


def _on_pitch_goals(match_ids, minutes: dict) -> dict:
    """{(match_id, player_id): (goals_for, goals_against) while he was on the pitch}."""
    goals: dict[int, list] = defaultdict(list)  # match_id -> [(minute, side)]
    for mid, minute, side in (MatchShot.objects
                              .filter(match_id__in=match_ids, is_goal=True,
                                      provider=PROVIDER_SOFASCORE)
                              .values_list("match_id", "minute", "team_side")):
        goals[mid].append((minute, side))
    if not goals:
        return {}
    appearances = {(a["match_id"], a["player_id"]): (a["side"], a["is_starter"])
                   for a in MatchAppearance.objects.filter(match_id__in=match_ids)
                   .values("match_id", "player_id", "side", "is_starter")}
    windows = on_pitch_windows(match_ids, minutes, appearances)
    out = {}
    for key, (side, is_starter) in appearances.items():
        scored = goals.get(key[0])
        if not scored:
            continue
        lo, hi = windows.get(key, _fallback_window(minutes.get(key, 0), is_starter))
        gf = ga = 0
        for minute, gside in scored:
            if minute is None or not (lo <= minute <= hi):
                continue
            if gside == side:
                gf += 1
            else:
                ga += 1
        out[key] = (gf, ga)
    return out


def _minutes_map(match_ids):
    return {(a["match_id"], a["player_id"]): a["minutes_played"]
            for a in MatchAppearance.objects
            .filter(match_id__in=match_ids)
            .values("match_id", "player_id", "minutes_played")}


def reference_population_keyed(competition_season_id: int):
    """Come ``_reference_population``, ma con la CHIAVE (match, player) davanti.

    Serve a chi deve agganciare alla riga qualcosa che nei totali non c'e' — i gol
    e la loro importanza, che vivono nella mappa dei tiri. Stessa popolazione,
    perche' una media presa su un insieme diverso da quello che definisce la
    reference sposta il centro del ruolo di quanto i due differiscono."""
    for key, role, feats, mins, exp in _reference_population(
            competition_season_id, with_key=True):
        yield key, role, feats, mins, exp


def _reference_population(competition_season_id: int, with_key: bool = False):
    """[(role, totals, minutes, exposure)] — the games that define every calibration.

    One definition, used by the feature scales, the role reference and the
    explanation's role averages alike: a drifting population between them would put
    the vote and its justification on different scales."""
    match_ids = list(Match.objects
                     .filter(competition_season_id=competition_season_id)
                     .values_list("id", flat=True))
    totals = _per_match_player_totals(match_ids)
    minutes = _minutes_map(match_ids)
    exposure = defensive_exposure(match_ids, minutes)
    roles = current_role_map(only_declared=True)
    for (mid, pid), feats in totals.items():
        role = roles.get(pid)
        if not role:
            continue
        mins = minutes.get((mid, pid), 0)
        if mins < MIN_MINUTES_REFERENCE or not is_rated(mins, feats):
            continue
        row = (role, feats, mins, exposure.get((mid, pid), 0.0))
        yield ((mid, pid), *row) if with_key else row


def build_feature_scales(competition_season_id: int) -> dict:
    """{"outfield"|"gk": {feature: {"sigma_raw", "sigma_z"}}} over a season.

    The two spreads the standardisation needs (see ``_feature_z``), frozen next to
    the role reference so a weight keeps its meaning between recalibrations. Two
    passes are unavoidable: the second σ is the spread of the COMPRESSED variable,
    which cannot be known before the first σ has fixed the compression scale.
    """
    raw: dict[str, dict[str, list]] = {"outfield": defaultdict(list), "gk": defaultdict(list)}
    for role, feats, mins, exp in _reference_population(competition_season_id):
        gk = role == Player.ROLE_GK
        bucket = raw["gk" if gk else "outfield"]
        for k, v in raw_feature_values(feats, mins, exp, gk=gk).items():
            bucket[k].append(v)

    def _sd(values, centre=0.0):
        n = len(values)
        if n < 2:
            return 0.0
        m = sum(values) / n
        return math.sqrt(sum((x - m) ** 2 for x in values) / n)

    out: dict[str, dict] = {}
    for channel, cols in raw.items():
        scales = {}
        for k, values in cols.items():
            s_raw = _sd(values)
            if not s_raw:
                continue  # a feature with no spread carries no information
            comp = _compression_of(k)
            s_z = _sd([comp(v / s_raw) for v in values])
            if not s_z:
                continue
            # mu_z: where the AVERAGE appearance sits on the standardised scale.
            # Needed by any transform that has to know what "average" means for a
            # feature — today only the exposure's asymmetric credit
            # (EXPOSURE_CREDIT); stored for every feature because it costs nothing
            # and a frozen mean belongs next to the frozen spreads it goes with.
            mu_z = sum(comp(v / s_raw) for v in values) / (len(values) * s_z)
            scales[k] = {"sigma_raw": s_raw, "sigma_z": s_z, "mu_z": mu_z,
                         "n": len(values)}
        out[channel] = scales
    return out


_scales_cache: dict | None = None


def feature_scales(*, gk: bool = False) -> dict:
    """The frozen per-feature spreads for a channel (see ``build_feature_scales``).

    Read from the calibration file. Missing (a fresh checkout, a test database) is
    not fatal: the weights simply have nothing to standardise against, so every
    feature returns 0 and the vote falls back to the role centre — loudly wrong
    rather than quietly rescaled, which is the failure mode we want."""
    global _scales_cache
    if _scales_cache is None:
        from vfoot.services.vote_reference import fixed_feature_scales
        _scales_cache = fixed_feature_scales() or {}
    return _scales_cache.get("gk" if gk else "outfield", {})


def clear_scales_cache() -> None:
    """Drop the in-process copy (after a recalibration, or in tests)."""
    global _scales_cache
    _scales_cache = None


MINUTE_CURVE_WINDOW = 8      # +-minuti della media mobile
MINUTE_CURVE_MIN_N = 30      # sotto questo campione il punto non si stima


def build_minute_curves(competition_season_id: int, reference: dict,
                        scales: dict | None = None) -> None:
    """Aggiunge a ``reference`` le due curve indice-vs-minuti, IN LOCO.

    ``by_minute`` per l'indice intero e ``observed_by_minute`` per la sola parte
    dei fatti, piu' ``observed_mean``. Sono cio' che permette di leggere come
    merito solo lo scarto dal rendimento TIPICO DI QUEL MINUTAGGIO — v.
    MINUTE_CONDITIONING.

    SU TUTTE LE PRESENZE VALUTATE, non sulla popolazione di riferimento: quella
    taglia sotto i ``MIN_MINUTES_REFERENCE`` minuti, cioe' proprio la fascia che
    le curve devono descrivere. Le MEDIE di ruolo restano invece quelle della
    reference, perche' spostarle muoverebbe ogni voto.
    """
    match_ids = list(Match.objects
                     .filter(competition_season_id=competition_season_id)
                     .values_list("id", flat=True))
    totals = _per_match_player_totals(match_ids)
    minutes = _minutes_map(match_ids)
    exposure = defensive_exposure(match_ids, minutes)
    roles = current_role_map()
    idx_by = defaultdict(lambda: defaultdict(list))
    obs_by = defaultdict(lambda: defaultdict(list))
    obs_ref = defaultdict(list)
    for (mid, pid), feats in totals.items():
        role = roles.get(pid)
        if role is None or role == Player.ROLE_GK:
            continue
        mins = minutes.get((mid, pid), 0)
        if not mins or not is_rated(mins, feats):
            continue
        exp = exposure.get((mid, pid), 0.0)
        chan = (scales or {}).get("outfield")
        idx_by[role][mins].append(index_for_role(role, feats, mins, exp, chan))
        o = observed_index(role, feats, mins, exp, chan)
        obs_by[role][mins].append(o)
        if mins >= MIN_MINUTES_REFERENCE:
            obs_ref[role].append(o)

    def curva(bymin: dict) -> dict:
        out = {}
        for m in range(1, 130):
            vals = [v for mm, lst in bymin.items()
                    if abs(mm - m) <= MINUTE_CURVE_WINDOW for v in lst]
            if len(vals) >= MINUTE_CURVE_MIN_N:
                out[str(m)] = sum(vals) / len(vals)
        return out

    for role in idx_by:
        if role not in reference:
            continue
        reference[role]["by_minute"] = curva(idx_by[role])
        reference[role]["observed_by_minute"] = curva(obs_by[role])
        vals = obs_ref.get(role) or []
        reference[role]["observed_mean"] = (sum(vals) / len(vals)) if vals else 0.0


def flatten_minute_curves(competition_season_id: int, reference: dict,
                          external: dict, window: int = MINUTE_CURVE_WINDOW,
                          min_n: int = MINUTE_CURVE_MIN_N) -> dict:
    """Corregge ``by_minute`` col RESIDUO contro un giudizio esterno, IN LOCO.

    ``external`` e' {"<giornata>:<player_id>": voto}. Ritorna {minuti: residuo} per
    il log.

    PERCHE'. La curva nasce come "indice medio a quei minuti", ma il suo mestiere e'
    un altro: rendere confrontabili minutaggi diversi. Misurata sull'indice, quel
    mestiere lo fa male in una fascia precisa — i 46-70 minuti, che sono al 95%
    TITOLARI SOSTITUITI. Per chi entra il poco minutaggio e' una circostanza e va
    perdonata; per chi esce e' un verdetto (l'allenatore lo toglie perche' gioca
    male, e il suo indice infatti e' negativo), e perdonarlo e' l'errore. La stessa
    curva tratta due popolazioni che vogliono dire l'opposto.
    Misurato sulla 25-26: nella fascia i titolari tolti prendono da noi +0.070 piu'
    del giudice, i 53 subentrati +0.000.
    Correggerla sul residuo chiude la cosa senza dover modellare la causa: scarto
    fra la fascia migliore e la peggiore da 0.140 a 0.028, errore medio da 0.3416 a
    0.3387.
    """
    per: dict[int, list] = defaultdict(list)
    ref_only = {r: reference[r] for r in reference if r in ("DIF", "CEN", "ATT")}
    for m in Match.objects.filter(competition_season_id=competition_season_id):
        for row in voto_puro_for_match(m, reference):
            if not row["rated"] or row.get("role") not in ref_only:
                continue
            voto = external.get(f'{m.matchday}:{row["player_id"]}')
            if voto is None:
                continue
            # PRIMA dello stadio finale, e arrotondato come fa il banco: la curva
            # si tara sul voto che lo stadio finale poi comprimera'.
            nostro = _round_half(row.get("voto_pre_scala", row["voto_puro"]))
            per[int(row["minutes"])].append(nostro - voto)
    residuo = {}
    for minute in range(1, 100):
        campione = [x for mm in range(minute - window, minute + window + 1)
                    for x in per.get(mm, ())]
        if len(campione) >= min_n:
            residuo[minute] = sum(campione) / len(campione)
    if not residuo:
        return {}
    for role, r in ref_only.items():
        curva = dict(r.get("by_minute") or {})
        for minute, scarto in residuo.items():
            w = minute / (minute + shrinkage_for(role))
            conditioning = minute_conditioning_for(role)
            if w <= 0 or not conditioning:
                continue
            curva[str(minute)] = curva.get(str(minute), 0.0) + (
                scarto * r["std"] / (spread_k_for(role) * w * conditioning))
        r["by_minute"] = curva
    return residuo


def build_reference(competition_season_id: int, *,
                    pooled_std: bool = POOLED_ROLE_SPREAD,
                    scales: dict | None = None) -> dict:
    """Per-role (mean, std) of the performance index over a season.

    Returns {role: {"mean": m, "std": s, "n": n}}. With ``pooled_std`` every
    outfield role keeps its own centre but shares ONE spread — see
    POOLED_ROLE_SPREAD for why that is the default.

    ``scales`` must be the ones the votes will be scored with; the calibration
    command passes the freshly built set, since the frozen file is still the old one
    at that point.
    """
    samples = defaultdict(list)  # role -> [performance index]
    for role, feats, mins, exp in _reference_population(competition_season_id):
        # GKs get their own index AND their own role bucket, so they are z-scored
        # WITHIN the role: the keeper scale is self-calibrating like every other.
        chan = (scales or {}).get("gk" if role == Player.ROLE_GK else "outfield")
        samples[role].append(index_for_role(role, feats, mins, exp, chan))

    ref = {}
    for role, vals in samples.items():
        n = len(vals)
        mean = sum(vals) / n
        var = sum((x - mean) ** 2 for x in vals) / n if n > 1 else 0.0
        ref[role] = {"mean": mean, "std": math.sqrt(var) or 1.0, "n": n}

    # Bucket for players whose role we don't know: pool every OUTFIELD sample
    # (keepers excluded — their index lives on a different scale entirely). Less
    # precise than the right role bucket, but a real vote beats a fake s.v.
    outfield = [x for role, vals in samples.items() if role != Player.ROLE_GK
                for x in vals]
    if outfield:
        n = len(outfield)
        mean = sum(outfield) / n
        var = sum((x - mean) ** 2 for x in outfield) / n if n > 1 else 0.0
        ref[POOLED_OUTFIELD] = {"mean": mean, "std": math.sqrt(var) or 1.0, "n": n}

    if pooled_std:
        # OUTFIELD ONLY, and this is not a detail: the keeper index lives on its own
        # scale entirely (spread ~2.2 against ~0.4), so pooling him in would blow the
        # shared spread up by a factor of five and flatten every outfield vote toward
        # 6. He keeps his own, as he keeps his own feature channel.
        residuals = [x - ref[role]["mean"] for role, vals in samples.items()
                     if role != Player.ROLE_GK for x in vals]
        if residuals:
            m = sum(residuals) / len(residuals)
            pooled = math.sqrt(sum((r - m) ** 2 for r in residuals) / len(residuals))
            for role in ref:
                if role != Player.ROLE_GK:
                    ref[role]["std"] = pooled or 1.0
    return ref


def minute_shift(ref_key: str, minutes: int, reference: dict,
                 curve_key: str = "by_minute", mean_key: str = "mean") -> float:
    """Quanto dell'indice e' spiegato dal solo aver giocato quei minuti.

    ``MINUTE_CONDITIONING`` per lo scostamento fra la media dell'indice a QUEL
    minutaggio e la media del ruolo. Zero quando la curva non c'e' (reference
    vecchia, o un ruolo senza abbastanza presenze per stimarla): la mancanza
    riporta al comportamento di prima, mai a un voto inventato."""
    r = reference.get(ref_key) or {}
    curve = r.get(curve_key)
    conditioning = minute_conditioning_for(ref_key)
    if not curve or not conditioning:
        return 0.0
    m = max(0, int(minutes or 0))
    val = curve.get(m) if isinstance(curve, dict) else None
    if val is None:
        val = curve.get(str(m)) if isinstance(curve, dict) else None
    if val is None:                     # fuori dai minuti campionati: il piu' vicino
        try:
            keys = sorted(int(k) for k in curve)
        except (TypeError, ValueError):
            return 0.0
        if not keys:
            return 0.0
        near = min(keys, key=lambda k: abs(k - m))
        val = curve.get(near, curve.get(str(near)))
    if val is None:
        return 0.0
    return conditioning * (float(val) - r.get(mean_key, 0.0))


def _raw_vote_from_index(index: float, ref_key: str, minutes: int, reference: dict,
                         spread_k: float = VOTE_SPREAD_K,
                         observed: float | None = None) -> float:
    """The vote before the 0.5-grid rounding (and before result mitigation), clamped
    to the pagella range. Split out so the mitigation nudge can be applied to the
    raw value and the result rounded once.

    L'unico restringimento e' quello dei MINUTI. Ce n'era un secondo per i
    portieri, sull'evidenza della partita, tolto il 31/08/2026: v. la lapide di
    GK_EVIDENCE_FULL."""
    centre = vote_center_for(ref_key)
    r = reference.get(ref_key)
    if not r:
        return centre
    spread_k = spread_k_for(ref_key, spread_k)
    # Il minutaggio spiega gia' una parte dell'indice: la si toglie prima di
    # leggere il resto come merito (v. MINUTE_CONDITIONING).
    z = (index - r["mean"] - minute_shift(ref_key, minutes, reference)) / r["std"]
    # Shrink toward the role prior (z -> 0) when minutes are few: we don't trust a
    # per-90 rate extrapolated from a short cameo, so the vote regresses to 6 in
    # proportion to the evidence. w -> 1 for full games, ~0.4 at 20', ~0.3 at 10'.
    w = minutes / (minutes + shrinkage_for(ref_key)) if minutes > 0 else 0.0
    # I FATTI OSSERVATI NON PRENDONO ``w`` (v. UNSHRUNK_FEATURES). Scritto come
    # correzione additiva e non spaccando l'indice: w*I + (1-w)*O = w*resto + O,
    # quindi questa riga da' esattamente "i tassi attenuati, i fatti interi" senza
    # obbligare ogni chiamante a conoscere la divisione. Con ``observed`` assente
    # la correzione e' nulla e il voto e' quello di prima.
    extra = 0.0
    if observed is not None and w < 1.0:
        o_mean = r.get("observed_mean")
        if o_mean is not None:
            o_z = (observed - o_mean
                   - minute_shift(ref_key, minutes, reference,
                                  "observed_by_minute", "observed_mean")) / r["std"]
            extra = UNSHRINK_GAMMA * (1.0 - w) * o_z
    raw = centre + spread_k * (w * z + extra)
    return max(VOTE_MIN, min(VOTE_MAX, raw))


def _round_half(vote: float) -> float:
    return round(vote * 2) / 2.0  # 0.5 grid


def _vote_from_index(index: float, ref_key: str, minutes: int, reference: dict,
                     spread_k: float = VOTE_SPREAD_K) -> float:
    """Il voto del solo indice, senza le correzioni post-indice.

    PASSA DALLO STADIO FINALE come il voto vero: una funzione che si chiama "il voto"
    e salta l'ultimo stadio e' una trappola per chi la trova cercando."""
    grezzo = _raw_vote_from_index(index, ref_key, minutes, reference, spread_k)
    return _round_half(scale_saturation(grezzo, ref_key)[0])


def result_mitigation(raw_vote: float, gd_on: int, *,
                      centre: float = VOTE_CENTER,
                      cap: float = RESULT_MITIGATION_CAP,
                      k: float = RESULT_MITIGATION_K,
                      base: float = RESULT_MITIGATION_BASE,
                      max_share: float = RESULT_MITIGATION_MAX_SHARE,
                      anchor: float = RESULT_MITIGATION_LOSS_ANCHOR,
                      loss_k: float = RESULT_MITIGATION_LOSS_K,
                      loss_base: float = RESULT_MITIGATION_LOSS_BASE,
                      loss_max_share: float = RESULT_MITIGATION_LOSS_MAX_SHARE) -> float:
    """Divergence-only nudge toward the on-pitch result. ASIMMETRICA.

    Fires only for a vote ABOVE the target in a net defeat (gd_on<0) — pulled DOWN —
    or BELOW the centre in a net win (gd_on>0) — pulled UP. An aligned vote gets
    neither, so the nudge never inflates and never pushes a bad game further down in
    a win. The result severity is ``base + k·|gd_on|``: the discrete ``base`` marks
    that it IS a defeat/win (fires on the first goal), ``k`` weights each further
    goal of margin.

    I DUE LATI HANNO BERSAGLI DIVERSI, ed è deliberato (30/08/2026, v. il blocco
    RESULT_MITIGATION_LOSS_ANCHOR per la misura che lo giustifica):

      * sconfitta — il bersaglio è ``centre - anchor``, quindi una goleada subita
        può portare un voto SOTTO il centro di ruolo, fino a 5.65 per un
        centrocampista. È il motivo per cui esiste questa asimmetria: le pagelle
        esterne in una disfatta mandano la squadra all'insufficienza, e fermarsi
        al 6 lasciava un bias sistematico di +0.21 a tre gol di scarto;
      * vittoria — il bersaglio resta il centro, con le costanti di sempre: un
        voto basso in una goleada inflitta arriva al 6 e non un centesimo oltre.

    TRE limiti, e rispondono a domande diverse: ``max_share`` / ``loss_max_share``
    sono la FRAZIONE massima della divergenza che il risultato può cancellare — ed è
    quel che tiene il voto da questa parte del bersaglio, qualunque sia lo scarto —
    mentre ``cap`` è la caduta massima in punti di voto.

    ``centre`` e' il voto ORDINARIO del ruolo, non il 6 fisso: dal 25/08/2026 un
    difensore e' costruito attorno a 5.905 (ROLE_VOTE_CENTER), e misurare la sua
    divergenza dal 6 lo avrebbe fatto passare per «voto basso» anche quando era
    esattamente nella media del suo ruolo — spinto su in ogni vittoria, cioe' un
    offset che si mangiava da solo (misurato: +0.015 sulla media realizzata).
    L'ancora della sconfitta si misura da lì, non dal 6, per la stessa ragione.
    """
    if gd_on == 0:
        return 0.0
    if gd_on < 0:
        # only a vote above the (lowered) target is tempered in a defeat
        over = max(0.0, raw_vote - (centre - anchor))
        severity = min(loss_max_share, loss_base + loss_k * abs(gd_on))
        return max(-cap, -over * severity)
    under = max(0.0, centre - raw_vote)  # only a low vote is lifted in a win
    severity = min(max_share, base + k * gd_on)
    return min(cap, under * severity)


def voto_puro_for_match(match, reference: dict,
                        spread_k: float = VOTE_SPREAD_K,
                        always_rate: set | None = None) -> list[dict]:
    """Per-player voto puro for one match. List of dicts with components.

    LEAGUE-BLIND ON PURPOSE. There is no ``league`` parameter and there should not
    be one by accident: a performance is worth what it is worth, and the same match
    read from two leagues shows the same votes. The roles below come from
    ``current_role_map()`` — the season-wide measurement — so a player a league has
    frozen as ATT is still z-scored here against the population the DATA puts him
    in. That league's frozen role governs his label and his lineup slot, not his
    vote; see ``classic_pagella.pagella_for_match``, where the two part, and
    AGENTS.md "Classic Role Resolution" for what the choice costs (0.028 of a vote
    on average, 2 shown half-points in 36 appearances).

    Players below the rating threshold get ``rated=False`` and ``voto_puro=None``
    (senza voto). Goalkeepers are included, scored on the GK channel.

    A player with no declared role is NOT skipped: he is scored against the
    pooled outfield reference (or the GK one if his features give him away) and
    flagged ``role_known=False``. Dropping him used to render as s.v., which is a
    verdict on his performance — so a goalscorer could be shown as unrated.

    ``always_rate`` exempts a set of players from the minutes/involvement gate. Its
    one caller is the LIVE path (see ``classic_pagella.players_on_pitch``): senza
    voto is a verdict on a FINISHED performance, and at the tenth minute of a match
    everyone on the pitch is below the gate — declaring the whole XI s.v. says
    "they did nothing" when what is true is "they have barely started". They get
    the vote their ten minutes are worth, shrunk toward 6 by the same Bayesian
    weight that handles any short outing, and it moves as they play. It never fires
    at conclusion time, which is why the FINAL s.v. is exactly what it was before.
    """
    totals = _per_match_player_totals([match.id])
    minutes = _minutes_map([match.id])
    exposure = defensive_exposure([match.id], minutes)
    gd_on = on_pitch_goal_difference([match.id], minutes)
    ga_on = on_pitch_goals_against([match.id], minutes)
    roles = current_role_map()
    keepers = dict(Player.objects.values_list("id", "is_goalkeeper"))
    names = dict(Player.objects.values_list("id", "short_name"))
    full = dict(Player.objects.values_list("id", "full_name"))
    # Decisive-event override for s.v.: a scorer/assist-man/sent-off (on the pitch)
    # player is rated even below the minutes/touches gate. A booking alone is not
    # such an event — the pagelle leave those cameos unrated too.
    forcing = rating_forcing_event_players(match.id)
    # Il credito per i GOL, che dal 29/08/2026 non e' piu' una feature dell'indice:
    # dipende da che cosa il gol ha cambiato, non dai minuti giocati (v.
    # services/goal_impact). Arriva gia' in punti di voto, quindi si somma al voto
    # grezzo e non all'indice; ``goal_mean`` e' la media di ruolo da sottrarre,
    # senza la quale questo termine — che e' solo positivo — alzerebbe la media di
    # ogni ruolo che segna invece di ridistribuire.
    assist_detail = goal_impact.assists_by_player(match)
    assist_band, _ = goal_impact.fixed_assist_band()
    assist_mean = goal_impact.role_mean_assist_credit()
    goal_credit_detail = goal_impact.goals_by_player(match)
    goal_band, goal_p95 = goal_impact.fixed_band()
    goal_credit = {
        pid: goal_impact.goal_credit(goal_impact.importances_of(recs),
                                     goal_band, goal_p95)
        for pid, recs in goal_credit_detail.items()}
    goal_mean = goal_impact.role_mean_credit()
    assist_credit = {pid: goal_impact.assist_credit(recs, assist_band, goal_p95)
                     for pid, recs in assist_detail.items()}
    # the DETAILS, not just the magnitudes: the explanation has to be able to say
    # which sending-off and which kind of own goal produced the drop it reports
    red_info = red_card_details(match.id)
    og_info = own_goal_details(match.id)
    red_adj = {pid: -d['penalty'] for pid, d in red_info.items()}
    og_adj = {pid: d['penalty'] for pid, d in og_info.items()}
    pen_adj = penalty_missed_adjustments(match.id)
    outfield_roles = (Player.ROLE_DEF, Player.ROLE_MID, Player.ROLE_FWD)
    always_rate = always_rate or set()

    results = []
    for (mid, pid), feats in totals.items():
        mins = minutes.get((mid, pid), 0)
        if mins <= 0:
            continue
        role, role_known = resolve_role(roles.get(pid) or "", feats,
                                        bool(keepers.get(pid)))
        exp = exposure.get((mid, pid), 0.0)
        idx = index_for_role(role, feats, mins, exp)
        # La parte fatta di FATTI, che il voto non attenua (v. UNSHRUNK_FEATURES).
        obs = observed_index(role, feats, mins, exp)
        # An inferred KEEPER still belongs in the keeper distribution — his own
        # features identified him. Only an unknown outfielder needs the pool.
        ref_key = role if role else POOLED_OUTFIELD
        # Rated if he played/was involved enough, OR was in a decisive event
        # (goal/assist/own goal/sending-off), OR won/conceded a penalty, OR the
        # caller says the gate does not apply to him yet (he is still on the pitch
        # of a match in progress — see ``always_rate``).
        rated = (is_rated(mins, feats) or pid in forcing or pid in always_rate
                 or feats.get("penalties_won", 0.0) > 0
                 or feats.get("penalties_conceded", 0.0) > 0)
        raw = _raw_vote_from_index(idx, ref_key, mins, reference, spread_k, obs)
        # I GOL, in punti di voto e PRIMA della mitigazione: sono merito, quindi
        # devono essere temperati dal risultato come tutto il resto — un gol in una
        # goleada subita non fa eccezione. Sommati al voto grezzo e non all'indice
        # perche' il loro valore non passa per lo shrinkage sui minuti, che e' il
        # motivo per cui sono usciti dall'indice.
        gadj = goal_credit.get(pid, 0.0) - goal_mean.get(ref_key, 0.0)
        aadj = assist_credit.get(pid, 0.0) - assist_mean.get(ref_key, 0.0)
        raw = max(VOTE_MIN, min(VOTE_MAX, raw + gadj + aadj))
        # Result mitigation: divergence-only, outfield only (the GK channel already
        # reflects the result). Recorded so the vote explanation can reconcile.
        nudge = (result_mitigation(raw, gd_on[(mid, pid)],
                                   centre=vote_center_for(ref_key))
                 if role in outfield_roles and (mid, pid) in gd_on else 0.0)
        # Red-card + own-goal + missed-penalty performance drops (post-adjustments,
        # any role; the missed penalty stays a good shot in the index, this is the
        # added drop for the miss — see penalty_missed_adjustments).
        # Le tre correzioni sono in punti di VOTO, ma qui siamo PRIMA dello stadio
        # finale, che riapre lo scostamento dal centro di un fattore ~1,6 sul
        # movimento (e di 1,0 sul portiere, che non ci passa). Dividerle per quel
        # fattore e' l'unico modo perche' "-0,40 per un autogol" voglia dire la
        # stessa cosa per un difensore e per un portiere, e perche' una ritaratura
        # della scala non le sposti tutte in silenzio. Sotto il centro la
        # saturazione e' l'identita', quindi il fattore e' esattamente questo.
        fattore_scala = (ROLE_SATURATION[ref_key][2]
                         if ref_key in ROLE_SATURATION else 1.0)
        radj = red_adj.get(pid, 0.0) / fattore_scala
        oadj = og_adj.get(pid, 0.0) / fattore_scala
        padj = pen_adj.get(pid, 0.0) / fattore_scala
        # Lo stadio finale della scala. Sta QUI, dopo ogni correzione, perche' e'
        # cosi' che e' stato tarato: comprime il voto COMPLETO, mitigazione inclusa.
        pieno = max(VOTE_MIN, min(VOTE_MAX, raw + nudge + radj + oadj + padj))
        # Il voto PRIMA dello stadio finale. Serve a ``flatten_minute_curves``, che
        # misura il residuo contro il giudice esterno: quel residuo va misurato dove
        # e' stato tarato, cioe' prima della saturazione. Misurarlo dopo produce una
        # curva diversa — e' l'errore che ha fatto fallire il primo test di
        # accettazione, con la produzione mezzo punto sopra il modello su un voto
        # ogni sette.
        pre_scala = pieno
        pieno, scala = scale_saturation(pieno, ref_key)
        voto = (_round_half(max(VOTE_MIN, min(VOTE_MAX, pieno)))
                if rated else None)
        results.append({
            "player_id": pid,
            "name": names.get(pid) or full.get(pid) or str(pid),
            "role": role,
            "role_known": role_known,
            "minutes": mins,
            "touches": round(feats.get("touches", 0.0), 1),
            "index": round(idx, 2),
            # La parte dell'indice fatta di FATTI, che il voto non attenua (v.
            # UNSHRUNK_FEATURES). Esposta accanto all'indice perche' senza di lei
            # la riga non basta a ricostruire il voto — e chi ci prova ottiene il
            # modello di prima senza accorgersene.
            "observed": round(obs, 4),
            "rated": rated,
            # DA QUI IN GIU', NIENTE ARROTONDAMENTI. Questi numeri non si mostrano
            # a nessuno: la spiegazione del voto li RIsomma per ricostruire il voto
            # che sta accanto al nome, nello stesso ordine in cui li ha sommati
            # questo ciclo. Troncarli al millesimo per fare ordine nel payload
            # spostava il grezzo di mezzo millesimo, e sul bordo della griglia dei
            # mezzi punti mezzo millesimo vale MEZZO VOTO — il pannello diceva 6.0
            # sotto un 6.5. Chi vuole vederli scritti corti li arrotondi dove li
            # stampa.
            #
            # Il credito dei gol, gia' centrato sulla media di ruolo. Esposto come
            # le altre correzioni post-indice perche' la SPIEGAZIONE deve poterlo
            # nominare: e' una voce che puo' valere mezzo voto e non compare in
            # nessuna feature dell'indice.
            "goal_adjustment": gadj,
            # I gol con lo stato che hanno cambiato: la spiegazione ne ricava la
            # frase, e il dettaglio tiro per tiro li ritrova per nome.
            "goal_detail": goal_credit_detail.get(pid, []),
            "assist_detail": assist_detail.get(pid, []),
            "assist_adjustment": aadj,
            "result_nudge": nudge,
            "red_adjustment": radj,
            "own_goal_adjustment": oadj,
            "red_detail": red_info.get(pid),
            "own_goal_detail": og_info.get(pid),
            "penalty_adjustment": padj,
            # Lo stadio finale, per la SPIEGAZIONE: ``scale_factor`` e' quanto e'
            # stato riscalato lo scostamento dal centro, ``scale_base`` il centro
            # nuovo. Senza questi due la scomposizione additiva non torna col voto.
            "voto_pre_scala": pre_scala,
            "scale_factor": scala,
            # La base che la SPIEGAZIONE deve usare. Non e' il centro nuovo del
            # ruolo: il voto grezzo parte da ``vote_center_for``, mentre lo stadio
            # finale comprime attorno a ``centro_pre``, che e' un altro punto. La
            # differenza fra i due, riscalata, e' una costante e va nella base —
            # se la si dimentica la scomposizione sballa di quella costante, ed e'
            # esattamente l'errore che avevo fatto la prima volta.
            "scale_base": (
                ROLE_SATURATION[ref_key][1]
                + scala * (vote_center_for(ref_key) - ROLE_SATURATION[ref_key][0])
                if ref_key in ROLE_SATURATION else vote_center_for(ref_key)),
            "voto_puro": voto,
        })
    results.sort(key=lambda d: (d["voto_puro"] is None, -(d["voto_puro"] or 0)))
    return results
