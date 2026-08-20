"""Chiedersi, al momento di mostrarla, se una notifica ha ancora senso.

Una push non e' un messaggio istantaneo. Il servizio del dispositivo (FCM, APNs,
autopush) la mette in coda e la consegna quando quel browser si ricollega: chi
decide un ruolo dal telefono alle 16 e accende il computer alle 18 se la vede
arrivare li', identica, e cliccandola trova una pagina dove non c'e' piu' niente
da fare. Segnalato il 20/08/2026.

Non e' un duplicato da sopprimere e non e' un errore di invio: e' la STESSA
notifica, mandata a due installazioni dello stesso utente, consegnata in ritardo
alla seconda. Nessuno dei due lati puo' saperlo al momento della partenza --
quando e' partita c'era davvero qualcosa da decidere -- quindi l'unico posto in
cui la domanda ha una risposta e' il momento in cui la si mostra. Percio' ogni
push che chiede di FARE qualcosa porta con se' un gettone firmato; il service
worker lo presenta prima di aprire la tendina e questo modulo risponde una cosa
sola: per quella persona, in quella lega, c'e' ancora qualcosa da fare?

**Firmato e non autenticato, di proposito.** Il worker non ha il token
dell'utente -- sta in localStorage, che lui non vede -- e per consegnare una push
viene svegliato da freddo, senza nessuna finestra aperta a cui chiederlo. Il
gettone e' firmato con la SECRET_KEY, scade, e vale per UNA domanda soltanto
(utente, tipo, lega) la cui risposta e' un booleano: chi lo intercettasse non
otterrebbe altro che quel si'/no, e per intercettarlo dovrebbe gia' essere sul
dispositivo, visto che il corpo della push viaggia cifrato (RFC 8291).

**Le notizie non passano di qui.** «La decisione e' stata presa», «la tua
formazione e' cambiata», un gol: restano vere anche il giorno dopo. Si controlla
solo cio' che CHIEDE UN'AZIONE, cioe' l'unica cosa che qualcun altro -- o tu
stesso, da un altro dispositivo -- puo' avere gia' fatto al posto tuo.

E in caso di dubbio si mostra. Una notifica di troppo e' una seccatura; una
notifica soppressa per un errore nostro e' un mercato fermo di cui nessuno viene
avvisato, quindi ogni risposta incerta (firma illeggibile, gettone scaduto,
errore interrogando il database) vale «non e' stantia».
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core import signing

log = logging.getLogger(__name__)

SALT = "vfoot.push.relevance"

KIND_DECISIONS = "decisions"          # ruoli da decidere (amministratore)
KIND_CONSULTATIONS = "consultations"  # pareri da dare (partecipante)
KIND_CONCLUSIONS = "conclusions"      # giornate da chiudere (amministratore)


def mint(user, kind: str, ref: int) -> str:
    """Il gettone da infilare nella push. Sollevare qui e' giusto: un tipo che
    non esiste e' un errore di programmazione, non una condizione di rete."""
    if kind not in _RULES:
        raise ValueError(f"Tipo di controllo sconosciuto: {kind}")
    return signing.dumps({"u": user.id, "k": kind, "r": int(ref)},
                         salt=SALT, compress=True)


def is_stale(token: str) -> bool:
    """C'e' ancora qualcosa da fare? Se non si riesce a dirlo, la notifica si
    mostra: v. l'ultimo capoverso del docstring del modulo."""
    try:
        claim = signing.loads(str(token or ""), salt=SALT, max_age=_max_age())
    except signing.BadSignature:
        # Scaduto o manomesso. Scaduto e' il caso normale: il TTL della push e'
        # gia' passato e questa consegna non dovrebbe nemmeno essere avvenuta.
        return False
    rule = _RULES.get(claim.get("k"))
    if rule is None:
        return False
    user = User.objects.filter(id=claim.get("u"), is_active=True).first()
    if user is None:
        return False
    try:
        return not rule(user, int(claim.get("r") or 0))
    except Exception:                                     # noqa: BLE001
        log.exception("Controllo di pertinenza fallito per la push %s", claim)
        return False


def _max_age() -> int:
    """Oltre il TTL della push il gettone non serve a nessuno: se il servizio
    l'avesse tenuta cosi' a lungo l'avrebbe gia' buttata via lui. Un giorno di
    margine per gli orologi e per un TTL alzato dopo l'invio."""
    return int(getattr(settings, "VFOOT_PUSH_TTL_SECONDS", 86400)) + 86400


def _league(league_id: int):
    from vfoot.models import FantasyLeague
    return FantasyLeague.objects.filter(id=league_id).first()


def _is_admin(league, user) -> bool:
    """Come lo intende chi manda queste notifiche (v. ``_push_new_decisions``):
    gli amministratori piu' il proprietario. Conta anche qui perche' perdere i
    permessi rende la richiesta priva di oggetto quanto averla gia' evasa."""
    from vfoot.models import LeagueMembership
    return bool(league.owner_id == user.id
                or LeagueMembership.objects.filter(
                    league=league, user=user,
                    role=LeagueMembership.ROLE_ADMIN).exists())


def _roles_to_decide(user, league_id: int) -> bool:
    from vfoot.services.league_decisions import blocking_decisions
    league = _league(league_id)
    return bool(league and _is_admin(league, user)
                and blocking_decisions(league).exists())


def _opinions_to_give(user, league_id: int) -> bool:
    from vfoot.services.league_decisions import attention_count
    league = _league(league_id)
    return bool(league and attention_count(league, user) > 0)


def _matchdays_to_close(user, league_id: int) -> bool:
    from vfoot.services import matchday_state
    league = _league(league_id)
    return bool(league and _is_admin(league, user)
                and matchday_state.conclusion_queue(league))


# Tipo -> «c'e' ancora qualcosa da fare per costui?». La push e' stantia quando
# la risposta e' no.
_RULES = {
    KIND_DECISIONS: _roles_to_decide,
    KIND_CONSULTATIONS: _opinions_to_give,
    KIND_CONCLUSIONS: _matchdays_to_close,
}
