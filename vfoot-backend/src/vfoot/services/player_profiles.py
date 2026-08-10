"""Per-player profiles derived from real StatsBomb data, shared by the
simulation engine and the lineup/formation UI.

Everything here is descriptive of a player's *spatial habits* over the available
matches: where they act (footprint), the role that implies (spatially inferred,
no position labels), and how much/often they play (minutes). It is the seed of a
per-matchday predictive model — for now it summarises the season without leakage
concerns (the materialised league is historical)."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict

from django.core.cache import cache
from django.db.models import Case, F, FloatField, Max, Sum, Value, When

from realdata.models import Match, MatchAppearance, PlayerZoneFeature
from realdata.services.sofascore_adapter import METHOD_UNPLACED

_ZONE_RE = re.compile(r"^Z_(\d+)_\d+$")


def zone_col(zone_key: str) -> int | None:
    m = _ZONE_RE.match(zone_key)
    return int(m.group(1)) if m else None


def role_from_footprint(footprint: dict[str, float]) -> str:
    """Coarse role inferred from where the player acts (footprint = normalised
    presence over zones, sum=1). GK touch almost only their own box (col-0 share
    high); outfielders separate by the column centre of gravity."""
    col_share: dict[int, float] = defaultdict(float)
    for zone_key, presence in footprint.items():
        col = zone_col(zone_key)
        if col is not None:
            col_share[col] += presence
    if not col_share:
        return "MID"
    avg_col = sum(col * share for col, share in col_share.items())
    if col_share.get(0, 0.0) >= 0.6 or avg_col < 0.5:
        return "GK"
    if avg_col < 1.9:
        return "DEF"
    if avg_col < 2.5:
        return "MID"
    return "ATT"


def average_column(footprint: dict[str, float]) -> float:
    total = 0.0
    for zone_key, presence in footprint.items():
        col = zone_col(zone_key)
        if col is not None:
            total += col * presence
    return round(total, 3)


def _who(player_ids) -> str:
    """Impronta dell'INSIEME dei giocatori, indipendente dall'ordine: due chiamate
    con la stessa rosa in ordine diverso devono trovare la stessa voce, altrimenti
    la cache si riempie di copie della stessa risposta."""
    return hashlib.sha1(",".join(str(i) for i in sorted(player_ids)).encode()).hexdigest()[:12]


def _data_fp(competition_season_id: int | None) -> str:
    """Impronta dei DATI, cioè la parte che rende la cache sicura invece che
    pericolosa: cambia appena una partita finita viene reimportata, e con essa
    cambia la chiave. Stesso mestiere e stessa funzione che usa classic_pagella."""
    from vfoot.services.classic_pagella import data_version

    return data_version(competition_season_id) if competition_season_id else "-"


def _footprint_cache_key(player_ids, as_of_matchday, competition_season_id) -> str:
    return (f"vfoot:player_footprints:{competition_season_id or '-'}:{as_of_matchday}"
            f":{_data_fp(competition_season_id)}:{_who(player_ids)}")


def player_footprints(player_ids: list[int], as_of_matchday: int | None = None,
                      competition_season_id: int | None = None) -> dict[int, dict[str, float]]:
    """{player_id: {zone_key: presence_share}} from touches (sum=1). When
    as_of_matchday is given, only matches BEFORE it count (no leakage: you set a
    lineup for matchday N knowing only matchdays < N).

    ONE SEASON, the one the caller chose — the same season `player_form` and
    `player_minutes` describe. Without it the cutoff was a matchday NUMBER compared
    across every season at once, which produced a shape nobody would have asked
    for: of the seasons before, matchdays 1-21 counted and 22-38 did not. Neither
    "this year" nor "the whole career", just an artefact of comparing a number
    without looking at which season it belonged to. Measured on one squad: 3728
    rows from the current season and 3010 from the one before.

    Summed BY THE DATABASE. The zone shares are a ratio, so the division has to
    stay here, but the summing does not: it was 6738 rows crossing into Python to
    produce a few hundred numbers, on every request.
    """
    ids = [int(p) for p in player_ids]
    if not ids:
        return {}

    key = _footprint_cache_key(ids, as_of_matchday, competition_season_id)
    hit = cache.get(key)
    if hit is not None:
        return {int(p): z for p, z in hit.items()}

    # A footprint is a claim about position, so the unplaced rows a live match's
    # light round writes are not part of it (see sofascore_adapter.METHOD_UNPLACED).
    qs = (PlayerZoneFeature.objects.filter(feature_key="touches", player_id__in=ids)
          .exclude(source_method=METHOD_UNPLACED))
    if competition_season_id is not None:
        qs = qs.filter(match__competition_season_id=competition_season_id)
    if as_of_matchday is not None:
        qs = qs.filter(match__matchday__lt=as_of_matchday)

    raw: dict[int, dict[str, float]] = defaultdict(dict)
    for player_id, zone_key, total in (qs.values("player_id", "zone_key")
                                       .annotate(total=Sum("value", output_field=FloatField()))
                                       .values_list("player_id", "zone_key", "total")):
        raw[int(player_id)][str(zone_key)] = float(total or 0.0)

    footprints: dict[int, dict[str, float]] = {}
    for player_id, zones in raw.items():
        total = sum(zones.values())
        if total > 0:
            footprints[player_id] = {z: round(v / total, 5) for z, v in zones.items()}
    cache.set(key, footprints, None)
    return footprints


# Quante giornate guarda il giudizio sull'IMPIEGO. Sei: un mese e mezzo di
# campionato, abbastanza da non farsi ingannare da una panchina isolata e poco da
# ricordarsi di un titolare che ha smesso di giocare a novembre.
#
# La stagione intera, che era la base di prima, risponde a un'altra domanda —
# "quanto ha giocato quest'anno" — e per la domanda che il fantallenatore fa
# davvero, cioè "lo schiero sabato?", invecchia male: a marzo un titolare
# infortunato da due mesi continuava a leggersi «titolare abituale» perché le
# ventidue partite di prima pesavano più delle ultime otto.
MINUTES_WINDOW = 6


def player_minutes(player_ids: list[int], as_of_matchday: int | None = None,
                   competition_season_id: int | None = None,
                   window: int = MINUTES_WINDOW) -> dict[int, dict]:
    """{player_id: {appearances, starts, avg_minutes, recent_*}} sulle partite
    disponibili (solo prima di as_of_matchday e di una stagione, quando dati).

    I campi ``recent_`` guardano solo le ultime ``window`` giornate: sono quelli
    da cui si ricava l'impiego. Gli altri restano sull'intera stagione, perché
    «36 presenze» è un fatto della stagione e non va riscritto ogni domenica.
    """
    agg: dict[int, dict] = defaultdict(lambda: {"appearances": 0, "starts": 0, "minutes": 0,
                                                "r_appearances": 0, "r_minutes": 0})
    qs = MatchAppearance.objects.filter(player_id__in=player_ids)
    if competition_season_id is not None:
        qs = qs.filter(match__competition_season_id=competition_season_id)
    if as_of_matchday is not None:
        qs = qs.filter(match__matchday__lt=as_of_matchday)

    # L'ULTIMA GIORNATA GIOCATA DAL CAMPIONATO. Due sorgenti sbagliate, entrambe
    # scartate: il fondo del CALENDARIO metterebbe la finestra su giornate che
    # nessuno ha ancora giocato, e ogni giocatore risulterebbe fermo da sei turni;
    # le PRESENZE di questi giocatori la sposterebbero addosso a loro — un
    # infortunato che non gioca dalla quattordicesima porterebbe la finestra alla
    # quattordicesima, dove risulta titolare, cioè esattamente il caso che questo
    # cambio esiste per raccontare. La finestra è un fatto del campionato, quindi
    # si legge dalle partite finite.
    last_md = as_of_matchday - 1 if as_of_matchday is not None else (
        Match.objects
        .filter(status=Match.STATUS_FINISHED,
                **({"competition_season_id": competition_season_id}
                   if competition_season_id is not None else {}))
        .aggregate(m=Max("matchday"))["m"] or 0
    )
    first_md = max(1, last_md - window + 1)
    # Quante giornate ha davvero, la finestra: a inizio stagione sono meno di
    # `window`, e dividere per sei quando se ne sono giocate due direbbe che non
    # gioca mai nessuno.
    window_size = max(0, last_md - first_md + 1) if last_md else 0

    rows = qs.values_list("player_id", "minutes_played", "is_starter", "match__matchday")
    for player_id, minutes, is_starter, matchday in rows:
        a = agg[int(player_id)]
        mins = int(minutes or 0)
        a["appearances"] += 1
        a["minutes"] += mins
        if is_starter:
            a["starts"] += 1
        # NELLA FINESTRA CONTANO I MINUTI GIOCATI, non le convocazioni. Altrove
        # ``appearances`` conta ogni convocazione, panchina inclusa — è la
        # definizione del dato — ma qui la domanda è «quante volte è sceso in
        # campo», e contare le panchine produceva la frase autocontraddittoria
        # «in campo 6 volte, 0′ di media» per un rincalzo mai entrato.
        if matchday is not None and mins > 0 and first_md <= int(matchday) <= last_md:
            a["r_appearances"] += 1
            a["r_minutes"] += mins
    out: dict[int, dict] = {}
    for player_id, a in agg.items():
        apps, r_apps = a["appearances"], a["r_appearances"]
        out[player_id] = {
            "appearances": apps,
            "starts": a["starts"],
            "avg_minutes": round(a["minutes"] / apps, 1) if apps else 0.0,
            "recent_appearances": r_apps,
            "recent_avg_minutes": round(a["r_minutes"] / r_apps, 1) if r_apps else 0.0,
            "recent_window": window_size,
        }
    return out


def minutes_label(avg_minutes: float, appearances: int, total_matches: int,
                  has_history: bool = False) -> str:
    """high / medium / low: quanto ci si può aspettare di vederlo in campo.

    Si legge sulle ULTIME giornate (v. MINUTES_WINDOW), non sulla stagione: è una
    previsione su sabato prossimo, e una previsione la fa la settimana scorsa.

    Due misure insieme, perché ognuna da sola inganna. Le PRESENZE sole
    promuoverebbero il subentrante che entra al 90° ogni domenica; i MINUTI soli
    promuoverebbero chi ha giocato una partita intera a ottobre e più niente. Il
    tag chiede entrambe le cose: che ci sia spesso, e che quando c'è resti in
    campo.

    'unknown' quando non c'è NIENTE da guardare: nessuna giornata giocata dal
    campionato, e nessuna storia alle spalle. Dare del panchinaro a un giocatore
    di cui non si sa nulla sarebbe un'affermazione inventata.

    Ma zero presenze nella finestra NON è mancanza di informazione quando il
    giocatore in stagione ha giocato: è l'informazione più importante che questo
    tag possa dare — non scende in campo da sei giornate — e va detta. È il caso
    dell'infortunato e del fuori rosa, cioè esattamente quelli che non si vogliono
    schierare; leggendo solo ``appearances`` finivano senza etichetta, che a
    schermo si vede come «nessun problema».
    """
    if total_matches <= 0:
        return "unknown"
    if appearances == 0:
        return "low" if has_history else "unknown"
    play_share = appearances / total_matches
    if play_share >= 0.6 and avg_minutes >= 60:
        return "high"
    if play_share >= 0.3 and avg_minutes >= 30:
        return "medium"
    return "low"


def _form_cache_key(player_ids, params, scales, as_of_matchday, window,
                    competition_season_id) -> str:
    """Chiave che cambia da sé quando cambia una qualunque delle cose da cui il
    risultato dipende: i giocatori, la finestra, i PESI e i DATI.

    L'ultimo pezzo e' quello che rende la cache sicura, ed e' lo stesso mestiere
    che fa ``classic_pagella.data_version``: conta le partite finite della stagione
    e il loro ultimo timbro, quindi si sposta appena una partita passata viene
    reimportata. Una chiave che non lo contenesse servirebbe numeri vecchi senza
    dire niente -- il modo esatto in cui il listone si e' gia' rotto una volta.
    """
    weights = repr((sorted((k, params[k]) for k in params),
                    sorted((k, scales[k]) for k in scales))).encode()
    fp = hashlib.sha1(weights).hexdigest()[:12]
    return (f"vfoot:player_form:{competition_season_id or '-'}:{as_of_matchday}"
            f":{window}:{fp}:{_data_fp(competition_season_id)}:{_who(player_ids)}")


def player_form(
    player_ids: list[int],
    params: dict[str, float],
    scales: dict[str, float],
    as_of_matchday: int | None = None,
    window: int = 6,
    competition_season_id: int | None = None,
) -> dict[int, float]:
    """Expected per-match contribution from RECENT form: the calibration-weighted
    net value (Σ param·value/scale over zones & features) of each player's last
    `window` matchdays before the cutoff, averaged per match. Errors carry their
    negative weight, so a sloppy spell drags the number down.

    ONE SEASON, the one the caller chose. Without `competition_season_id` the
    window is a matchday RANGE and nothing else, so "the last six matchdays"
    silently included matchdays 16-21 of the season before as well — measured, 45%
    of the rows read, and 17 form values out of 23 wrong because of it. Which
    season to describe is already decided upstream (the lineup view falls back to
    the previous one when the current has not started); `player_minutes` has always
    honoured that decision, and this simply stops being the one that ignores it.

    Summed BY THE DATABASE, not in Python. The old shape pulled every zone-feature
    row of every player — 34k rows to produce two dozen numbers — and that cost is
    paid per request: alone it is 60ms, but five concurrent requests took 2.8s,
    forty times worse per request rather than five, because the row conversion
    holds the GIL while SQLite pages thrash. Aggregating leaves 196 rows.
    """
    ids = [int(p) for p in player_ids]
    if not ids:
        return {}

    key = _form_cache_key(ids, params, scales, as_of_matchday, window,
                          competition_season_id)
    hit = cache.get(key)
    if hit is not None:
        # Le chiavi tornano dal JSON come stringhe: rimesse a int, altrimenti il
        # chiamante trova un dizionario che a lui sembra vuoto.
        return {int(k): v for k, v in hit.items()}

    # Solo le feature che hanno UN PESO E UNA SCALA: sono 14 su 46, e le altre 32
    # venivano lette, trasferite e buttate via dall'`if w and s`.
    usable = [k for k in params if params.get(k) and scales.get(k)]
    if not usable:
        return {}

    qs = PlayerZoneFeature.objects.filter(player_id__in=ids, feature_key__in=usable)
    if competition_season_id is not None:
        qs = qs.filter(match__competition_season_id=competition_season_id)
    if as_of_matchday is not None:
        qs = qs.filter(match__matchday__lt=as_of_matchday,
                       match__matchday__gte=as_of_matchday - window)

    # Due CASE, e non un peso gia' diviso: cosi' l'aritmetica resta w * (value / s),
    # nello stesso ordine di prima. Precalcolare w/s sposterebbe l'ultima cifra, e
    # su un numero che alimenta i voti non e' una liberta' da prendersi in silenzio.
    w_case = Case(*[When(feature_key=k, then=Value(float(params[k]))) for k in usable],
                  output_field=FloatField())
    s_case = Case(*[When(feature_key=k, then=Value(float(scales[k]))) for k in usable],
                  output_field=FloatField())
    rows = (qs.annotate(_w=w_case, _s=s_case)
              .values("player_id", "match_id")
              .annotate(total=Sum(F("_w") * (F("value") / F("_s")),
                                  output_field=FloatField()))
              .values_list("player_id", "match_id", "total"))

    by_player: dict[int, list[float]] = defaultdict(list)
    for pid, _mid, total in rows:
        by_player[int(pid)].append(float(total or 0.0))
    out = {pid: round(sum(cs) / len(cs), 3) for pid, cs in by_player.items() if cs}
    # Senza scadenza, come le altre cache di questo progetto: a farla decadere e'
    # la chiave, non l'orologio.
    cache.set(key, out, None)
    return out


def player_profiles(
    player_ids: list[int],
    total_matches: int = 0,
    as_of_matchday: int | None = None,
    params: dict[str, float] | None = None,
    scales: dict[str, float] | None = None,
    competition_season_id: int | None = None,
) -> dict[int, dict]:
    """Full per-player profile: role, footprint, avg column, minutes summary, and
    (when params/scales given) recent-form expected contribution. With
    as_of_matchday everything is computed from matches before that matchday only."""
    ids = [int(pid) for pid in player_ids]
    footprints = player_footprints(ids, as_of_matchday=as_of_matchday,
                                   competition_season_id=competition_season_id)
    minutes = player_minutes(ids, as_of_matchday=as_of_matchday,
                             competition_season_id=competition_season_id)
    form = (
        player_form(ids, params, scales, as_of_matchday=as_of_matchday,
                    # La stessa stagione che riceve player_minutes. Passarla a una
                    # sola delle due e' cio' che faceva leggere alla forma anche
                    # l'anno prima, mentre l'impiego guardava solo quest'anno.
                    competition_season_id=competition_season_id)
        if params and scales
        else {}
    )
    # `total_matches` non serve più a giudicare l'impiego (lo fa la finestra
    # delle ultime giornate, dentro player_minutes) e resta nella firma per i
    # chiamanti che lo passano.
    profiles: dict[int, dict] = {}
    for pid in ids:
        fp = footprints.get(pid, {})
        # Il default vale per chi non ha NESSUNA riga di presenza (un neoacquisto,
        # un giovane mai convocato) e deve avere la stessa forma di una vera:
        # dimenticare qui una chiave nuova non rompe il calcolo, rompe la pagina.
        mins = minutes.get(pid, {"appearances": 0, "starts": 0, "avg_minutes": 0.0,
                                 "recent_appearances": 0, "recent_avg_minutes": 0.0,
                                 "recent_window": 0})
        profiles[pid] = {
            "role": role_from_footprint(fp) if fp else "MID",
            "avg_col": average_column(fp),
            "footprint": fp,
            "appearances": mins["appearances"],
            "starts": mins["starts"],
            "avg_minutes": mins["avg_minutes"],
            # I numeri della finestra viaggiano col profilo, e non per completezza:
            # sono ciò che rende il tag verificabile a schermo — «4 volte su 6,
            # 71′ di media» dice da sé perché c'è scritto «titolare abituale».
            "recent_appearances": mins["recent_appearances"],
            "recent_avg_minutes": mins["recent_avg_minutes"],
            "recent_window": mins["recent_window"],
            "minutes_label": minutes_label(
                mins["recent_avg_minutes"], mins["recent_appearances"], mins["recent_window"],
                # Ha una storia in questa stagione: allora zero presenze recenti
                # significa «non gioca piu'», non «non lo conosciamo».
                has_history=mins["appearances"] > 0),
            "form": form.get(pid, 0.0),
        }
    return profiles
