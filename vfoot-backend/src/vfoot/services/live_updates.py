"""What the leagues are told while a real match is being played.

Two channels, and they are for opposite situations — the distinction is the whole
design, not a detail of it:

* **the WebSocket nudge** reaches pages that are OPEN. It fires after any import
  that moved anything, carries no data, and its only job is to make the page
  re-read. Cheap enough to send every ten minutes for two hours.
* **the push** reaches people who are NOT looking — the phone in a pocket, the app
  closed. It costs the user's attention every single time, so it is spent only on
  what would make somebody put down what they are doing: **a goal by one of his
  players, a sending-off, and full time**. Never a vote that moved; that would be a
  notification every ten minutes per match, which is the fastest way to have the
  permission revoked for good.

WHO GETS THE PUSH. Whoever FIELDED the player in the matchday being played — read
from the saved lineup, not from the roster. Owning a player you left on the bench
is not a reason to be woken up, and the bench itself is: a benched player who has
come on is scoring for you.

CHE COSA E' ACCADUTO, MENO CIO' CHE E' GIA' STATO DETTO. Fino al 31/08/2026 gli
eventi si leggevano dalla DIFFERENZA fra due istantanee della partita prese ai due
lati dell'import. Era elegante e sbagliato in due modi opposti, trovati insieme
grazie a una segnalazione:

* *un gol poteva sparire per sempre*. Se l'import scriveva il gol ma l'annuncio non
  girava — tick ucciso, import fallito a meta' — il giro dopo quel gol era gia'
  nell'istantanea «prima»: nessuno lo annunciava piu', e non restava una riga.
* *e la ritrattazione non esisteva*. La differenza guardava solo le salite.

Adesso lo stato di cio' che e' stato annunciato sta in una tabella
(``LiveEventNotice``), e ogni giro confronta la realta' con quella. Idempotente per
costruzione, e il calo di un gol e' un evento come la sua comparsa.

DUE TESTIMONI PER UN GOL. ``MatchAppearance.goals`` e' lo specchio di UN campo del
fornitore (``statistics.goals`` della distinta) e in diretta e' provvisorio: il
29/08/2026 ha attribuito per qualche minuto un gol a Guðmundsson, in una partita
dove il punteggio non si era mosso, la mappa dei tiri segnava quel tiro come
respinto e nel tabellino finale il gol non c'e' mai stato — e la notifica falsa era
gia' partita. Da allora un gol si annuncia solo se lo conferma anche la mappa dei
tiri, che arriva dalla stessa quaterna di richieste e non costa niente in piu'.
"""
from __future__ import annotations

import logging

from django.utils import timezone

from realdata.models import (
    CARD_RED, CARD_SECOND_YELLOW, Match, MatchAppearance,
    MatchDisciplinaryEvent, MatchShot, Player, PlayerTeamStint,
)
from vfoot.models import (
    FantasyLeague, FantasyMatchday, LeagueMembership, LiveEventNotice,
    PushSubscription, SavedLineupSnapshot,
)
from vfoot.services import push_channel

log = logging.getLogger(__name__)

SENT_OFF = (CARD_RED, CARD_SECOND_YELLOW)

# Where a tapped notification lands: the league home, which is where the section
# with the matches being played is — one tap from every tabellino of the round.
# Not the fixture page directly, because "which fixture" depends on who is reading
# and a notification is composed once for several people.
LIVE_URL = "/home"


# --------------------------------------------------------------------------- #
# The nudge                                                                    #
# --------------------------------------------------------------------------- #
def leagues_following(match: Match):
    """Every league whose reference season is the one this match belongs to.

    A league follows a whole championship, not individual matches: it is the round
    that is being played, and any of its ten matches can move any of its tabellini.
    """
    return FantasyLeague.objects.filter(
        reference_season_id=match.competition_season_id)


def leagues_to_nudge(match: Match) -> set[int]:
    """The league ids that would want to hear about this match changing.

    Collected rather than nudged on the spot: a tick that imports the three matches
    of a Sunday evening would otherwise send three nudges, and every open page would
    re-read the whole calendar three times in eight seconds. The round changed once.
    """
    return set(leagues_following(match).values_list("id", flat=True))


def broadcast_leagues(league_ids) -> int:
    """Send ONE nudge per league. Returns how many went out."""
    from vfoot.services.live_realtime import broadcast_live

    ids = sorted(set(league_ids))
    for league_id in ids:
        broadcast_live(league_id, kind="scores")
    return len(ids)


def broadcast_match(match: Match) -> int:
    """Nudge every league following this match — the single-match convenience."""
    return broadcast_leagues(leagues_to_nudge(match))


# --------------------------------------------------------------------------- #
# Che cosa e' accaduto                                                         #
# --------------------------------------------------------------------------- #
def corroborated_goals(match: Match) -> dict[int, int]:
    """{player_id: gol che si possono AFFERMARE} — il MINIMO fra i due testimoni.

    I due testimoni arrivano dalle stesse quattro richieste che ogni round leggero
    fa gia', quindi il secondo non costa niente:

    * il tabellino (``MatchAppearance.goals``), che e' lo specchio di un solo campo
      della distinta del fornitore e in diretta e' provvisorio;
    * la mappa dei tiri (``MatchShot.is_goal``), che e' un'altra chiamata e un'altra
      struttura, e che sul dato definitivo concorda col tabellino su 882 gol su 882.

    Il minimo, e non l'uno o l'altro: chi ne dice meno tiene fermo l'annuncio, che e'
    esattamente cio' che serviva il 29/08/2026 col gol mai esistito di Guðmundsson.
    E tenerlo fermo non costa il gol — l'annuncio non guarda piu' una differenza, ma
    il registro — costa al massimo il round successivo, due minuti.

    L'autogol non e' un gol di chi lo segna e la domanda si fa in un posto solo, v.
    ``classic_rating.is_own_goal``: SofaScore lo archivia come un tiro 'goal' taggato
    con la squadra PER CUI conta, cioe' l'avversaria di chi ha tirato.
    """
    from vfoot.services.classic_rating import is_own_goal

    claimed: dict[int, int] = {}
    side: dict[int, str] = {}
    for pid, goals, sd in MatchAppearance.objects.filter(match=match).values_list(
            "player_id", "goals", "side"):
        side[pid] = sd
        if goals:
            claimed[pid] = int(goals)
    if not claimed:
        return {}
    seen: dict[int, int] = {}
    for pid, shot_type, team_side in MatchShot.objects.filter(
            match=match, is_goal=True, player_id__in=list(claimed)).values_list(
            "player_id", "shot_type", "team_side"):
        if is_own_goal(shot_type, team_side, side.get(pid)):
            continue
        seen[pid] = seen.get(pid, 0) + 1
    return {pid: min(n, seen[pid]) for pid, n in claimed.items() if seen.get(pid)}


def sent_off(match: Match) -> set[int]:
    """Chi e' stato espulso. Testimone unico e va bene cosi': i cartellini vivono
    SOLO negli incidenti del fornitore, che sono la loro sede propria — non un
    riflesso di qualcos'altro come lo era il conteggio dei gol."""
    return set(MatchDisciplinaryEvent.objects
               .filter(match=match, card_type__in=SENT_OFF)
               .values_list("player_id", flat=True))


def _still_said(match: Match) -> set[tuple[int, str, int]]:
    """Cio' che e' stato annunciato E NON SMENTITO.

    Le smentite si escludono di proposito: un gol annullato e poi restituito (il VAR
    che si rimangia il VAR) e' di nuovo una notizia, e chi si e' visto arrivare
    «annullato» ha diritto di sapere che invece vale. Il costo teorico e' un
    fornitore che oscilla e fa da altalena; non se n'e' mai visto uno, e l'altra
    scelta — tacere per sempre dopo una smentita — sbaglia su un caso che capita.
    """
    return {(n.player_id, n.kind, n.occurrence)
            for n in LiveEventNotice.objects.filter(match=match,
                                                    retracted_at__isnull=True)}


def pending_events(match: Match, goals: dict[int, int],
                   reds: set[int]) -> list[tuple[int, str, int]]:
    """(giocatore, tipo, occorrenza) accaduti e non ancora annunciati.

    ``occurrence`` e' il QUALE, non il quanti: il secondo gol dello stesso giocatore
    e' una notizia a se' e prende una notifica a se'. Prima era il delta di un round
    — «doppietta» voleva dire due gol capitati nella stessa finestra di due minuti,
    che non e' una proprieta' della partita ma della nostra cadenza.
    """
    said = _still_said(match)
    out: list[tuple[int, str, int]] = []
    for pid, count in goals.items():
        out += [(pid, LiveEventNotice.KIND_GOAL, occ)
                for occ in range(1, count + 1)
                if (pid, LiveEventNotice.KIND_GOAL, occ) not in said]
    out += [(pid, LiveEventNotice.KIND_RED, 1) for pid in reds
            if (pid, LiveEventNotice.KIND_RED, 1) not in said]
    return out


def stale_notices(match: Match, goals: dict[int, int],
                  reds: set[int]) -> list[LiveEventNotice]:
    """Cio' che avevamo annunciato e che la partita non conferma piu'.

    Il fornitore toglie: un gol dato e poi annullato dal VAR, un rosso corretto in
    giallo. Chi legge ha in tendina una notizia falsa e nessuno gliel'ha smentita —
    finche' l'annuncio guardava solo le salite, la ritrattazione non esisteva
    proprio. Le gia' ritrattate non si guardano: la smentita si manda una volta.
    """
    out = []
    for notice in LiveEventNotice.objects.filter(match=match,
                                                 retracted_at__isnull=True):
        if notice.kind == LiveEventNotice.KIND_GOAL:
            alive = notice.occurrence <= goals.get(notice.player_id, 0)
        else:
            alive = notice.player_id in reds
        if not alive:
            out.append(notice)
    return out


# --------------------------------------------------------------------------- #
# Who is fielding whom                                                         #
# --------------------------------------------------------------------------- #
def _playing_matchdays(match: Match):
    """The (league, FantasyMatchday) pairs this match feeds, still open.

    A concluded matchday is frozen: whatever happens in a recovery of it is the
    admin's business, not a notification's.
    """
    if match.matchday is None:
        return []
    return [
        (md.league, md) for md in
        FantasyMatchday.objects
        .filter(real_competition_season_id=match.competition_season_id,
                real_matchday=match.matchday)
        .exclude(status=FantasyMatchday.STATUS_CONCLUDED)
        .select_related("league")
    ]


def _managers_fielding(league, md, player_ids: set) -> dict:
    """{player_id: [user, ...]} — who has each player in a saved lineup this round.

    Read from the snapshots directly rather than through ``read_saved_lineup``: that
    one resolves ONE team's lineup for one competition, and here the question is the
    other way round (who, in this whole league, fielded any of these players). A
    league with a cup as well as a championship has several lineups per team and
    every one of them counts — the player is playing for that manager either way.

    ``lineup_id`` is ``team<id>`` or ``team<id>:comp<n>``; the team is its prefix.
    """
    if not player_ids:
        return {}
    users_by_team = {
        mem.team.id: mem.user
        for mem in LeagueMembership.objects.filter(league=league)
        .select_related("user", "team")
        if getattr(mem, "team", None) is not None
    }
    out: dict[int, list] = {}
    for snap in SavedLineupSnapshot.objects.filter(
            league_id=str(league.id), matchday_id=str(md.real_matchday),
            lineup_id__startswith="team"):
        team_id = _team_of_lineup(snap.lineup_id)
        user = users_by_team.get(team_id)
        if user is None:
            continue
        fielded = {int(x) for x in (snap.starter_player_ids or [])}
        fielded |= {int(x) for x in (snap.bench_player_ids or [])}
        if snap.gk_player_id:
            fielded.add(int(snap.gk_player_id))
        for pid in fielded & player_ids:
            bucket = out.setdefault(pid, [])
            if user not in bucket:
                bucket.append(user)
    return out


def _team_of_lineup(lineup_id: str) -> int | None:
    head = str(lineup_id or "").split(":")[0]
    return int(head[4:]) if head[:4] == "team" and head[4:].isdigit() else None


# --------------------------------------------------------------------------- #
# The two announcements                                                        #
# --------------------------------------------------------------------------- #
# Chi ha segnato piu' di una volta: la parola giusta esiste fino alla quaterna, e
# oltre si conta. Detta dall'occorrenza, che e' un fatto della partita — prima era
# il delta di un round, cioe' un fatto della nostra cadenza.
_MULTIPLE = {2: "doppietta", 3: "tripletta", 4: "quaterna"}


def announce_events(match: Match) -> int:
    """Annuncia cio' che e' accaduto e non e' ancora stato detto, e smentisce cio'
    che il fornitore ha tolto. Restituisce quante consegne sono partite.

    Never raises: this runs inside the tick, and a push service having a bad minute
    must not cost an import.
    """
    try:
        return _announce_events(match)
    except Exception:  # noqa: BLE001
        log.exception("Notifiche live fallite per la partita %s", match.id)
        return 0


def _announce_events(match: Match) -> int:
    if not push_channel.configured():
        return 0
    goals = corroborated_goals(match)
    reds = sent_off(match)
    fresh = pending_events(match, goals, reds)
    stale = stale_notices(match, goals, reds)
    if not fresh and not stale:
        return 0
    names = dict(Player.objects
                 .filter(id__in=[pid for pid, _k, _o in fresh]
                                + [n.player_id for n in stale])
                 .values_list("id", "full_name"))
    return (_say(match, fresh, names) + _unsay(match, stale, names))


def _say(match: Match, events, names: dict) -> int:
    """Manda le notifiche nuove e ne lascia la riga.

    La riga si scrive SEMPRE, anche quando non l'aspettava nessuno: «e' successo, e
    non interessava a nessuno» e «non e' ancora stato valutato» sono fatti opposti, e
    senza distinguerli ogni round riesaminerebbe in eterno gli stessi eventi.
    """
    if not events:
        return 0
    audience = _audience(match, {pid for pid, _k, _o in events})
    sent = 0
    for pid, kind, occ in events:
        name = names.get(pid, str(pid))
        if kind == LiveEventNotice.KIND_GOAL:
            title = _goal_title(name, occ)
            body = f"{_scoreline(match)} · il voto si sta muovendo."
        else:
            title = f"🟥 {name} espulso"
            body = f"{_scoreline(match)} · la sua partita finisce qui."
        recipients = []
        for user in audience.get(pid, []):
            got = push_channel.send_to_user(
                user, title=title, body=body, url=LIVE_URL,
                tag=_tag(match, pid, kind, occ),
                # Un gol scade: fra due minuti non e' piu' una notizia, e il
                # servizio del dispositivo e' libero di rimandare cio' che non e'
                # marcato urgente finche' lo schermo non si riaccende.
                urgency=push_channel.URGENCY_HIGH)
            recipients.append({"user_id": user.id, "username": user.username,
                               "devices": _devices(user), "delivered": got})
            sent += got
        LiveEventNotice.objects.update_or_create(
            match=match, player_id=pid, kind=kind, occurrence=occ,
            defaults={"recipients": recipients, "retracted_at": None,
                      "created_at": timezone.now()})
    return sent


def _unsay(match: Match, notices, names: dict) -> int:
    """Smentisce cio' che il fornitore ha tolto, alle stesse persone e sullo stesso
    tag — cosi' la smentita PRENDE IL POSTO della notizia falsa in tendina invece di
    affiancarla. I destinatari si rileggono dalla riga e non si ricalcolano: chi ha
    ricevuto l'annuncio ha diritto alla rettifica anche se nel frattempo ha cambiato
    formazione.
    """
    if not notices:
        return 0
    from django.contrib.auth.models import User

    users = {u.id: u for u in User.objects.filter(
        id__in=[r.get("user_id") for n in notices for r in (n.recipients or [])])}
    sent = 0
    for notice in notices:
        name = names.get(notice.player_id, str(notice.player_id))
        if notice.kind == LiveEventNotice.KIND_GOAL:
            title = f"❌ Annullato il gol di {name}"
            body = f"{_scoreline(match)} · il dato è stato corretto: quel gol non c'è."
        else:
            title = f"❌ {name} non è espulso"
            body = f"{_scoreline(match)} · il cartellino è stato corretto."
        for row in (notice.recipients or []):
            user = users.get(row.get("user_id"))
            if user is None:
                continue
            sent += push_channel.send_to_user(
                user, title=title, body=body, url=LIVE_URL,
                tag=_tag(match, notice.player_id, notice.kind, notice.occurrence),
                urgency=push_channel.URGENCY_HIGH)
        notice.retracted_at = timezone.now()
        notice.save(update_fields=["retracted_at"])
    return sent


def _goal_title(name: str, occurrence: int) -> str:
    if occurrence == 1:
        return f"⚽ Gol di {name}"
    word = _MULTIPLE.get(occurrence)
    return f"⚽ {name}: {word}!" if word else f"⚽ {name}, {occurrence}° gol!"


def _tag(match: Match, player_id: int, kind: str, occurrence: int) -> str:
    """Uno per (partita, giocatore, tipo, occorrenza): un rinvio dello stesso evento
    SOSTITUISCE la notifica in tendina invece di impilarne una seconda copia, e il
    secondo gol dello stesso giocatore, che e' un altro evento, si mette accanto al
    primo invece di cancellarlo."""
    return f"live-{match.id}-{player_id}-{kind}-{occurrence}"


def _devices(user) -> int:
    return PushSubscription.objects.filter(user=user).count()


def _audience(match: Match, player_ids: set) -> dict[int, list]:
    """{player_id: [utenti]} — chi li ha schierati, in tutte le leghe che stanno
    giocando questa giornata, ciascuno una volta sola. Uno che gioca in due leghe
    con lo stesso giocatore in campo e' una persona, non due notifiche."""
    out: dict[int, list] = {}
    for league, md in _playing_matchdays(match):
        for pid, users in _managers_fielding(league, md, player_ids).items():
            bucket = out.setdefault(pid, [])
            for user in users:
                if all(user.id != seen.id for seen in bucket):
                    bucket.append(user)
    return out


def announce_full_time(match: Match) -> int:
    """Push "the match is over" to whoever had players in it.

    Full time, not the end of the round: it is the instant at which those players'
    votes stop moving, which is the thing the person following his matchday is
    actually waiting for. The end of the round is somebody else's event — the
    admin's — and it already has its own message.
    """
    try:
        return _announce_full_time(match)
    except Exception:  # noqa: BLE001
        log.exception("Notifica di fine partita fallita per %s", match.id)
        return 0


def _announce_full_time(match: Match) -> int:
    if not push_channel.configured():
        return 0
    played = set(MatchAppearance.objects.filter(match=match, minutes_played__gt=0)
                 .values_list("player_id", flat=True))
    if not played:
        # No squad sheet yet (the live import has not run, or was blocked). Fall
        # back to the two clubs' registered players: worse aim, but a full time
        # nobody is told about is worse still.
        played = set(PlayerTeamStint.objects.filter(
            team_season_id__in=[match.home_team_id, match.away_team_id],
            end_date__isnull=True).values_list("player_id", flat=True))
    sent = 0
    for league, md in _playing_matchdays(match):
        fielding = _managers_fielding(league, md, played)
        users = {u.id: u for users in fielding.values() for u in users}
        title = f"Finita: {_scoreline(match)}"
        body = ("I voti dei tuoi giocatori si assestano nell'ora prossima, "
                "poi diventano definitivi.")
        for user in users.values():
            sent += push_channel.send_to_user(
                user, title=title, body=body, url=LIVE_URL, tag=f"ft-{match.id}",
                urgency=push_channel.URGENCY_HIGH)
    return sent


def _scoreline(match: Match) -> str:
    home = match.home_team.team.name if match.home_team_id else "?"
    away = match.away_team.team.name if match.away_team_id else "?"
    hg = "-" if match.home_goals is None else match.home_goals
    ag = "-" if match.away_goals is None else match.away_goals
    return f"{home} {hg}-{ag} {away}"
