"""Il banco di prova dei pesi: valutare un modello intero in millisecondi.

PERCHE' ESISTE. Tarare il voto significa rispondere a una domanda — "se muovo
questo peso, che cosa succede ai casi che ho guardato in campo?" — e finora
rispondere costava tre minuti: ricalibrare la stagione, spedire il codice al
server, ripunteggiare venti partite. A quel prezzo si provano cinque idee al
giorno e si tara un peso alla volta, che e' esattamente come ci si e' arrivati
finora: a mano, e con i casi in equilibrio sul bordo dell'arrotondamento.

IL PEZZO CHE RENDE TUTTO POSSIBILE e' che l'indice e' LINEARE nei pesi:

    indice = somma su k di  peso[k] * z[k]

e le ``z`` — il valore della feature standardizzato sulla popolazione — non
dipendono dai pesi. Quindi la matrice delle z si calcola UNA VOLTA, e da li' in
poi provare un vettore di pesi e' un prodotto matrice-vettore. Tre minuti
diventano qualche millisecondo, e diventa possibile cercare invece che indovinare.

CHE COSA RICALCOLA, E COSA NO. Ricalibrare non e' un dettaglio: cambiare un peso
sposta anche la media e la sigma del ruolo contro cui l'indice viene z-scorato, e
un banco che le tenesse ferme misurerebbe un modello che non spediremmo mai (e'
successo davvero, il 01/09/2026: una misura senza ricalibrazione dava 13 bersagli
su 15, la stessa configurazione ricalibrata ne dava 10). Quindi qui dentro si
rifanno, a ogni valutazione:

  * media e sigma per ruolo (``build_reference``);
  * le curve per fascia di minuti, che sono medie dell'indice e quindi si muovono
    con lui.

NON si rifa' la banda d'impatto del gol, che e' l'unica approssimazione di questo
banco: dipende dai pesi (il suo bersaglio e' al netto del residuo di conclusioni
e volume) ma si muove poco — misurata su quattro configurazioni diverse del
01/09/2026, fra 0.3228 e 0.3395 sull'estremo basso, cioe' ~15 millesimi di voto
su un gol da mezzo punto. E' abbastanza per contare sui casi al bordo, e infatti
la regola e': la RICERCA gira con la banda ferma, ogni candidato che sopravvive
viene poi rivalutato per intero dalla pipeline vera. Il banco propone, la
pipeline dispone.

COME SI USA. ``Bench(season_id)`` costruisce tutto una volta; ``bench.voti(w)``
restituisce i voti per un vettore di pesi. ``bench.fedelta()`` e' la prima cosa
da chiamare e l'unica che non si puo' saltare: verifica che sui pesi di ADESSO il
banco riproduca voto per voto quello che produce ``voto_puro_for_match``. Se
diverge, il banco sta misurando qualcos'altro e va riparato prima di crederci.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np

from realdata.models import Match, Player
from vfoot.services import classic_rating as cr


# I pesi che il banco puo' muovere: quelli del canale di movimento. Il portiere ha
# un vettore suo e una sigma che questi non toccano (verificato il 01/09/2026: la
# ritaratura dei ruoli di movimento ha lasciato la sigma dei portieri a 2.0288
# contro 2.0295), quindi tenerlo fuori non e' una semplificazione ma la verita'.
def chiavi_mobili() -> list[str]:
    """Le feature del canale di movimento, in ordine stabile, ESPOSIZIONE COMPRESA.

    Ordine stabile e non "l'ordine del dizionario": il vettore dei pesi viaggia
    fra il banco, la ricerca e il rapporto, e un ordine che cambia fra due
    esecuzioni renderebbe i numeri incomparabili senza dirlo.

    L'esposizione non sta in ``WEIGHTS`` — nell'indice e' una riga a parte, con il
    segno meno scritto a mano — e la prima versione di questa funzione se l'e'
    persa. La prova di fedelta' l'ha vista subito, ed e' il motivo per cui quella
    prova esiste: la media del banco stava sopra a quella vera di 0.239 sui
    difensori, 0.171 sui centrocampisti e 0.140 sugli attaccanti, cioe' in ordine
    di quanto pericolo passa dalla loro zona. Un difetto che si annuncia col
    proprio nome, se qualcuno guarda.
    """
    return sorted((set(cr.WEIGHTS) | {cr.EXPOSURE_KEY}) - set(FUORI_DALL_INDICE))


class Bench:
    """La popolazione della stagione, ridotta a numeri che non dipendono dai pesi."""

    def __init__(self, season_id: int, *, verbose: bool = False):
        self.season_id = season_id
        self.scales = {"gk": cr.feature_scales(gk=True),
                       "outfield": cr.feature_scales(gk=False)}
        self.keys = chiavi_mobili()
        self.idx_of = {k: i for i, k in enumerate(self.keys)}

        # --- la popolazione di calibrazione (quella che definisce media e sigma)
        pop_role, pop_z, pop_min = [], [], []
        for key, role, feats, mins, exp in cr._reference_population(season_id, with_key=True):
            if role == Player.ROLE_GK:
                continue
            pop_role.append(role)
            pop_z.append(self._z_vector(role, feats, mins, exp))
            pop_min.append(mins)
        self.pop_role = np.array(pop_role)
        self.pop_z = np.array(pop_z, dtype=float)
        self.pop_min = np.array(pop_min, dtype=float)
        if verbose:
            print("banco: %d presenze di calibrazione, %d pesi mobili"
                  % (len(self.pop_z), len(self.keys)))

    # ------------------------------------------------------------------ z
    def _z_vector(self, role: str, feats: dict, mins: int, exp: float) -> np.ndarray:
        """Il vettore delle z di una presenza, nell'ordine di ``self.keys``.

        E' la stessa trasformazione che applica ``index_for_role`` — ``scored_z``,
        non ``_feature_z`` — perche' su alcune feature l'indice applica un credito
        (v. CREDITED_FEATURES) e una z grezza non tornerebbe col voto.

        L'ESPOSIZIONE ENTRA COL SEGNO GIA' GIRATO. Nell'indice vero e' sottratta
        (``idx -= EXPOSURE_WEIGHT * ...``) invece che sommata come tutte le altre;
        qui si mette il suo z negato, cosi' il prodotto scalare resta una somma
        sola e il peso dell'esposizione si muove come gli altri.
        """
        chan = self.scales["outfield"]
        values = cr.raw_feature_values(feats, mins, exp, gk=False)
        pesi_ruolo = cr.weights_for_role(role)
        v = np.zeros(len(self.keys))
        for k in self.keys:
            if k not in pesi_ruolo:
                continue
            v[self.idx_of[k]] = cr.scored_z(k, values.get(k, 0.0), chan)
        if cr.EXPOSURE_KEY in self.idx_of:
            v[self.idx_of[cr.EXPOSURE_KEY]] = -cr.exposure_z(
                values.get(cr.EXPOSURE_KEY, 0.0), chan)
        return v

    def vettore_pesi(self, role: str) -> np.ndarray:
        """I pesi di ADESSO per questo ruolo, come vettore.

        Per ruolo e non uno solo: ``ROLE_WEIGHTS`` da' a difensori, centrocampisti
        e attaccanti valori diversi su tre feature (i duelli persi, i duelli vinti
        del difensore, il dribbling concesso), e appiattirli su un vettore unico
        cancellerebbe proprio le decisioni prese con piu' cura.
        """
        pesi = cr.weights_for_role(role)
        w = np.zeros(len(self.keys))
        for k, val in pesi.items():
            if k in self.idx_of:
                w[self.idx_of[k]] = val
        if cr.EXPOSURE_KEY in self.idx_of:
            w[self.idx_of[cr.EXPOSURE_KEY]] = cr.EXPOSURE_WEIGHT
        return w

    # ----------------------------------------------------------- indice e riferimento
    def indici(self, W: dict[str, np.ndarray]) -> np.ndarray:
        """L'indice di ogni presenza della popolazione, per un dizionario di
        vettori-peso {ruolo: vettore}."""
        out = np.empty(len(self.pop_z))
        for role in ("DIF", "CEN", "ATT"):
            m = self.pop_role == role
            if m.any():
                out[m] = self.pop_z[m] @ W[role]
        return out

    def riferimento(self, W) -> dict:
        """media e sigma per ruolo — la stessa cosa che fa ``build_reference``,
        compresa la sigma MESSA IN COMUNE fra i ruoli di movimento quando
        ``POOLED_ROLE_SPREAD`` e' acceso (e lo e')."""
        idx = self.indici(W)
        ref = {}
        for role in ("DIF", "CEN", "ATT"):
            m = self.pop_role == role
            vals = idx[m]
            ref[role] = {"mean": float(vals.mean()), "std": float(vals.std()) or 1.0,
                         "n": int(m.sum())}
        if cr.POOLED_ROLE_SPREAD:
            scarti = np.concatenate([idx[self.pop_role == r] - ref[r]["mean"]
                                     for r in ("DIF", "CEN", "ATT")])
            comune = float(scarti.std()) or 1.0
            for r in ("DIF", "CEN", "ATT"):
                ref[r]["std"] = comune
        return ref, idx

    # ------------------------------------------------------- curve dei minuti
    def _popola_valutate(self):
        """La seconda popolazione: TUTTE le presenze valutate, non solo quelle di
        calibrazione.

        Serve alle curve per fascia di minuti, che descrivono proprio la fascia che
        la popolazione di riferimento taglia via (sotto ``MIN_MINUTES_REFERENCE``).
        Porta due vettori: l'indice intero e la sola parte dei FATTI
        (``UNSHRUNK_FEATURES``), che il voto scorpora dall'attenuazione sui minuti.
        """
        mids = list(Match.objects.filter(competition_season_id=self.season_id)
                    .values_list("id", flat=True))
        totals = cr._per_match_player_totals(mids)
        minutes = cr._minutes_map(mids)
        exposure = cr.defensive_exposure(mids, minutes)
        roles = cr.current_role_map()
        maschera_oss = np.array([1.0 if k in cr.UNSHRUNK_FEATURES else 0.0
                                 for k in self.keys])
        chiavi, ruoli, zz, mm = [], [], [], []
        for (mid, pid), feats in totals.items():
            role = roles.get(pid)
            if role is None or role == Player.ROLE_GK:
                continue
            mins = minutes.get((mid, pid), 0)
            if not mins or not cr.is_rated(mins, feats):
                continue
            chiavi.append((mid, pid)); ruoli.append(role); mm.append(mins)
            zz.append(self._z_vector(role, feats, mins, exposure.get((mid, pid), 0.0)))
        self.val_key = chiavi
        self.val_role = np.array(ruoli)
        self.val_z = np.array(zz, dtype=float)
        self.val_min = np.array(mm, dtype=float)
        self.maschera_oss = maschera_oss
        # LE FINESTRE, precalcolate: per ogni ruolo e ogni minuto della curva, quali
        # righe della popolazione ci cadono dentro. Non dipendono dai pesi, quindi
        # si calcolano una volta e la curva diventa una media su indici gia' noti.
        self.finestre = {r: {} for r in ("DIF", "CEN", "ATT")}
        per_ruolo = defaultdict(list)
        for i, r in enumerate(ruoli):
            per_ruolo[r].append(i)
        for r, righe in per_ruolo.items():
            if r not in self.finestre:
                continue
            minuti = self.val_min[righe]
            for m in range(1, 130):
                dentro = [righe[j] for j in np.nonzero(
                    np.abs(minuti - m) <= cr.MINUTE_CURVE_WINDOW)[0]]
                if dentro:
                    self.finestre[r][m] = np.array(dentro)
        self.sopra_soglia = {
            r: np.array([i for i in per_ruolo.get(r, [])
                         if self.val_min[i] >= cr.MIN_MINUTES_REFERENCE], dtype=int)
            for r in ("DIF", "CEN", "ATT")}

    def curve(self, W, ref) -> None:
        """Attacca a ``ref`` le due curve, come fa ``build_minute_curves``.

        Le medie di RUOLO restano quelle della reference (spostarle muoverebbe ogni
        voto): qui si aggiunge solo il profilo per minutaggio.
        """
        idx = np.empty(len(self.val_z)); oss = np.empty(len(self.val_z))
        for role in ("DIF", "CEN", "ATT"):
            m = self.val_role == role
            if not m.any():
                continue
            idx[m] = self.val_z[m] @ W[role]
            oss[m] = self.val_z[m] @ (W[role] * self.maschera_oss)
        for role in ("DIF", "CEN", "ATT"):
            # FINESTRA SCORREVOLE, non media per minuto esatto: il vero
            # ``build_minute_curves`` mette insieme tutti i minutaggi entro
            # MINUTE_CURVE_WINDOW e tiene il punto solo se ci sono almeno
            # MINUTE_CURVE_MIN_N presenze. Le chiavi sono STRINGHE, come li'.
            by, oby = {}, {}
            for m in range(1, 130):
                righe = self.finestre[role].get(m)
                if righe is None or len(righe) < cr.MINUTE_CURVE_MIN_N:
                    continue
                by[str(m)] = float(idx[righe].mean())
                oby[str(m)] = float(oss[righe].mean())
            ref[role]["by_minute"] = by
            ref[role]["observed_by_minute"] = oby
            sopra = self.sopra_soglia[role]
            ref[role]["observed_mean"] = float(oss[sopra].mean()) if len(sopra) else 0.0

    # ------------------------------------------------------------- i bersagli
    def carica_calibrazione(self, verbose: bool = False) -> None:
        """Le presenze della stagione CHIUSA, punteggiabili.

        DUE POPOLAZIONI, DUE MESTIERI, e confonderle e' l'errore che ho gia' fatto
        due volte oggi. Questa — la stagione con le pagelle — serve a misurare
        l'accordo coi giudici e a tarare l'appiattimento della curva dei minuti.
        L'altra (``carica_bersagli_da_file``) e' la stagione IN CORSO, e serve solo
        a valutare le osservazioni di campo. Indicizzare i giudici sulla seconda
        da' un campione vuoto e una correlazione che non misura niente: il
        pavimento sembra esserci e non c'e'.

        Con TUTTO cio' che non dipende dai pesi.

        Il credito dei gol e degli assist, il rosso, l'autogol, il rigore
        sbagliato, la differenza reti mentre era in campo: sono costanti rispetto ai
        pesi (il credito del gol passa per la banda d'impatto, che il banco tiene
        ferma — v. l'intestazione). Si prendono UNA VOLTA facendo girare la
        pipeline vera, invece di riscriverne il calcolo: cosi' il banco non puo'
        divergere su questi termini, perche' non li ricalcola affatto.
        """
        from vfoot.services.classic_rating import voto_puro_for_match
        from vfoot.services.classic_pagella import get_reference
        ref = get_reference(self.season_id)
        righe = {}
        for match in Match.objects.filter(competition_season_id=self.season_id):
            for row in voto_puro_for_match(match, ref):
                if not row.get("rated") or row.get("role") == Player.ROLE_GK:
                    continue
                righe[(match.id, row["player_id"])] = row
        chiavi, ruoli, zz, mm, extra = [], [], [], [], []
        mids = [m.id for m in Match.objects.filter(competition_season_id=self.season_id)]
        totals = cr._per_match_player_totals(mids)
        minutes = cr._minutes_map(mids)
        exposure = cr.defensive_exposure(mids, minutes)
        # La differenza reti mentre era in campo: la riga non la porta (porta gia'
        # la mitigazione calcolata), ma il banco deve RIcalcolarla, perche' la
        # mitigazione dipende dal voto grezzo e quindi dai pesi.
        gd_on = cr.on_pitch_goal_difference(mids, minutes)
        for (mid, pid), row in righe.items():
            feats = totals.get((mid, pid))
            if feats is None:
                continue
            mins = minutes.get((mid, pid), 0)
            role = row["role"]
            chiavi.append((mid, pid)); ruoli.append(role); mm.append(mins)
            zz.append(self._z_vector(role, feats, mins, exposure.get((mid, pid), 0.0)))
            extra.append((row.get("goal_adjustment", 0.0) + row.get("assist_adjustment", 0.0),
                          row.get("red_adjustment", 0.0) + row.get("own_goal_adjustment", 0.0)
                          + row.get("penalty_adjustment", 0.0),
                          gd_on.get((mid, pid)), row.get("voto_puro"), None))
        self.cal_key = chiavi
        self.cal_role = np.array(ruoli)
        self.cal_z = np.array(zz, dtype=float)
        self.cal_min = np.array(mm, dtype=float)
        self.cal_extra = extra
        self.cal_idx = {k: i for i, k in enumerate(chiavi)}
        if verbose:
            print("calibrazione: %d presenze di movimento" % len(chiavi))

    def voti(self, W, ref=None, quale: str = "cal", banda=None) -> dict:
        """{(match, player): voto grezzo} per un vettore di pesi.

        Ricalibra (media, sigma, curve) e poi rifa' il voto con la stessa formula
        di ``_raw_vote_from_index``: attenuazione sui minuti, fatti osservati non
        attenuati, credito dei gol, mitigazione del risultato, cartellini.
        """
        if ref is None:
            ref, _ = self.riferimento(W)
            self.curve(W, ref)
        chiavi = self.cal_key if quale == "cal" else self.ber_key
        ruoli = self.cal_role if quale == "cal" else self.ber_role
        Z = self.cal_z if quale == "cal" else self.ber_z
        MIN = self.cal_min if quale == "cal" else self.ber_min
        EXTRA = self.cal_extra if quale == "cal" else self.ber_extra
        # Il credito di gol e assist: dalla BANDA se ce l'abbiamo (e' un parametro
        # da ottimizzare), altrimenti quello congelato dall'export.
        cred = credito(self, quale, banda) if banda is not None else None
        out = {}
        for role in ("DIF", "CEN", "ATT"):
            m = np.nonzero(ruoli == role)[0]
            if not len(m):
                continue
            w = W[role]
            idx = Z[m] @ w
            oss = Z[m] @ (w * self.maschera_oss)
            for j, i in enumerate(m):
                mins = int(MIN[i])
                raw = cr._raw_vote_from_index(float(idx[j]), role, mins, ref,
                                              observed=float(oss[j]))
                gadj, adj, gd_on, _v, _r = EXTRA[i]
                if cred is not None:
                    gadj = float(cred[i])
                raw = max(cr.VOTE_MIN, min(cr.VOTE_MAX, raw + gadj))
                if gd_on is not None:
                    raw += cr.result_mitigation(raw, gd_on,
                                                centre=cr.vote_center_for(role))
                raw = max(cr.VOTE_MIN, min(cr.VOTE_MAX, raw + adj))
                out[chiavi[i]] = raw
        return out

    def carica_bersagli_da_file(self, percorso: str, verbose: bool = False) -> None:
        """I bersagli da un'altra stagione, esportata dove i suoi dati esistono.

        LA CALIBRAZIONE E I BERSAGLI STANNO SU DUE STAGIONI DIVERSE, ed e' la
        forma giusta, non un ripiego: la produzione fa esattamente cosi'. Media,
        sigma, curve e giudici vengono dalla stagione CHIUSA — e' li' che ci sono
        le pagelle — mentre le osservazioni di campo sono sulla stagione IN CORSO,
        che in locale non esiste (quella e' simulata: 220 partite "finite" fino a
        gennaio) e vive solo in produzione.

        Il primo tentativo teneva una stagione sola e gli otto vincoli sulla 26-27
        non si agganciavano; peggio, i sette che si agganciavano trovavano un
        omonimo nella 25-26 e la ricerca lavorava diligentemente su partite che
        non c'entravano niente. Da qui la regola: un vincolo che non trova la sua
        presenza e' un ERRORE, non un avviso (v. ``aggancia``).
        """
        import json
        righe = json.load(open(percorso))
        chiavi, ruoli, zz, mm, extra, nomi = [], [], [], [], [], {}
        for r in righe:
            role = r["ruolo"]
            if role not in ("DIF", "CEN", "ATT"):
                continue
            k = (r["mid"], r["pid"])
            chiavi.append(k); ruoli.append(role); mm.append(r["minuti"])
            zz.append(self._z_vector(role, r["totali"], r["minuti"], r["esposizione"]))
            extra.append((r["gol"] + r["assist"], r["altri"], r["gd_on"],
                          r["voto_prod"], None))
            nomi[k] = (r["nome"], r["gd"])
        self.ber_key = chiavi
        self.ber_role = np.array(ruoli)
        self.ber_z = np.array(zz, dtype=float)
        self.ber_min = np.array(mm, dtype=float)
        self.ber_extra = extra
        self.ber_idx = {k: i for i, k in enumerate(chiavi)}
        self.ber_nomi = nomi
        if verbose:
            print("bersagli da file: %d presenze" % len(chiavi))

    def aggancia(self, frammento: str, giornata: int):
        """La presenza di un vincolo, o un'eccezione.

        Solleva se non trova, e solleva anche se trova PIU' DI UNO: due giocatori
        con lo stesso cognome nella stessa giornata sono un vincolo ambiguo, e
        sceglierne uno a caso e' il modo in cui una ricerca lavora per un'ora sulla
        partita sbagliata senza che nessuno se ne accorga."""
        import unicodedata

        def norm(s):
            return ''.join(c for c in unicodedata.normalize('NFD', s)
                           if unicodedata.category(c) != 'Mn').lower()

        f = norm(frammento)
        trovati = [k for k, (nome, gd) in self.ber_nomi.items()
                   if gd == giornata and f in norm(nome)]
        if not trovati:
            raise LookupError("vincolo non agganciato: '%s' alla giornata %d"
                              % (frammento, giornata))
        if len(trovati) > 1:
            raise LookupError("vincolo ambiguo: '%s' alla giornata %d trova %s"
                              % (frammento, giornata,
                                 [self.ber_nomi[k][0] for k in trovati]))
        return trovati[0]





# --- IL CRUSCOTTO: che cosa e' cambiato, in unita' che una persona puo' giudicare
#
# NASCE DA UN DIFETTO VERO, e va tenuto in testa a qualunque ricerca automatica.
# Il 01/09/2026 la ritaratura del voto ha gonfiato del 52% ogni evento raro — un
# rigore concesso e' arrivato a costare -1.29, piu' di quanto renda qualunque gol —
# e NON CE NE SIAMO ACCORTI. Tutte le misure aggregate erano verdi: l'accordo coi
# tre giudici migliorava, i bersagli tenevano, la suite passava. Se n'e' accorto
# l'utente guardando il pannello di un giocatore, dopo il rilascio.
#
# La lezione non e' "serviva un test in piu'" (quello c'e' ora, v.
# tests_rare_events.py): e' che un ottimizzatore che massimizza un punteggio
# aggregato ripeterebbe lo stesso errore molto piu' in fretta, e su piu' pesi
# insieme. Quindi le grandezze qui sotto — quelle che hanno un significato FUORI
# dall'indice, e che percio' si possono giudicare a occhio — non sono un rapporto
# da leggere dopo: sono un VINCOLO come gli altri, e un candidato che le sposta
# fuori banda va scartato anche se tutto il resto migliora.
def cruscotto(bench, W, ref=None) -> dict:
    """{nome: valore} delle grandezze leggibili da un essere umano.

    Non sono pesi: sono le domande a cui un peso risponde. "Quanto vale un rigore
    concesso" ha una risposta discutibile a cena; "quanto vale 0.0303 di
    penalties_conceded" non ce l'ha.
    """
    if ref is None:
        ref, _ = bench.riferimento(W)
    scales = bench.scales["outfield"]
    std = ref["DIF"]["std"]
    kk = cr.spread_k_for("DIF")
    out = {}
    for k in ("clearances_off_line", "penalties_won", "penalties_conceded",
              "errors_led_to_goal", "errors_led_to_shot"):
        sig = (scales.get(k) or {}).get("sigma_raw") or 0.0
        i = bench.idx_of.get(k)
        if sig and i is not None:
            out["1 " + k] = float(W["DIF"][i]) / sig * kk / std
    from vfoot.services.goal_impact import fixed_band
    (lo, hi), _ = fixed_band()
    out["1 gol (da/a)"] = (lo, hi)
    out["sigma dei ruoli"] = std
    return out


# ==============================================================================
# I VINCOLI — uno solo, di tante forme
# ==============================================================================
# Il salto di qualita' del disegno, e viene da un'osservazione dell'utente: le
# grandezze in unita' umane (quanto vale un rigore concesso), le soglie sui singoli
# voti, gli ordinamenti fra compagni e l'accordo coi giudici NON sono quattro
# meccanismi diversi. Sono tutti la stessa cosa: **una quantita', un bersaglio, un
# margine**. Espressi cosi', l'algoritmo non ha bisogno di sapere di che tipo sono,
# e aggiungere un'osservazione calcistica nuova costa una riga invece di un ramo.
#
# Ed e' la differenza fra un sistema che risolve i quindici casi di oggi e uno che
# regge i sessanta di fra sei mesi. La taratura non finisce: ogni giornata guardata
# in campo produce vincoli nuovi, e quello che deve restare costante e' il modo di
# scriverli.
#
# ``scarto`` positivo = soddisfatto, e di quanto; negativo = violato, e di quanto.
# E' l'unica cosa che l'ottimizzatore guarda.

class Vincolo:
    tipo = "?"
    # QUANTO PESA questo vincolo nella funzione, e non e' un dettaglio di taratura.
    # Con un peso solo per tutti, il termine dei giudici (che somma su 10.583
    # pagelle) schiaccia quello dei casi di campo: misurato il 01/09/2026, 0.849
    # contro 0.278, e l'ottimizzatore ha giustamente ignorato le osservazioni.
    # Il peso per vincolo e' anche il modo di dire che cosa e' NEGOZIABILE: le
    # osservazioni di campo si contraddicono a vicenda e un compromesso fra loro ha
    # senso, gli invarianti no — "un rigore concesso vale meno di un gol" non e' un
    # giudizio da bilanciare, e' la condizione perche' il voto significhi qualcosa.
    # Se la si puo' vendere per due centesimi di correlazione, la si vendera'.
    peso = 1.0

    def __init__(self, nome: str, margine: float = 0.05):
        self.nome, self.margine = nome, margine

    def scarto(self, ctx) -> float:
        raise NotImplementedError


class Ordine(Vincolo):
    """«A sta sotto B, nella stessa partita.»

    La forma da preferire, e il motivo e' misurato: le soglie sul voto singolo si
    ribaltano quando il grezzo si sposta di un centesimo (tre dei quindici bersagli
    del 01/09/2026 stavano a 0.01-0.03 dal bordo dell'arrotondamento). Un
    ordinamento non ha bordi: confronta due numeri continui, e resta vero comunque
    cada la griglia dei mezzi punti.
    """
    tipo = "ordine"

    def __init__(self, nome, sotto, sopra, margine=0.05):
        super().__init__(nome, margine)
        self.sotto, self.sopra = sotto, sopra

    def scarto(self, ctx):
        v = ctx["voti"]
        if self.sotto not in v or self.sopra not in v:
            return 0.0
        return (v[self.sopra] - v[self.sotto]) - self.margine


class Soglia(Vincolo):
    """«Il voto di X sta sotto (o sopra) questo numero.»

    Si valuta sul GREZZO e non sul voto arrotondato, con un margine: altrimenti
    l'ottimizzatore impara a fermarsi a un millesimo dalla soglia, che e' vincere
    la misura senza vincere niente.
    """
    tipo = "soglia"

    def __init__(self, nome, chiave, verso, valore, margine=0.05):
        super().__init__(nome, margine)
        self.chiave, self.verso, self.valore = chiave, verso, valore

    def scarto(self, ctx):
        v = ctx["voti"].get(self.chiave)
        if v is None:
            return 0.0
        return (self.valore - v - self.margine if self.verso == "<="
                else v - self.valore - self.margine)


class Invariante(Vincolo):
    """«Una occorrenza di questo evento vale tanto, piu' o meno tanto.»

    Le grandezze che si possono giudicare a occhio, e che percio' sono l'unica
    difesa contro un ottimizzatore che migliora ogni media peggiorando il calcio.
    Il 01/09/2026 il gonfiaggio degli eventi rari (x1.52) ha attraversato indenne
    l'accordo coi tre giudici, i bersagli e la suite: nessuna misura aggregata lo
    vedeva, perche' non era un errore di media, era un errore di significato.
    """
    tipo = "invariante"
    peso = 500.0   # NON negoziabile: v. il commento su Vincolo.peso

    def __init__(self, nome, quantita, atteso, tolleranza):
        super().__init__(nome, 0.0)
        self.quantita, self.atteso, self.tolleranza = quantita, atteso, tolleranza

    def scarto(self, ctx):
        v = ctx["cruscotto"].get(self.quantita)
        if v is None:
            return 0.0
        return self.tolleranza - abs(v - self.atteso)


class Giudice(Vincolo):
    """«L'accordo con questo giudice non scende sotto quello di adesso.»

    Il pavimento, e la ragione per cui la ricerca non puo' allontanarsi dal calcio
    inseguendo quindici casi: dietro c'e' un giudizio indipendente su diecimila
    presenze. Come dice l'utente: e' quello che garantisce di non divergere troppo.
    """
    tipo = "giudice"

    def __init__(self, nome, chiave, minimo, margine=0.0):
        super().__init__(nome, margine)
        self.chiave, self.minimo = chiave, minimo

    def scarto(self, ctx):
        v = ctx["giudici"].get(self.chiave)
        return 0.0 if v is None else v - self.minimo - self.margine


def carica_giudici(bench, percorso: str) -> None:
    """Aggancia al banco i voti esterni: le due pagelle e il rating SofaScore.

    Il file e' quello che la sessione di taratura produce gia' (``join.json``):
    ``{"ext": {"<giornata>:<player_id>": {"Fantacalcio": v, "Statistico": v}},
    "stats": {"<giornata>:<player_id>": {"rating": v, "mins": n}}}``.

    SI CONFRONTA SOLO CHI HA GIOCATO ALMENO 60 MINUTI, come ogni misura d'accordo
    di questo progetto: sotto quella soglia le pagelle smettono di giudicare e
    cominciano a non sbilanciarsi, e la correlazione misurerebbe la loro prudenza.
    """
    import json
    d = json.load(open(percorso))
    gd_of = dict(Match.objects.filter(competition_season_id=bench.season_id)
                 .values_list("id", "matchday"))
    bench.giud_righe = {"Redazione": [], "Statistico": [], "SofaScore": []}
    for i, (mid, pid) in enumerate(bench.cal_key):
        k = "%s:%s" % (gd_of.get(mid), pid)
        st = (d["stats"] or {}).get(k) or {}
        if (st.get("mins") or 0) < 60:
            continue
        e = (d["ext"] or {}).get(k) or {}
        if e.get("Fantacalcio") is not None:
            bench.giud_righe["Redazione"].append((i, e["Fantacalcio"]))
        if e.get("Statistico") is not None:
            bench.giud_righe["Statistico"].append((i, e["Statistico"]))
        if st.get("rating"):
            bench.giud_righe["SofaScore"].append((i, st["rating"]))
    for nome, righe in bench.giud_righe.items():
        bench.giud_righe[nome] = (np.array([r[0] for r in righe]),
                                  np.array([r[1] for r in righe], dtype=float))


def accordo(bench, voti_arr: np.ndarray) -> dict:
    """La correlazione con ognuno dei tre giudici, sui voti GREZZI.

    Sui grezzi e non sugli arrotondati: la griglia dei mezzi punti aggiunge rumore
    che non appartiene al modello, e nella ricerca quel rumore diventerebbe un
    gradino su cui l'ottimizzatore inciampa."""
    out = {}
    for nome, (idx, ext) in bench.giud_righe.items():
        if not len(idx):
            continue
        x = voti_arr[idx]
        out[nome] = float(np.corrcoef(x, ext)[0, 1])
    return out


def contesto(bench, W) -> dict:
    """Tutto quello che i vincoli possono guardare, per un vettore di pesi."""
    ref, _ = bench.riferimento(W)
    bench.curve(W, ref)
    # ``contesto`` non riceve theta: usa il credito congelato dell'export.
    primo = bench.voti(W, ref, "cal")
    appiattisci(bench, W, ref,
                np.array([primo.get(k, 6.0) for k in bench.cal_key]))
    voti_cal = bench.voti(W, ref, "cal")
    arr_cal = np.array([voti_cal.get(k, 6.0) for k in bench.cal_key])
    return {"voti": bench.voti(W, ref, "ber"), "arr": arr_cal, "ref": ref,
            "giudici": accordo(bench, arr_cal),
            "cruscotto": cruscotto(bench, W, ref)}


def perdita(bench, W, vincoli, W0, lam: float = 1.0) -> tuple:
    """La funzione da minimizzare, e il contesto che l'ha prodotta.

    Due termini, e l'ordine conta:

      * i VINCOLI VIOLATI, al quadrato e con un peso grosso. Non "quanti ne
        centro" — che premierebbe fermarsi a un millesimo dal bordo — ma quanto
        manca a ciascuno, cosi' la direzione dello spostamento e' informativa
        anche quando nessuno e' ancora soddisfatto.
      * il CAMBIAMENTO, ‖w − w0‖ sui pesi normalizzati dalla loro taglia. E' il
        "muovere di poco" chiesto dall'utente, ed e' anche cio' che rende il
        problema ben posto: le direzioni che soddisfano i vincoli sono tante e
        quasi tutte assurde, questa sceglie la piu' vicina a quella che gia' c'e'.
    """
    ctx = contesto(bench, W)
    viol = 0.0
    for v in vincoli:
        s = v.scarto(ctx)
        if s < 0:
            viol += s * s
    cambio = 0.0
    for r in ("DIF", "CEN", "ATT"):
        base = np.where(np.abs(W0[r]) > 1e-9, np.abs(W0[r]), 1e-3)
        cambio += float(np.sum(((W[r] - W0[r]) / base) ** 2))
    return 100.0 * viol + lam * cambio / 3.0, ctx


def carica_residui_esterni(bench, percorso: str, giudice: str = "Fantacalcio") -> None:
    """I voti del giudice su cui si TARA la curva dei minuti, senza filtro di minuti.

    Diverso da ``carica_giudici``, e la differenza conta: li' si misura l'accordo e
    si guarda solo chi ha giocato almeno un'ora, qui si corregge la curva proprio
    nella fascia degli spezzoni. Filtrare a 60 minuti vorrebbe dire tarare la curva
    dei minuti su chi i minuti li ha fatti tutti.
    """
    import json
    d = json.load(open(percorso))
    gd_of = dict(Match.objects.filter(competition_season_id=bench.season_id)
                 .values_list("id", "matchday"))
    bench.res_idx, bench.res_ext = [], []
    for i, (mid, pid) in enumerate(bench.cal_key):
        v = ((d["ext"] or {}).get("%s:%s" % (gd_of.get(mid), pid)) or {}).get(giudice)
        if v is not None:
            bench.res_idx.append(i); bench.res_ext.append(v)
    bench.res_idx = np.array(bench.res_idx, dtype=int)
    bench.res_ext = np.array(bench.res_ext, dtype=float)


def appiattisci(bench, W, ref, voti_arr) -> dict:
    """Riproduce ``flatten_minute_curves``: corregge ``by_minute`` col residuo.

    Il residuo si misura sul voto ARROTONDATO, come fa l'originale — e non e' una
    svista da migliorare qui: se il banco usasse il grezzo starebbe tarando una
    curva diversa da quella che la calibrazione vera produce, che e' l'unico modo
    di sbagliare che questo file non si puo' permettere.
    """
    if not len(getattr(bench, "res_idx", ())):
        return {}
    minuti = bench.cal_min[bench.res_idx]
    scarti = np.array([cr._round_half(v) for v in voti_arr[bench.res_idx]]) - bench.res_ext
    residuo = {}
    for minute in range(1, 100):
        m = np.abs(minuti - minute) <= cr.MINUTE_CURVE_WINDOW
        if int(m.sum()) >= cr.MINUTE_CURVE_MIN_N:
            residuo[minute] = float(scarti[m].mean())
    for role in ("DIF", "CEN", "ATT"):
        r = ref[role]
        curva = dict(r.get("by_minute") or {})
        for minute, scarto in residuo.items():
            w = minute / (minute + cr.shrinkage_for(role))
            cond = cr.minute_conditioning_for(role)
            if w <= 0 or not cond:
                continue
            curva[str(minute)] = curva.get(str(minute), 0.0) + (
                scarto * r["std"] / (cr.spread_k_for(role) * w * cond))
        r["by_minute"] = curva
    return residuo


# ==============================================================================
# LA RICERCA — la direzione la dicono i vincoli, la strada la sceglie il minimo
# ==============================================================================
# NON e' una ricerca alla cieca, ed e' la differenza che l'utente ha chiesto: le
# osservazioni puntuali non sono un punteggio da massimizzare a tentativi, sono
# EVIDENZA SULLA DIREZIONE dello spostamento. Quindi si misura quella direzione
# invece di indovinarla:
#
#   1. si calcola come ogni vincolo risponde a ogni peso (la matrice J, per
#      differenze finite: 51 valutazioni da 67 ms, cioe' tre secondi e mezzo);
#   2. si risolve il passo PIU' CORTO che porta i vincoli violati dentro
#      (minimi quadrati con insieme attivo: fra le infinite direzioni che
#      risolvono, quella che muove meno);
#   3. si rivaluta per davvero — perche' il modello non e' lineare — e si ripete.
#
# Il termine di minimo cambiamento non e' cosmesi. Con 51 pesi e una ventina di
# vincoli il sistema e' enormemente sotto-determinato: le soluzioni sono infinite
# e quasi tutte sono assurdita' calcistiche. La regolarizzazione e' cio' che rende
# il problema ben posto, insieme al pavimento sui giudici — che e' l'unica cosa che
# tiene la ricerca ancorata a diecimila partite invece che a quindici casi.

CHIAVI_RUOLO = ("dribbled_past", "duels_lost", "duels_won")


def parametri(bench, W) -> np.ndarray:
    """Il vettore da ottimizzare: i pesi condivisi, piu' i tre per ruolo.

    Non 3x42 pesi indipendenti: i ruoli di movimento condividono un vettore solo
    per scelta di modello (v. ROLE_WEIGHTS), e lasciarli sciogliere qui vorrebbe
    dire far decidere all'ottimizzatore una cosa che abbiamo deciso noi."""
    theta = list(W["DIF"])
    for k in CHIAVI_RUOLO:
        i = bench.idx_of.get(k)
        if i is not None:
            theta += [W[r][i] for r in ("DIF", "CEN", "ATT")]
    if hasattr(bench, "banda0"):
        theta += list(bench.banda0)
    return np.array(theta, dtype=float)


# Le quattro code del vettore: lo/hi del gol, lo/hi dell'assist. Stanno IN FONDO
# cosi' la parte dei pesi conserva la sua numerazione e i vettori vecchi si
# riconoscono dalla lunghezza invece di allinearsi male in silenzio.
N_BANDA = 4


def lunghezza_attesa(bench) -> int:
    """Quanti parametri deve avere theta per QUESTO banco."""
    return (len(bench.keys) + 3 * sum(1 for k in CHIAVI_RUOLO if k in bench.idx_of)
            + (N_BANDA if hasattr(bench, "banda0") else 0))


def banda_da_parametri(bench, theta):
    """La banda del gol e dell'assist, se il banco le porta."""
    return theta[-N_BANDA:] if hasattr(bench, "banda0") else None


def proietta(bench, theta, theta0):
    """Riporta dentro i confini un vettore che l'ottimizzatore ha proposto.

    NIENTE CAMBI DI SEGNO: un peso che cambia segno e' un'affermazione calcistica
    («vincere un duello aereo fa male»), non una taratura, e l'ottimizzatore la
    produce appena due feature sono ridondanti — misurato il 01/09/2026 sulla
    coppia dei duelli aerei, che correla 0.66 con i duelli generici. Un peso puo'
    andare a ZERO, che vuol dire "questa cosa non conta"; non puo' attraversarlo.

    E la banda resta ordinata e positiva: ``lo <= hi`` e nessuno dei due sotto
    zero, perche' un gol non puo' valere meno di niente.
    """
    t = np.array(theta, dtype=float)
    npesi = len(theta0) - (N_BANDA if hasattr(bench, "banda0") else 0)
    for i in range(npesi):
        if theta0[i] > 0:
            t[i] = max(0.0, t[i])
        elif theta0[i] < 0:
            t[i] = min(0.0, t[i])
        else:
            t[i] = 0.0          # uno zero deliberato resta zero
    if hasattr(bench, "banda0"):
        lo, hi, la, ha = t[-N_BANDA:]
        lo = max(0.0, lo); la = max(0.0, la)
        t[-N_BANDA:] = [lo, max(lo, hi), la, max(la, ha)]
    return t


def pesi_da_parametri(bench, theta) -> dict:
    # UN THETA DELLA LUNGHEZZA SBAGLIATA E' UN THETA DI UN ALTRO MODELLO, e va
    # rifiutato invece che troncato. Il 01/09/2026 ho tolto due feature
    # dall'insieme dei pesi mobili e poi ricaricato un vettore salvato PRIMA:
    # ``theta[:n]`` ne ha preso silenziosamente i primi 40, attaccando ogni peso
    # alla feature sbagliata. Il difetto non ha dato nessun errore — solo numeri
    # assurdi (la correlazione partiva da 0.58 invece che da 0.80) che si notano
    # se uno guarda, e non si notano se uno legge solo la riga finale.
    atteso = lunghezza_attesa(bench)
    if len(theta) != atteso:
        raise ValueError(
            "theta ha %d parametri ma questo banco ne vuole %d: e' il vettore di "
            "un altro insieme di feature (ricalcolalo, non troncarlo)"
            % (len(theta), atteso))
    n = len(bench.keys)
    W = {r: np.array(theta[:n], dtype=float) for r in ("DIF", "CEN", "ATT")}
    p = n
    for k in CHIAVI_RUOLO:
        i = bench.idx_of.get(k)
        if i is None:
            continue
        for j, r in enumerate(("DIF", "CEN", "ATT")):
            W[r][i] = theta[p + j]
        p += 3
    return W


def margini(bench, theta, vincoli) -> tuple:
    """Lo scarto di ogni vincolo, e il contesto che l'ha prodotto."""
    W = pesi_da_parametri(bench, theta)
    ref, _ = bench.riferimento(W)
    bench.curve(W, ref)
    # PRIMO GIRO SULLA CALIBRAZIONE: serve a tarare l'appiattimento, che si misura
    # sul residuo contro le pagelle — cioe' sulla stagione dove le pagelle ci sono.
    # LA CHIAMATA STA FUORI DALLA COMPRENSIONE: scritta dentro, ``voti`` girava una
    # volta per chiave invece che una volta — 9933 esecuzioni da 40 ms, cioe' 6
    # minuti e mezzo per UNA valutazione invece di 150 millisecondi. Il banco esiste
    # per essere veloce; una riga cosi' ne annulla il motivo, e in silenzio.
    banda = banda_da_parametri(bench, theta)
    primo = bench.voti(W, ref, "cal", banda)
    arr0 = np.array([primo.get(k, 6.0) for k in bench.cal_key])
    appiattisci(bench, W, ref, arr0)
    # Ora la curva e' quella definitiva: si ripunteggia la calibrazione (per
    # l'accordo coi giudici) e si punteggiano i BERSAGLI (per i vincoli di campo).
    voti_cal = bench.voti(W, ref, "cal", banda)
    arr_cal = np.array([voti_cal.get(k, 6.0) for k in bench.cal_key])
    voti_ber = bench.voti(W, ref, "ber", banda)
    ctx = {"voti": voti_ber, "arr": arr_cal, "ref": ref,
           "giudici": accordo(bench, arr_cal), "cruscotto": cruscotto(bench, W, ref)}
    return np.array([v.scarto(ctx) for v in vincoli]), ctx


def passo(J, m, scala, dentro: float = 0.0, raggio: float = 0.25):
    """Il passo piu' corto che porta dentro i vincoli violati.

    USA SCIPY SE C'E', altrimenti l'insieme attivo qui sotto. L'import e' DENTRO
    la funzione di proposito: questo file sta in ``services/``, e se un giorno
    qualcosa lo importasse dal codice che gira in produzione una dipendenza da
    scipy in cima al modulo farebbe cadere il server per uno strumento che il
    server non usa. Scipy e' installato solo in sviluppo, e qui e' un lusso, non
    un requisito.
    """
    try:
        from scipy.optimize import minimize
    except ImportError:
        return _passo_numpy(J, m, scala, dentro, raggio)
    n = J.shape[1]
    D = 1.0 / np.where(scala > 1e-12, scala, 1e-12)
    vinc = [{"type": "ineq",
             "fun": (lambda d, i=i: m[i] + float(J[i] @ d) - dentro)}
            for i in range(len(m))]
    vinc.append({"type": "ineq",
                 "fun": lambda d: raggio - float(np.sqrt(np.sum((d * D) ** 2)))})
    r = minimize(lambda d: float(np.sum((d * D) ** 2)), np.zeros(n),
                 jac=lambda d: 2.0 * (d * D * D), constraints=vinc,
                 method="SLSQP", options={"maxiter": 300, "ftol": 1e-12})
    if not np.all(np.isfinite(r.x)):
        return _passo_numpy(J, m, scala, dentro, raggio)
    return r.x


def _passo_numpy(J, m, scala, dentro: float = 0.0, raggio: float = 0.25):
    """La riserva, senza scipy: stesso problema con un insieme attivo.

    Insieme attivo: si impongono come uguaglianze i soli vincoli fuori (o troppo
    vicini al bordo), si risolve in forma chiusa il minimo di ‖D·dtheta‖ sotto quei
    vincoli, e se il passo ne rompe altri li si aggiunge e si rifa'. Il raggio di
    fiducia tiene il passo dentro la zona in cui la linearizzazione vale.
    """
    n = J.shape[1]
    attivi = [i for i in range(len(m)) if m[i] < dentro]
    for _ in range(12):
        if not attivi:
            return np.zeros(n)
        A = J[attivi]
        b = np.array([dentro - m[i] for i in attivi])
        # min ‖D dtheta‖  s.t.  A dtheta = b   ->   dtheta = D^-2 A' (A D^-2 A')^-1 b
        Dm2 = np.diag(scala ** 2)
        M = A @ Dm2 @ A.T
        try:
            lam = np.linalg.solve(M + 1e-12 * np.eye(len(attivi)), b)
        except np.linalg.LinAlgError:
            lam = np.linalg.lstsq(M, b, rcond=None)[0]
        d = Dm2 @ A.T @ lam
        norm = float(np.sqrt(np.sum((d / scala) ** 2)))
        if norm > raggio:
            d *= raggio / norm
        nuovi = [i for i in range(len(m))
                 if i not in attivi and m[i] + float(J[i] @ d) < dentro]
        if not nuovi:
            return d
        attivi += nuovi
    return d

# ==============================================================================
# LA FORMULAZIONE MORBIDA — un minimo esiste sempre, e i residui sono una misura
# ==============================================================================
# PERCHE' SI CAMBIA (idea dell'utente, 01/09/2026). Con i vincoli RIGIDI il problema
# o e' fattibile o non lo e', e questo non lo e': le osservazioni di campo tirano
# l'una contro l'altra (Raimondo deve salire rispetto ai difensori, Dimarco e
# Rrahmani devono scendere rispetto ai compagni — e' la stessa leva nei due versi)
# e tutte insieme costano accordo con le pagelle. Un metodo a insieme attivo, su un
# problema infattibile, non fallisce in modo pulito: annaspa. Misurato — i vincoli
# violati salivano da 8 a 10 mentre il difetto scendeva, e il solutore cedeva tutti
# e tre i pavimenti sui giudici per un millesimo ciascuno.
#
# Con la formulazione morbida il minimo esiste sempre, e soprattutto **i residui
# all'ottimo diventano una diagnosi**: quello che resta violato quando tutto e'
# bilanciato e' cio' che i PESI non possono raggiungere, e che quindi vuole un
# cambiamento strutturale (una feature che non c'e', un trattamento diverso) invece
# di un'altra ritaratura. E' l'informazione che serve, e con i vincoli rigidi non
# si otteneva.
#
# LE UNITA' SONO PUNTI DI VOTO, tutte e tre. Per l'accordo coi giudici si usa
# l'ERRORE MEDIO e non la correlazione, proprio per questo: la correlazione e' un
# numero puro e metterla nella stessa somma dei margini vorrebbe dire scegliere un
# tasso di cambio a occhio. Con l'errore medio il tasso resta una scelta — quanto
# vale un caso violato di un decimo rispetto a un decimo di errore in piu' su
# diecimila pagelle — ma e' una scelta che si puo' discutere invece che una
# costante calata dall'alto.

def errore_medio(bench, voti_arr) -> dict:
    """L'errore medio contro ogni giudice, in punti di voto."""
    out = {}
    for nome, (idx, ext) in bench.giud_righe.items():
        if len(idx):
            out[nome] = float(np.mean(np.abs(voti_arr[idx] - ext)))
    return out


def obiettivo(bench, theta, vincoli, theta0, base,
              rho: float = 1.0, lam: float = 0.02, mu: float = 30.0):
    """L(theta), e il contesto che l'ha prodotta.

    ``rho``  quanto pesa un'osservazione di campo violata (al quadrato, cosi' una
             violazione grossa conta piu' di due piccole: e' l'ordine giusto,
             perche' un caso molto sbagliato e' un difetto e due leggermente
             sbagliati sono rumore).
    ``lam``  quanto pesa il cambiamento relativo dei pesi. Basso di proposito: non
             deve impedire di muoversi, deve scegliere fra soluzioni equivalenti.
    ``mu``   il tasso di cambio con le pagelle. A 30, un millesimo di errore medio
             in piu' su 10.583 presenze costa quanto un caso violato di 0.18 punti:
             la popolazione pesa piu' del singolo caso, che e' come deve essere.
    """
    m, ctx = margini(bench, theta, vincoli)
    pesi = np.array([v.peso for v in vincoli])
    viol = float(np.sum(pesi * np.minimum(m, 0.0) ** 2))
    W = pesi_da_parametri(bench, theta)
    cambio = 0.0
    W0 = pesi_da_parametri(bench, theta0)
    for r in ("DIF", "CEN", "ATT"):
        b = np.where(np.abs(W0[r]) > 1e-9, np.abs(W0[r]), 1e-3)
        cambio += float(np.sum(((W[r] - W0[r]) / b) ** 2))
    mae = errore_medio(bench, ctx["arr"])
    peggio = sum(mae[k] - base[k] for k in mae)
    ctx["mae"] = mae
    ctx["termini"] = {"vincoli": rho * viol, "cambiamento": lam * cambio / 3.0,
                      "giudici": mu * peggio}
    return rho * viol + lam * cambio / 3.0 + mu * peggio, ctx


# ==============================================================================
# LE BANDE DEL GOL E DELL'ASSIST COME PARAMETRI
# ==============================================================================
# IDEA DELL'UTENTE, ed e' la correzione di un errore mio. Lasciando l'ottimizzatore
# libero, riaccendeva `shots_goal` e `assists` come feature dell'indice — che sono
# a ZERO per disegno, perche' quegli eventi li paghiamo FUORI dall'indice, graduati
# dal ΔxP (v. services/goal_impact). Non era un capriccio: stava dicendo una cosa
# vera, cioe' che i giudici pagano il gol piu' di noi. Ma la diceva con lo
# strumento sbagliato — un conteggio, che butta via la graduazione per impatto e
# si fa attenuare dai minuti.
#
# La risposta giusta non e' vietarglielo: e' dargli la manopola NOSTRA. Cosi' se il
# dato dice che paghiamo poco il gol, il livello sale CONSERVANDO il disegno — un
# gol che non ha cambiato niente continua a valere poco.
#
# E costa zero, perche' il credito e' lineare nella banda:
#
#     credito = n * lo + (hi - lo) * somma_delle_radici_delle_importanze
#
# quindi bastano due numeri per presenza (quanti gol, e la somma dei sqrt(u)) e
# ``lo``/``hi`` diventano due parametri come gli altri.
#
# `shots_goal` e `assists` ESCONO dall'insieme dei pesi mobili: non sono feature
# dell'indice in questo modello, e tenerle come "zeri da proteggere" le lascerebbe
# comunque nel vettore, nello jacobiano e nel registro delle spiegazioni.

FUORI_DALL_INDICE = ("shots_goal", "assists")


def carica_bande(bench, percorso_cal: str, percorso_ber: str) -> None:
    """I due numeri per presenza, per entrambe le popolazioni.

    Le MEDIE DI RUOLO si ricavano dai crediti gia' esportati invece di
    ricalcolarle: ``gadj_esportato = credito(banda_attuale) - media_ruolo``, quindi
    la media e' una sottrazione. Cosi' il banco non puo' divergere dal modello vero
    su questo termine, perche' non lo indovina.
    """
    import json
    for nome, perc, chiavi, extra in (("cal", percorso_cal, bench.cal_key, bench.cal_extra),
                                      ("ber", percorso_ber, bench.ber_key, bench.ber_extra)):
        d = json.load(open(perc))
        righe = d["righe"]
        n_g = np.zeros(len(chiavi)); r_g = np.zeros(len(chiavi))
        n_a = np.zeros(len(chiavi)); r_a = np.zeros(len(chiavi))
        for i, (mid, pid) in enumerate(chiavi):
            r = righe.get("%d:%d" % (mid, pid))
            if not r:
                continue
            n_g[i] = r.get("n_gol", 0); r_g[i] = r.get("r_gol", 0.0)
            n_a[i] = r.get("n_ass", 0); r_a[i] = r.get("r_ass", 0.0)
        setattr(bench, nome + "_ngol", n_g); setattr(bench, nome + "_rgol", r_g)
        setattr(bench, nome + "_nass", n_a); setattr(bench, nome + "_rass", r_a)
        # la media di ruolo, ricavata: credito(banda attuale) - adj esportato
        from vfoot.services.goal_impact import fixed_band, fixed_assist_band
        (lo, hi), _ = fixed_band()
        (la, ha), _ = fixed_assist_band()
        cred = n_g * lo + (hi - lo) * r_g + n_a * la + (ha - la) * r_a
        adj = np.array([e[0] for e in extra])
        setattr(bench, nome + "_media", cred - adj)
    bench.banda0 = np.array([*fixed_band()[0], *fixed_assist_band()[0]])


def credito(bench, quale: str, banda) -> np.ndarray:
    """Il credito di gol e assist per una banda, gia' al netto della media di ruolo."""
    lo, hi, la, ha = banda
    n_g = getattr(bench, quale + "_ngol"); r_g = getattr(bench, quale + "_rgol")
    n_a = getattr(bench, quale + "_nass"); r_a = getattr(bench, quale + "_rass")
    return (n_g * lo + (hi - lo) * r_g + n_a * la + (ha - la) * r_a
            - getattr(bench, quale + "_media"))
