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
distribuzione, ``Y`` binomiale negativa.

DALLA REVISIONE DELLA SOSTA (ottobre 2026, schema 3) la struttura e' quella che
NON PUO' derivare, per costruzione e per qualunque peso:

    V(t) = base_r + s_r * k_r(t) * SUM_k u_k w_k [ z_k(t) - z0_k ]  +  (1 - t) * c90_r + atteso

* ``base_r`` e' COSTANTE nei minuti: spariscono la rampa, lo spostamento del
  centro, la curva per minuto. Il ritorno verso la media di chi ha giocato poco
  EMERGE dal completamento (ha 80 minuti di prior), non da una correzione;
* ``z0_k`` e' la media predittiva A PRIORI della feature, calcolata dal modello
  coi pesi correnti e non letta da una reference: a zero minuti ogni voce vale
  esattamente zero, in media vale zero a ogni t (martingala), a 90 minuti e'
  l'indice meno la sua media;
* le grandezze CONTINUE (esposizione, xA, sga_post) sono Poisson COMPOSTI: eventi
  a tasso incerto — tiri subiti nelle proprie zone, passaggi chiave, tiri — per la
  MARCA del singolo gesto (quota di carica, xA del passaggio, xGOT-xG del tiro),
  e il neutro e' l'attesa di z sulla predittiva, non z della media (Jensen: la
  compressione e' concava, e valutare z sulla media sovrastimava di 2-5 centesimi
  a prior corretto). Il valore difensivo ha incrementi gaussiani indipendenti;
* le DISPERSIONI sono per (ruolo, grandezza): quelle per famiglia erano sbagliate
  di un fattore 2 nei due sensi secondo il ruolo;
* ``k_r(t) = 1 + (1 - t) q / (1 + q t)`` e' il FATTORE COMUNE: ogni voce da sola e'
  tarata (pendenza ~1 del voto a 90' su quello al minuto m), il totale no, perche'
  in una buona giornata un giocatore va bene su molte cose insieme e il
  completamento voce per voce non usa il passaggio riuscito per prevedere il
  contrasto che verra'. Un parametro per ruolo, stimato senza giudici (q ~ 0,25
  per tutti e tre), k(1) = 1;
* lo STADIO FINALE della scala va DENTRO l'attesa (v. ``predictive_sigma`` e
  ``classic_rating.scale_saturation``): comprime sopra il centro, quindi la media
  dei voti finali scende man mano che la dispersione cresce coi minuti — anche
  con un completamento perfetto. Il voto giusto al minuto m e' E[stadio(V90) |
  visto], con predittiva gaussiana di larghezza sigma_r * sqrt(1 - t).

E l'ESPRESSIVITA': ``s_r`` non minimizza piu' l'errore contro un giudice rumoroso
(la scala che minimizza l'errore e' correlazione x rapporto delle dispersioni: uno
schiacciamento da regressione, 0,56-0,68). E' la scala precedente per 1,4, che
porta la dispersione del voto a quella dei giudici e riempie i 5 e i 4,5 senza
perdere accordo; ``base_r`` e' risolta perche' la media a 90' di ogni ruolo non si
muova. La misura e' in experiments-revisione-sosta/PROPOSTA_10-10.md.

Sopra il completamento stanno i PESI (tabelle di ``classic_rating``) e la
calibrazione per ruolo qui sotto, in ``data/bayesian_completion.json``.

IL MODELLO E' TARATO SU UNA REFERENCE PRECISA. Scale delle feature e dispersioni
della reference congelata sono INGRESSI della taratura. Per questo l'artifact pinna
l'impronta dei pesi con cui la reference fu calibrata e lo sha del file: chi
ricalibra la reference o tocca un peso deve rifare anche questa taratura, e
``check_pins`` lo dice.

Tutto quel che segue l'indice — credito gol/assist, mitigazione, disciplina,
saturazione — e' quello di ``classic_rating``. Il portiere non passa di qui: ha il
suo canale (``keeper_channel``).
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

log = logging.getLogger(__name__)

ARTIFACT_PATH = Path(settings.BASE_DIR) / "vfoot" / "data" / "bayesian_completion.json"
SCHEMA_VERSION = 3
OUTFIELD = (Player.ROLE_DEF, Player.ROLE_MID, Player.ROLE_FWD)
# Le grandezze che NON sono conteggi.
CONTINUOUS = frozenset({"defensive_value", "expected_assists", "xg_shots", "sga_post",
                        cr.EXPOSURE_KEY})
# I Poisson composti: la grandezza e il CONTEGGIO degli eventi che la generano,
# come lo porta ``raw_feature_values`` (l'esposizione ha il suo, ``_n_exposure``,
# che il calcolo dell'esposizione restituisce accanto alla carica).
COMPOUND_COUNT_OF = {cr.EXPOSURE_KEY: cr.EXPOSURE_COUNT_KEY,
                     "expected_assists": "key_passes",
                     "sga_post": "shots"}
GAUSSIAN = frozenset({"defensive_value"})
# Quattro famiglie di dispersione condivise: il RIPIEGO per una grandezza che non
# ha una dispersione per ruolo (evento raro, stimatore dei momenti instabile).
CIRCULATION = frozenset({"touches", "passes_completed", "long_balls_completed",
                         "errors_bad_passes"})
DECISIVE = frozenset({"shots", "shots_on_target", "shots_blocked", "clearances_off_line",
                      "errors_led_to_goal", "errors_led_to_shot", "penalties_won",
                      "penalties_conceded", "goals", "assists"})
# Massa di probabilita' trascurata nella somma predittiva.
TAIL = 1e-11
_MAX_TERMS = 20000
# I nodi delle quadrature: Gamma per le marche positive (quantili equispaziati),
# Gauss-Hermite per quelle con segno e per la gaussiana.
_GAMMA_Q = (np.arange(24) + 0.5) / 24.0
_GH_X, _GH_W = np.polynomial.hermite.hermgauss(15)


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
    """Prior, dispersioni, marche e calibrazione, letti una volta. ``None`` se il
    file manca: allora il voto torna al modello precedente, e lo dice."""
    global _artifact, _artifact_loaded
    if _artifact_loaded:
        return _artifact
    _artifact_loaded = True
    if not ARTIFACT_PATH.exists():
        log.error("bayesian_completion.json manca: i minuti non giocati si votano "
                  "col modello precedente (proiezione a 90 e attenuazione).")
        return None
    data = json.loads(ARTIFACT_PATH.read_text())
    if data.get("schema_version") != SCHEMA_VERSION:
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
    Il portiere ha il suo canale; la scala aggregata (giocatore senza ruolo)
    resta al modello precedente, che per lei non e' mai stata ritarata."""
    return ref_key in OUTFIELD and artifact() is not None


def calibration(ref_key: str) -> tuple[float, float]:
    """``(base, scala)``: V = base + scala * k(t) * evidenza + credito atteso.

    ``base`` e' il voto di merito (pre-stadio) di chi ha fatto ESATTAMENTE la
    media a priori del ruolo, a qualunque minuto; ``scala`` e' s_r."""
    c = (artifact() or {}).get("calibration", {}).get(ref_key)
    if not c:
        return cr.neutral_pre_scale(ref_key), 1.0
    return float(c["base"]), float(c["scale"])


def common_factor(ref_key: str, t: float) -> float:
    """k(t) = 1 + (1 - t) q / (1 + q t): quanto lo scostamento visto al minuto m
    dice del resto della partita. k(1) = 1."""
    q = float((artifact() or {}).get("common_factor", {}).get(ref_key, 0.0))
    if q <= 0:
        return 1.0
    return 1.0 + (1.0 - t) * q / (1.0 + q * t)


def predictive_sigma(ref_key: str, t: float) -> float:
    """La larghezza della predittiva del voto pre-stadio a 90' dato quel che si e'
    visto fino a t: sigma_r * sqrt(1 - t). Zero a partita intera."""
    s = float((artifact() or {}).get("predictive_sigma", {}).get(ref_key, 0.0))
    return s * math.sqrt(max(0.0, 1.0 - t))


def _prior(ref_key: str) -> dict:
    return (artifact() or {}).get("role_priors", {}).get(ref_key) or {}


def prior_rate(ref_key: str, key: str) -> float:
    return float((_prior(ref_key).get("raw") or {}).get(key, 0.0))


def dispersion(key: str, ref_key: str | None = None) -> float:
    """Var(lambda)/mu^2 di QUESTA grandezza per QUESTO ruolo; la famiglia e' il
    ripiego per chi non ha una stima propria."""
    art = artifact() or {}
    if ref_key:
        own = (art.get("dispersions_by_role", {}).get(ref_key) or {}).get(key)
        if own is not None:
            return float(own)
    return float(art.get("dispersions", {}).get(family(key), 0.0))


def mark(ref_key: str, key: str) -> dict:
    """La marca del singolo gesto per un Poisson composto: {rate, c, m1, var,
    floor} — tasso degli eventi per 90, sua dispersione, media e varianza della
    marca, fondo per 90 (la parte della grandezza che non passa per un evento
    contato, come la xA senza passaggio chiave)."""
    return (artifact() or {}).get("marks", {}).get(ref_key, {}).get(key) or {}


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


def _expected_z_over(key: str, scales: dict, base: float, mean: float, var: float,
                     positive: bool) -> float:
    """E[z(base + Y)] con Y di media e varianza date: Gamma se positiva, Normale
    altrimenti. A varianza nulla e' z della media."""
    if var <= 1e-14:
        return float(_z_vec(key, np.array([base + mean]), scales)[0])
    if positive and mean > 0:
        shape = mean * mean / var
        x, w = _gamma_rule(shape)
        return float(w @ _z_vec(key, base + (var / mean) * x, scales))
    y = mean + math.sqrt(2 * var) * _GH_X
    return float((_GH_W * _z_vec(key, base + y, scales)).sum() / math.sqrt(math.pi))


_GAMMA_RULES: dict[float, tuple[np.ndarray, np.ndarray]] = {}
_GAMMA_NODES = 16


def _gamma_rule(shape: float) -> tuple[np.ndarray, np.ndarray]:
    """Nodi e pesi (normalizzati a 1) per E[g(X)] con X ~ Gamma(shape, 1): la
    quadratura di Gauss-Laguerre generalizzata, dal problema agli autovalori
    della matrice di Jacobi (Golub-Welsch). Esatta sui polinomi fino al grado
    2n - 1, senza scipy, e valida anche per shape < 1. Le forme si arrotondano
    al millesimo per riusare la regola: il costo e' un eigh 16x16."""
    k = round(max(shape, 1e-3), 3)
    rule = _GAMMA_RULES.get(k)
    if rule is None:
        alpha = k - 1.0
        n = _GAMMA_NODES
        i = np.arange(n, dtype=float)
        diag = 2 * i + alpha + 1
        off = np.sqrt(i[1:] * (i[1:] + alpha))
        jac = np.diag(diag) + np.diag(off, 1) + np.diag(off, -1)
        vals, vecs = np.linalg.eigh(jac)
        rule = (np.maximum(vals, 0.0), vecs[0] ** 2)
        if len(_GAMMA_RULES) > 4096:
            _GAMMA_RULES.clear()
        _GAMMA_RULES[k] = rule
    return rule


def compound_z(ref_key: str, key: str, value: float, n_seen: float, t: float,
               scales: dict) -> float:
    """E[z(visto + somma delle marche degli eventi che mancano)].

    Eventi mancanti N ~ binomiale negativa (tasso a posteriori dagli eventi
    VISTI, non dal valore); somma delle marche | N >= 1 ai primi due momenti,
    Gamma se la marca e' positiva (esposizione, xA), Normale se ha segno
    (sga_post); atomo in N = 0. Il valore difensivo e' un processo a incrementi
    gaussiani: Normale(h mu, h var)."""
    h = 1.0 - t
    p = mark(ref_key, key)
    if key in GAUSSIAN:
        if not p:
            return float(_z_vec(key, np.array([value]), scales)[0])
        return _expected_z_over(key, scales, value, h * float(p.get("mu", 0.0)),
                                h * float(p.get("var", 0.0)), False)
    if not p or h <= 1e-12:
        return float(_z_vec(key, np.array([value]), scales)[0])
    base = value + h * float(p.get("floor", 0.0))
    mu, c = float(p["rate"]), max(float(p["c"]), 1e-6)
    a = 1.0 / c + n_seen
    lam = (mu + c * mu * n_seen) / (1 + c * mu * t)
    en = h * lam
    vn = en + en * en / a
    p0 = (a / (a + en)) ** a                       # P(nessun altro evento)
    if p0 > 1 - 1e-9:
        return float(_z_vec(key, np.array([base]), scales)[0])
    en1 = en / (1 - p0)
    en2 = (vn + en * en) / (1 - p0)
    m1, v = float(p["m1"]), float(p["var"])
    mean = en1 * m1
    var = en1 * v + (en2 - en1 * en1) * m1 * m1
    z0 = float(_z_vec(key, np.array([base]), scales)[0])
    return p0 * z0 + (1 - p0) * _expected_z_over(key, scales, base, mean, var,
                                                 key != "sga_post")


def completed_z(ref_key: str, key: str, value: float, t: float, scales: dict,
                n_seen: float = 0.0) -> float:
    """La feature come entra nell'indice: osservato piu' completamento predittivo."""
    if key in COMPOUND_COUNT_OF or key in GAUSSIAN:
        return compound_z(ref_key, key, value, n_seen, t, scales)
    if key in CONTINUOUS:
        return cr.scored_z(key, value + (1.0 - t) * prior_rate(ref_key, key), scales)
    return expected_transform(lambda v: _z_vec(key, v, scales), value, t,
                              prior_rate(ref_key, key), dispersion(key, ref_key))


def neutral_z(ref_key: str, key: str, scales: dict) -> float:
    """La stessa feature per chi non ha giocato un minuto: tutto completamento.
    E' la media predittiva A PRIORI di z, calcolata dal modello: il neutro di ogni
    voce, a ogni minuto."""
    cache_key = (ref_key, key)
    if cache_key not in _neutral:
        _neutral[cache_key] = completed_z(ref_key, key, 0.0, 0.0, scales, 0.0)
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
    """Punti di voto (prima della scala del ruolo) per un punto di indice di questa
    voce. E' la scala della partita intera del modello precedente, conservata
    perche' la calibrazione e' stata risolta su di lei: i fatti osservati portano
    la quota in piu' che il voto non attenuava (UNSHRUNK_FEATURES)."""
    gain, u90, obs_scale = _gain_parts(ref_key, reference)
    return gain * (u90 + (obs_scale if key in cr.UNSHRUNK_FEATURES else 0.0))


def rate_unit(ref_key: str, reference: dict) -> float:
    gain, u90, _ = _gain_parts(ref_key, reference)
    return gain * u90


def evidence_terms(ref_key: str, values: dict, minutes: int,
                   scales: dict | None = None) -> dict:
    """{voce: peso * (z completato - z neutro)}: cio' che i minuti VISTI hanno
    aggiunto, voce per voce, rispetto alla media a priori del ruolo. A 90 minuti
    e' ``peso * (z - z0)``, cioe' l'indice di sempre meno la sua media."""
    if minutes <= 0:
        return {}
    scales = cr.feature_scales(gk=False) if scales is None else scales
    t = min(minutes, 90) / 90.0
    out = {}
    for key, w in weights_with_exposure(ref_key).items():
        if not w:
            continue
        n_seen = float(values.get(COMPOUND_COUNT_OF.get(key, ""), 0.0) or 0.0)
        z = completed_z(ref_key, key, values.get(key, 0.0), t, scales, n_seen)
        z -= neutral_z(ref_key, key, scales)
        if z:
            out[key] = w * z
    return out


def expected_credit_rate(ref_key: str) -> float:
    """Il credito di gol e assist per 90 minuti del giocatore medio del ruolo, in
    punti di voto: quel che i minuti NON visti valgono a priori."""
    p = _prior(ref_key)
    return float(p.get("goals", 0.0)) + float(p.get("assists", 0.0))


def event_completion(ref_key: str, goals: float, assists: float, t: float) -> float:
    """Il credito ATTESO per gol e assist nei minuti non giocati, OLTRE la prior:
    chi ha gia' segnato in mezz'ora ha un tasso a posteriori piu' alto e i minuti
    che gli mancano valgono un po' di piu'. Zero a partita intera e a zero minuti."""
    p = _prior(ref_key)
    means = (artifact() or {}).get("event_count_means", {}).get(ref_key) or {}
    h = 1.0 - t
    if h <= 0:
        return 0.0
    rate = 0.0
    for key, observed in (("goals", goals), ("assists", assists)):
        emu = float(means.get(key, 0.0))
        credit = float(p.get(key, 0.0))
        post = posterior_rate(float(observed or 0), t, emu, dispersion(key, ref_key))
        rate += credit * (post / emu if emu > 0 else 1.0) - credit
    return h * rate


def index_vote(ref_key: str, values: dict, minutes: int, goals: float, assists: float,
               reference: dict, scales: dict | None = None) -> dict:
    """Il voto di merito PRIMA di credito gol osservato, mitigazione, disciplina e
    stadio finale, con la sua scomposizione. ``values`` sono ``raw_feature_values``
    a 90 minuti, cioe' i totali NON proiettati: qui i minuti li tratta il modello.

    ``credit_rest`` e' il credito atteso di gol e assist nei minuti non visti
    (prior piu' aggiornamento), FUORI dalla scala del ruolo come lo e' il credito
    osservato che ``voto_puro_for_match`` somma dopo."""
    scales = cr.feature_scales(gk=False) if scales is None else scales
    t = min(max(minutes, 0), 90) / 90.0
    terms = evidence_terms(ref_key, values, minutes, scales)
    units = {key: unit_for(ref_key, key, reference) for key in terms}
    evidence = sum(units[k] * v for k, v in terms.items())
    base, scale = calibration(ref_key)
    k = common_factor(ref_key, t)
    merit = base + scale * k * evidence
    event = event_completion(ref_key, goals, assists, t)
    credit_rest = (1.0 - t) * expected_credit_rate(ref_key) + event
    v = merit + credit_rest
    return {
        "vote": max(cr.VOTE_MIN, min(cr.VOTE_MAX, v)),
        "unclamped": v, "merit": merit, "base": base, "scale": scale, "k": k,
        "evidence": evidence, "terms": terms, "units": units,
        "index": sum(terms.values()), "event": event, "credit_rest": credit_rest,
        "t": t, "sigma": predictive_sigma(ref_key, t),
    }
