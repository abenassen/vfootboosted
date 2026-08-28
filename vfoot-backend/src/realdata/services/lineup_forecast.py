"""Il motore delle probabili formazioni: il nostro, quello di fondo.

E' lo strato che c'e' SEMPRE. Non chiede niente alla rete — legge presenze e
cartellini che abbiamo gia' — e quindi copre la finestra in cui nessuna fonte ha
ancora pubblicato: da quando finisce una giornata a quando SofaScore scrive la
sua previsione, che abbiamo misurato comparire fra le 175 e le 79 ore prima del
calcio d'inizio. Fuori di li' e' grossolano e lo sa: dice chi gioca di solito,
non chi gioca domenica.

COME COMBINA. Una probabilita' a priori dalle ultime giornate, e sopra di essa
degli INDIZI che si sommano in scala logit:

    p = sigma( logit(priore) + somma dei log_odds degli indizi )

La scala logit e' la scelta di fondo, ed e' quella che rende il modello
estensibile senza riscriverlo: due indizi deboli valgono un indizio forte, il
loro ordine non conta, e nessuno di loro puo' da solo portare a 0 o a 1. Il
giorno che si sapra' che un giocatore ha litigato con l'allenatore, quella e' una
riga in ``LineupEvidence`` con il suo peso — non un ramo in questo file.

LE CERTEZZE NON SONO PESI. Una squalifica non e' un log_odds molto negativo: e'
uno zero. Passa da ``hard_out``, che non partecipa alla somma e non si puo'
compensare con tre indizi positivi. La differenza conta il giorno che qualcuno,
per far tornare un numero, sara' tentato di scrivere -12 da qualche parte.

E LA SQUADRA SCHIERA UNDICI. Le probabilita' grezze non lo sanno, e sommate
danno tredici o nove. L'ultimo passo e' una calibrazione: si cerca lo scostamento
uniforme in logit che porta la somma a 1 fra i portieri e a 10 fra gli altri. Non
cambia l'ORDINE di nessuno — sposta il livello, non il merito — ed e' cio' che
rende «74%» una frase con un significato invece di un numero.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from django.db.models import Q
from django.utils import timezone

from realdata.models import (
    CARD_RED, CARD_SECOND_YELLOW, CARD_YELLOW, LineupEvidence, LineupForecast,
    LineupForecastEntry, Match, MatchAppearance, MatchDisciplinaryEvent,
    PlayerMarketValue, PlayerTeamStint,
)

# --- le costanti del modello -------------------------------------------------

# Quante giornate della squadra guarda il priore. Sei e' un compromesso misurato
# a occhio fra "segue le rotazioni" e "non insegue il caso": con tre, un turnover
# di coppa ribalta il giudizio su un titolare.
FORM_WINDOW = 6
# Peso della giornata n-esima all'indietro. 0.82^5 = 0.37: la piu' vecchia della
# finestra pesa poco piu' di un terzo della piu' recente.
RECENCY = 0.82
# Priore Beta: serve a non dare 100% a chi ha una sola presenza da titolare.
#
# La sua forza NON cambia chi il modello mette in campo — misurato sulla 25-26 su
# cinque giornate, passando da (0.6, 2.0) a (0.15, 0.5) l'XI indovinato resta
# 74,6% e il portiere 85,0%, identici alla cifra decimale. Sposta solo il LIVELLO
# delle probabilita' dichiarate, ed e' la stessa struttura che il voto puro ha in
# ROLE_VOTE_CENTER: un peso ordina, non alza.
#
# Quindi la scelta non e' di accuratezza ma di ONESTA': il numero scritto deve
# valere quanto vale. Misurato, sui titolari previsti:
#
#     (0.6, 2.0)   portieri dicono 71% e ne indovinano 85%   movimento 70% / 74%
#     (0.15, 0.5)  portieri dicono 85% e ne indovinano 85%   movimento 78% / 74%
#     (0.10, 0.35) portieri dicono 87% e ne indovinano 85%   movimento 79% / 74%
#
# Vince la seconda: i portieri cadono esatti e il movimento resta quattro punti
# ottimista, contro i quattordici di scarto della prima. Quei quattro punti sono
# il residuo noto di questo strato, e sono la ragione per cui un portiere di
# riserva non va mai letto come "quasi titolare".
PRIOR_STARTS, PRIOR_OPPORTUNITIES = 0.15, 0.5

# Serie A: si e' squalificati alla quinta ammonizione e a ogni multiplo di cinque.
# MISURATO sulla 25-26 e non dedotto da un regolamento: dopo un multiplo di 5 il
# giocatore manca alla partita successiva nel 95,1% dei casi (102 casi) contro un
# 41,6% di fondo, e dopo un rosso nel 100% (63 casi). Se la soglia cambiasse, e'
# la stessa misura a dirlo — non questo commento.
#
# I cinque residui della soglia gialla sono sparsi su tutta la stagione (G13, G18,
# G26, G30, G33), quindi non sono un condono: sono ricorsi accolti e gialli che il
# giudice sportivo non ha convalidato. E' la ragione per cui questo strato dichiara
# una confidenza e non una certezza, e per cui sopra ci va una fonte che le
# notizie le sa.
YELLOW_SUSPENSION_EVERY = 5

MAX_LOGIT = 6.0   # sigma(6) = 0.9975: oltre, e' un modo goffo di scrivere "out"

# Quanto il valore di mercato muove la MEDIA del priore, dal centro verso i bordi.
# 0.20 porta la media da 0.30 (piatta) a 0.10 per il piu' economico della rosa e
# 0.50 per il piu' caro.
#
# Il valore entra SOLO come media del priore Beta, il che vuol dire che si lava da
# solo: un giocatore con sei presenze e' descritto dalle presenze, e il prezzo che
# ha pagato la societa' non conta piu' niente. Conta dove le presenze non dicono
# nulla — un acquisto di agosto, un rientro da un infortunio lungo — ed e' li' che
# e' stato misurato: fra i 1211 giocatori senza NESSUNA presenza da titolare nella
# finestra, chi poi parte titolare ha un valore mediano di 7,0 M€ contro 2,5 M€ di
# chi resta fuori, con un'AUC di 0,702. Da solo il valore vale poco (gli undici piu'
# cari di una rosa indovinano il 50% contro il 41% del caso): non e' una fonte, e'
# cio' che si sa di un giocatore prima di averlo visto giocare.
#
# Da solo sposta pochissimo, e va detto: su giornate di verifica disgiunte,
# 73.33% senza niente, 73.48% col solo valore, 73.64% con la sola forma, 73.94%
# con entrambi. Le due leve sono piccole e si sommano.
VALUE_PRIOR_SPREAD = 0.20

# Quanto la FORMA sposta la titolarita', in logit per punto di voto sopra il sei.
#
# L'ipotesi: chi sta giocando bene viene riconfermato. Misurata sulla 25-26 su
# 8137 titolari — chi viene riconfermato alla partita dopo ha una media voto di
# 6,93 contro 6,68 di chi non lo e', AUC 0,615. Il segnale c'e' ed e' sui
# TITOLARI, cioe' esattamente dove si decide un undici.
#
# 0.5 e non di piu', e il perche' e' il motivo per cui questa riga ha un numero
# basso invece di quello che sembrava migliore. Tarando e verificando sulle STESSE
# giornate il massimo cadeva a 1.5-2.0; su giornate disgiunte (taratura 3,7,11...
# verifica 5,9,13...) il massimo e' a 0.5 e oltre si appiattisce:
#
#     peso    taratura   verifica
#     0.0      74.85%     73.48%
#     0.5      75.56%     73.94%   <-
#     2.0      75.86%     73.79%
#     4.0      75.30%     73.23%
#
# La differenza fra le due colonne e' quanto il modello stava imparando il campione
# invece del calcio.
FORM_LOGIT_PER_VOTE = 0.5


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-min(x, 40.0)))
    e = math.exp(max(x, -40.0))
    return e / (1.0 + e)


def _logit(p: float) -> float:
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


@dataclass
class PlayerForecast:
    player_id: int
    team_season_id: int
    probability: float          # 0..1
    is_goalkeeper: bool = False
    out: bool = False
    reason: str = ""
    evidence: list = field(default_factory=list)


# --- squalifiche: derivate, mai salvate --------------------------------------

def _played_before(competition_season, before) -> list[dict]:
    """Le partite finite di questa competizione prima dell'istante ``before``,
    IN ORDINE DI DATA.

    L'ordine e' il punto, e per un giorno non lo e' stato. Ordinando per giornata
    invece che per calcio d'inizio, un recupero manda la squalifica sulla partita
    sbagliata: la squadra che gioca il recupero della 20a dopo la 21a ha come
    "successiva" la 21a per numero e il recupero per data, e solo la seconda e'
    quella in cui il rosso si sconta. Misurato: per giornata la regola del rosso
    risultava vera nel 92,1% dei casi, per data nel 100,0%. Non era il calcio a
    fare eccezioni, era la query.
    """
    return list(Match.objects
                .filter(competition_season=competition_season,
                        status=Match.STATUS_FINISHED,
                        kickoff__isnull=False, kickoff__lt=before)
                .order_by("kickoff", "id")
                .values("id", "matchday", "kickoff", "home_team_id", "away_team_id"))


def suspensions_for(competition_season, before, played=None) -> dict[int, str]:
    """{player_id: motivo} per chi salta la partita che si gioca a ``before``.

    Si guarda l'ULTIMA partita giocata da ciascuna squadra prima di quell'istante,
    che e' l'unica su cui una squalifica di una giornata puo' essere stata
    comminata. Un rosso o una seconda gialla la' dentro, oppure un giallo che porta
    il conto a un multiplo di cinque: in entrambi i casi il giocatore non c'e'.

    Il conto delle ammonizioni e' cumulativo da inizio stagione e si ferma alla
    partita esaminata: un giallo preso dopo non puo' aver causato una squalifica
    prima.
    """
    played = _played_before(competition_season, before) if played is None else played
    if not played:
        return {}

    last_of_team: dict[int, int] = {}
    for m in played:
        last_of_team[m["home_team_id"]] = m["id"]
        last_of_team[m["away_team_id"]] = m["id"]
    last_matches = set(last_of_team.values())
    order = {m["id"]: i for i, m in enumerate(played)}

    cards = defaultdict(list)
    for mid, pid, ct in (MatchDisciplinaryEvent.objects
                         .filter(match_id__in=list(order), player__isnull=False)
                         .values_list("match_id", "player_id", "card_type")):
        cards[pid].append((order[mid], ct, mid))

    out: dict[int, str] = {}
    for pid, events in cards.items():
        events.sort()
        yellows = 0
        for _, ct, mid in events:
            if ct == CARD_YELLOW:
                yellows += 1
            if mid not in last_matches:
                continue
            if ct in (CARD_RED, CARD_SECOND_YELLOW):
                out[pid] = "espulso nell'ultima partita"
            elif ct == CARD_YELLOW and yellows % YELLOW_SUSPENSION_EVERY == 0:
                out[pid] = f"squalificato ({yellows}a ammonizione)"
    return out


# --- il priore: quanto spesso gioca ------------------------------------------

def _team_schedule(played: list[dict]) -> dict[int, list[int]]:
    """{team_season_id: [match_id...]} — le ultime ``FORM_WINDOW`` partite giocate
    da ciascuna squadra, IN ORDINE DI DATA (v. ``_played_before``: e' la stessa
    ragione, e una finestra ordinata per giornata dopo un recupero pesa la partita
    sbagliata come "la piu' recente")."""
    sched = defaultdict(list)
    for m in played:
        sched[m["home_team_id"]].append(m["id"])
        sched[m["away_team_id"]].append(m["id"])
    return {ts: ids[-FORM_WINDOW:] for ts, ids in sched.items()}


def _value_prior_means(team_ids: list[int]) -> dict[int, float]:
    """{player_id: media del priore} dal valore di mercato, per RANGO dentro la
    rosa — non dal prezzo assoluto.

    Il rango e non l'importo perche' la domanda e' "gioca?", e si gioca contro i
    propri compagni: dieci milioni sono tanti in una squadra e la panchina in
    un'altra. Chi non ha un valore resta al centro, che e' il modo giusto di dire
    che di lui non sappiamo niente.
    """
    centre = PRIOR_STARTS / PRIOR_OPPORTUNITIES
    values: dict[int, dict[int, float]] = {}
    latest: dict[int, float] = {}
    for pid, v in (PlayerMarketValue.objects
                   .filter(provider="transfermarkt",
                           player__team_stints__team_season_id__in=team_ids)
                   .order_by("player_id", "-as_of")
                   .values_list("player_id", "value_eur")):
        if v is not None:
            latest.setdefault(pid, float(v))
    for ts in team_ids:
        squad = [pid for pid in PlayerTeamStint.objects
                 .filter(team_season_id=ts, end_date__isnull=True)
                 .values_list("player_id", flat=True) if pid in latest]
        values[ts] = {}
        if len(squad) < 2:
            continue
        ranked = sorted(squad, key=lambda pid: latest[pid])
        for i, pid in enumerate(ranked):
            pct = i / (len(ranked) - 1)            # 0 = il piu' economico
            values[ts][pid] = centre + VALUE_PRIOR_SPREAD * (2 * pct - 1)
    return {pid: m for per_team in values.values() for pid, m in per_team.items()}


def _form(played: list[dict], team_ids: list[int]) -> dict[int, float]:
    """{player_id: media voto pesata per recenza, nella finestra}.

    Lo stesso decadimento del priore, e per la stessa ragione: la partita di tre
    settimane fa dice meno di quella di domenica. Solo chi ha giocato ha una
    media; chi non ha giocato non ha una forma, ha un'assenza — e quella la conta
    gia' il priore.
    """
    sched = _team_schedule(played)
    wanted = {ts: sched.get(ts, []) for ts in team_ids}
    position = {ts: {mid: i for i, mid in enumerate(ids)} for ts, ids in wanted.items()}
    all_ids = {mid for ids in wanted.values() for mid in ids}
    if not all_ids:
        return {}
    num: dict[int, float] = defaultdict(float)
    den: dict[int, float] = defaultdict(float)
    for mid, pid, ts, raw in (MatchAppearance.objects
                              .filter(match_id__in=all_ids, team_season_id__in=team_ids)
                              .values_list("match_id", "player_id", "team_season_id",
                                           "raw_stats")):
        rating = (raw or {}).get("rating")
        if rating is None:
            continue
        i = position.get(ts, {}).get(mid)
        if i is None:
            continue
        w = RECENCY ** (len(wanted[ts]) - 1 - i)
        num[pid] += w * float(rating)
        den[pid] += w
    return {pid: num[pid] / den[pid] for pid in num if den[pid] > 0}


def _priors(played: list[dict], team_ids: list[int]) -> tuple[dict, dict, dict]:
    """({(team_season_id, player_id): priore}, {team_season_id: priore di chi non
    ha mai iniziato}, {team_season_id: quante partite ha in finestra}).

    Il denominatore sono le OCCASIONI, cioe' tutte le partite della finestra —
    non le partite in cui il giocatore c'era. Chi e' stato fuori un mese scende, e
    deve scendere: la domanda non e' "quando c'e', gioca?" ma "gioca domenica?".
    """
    sched = _team_schedule(played)
    wanted = {ts: sched.get(ts, []) for ts in team_ids}
    position = {ts: {mid: i for i, mid in enumerate(ids)} for ts, ids in wanted.items()}
    all_ids = {mid for ids in wanted.values() for mid in ids}

    starts: dict[int, dict[int, float]] = {ts: defaultdict(float) for ts in team_ids}
    if all_ids:
        for mid, pid, ts, is_starter in (MatchAppearance.objects
                                         .filter(match_id__in=all_ids,
                                                 team_season_id__in=team_ids)
                                         .values_list("match_id", "player_id",
                                                      "team_season_id", "is_starter")):
            if not is_starter:
                continue
            i = position.get(ts, {}).get(mid)
            if i is None:
                continue
            starts[ts][pid] += RECENCY ** (len(wanted[ts]) - 1 - i)

    # La media del priore e' quella del giocatore, non una costante: e' il posto
    # in cui il valore di mercato entra, e l'unico. Il conteggio delle presenze le
    # sta sopra e la sovrasta appena ce n'e'.
    means = _value_prior_means(team_ids)
    centre = PRIOR_STARTS / PRIOR_OPPORTUNITIES

    priors: dict[tuple[int, int], float] = {}
    floor: dict[int, float] = {}
    history: dict[int, int] = {}
    for ts in team_ids:
        ids = wanted.get(ts) or []
        history[ts] = len(ids)
        occasions = sum(RECENCY ** (len(ids) - 1 - i) for i in range(len(ids)))
        floor[ts] = centre * PRIOR_OPPORTUNITIES / (occasions + PRIOR_OPPORTUNITIES)
        for pid, s_ in starts[ts].items():
            m = means.get(pid, centre)
            priors[(ts, pid)] = ((s_ + m * PRIOR_OPPORTUNITIES)
                                 / (occasions + PRIOR_OPPORTUNITIES))
    return priors, floor, history


# --- gli indizi ---------------------------------------------------------------

def _evidence_for(competition_season, matchday: int, player_ids) -> dict[int, list]:
    """{player_id: [LineupEvidence...]} valide per questa giornata."""
    now = timezone.now()
    rows = (LineupEvidence.objects
            .filter(competition_season=competition_season, player_id__in=player_ids)
            .filter(Q(matchday__isnull=True) | Q(matchday=matchday))
            .filter(Q(valid_until__isnull=True) | Q(valid_until__gte=now)))
    by_player = defaultdict(list)
    for e in rows:
        by_player[e.player_id].append(e)
    return by_player


# --- la calibrazione a undici -------------------------------------------------

def _calibrate(logits: list[float], target: float) -> list[float]:
    """Sposta TUTTI i logit della stessa quantita' finche' la somma delle
    probabilita' non fa ``target``. Non cambia l'ordine di nessuno."""
    if not logits or target <= 0:
        return logits
    lo, hi = -12.0, 12.0
    for _ in range(60):
        mid = (lo + hi) / 2
        total = sum(_sigmoid(x + mid) for x in logits)
        if total < target:
            lo = mid
        else:
            hi = mid
    shift = (lo + hi) / 2
    return [x + shift for x in logits]


# --- il calcolo ---------------------------------------------------------------

def forecast_teams(competition_season, before, team_ids: list[int], *,
                   matchday: int | None = None) -> dict[int, list[PlayerForecast]]:
    """{team_season_id: [PlayerForecast ordinati per probabilita' decrescente]}.

    ``before`` e' il calcio d'inizio della partita da prevedere: tutto cio' che si
    guarda deve essere accaduto prima di quell'istante, e questa e' l'unica
    barriera contro il guardare avanti. ``matchday`` serve solo a pescare gli
    indizi scritti per quella giornata.
    """
    played = _played_before(competition_season, before)
    squads = defaultdict(list)
    gk = {}
    for pid, ts, is_gk in (PlayerTeamStint.objects
                           .filter(team_season_id__in=team_ids, end_date__isnull=True)
                           .values_list("player_id", "team_season_id",
                                        "player__is_goalkeeper")):
        squads[ts].append(pid)
        gk[pid] = bool(is_gk)

    priors, floor, history = _priors(played, team_ids)
    value_means = _value_prior_means(team_ids)
    centre = PRIOR_STARTS / PRIOR_OPPORTUNITIES
    form = _form(played, team_ids) if FORM_LOGIT_PER_VOTE else {}
    sched_now = _team_schedule(played)
    occasions_of = {ts: sum(RECENCY ** (len(sched_now.get(ts, [])) - 1 - i)
                            for i in range(len(sched_now.get(ts, []))))
                    for ts in team_ids}
    banned = suspensions_for(competition_season, before, played=played)
    all_players = [pid for ids in squads.values() for pid in ids]
    evidence = _evidence_for(competition_season, matchday, all_players)

    result: dict[int, list[PlayerForecast]] = {}
    for ts in team_ids:
        # UNA SQUADRA SENZA STORIA NON HA UNA PREVISIONE, e non deve fingere di
        # averne una. Con zero partite in finestra ogni priore vale il fondo, tutti
        # i giocatori escono con LA STESSA probabilita', e ``predicted_xi`` finisce
        # per scegliere gli undici ``player_id` piu' bassi — cioe' l'ordine di
        # importazione. Misurato alla prima giornata della 25-26: un solo valore
        # (0,4762) per tutti i giocatori di movimento, e un 53,6% di XI "azzeccati"
        # che e' l'ordine con cui Transfermarkt elenca la rosa, non conoscenza.
        #
        # Una partita basta: alla seconda giornata il motore fa 80,0%, il massimo
        # di tutta la stagione. Zero no. E alla prima giornata la previsione la
        # porta SofaScore, che le notizie le sa gia' (v. probable_lineups.merged,
        # che tiene chi c'e' solo da loro).
        if not history.get(ts):
            continue
        rows: list[PlayerForecast] = []
        for pid in squads.get(ts, []):
            f = PlayerForecast(player_id=pid, team_season_id=ts, probability=0.0,
                               is_goalkeeper=gk.get(pid, False))
            if pid in banned:
                f.out, f.reason = True, banned[pid]
            hard = [e for e in evidence.get(pid, [])
                    if e.availability == LineupEvidence.AVAIL_OUT]
            if hard and not f.out:
                f.out = True
                f.reason = hard[0].note or hard[0].get_kind_display().lower()
            f.evidence = evidence.get(pid, [])
            rows.append(f)

        live = [f for f in rows if not f.out]
        for group, target in ((True, 1.0), (False, 10.0)):
            part = [f for f in live if f.is_goalkeeper is group]
            if not part:
                continue
            logits = []
            for f in part:
                base = priors.get((ts, f.player_id))
                if base is None:
                    # Nessuna presenza da titolare in finestra: qui il valore e'
                    # tutto quello che abbiamo, ed e' la meta' del suo mestiere.
                    m = value_means.get(f.player_id, centre)
                    base = m * PRIOR_OPPORTUNITIES / (occasions_of.get(ts, 0.0)
                                                      + PRIOR_OPPORTUNITIES)
                shift = sum(e.log_odds for e in f.evidence
                            if e.availability != LineupEvidence.AVAIL_OUT)
                # La forma e' un indizio come gli altri e passa dalla stessa
                # somma: chi sta giocando bene viene riconfermato piu' spesso.
                voto = form.get(f.player_id)
                if voto is not None:
                    shift += FORM_LOGIT_PER_VOTE * max(-2.0, min(2.0, voto - 6.0))
                logits.append(max(-MAX_LOGIT, min(MAX_LOGIT, _logit(base) + shift)))
            for f, x in zip(part, _calibrate(logits, min(target, len(part) * 0.98))):
                f.probability = _sigmoid(x)
        rows.sort(key=lambda f: (-f.probability, f.player_id))
        result[ts] = rows
    return result


def predicted_xi(rows: list[PlayerForecast]) -> set[int]:
    """Gli undici: il portiere piu' probabile, e i dieci di movimento sopra."""
    live = [f for f in rows if not f.out]
    keepers = [f for f in live if f.is_goalkeeper]
    others = [f for f in live if not f.is_goalkeeper]
    xi = {keepers[0].player_id} if keepers else set()
    xi |= {f.player_id for f in others[:10]}
    return xi


def build_forecast(match, *, matchday: int | None = None,
                   now=None) -> LineupForecast | None:
    """Scrive (o riscrive) la previsione del NOSTRO motore per una partita.

    ``now`` e' l'istante del chiamante, non l'orologio di sistema, e la
    differenza non e' accademica: il timbro che si lascia qui e' quello su cui il
    cancello di ``refresh_all`` decide se ricalcolare. Sotto simulazione — dove il
    tick vive a febbraio e il processo ad agosto — timbrare con
    ``timezone.now()`` lascia il timbro SEMPRE indietro rispetto ai dati, e il
    cancello non si chiude mai: si ricalcola tutto a ogni minuto, in silenzio.
    """
    md = matchday if matchday is not None else match.matchday
    if match.kickoff is None:
        return None    # senza un orario non c'e' un "prima": v. _played_before
    teams = [match.home_team_id, match.away_team_id]
    per_team = forecast_teams(match.competition_season, match.kickoff, teams,
                              matchday=md)
    # Nessuna delle due squadre ha storia: non si scrive una previsione vuota, che
    # in tabella sarebbe indistinguibile da una previsione che c'e' ed e' tutta a
    # zero. Chi legge deve trovare "niente", e dire "non ancora".
    if not any(per_team.get(ts) for ts in teams):
        return None

    fc, _ = LineupForecast.objects.get_or_create(
        match=match, source=LineupForecast.SOURCE_VFOOT)
    previous = dict(LineupForecastEntry.objects.filter(forecast=fc)
                    .values_list("player_id", "probability"))
    LineupForecastEntry.objects.filter(forecast=fc).delete()

    entries = []
    for ts in teams:
        rows = per_team.get(ts, [])
        xi = predicted_xi(rows)
        for f in rows:
            pct = 0 if f.out else int(round(f.probability * 100))
            if f.out:
                status = LineupForecastEntry.STATUS_OUT
            elif f.player_id in xi:
                status = LineupForecastEntry.STATUS_STARTER
            else:
                status = LineupForecastEntry.STATUS_BENCH
            entries.append(LineupForecastEntry(
                forecast=fc, player_id=f.player_id, team_season_id=ts,
                probability=pct, previous_probability=previous.get(f.player_id),
                status=status, reason=f.reason[:120]))
    LineupForecastEntry.objects.bulk_create(entries)
    fc.refreshed_at = now or timezone.now()
    fc.save(update_fields=["refreshed_at"])
    return fc
