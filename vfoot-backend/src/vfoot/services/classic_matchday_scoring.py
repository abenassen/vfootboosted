"""Score a fantasy matchday (classic) from the real results — the live conclusion.

Pipeline:
  1. build_matchday_index(): run pagella_for_match over ALL real matches of the
     reference real matchday → a per-player line index (voto_puro / fantavoto / sv /
     lineup_role / conceded), one entry per player who appeared.
  2. for each fantasy fixture, read both teams' saved lineups (SavedLineupSnapshot),
     compose their line lists FILTERED to players still owned (sold players become
     empty s.v. slots; the bench drops them), and score with the classic_scoring
     engine.
  3. the caller (the conclusion view) persists home_total/away_total +
     FantasyFixtureDetail.payload + the ruleset snapshot, atomically.

The composition (compose_team_lines) is pure and unit-tested without a DB; only the
index/lineup/roster lookups touch the database.
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db.models import Count, Max

from realdata.models import Match, Player, PlayerTeamStint
from vfoot.models import (
    FantasyFixture,
    FantasyFixtureDetail,
    FantasyRosterSlot,
    LeaguePlayerRole,
    SavedLineupSnapshot,
)
from vfoot.services.classic_pagella import (
    get_reference,
    get_role_averages,
    matchday_data_version,
    pagella_for_match,
)
from vfoot.services.classic_scoring import Ruleset, resolve_fixture, score_team
from vfoot.services import frozen_roster
from vfoot.services.match_resolver import (
    matchday_fixtures_by_team,
    pending_matches,
    pending_player_ids,
)
from vfoot.services.vote_reference import scoring_fingerprint

CLASSIC_ROLE_TO_LINEUP = {"POR": "GK", "DIF": "DEF", "CEN": "MID", "ATT": "ATT"}

log = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Database lookups (thin).                                                     #
# --------------------------------------------------------------------------- #
# Quanto vive in cache una pagella di giornata. NON è la scadenza della
# freschezza — quella la fa la chiave, che cambia appena i dati si muovono — ma il
# tetto massimo di ciò che resta in giro se qualcosa va storto nella pulizia qui
# sotto.
INDEX_CACHE_TTL = 6 * 3600


def _index_pointer_key(competition_season_id: int, real_matchday: int, league_id: int) -> str:
    """Dove è scritta l'ULTIMA chiave usata per questa giornata in questa lega.

    Serve a buttare via la voce precedente quando se ne scrive una nuova, e la
    ragione è la cache su file: tiene 500 voci in tutto, e un turno in diretta ne
    genererebbe una nuova ogni due minuti — trenta all'ora, duecento in una serata
    di campionato, duecento MB di pagelle che nessuno rileggerà mai. Arrivato al
    tetto, il culling non butta le più vecchie: ne butta un terzo a caso, e fra
    quelle la taratura del voto, che costa molto più di quel che ha risparmiato.
    Una voce viva per (lega, giornata), e il problema non si pone.
    """
    return f"vfoot:mdindex:last:{competition_season_id}:{real_matchday}:{league_id}"


def _index_cache_key(competition_season_id: int, real_matchday: int, league) -> str:
    """La chiave sotto cui vive l'indice di una giornata.

    Tre cose la muovono, e servono tutte e tre:

    * i DATI del turno (``matchday_data_version``) — due minuti di partita e la
      chiave è un'altra, che è esattamente la freschezza voluta;
    * i RUOLI CONGELATI della lega, che l'import di Transfermarkt può aggiungere a
      lega in corso e che decidono il ruolo — e quindi il malus — di ogni riga;
    * l'IMPRONTA DEL MODELLO, perché ritoccare i pesi cambia ogni voto senza
      toccare una riga di database. Senza, il listone ha già servito per settimane
      voti calcolati prima di una ritaratura, e nessuna chiave si era mossa.
    """
    roles = (LeaguePlayerRole.objects.filter(league=league)
             .aggregate(n=Count("id"), last=Max("updated_at")))
    stamp = roles["last"].isoformat() if roles["last"] else "-"
    return (f"vfoot:mdindex:{competition_season_id}:{real_matchday}:{league.id}"
            f":{roles['n'] or 0}:{stamp}"
            f":{matchday_data_version(competition_season_id, real_matchday)}"
            f":{scoring_fingerprint()}")


def build_matchday_index(competition_season_id: int, real_matchday: int, league) -> dict:
    """player_id -> pagella line, for every player who appeared in the real matchday.

    A player plays in exactly one real match per matchday, so keys never collide.
    ``league`` is passed so the FROZEN classic roles win (a league's match detail must
    agree with its own listone).

    IN CACHE, e non per fare economia su un conto raro: questo è il conto più caro
    che l'applicazione faccia in risposta a un clic. Sono le dieci pagelle del
    turno — voto puro, esposizione difensiva e spiegazione per quattrocentosessanta
    giocatori, un secondo pieno — e il calendario le rifaceva TUTTE per stampare
    due numeri per partita, a ogni apertura della home e a ogni colpo del socket
    live. La chiave cambia appena i dati si muovono, quindi non c'è niente da
    invalidare a mano: chi importa continua a non sapere che questa cache esista.

    Le righe che escono di qui non vanno modificate sul posto — ``compose_team_lines``
    ne fa una copia prima di toccarle, ed è quella copia che il tabellino marca come
    provvisoria.
    """
    key = _index_cache_key(competition_season_id, real_matchday, league)
    hit = cache.get(key)
    if hit is not None:
        return hit

    matches = Match.objects.filter(
        competition_season_id=competition_season_id, matchday=real_matchday
    )
    reference = get_reference(competition_season_id)
    averages = get_role_averages(competition_season_id)
    index: dict[int, dict] = {}
    for m in matches:
        detail = pagella_for_match(m, reference=reference, league=league, averages=averages)
        for side in ("home", "away"):
            for line in detail[side]["starters"] + detail[side]["bench"]:
                index[line["player_id"]] = line

    # UNA voce viva per (lega, giornata): la precedente è spazzatura dall'istante
    # in cui i dati si sono mossi, e lasciarla lì riempirebbe la cache di pagelle
    # che nessuno rileggerà (vedi _index_pointer_key).
    pointer = _index_pointer_key(competition_season_id, real_matchday, league.id)
    previous = cache.get(pointer)
    if previous and previous != key:
        cache.delete(previous)
    cache.set(key, index, INDEX_CACHE_TTL)
    cache.set(pointer, key, INDEX_CACHE_TTL)
    return index


def owned_player_ids(team) -> set:
    """La rosa di ADESSO. Per tutto cio' che riguarda una giornata gia' cominciata
    la domanda giusta e' un'altra — v. ``frozen_roster.owned_for_matchday``."""
    return frozen_roster.owned_now(team)


def role_map_for(league, player_ids: list[int]) -> dict:
    """player_id -> lineup role (GK/DEF/MID/ATT), from the league's FROZEN roles, with
    the Transfermarkt seed as a fallback (mirrors the lineup-save validation)."""
    frozen = {
        lpr.player_id: CLASSIC_ROLE_TO_LINEUP.get(lpr.role, "MID")
        for lpr in LeaguePlayerRole.objects.filter(league=league, player_id__in=player_ids)
    }
    missing = [pid for pid in player_ids if pid not in frozen]
    if missing:
        for pid, seed in Player.objects.filter(id__in=missing).exclude(
            classic_role_seed=""
        ).values_list("id", "classic_role_seed"):
            frozen[pid] = CLASSIC_ROLE_TO_LINEUP.get(seed, "MID")
    return frozen


def _lineup_key(team_id: int, competition_id: int | None) -> str:
    return f"team{team_id}" + (f":comp{competition_id}" if competition_id is not None else "")


def read_saved_lineup(league_id: int, real_matchday: int, team_id: int, competition_id: int | None):
    """The team's saved lineup for this matchday+competition, falling back to a
    competition-agnostic snapshot."""
    key = _lineup_key(team_id, competition_id)
    snap = SavedLineupSnapshot.objects.filter(
        league_id=str(league_id), matchday_id=str(real_matchday), lineup_id=key
    ).first()
    if snap is None and competition_id is not None:
        snap = SavedLineupSnapshot.objects.filter(
            league_id=str(league_id), matchday_id=str(real_matchday), lineup_id=f"team{team_id}"
        ).first()
    return snap


def lineup_still_owned(snap, owned: set[int]):
    """La formazione di uno snapshot, ripulita di chi non e' piu' in rosa.

    Ritorna ``(gk, titolari, panchina, usciti)``. Serve alla formazione EREDITATA
    — quella della giornata prima, riproposta a chi non ha ancora schierato — e
    applica la stessa regola che il punteggio applica gia' al suo ripiego: chi e'
    stato venduto sparisce e lascia un posto vuoto, non viene rimpiazzato d'ufficio.

    Il posto vuoto non e' una mancanza di questa funzione, e' la risposta giusta:
    scegliere un sostituto al posto dell'allenatore significherebbe schierare per
    lui un giocatore che non ha scelto, e per di piu' in silenzio. La pagina il
    buco lo mostra e lo fa toccare.
    """
    gk = int(snap.gk_player_id) if snap.gk_player_id else None
    outfield = [int(x) for x in (snap.starter_player_ids or [])]
    bench = [int(x) for x in (snap.bench_player_ids or [])]
    gone = [p for p in ([gk] if gk else []) + outfield + bench if p not in owned]
    return (
        gk if (gk is not None and gk in owned) else None,
        [p for p in outfield if p in owned],
        [p for p in bench if p in owned],
        gone,
    )


def read_previous_lineup(league_id: int, real_matchday: int, team_id: int, competition_id: int | None):
    """The most recent saved lineup from a matchday BEFORE this one (the 'previous'
    fallback for a team that didn't set one). Returns None if there is no earlier lineup."""
    keys = [_lineup_key(team_id, competition_id), f"team{team_id}"]
    best = None
    best_md = None
    for snap in SavedLineupSnapshot.objects.filter(league_id=str(league_id), lineup_id__in=keys):
        try:
            md = int(snap.matchday_id)
        except (TypeError, ValueError):
            continue
        if md < real_matchday and (best_md is None or md > best_md):
            best, best_md = snap, md
    return best


# --------------------------------------------------------------------------- #
# Pure composition (unit-tested without a DB).                                 #
# --------------------------------------------------------------------------- #
def _sv_line(pid: int, lineup_role: str, name: str | None = None,
             pending: bool = False, vacant: bool = False) -> dict:
    """A senza-voto placeholder for a player with no line in the index (didn't play)
    or no longer owned (sold): no vote, so it triggers a substitution / is excluded.

    ``pending`` marks the other reason for having no vote: his club's match has not
    been played yet. It reads as s.v. everywhere the sum is concerned, but the bench
    must NOT cover it — a postponement is not a performance.

    ``vacant`` marks the third: the slot holds somebody this team no longer has, in
    a lineup it never submitted for this round. Da qui in giu' e' un senza voto come
    gli altri — panchina e voto d'ufficio lo coprono entrambi (v. classic_scoring.
    _fill_unresolved, che spiega perche' non lo si punisce due volte). Il marchio
    resta perche' dice una cosa vera e diversa: li' non c'e' nessuno da giudicare.
    """
    return {
        "player_id": pid, "name": name or str(pid), "lineup_role": lineup_role,
        "role": None, "voto_puro": None, "fantavoto": None, "sv": True,
        "pending": pending, "vacant": vacant,
        "conceded": 0, "entered": False, "entered_for": None, "replaced_by": None,
    }


def _office_line(pid: int, lineup_role: str, voto: float, name: str | None = None) -> dict:
    """An imposed vote: it IS the voto puro and the fantavoto, with nothing added.

    No goal, assist or card can be credited for a match that was not played, so the
    line carries the ruling and nothing else. ``office`` marks it as such — for the
    tabellino, and so the clean-sheet modifier does not mistake it for a game.
    """
    return {
        "player_id": pid, "name": name or str(pid), "lineup_role": lineup_role,
        "role": None, "voto_puro": voto, "fantavoto": voto, "sv": False,
        "pending": False, "office": True,
        "conceded": 0, "entered": False, "entered_for": None, "replaced_by": None,
    }


def names_for(player_ids) -> dict[int, str]:
    """{player_id: the name to show}, with the SAME preference the played line uses
    (classic_pagella._line), so one player is named one way whether he has a
    performance behind him or only a placeholder.

    Needed because a placeholder is built without an appearance, and the appearance
    is where a played line gets its name from. Without this the tabellino fell back
    to the id — which on a round in progress is most of a bench, and reads like a
    data corruption rather than a player who has not taken the field."""
    return {p.id: (p.short_name or p.full_name or str(p.id))
            for p in Player.objects.filter(id__in=list(player_ids))
            .only("id", "short_name", "full_name")}


def compose_team_lines(
    gk_id: int | None,
    outfield_ids: list[int],
    bench_ids: list[int],
    index: dict,
    role_map: dict,
    pending: set | None = None,
    office: dict | None = None,
    vacant: set | None = None,
    names: dict | None = None,
) -> tuple[list[dict], list[dict]]:
    """Build the ordered (starters, bench) line lists for scoring.

    **The submitted lineup is authoritative.** It was frozen at its matchday's lock
    and it is scored as sent: who owns the player TODAY does not enter into it. That
    is what makes a postponed round score identically whether it is concluded on time
    or six weeks later, and it is safe because a settlement repairs every lineup that
    is still open and never touches one that has locked (services/lineup_repair).

    - starters = [gk] + outfield (the XI): each becomes its index line, or an s.v.
      placeholder when he has no line (didn't play / wasn't rated), which triggers a
      substitution;
    - bench keeps its priority order; a benched player with no vote simply cannot
      come on.
    Every line's lineup_role is forced from role_map so the manager's slot role is
    authoritative and consistent between played and non-played players.

    ``pending`` are players whose real match has not been played at all: they get a
    placeholder that the substitution engine leaves alone (see classic_scoring).
    ``office`` are the votes the league has imposed, which win over everything.
    ``vacant`` are slots to empty regardless — used ONLY when falling back to an
    older lineup the manager never submitted for this matchday: that one is the
    admin's substitute, not the manager's word, so it is right to strip from it the
    players the team no longer has. Svuotato il posto, quel che ne segue e' il
    trattamento di un senza voto qualunque.
    """
    starter_ids = ([gk_id] if gk_id else []) + list(outfield_ids)
    pending = pending or set()
    office = office or {}
    vacant = vacant or set()
    names = names or {}

    def line_for(pid: int) -> dict:
        role = role_map.get(pid, "MID")
        name = names.get(pid)
        if pid in office:
            # The league has ruled on this match: the ruling wins over both the
            # missing data and any partial data the provider may have shipped — e
            # anche sul posto del ceduto, che da quando e' un senza voto come gli
            # altri non ha ragione di essere l'unico fuori dalla portata di una
            # decisione della lega.
            return _office_line(pid, role, office[pid], name)
        if pid in vacant:
            return _sv_line(pid, role, name, vacant=True)
        if pid in pending:
            # Pending BEFORE the index on purpose: a match that is finished but whose
            # data has not stabilised can already have appearances imported, so a line
            # may well exist — but the vote is not official yet, and counting it would
            # freeze a number that the next import can still move.
            return _sv_line(pid, role, name, pending=True)
        base = index.get(pid)
        if base is None:
            return _sv_line(pid, role, name)  # played, not rated: a plain s.v.
        line = dict(base)
        line["lineup_role"] = role
        return line

    starters = [line_for(pid) for pid in starter_ids]
    bench = [line_for(pid) for pid in bench_ids]
    return starters, bench


def _serialize_team(team: dict) -> dict:
    """Make a score_team/resolve_fixture team dict JSON-safe (ModifierResult -> dict)."""
    out = dict(team)
    out["modifiers"] = [
        {"key": m.key, "eligible": m.eligible, "value": m.value, "scope": m.scope, "detail": m.detail}
        for m in team.get("modifiers", [])
    ]
    return out


def build_fixture_payload(fixture_meta: dict, home: dict, away: dict, ruleset: Ruleset) -> dict:
    """The FantasyFixtureDetail payload — same shape the seed produces, so the existing
    classic match-detail UI renders a concluded league fixture unchanged."""
    return {
        "mode": "classic",
        "fixture_id": fixture_meta.get("fixture_id"),
        "fantasy_round": fixture_meta.get("fantasy_round"),
        "real_matchday": fixture_meta.get("real_matchday"),
        "stage": fixture_meta.get("stage"),
        # Which competition this fixture belongs to. The page opened from the home
        # had no way to know, so the shell kept pointing at whatever competition was
        # selected before — you could read a cup tie under a "CHAMPIONSHIP" banner,
        # with the side menu offering that other competition's calendar.
        "competition_id": fixture_meta.get("competition_id"),
        "home_team": fixture_meta.get("home_team"),
        "away_team": fixture_meta.get("away_team"),
        "home_goals": home["goals"],
        "away_goals": away["goals"],
        "home_total": home["total"],
        "away_total": away["total"],
        "defense_bonus_mode": ruleset.defense_mode,
        "defense_bonus_gate": ruleset.defense_gate,
        "sv_office_vote": ruleset.sv_office_vote,
        "result": "home" if home["goals"] > away["goals"] else "away" if away["goals"] > home["goals"] else "draw",
        "home": _serialize_team(home),
        "away": _serialize_team(away),
    }


def _snap_all_ids(snap) -> list[int]:
    if snap is None:
        return []
    ids = [int(snap.gk_player_id)] if snap.gk_player_id else []
    ids += [int(x) for x in (snap.starter_player_ids or [])]
    ids += [int(x) for x in (snap.bench_player_ids or [])]
    return ids


def office_votes_for(league, md, player_ids) -> dict:
    """player_id -> imposed vote, for the league's ACTIVE office overrides of this
    matchday. A player is covered when his club plays the overridden match."""
    from vfoot.models import OfficeOverride

    overrides = {
        o.match_id: o.voto
        for o in OfficeOverride.objects.filter(
            league=league, fantasy_matchday=md, is_active=True)
    }
    if not overrides:
        return {}
    cs_id = md.real_competition_season_id
    fixtures = matchday_fixtures_by_team(cs_id, md.real_matchday)
    stints = dict(
        PlayerTeamStint.objects.filter(
            player_id__in=list(player_ids),
            team_season__competition_season_id=cs_id,
            end_date__isnull=True,
        ).values_list("player_id", "team_season_id")
    )
    out = {}
    for pid in player_ids:
        match = fixtures.get(stints.get(pid))
        if match is not None and match.id in overrides:
            out[pid] = overrides[match.id]
    return out


def team_lines_for_conclusion(league, team, competition_id, real_matchday, index, resolution,
                              pending=None, office=None):
    """Resolve a team's (starters, bench) line lists at conclusion.

    Returns (starters, bench, meta). meta["source"] is one of:
      - "lineup":  the team submitted a lineup for this matchday;
      - "previous": no lineup, admin chose to reuse the previous one (filtered to
                    still-owned players);
      - "forfait":  no lineup, admin chose forfait (empty XI -> 0);
      - "missing":  no lineup and no admin resolution yet — the caller must ask the
                    admin (meta carries has_previous_lineup + previous_lineup_stale).
    """
    # LA ROSA DI QUANDO LA GIORNATA E' COMINCIATA, non quella di adesso. Fra
    # l'ultimo fischio e la conclusione il mercato lavora, e leggendo la rosa di
    # oggi uno svincolo validato in quella finestra apriva un buco a ritroso in
    # una giornata gia' giocata: la stessa giornata chiusa lunedi' sera e chiusa
    # mercoledi' dava due risultati diversi. Il punteggio di un turno non puo'
    # dipendere dal giorno in cui l'admin lo chiude.
    owned = frozen_roster.owned_for_matchday(league, team, real_matchday)
    snap = read_saved_lineup(league.id, real_matchday, team.id, competition_id)
    source = "lineup"

    if snap is None:
        if resolution == "forfait":
            return [], [], {"source": "forfait", "stale": 0}
        if resolution == "previous":
            snap = read_previous_lineup(league.id, real_matchday, team.id, competition_id)
            if snap is None:
                return [], [], {"source": "forfait", "stale": 0}  # nothing earlier -> forfait
            source = "previous"
        else:
            # NESSUNA DECISIONE DA PRENDERE, quasi mai piu'.
            #
            # Chi non ha schierato viene trattato come chi ha mandato la formazione
            # della giornata precedente — che e' anche quella che la sua pagina gli
            # mostrava, con scritto «se non la tocchi, gioca questa». Prima qui si
            # tornava «missing», la conclusione della giornata si fermava e l'admin
            # doveva scegliere a mano, squadra per squadra, fra forfait e formazione
            # precedente: una decisione presa a voti gia' noti, da una persona, su
            # ogni singolo caso. Ora e' una regola annunciata prima.
            #
            # Il forfait resta, ma come scavalco esplicito (`resolution ==
            # "forfait"`), per la squadra che ha davvero abbandonato. Cambia chi
            # porta l'onere: prima l'admin decideva sempre, ora solo nel caso
            # eccezionale.
            #
            # «missing» sopravvive per l'unico caso in cui non c'e' proprio niente
            # da ereditare: la prima giornata di chi non ha mai schierato.
            prev = read_previous_lineup(league.id, real_matchday, team.id, competition_id)
            if prev is None:
                return None, None, {
                    "source": "missing",
                    "has_previous_lineup": False,
                    "previous_lineup_stale": 0,
                }
            snap = prev
            source = "previous"

    gk = int(snap.gk_player_id) if snap.gk_player_id else None
    outfield = [int(x) for x in (snap.starter_player_ids or [])]
    bench = [int(x) for x in (snap.bench_player_ids or [])]
    all_ids = ([gk] if gk else []) + outfield + bench
    role_map = role_map_for(league, all_ids)
    # Only the fallback lineup is filtered against today's roster — see compose_team_lines.
    vacant = {p for p in all_ids if p not in owned} if source == "previous" else set()
    starters, bench_lines = compose_team_lines(gk, outfield, bench, index, role_map,
                                               pending, office, vacant,
                                               names_for(all_ids))
    return starters, bench_lines, {"source": source, "stale": len(vacant)}


def score_composed_fixture(
    home_lines: tuple[list[dict], list[dict]],
    away_lines: tuple[list[dict], list[dict]],
    ruleset: Ruleset,
    fixture_meta: dict,
    round_open: bool = False,
) -> dict:
    """Score both composed teams and return the payload. Pure given the line lists.

    ``fixture_meta["home_advantage"]`` dice se in QUESTA partita giocare in casa
    conta: viaggia nel meta e non come argomento a parte perché è un dato della
    partita, come il turno e la fase, e ogni chiamante ce l'ha già in mano.

    ``round_open`` invece non è un dato della partita ma dell'orologio, e riguarda
    una decisione sola: il voto d'ufficio sui buchi, che aspetta l'ultimo fischio
    del turno (v. ``classic_scoring._fill_unresolved``). Spento di default, cioè
    com'è alla conclusione: chi la chiama sta dicendo che la giornata è finita.
    """
    home = score_team(home_lines[0], home_lines[1], ruleset, round_open)
    away = score_team(away_lines[0], away_lines[1], ruleset, round_open)
    resolve_fixture(home, away, ruleset, bool(fixture_meta.get("home_advantage")))
    return build_fixture_payload(fixture_meta, home, away, ruleset)


# --------------------------------------------------------------------------- #
# The same score, computed while the matchday is still being played.           #
# --------------------------------------------------------------------------- #
def _live_states(cs_id: int, real_matchday: int, player_ids) -> tuple[set, set, set]:
    """(not_started, unstable, in_progress): come il voto di un giocatore puo' non
    essere definitivo.

    ``pending_player_ids`` collapses them into one, and rightly so at conclusion
    time — a vote that is not final is not a vote. During the round the difference
    is the whole point:

    * NOT STARTED — his club has not kicked off. There is nothing to show and the
      bench must not cover him: a match that has not been played is not a bad
      performance.
    * UNSTABLE — his club is playing, or has finished and the provider has not
      settled the data. There IS a vote, computed from what has happened so far;
      it is simply going to move. Showing it and saying so is the feature.
    * IN PROGRESS — il sottoinsieme stretto di UNSTABLE: la palla sta ancora
      rotolando. E' un insieme a parte perche' e' l'unico che il MOTORE deve
      guardare, mentre l'altro riguarda soltanto quel che si legge.

      La differenza dura un'ora tonda: ``data_ready`` arriva alla conferma di
      +1h dopo il fischio (v. tick), quindi «instabile» resta vero per tutta
      un'ora su una partita che e' finita e su cui e' gia' partita la notifica
      di fine partita. Fusi insieme, i due dicevano a turno la cosa sbagliata:
      al quinto minuto la panchina copriva un titolare che era regolarmente in
      campo (nessuno ha ancora un voto, e un buco non e' un buco finche' la
      partita che l'ha fatto non e' finita), e per l'ora dopo il fischio la
      pagina scriveva «in corso» su partite abbondantemente concluse.
    """
    player_ids = list(player_ids)
    if not player_ids:
        return set(), set(), set()
    fixtures = matchday_fixtures_by_team(cs_id, real_matchday)
    stints = dict(
        PlayerTeamStint.objects.filter(
            player_id__in=player_ids,
            team_season__competition_season_id=cs_id,
            end_date__isnull=True,
        ).values_list("player_id", "team_season_id")
    )
    not_started, unstable, in_progress = set(), set(), set()
    for pid in player_ids:
        match = fixtures.get(stints.get(pid))
        if match is None or match.data_ready:
            continue
        if match.status == Match.STATUS_LIVE:
            unstable.add(pid)
            in_progress.add(pid)
        elif match.status == Match.STATUS_FINISHED:
            unstable.add(pid)
        else:
            not_started.add(pid)
    return not_started, unstable, in_progress


def round_still_open(cs_id: int, real_matchday: int) -> bool:
    """C'e' ancora una partita di questa giornata da giocare (o sul campo adesso)?

    Serve a UNA decisione: il voto d'ufficio sui buchi, che non si impone finche' la
    panchina puo' ancora coprirli (v. ``classic_scoring._fill_unresolved``). E' una
    domanda sul CALENDARIO, non sui giocatori di una squadra: la risposta e' la
    stessa per tutta la lega e cambia una volta sola, all'ultimo fischio del turno.

    IL RINVIO RESTA FUORI (``postponed``, come in ``matchday_state.playing_matchday``):
    quella non e' una partita ancora da giocare in giornata, e' un caso che la lega
    risolve a parte — aspettando il recupero o deliberando. Tenere sospesi i buchi di
    tutti per sei settimane sarebbe peggio del problema.
    """
    return Match.objects.filter(
        competition_season_id=cs_id, matchday=real_matchday,
        status__in=(Match.STATUS_SCHEDULED, Match.STATUS_LIVE),
    ).exists()


def _mark_unstable(team: dict, unstable: set, in_progress: set | None = None) -> bool:
    """Flag every line whose real match is still moving, and the team with it.

    A total made in part of provisional votes is itself provisional — there is no
    honest way to show a settled number on top of unsettled ones.

    DUE MARCHI E NON UNO, perche' sono due affermazioni diverse:

    * ``provisional`` — questo numero puo' ancora cambiare. Riguarda solo quel che
      si legge, e vale sia per la partita in corso sia per quella finita che il
      fornitore non ha ancora confermato.
    * ``in_progress`` — la palla sta ancora rotolando. E' l'unico che il MOTORE
      guarda (``classic_scoring.score_team``): finche' e' acceso, il titolare senza
      voto non e' un buco e la panchina non lo copre.

    Il secondo non e' deducibile dal primo: fra il fischio finale e la conferma
    passa un'ora, e in quell'ora ``provisional`` e' vero mentre non c'e' piu'
    niente in corso.
    """
    in_progress = in_progress or set()
    any_unstable = False
    for line in team.get("starters", []) + team.get("bench", []):
        if line.get("player_id") in unstable and not line.get("office"):
            line["provisional"] = True
            any_unstable = True
            if line["player_id"] in in_progress:
                line["in_progress"] = True
        if line.get("pending"):
            any_unstable = True
    team["provisional"] = any_unstable
    team["in_progress"] = any(
        line.get("in_progress")
        for line in team.get("starters", []) + team.get("bench", [])
    )
    return any_unstable


def _engine_in_progress(in_progress: set, index: dict, projected: bool) -> set:
    """Quali «partita in corso» il MOTORE deve continuare a rispettare.

    Fuori dalla previsione, tutte: finche' la palla rotola, un titolare senza voto
    non e' un buco e la panchina non lo copre (v. ``classic_scoring.score_team``).

    Nella previsione, SOLO CHI E' IN CAMPO — ed e' tutta la differenza fra le due
    letture. La domanda «se la giornata finisse adesso?» risponde diversamente dal
    solito per una categoria di righe sola: il titolare con zero minuti in una
    partita che si sta giocando. Al fischio finale la panchina lo coprirebbe, e il
    voto d'ufficio tapperebbe il buco che resta; la previsione lo dice subito.

    CHI E' IN CAMPO RESTA INTOCCABILE ANCHE QUI, e questa e' la riga che separa la
    funzione dalla scorciatoia sbagliata: nei primi minuti chi sta giocando non ha
    ancora un voto — il fornitore non ha ancora dati su di lui — e sostituirlo
    sarebbe la stessa cosa sbagliata di sempre, un cambio dato come risposta a «non
    ha giocato» a uno che sta giocando, stavolta offerta come funzione invece che
    subita come bug. La differenza fra i due la dice gia' la pagella, che scrive
    ``sv_reason == "in_campo"`` per l'uno e ``non_entrato`` per l'altro.

    L'insieme piu' stretto lo vede il motore e basta: la marcatura DOPO il calcolo
    riceve quello vero, quindi la pagina continua a scrivere «in corso» su quelle
    righe. Ed e' giusto — la partita e' in corso davvero, ed e' esattamente il
    motivo per cui questo numero puo' cambiare fra dieci minuti.
    """
    if not projected:
        return in_progress
    return {pid for pid in in_progress
            if (index.get(pid) or {}).get("sv_reason") == "in_campo"}


def ruleset_for_round(league, md):
    """The rules THIS round is played under.

    A league's settings are live, and a round takes three days: without this, a
    setting changed on Sunday — the lock mode, the defence gate, the office vote —
    re-scored Saturday's matches, and the conclusion on Tuesday used whatever the
    settings happened to be on Tuesday. The rules of a round are the rules in force
    when it BEGAN, so they are frozen into ``md.ruleset_snapshot`` the first time
    the round is scored after its first kickoff — the live calendar, the fixture
    detail and the tick all pass through here within minutes of it — and the
    conclusion reads the same frozen copy. Before the kickoff nothing is frozen:
    the admin can still change his mind about a round nobody has played.

    The recompute endpoint keeps its explicit "with the CURRENT rules" option: that
    is the admin overriding the freeze on purpose, and it rewrites the snapshot.
    """
    if md.ruleset_snapshot:
        return Ruleset.from_snapshot(md.ruleset_snapshot)
    ruleset = Ruleset.from_league(league)
    from vfoot.services import matchday_state

    if matchday_state.is_locked(md.real_competition_season_id, md.real_matchday):
        md.ruleset_snapshot = ruleset.to_snapshot()
        md.save(update_fields=["ruleset_snapshot"])
    return ruleset


def live_scorer(league, md, ruleset, projected: bool = False):
    """Prepare a matchday ONCE, then score any number of its fixtures.

    The expensive half is per-MATCHDAY, not per-fixture: ``build_matchday_index``
    runs the pagella over all ten real matches of the round (half a second), and
    the two instability sets are the same question for the whole league. A
    calendar showing the five provisional scores of a round paid that five times
    before this existed.

    ``projected`` — «SE LA GIORNATA FINISSE ADESSO». Non e' una previsione di come
    andra' a finire (quella vorrebbe un modello sulle partite non ancora
    cominciate, e non abita qui): e' lo stesso conto di sempre con una sola
    domanda risposta diversamente, v. ``_engine_in_progress``. Non si salva, non
    si spinge e non entra in classifica — e' un secondo modo di LEGGERE il turno,
    chiesto dalla pagina che lo mostra.

    Returns a callable ``score(fixture) -> payload``.
    """
    index = build_matchday_index(md.real_competition_season_id, md.real_matchday, league)
    # Rosters AND everyone actually FIELDED this round. Not the same set, and the
    # difference is not a corner case: the submitted lineup is authoritative and is
    # scored as sent, so a player sold since the lock still has a line in the
    # tabellino. Asking the states only about today's rosters left exactly those
    # lines unmarked — scored from a match in progress, and shown as if settled.
    ids = set(
        FantasyRosterSlot.objects.filter(team__league=league, released_at__isnull=True)
        .values_list("player_id", flat=True)
    )
    for snap in SavedLineupSnapshot.objects.filter(
            league_id=str(league.id), matchday_id=str(md.real_matchday)):
        if snap.gk_player_id:
            ids.add(int(snap.gk_player_id))
        ids.update(int(x) for x in (snap.starter_player_ids or []))
        ids.update(int(x) for x in (snap.bench_player_ids or []))
    not_started, unstable, in_progress = _live_states(
        md.real_competition_season_id, md.real_matchday, ids)
    office = office_votes_for(league, md, ids)
    not_started -= set(office)
    unstable -= set(office)
    in_progress -= set(office)
    engine_in_progress = _engine_in_progress(in_progress, index, projected)
    # C'e' ancora una partita del turno da giocare? Allora un titolare senza voto
    # non e' ancora un buco da pagare: il panchinaro che lo coprira' deve solo
    # scendere in campo (v. classic_scoring._fill_unresolved).
    round_open = round_still_open(md.real_competition_season_id, md.real_matchday)
    # Nella previsione no. «Se la giornata finisse adesso» e' la domanda di un turno
    # gia' chiuso: li' i buchi sono definitivi e il voto d'ufficio li tappa — la
    # stessa deroga, sulla stessa riga, che ``_engine_in_progress`` fa sui cambi.
    engine_round_open = False if projected else round_open

    def score_with(fx, frozen_by_kickoff: set, open_round: bool) -> dict:
        """Il tabellino, dato l'insieme di «sta ancora giocando» che il motore deve
        rispettare. Chiamabile due volte sullo stesso fixture: ogni giro ricompone
        le righe da zero (``compose_team_lines`` copia quelle dell'indice), quindi
        il secondo non eredita niente dal primo."""
        lines = {}
        for side, team in (("home", fx.home_team), ("away", fx.away_team)):
            # ``previous`` rather than None: mid-round there is no admin to ask what
            # to do with a team that did not field, and a preview must not be able
            # to answer 400. It is a PREVIEW of the most likely conclusion, not a
            # ruling — the admin still chooses when he closes the round.
            starters, bench, meta = team_lines_for_conclusion(
                league, team, fx.competition_id, md.real_matchday, index, "previous",
                not_started, office)
            starters, bench = starters or [], bench or []
            # BEFORE scoring, not only after: the scorer READS these marks. Con
            # ``in_progress`` decide chi non va sostituito (score_team) e che cosa
            # non e' un buco (_fill_unresolved); marcati dopo, al quinto minuto la
            # panchina coprirebbe tutti quelli che sono regolarmente in campo, e una
            # lega col voto d'ufficio aprirebbe il turno con undici buchi.
            #
            # QUI l'insieme che decide, e solo qui: e' il motore che risponde alla
            # domanda fatta (v. _engine_in_progress). La marcatura di sotto, quella
            # che la pagina legge, riceve sempre l'insieme vero.
            _mark_unstable({"starters": starters, "bench": bench}, unstable,
                           frozen_by_kickoff)
            lines[side] = (starters, bench, meta)

        payload = score_composed_fixture(
            (lines["home"][0], lines["home"][1]),
            (lines["away"][0], lines["away"][1]),
            ruleset,
            {"fixture_id": fx.id, "fantasy_round": fx.round_no,
             "real_matchday": md.real_matchday, "stage": fx.stage_id,
             "competition_id": fx.competition_id,
             "home_advantage": fx.home_advantage,
             "home_team": fx.home_team.name, "away_team": fx.away_team.name},
            round_open=open_round,
        )
        home_unstable = _mark_unstable(payload["home"], unstable, in_progress)
        away_unstable = _mark_unstable(payload["away"], unstable, in_progress)
        # ``live`` qui vuol dire «calcolato adesso invece che congelato», ed e' vero
        # dal primo calcio d'inizio fino alla conclusione dell'admin — cioe' anche
        # il lunedi' mattina. Non e' «la palla sta rotolando», che e' ``in_progress``
        # e dura quanto le partite. Chi disegna la pastiglia deve leggere il secondo.
        payload["live"] = True
        payload["provisional"] = home_unstable or away_unstable
        payload["in_progress"] = bool(payload["home"].get("in_progress")
                                      or payload["away"].get("in_progress"))
        # I buchi che aspettano l'ultimo fischio per essere tappati. La pagina lo
        # dice in una riga di legenda: senza, un posto scoperto al sabato sera si
        # legge come «questa lega il voto d'ufficio non ce l'ha».
        payload["office_deferred"] = bool(
            open_round and ruleset.sv_office_vote
            and (payload["home"]["unresolved_sv"] or payload["away"]["unresolved_sv"]))
        payload["lineup_source"] = {"home": lines["home"][2].get("source"),
                                    "away": lines["away"][2].get("source")}
        return payload

    def score(fx) -> dict:
        payload = score_with(fx, engine_in_progress, engine_round_open)
        # Il payload si dichiara. Senza, la pagina puo' finire per mostrare un
        # totale previsto sotto la pastiglia «in corso» — cioe' un numero che non
        # e' il punteggio della sfida presentato come se lo fosse. Chi lo riceve
        # deve sapere quale delle due domande ha fatto.
        payload["projected"] = projected
        if projected:
            # E ANCHE L'ALTRA RISPOSTA, nello stesso giro, per una domanda sola:
            # LE DUE COINCIDONO? Spesso si' — quando sono tutti in campo non c'e'
            # niente da anticipare — e allora in pagina non si muove un numero. Chi
            # ha appena premuto il tasto vede una pagina identica a prima, e senza
            # una parola quello e' un tasto rotto invece che un tasto d'accordo.
            # L'assenza di differenza e' un'informazione, e da qui la si ricava.
            #
            # NON serve a stampare il confronto accanto al totale: da acceso cambia
            # gia' tutto il tabellino, e ripetere «56,5 → 68,5» era dire una terza
            # volta la stessa cosa.
            #
            # Costa un secondo passaggio di aritmetica su una trentina di righe: le
            # dieci pagelle del turno — la mezza secondo — sono gia' fatte e
            # condivise fra i due giri.
            actual = score_with(fx, in_progress, round_open)
            payload["actual"] = {
                "home_total": actual["home_total"], "away_total": actual["away_total"],
                "home_goals": actual["home_goals"], "away_goals": actual["away_goals"],
            }
        return payload

    return score


def score_fixture_live(fx, league, md, ruleset, projected: bool = False) -> dict:
    """The tabellino of a league fixture whose matchday is NOT concluded.

    Same functions as the conclusion, in the same order — that is deliberate, and
    the property to preserve: when the admin finally concludes, the frozen payload
    must be the one that was being shown a minute earlier. Anything computed a
    second way here would drift.

    NOTHING IS PERSISTED. The frozen payload is born at the conclusion and only
    there, which is what makes reopening a closed matchday pure reading (see
    docs/classic_live_scoring.md). Writing a provisional payload into
    FantasyFixtureDetail would destroy that property for the sake of a cache.

    ``projected`` — v. ``live_scorer``. Che la previsione passi di qui e non da un
    conto tutto suo E' il motivo per cui ci si puo' fidare: sono le stesse regole
    della lega, applicate dallo stesso motore, con una domanda sola cambiata.
    """
    return live_scorer(league, md, ruleset, projected=projected)(fx)


def _warn_about_unrepaired_lineups(league, md, team_lines) -> list[dict]:
    """Fielded players whose slot was released BEFORE the matchday locked."""
    from vfoot.services import matchday_state

    lock = matchday_state.lineup_lock_at(md.real_competition_season_id, md.real_matchday)
    if lock is None:
        return []
    fielded = {line["player_id"] for lines in team_lines.values() for line in lines[0] + lines[1]}
    if not fielded:
        return []
    bad = [
        {"player_id": s.player_id, "team_id": s.team_id,
         "released_at": s.released_at.isoformat()}
        for s in FantasyRosterSlot.objects.filter(
            team__league=league, player_id__in=fielded,
            released_at__isnull=False, released_at__lt=lock)
        # A player released before the lock and re-acquired since is not an anomaly.
        if not FantasyRosterSlot.objects.filter(
            team_id=s.team_id, player_id=s.player_id, released_at__isnull=True).exists()
    ]
    if bad:
        log.error(
            "Formazione non riparata: lega=%s giornata=%s — %d giocatori schierati "
            "erano gia' fuori rosa al blocco della giornata (%s). Il punteggio li "
            "conta comunque: la formazione fa fede. Controllare lineup_repair.",
            league.id, md.real_matchday, len(bad), bad[:5])
    return bad


def score_and_persist_matchday(md, league, ruleset, fixtures, resolutions, force, update_snapshot=True):
    """Score every fixture of a classic matchday and FREEZE the results, atomically:
    fx.home_total/away_total (classic goals) + FantasyFixtureDetail.payload (the full
    tabellino) + (optionally) md.ruleset_snapshot. Shared by the conclusion and the
    manual recompute.

    If any team has no lineup and no resolution and not ``force``, nothing is persisted
    and the return carries ``missing_teams`` (the caller should return a 400). Returns
    {"updated", "stage_ids", "missing_teams"}.
    """
    index = build_matchday_index(md.real_competition_season_id, md.real_matchday, league)
    resolutions = resolutions or {}

    # Which of these players' clubs have not played yet: computed over every roster
    # involved (a superset of the fielded players — two queries either way) so that a
    # postponement is told apart from a senza voto BEFORE the lines are composed.
    teams = {t.id: t for fx in fixtures for t in (fx.home_team, fx.away_team)}
    roster_ids = set()
    for team in teams.values():
        roster_ids |= frozen_roster.owned_for_matchday(league, team, md.real_matchday)
    pending = pending_player_ids(md.real_competition_season_id, md.real_matchday, roster_ids)
    # The league's ruling on the matches it decided not to wait for. It covers part
    # (or all) of the pending set: what stays pending is what nobody has ruled on.
    office = office_votes_for(league, md, roster_ids)
    pending -= set(office)

    # Pass 1: resolve lineups, collect teams still without one.
    team_lines: dict[tuple[int, str], tuple] = {}
    missing_teams: dict[int, dict] = {}
    for fx in fixtures:
        for side, team in (("home", fx.home_team), ("away", fx.away_team)):
            res = resolutions.get(str(team.id))
            starters, bench, meta = team_lines_for_conclusion(
                league, team, fx.competition_id, md.real_matchday, index, res, pending, office)
            if meta["source"] == "missing":
                missing_teams[team.id] = {"team_id": team.id, "name": team.name, **meta}
            else:
                team_lines[(fx.id, side)] = (starters, bench, meta)

    if missing_teams and not force:
        return {"updated": 0, "stage_ids": set(), "missing_teams": list(missing_teams.values()),
                "pending_matches": []}

    # The lineup is authoritative, which is only sound if every settlement repaired
    # the lineups that were still open. A player fielded here who had ALREADY left the
    # team when the round locked means one did not — a bug, not a game situation, and
    # one that would otherwise pay points to a team that no longer had him. It cannot
    # be corrected at this point (the lineup is frozen), so it is made loud instead.
    _warn_about_unrepaired_lineups(league, md, team_lines)

    # Players actually FIELDED whose match has not been played. The matchday cannot
    # be honestly scored while these exist: the league either waits for the recovery
    # (the awaiting state) or imposes an office vote. The caller decides; here we
    # only report it.
    fielded_pending = {
        line["player_id"]
        for lines in team_lines.values()
        for line in lines[0]
        if line.get("pending")
    }
    pending_info = pending_matches(
        md.real_competition_season_id, md.real_matchday, fielded_pending)
    if pending_info and not force:
        return {"updated": 0, "stage_ids": set(), "missing_teams": [],
                "pending_matches": pending_info}

    # Pass 2: score + persist (a still-missing team under force = forfait / empty).
    updated = 0
    stage_ids: set[int] = set()
    for fx in fixtures:
        home_ln = team_lines.get((fx.id, "home")) or ([], [], {})
        away_ln = team_lines.get((fx.id, "away")) or ([], [], {})
        payload = score_composed_fixture((home_ln[0], home_ln[1]), (away_ln[0], away_ln[1]), ruleset, {
            "fixture_id": fx.id, "fantasy_round": fx.round_no, "real_matchday": md.real_matchday,
            "stage": fx.stage_id, "competition_id": fx.competition_id,
            "home_advantage": fx.home_advantage,
            "home_team": fx.home_team.name, "away_team": fx.away_team.name,
        })
        fx.home_total = float(payload["home_goals"])
        fx.away_total = float(payload["away_goals"])
        fx.status = FantasyFixture.STATUS_FINISHED
        FantasyFixtureDetail.objects.update_or_create(
            fixture=fx,
            defaults={"vfoot_home": payload["home_total"],
                      "vfoot_away": payload["away_total"], "payload": payload},
        )
        updated += 1
        if fx.stage_id:
            stage_ids.add(fx.stage_id)

    if fixtures:
        FantasyFixture.objects.bulk_update(fixtures, ["home_total", "away_total", "status"], batch_size=500)
    if update_snapshot:
        md.ruleset_snapshot = ruleset.to_snapshot()
        md.save(update_fields=["ruleset_snapshot"])
    return {"updated": updated, "stage_ids": stage_ids, "missing_teams": [],
            "pending_matches": pending_info}
