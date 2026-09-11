"""Il completamento bayesiano dei minuti non giocati.

Fino all'11/09/2026 uno spezzone si votava PROIETTANDO i volumi a 90 minuti
(``90 / max(m, 55)``), attenuando lo scostamento dal 6 con ``m / (m + 90)`` e
correggendo il livello con una curva empirica per minuto tarata sul giudice. Tre
meccanismi per una domanda sola: che cosa avrebbe fatto, nei minuti che non ha
giocato, un giocatore di cui abbiamo visto questi?

Qui la risposta e' un modello, non tre correzioni. Ogni conteggio ``x`` osservato
in una frazione ``t = m/90`` di partita e' letto come un processo di Poisson a
tasso incerto, ``X | lambda ~ Poisson(t lambda)`` con ``lambda ~ Gamma`` centrata
sul tasso medio del ruolo. L'osservazione aggiorna il tasso (chi ha fatto molto in
poco ne ha uno alto, ma la prior lo frena quanto piu' i minuti sono pochi), e i
minuti mancanti si completano con la DISTRIBUZIONE predittiva del conteggio
finale: la feature che entra nell'indice e' la media di ``z(x + Y)`` sotto quella
distribuzione, ``Y`` binomiale negativa. A 90 minuti ``Y`` e' zero e tutto
coincide col voto di partita intera; a zero minuti il completamento e' esattamente
l'ancora neutra (il valore che lo stadio finale porta a 6), che la calibrazione del
ruolo qui sotto sposta poi di ``delta_c`` — circa -0,2 per un difensore: di chi non
si e' visto niente il modello tarato dice 5,7-5,8, non 6. Le grandezze continue
(xG, xA, esposizione, indice difensivo) si completano col loro tasso medio, senza
distribuzione.

Sopra il completamento stanno i PESI e una CALIBRAZIONE per ruolo (centro e
scala affini), cercati sulle giornate dispari 2025-26 col vincolo che zeri e
segni restassero quelli del modello precedente — e' la soluzione ``constrained``
di ``experiments-voto-minutaggi/sign_rule_effect.py``, misurata fuori campione
sulle giornate pari e sulle prime tre della 2026-27 (artifact «Il Bayesiano
vincolato»). I pesi vivono nelle tabelle di ``classic_rating`` come sempre; qui
stanno prior, dispersioni e calibrazione, in ``data/bayesian_completion.json``.

IL MODELLO E' TARATO SU UNA REFERENCE PRECISA. Medie, dispersioni e scale della
reference congelata sono INGRESSI della taratura: la calibrazione affine le ha
assorbite. Per questo l'artifact pinna l'impronta dei pesi con cui la reference
fu calibrata e lo sha del file: chi ricalibra la reference o tocca un peso deve
rifare anche questa taratura, e ``check_pins`` lo dice.

Tutto quel che segue l'indice — credito gol/assist, mitigazione, disciplina,
saturazione — e' quello di ``classic_rating`` e non e' toccato. Il portiere non
passa di qui.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
from pathlib import Path

import numpy as np
from django.conf import settings

from realdata.models import Player
from vfoot.services import classic_rating as cr
from vfoot.services import goal_impact

log = logging.getLogger(__name__)

ARTIFACT_PATH = Path(settings.BASE_DIR) / "vfoot" / "data" / "bayesian_completion.json"
OUTFIELD = (Player.ROLE_DEF, Player.ROLE_MID, Player.ROLE_FWD)
# Le grandezze che NON sono conteggi: si completano col tasso medio, senza
# distribuzione. L'indice difensivo e' un valore atteso normalizzato, xG e xA
# sono somme di probabilita', sga_post e' una differenza con segno, l'esposizione
# un pericolo atteso.
CONTINUOUS = frozenset({"defensive_value", "expected_assists", "xg_shots", "sga_post",
                        cr.EXPOSURE_KEY})
# Quattro famiglie di dispersione condivise (Var(lambda)/mu^2), stimate una volta:
# un conteggio raro e uno frequente non hanno la stessa incertezza sul tasso.
CIRCULATION = frozenset({"touches", "passes_completed", "long_balls_completed",
                         "errors_bad_passes"})
DECISIVE = frozenset({"shots", "shots_on_target", "shots_blocked", "clearances_off_line",
                      "errors_led_to_goal", "errors_led_to_shot", "penalties_won",
                      "penalties_conceded", "goals", "assists"})
# Massa di probabilita' trascurata nella somma predittiva.
TAIL = 1e-11
_MAX_TERMS = 20000


def family(key: str) -> str:
    if key.startswith("gk_"):
        return "goalkeeper"
    if key in CIRCULATION:
        return "circulation"
    if key in DECISIVE:
        return "decisive"
    return "duels_defense"


# ---------------------------------------------------------------- l'artifact
_artifact: dict | None = None
_artifact_loaded = False
_neutral: dict[tuple[str, str], float] = {}


def artifact() -> dict | None:
    """Prior, dispersioni e calibrazione, letti una volta. ``None`` se il file
    manca: allora il voto torna al modello precedente, e lo dice."""
    global _artifact, _artifact_loaded
    if _artifact_loaded:
        return _artifact
    _artifact_loaded = True
    if not ARTIFACT_PATH.exists():
        log.error("bayesian_completion.json manca: i minuti non giocati si votano "
                  "col modello precedente (proiezione a 90 e attenuazione).")
        return None
    data = json.loads(ARTIFACT_PATH.read_text())
    if data.get("schema_version") != 2:
        log.error("bayesian_completion.json ha uno schema sconosciuto (%s): ignorato.",
                  data.get("schema_version"))
        return None
    _artifact = data
    for problem in check_pins(data):
        log.error("bayesian_completion.json: %s", problem)
    return _artifact


def clear_cache() -> None:
    global _artifact, _artifact_loaded
    _artifact, _artifact_loaded = None, False
    _neutral.clear()


def artifact_sha256() -> str | None:
    """Per ``scoring_fingerprint``: cambiare prior o calibrazione cambia i voti."""
    if not ARTIFACT_PATH.exists():
        return None
    return hashlib.sha256(ARTIFACT_PATH.read_bytes()).hexdigest()[:16]


def check_pins(data: dict | None = None) -> list[str]:
    """Le due impronte che rendono il modello quello tarato, e non un parente.

    Vuota se tutto torna. Altrimenti una riga per problema — e' anche un test
    (tests_bayesian_completion), perche' un errore qui produce voti sbagliati in
    silenzio."""
    data = data if data is not None else artifact()
    if not data:
        return ["artifact assente"]
    from vfoot.services import vote_reference as vr
    out = []
    if data.get("weights_fingerprint") != vr.weights_fingerprint():
        out.append("i pesi del codice (%s) non sono quelli della taratura (%s)"
                   % (vr.weights_fingerprint(), data.get("weights_fingerprint")))
    if vr.REFERENCE_PATH.exists():
        sha = hashlib.sha256(vr.REFERENCE_PATH.read_bytes()).hexdigest()
        if data.get("reference_sha256") != sha:
            out.append("vote_reference.json (%s) non e' il file su cui il modello e' "
                       "stato tarato (%s)" % (sha[:16], str(data.get("reference_sha256"))[:16]))
    return out


def is_active(ref_key: str) -> bool:
    """Il completamento vale per i tre ruoli di movimento con un artifact valido.
    Il portiere e la scala aggregata (giocatore senza ruolo) restano al modello
    precedente, che per loro non e' mai stato ritarato."""
    return ref_key in OUTFIELD and artifact() is not None


def calibration(ref_key: str) -> tuple[float, float, float]:
    """``(delta_c, scala, ancora)``: V = ancora + delta_c + scala * (V_indice - ancora)."""
    c = (artifact() or {}).get("calibration", {}).get(ref_key)
    anchor = cr.neutral_pre_scale(ref_key)
    if not c:
        return 0.0, 1.0, anchor
    return float(c["delta_c"]), float(c["scale"]), anchor


def centre_shift(ref_key: str, t: float) -> float:
    """Di quanto la calibrazione sposta il centro per QUESTA frazione di partita.

    ``delta_c`` e' la correzione di livello del voto costruito sull'evidenza; la
    forma in ``calibration.shape`` dice quanta ne spetta a chi ha giocato ``t``:
    ``constant`` la applica intera a tutti (ancora compresa), ``smoothstep``
    la fa partire da zero a zero minuti — cosi' l'ancora neutra resta 6 — e la
    porta per intero da ``tau`` in su senza gomiti."""
    delta_c, _scale, _anchor = calibration(ref_key)
    c = (artifact() or {}).get("calibration", {}).get(ref_key) or {}
    shape = c.get("shape", "constant")
    if shape == "constant":
        return delta_c
    tau = float(c.get("tau", 1.0))
    u = min(max(t / tau, 0.0), 1.0)
    if shape == "smoothstep":
        return delta_c * (3 * u * u - 2 * u ** 3)
    if shape == "ramp":
        return delta_c * u
    raise ValueError("forma della calibrazione sconosciuta: %r" % shape)


def _prior(ref_key: str) -> dict:
    return (artifact() or {}).get("role_priors", {}).get(ref_key) or {}


def prior_rate(ref_key: str, key: str) -> float:
    return float((_prior(ref_key).get("raw") or {}).get(key, 0.0))


def dispersion(key: str) -> float:
    return float((artifact() or {}).get("dispersions", {}).get(family(key), 0.0))


# ---------------------------------------------------------------- la predittiva
def posterior_rate(x: float, t: float, mu: float, c: float) -> float:
    """La media a posteriori del tasso, in unita' per 90'. Stabile a mu o c nulli."""
    if mu <= 0 or c <= 0:
        return mu
    return (mu + c * mu * x) / (1 + c * mu * t)


def expected_transform(fn, x: float, t: float, mu: float, c: float) -> float:
    """E[fn(x + Y)] con Y il conteggio dei minuti mancanti.

    Binomiale negativa (tasso incerto) se ``c > 0``, Poisson se il tasso e' certo.
    ``fn`` prende un array di valori e ne restituisce uno: e' la trasformazione
    della feature, che qui viene integrata per davvero e non valutata sulla media —
    la compressione e' concava e la differenza e' misurabile."""
    h = 1.0 - t
    if h <= 1e-12 or mu <= 0:
        return float(fn(np.array([x], dtype=float))[0])
    if c <= 1e-8:
        lam = h * mu
        p0 = math.exp(-lam)
        ratio = lambda n: lam / (n + 1)                          # noqa: E731
    else:
        a = 1.0 / c + x
        rate = 1.0 / (c * mu) + t
        p = rate / (rate + h)
        p0 = p ** a
        ratio = lambda n: (a + n) / (n + 1) * (1.0 - p)          # noqa: E731
    pmf = [p0]
    total = p0
    n = 0
    while total < 1.0 - TAIL and n < _MAX_TERMS:
        pmf.append(pmf[-1] * ratio(n))
        total += pmf[-1]
        n += 1
    probs = np.array(pmf)
    values = x + np.arange(len(pmf), dtype=float)
    return float(probs @ fn(values))


def _z_vec(key: str, values: np.ndarray, scales: dict) -> np.ndarray:
    """``classic_rating.scored_z`` su un array: stessa formula, stessa asimmetria."""
    s = scales.get(key)
    if not s or not s.get("sigma_raw") or not s.get("sigma_z"):
        return np.zeros_like(values, dtype=float)
    u = values / s["sigma_raw"]
    if key in cr.NO_COMPRESS_FEATURES:
        z = u
    else:
        z = np.sign(u) * cr.COMPRESS_K * np.log1p(np.abs(u) / cr.COMPRESS_K)
    z = z / s["sigma_z"]
    credit = (cr.EXPOSURE_CREDIT if key == cr.EXPOSURE_KEY
              else cr.ABSENCE_CREDIT if key in cr.CREDITED_FEATURES else 1.0)
    mu = s.get("mu_z")
    if mu is None or credit >= 1.0:
        return z
    d = z - mu
    return mu + np.where(d >= 0, d, credit * d)


def completed_z(ref_key: str, key: str, value: float, t: float, scales: dict) -> float:
    """La feature come entra nell'indice: osservato piu' completamento predittivo."""
    mu = prior_rate(ref_key, key)
    if key in CONTINUOUS:
        return cr.scored_z(key, value + (1.0 - t) * mu, scales)
    return expected_transform(lambda v: _z_vec(key, v, scales), value, t, mu, dispersion(key))


def neutral_z(ref_key: str, key: str, scales: dict) -> float:
    """La stessa feature per chi non ha giocato un minuto: tutto completamento."""
    cache_key = (ref_key, key)
    if cache_key not in _neutral:
        mu = prior_rate(ref_key, key)
        if key in CONTINUOUS:
            _neutral[cache_key] = cr.scored_z(key, mu, scales)
        else:
            _neutral[cache_key] = expected_transform(
                lambda v: _z_vec(key, v, scales), 0.0, 0.0, mu, dispersion(key))
    return _neutral[cache_key]


# ---------------------------------------------------------------- l'indice
def weights_with_exposure(ref_key: str) -> dict:
    return {**cr.weights_for_role(ref_key), cr.EXPOSURE_KEY: -cr.EXPOSURE_WEIGHT}


def _gain_parts(ref_key: str, reference: dict) -> tuple[float, float, float]:
    r = reference.get(ref_key) or {}
    std = r.get("std") or 0.0
    gain = cr.spread_k_for(ref_key) / std if std else 0.0
    u90 = 90.0 / (90.0 + cr.shrinkage_for(ref_key))
    obs_scale = (cr.UNSHRINK_GAMMA * (1.0 - u90)
                 if r.get("observed_mean") is not None else 0.0)
    return gain, u90, obs_scale


def unit_for(ref_key: str, key: str, reference: dict) -> float:
    """Punti di voto (prima della calibrazione) per un punto di indice di questa
    voce. E' la scala della partita intera: i fatti osservati portano in piu' la
    quota che il voto non attenua (UNSHRUNK_FEATURES), come a 90 minuti."""
    gain, u90, obs_scale = _gain_parts(ref_key, reference)
    return gain * (u90 + (obs_scale if key in cr.UNSHRUNK_FEATURES else 0.0))


def rate_unit(ref_key: str, reference: dict) -> float:
    gain, u90, _ = _gain_parts(ref_key, reference)
    return gain * u90


def intercept(ref_key: str, reference: dict) -> float:
    """Il voto di partita intera a indice zero: la stessa costante di
    ``_raw_vote_from_index`` a 90 minuti, scritta a parte."""
    r = reference.get(ref_key) or {}
    gain, u90, obs_scale = _gain_parts(ref_key, reference)
    return cr.vote_center_for(ref_key) - gain * (
        u90 * (r.get("mean", 0.0) + cr.minute_shift(ref_key, 90, reference))
        + obs_scale * ((r.get("observed_mean") or 0.0)
                       + cr.minute_shift(ref_key, 90, reference,
                                         "observed_by_minute", "observed_mean")))


def evidence_terms(ref_key: str, values: dict, minutes: int,
                   scales: dict | None = None) -> dict:
    """{voce: peso * (z completato - h * z neutro)}: cio' che i minuti VISTI hanno
    aggiunto, voce per voce, rispetto a un giocatore di cui non si e' visto niente.
    A 90 minuti e' ``peso * z`` come nell'indice di sempre."""
    if minutes <= 0:
        return {}
    scales = cr.feature_scales(gk=False) if scales is None else scales
    t = min(minutes, 90) / 90.0
    h = 1.0 - t
    out = {}
    for key, w in weights_with_exposure(ref_key).items():
        if not w:
            continue
        z = completed_z(ref_key, key, values.get(key, 0.0), t, scales)
        if h > 0:
            z -= h * neutral_z(ref_key, key, scales)
        if z:
            out[key] = w * z
    return out


def event_completion(ref_key: str, goals: float, assists: float, t: float) -> float:
    """Il credito ATTESO per gol e assist nei minuti non giocati, oltre la prior:
    chi ha gia' segnato in mezz'ora ha un tasso a posteriori piu' alto e i minuti
    che gli mancano valgono un po' di piu'. Zero a partita intera e a zero minuti."""
    p = _prior(ref_key)
    means = (artifact() or {}).get("event_count_means", {}).get(ref_key) or {}
    c = dispersion("goals")
    h = 1.0 - t
    if h <= 0:
        return 0.0
    rate = 0.0
    for key, observed in (("goals", goals), ("assists", assists)):
        emu = float(means.get(key, 0.0))
        credit = float(p.get(key, 0.0))
        post = posterior_rate(float(observed or 0), t, emu, c)
        rate += credit * (post / emu if emu > 0 else 1.0) - credit
    return h * rate


def base_index(ref_key: str, t: float, reference: dict) -> float:
    """Il voto-indice di chi ha fatto esattamente la media: la costante di partita
    intera pesata ``t`` e, per la frazione non vista, l'ancora neutra piu' la media
    del credito gol/assist che il credito osservato (centrato) toglie subito dopo."""
    old_mean = (goal_impact.role_mean_credit().get(ref_key, 0.0)
                + goal_impact.role_mean_assist_credit().get(ref_key, 0.0))
    return t * intercept(ref_key, reference) + (1.0 - t) * (cr.neutral_pre_scale(ref_key) + old_mean)


def index_vote(ref_key: str, values: dict, minutes: int, goals: float, assists: float,
               reference: dict, scales: dict | None = None) -> dict:
    """Il voto di merito PRIMA di credito gol, mitigazione, disciplina e stadio
    finale, con la sua scomposizione. ``values`` sono ``raw_feature_values`` a 90
    minuti, cioe' i totali NON proiettati: qui i minuti li tratta il modello."""
    scales = cr.feature_scales(gk=False) if scales is None else scales
    t = min(max(minutes, 0), 90) / 90.0
    terms = evidence_terms(ref_key, values, minutes, scales)
    units = {key: unit_for(ref_key, key, reference) for key in terms}
    base = base_index(ref_key, t, reference)
    event = event_completion(ref_key, goals, assists, t)
    v_index = base + event + sum(units[k] * v for k, v in terms.items())
    delta_c, scale, anchor = calibration(ref_key)
    shift = centre_shift(ref_key, t)
    v = anchor + shift + scale * (v_index - anchor)
    return {
        "vote": max(cr.VOTE_MIN, min(cr.VOTE_MAX, v)),
        "unclamped": v, "v_index": v_index, "base_index": base, "event": event,
        "terms": terms, "units": units, "index": sum(terms.values()),
        "scale": scale, "delta_c": delta_c, "shift": shift, "anchor": anchor, "t": t,
    }
