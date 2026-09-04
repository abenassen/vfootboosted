"""IL MODELLO DEL VOTO IN PRODUZIONE FINO AL 03/09/2026 — copia di sicurezza.

Non e' codice: e' l'archivio dei pesi e delle costanti *con le loro
motivazioni*, preso da classic_rating.py al commit a0a8bd1 subito prima della
ritaratura. Serve per due cose: capire perche' un peso valeva quello che
valeva, e poter tornare indietro sapendo a che cosa si torna.

Le motivazioni per riga qui sotto descrivono QUESTI valori. Nel file vivo
sono state riscritte sui valori nuovi.
"""

# ==========================================================================
# TOTAL_WEIGHTS
# ==========================================================================

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
    "expected_assists": 0.07,
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
    "sga_post": 0.06516,
    # = β: the mass of chances occupied. NON rialzato insieme a S, quindi β/S passa
    # da 1/3 a 1/4.5. E' una deroga consapevole al rapporto scritto sopra: β/S
    # esiste per l'ORDINAMENTO dei gol (un gol difficile deve battere un tap-in) e
    # quella proprieta' regge anche qui (gran gol +1.042 contro tap-in +0.870).
    # Tenendolo a 1/3 avremmo restituito un terzo della severita' appena comprata,
    # perche' questo peso paga l'essersi PROCURATI la posizione comunque sia finita.
    "xg_shots": 0.01454,
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
    "shots_on_target": 0.01557,
    "shots": 0.0176,              # shot ACTIVITY still rewarded, not penalised
    "shots_off": 0.00617,          # even an off-target attempt: small credit for shooting
    "errors_led_to_goal": -0.02124,  # una occorrenza: -0.91 -> -0.60 (era -0.0354)
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
    "penalties_conceded": -0.01618,  # una occorrenza: -0.455
    # Winning one is the mirror image and equally unrewarded: the bonus goes to
    # whoever converts, never to the player who earned it.
    "penalties_won": 0.01463,  # una occorrenza: +0.78 -> +0.51 (era 0.0244)
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
    "clearances_off_line": 0.00888,  # una occorrenza: +0.54 -> +0.30 (era 0.0175)
    "last_man_tackle": 0.0,
    # An error that let the opponent SHOOT, without a goal following.
    "errors_led_to_shot": -0.01131,  # una occorrenza: -0.26 -> -0.17 (era -0.0189)
    "shots_blocked": 0.00877,      # the defence intervened (x0.7 col blocco volume)
    # PROVIDER PROXY, and the only one in the model — read the note below before
    # touching it.
    "defensive_value": 0.085,
}

# ==========================================================================
# PER90_WEIGHTS
# ==========================================================================

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
    "dribbles_won": 0.0132,
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
    "duels_won": 0.04425,
    "duels_lost": -0.0631,          # the losing side of the contests we reward
    "dribbled_past": -0.0341,       # subset of duels_lost: beaten one-on-one is worse
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
    "passes_opp_half": 0.0548,      # progression: a pass in the opponent half is worth more
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
    "aerials_won": 0.01589,
    "aerials_lost": -0.0157,
    "tackles_won": 0.0107,          # a committed, deliberate intervention
    "was_fouled": 0.0117,           # an opponent had to stop you illegally
    "long_balls_completed": 0.0331,
    "crosses_completed": 0.0222,    # (reactivated by the hand-tuning)
    "touches_in_box": 0.0072,
    "interceptions": 0.026,
    "ball_recoveries": 0.01871,
    "blocks": 0.0116,
    "clearances": 0.0226,
    # passes_completed/touches held at 0.01: the earlier kurtosis-gradient nudge
    # (0.01 -> 0.02, with passes_opp_half 0.05 -> 0.06) flattened the distribution
    # toward Statistico's, but that low kurtosis is a symptom of Statistico being
    # result-driven, not a target — and the possession up-weight worked against
    # tempering high votes in defeats (Koopmeiners). Reverted; result-awareness is
    # instead carried by the (stronger) result mitigation below.
    "passes_completed": 0.0142,
    "touches": 0.0125,
    "errors_bad_passes": -0.0189,
    "errors_dispossessed": -0.0163,
    "errors_miscontrols": -0.019,
    "errors_fouls_committed": -0.0114,
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

# ==========================================================================
# ROLE_WEIGHTS
# ==========================================================================

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
    Player.ROLE_DEF: {"dribbled_past": -0.045, "duels_lost": -0.08519, "duels_won": 0.0210},
    Player.ROLE_MID: {"dribbled_past": 0.0, "duels_lost": -0.0631},
    Player.ROLE_FWD: {"dribbled_past": 0.0, "duels_lost": -0.02209},
}

# ==========================================================================
# GK_TOTAL_WEIGHTS
# ==========================================================================

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
    "gk_goals_prevented": 1.60,     # SIGNED: negative when he underperforms the xG faced
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
    "gk_penalty_saves": 0.0,
    "errors_led_to_goal": -0.60,    # the papera — see above
    "errors_led_to_shot": -0.102,
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

# ==========================================================================
# GK_PER90_WEIGHTS
# ==========================================================================

GK_PER90_WEIGHTS = {
    "gk_saves_inside_box": 0.4972,
    "gk_saves": 0.2712,
    "gk_high_claims": 0.1315,       # command of the area
    "gk_sweeper": 0.0848,           # sweeper-keeper interventions
    "gk_punches": 0.0528,
    "gk_crosses_not_claimed": -0.0535,
    "passes_completed": 0.0085,     # distribution, marginal
}

# ==========================================================================
# LE COSTANTI SCALARI
# ==========================================================================
COMPRESS_K = 3.0
UNSHRINK_GAMMA = 0.25
EXPOSURE_WEIGHT = 0.1594    # same unit as every other weight: index points per 1σ
VOTE_SPREAD_K = 0.727      # vote points per 1 std of within-role index
GK_SPREAD_K = 0.8
SHRINKAGE_MINUTES = 25
MINUTE_CONDITIONING = 0.75
ROLE_VOTE_CENTER = {Player.ROLE_DEF: 5.91, Player.ROLE_GK: 6.15}
