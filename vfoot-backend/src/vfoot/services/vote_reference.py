"""The FIXED per-role calibration the voto puro is scored against.

Why fixed, and not computed from the running season: the vote centres each role
on 6 by z-scoring a player's index against his peers' mean and spread. If that
mean and spread came from the season in progress, two things would break, both of
them the user's objection:

* cold start — on matchday 1 there is no season to average, so there is no scale;
* drift — the reference would move as results arrive, so the same performance
  would earn a different vote in September and in May, and a 6 would not mean the
  same thing across matchdays, let alone across seasons.

So mean/std per role (and the per-feature averages the explanation subtracts) are
calibrated ONCE on a COMPLETED season, frozen to a file in the repo, and read
from there forever after. They are a parameter of the model, exactly like the
weights, and are re-derived only when the model itself changes — never during a
season. The stored ``weights_fingerprint`` records which weights produced them,
so a silent mismatch (someone edits a weight, forgets to recalibrate) surfaces as
a warning instead of as quietly wrong votes.
"""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from django.conf import settings

log = logging.getLogger(__name__)

# Versioned in the repo next to the code whose behaviour it fixes.
REFERENCE_PATH = Path(settings.BASE_DIR) / "vfoot" / "data" / "vote_reference.json"


def weights_fingerprint() -> str:
    """A short hash of every number the reference depends on. If any weight, the
    spread constant, or the shrinkage changes, so does this — which is how a
    recalibration-needed state is detected rather than assumed away."""
    from vfoot.services import classic_rating as cr
    payload = {
        "total": cr.TOTAL_WEIGHTS, "per90": cr.PER90_WEIGHTS,
        "gk_total": cr.GK_TOTAL_WEIGHTS, "gk_per90": cr.GK_PER90_WEIGHTS,
        # Per-role overrides change the index of the roles they touch, hence those
        # roles' mean and spread: same invalidation as any other weight.
        "role_weights": cr.ROLE_WEIGHTS,
        "exposure": cr.EXPOSURE_WEIGHT, "exposure_lambda": cr.EXPOSURE_LAMBDA,
        "exposure_kernel": cr.EXPOSURE_KERNEL,
        # Changes the exposure the INDEX consumes, hence the per-role mean and spread
        # of the index: a change here invalidates the reference exactly as a weight
        # change does.
        "exposure_credit": cr.EXPOSURE_CREDIT,
        # Same reasoning for the absence credit: it changes the z the index
        # consumes for every credited count, hence the per-role mean and spread.
        "absence_credit": cr.ABSENCE_CREDIT,
        "credited_features": sorted(cr.CREDITED_FEATURES),
        # The compression shape and the derived-feature recipe both change what the
        # stored per-feature spreads mean, so a change to either must invalidate the
        # calibration exactly as a weight change does.
        "compress_k": cr.COMPRESS_K, "sga_post_woodwork": cr.SGA_POST_WOODWORK,
        # Stessa ragione del legno: e' un addendo della ricetta di sga_post, quindi
        # cambia i valori grezzi della feature e le sigma calibrate su di essi.
        "sga_post_blocked": cr.SGA_POST_BLOCKED,
        # which features skip the compression changes their stored spreads and the
        # index built from them — a reference computed under a different exemption
        # set scores every vote on the wrong scale
        "no_compress": sorted(cr.NO_COMPRESS_FEATURES),
        # Whether the outfield roles share one spread changes the stored per-role
        # std, so flipping it without recalibrating would score every vote against
        # the wrong scale — exactly the state this fingerprint exists to catch.
        "pooled_role_spread": cr.POOLED_ROLE_SPREAD,
        "spread_k": cr.VOTE_SPREAD_K, "gk_spread_k": cr.GK_SPREAD_K,
        "center": cr.VOTE_CENTER,
        # Il centro per ruolo sposta il voto senza toccare l'indice: non cambia la
        # calibrazione, ma cambia OGNI voto di quel ruolo, quindi l'impronta deve
        # muoversi o la cache servirebbe un misto.
        "role_center": cr.ROLE_VOTE_CENTER,
        "extrap_floor": cr.EXTRAP_FLOOR_MINUTES, "shrinkage": cr.SHRINKAGE_MINUTES,
        "min_ref": cr.MIN_MINUTES_REFERENCE,
        # Changes what a keeper's goals-prevented IS when his side scored an own
        # goal, hence the mean and spread of the keeper index: a reference computed
        # under a different default scores those votes on the wrong scale.
        "own_goal_keeper_default": cr.OWN_GOAL_KEEPER_XGOT_DEFAULT,
    }
    blob = json.dumps(payload, sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


# BUMP THIS when the scoring CODE changes in a way that moves votes without any
# constant changing — a fixed formula, an argument that was not being passed, a
# different feature source. The rest of the fingerprint is built from constants
# and from the calibration file, so a pure code fix leaves it identical and every
# cached vote in the wild stays wrong until someone clears the cache by hand.
#   1 -> 2: the listone was building the index without the defensive exposure.
#   2 -> 3: the listone now scores through voto_puro_for_match, so it also gets
#           the keeper evidence damping, the sending-off / own-goal / missed-penalty
#           drops, the result mitigation and the decisive-event rated override.
#   3 -> 4: a keeper's goals-prevented no longer swallows a team-mate's own goal as
#           if he had been beaten by a shot — it is credited with the own goal's own
#           difficulty (``_merge_own_goal_relief``). The new default constant is in
#           the fingerprint too; this bump is what invalidates the CACHED votes of
#           the 22 keeper appearances a season that the change moves.
#   4 -> 5: the result mitigation can no longer erase the WHOLE divergence from 6
#           (RESULT_MITIGATION_MAX_SHARE): at four goals of margin it used to pin
#           every divergent vote to exactly 6.0, and past four it crossed the centre.
#           (Il "mai sotto il 6" che questo giro difendeva vale, dalla 9, solo per
#           le vittorie: v. 8 -> 9.)
#           The post-index constants now key the scoring fingerprint below, so a
#           future change to them invalidates caches on its own — this bump covers
#           the one that introduced them.
#   5 -> 6: il registro esteso porta due campi nuovi -- le voci raccolte per
#           famiglia (``groups``) e la mappa dei tiri -- e i VOTI non cambiano.
#           Proprio per questo serviva un giro qui: la chiave della cache si muove
#           con le costanti del MODELLO, e una modifica che cambia la FORMA del
#           payload senza toccarne i numeri non le sposta. La cache in produzione
#           e' su FILE e sopravvive ai riavvii, quindi ha continuato a servire le
#           righe vecchie -- senza i gruppi -- a un frontend che li aspettava, e il
#           pannello si apriva vuoto. Chi aggiunge un campo al registro bumpa qui.
#   6 -> 7: la spiegazione del voto calcolava il numero con la scala di MOVIMENTO
#           anche per il portiere (GK_SPREAD_K era arrivato senza di lei), e il
#           pannello «come nasce il voto puro» smentiva il voto scritto accanto al
#           nome in 91 pagelle di portiere su 1247. I voti non si muovono di un
#           centesimo: si muove il payload della spiegazione, che vive nella stessa
#           cache su file dei voti e sopravvive al riavvio. Senza questo giro la
#           produzione avrebbe continuato a servire il pannello sbagliato fino al
#           primo dato nuovo di quella giornata.
#   7 -> 8: l'autogol contava come CONCLUSIONE TENTATA. ``_merge_shot_detail`` lo
#           teneva gia' fuori da ``shots_goal``, ma ``shots`` arriva dalle zone del
#           fornitore e li' l'autogol c'era: 22 su 22 sulla 25-26, e siccome il
#           volume di tiro e' creditato, ognuno regalava al suo autore +0.048 di
#           voto in media. Qui i VOTI si muovono davvero (solo per quei giocatori),
#           quindi senza questo giro la cache su file avrebbe continuato a servire
#           il voto col regalo dentro. Insieme, la mappa dei tiri smette di
#           chiamarlo "gol" e di stampargli accanto un numero fabbricato.
#           Nella stessa versione: l'xGOT D'UFFICIO. Dove il fornitore non manda
#           ``expectedGoalsOnTarget``, la sua assenza si leggeva come uno zero e
#           ``sga_post`` raccontava conclusioni buttate via — su Moro, che aveva
#           segnato, −0.880 e un punto pieno di voto (6.0 invece di 7.0). Ora il
#           buco si tappa con l'xGOT della mappa dei tiri, che e' gia' la fonte
#           dell'altra meta' della sottrazione. Due righe in tutta la 25-26.
#   8 -> 9: la mitigazione del risultato diventa ASIMMETRICA. Nella sconfitta il
#           bersaglio della tirata scende a ``centro_di_ruolo − 0.35``, quindi una
#           goleada subita puo' portare il voto sotto il centro (5.65 per un
#           centrocampista) invece di fermarlo li'; nella vittoria non cambia
#           niente e il tetto resta il centro. Le tre costanti nuove sono nel
#           fingerprint qui sotto, ma questo giro serve lo stesso: si spostano 343
#           voti su 9.933 nella 25-26, e la cache su FILE della produzione avrebbe
#           continuato a servire quelli vecchi fino al primo dato nuovo di quella
#           giornata. Chi rilegge: il perche' e la misura stanno nel blocco
#           RESULT_MITIGATION_LOSS_ANCHOR di classic_rating.
SCORING_CODE_VERSION = 9


def scoring_fingerprint() -> str:
    """A hash of EVERYTHING that turns features into a vote, for cache keys.

    ``weights_fingerprint`` answers "does the stored reference still match the
    weights"; this answers the different question "would the same appearance get
    the same vote today", which needs three things it deliberately leaves out:

      * the CALIBRATION ITSELF — recalibrating produces new per-role means and
        spreads with the weights untouched, so the weights hash alone does not
        move and anything keyed on it would keep serving pre-calibration votes;
      * the rated/senza-voto GATES, which decide WHO gets a vote at all;
      * the goalkeeper evidence damping, which scales the deviation from 6.

    Anything caching derived votes must key on this. Without it a cached season
    stays valid until a new match is played: the 25-26 season is over, so the
    listone served ratings computed before the whole v3 retuning and no key ever
    changed. Cheap to compute — one file already in memory plus a few constants.
    """
    from vfoot.services import classic_rating as cr
    payload = {
        "code": SCORING_CODE_VERSION,
        "weights": weights_fingerprint(),
        # The calibrated scale, not just the weights that produced it.
        "reference": _load() or {},
        "gates": [cr.MIN_MINUTES_RATED, cr.MIN_TOUCHES_RATED,
                  cr.ALWAYS_RATED_MINUTES],
        # Le correzioni APPLICATE DOPO l'indice: mitigazione del risultato, rosso,
        # autogol, rigore sbagliato. Non stanno nel fingerprint dei pesi perché non
        # entrano nella calibrazione — l'indice non le vede, quindi la reference
        # resterebbe valida — ma i VOTI li cambiano, e questa è la chiave di chi li
        # mette in cache. Senza, ritoccare la mitigazione lasciava in giro i voti
        # calcolati prima senza che nessuna chiave si muovesse.
        "post_index": [cr.RESULT_MITIGATION_K, cr.RESULT_MITIGATION_BASE,
                       cr.RESULT_MITIGATION_CAP, cr.RESULT_MITIGATION_MAX_SHARE,
                       cr.RESULT_MITIGATION_LOSS_ANCHOR, cr.RESULT_MITIGATION_LOSS_K,
                       cr.RESULT_MITIGATION_LOSS_BASE,
                       cr.RESULT_MITIGATION_LOSS_MAX_SHARE,
                       cr.RED_CARD_K, sorted(cr.RED_CARD_SEVERITY.items()),
                       sorted(cr.RED_CARD_FIXED.items()),
                       cr.OWN_GOAL_VOTE_DEFLECTION, cr.OWN_GOAL_VOTE_SOLO,
                       cr.OWN_GOAL_VOTE_FLAT,
                       cr.PENALTY_MISSED_VOTE_RELEVANT,
                       cr.PENALTY_MISSED_VOTE_IRRELEVANT],
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def save(reference: dict, role_averages: dict, *, season_id: int,
         feature_scales: dict | None = None, goal_impact: dict | None = None) -> None:
    REFERENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE_PATH.write_text(json.dumps({
        "calibrated_on_season": season_id,
        "weights_fingerprint": weights_fingerprint(),
        "reference": reference,
        "role_averages": role_averages,
        # Per-feature spreads: without them a weight has nothing to standardise
        # against, so they are as much a part of the calibration as the role mean.
        "feature_scales": feature_scales or {},
        # La tabella dei punti attesi, la banda del gol e la media di ruolo del
        # credito (v. services/goal_impact). Stanno QUI e non fra le costanti del
        # codice per due ragioni: sono misurate su una stagione come tutto il resto
        # della calibrazione, e ``scoring_fingerprint`` fa l'hash dell'intero file —
        # quindi ritararle invalida da sola ogni cache di voti, senza che nessuno
        # debba ricordarsi di aggiungerle a una lista.
        "goal_impact": goal_impact or {},
    }, indent=2, sort_keys=True))


_cache: dict | None = None


def _load() -> dict | None:
    global _cache
    if _cache is not None:
        return _cache
    if not REFERENCE_PATH.exists():
        return None
    data = json.loads(REFERENCE_PATH.read_text())
    if data.get("weights_fingerprint") != weights_fingerprint():
        # Loud on purpose: the votes are now being scored against a scale that no
        # longer matches the weights producing the indices. Still usable — better
        # a slightly stale scale than none — but someone must recalibrate.
        log.warning("vote_reference.json was calibrated for different weights "
                    "(%s != %s); run `manage.py calibrate_vote_reference`.",
                    data.get("weights_fingerprint"), weights_fingerprint())
    _cache = data
    return data


def clear_cache() -> None:
    """Drop the in-process copy (after a recalibration, or in tests)."""
    global _cache
    _cache = None


def fixed_reference() -> dict | None:
    data = _load()
    return data["reference"] if data else None


def fixed_role_averages() -> dict | None:
    data = _load()
    return data["role_averages"] if data else None


def fixed_feature_scales() -> dict | None:
    data = _load()
    return data.get("feature_scales") if data else None


def fixed_goal_impact() -> dict | None:
    """{"xp": {...}, "band": [lo, hi], "p95": x, "role_mean_credit": {...}}."""
    data = _load()
    return data.get("goal_impact") if data else None
