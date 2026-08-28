"""Lo strato SofaScore delle probabili formazioni: leggerlo, e fonderlo col nostro.

SofaScore pubblica un XI PREVISTO — ``confirmed: false`` — e lo pubblica presto:
misurato il 28/08/2026 sulla 2a giornata, era li' per tutte e dieci le partite,
la piu' lontana a 79 ore dal calcio d'inizio. Non e' una stima statistica come la
nostra: porta notizie. Su quella giornata il 95% del suo XI coincideva con quello
di fantacalcio.it, e 31 dei suoi titolari previsti non avevano giocato un minuto
del campionato — cose che nessun modello sui dati storici puo' sapere.

LA TRAPPOLA, e va scritta prima di tutto il resto: per una giornata ancora
lontana l'endpoint risponde 200 con ``confirmed: false`` e ZERO giocatori.
``confirmed=false`` non vuol dire "previsione", vuol dire "non ufficiale", e
copre sia la previsione sia il vuoto. Il discriminante e' il numero di giocatori.
Chi non lo conta salva previsioni vuote senza un errore da nessuna parte.

E' UN LAVORO DI SERIE B, deliberatamente. Una richiesta a partita (contro le
quattro di un giro live e le ventisei di uno pesante), mai dentro una finestra
live, e chi lo chiama deve poter rinunciare: il namespace di uscita e' uno solo e
gli IP buoni sono una risorsa scarsa che serve la domenica per i voti. Una
probabile formazione non vale un IP bruciato.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone as dt_timezone
from pathlib import Path

from django.conf import settings
from django.db import models
from django.utils import timezone

from realdata.models import (
    LineupEvidence, LineupForecast, LineupForecastEntry, Match, Player,
    PlayerAlias, PlayerTeamStint,
)
from realdata.services import lineup_forecast as engine
from realdata.services.identity import is_synthetic_sofascore_id, norm_name

log = logging.getLogger(__name__)

# Fin dove guardiamo avanti. Oltre le ~80 ore SofaScore non ha ancora scritto
# niente (misurato: la 3a giornata a 175 ore rispondeva vuota), quindi chiedere
# di piu' e' spendere richieste per un 200 vuoto.
HORIZON = timedelta(hours=84)

# LE BANDE DELLA CADENZA. Tre, e ognuna ha un mestiere diverso — non sono un
# raffinamento progressivo della stessa idea.
#
#   da 84h a 48h, ogni 12h   accorgersi che la previsione E' COMPARSA. SofaScore
#                            la scrive piu' o meno quando finisce la giornata
#                            precedente (misurato: c'era a 79 ore, non a 175), e
#                            in questa finestra non si muove quasi nulla: bastano
#                            tre letture. L'estremo superiore e' HORIZON, oltre il
#                            quale non si guarda affatto perche' non c'e' niente.
#
#   da 48h a 105 min, ogni 3h    seguire le NOTIZIE, che e' l'unica cosa che
#                            muove una probabile formazione. Qui la vecchia
#                            soglia era a 12 ore ed era sbagliata: misurato il
#                            28/08/2026 su Juventus-Parma, alle 15:58 SofaScore
#                            dava McKennie titolare e alle 17:30 lo aveva messo
#                            fra gli assenti — a 26 ore dal fischio, cioe' dentro
#                            la banda lenta. Avremmo continuato a dirlo al 97%
#                            fino alle 4 di notte. La domanda giusta non e'
#                            «quanto manca al fischio» ma «quanto puo' essere
#                            vecchio un numero che presentiamo come corrente».
#
#   ultimi 75 min, ogni 15 min    prendere LA DISTINTA UFFICIALE appena esce, e
#                            poi smettere: appena e' ufficiale la partita esce da
#                            ``due_matches`` e non si chiede piu' niente.
#
#                            Comincia a 75 e non a 105 minuti perche' prima non
#                            c'e' niente da prendere. MISURATO su Milan-Venezia
#                            del 28/08/2026, leggendo ogni due minuti: a T-54 la
#                            distinta era ancora una previsione (22 giocatori,
#                            zero panchina), a T-52 era ufficiale (50 giocatori,
#                            28 in panchina). Partendo da 105 si leggevano quattro
#                            volte le stesse ventidue righe prima che uscisse
#                            qualcosa.
#
#                            Il margine resta: una distinta insolitamente
#                            anticipata viene comunque presa alla prima lettura di
#                            questa banda, solo un quarto d'ora piu' tardi. E' UNA
#                            osservazione, non una distribuzione — ma ora
#                            ``LineupForecast.official`` e ``refreshed_at`` la
#                            registrano a ogni partita, quindi fra qualche
#                            giornata questa soglia si potra' tarare sui nostri
#                            dati invece che su una misura sola.
FAR_EVERY = timedelta(hours=12)
FAR_BEYOND = timedelta(hours=48)
NEAR_EVERY = timedelta(hours=3)
LAST_EVERY = timedelta(minutes=15)
LAST_WITHIN = timedelta(minutes=75)

# Quanto pesa il parere di SofaScore quando lo fondiamo col nostro, in log-odds.
#
# NON e' una manopola scelta a occhio: e' il rapporto di verosimiglianza di una
# fonte che indovina il titolare con probabilita' p, cioe' log(p / (1-p)). Con
# p = 0.85 fa 1.73. Il giorno che avremo misurato la SUA accuratezza contro le
# distinte ufficiali — l'unico modo, visto che delle probabili non esiste
# archivio e la misura si puo' fare solo in avanti — si cambia il numero qui e
# tutto il resto segue.
SOURCE_ACCURACY = 0.85


def source_log_odds(accuracy: float = SOURCE_ACCURACY) -> float:
    a = min(max(accuracy, 0.5001), 0.9999)
    return math.log(a / (1 - a))


# --- lettura ------------------------------------------------------------------

def _cache_path(external_id: str) -> Path:
    return (Path(settings.VFOOT_SOFASCORE_CACHE)
            / f"api_v1_event_{external_id}_lineups.json")


def read_cached(match) -> dict | None:
    try:
        return json.loads(_cache_path(match.external_id).read_text())
    except (OSError, ValueError):
        return None


def is_usable_prediction(payload: dict | None) -> bool:
    """C'e' un foglio squadra utilizzabile? Previsto o ufficiale, indifferente.

    Il discriminante e' il NUMERO DI GIOCATORI, mai ``confirmed``. Per una
    giornata lontana l'endpoint risponde 200 con ``confirmed: false`` e zero
    giocatori: "non ufficiale" copre sia la previsione sia il vuoto, e chi legge
    solo quel campo salva formazioni vuote senza un errore da nessuna parte.
    """
    if not payload:
        return False
    players = [p for side in ("home", "away")
               for p in ((payload.get(side) or {}).get("players") or [])]
    return len(players) >= 20


def is_official(payload: dict | None) -> bool:
    """La distinta e' quella vera, uscita dallo spogliatoio."""
    return bool(payload and payload.get("confirmed")
                and is_usable_prediction(payload))


def _payload_people(payload: dict) -> list[dict]:
    """Tutti gli esseri umani citati dal payload: schierati e assenti."""
    out = []
    for side in ("home", "away"):
        blk = payload.get(side) or {}
        for p in blk.get("players") or []:
            if (p.get("player") or {}).get("id") is not None:
                out.append(p["player"])
        for m in blk.get("missingPlayers") or []:
            if (m.get("player") or {}).get("id") is not None:
                out.append(m["player"])
    return out


def _resolve_players(payload: dict, match) -> tuple[dict[int, int], list[str]]:
    """({id SofaScore: nostro player_id}, [nomi non agganciati]).

    Tre passi, e il terzo esiste perche' i primi due non bastavano: meta' del
    payload cadeva. Un giocatore arrivato da Transfermarkt non ha un
    ``external_id`` SofaScore, e nemmeno un alias VERO — al massimo quello
    sintetico del simulatore, che non nomina nessuno (v. identity). Sulla
    Milan-Venezia del 28/08/2026 il Venezia si risolveva 2 su 11.

      1. ``external_id``, per chi da SofaScore ci e' arrivato;
      2. un alias vero (mai uno sintetico);
      3. nome + data di nascita, DENTRO le rose delle due squadre di questa
         partita — e l'id trovato si SCRIVE come alias, cosi' la volta dopo il
         passo 3 non serve piu'.

    Il terzo passo e' ristretto alle due rose e chiede la data di nascita perche'
    un omonimo agganciato per sbaglio e' peggio di un giocatore mancante: questo
    modulo non crea anagrafica e non deve poterla sporcare.
    """
    people = _payload_people(payload)
    ext_ids = {str(p["id"]) for p in people}

    resolved: dict[int, int] = {}
    for e, pid in (Player.objects
                   .filter(external_source="sofascore", external_id__in=ext_ids)
                   .values_list("external_id", "id")):
        resolved[int(e)] = pid
    for pid, alias in (PlayerAlias.objects
                       .filter(source="sofascore", alias__in=ext_ids)
                       .values_list("player_id", "alias")):
        if not is_synthetic_sofascore_id(alias):
            resolved.setdefault(int(alias), pid)

    missing = [p for p in people if int(p["id"]) not in resolved]
    unmatched: list[str] = []
    if missing:
        squad = {}
        for pid, full, short, dob in (PlayerTeamStint.objects
                                      .filter(team_season_id__in=[match.home_team_id,
                                                                  match.away_team_id],
                                              end_date__isnull=True)
                                      .values_list("player_id", "player__full_name",
                                                   "player__short_name",
                                                   "player__date_of_birth")):
            for nm in (full, short):
                key = norm_name(nm)
                if key:
                    squad.setdefault(key, []).append((pid, dob))
        learned = []
        for p in missing:
            dob = _dob(p.get("dateOfBirthTimestamp"))
            cands = squad.get(norm_name(p.get("name"))) or []
            if len(cands) != 1:
                unmatched.append(str(p.get("name")))
                continue
            pid, our_dob = cands[0]
            # La data deve concordare quando c'e' da entrambe le parti. Quando
            # manca a uno dei due si accetta il nome: dentro due sole rose, un
            # nome completo identico e' gia' un'identificazione.
            if dob and our_dob and dob != our_dob:
                unmatched.append(str(p.get("name")))
                continue
            resolved[int(p["id"])] = pid
            learned.append(PlayerAlias(player_id=pid, source="sofascore",
                                       alias=str(p["id"])))
        if learned:
            PlayerAlias.objects.bulk_create(learned, ignore_conflicts=True)
    return resolved, unmatched


def _dob(ts):
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=dt_timezone.utc).date()
    except (TypeError, ValueError, OSError):
        return None


# --- scrittura ----------------------------------------------------------------

_MISSING_KIND = {
    1: LineupEvidence.KIND_INJURY,
    2: LineupEvidence.KIND_SUSPENSION,
    3: LineupEvidence.KIND_INTERNATIONAL,
    4: LineupEvidence.KIND_TRANSFER,
}


def import_predicted(match, *, now=None) -> bool:
    """Scrive la previsione di SofaScore per questa partita. False se non c'era.

    ``now`` come in ``lineup_forecast.build_forecast``: il timbro e' del
    chiamante, perche' su di esso decide la cadenza."""
    payload = read_cached(match)
    if not is_usable_prediction(payload):
        return False
    known, unmatched = _resolve_players(payload, match)

    fc, _ = LineupForecast.objects.get_or_create(
        match=match, source=LineupForecast.SOURCE_SOFASCORE)
    fc.official = is_official(payload)
    previous = dict(LineupForecastEntry.objects.filter(forecast=fc)
                    .values_list("player_id", "probability"))
    LineupForecastEntry.objects.filter(forecast=fc).delete()

    entries = []
    sides = {"home": match.home_team_id, "away": match.away_team_id}
    for side, ts_id in sides.items():
        blk = payload.get(side) or {}
        setattr(fc, f"{side}_formation", (blk.get("formation") or "")[:16])
        for p in blk.get("players") or []:
            ext = (p.get("player") or {}).get("id")
            pid = known.get(ext)
            if pid is None:
                continue
            starter = not p.get("substitute")
            entries.append(LineupForecastEntry(
                forecast=fc, player_id=pid, team_season_id=ts_id,
                probability=100 if starter else 0,
                previous_probability=previous.get(pid),
                status=(LineupForecastEntry.STATUS_STARTER if starter
                        else LineupForecastEntry.STATUS_BENCH)))
    LineupForecastEntry.objects.bulk_create(entries, ignore_conflicts=True)
    fc.refreshed_at = now or timezone.now()
    fc.save(update_fields=["refreshed_at", "home_formation", "away_formation",
                           "official"])

    _import_missing(match, payload, known, now=now)
    if unmatched:
        # Detto, non ingoiato: una formazione a meta' e' il modo in cui questo
        # importatore puo' sbagliare senza che nessuno se ne accorga.
        log.warning("probabili %s: %d giocatori non agganciati (%s)",
                    match.external_id, len(unmatched), ", ".join(unmatched[:6]))
    return True


def _import_missing(match, payload: dict, known: dict[int, int], *,
                    now=None) -> int:
    """``missingPlayers`` -> indizi, PER QUESTA PARTITA e non per la giornata.

    Una lista di assenti e' una fotografia e due fotografie non si sommano: chi e'
    guarito deve sparire, quindi si cancella prima di riscrivere. Ma si cancella
    solo la fotografia di QUESTE DUE SQUADRE.

    La prima versione ripuliva l'intera giornata e riscriveva solo la partita che
    stava importando, cosi' ognuna delle dieci cancellava le altre nove: in
    produzione, dopo un giro completo, gli unici assenti registrati per la seconda
    giornata erano i sette della Lazio — l'ultima importata. Gli infortunati della
    Juventus erano stati scritti e spazzati via nello stesso minuto, e McKennie e
    Yildiz risultavano disponibili.

    L'insieme da ripulire e' la rosa delle due squadre PIU' i giocatori nominati
    dal payload: il secondo pezzo serve per chi e' stato ceduto o non ha ancora una
    stint, che altrimenti lascerebbe una riga orfana e resterebbe indisponibile per
    sempre.
    """
    cs = match.competition_season
    squad = set(PlayerTeamStint.objects
                .filter(team_season_id__in=[match.home_team_id, match.away_team_id],
                        end_date__isnull=True)
                .values_list("player_id", flat=True))
    squad |= {pid for pid in known.values()}
    LineupEvidence.objects.filter(competition_season=cs, source="sofascore",
                                  matchday=match.matchday,
                                  player_id__in=squad).delete()
    rows = []
    for side in ("home", "away"):
        for m in ((payload.get(side) or {}).get("missingPlayers") or []):
            pid = known.get((m.get("player") or {}).get("id"))
            if pid is None:
                continue
            rows.append(LineupEvidence(
                competition_season=cs, player_id=pid, matchday=match.matchday,
                kind=_MISSING_KIND.get(m.get("reason"), LineupEvidence.KIND_NOTE),
                availability=LineupEvidence.AVAIL_OUT, source="sofascore",
                note=str(m.get("description") or "")[:200],
                # Lo stesso orologio del timbro sulla previsione: e' il confronto
                # fra i due che decide se il motore ricalcola, e due orologi
                # diversi lo rendono una moneta lanciata.
                created_at=now or timezone.now()))
    LineupEvidence.objects.bulk_create(rows)
    return len(rows)


# --- la cadenza ---------------------------------------------------------------

def due_matches(now=None, *, horizon=HORIZON) -> list[Match]:
    """Le partite che meritano un giro adesso, dalla piu' vicina al fischio.

    Mai una partita gia' cominciata: dentro la finestra live la distinta la porta
    il giro live, che passa dallo stesso namespace e ha la precedenza su tutto.
    """
    now = now or timezone.now()
    qs = (Match.objects
          .filter(status=Match.STATUS_SCHEDULED, kickoff__isnull=False,
                  kickoff_provisional=False,
                  kickoff__gt=now, kickoff__lte=now + horizon)
          .exclude(competition_season__external_id="")
          .select_related("competition_season")
          .order_by("kickoff"))
    seen = {mid: (stamp, official) for mid, stamp, official in
            LineupForecast.objects
            .filter(match__in=qs, source=LineupForecast.SOURCE_SOFASCORE)
            .values_list("match_id", "refreshed_at", "official")}
    due = []
    for m in qs:
        last, official = seen.get(m.id, (None, False))
        if official:
            # Gia' ufficiale: non c'e' piu' niente da sapere, e ogni altra
            # richiesta sarebbe spesa per riscrivere lo stesso foglio.
            continue
        to_kickoff = m.kickoff - now
        if to_kickoff <= LAST_WITHIN:
            every = LAST_EVERY
        elif to_kickoff <= FAR_BEYOND:
            every = NEAR_EVERY
        else:
            every = FAR_EVERY
        if last is None or now - last >= every:
            due.append(m)
    return due


def refresh(now=None, *, limit: int = 10, fetch=None) -> dict:
    """Un giro: scalda le distinte dovute e le importa. Torna un piccolo verbale.

    ``limit`` e' un tetto per giro, non una selezione: le partite escono in ordine
    di calcio d'inizio, quindi cio' che resta fuori e' cio' che ha piu' tempo.
    """
    from realdata.services import egress_client

    matches = due_matches(now)[:limit]
    report = {"due": len(matches), "fetched": 0, "imported": 0, "empty": 0}
    if not matches:
        return report
    # Un id non numerico non fa saltare il giro: lo salta e basta. Questo lavoro
    # e' l'ultimo della fila e non deve poter rompere niente — nemmeno se stesso.
    ids, usable = [], []
    for m in matches:
        try:
            ids.append(int(m.external_id))
            usable.append(m)
        except (TypeError, ValueError):
            log.warning("probabili: id esterno non numerico su %s (%r), saltata",
                        m, m.external_id)
    report["due"] = len(usable)
    if not ids:
        return report
    matches = usable

    warm = fetch or egress_client.warm_probable
    if not warm(ids):
        # Bloccati o namespace occupato: si rinuncia al giro. NON si ruota l'IP —
        # v. l'intestazione: un IP buono speso giovedi' per una probabile e' un IP
        # che puo' non esserci domenica per i voti.
        report["blocked"] = True
        return report
    report["fetched"] = len(matches)
    for m in matches:
        if import_predicted(m, now=now):
            report["imported"] += 1
        else:
            report["empty"] += 1
    return report


# --- la fusione ---------------------------------------------------------------

def merged_for_matches(matches) -> dict[int, dict[int, dict]]:
    """{match_id: {player_id: {...}}} — la titolarita' fusa, per PIU' partite in
    un colpo solo.

    Tre query in tutto, quali che siano le partite. La versione per una partita
    sola ne faceva tre CIASCUNA, e chi legge una giornata intera le legge tutte:
    trentuno query per disegnare una pagina, che crescono con le partite del
    turno e non con nulla di utile. Nessuno se ne sarebbe accorto — venti
    millisecondi — ma una crescita lineare che non serve a niente si toglie
    quando la si vede, non quando fa male.

    Il calcolo per partita e' invariato ed e' tutto in ``_merge_one``: qui si
    raccolgono i dati, la' si decide.
    """
    matches = list(matches)
    if not matches:
        return {}
    ids = [m.id for m in matches]

    forecasts = list(LineupForecast.objects.filter(match_id__in=ids))
    by_match_source = {(f.match_id, f.source): f for f in forecasts}
    entries: dict[tuple[int, str], dict[int, LineupForecastEntry]] = {}
    fc_of = {f.id: (f.match_id, f.source) for f in forecasts}
    for e in LineupForecastEntry.objects.filter(forecast_id__in=list(fc_of)):
        key = fc_of[e.forecast_id]
        entries.setdefault(key, {})[e.player_id] = e

    players = {pid for per in entries.values() for pid in per}
    keepers = dict(Player.objects.filter(id__in=players)
                   .values_list("id", "is_goalkeeper"))

    out: dict[int, dict[int, dict]] = {}
    for m in matches:
        sofa = by_match_source.get((m.id, LineupForecast.SOURCE_SOFASCORE))
        merged_one = _merge_one(
            ours=entries.get((m.id, LineupForecast.SOURCE_VFOOT), {}),
            theirs=entries.get((m.id, LineupForecast.SOURCE_SOFASCORE), {}),
            official=bool(sofa and sofa.official),
            keepers=keepers,
            source_as_of=sofa.refreshed_at if sofa else None,
        )
        if merged_one:
            out[m.id] = merged_one
    return out


def _merge_one(*, ours, theirs, official: bool, keepers,
               source_as_of=None) -> dict[int, dict]:
    """La fusione di UNA partita, su dati gia' raccolti.

    Il nostro motore da' il livello, SofaScore lo corregge. E lo corregge nello
    stesso modo in cui il motore tratta ogni altro indizio — uno spostamento in
    logit, non una sovrascrittura — perche' un XI binario che azzerasse la nostra
    stima butterebbe via l'unica informazione che abbiamo sui panchinari: fra due
    esclusi, SofaScore dice che sono entrambi fuori, noi sappiamo quale dei due
    gioca di piu'.
    """
    delta = source_log_odds()
    # QUANDO L'ABBIAMO LETTA. Un numero che viene da una fonte esterna e' vecchio
    # quanto l'ultima lettura, e chi lo guarda deve poterlo sapere: SofaScore ha
    # cambiato l'undici della Juventus in novanta minuti, e senza questa data la
    # nostra pagina avrebbe detto 97% senza modo di spiegare perche'.
    as_of = source_as_of.isoformat() if source_as_of else None
    # DI QUALI SQUADRE SofaScore HA DETTO QUALCOSA. Serve perche' la sua
    # previsione contiene SOLO gli undici titolari: chi non c'e' non e' assente
    # dal parere, e' il parere. Senza questo insieme lo spostamento era
    # asimmetrico — la spinta ai suoi undici e niente a tutti gli altri — e ogni
    # panchinaro restava al numero del nostro motore. McKennie, tolto dall'undici
    # e messo fra gli assenti, continuava a leggersi 86%.
    sofa_teams = {e.team_season_id for e in theirs.values()}
    out: dict[int, dict] = {}
    for pid, e in ours.items():
        base = {"team_season_id": e.team_season_id, "reason": e.reason,
                "previous": e.previous_probability, "sources": ["vfoot"],
                "as_of": None}
        if e.status == LineupForecastEntry.STATUS_OUT:
            out[pid] = {**base, "probability": 0,
                        "status": LineupForecastEntry.STATUS_OUT}
            continue
        p = max(1, min(99, e.probability)) / 100.0
        t = theirs.get(pid)
        if t is not None:
            base["sources"].append("sofascore")
            base["as_of"] = as_of
            # Una distinta UFFICIALE non si fonde: si sostituisce. Spostare di
            # 1.73 in logit un fatto osservato darebbe 96% a chi e' in campo e 4%
            # a chi non c'e', cioe' un dubbio che non esiste — e la pagina direbbe
            # "probabile" di una formazione gia' letta dallo speaker.
            if official:
                p = 1.0 if t.status == LineupForecastEntry.STATUS_STARTER else 0.0
            else:
                sign = 1.0 if t.status == LineupForecastEntry.STATUS_STARTER else -1.0
                p = engine._sigmoid(engine._logit(p) + sign * delta)
        elif official:
            # Distinta ufficiale uscita e lui non c'e': non e' improbabile, e'
            # fuori. Il nostro numero non ha piu' niente da dire.
            base["sources"].append("sofascore")
            base["as_of"] = as_of
            p = 0.0
        elif e.team_season_id in sofa_teams:
            # SofaScore ha detto chi gioca in questa squadra, e lui non c'e':
            # e' un parere contrario, e pesa quanto peserebbe quello favorevole.
            base["sources"].append("sofascore")
            base["as_of"] = as_of
            p = engine._sigmoid(engine._logit(p) - delta)
        out[pid] = {**base, "probability": int(round(p * 100)), "status": ""}
    # Un titolare previsto da SofaScore che il nostro motore non ha in rosa (un
    # acquisto che le nostre stint non conoscono ancora) non va perso: e' proprio
    # il caso in cui loro sanno e noi no.
    for pid, t in theirs.items():
        if pid in out:
            continue
        starter = t.status == LineupForecastEntry.STATUS_STARTER
        out[pid] = {"team_season_id": t.team_season_id, "reason": "",
                    "previous": t.previous_probability, "sources": ["sofascore"],
                    "as_of": as_of,
                    "probability": (100 if starter else (0 if official else 10)),
                    "status": ""}

    # LO STATO SI RICALCOLA SULLA PROBABILITA' FUSA, e non e' un dettaglio: lo
    # stato del nostro motore riguarda la NOSTRA stima, e un giocatore che noi
    # mettevamo in panchina e SofaScore schiera esce da qui al 79% ma con scritto
    # «panchina». La pagina raggruppa per stato, quindi la formazione mostrata
    # aveva nove titolari invece di undici.
    by_team: dict[int, list[int]] = {}
    for pid, info in out.items():
        if info["status"] != LineupForecastEntry.STATUS_OUT:
            by_team.setdefault(info["team_season_id"], []).append(pid)
    for ids in by_team.values():
        ids.sort(key=lambda pid: -out[pid]["probability"])
        gk = [pid for pid in ids if keepers.get(pid)]
        others = [pid for pid in ids if not keepers.get(pid)]
        xi = set(gk[:1]) | set(others[:10])
        for pid in ids:
            out[pid]["status"] = (LineupForecastEntry.STATUS_STARTER if pid in xi
                                  else LineupForecastEntry.STATUS_BENCH)
    return out


def merged(match) -> dict[int, dict]:
    """La titolarita' fusa di UNA partita. Comodita' su ``merged_for_matches``."""
    return merged_for_matches([match]).get(match.id, {})


def probabilities_for(competition_season, matchday: int,
                      player_ids=None) -> dict[int, dict]:
    """{player_id: {...}} per una giornata intera — cio' che legge la pagina
    formazione, dove i venticinque di un allenatore sono sparsi su dieci partite.

    Una sola passata sulle partite della giornata; il filtro sui giocatori si
    applica DOPO, perche' la fusione ha senso solo per squadra intera: lo stato
    «titolare» esce da un confronto fra compagni, non da una soglia.
    """
    out: dict[int, dict] = {}
    for per_match in merged_for_matches(
            Match.objects.filter(competition_season=competition_season,
                                 matchday=matchday)).values():
        out.update(per_match)
    if player_ids is not None:
        wanted = set(player_ids)
        out = {pid: v for pid, v in out.items() if pid in wanted}
    return out


def match_payload(match) -> dict | None:
    """Le due formazioni previste di una partita, pronte da disegnare.

    ``None`` quando non c'e' NIENTE: nessuna previsione nostra e nessuna loro. La
    pagina deve poter dire "non ancora", che e' diverso da "undici a caso".
    """
    forecasts = {f.source: f for f in match.lineup_forecasts.all()}
    if not forecasts:
        return None
    probs = merged(match)
    if not probs:
        return None

    sofa = forecasts.get(LineupForecast.SOURCE_SOFASCORE)
    names = dict(Player.objects.filter(id__in=probs)
                 .values_list("id", "short_name"))
    full = dict(Player.objects.filter(id__in=probs).values_list("id", "full_name"))

    sides = {}
    for side, ts_id in (("home", match.home_team_id), ("away", match.away_team_id)):
        rows = []
        for pid, info in probs.items():
            if info["team_season_id"] != ts_id:
                continue
            rows.append({
                "player_id": pid,
                "name": names.get(pid) or full.get(pid) or "?",
                "probability": info["probability"],
                "previous": info.get("previous"),
                "status": info["status"],
                "reason": info["reason"],
                "sources": info["sources"],
            })
        rows.sort(key=lambda r: (-r["probability"], r["name"]))
        sides[side] = {
            "formation": (getattr(sofa, f"{side}_formation", "") if sofa else ""),
            "players": rows[:26],
        }

    return {
        "match_id": match.id,
        "home_team": match.home_team.team.name,
        "away_team": match.away_team.team.name,
        "kickoff": match.kickoff.isoformat() if match.kickoff else None,
        "refreshed_at": max(f.refreshed_at for f in forecasts.values()).isoformat(),
        # Quale strato sta parlando. La pagina lo deve dire: una previsione fatta
        # solo dalle nostre presenze e una che ha visto le notizie non sono la
        # stessa cosa, e chi legge ha diritto di sapere quale sta guardando.
        "sources": sorted(forecasts),
        "official": bool(sofa is not None and sofa.official),
        **sides,
    }


def inputs_changed_at(competition_season):
    """L'istante piu' recente in cui e' cambiato qualcosa che il NOSTRO motore
    legge: una partita importata (presenze, cartellini) o un indizio scritto.

    E' il cancello che al motore mancava. Senza, ``refresh_all`` ricalcolava tutte
    le partite entro ottantaquattro ore A OGNI MINUTO, per giorni, e nessuno se ne
    sarebbe accorto: il risultato e' identico, cambia solo il conto delle query.
    Peggio, ``previous_probability`` finiva per confrontare con sessanta secondi
    prima, quindi la freccia «e' salito» non poteva comparire mai — la si sarebbe
    cercata in pagina per settimane senza capire perche' non arriva.
    """
    stamps = (Match.objects
              .filter(competition_season=competition_season,
                      status=Match.STATUS_FINISHED)
              .aggregate(a=models.Max("data_imported_at"),
                         b=models.Max("data_checked_at")))
    ev = (LineupEvidence.objects
          .filter(competition_season=competition_season)
          .aggregate(c=models.Max("created_at")))
    return max([v for v in (stamps["a"], stamps["b"], ev["c"]) if v], default=None)


def refresh_all(now=None, *, limit: int = 10, fetch=None) -> dict:
    """Il giro completo delle probabili, nell'ordine che conta.

    PRIMA SofaScore, POI il nostro motore, e non e' indifferente: la lista degli
    assenti la scrive SofaScore (``missingPlayers`` -> ``LineupEvidence``) e la
    legge il nostro motore. Costruendo la nostra previsione per prima, un
    infortunio scaricato adesso sarebbe entrato solo al giro successivo — cioe'
    fino a dodici ore dopo, con l'infortunato ancora dato all'ottanta per cento.

    Chiamato dal tick nel solo momento in cui non c'e' nient'altro da fare.
    """
    now = now or timezone.now()
    report = refresh(now, limit=limit, fetch=fetch)

    upcoming = list(Match.objects
                    .filter(status=Match.STATUS_SCHEDULED, kickoff__isnull=False,
                            kickoff__gt=now, kickoff__lte=now + HORIZON)
                    .select_related("competition_season"))
    seen = dict(LineupForecast.objects
                .filter(match__in=upcoming, source=LineupForecast.SOURCE_VFOOT)
                .values_list("match_id", "refreshed_at"))
    changed: dict[int, object] = {}
    built = skipped = 0
    for m in upcoming:
        cs_id = m.competition_season_id
        if cs_id not in changed:
            changed[cs_id] = inputs_changed_at(m.competition_season)
        last, mark = seen.get(m.id), changed[cs_id]
        if last is not None and mark is not None and last >= mark:
            skipped += 1
            continue
        if engine.build_forecast(m, now=now) is not None:
            built += 1
    report["built"] = built
    report["unchanged"] = skipped
    return report
