"""Real-match classic pagella — per-player voto puro + bonus/malus = fantavoto
for a single REAL match (e.g. a Serie A fixture), for the whole squad that
appeared, not a fantasy lineup.

This is the shared, reusable version of the fantavoto assembly that previously
lived (cache-coupled, path-hardcoded) inside ``seed_classic_demo_league``. It is
DB-only and portable, so it serves both the real-championship match-detail view
and, later, the live classic scoring path.

Output shape mirrors the frontend ``ClassicTeamDetail`` / ``ClassicPlayerLine``
so the existing ``ClassicMatchDetail`` component renders it directly.

Known scope note: own goals, penalty saves and penalty misses are NOT in the DB
(they were read from the provider cache by the seed); they are omitted here and
default to 0. Goals, assists (MatchAppearance) and cards (MatchDisciplinaryEvent)
— the dominant bonus/malus terms — are fully covered.
"""
from __future__ import annotations

import hashlib
import logging
from collections import defaultdict

from django.core.cache import cache
from django.db.models import Count, Max, Sum

from realdata.models import (
    CARD_RED,
    CARD_SECOND_YELLOW,
    CARD_YELLOW,
    Match,
    MatchAppearance,
    MatchDisciplinaryEvent,
    MatchShot,
    Player,
)
from vfoot.models import LeaguePlayerRole
from vfoot.services.classic_rating import (
    build_reference, defensive_exposure, current_role_map, voto_puro_for_match,
    _minutes_map, _per_match_player_totals,
)
from vfoot.services.vote_explanation import explain, role_average_terms, to_sentence
from vfoot.services.vote_reference import (
    fixed_reference, fixed_role_averages, scoring_fingerprint,
)

log = logging.getLogger(__name__)

CARD_MALUS = {CARD_YELLOW: 0.5, CARD_SECOND_YELLOW: 1.0, CARD_RED: 1.0}
OWN_GOAL_MALUS = 2.0  # classic fantacalcio: -2 per own goal (from raw_stats.ownGoals)
PENALTY_MISSED_MALUS = 3.0  # classic fantacalcio: -3 per missed penalty (MatchShot situation)
PENALTY_SAVED_BONUS = 3.0   # classic fantacalcio: +3 to the GK who saves a penalty
ROLE_TO_LINEUP = {"POR": "GK", "DIF": "DEF", "CEN": "MID", "ATT": "ATT"}
# Pagella reading order: goalkeeper -> defence -> midfield -> attack.
ROLE_ORDER = {"POR": 0, "DIF": 1, "CEN": 2, "ATT": 3}
GOAL_THRESHOLDS = (66.0, 72.0, 78.0, 84.0, 90.0, 96.0)


def classic_goals(total: float) -> int:
    return sum(1 for t in GOAL_THRESHOLDS if total >= t)


def data_version(competition_season_id: int) -> str:
    """Cheap fingerprint of a season's played data: it changes exactly when a
    match is finalized, so anything derived from the season can be cached under it."""
    agg = (Match.objects
           .filter(competition_season_id=competition_season_id,
                   status=Match.STATUS_FINISHED)
           .aggregate(n=Count("id"), last=Max("data_checked_at")))
    last = agg["last"].isoformat() if agg["last"] else "-"
    return f"{agg['n'] or 0}:{last}"


def matchday_data_version(competition_season_id: int, real_matchday: int) -> str:
    """Impronta dei dati di UN turno — quella che si muove mentre il turno si gioca.

    ``data_version`` qui non servirebbe a niente, e la differenza è il motivo per
    cui questa esiste: quella conta le partite FINITE della stagione, quindi
    durante un turno in corso non si sposta di un millimetro — cioè esattamente
    quando i voti cambiano ogni due minuti.

    Legge due cose. Della partita, i campi che il tick scrive DOPO aver importato
    (stato, punteggio, ``data_ready`` e i due timbri): l'ordine conta, perché una
    lettura che capitasse in mezzo salverebbe i dati nuovi sotto la chiave
    vecchia, e il timbro che segue la manda subito in soffitta — mai il contrario.
    Delle presenze, quattro somme: nessuna riga porta una data di modifica, e un
    reimport a mano dei tabellini non tocca la partita, quindi senza queste
    passerebbe inosservato.
    """
    rows = list(
        Match.objects.filter(competition_season_id=competition_season_id,
                             matchday=real_matchday)
        .order_by("id")
        .values_list("id", "status", "data_ready", "home_goals", "away_goals",
                     "data_checked_at", "data_imported_at")
    )
    apps = MatchAppearance.objects.filter(match_id__in=[r[0] for r in rows]).aggregate(
        n=Count("id"), mins=Sum("minutes_played"),
        goals=Sum("goals"), assists=Sum("assists"))
    blob = repr((rows, sorted(apps.items()))).encode()
    return hashlib.sha1(blob).hexdigest()[:16]


def get_reference(competition_season_id: int) -> dict:
    """The per-role (mean, std) the voto puro is z-scored against.

    Prefers the FIXED calibration frozen on a completed season: a reference that
    moved with the season in progress has no value on matchday 1 and makes a 6
    mean different things over time. Falls back to computing it from the given
    season only when no calibration file exists yet, so a fresh checkout still
    works — with the live-drift caveat that fix exists to remove."""
    fixed = fixed_reference()
    if fixed is not None:
        return fixed
    key = f"vfoot:voto_reference:{competition_season_id}:{data_version(competition_season_id)}"
    hit = cache.get(key)
    if hit is not None:
        return hit
    data = build_reference(competition_season_id)
    cache.set(key, data, None)
    return data


def get_role_averages(competition_season_id: int) -> dict:
    """Per-role average contribution of each feature — the yardstick a vote
    explanation is read against. Season-wide and expensive, so it is cached under
    the same data version as the reference and refreshes when a match is
    finalized. Prefers the FIXED calibration for the same reason get_reference
    does: the explanation must subtract the same mean the vote does, so if the
    vote is on a frozen scale the explanation has to be too."""
    fixed = fixed_role_averages()
    if fixed is not None:
        return fixed
    key = (f"vfoot:role_term_averages:{competition_season_id}:"
           f"{data_version(competition_season_id)}")
    hit = cache.get(key)
    if hit is not None:
        return hit
    data = compute_role_averages(competition_season_id)
    cache.set(key, data, None)
    return data


def compute_role_averages(competition_season_id: int,
                          scales: dict | None = None) -> dict:
    """Per-role average contribution of each feature, over one season's rated
    appearances. The building block behind both the cached live path and the
    frozen calibration; kept separate so both use exactly the same computation.

    ``scales`` lets the calibration command pass the spreads it has just built:
    reading the frozen file there would use the PREVIOUS calibration, so the
    explanation's means would be on a different scale from the vote they explain.
    Shares ``_reference_population`` with the reference itself, so the two can
    never be computed over different games.
    """
    from vfoot.services.classic_rating import _reference_population
    return role_average_terms(_reference_population(competition_season_id),
                              scales=scales)


def _cards_for_match(match_id: int) -> dict[int, dict]:
    cards: dict[int, dict] = defaultdict(
        lambda: {"yellow": 0, "red": 0, "second_yellow": 0, "malus": 0.0})
    for pid, ct in (MatchDisciplinaryEvent.objects
                    .filter(match_id=match_id)
                    .values_list("player_id", "card_type")):
        rec = cards[pid]
        if ct in rec:
            rec[ct] += 1
        rec["malus"] += CARD_MALUS.get(ct, 0.0)
    return cards


def _missed_penalties_for_match(match_id: int) -> dict[int, int]:
    """{player_id: count of penalties taken and NOT scored} — the -3 malus events."""
    out: dict[int, int] = defaultdict(int)
    for pid in (MatchShot.objects
                .filter(match_id=match_id, situation="penalty", is_goal=False)
                .exclude(player__isnull=True)
                .values_list("player_id", flat=True)):
        out[pid] += 1
    return out


def _keeper_at(match_id: int, keeper_apps=None):
    """Returns ``at(side, minute) -> goalkeeper_id`` for the keeper ON PITCH for that
    side at that minute. With a substitution the starter is credited up to the minute
    he was replaced (his minutes_played), the sub after. One keeper -> always him.

    ``keeper_apps`` is an optional iterable of (side, pid, is_starter, minutes) — the
    keepers as the caller identified them (e.g. by resolved POR role, which also picks
    up a keeper recognised from his features but missing the provider flag). Omitted,
    it falls back to the ``is_goalkeeper`` provider flag."""
    if keeper_apps is None:
        keeper_apps = (MatchAppearance.objects
                       .filter(match_id=match_id, player__is_goalkeeper=True)
                       .values_list("side", "player_id", "is_starter", "minutes_played"))
    gks: dict[str, list] = defaultdict(list)
    for side, pid, starter, mins in keeper_apps:
        gks[side].append({"pid": pid, "starter": bool(starter), "mins": mins or 0})

    def at(side: str, minute) -> int | None:
        cands = gks.get(side, [])
        if not cands:
            return None
        if len(cands) == 1:
            return cands[0]["pid"]
        starter = next((c for c in cands if c["starter"]), cands[0])
        if minute is not None and minute > starter["mins"]:
            sub = next((c for c in cands if not c["starter"]), None)
            if sub is not None:
                return sub["pid"]
        return starter["pid"]
    return at


_OPP_SIDE = {"home": "away", "away": "home"}


def _penalties_saved_for_match(match_id: int) -> dict[int, int]:
    """{goalkeeper_id: penalties he SAVED} — the +3 bonus events. A saved penalty is
    a shot situation='penalty' with outcome 'save' (not merely off target / woodwork);
    fantacalcio credits it to the keeper of the side defending it — the opposite side
    from the taker, and the one on the pitch at the shot minute."""
    saves = list(MatchShot.objects
                 .filter(match_id=match_id, situation="penalty", is_goal=False,
                         shot_type="save")
                 .values_list("team_side", "minute"))
    if not saves:
        return {}
    at = _keeper_at(match_id)
    out: dict[int, int] = defaultdict(int)
    for taker_side, minute in saves:
        gk = at(_OPP_SIDE.get(taker_side, ""), minute)
        if gk is not None:
            out[gk] += 1
    return out


def _goals_conceded_by_keeper(match_id: int, keeper_apps=None) -> dict[int, int]:
    """{goalkeeper_id: goals conceded WHILE ON PITCH} — the GK -1/goal malus. Charging
    the whole team's goals-against to whichever keeper appeared double-counts a keeper
    change and hands a subbed-off keeper goals he never faced (Okoye gd16: fanta 0, we
    had 5). Each goal (opponent shot is_goal, own goals included as they count for the
    opponent) is charged to the keeper on the pitch for the conceding side at its
    minute. Falls back to the score-based total for a side whose goals aren't all in
    the shotmap, so the malus is never understated. ``keeper_apps`` — see _keeper_at."""
    goals = list(MatchShot.objects
                 .filter(match_id=match_id, is_goal=True)
                 .values_list("team_side", "minute"))
    m = Match.objects.filter(id=match_id).values("home_goals", "away_goals").first()
    hg, ag = (int((m or {}).get("home_goals") or 0), int((m or {}).get("away_goals") or 0))
    at = _keeper_at(match_id, keeper_apps)
    out: dict[int, int] = defaultdict(int)
    # per-side shotmap goal count, to detect an incomplete shotmap
    shot_against = {"home": 0, "away": 0}
    charged = {"home": 0, "away": 0}
    for scoring_side, minute in goals:
        conceding = _OPP_SIDE.get(scoring_side, "")
        shot_against[conceding] = shot_against.get(conceding, 0) + 1
        gk = at(conceding, minute)
        if gk is not None:
            out[gk] += 1
            charged[conceding] += 1
    # if a side's goals-against aren't fully in the shotmap, top up its starter keeper
    for side, total in (("home", ag), ("away", hg)):  # home concedes the away goals
        missing = total - shot_against.get(side, 0)
        if missing > 0:
            gk = at(side, 0)  # minute 0 -> the starter
            if gk is not None:
                out[gk] += missing
    return out


def match_in_progress(match) -> bool:
    """The ball is still rolling: nobody's performance is complete yet.

    NOT the same as "not final". A match that has ended and whose data the provider
    has not settled is unstable but OVER — every verdict on it is legitimate, it may
    just move by a tenth. This is the narrower state where a verdict would be a
    statement about a match that has not happened.
    """
    return match.status == Match.STATUS_LIVE and not match.data_ready


def elapsed_minutes(apps) -> int:
    """The clock of a match in progress, read off the appearances.

    There is no minute on the ``Match`` row — the provider ships one only inside
    the live payload, which we do not keep — but whoever has been on longest has
    been on since kick-off, so his minutes ARE the elapsed time. Free: the number
    was already being computed to decide who is on the pitch.

    Stoppage time is included exactly as the provider counts it, so this can read
    past 45 or 90. It is a floor, not a broadcast clock: nobody's minutes tick up
    between two imports, so it steps forward at the import's pace.
    """
    return max((a.minutes_played or 0 for a in apps), default=0)


def players_on_pitch(apps) -> set[int]:
    """Of a match IN PROGRESS, who is on the field right now.

    The clock comes from ``elapsed_minutes``; anyone below it has left the field
    (substituted, or sent off), and his performance IS complete even though the
    match is not.

    A minute of tolerance because the provider rounds, and starters count at
    minute zero: at kick-off the whole XI reads 0', and calling them "not on the
    pitch" would be exactly the misreading this exists to remove.
    """
    elapsed = elapsed_minutes(apps)
    return {
        a.player_id
        for a in apps
        if (a.is_starter or (a.minutes_played or 0) > 0)
        and (a.minutes_played or 0) >= elapsed - 1
    }


def _line(app: MatchAppearance, declared_role: str, vp_rows: dict,
          cards: dict, conceded: int, explanation: dict | None = None,
          missed_pens: int = 0, saved_pens: int = 0,
          on_pitch: bool = False) -> dict:
    pid = app.player_id
    c = cards.get(pid, {})
    card_malus = c.get("malus", 0.0)
    own_goals = int((app.raw_stats or {}).get("ownGoals") or 0)
    row = vp_rows.get(pid)
    # Prefer the role the rating layer actually SCORED him as: when the Player row
    # carries no classic_role_seed it may have inferred one (a keeper gives himself
    # away through his gk_* features). Falling straight back to "CEN" used to put
    # a keeper in midfield and cost him the -1/goal conceded.
    role = declared_role or (row or {}).get("role") or ""
    role_known = bool(declared_role) or bool((row or {}).get("role_known"))
    lrole = ROLE_TO_LINEUP.get(role, "MID")
    events = {"goals": app.goals, "assists": app.assists,
              "yellow": c.get("yellow", 0),
              "red": c.get("red", 0) + c.get("second_yellow", 0),
              "own_goals": own_goals, "missed_penalties": missed_pens,
              "saved_penalties": saved_pens}
    base = {"player_id": pid,
            "name": app.player.short_name or app.player.full_name or str(pid),
            "role": role or "CEN", "role_known": role_known,
            "lineup_role": lrole,
            # Goals conceded while on the pitch (keepers only; 0 for outfielders) —
            # consumed by the classic scoring keeper-clean-sheet modifier.
            "conceded": conceded,
            "minutes": app.minutes_played, "entered": False,
            "entered_for": None, "replaced_by": None, "events": events}

    # Voto puro from the heuristic. Keepers now have their OWN channel (anchored on
    # goals prevented), so they are no longer pinned to a flat baseline.
    # s.v. has THREE legitimate causes, and they are not the same thing: he never
    # came on, he played too little to be read, or we are missing the match. Say
    # which — an unexplained s.v. on a player who scored reads as a scoring bug.
    if row is None:
        # The rating layer only emits a row for a player who was on the pitch, so
        # an unused substitute lands here — and calling that "missing data" says
        # the opposite of the truth. We have his data; it says he never played.
        # The genuine hole is a player with minutes and no performance behind
        # them, which is rare enough to be worth telling apart rather than
        # burying under the same badge as the whole bench.
        #
        # Unless he is ON THE PITCH: at the fifth minute a player can perfectly
        # well have no feature rows yet (the heatmap has nothing to spread), and
        # both of the other two answers would be false — he has neither stayed on
        # the bench nor gone missing from our data.
        reason = ("in_campo" if on_pitch
                  else "non_entrato" if not app.minutes_played else "dati_mancanti")
        return {**base, "sv": True, "sv_reason": reason,
                "voto_puro": None, "bonus": 0.0, "malus": 0.0, "fantavoto": None}
    if not row.get("rated") or row.get("voto_puro") is None:
        return {**base, "sv": True,
                "sv_reason": "in_campo" if on_pitch else "impiego_insufficiente",
                "voto_puro": None, "bonus": 0.0, "malus": 0.0, "fantavoto": None}
    base["sv_reason"] = None
    # Why this vote. Only for a rated player: explaining a vote that does not
    # exist would be inventing one.
    if explanation is not None:
        base["explanation"] = explanation
        base["explanation_text"] = to_sentence(explanation)
    vp = float(row["voto_puro"])
    bonus = 3.0 * app.goals + 1.0 * app.assists + PENALTY_SAVED_BONUS * saved_pens
    # A keeper also carries the classic -1 per goal conceded. This does NOT double
    # count: his voto puro measures performance against the xG ON TARGET he faced
    # (shot difficulty), the malus is the raw goal count — the usual voto-puro /
    # bonus-malus separation. Own goals (-2 each) sit here too: the voto puro is
    # feature-based and blind to them (they never enter its shot features), so the
    # malus is the ONLY place the own goal registers — no double penalty.
    malus = (card_malus + OWN_GOAL_MALUS * own_goals
             + PENALTY_MISSED_MALUS * missed_pens
             + (float(conceded) if role == "POR" else 0.0))
    return {**base, "sv": False, "voto_puro": round(vp, 1),
            "bonus": bonus, "malus": malus, "fantavoto": round(vp + bonus - malus, 1)}


def match_of_player(cs_id: int, matchday: int, player_id: int):
    """La partita VERA in cui quel giocatore ha giocato quel turno, o None.

    Si parte dalla presenza e non dal club (v. ``match_resolver.authoritative_match``,
    che risolve dal contratto aperto): qui la domanda non e' "chi gioca oggi" ma
    "da dove viene questo voto", e il voto ha dietro una MatchAppearance — quella
    di chi si e' trasferito a stagione in corso compresa, che dal club di oggi non
    si troverebbe piu'. Se per una qualunque ragione ce ne fossero due, vince la
    partita conclusa: la sagoma del rinvio non ha voti da spiegare.
    """
    return (Match.objects
            .filter(id__in=MatchAppearance.objects
                    .filter(player_id=player_id)
                    .values_list("match_id", flat=True),
                    competition_season_id=cs_id, matchday=matchday)
            .order_by("-data_ready", "-id")
            .first())


def vote_ledger(match, player_id: int) -> dict | None:
    """Le voci che il riassunto NON mostra, per un giocatore di una partita.

    Il pannello del voto ne tiene tre e chiude con "altre N voci": su una
    prestazione buona dappertutto quelle N sono la maggior parte del voto, e questa
    e' la loro lista. Si calcola l'intera pagella (una sola volta per partita, in
    cache) perche' e' l'unico modo di essere certi che i numeri siano gli STESSI che
    hanno prodotto la riga: un secondo percorso di calcolo, prima o poi, dissente.

    La chiave della cache porta l'impronta del TURNO, non della stagione: a partita
    in corso i voti si muovono a ogni giro del tick, e ``data_version`` non se ne
    accorgerebbe (conta le partite finite).
    """
    # L'IMPRONTA DEL MODELLO nella chiave, non solo quella dei dati. Senza, dopo
    # una ritaratura questa cache serviva per un'ora la scomposizione VECCHIA
    # accanto al voto NUOVO — e il campo ``voto`` qui dentro contraddiceva quello
    # in cima al pannello. E' lo stesso difetto gia' corretto una volta per il
    # listone (v. player_ratings) e per l'indice di giornata.
    key = (f"vfoot:vote_ledger:{match.id}:"
           f"{matchday_data_version(match.competition_season_id, match.matchday)}"
           f":{scoring_fingerprint()}")
    rows = cache.get(key)
    if rows is None:
        pag = pagella_for_match(match, ledger=True)
        rows = {}
        for side in ("home", "away"):
            for group in ("starters", "bench"):
                for line in pag[side][group]:
                    why = line.get("explanation")
                    # ``explain`` torna una forma VUOTA quando non c'e' niente da
                    # spiegare (nessuna feature pesata, o il ruolo senza taratura):
                    # la si riconosce dal voto che non c'e', e quel giocatore non
                    # entra nel registro invece di entrarci con dei buchi.
                    if not why or "voto" not in why:
                        continue
                    rows[line["player_id"]] = {
                        "player_id": line["player_id"],
                        "name": line["name"],
                        "match_id": match.id,
                        "minutes": why["minutes"],
                        # Il voto ricalcolato ADESSO. Chi ha in mano un referto
                        # congelato puo' confrontarlo col proprio: se i due non
                        # coincidono, quel tabellino e' stato scritto con un'altra
                        # taratura del modello e il registro non lo spiega.
                        "voto": why["voto"],
                        "subtotal": why["subtotal"],
                        "other_points": why["other_points"],
                        "other_count": why["other_count"],
                        "terms": why["other_terms"],
                        # Le stesse voci raccolte per senso, col subtotale di ogni
                        # famiglia: e' la forma in cui l'elenco si legge invece di
                        # scorrere. ``terms`` resta perche' e' il dettaglio dentro
                        # ogni gruppo, e perche' un client vecchio continua a
                        # funzionare senza sapere niente dei gruppi.
                        "groups": why["other_groups"],
                        "tiny": why["other_tiny"],
                    }
        cache.set(key, rows, 3600)
    return rows.get(player_id)


def _team_detail(starters: list[dict], bench: list[dict]) -> dict:
    # Order by role (GK->DEF->MID->ATT), then by fantavoto desc within a role,
    # with senza-voto players last in their role band.
    def _sort(ls):
        return sorted(ls, key=lambda l: (ROLE_ORDER.get(l["role"], 9),
                                         l["fantavoto"] is None,
                                         -(l["fantavoto"] or 0)))

    starters, bench = _sort(starters), _sort(bench)
    total = round(sum(l["fantavoto"] for l in starters
                      if l["fantavoto"] is not None), 1)
    return {
        "starters": starters, "bench": bench, "substitutions": [],
        "base_total": total, "total": total, "goals": classic_goals(total),
        "defense": {"eligible": False, "reason": "non applicabile (partita reale)",
                    "avg": None, "bonus": 0.0, "applied": 0.0, "mode": None},
    }


def pagella_for_match(match, reference: dict | None = None, league=None,
                      averages: dict | None = None,
                      full_explanation: bool = False,
                      ledger: bool = False) -> dict:
    """Full per-team pagella for a real match. Returns {'home': ClassicTeamDetail,
    'away': ClassicTeamDetail}. Only meaningful for a match with imported
    appearances (a finished, data-loaded fixture).

    Pass ``league`` whenever the pagella is read INSIDE a league: classic roles are
    fixed when that league's listone opens and never move again, so its frozen
    LeaguePlayerRole is the authority. ``Player.classic_role_seed`` is a live seed that
    the next Transfermarkt import can rewrite — reading it here would let a league's
    match detail contradict its own listone. The league is tied to one reference
    season, so its snapshot already carries the season: no per-season role needed.

    ``full_explanation`` attaches the per-feature ledger (every weighted feature with
    its value, its standing on the population scale, its weight and the vote points
    it moved) to each explained line. Off by default: it is several times the size of
    the vote it explains, which suits an analysis page and bloats an API response.

    ``ledger`` attaches the shorter, spoken one: the entries the summary did NOT
    show, each with a name — what the app's "altre N voci" line opens onto. Also off
    by default, and for a sharper reason than size: this payload is re-fetched on
    every live push while a match is being played, so it carries only what the
    screen is showing.
    """
    if reference is None:
        reference = get_reference(match.competition_season_id)

    apps = list(MatchAppearance.objects.filter(match=match).select_related("player"))
    # While the match is being PLAYED, the minutes/involvement gate is asking a
    # question nobody can answer yet. Whoever is on the pitch is rated on what he
    # has done so far; whoever has already come off is judged normally, because for
    # him the match IS over. See classic_rating.voto_puro_for_match(always_rate=).
    on_pitch = players_on_pitch(apps) if match_in_progress(match) else set()
    vp_rows = {r["player_id"]: r
               for r in voto_puro_for_match(match, reference, always_rate=on_pitch)}
    if averages is None:
        averages = get_role_averages(match.competition_season_id)
    feats = _per_match_player_totals([match.id])
    mins = _minutes_map([match.id])
    exposures = defensive_exposure([match.id], mins)
    cards = _cards_for_match(match.id)
    missed_pens = _missed_penalties_for_match(match.id)
    saved_pens = _penalties_saved_for_match(match.id)
    pids = [a.player_id for a in apps]
    # Base: the season's disambiguated role (same source the voto puro was scored
    # against), so a league-less match detail agrees with the vote it shows.
    roles = {pid: r for pid, r in
             current_role_map().items() if pid in pids}
    if league is not None:
        # Frozen roles win. Players with no frozen row (e.g. someone sold before
        # the listone was drawn up) keep the season role as a fallback.
        #
        # AND HERE THE TWO ROLES PART, DELIBERATELY. What this dict changes is the
        # LABEL and the lineup slot; the vote in ``vp_rows`` was already computed
        # above, by a function that builds its own ``current_role_map()`` and never
        # sees a league. So a player frozen ATT here is shown and fielded as an
        # attacker while his voto puro is z-scored against midfielders — and his
        # explanation says midfielders too, because ``explain`` reads the role off
        # the vote's own row, not off this one.
        #
        # It is a decision, not an oversight (11/08/2026, AGENTS.md "Classic Role
        # Resolution"): one vote per player per match, the same in every league.
        # Measured before choosing: 0.028 of a vote on average, and the SHOWN
        # half-point moves in 2 appearances out of 36. The alternative — rescoring
        # per league — costs a pagella per league instead of one per match.
        # Whoever reverses it passes these roles into ``voto_puro_for_match`` and
        # adds the league to the pagella cache key; both, or the cache serves one
        # league's votes to another.
        roles.update(LeaguePlayerRole.objects
                     .filter(league=league, player_id__in=pids)
                     .values_list("player_id", "role"))
    hg, ag = int(match.home_goals or 0), int(match.away_goals or 0)

    # Goals conceded are charged to the keeper on the pitch (not the whole team's
    # total to each keeper who appeared). Identify keepers the same way the malus
    # does — the resolved POR role — so a keeper recognised only from his features
    # (no provider flag) is still credited.
    def _is_por(a):
        return (roles.get(a.player_id) or (vp_rows.get(a.player_id) or {}).get("role")) == "POR"
    keeper_apps = [(a.side, a.player_id, a.is_starter, a.minutes_played)
                   for a in apps if _is_por(a)]
    conceded_by = _goals_conceded_by_keeper(match.id, keeper_apps)

    buckets = {"home": {"starters": [], "bench": []},
               "away": {"starters": [], "bench": []}}
    for a in apps:
        # Goals conceded WHILE THIS keeper was on the pitch (0 for outfielders; a
        # keeper change no longer charges both keepers the whole team's goals-against).
        conceded = conceded_by.get(a.player_id, 0)
        key = (match.id, a.player_id)
        row = vp_rows.get(a.player_id)
        why = None
        if row and row.get("rated") and key in feats:
            why = explain(row.get("role") or roles.get(a.player_id, ""), feats[key],
                          mins.get(key, 0), reference, averages,
                          exposures.get(key, 0.0),
                          result_nudge=row.get("result_nudge", 0.0),
                          red_adjustment=row.get("red_adjustment", 0.0),
                          own_goal_adjustment=row.get("own_goal_adjustment", 0.0),
                          penalty_adjustment=row.get("penalty_adjustment", 0.0),
                          # Il credito dei gol e i gol che lo producono: senza il
                          # dettaglio la riga non saprebbe come chiamarsi, e senza
                          # il numero la spiegazione non tornerebbe col voto.
                          goal_adjustment=row.get("goal_adjustment", 0.0),
                          goal_detail=row.get("goal_detail"),
                          assist_adjustment=row.get("assist_adjustment", 0.0),
                          assist_detail=row.get("assist_detail"),
                          # WHY the sending-off / own goal cost what it cost: the
                          # drops are graded (severity x man-down time; deflection vs
                          # own error), so naming only the event would leave most of
                          # the number unexplained
                          red_detail=row.get("red_detail"),
                          own_goal_detail=row.get("own_goal_detail"),
                          # an assist is a bonus, not a feature: the explanation says
                          # so when the pass behind it carried little expected value
                          assists=a.assists or 0,
                          # the per-feature ledger: off by default (it is far bigger
                          # than the vote it explains), on for the analysis report
                          full=full_explanation,
                          # le voci non mostrate, nominate una per una: le chiede
                          # solo chi apre il dettaglio di un voto (v. vote_ledger)
                          ledger=ledger)
        line = _line(a, roles.get(a.player_id, ""), vp_rows, cards, conceded, why,
                     missed_pens=missed_pens.get(a.player_id, 0),
                     saved_pens=saved_pens.get(a.player_id, 0),
                     on_pitch=a.player_id in on_pitch)
        buckets[a.side]["starters" if a.is_starter else "bench"].append(line)

    return {
        "home": _team_detail(buckets["home"]["starters"], buckets["home"]["bench"]),
        "away": _team_detail(buckets["away"]["starters"], buckets["away"]["bench"]),
    }


# Come si chiama, a schermo, l'esito di un tiro. L'AUTOGOL non e' fra le chiavi
# del fornitore (per lui e' un 'goal' come gli altri, v. ``is_own_goal``) e sta qui
# sotto una chiave nostra: chiamarlo "gol" nel pannello di chi l'ha subito era il
# modo piu' rapido di far perdere fiducia a tutto il resto.
SHOT_OUTCOME_IT = {"goal": "gol", "save": "parato", "post": "legno",
                   "block": "murato", "miss": "fuori", "own": "autogol"}
# E da dove veniva.
SHOT_SITUATION_IT = {
    "regular": "azione", "assisted": "su assist", "fast-break": "in contropiede",
    "set-piece": "su palla inattiva", "corner": "su corner",
    "free-kick": "su punizione", "penalty": "su rigore",
    "throw-in-set-piece": "su rimessa",
}
# Le feature che UN TIRO muove. Toglierlo dai totali significa togliergli queste.
_SHOT_TYPE_FEATURE = {"post": "shots_post", "goal": "shots_goal",
                      "save": "shots_saved", "miss": "shots_off",
                      "block": "shots_blocked"}
# Le sei voci che COMPONGONO la riga «conclusioni» del riassunto. Sono le stesse
# di ``MERGES`` in vote_explanation e devono restarlo: questa e' la quantita' a cui
# i tiri devono sommare, e se le due liste divergessero la sezione tornerebbe a non
# quadrare senza che niente lo dica.
_SHOT_FAMILY = ("sga_post", "xg_shots", "shots_on_target", "shots",
                "shots_blocked", "shots_off")
# Oltre questo numero di tiri si rinuncia allo Shapley esatto. Costa 2^n
# valutazioni del solo sotto-indice: a 12 sono 4096, una quarantina di ms; il
# massimo di un'intera stagione e' 10 (1024, 11 ms misurati), quindi il ripiego non
# si e' mai presentato. Esiste perche' un endpoint non deve poter esplodere su un
# dato che non abbiamo ancora visto.
_SHAPLEY_MAX_SHOTS = 12


def shot_detail(match, player_id: int) -> dict:
    """I tiri di un giocatore in una partita, con quanto vale CIASCUNO.

    La riga «conclusioni» del riassunto e' il netto di sei feature su tutti i suoi
    tiri, e da quel numero solo non si capisce ne' che cosa abbia fatto ne' perche'.
    I dati per aprirla ci sono tutti (``MatchShot``: minuto, xG, xGOT, esito,
    situazione), e questa e' la loro forma leggibile.

    RITORNA LA SEZIONE INTERA, non il solo elenco: ``shots``, il ``baseline`` e il
    ``total``, che sommano. Perche' una tabella che non torna col numero sopra di
    se' non e' un dettaglio, e' una contraddizione — e con la mappa appesa sotto la
    riga del riassunto era esattamente cosi': su Conceicao in Juventus-Parma la riga
    diceva +0.24 e i due tiri sotto +0.49 e +0.04.

    IL VALORE DI UN TIRO E' UNO SHAPLEY. La domanda «quanto vale questo tiro» non
    ha una risposta sola: le feature passano per una compressione concava, quindi il
    contributo di un tiro dipende da quali altri tiri gli stanno accanto. Il
    leave-one-out — che stava qui fino al 30/08/2026 — ne sceglie UNA, sempre la
    stessa: il margine dell'ultimo tolto da un insieme pieno, cioe' il punto piu'
    piatto della curva. Nessun tiro paga mai il tratto ripido, e la somma non fa il
    totale: su Esposito in Fiorentina-Inter, +1.02 contro un effetto congiunto di
    +1.31. Lo Shapley media il margine del tiro su TUTTI gli ordini in cui i tiri
    potevano arrivare, ed e' l'unica ripartizione che tenga insieme quattro cose —
    somma esatta, simmetria fra tiri identici, zero a un tiro che non cambia niente,
    linearita' nelle feature. Il tiro fuori da 0.15 di xG di Esposito passa cosi'
    da +0.004 a −0.031: cambia SEGNO, ed e' il segno giusto (sopra il pareggio del
    modello un tiro fuori toglie).

    RISCALARE il leave-one-out fino a farlo tornare — la via breve — e' stato
    misurato e scartato: conserva le proporzioni del LOO, che sono gia' l'artefatto,
    e il fattore va da −10.7 a +9.2 perche' riga e tiri hanno segno opposto nel 35%
    dei casi (chi ha tirato POCO ha la riga negativa e i suoi tiri positivi). Su
    Thuram in Fiorentina-Inter avrebbe stampato «tiro −0.25» su un tiro che al voto
    aveva aggiunto.

    IL BASELINE e' la meta' mancante, e non e' un residuo: e' il valore della riga
    per chi non tira affatto, cioe' quanto costa a un attaccante, contro i pari
    ruolo, non aver concluso. Vale −0.28 per un ATT a novanta minuti, ed e' il 96%
    dello scarto che faceva sembrare sbagliata la tabella. Scritto come riga
    propria si legge e si controlla; spalmato sui tiri avrebbe addebitato a un
    gesto reale il prezzo di un'assenza.

    IL CREDITO DEL GOL NON E' QUI. Vive fuori dall'indice (v. ``goal_impact``) e ha
    gia' una riga sua nel riassunto: sommarlo anche al tiro-gol lo faceva leggere
    DUE VOLTE — su Kone' +0.57 nel riassunto e +1.44 sulla mappa, mediana +0.47 di
    troppo sui 112 marcatori misurati.

    Costa 2^n valutazioni del solo sotto-indice delle conclusioni, tutte in memoria:
    sul caso peggiore di un'intera stagione (10 tiri) sono ~8 ms, dentro una
    chiamata che ne pesa una sessantina di database — gli stessi che pagava il
    leave-one-out di prima, che di suo ricalcolava l'indice INTERO una volta per
    tiro. La combinatoria spaventa, l'aritmetica no. Si chiama comunque solo
    quando qualcuno apre il dettaglio di un voto, mai dentro la pagella, che
    viaggia per ventidue giocatori a ogni spinta del punteggio in diretta.
    """
    from math import factorial

    from vfoot.services.classic_rating import (
        SHRINKAGE_MINUTES, appearance_sides, derived_features, feature_scales,
        is_own_goal, scored_z, spread_k_for, weights_for_role,
    )

    empty = {"shots": [], "baseline": 0.0, "total": 0.0}
    key = (match.id, player_id)
    feats = _per_match_player_totals([match.id]).get(key)
    if not feats:
        return empty
    shots = list(MatchShot.objects.filter(match=match, player_id=player_id)
                 .order_by("minute", "id")
                 .values("minute", "xg", "xgot", "is_goal", "shot_type", "situation",
                         "team_side"))
    if not shots:
        return empty
    # L'AUTOGOL non e' una conclusione del giocatore, e i totali non lo contano
    # (v. ``_drop_own_goal_shots``): togliergli il tiro sottrarrebbe da ``feats``
    # una riga che li' dentro non c'e' — che e' esattamente come nasceva il +0.95
    # sull'autogol di Edmundsson, un xGOT sottratto da un totale che non l'aveva
    # mai contenuto. Si mostra lo stesso, col suo nome e a zero: chi l'ha visto in
    # campo deve ritrovarlo qui, e leggere che nel voto delle conclusioni non pesa.
    # Il malus ce l'ha, ed e' una riga sua nel riassunto.
    own_side = appearance_sides([match.id]).get(key)
    for s in shots:
        s["own_goal"] = is_own_goal(s["shot_type"], s["team_side"], own_side)

    mins_map = _minutes_map([match.id])
    mins = mins_map.get(key, 0)
    exposure = defensive_exposure([match.id], mins_map).get(key, 0.0)
    row = voto_puro_row(match, player_id) or {}
    role = row.get("role") or ""
    reference = get_reference(match.competition_season_id)
    if not role or role not in reference or mins <= 0 or not reference[role].get("std"):
        return empty
    scales = feature_scales(gk=role == Player.ROLE_GK)
    weights = weights_for_role(role)

    # La stessa conversione indice -> punti di voto che usa la spiegazione, e per la
    # stessa ragione per cui quella la prende da ``classic_rating``: due formule
    # copiate divergono, e qui il conto DEVE tornare con la riga scritta sopra.
    weight = mins / (mins + SHRINKAGE_MINUTES)
    per_unit = spread_k_for(role) * weight / reference[role]["std"]

    counted = [i for i, s in enumerate(shots) if not s["own_goal"]]
    n = len(counted)

    def _removed(mask):
        """Quanto tolgono, in totale, i tiri SPENTI in ``mask``."""
        gone = defaultdict(float)
        for bit, i in enumerate(counted):
            if mask >> bit & 1:
                continue
            s = shots[i]
            gone["shots"] += 1
            gone["xg_shots"] += s["xg"] or 0.0
            gone["xg_on_target"] += s["xgot"] or 0.0
            if s["is_goal"] or (s["xgot"] or 0.0) > 0:
                gone["shots_on_target"] += 1
            feat = _SHOT_TYPE_FEATURE.get(s["shot_type"])
            if feat:
                gone[feat] += 1
        return gone

    def totals_for(mask):
        """I totali del giocatore coi soli tiri accesi in ``mask``.

        Si SOTTRAE dai totali veri invece di ricostruirli dalla mappa: a maschera
        piena si riottiene esattamente l'indice che ha prodotto il voto, che e' la
        condizione perche' le righe tornino con la riga del riassunto.

        CON IL PAVIMENTO A ZERO, e non per prudenza: i due archivi non sempre
        parlano della stessa partita (v. il controllo qui sotto), e su Moro in
        Torino-Bologna sottrarre l'xGOT del suo gol da un totale che non lo conteneva
        portava ``xg_on_target`` a −0.995 — un giocatore che non tira con
        l'esecuzione peggiore della stagione, e un metro a −1.03 invece di −0.17.
        Un totale negativo non e' uno stato del mondo."""
        gone = _removed(mask)
        if not gone:
            return feats
        t = dict(feats)
        for k, v in gone.items():
            t[k] = max(0.0, (t.get(k) or 0.0) - v)
        return t

    # I DUE ARCHIVI PARLANO DELLA STESSA PARTITA? I totali dell'indice vengono
    # dalle zone del fornitore, la mappa da ``MatchShot``, e nel 3.9% delle righe
    # della 25-26 il canale xGOT non coincide (mediana 0.081, massimo 0.995). Il
    # pavimento qui sopra impedisce l'assurdo, ma non rende vero il numero: la
    # differenza finisce nel metro, che si legge storto (su Esposito il metro di
    # chi NON tira viene positivo). Detto ad alta voce perche' e' un difetto DEI
    # DATI e va corretto li', non compensato qui.
    gap = {k: round((feats.get(k) or 0.0) - v, 3)
           for k, v in _removed(0).items()
           if abs((feats.get(k) or 0.0) - v) > 0.02}
    if gap:
        log.warning("shot map and zone totals disagree for player %s in match %s: "
                    "%s left over after removing every shot — the shooting baseline "
                    "absorbs it", player_id, match.id, gap)

    def value(mask):
        """Il SOLO sotto-indice delle conclusioni. E' l'unica parte che i tiri
        muovono, e restringersi a lei e' quello che rende 2^n accessibile.

        I valori si leggono dai totali senza passare per ``raw_feature_values``:
        le sei voci sono tutte TOTALI (o derivate da totali), e li' quella
        funzione e' l'identita'. La scorciatoia vale finche' vale l'affermazione,
        che e' fissata da un test."""
        t = totals_for(mask)
        t = {**t, **derived_features(t)}
        return sum(weights.get(k, 0.0) * scored_z(k, t.get(k, 0.0), scales)
                   for k in _SHOT_FAMILY)

    full = (1 << n) - 1
    if n <= _SHAPLEY_MAX_SHOTS:
        # I 2^n valori PRIMA e in una lista, non dietro una funzione memoizzata: il
        # doppio ciclo li rilegge n·2^(n-1) volte — diecimila accessi con dieci
        # tiri — e li' il costo non era piu' il calcolo ma la chiamata (30 ms su 66
        # nel profilo). Ora la parte Shapley e' ~8 ms; il resto della funzione e'
        # lavoro di database che pagava anche il leave-one-out di prima
        # (``voto_puro_row`` da solo ne vale 37).
        vals = [value(mask) for mask in range(full + 1)]
        coef = [factorial(r) * factorial(n - r - 1) / factorial(n) for r in range(n)]
        share = [0.0] * n
        for bit in range(n):
            b = 1 << bit
            for sub in range(full + 1):
                if not sub & b:
                    share[bit] += coef[sub.bit_count()] * (vals[sub | b] - vals[sub])
        joint = vals[full] - vals[0]
        empty_value = vals[0]
    else:
        # Ripiego mai osservato in una stagione: il leave-one-out riportato al
        # totale. Non e' lo Shapley e non lo finge — e' l'approssimazione che
        # almeno fa quadrare la sezione, dove l'esatto costerebbe troppo.
        empty_value = value(0)
        vfull = value(full)
        joint = vfull - empty_value
        loo = [vfull - value(full & ~(1 << bit)) for bit in range(n)]
        tot = sum(loo)
        share = [x * (joint / tot) if tot else joint / n for x in loo]

    points = dict(zip(counted, (x * per_unit for x in share)))
    out = []
    for i, s in enumerate(shots):
        own = s["own_goal"]
        out.append({
            "minute": s["minute"],
            "outcome": (SHOT_OUTCOME_IT["own"] if own else
                        SHOT_OUTCOME_IT.get(s["shot_type"], s["shot_type"] or "tiro")),
            "situation": SHOT_SITUATION_IT.get(s["situation"] or "", ""),
            "xg": round(s["xg"] or 0.0, 3),
            "xgot": round(s["xgot"] or 0.0, 3),
            # xGOT − xG: quanto la conclusione ha aggiunto (o tolto) alla palla che
            # aveva. E' la grandezza su cui il modello giudica il tiro, quindi si
            # mostra invece di lasciarla ricavare a chi legge.
            "added": round((s["xgot"] or 0.0) - (s["xg"] or 0.0), 3),
            "points": 0.0 if own else round(points.get(i, 0.0), 3),
        })

    # Il metro: dove sta la riga di chi non ha concluso, rispetto ai pari ruolo.
    mean_terms = get_role_averages(match.competition_season_id).get(role, {})
    baseline = (empty_value - sum(mean_terms.get(k, 0.0) for k in _SHOT_FAMILY)) * per_unit
    return {"shots": out, "baseline": round(baseline, 3),
            "total": round(baseline + joint * per_unit, 3)}


# Le due voci che UN TIRO NELLO SPECCHIO muove nel canale del portiere, e quindi
# la quantità a cui la mappa delle parate deve sommare. Sono anche la famiglia
# ``parate`` del riassunto (v. MERGES in vote_explanation): le due liste devono
# restare la stessa cosa, o la sezione smette di quadrare senza che nulla lo dica.
#
# ``gk_saves_inside_box`` NON C'È, e non per dimenticanza: la mappa non sa dire
# quale parata fosse ravvicinata. La zona del tiro è l'unico indizio, e dedurlo da
# lì (Z_4_1/Z_4_2) coincide col conteggio del fornitore solo nel 76,2% delle 734
# presenze della 25-26, sbagliando quasi sempre per eccesso. Una riga per parata è
# una promessa di esattezza: quella voce resta fuori dalla mappa e continua a
# vivere nel gruppo «Parate e uscite», dove è un numero solo e non finge di essere
# attribuito a un gesto.
_SAVE_FAMILY = ("gk_goals_prevented", "gk_saves")
# Come si chiama, per il portiere, l'esito di un tiro che gli è arrivato addosso.
SAVE_OUTCOME_IT = {False: "parata", True: "gol subito"}


def save_detail(match, player_id: int) -> dict:
    """I tiri nello specchio che un portiere ha affrontato, con quanto vale CIASCUNO.

    È la mappa dei tiri (v. ``shot_detail``) letta dall'altra parte, e per la stessa
    ragione: la riga «gol evitati rispetto ai tiri affrontati» è il netto di due
    feature su tutti i tiri subiti, e da quel numero solo non si capisce se ha fatto
    una parata vera o tre respinte di routine. Su Vicario in Juventus-Parma la riga
    dice +0,37 e sotto ci sono un tiro da 0,640 di xGOT e due da 0,046 e 0,172.

    RITORNA LA SEZIONE INTERA — ``saves``, ``baseline`` e ``total`` — che somma alla
    riga che la intesta. Una tabella che non torna col numero sopra di sé non è un
    dettaglio, è una contraddizione.

    QUALI TIRI. Solo quelli arrivati NELLO SPECCHIO (parati o entrati) e solo quelli
    battuti mentre lui era in campo, risolti con ``_keeper_at`` — la stessa funzione
    che carica i gol al portiere giusto per il malus, così la mappa e il malus non
    possono raccontare due partite diverse. I tiri fuori e quelli murati non ci sono
    perché non sono suoi: il canale del portiere legge quello che ha raggiunto la
    porta, e chi ha guardato quindici conclusioni volare alte ha comunque passato un
    pomeriggio tranquillo.

    IL VALORE DI UNA PARATA È UNO SHAPLEY, per lo stesso motivo delle conclusioni:
    ``gk_saves`` passa per la compressione, quindi il contributo di una parata
    dipende da quante altre ce ne sono accanto — la sesta vale meno della seconda. E
    dal 30/08/2026 passa anche per il CREDITO PER L'ASSENZA, che sotto la media di
    ruolo appiattisce del tutto: togliere una parata a chi ne ha fatte due non costa
    niente su quel conteggio, e la mappa lo mostra invece di nasconderlo in un
    residuo. ``gk_goals_prevented`` invece è esente da compressione
    (NO_COMPRESS_FEATURES) e quindi lineare: su di lei lo Shapley coincide con
    l'xGOT del tiro, che è come dev'essere.

    IL GOL SUBITO È NELLA TABELLA, col suo segno. ``goals_prevented`` è la somma
    degli xGOT affrontati MENO i gol, quindi togliere un gol dai totali vale
    +(1 − xGOT): un gol su un tiro da 0,95 costa quasi niente, uno su un tiro da
    0,15 costa quasi un gol intero. È la cosa che il modello sa dire meglio di
    chiunque e che la riga da sola non diceva.

    IL METRO (``baseline``) è quanto vale la riga per un portiere a cui non è
    arrivato NIENTE nello specchio, contro i pari ruolo. Prima del credito per
    l'assenza era una voragine (non aver parato metteva sotto la media per
    costruzione); ora è quasi zero, ed è il posto in cui quel cambiamento si vede.
    """
    from math import factorial

    from vfoot.services.classic_rating import (
        OWN_GOAL_KEEPER_XGOT_DEFAULT, SHRINKAGE_MINUTES, appearance_sides,
        feature_scales, is_own_goal, raw_feature_values, scored_z, spread_k_for,
        weights_for_role,
    )

    empty = {"saves": [], "baseline": 0.0, "total": 0.0}
    key = (match.id, player_id)
    feats = _per_match_player_totals([match.id]).get(key)
    if not feats:
        return empty
    reference = get_reference(match.competition_season_id)
    rows = voto_puro_for_match(match, reference)
    row = next((r for r in rows if r["player_id"] == player_id), None) or {}
    role = row.get("role") or ""
    mins = _minutes_map([match.id]).get(key, 0)
    if (role != Player.ROLE_GK or role not in reference or mins <= 0
            or not reference[role].get("std")):
        return empty

    sides = appearance_sides([match.id])
    side = sides.get(key)
    # I PORTIERI COME LI RICONOSCE LA PAGELLA, non come li tagga il fornitore.
    # ``_keeper_at`` senza argomenti si fida di ``Player.is_goalkeeper``, e per un
    # portiere che quel tag non ce l'ha — riconosciuto solo dalle sue feature, che
    # e' il caso per cui ``keeper_apps`` esiste — la funzione non troverebbe nessuno
    # per la sua parte e OGNI tiro verrebbe scartato: mappa vuota, senza un errore.
    # Gli stessi ruoli risolti che usa il malus dei gol subiti, cosi' la mappa e il
    # malus non possono raccontare due partite diverse.
    por = {r["player_id"] for r in rows if r.get("role") == Player.ROLE_GK}
    keeper_apps = [(a["side"], a["player_id"], a["is_starter"], a["minutes_played"])
                   for a in MatchAppearance.objects.filter(match=match)
                   .values("side", "player_id", "is_starter", "minutes_played")
                   if a["player_id"] in por]
    at = _keeper_at(match.id, keeper_apps)
    faced = []
    for sh in (MatchShot.objects.filter(match=match).exclude(team_side=side)
               .order_by("minute", "id")
               .values("minute", "xgot", "is_goal", "situation", "shot_type",
                       "player_id", "team_side")):
        # nello specchio (parato: un xGOT c'è; oppure entrato) e battuto mentre
        # c'era LUI fra i pali.
        if sh["minute"] is None or not ((sh["xgot"] or 0.0) > 0 or sh["is_goal"]):
            continue
        if at(side, sh["minute"]) != player_id:
            continue
        # L'AUTOGOL DI UN COMPAGNO è in questa lista e non per sbaglio: SofaScore lo
        # archivia col ``team_side`` della squadra per cui CONTA, cioè l'avversaria,
        # quindi arriva qui insieme ai tiri veri. Ed è giusto che ci sia — il gol è
        # entrato nella sua porta e il suo ``goals_prevented`` l'ha pagato.
        #
        # Ma NON lo paga per intero: gli viene restituita la difficoltà del tiro
        # (v. ``_merge_own_goal_relief`` e OWN_GOAL_KEEPER_XGOT_DEFAULT), quindi
        # l'xGOT con cui la mappa deve contarlo è quello del credito, non zero.
        # Contandolo a zero la sezione perdeva 0.834 esatti, che finivano nel metro:
        # il difetto si è presentato da solo, con quel numero, appena il controllo
        # di riconciliazione è stato acceso.
        own = is_own_goal(sh["shot_type"], sh["team_side"],
                          sides.get((match.id, sh["player_id"])))
        xgot = sh["xgot"] or 0.0
        faced.append({**sh, "own_goal": own,
                      "xgot": (xgot or OWN_GOAL_KEEPER_XGOT_DEFAULT) if own else xgot})
    if not faced:
        return empty

    scales = feature_scales(gk=True)
    weights = weights_for_role(role)
    weight = mins / (mins + SHRINKAGE_MINUTES)
    per_unit = spread_k_for(role) * weight / reference[role]["std"]
    n = len(faced)

    def _removed(mask):
        """Quanto tolgono, in totale, i tiri SPENTI in ``mask``."""
        gone = defaultdict(float)
        for bit, s in enumerate(faced):
            if mask >> bit & 1:
                continue
            # gol evitati = somma degli xGOT affrontati MENO i gol: togliere un tiro
            # toglie il suo xGOT, e se era gol restituisce l'unità che aveva sottratto.
            gone["gk_goals_prevented"] += (s["xgot"] or 0.0) - (1.0 if s["is_goal"] else 0.0)
            if not s["is_goal"]:
                gone["gk_saves"] += 1.0
        return gone

    def totals_for(mask):
        """I totali del portiere coi soli tiri accesi in ``mask``.

        Si SOTTRAE dai totali veri, come per le conclusioni, così a maschera piena
        si riottiene esattamente l'indice che ha prodotto il voto.

        IL PAVIMENTO A ZERO VALE SOLO PER I CONTEGGI. ``gk_goals_prevented`` è
        legittimamente negativo — è la firma del portiere battuto su tiri parabili,
        cioè la cosa che più conta nel suo canale — e schiacciarlo a zero
        cancellerebbe proprio quella.
        """
        gone = _removed(mask)
        if not gone:
            return feats
        t = dict(feats)
        for k, v in gone.items():
            floor = k != "gk_goals_prevented"
            x = (t.get(k) or 0.0) - v
            t[k] = max(0.0, x) if floor else x
        return t

    # I DUE ARCHIVI PARLANO DELLA STESSA PARTITA? I totali vengono dalle zone del
    # fornitore, la mappa da ``MatchShot``. Sulla 25-26 l'identità regge (scarto
    # mediano esatto, 90,6% entro 0,10) ma nel resto no, e la differenza finisce nel
    # metro, dove si legge storta. Detto ad alta voce: è un difetto DEI DATI.
    gap = {k: round((feats.get(k) or 0.0) - v, 3)
           for k, v in _removed(0).items()
           if abs((feats.get(k) or 0.0) - v) > 0.02}
    if gap:
        log.warning("save map and zone totals disagree for keeper %s in match %s: "
                    "%s left over after removing every shot on target — the save "
                    "baseline absorbs it", player_id, match.id, gap)

    def value(mask):
        """Il SOLO sotto-indice delle parate: l'unica parte che i tiri muovono.

        PASSA PER ``raw_feature_values`` e non legge i totali nudi, come fa invece
        la mappa dei tiri. Lì la scorciatoia è lecita perché le sei voci delle
        conclusioni sono tutte TOTALI; qui no: ``gk_saves`` è una densità per 90'
        (v. GK_PER90_WEIGHTS) e ``gk_goals_prevented`` un totale, quindi la famiglia
        è mista. Con un portiere uscito al 60' la scorciatoia sbagliava di un terzo,
        e con uno che gioca i novanta — cioè quasi sempre — non sbagliava affatto:
        il difetto sarebbe passato inosservato in produzione per mesi.
        """
        values = raw_feature_values(totals_for(mask), mins, 0.0, gk=True)
        return sum(weights.get(k, 0.0) * scored_z(k, values.get(k, 0.0), scales)
                   for k in _SAVE_FAMILY)

    full = (1 << n) - 1
    if n <= _SHAPLEY_MAX_SHOTS:
        vals = [value(mask) for mask in range(full + 1)]
        coef = [factorial(r) * factorial(n - r - 1) / factorial(n) for r in range(n)]
        share = [0.0] * n
        for bit in range(n):
            b = 1 << bit
            for sub in range(full + 1):
                if not sub & b:
                    share[bit] += coef[sub.bit_count()] * (vals[sub | b] - vals[sub])
        joint, empty_value = vals[full] - vals[0], vals[0]
    else:
        # Ripiego: il leave-one-out riportato al totale. Un portiere oltre i dodici
        # tiri nello specchio non si è mai visto (massimo di stagione: 13, una volta).
        empty_value, vfull = value(0), value(full)
        joint = vfull - empty_value
        loo = [vfull - value(full & ~(1 << bit)) for bit in range(n)]
        tot = sum(loo)
        share = [x * (joint / tot) if tot else joint / n for x in loo]

    out = [{
        "minute": s["minute"],
        "outcome": ("autogol di un compagno" if s["own_goal"]
                    else SAVE_OUTCOME_IT[bool(s["is_goal"])]),
        "situation": SHOT_SITUATION_IT.get(s["situation"] or "", ""),
        "xgot": round(s["xgot"] or 0.0, 3),
        "points": round(share[i] * per_unit, 3),
    } for i, s in enumerate(faced)]

    mean_terms = get_role_averages(match.competition_season_id).get(role, {})
    baseline = (empty_value - sum(mean_terms.get(k, 0.0) for k in _SAVE_FAMILY)) * per_unit
    return {"saves": out, "baseline": round(baseline, 3),
            "total": round(baseline + joint * per_unit, 3)}


def voto_puro_row(match, player_id: int) -> dict | None:
    """La riga del voto di un giocatore, dalla pagella gia' in cache quando c'e'."""
    for r in voto_puro_for_match(match, get_reference(match.competition_season_id)):
        if r["player_id"] == player_id:
            return r
    return None
