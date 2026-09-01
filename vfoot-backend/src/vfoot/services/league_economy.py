"""Le due cose che l'admin fa all'economia della lega dal di fuori: dare crediti,
e trascrivere uno scambio fra due allenatori.

Sono le due che il resto del sistema non sa fare da solo. L'asta e il mercato a
offerte muovono crediti seguendo un regolamento; queste due no — nascono da un
accordo preso a voce, e l'app le REGISTRA. Per questo l'unica autorita' e' l'admin
e non una regola, e per questo lasciano una riga: chi ha dato cosa a chi, e quando.

**Crediti** (``BudgetGrant``): la dote che si distribuisce prima di una sessione di
mercato, a uno o a tutti. E' l'unico numero del budget che nessun contratto
registra — v. la formula in ``auction_engine``.

**Scambio** (``PlayerTrade``): i contratti VIAGGIANO. Il giocatore comprato a 50
arriva alla nuova squadra *a 50*, non a una cifra nuova: il contratto si chiude a
incasso pieno di qua (nessun buco) e se ne riapre uno identico di la'. Cosi' un
eventuale svincolo futuro restituisce il recupero giusto — la plusvalenza resta di
chi l'ha costruita.

E IL RESIDUO NON SI MUOVE. Uno scambio e' un accordo alla pari: i due allenatori
hanno deciso che quei giocatori si equivalgono, non che uno vale piu' crediti
dell'altro. Se il residuo si contasse sui soli contratti, chi cede il piu' caro si
ritroverebbe in cassa crediti spesi mesi prima — Okoye a 20 che torna dentro come
Provedel a 3 sono diciassette crediti comparsi dal niente — e chi lo riceve ne
perderebbe altrettanti senza aver comprato nulla. Percio' la differenza fra i due
pacchetti di contratti si PAREGGIA in crediti dentro lo stesso scambio, in
silenzio: chi cede piu' valore di quanto ne riceve versa la differenza all'altro,
e i due residui restano quelli di prima. Quel che cambia davvero, ed e' l'unica
cosa che deve cambiare, e' quanto ciascuno potra' recuperare il giorno che lo
svincolera': 3 invece di 20.

L'unico numero che sposta i residui e' allora la CONTROPARTITA, che i due si sono
detti e l'admin trascrive.

In classic i ruoli comandano: si scambia **a coppie di pari ruolo** (un
centrocampista per un centrocampista, anche piu' coppie insieme). E' la stessa
regola del mercato a offerte, e per la stessa ragione: le rose restano complete per
costruzione, e nelle formazioni ancora aperte l'entrante puo' prendere il posto
esatto dell'uscente (R2 in ``lineup_repair``). In aura i ruoli non esistono e il
vincolo non ha ragione d'essere: le due liste possono avere lunghezze diverse, e
chi parte senza sostituto lascia la sua casella vuota — la stessa cosa, onesta, che
fa una rimozione a mano.

La contropartita in crediti e' una coppia di ``BudgetGrant`` legate allo scambio:
il saldo resta una somma di righe, e non c'e' un secondo posto da cui leggere i
soldi di un allenatore.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from django.utils import timezone

from vfoot.models import (
    BudgetGrant,
    FantasyLeague,
    FantasyRosterSlot,
    FantasyTeam,
    PlayerTrade,
)
from vfoot.services import (
    currency,
    league_notifications,
    lineup_baseline,
    lineup_repair,
)
from vfoot.services.auction_engine import league_role_map, team_budgets


class EconomyError(Exception):
    """Operazione rifiutata: il messaggio e' quello che legge l'admin."""


def _batch() -> str:
    return secrets.token_hex(8)


def _is_classic(league: FantasyLeague) -> bool:
    return league.mode == FantasyLeague.MODE_CLASSIC


# --------------------------------------------------------------------------- #
# Crediti
# --------------------------------------------------------------------------- #

def grant_credits(
    league: FantasyLeague, teams: list[FantasyTeam], amount: int,
    reason: str = "", actor=None, now=None, trade: PlayerTrade | None = None,
) -> list[BudgetGrant]:
    """Concede (o toglie) ``amount`` crediti a ogni squadra della lista.

    Un solo gesto, un solo ``batch``: «50 a tutti» sono dieci righe e una notizia.
    Togliere e' permesso — un errore si corregge, e una penalita' e' una cosa che
    esiste — ma mai sotto zero: un budget negativo non e' una punizione, e' un
    conto che non torna, e da li' in poi nessuna schermata direbbe piu' il vero.
    """
    amount = int(amount)
    if amount == 0:
        raise EconomyError("Indica quanti crediti dare (o togliere).")
    if not teams:
        raise EconomyError("Nessuna squadra a cui darli.")

    if amount < 0 and _is_classic(league):
        budgets = team_budgets(league)
        short = [t.name for t in teams
                 if (budgets[t.id].remaining if t.id in budgets else 0) + amount < 0]
        if short:
            raise EconomyError(
                f"Non si scende sotto zero: {', '.join(short)} non ha "
                f"{currency.amount(-amount)} da togliere.")

    now = now or timezone.now()
    batch = _batch()
    return BudgetGrant.objects.bulk_create([
        BudgetGrant(team=t, amount=amount, reason=reason[:200], batch=batch,
                    trade=trade, created_by=actor, created_at=now)
        for t in teams
    ])


def revoke_batch(league: FantasyLeague, batch: str) -> int:
    """Cancella una concessione: la riga sparisce, come se non fosse mai stata.

    Solo le concessioni dell'admin — la contropartita di uno scambio appartiene
    allo scambio, e toglierla da sola lascerebbe due rose scambiate e i crediti no.
    """
    grants = list(BudgetGrant.objects.filter(
        team__league=league, batch=batch, trade__isnull=True).select_related("team"))
    if not grants:
        raise EconomyError("Concessione non trovata.")

    if _is_classic(league):
        budgets = team_budgets(league)
        short = [g.team.name for g in grants
                 if (budgets[g.team_id].remaining if g.team_id in budgets else 0)
                 - g.amount < 0]
        if short:
            raise EconomyError(
                "Quei crediti sono gia' stati spesi: annullarla lascerebbe "
                f"{', '.join(short)} sotto zero.")

    n = len(grants)
    BudgetGrant.objects.filter(id__in=[g.id for g in grants]).delete()
    return n


# --------------------------------------------------------------------------- #
# Scambio
# --------------------------------------------------------------------------- #

@dataclass
class TradeCheck:
    ok: bool
    reason: str = ""
    # Chi prende il posto di chi nelle formazioni gia' consegnate. In classic
    # copre sempre tutti; in aura solo fin dove le due liste si accompagnano.
    pairs_a: list[tuple[int, int]] = field(default_factory=list)   # (esce da A, entra in A)
    pairs_b: list[tuple[int, int]] = field(default_factory=list)
    # Quanto resta alle due squadre a scambio fatto.
    remaining_a: int = 0
    remaining_b: int = 0
    # Il pareggio dei contratti, in crediti: positivo se li versa A, negativo se
    # li versa B. E' cio' che tiene fermi i due residui qui sopra.
    settlement: int = 0


def _slots(team: FantasyTeam, player_ids: list[int]) -> dict[int, FantasyRosterSlot]:
    """I contratti aperti di questa squadra per quei giocatori, col nome dentro:
    serve anche alla fotografia dello scambio, e dopo la chiusura del contratto
    resta solo quella a dire chi era."""
    return {
        s.player_id: s for s in FantasyRosterSlot.objects.filter(
            team=team, player_id__in=player_ids, released_at__isnull=True
        ).select_related("player")
    }


def _pair_by_role(a_ids: list[int], b_ids: list[int],
                  roles: dict[int, str]) -> list[tuple[int, int]]:
    """Accoppia i due elenchi ruolo per ruolo. Presuppone i due multiinsiemi
    uguali, cioe' il controllo fatto un attimo prima."""
    by_role: dict[str, list[int]] = {}
    for pid in b_ids:
        by_role.setdefault(roles[pid], []).append(pid)
    return [(pid, by_role[roles[pid]].pop(0)) for pid in a_ids]


def _pledged_in_market(league: FantasyLeague, player_ids: list[int]) -> list[str]:
    """Chi, fra questi, e' gia' promesso in svincolo da un'offerta di mercato viva.

    Un'offerta tiene impegnati i crediti del suo offerente contando su quel
    giocatore: portarlo via con uno scambio non romperebbe nulla subito — la
    validazione ricontrolla e rifiuterebbe — ma lascerebbe crediti bloccati su una
    trattativa che non puo' piu' concludersi, e nessuno saprebbe perche'."""
    from vfoot.models import MarketOffer

    rows = (MarketOffer.objects
            .filter(session__league=league, status__in=MarketOffer.LIVE_STATUSES,
                    release_player_id__in=player_ids)
            .select_related("release_player"))
    return [r.release_player.short_name or r.release_player.full_name for r in rows]


def check_trade(
    league: FantasyLeague, team_a: FantasyTeam, team_b: FantasyTeam,
    players_a: list[int], players_b: list[int],
    cash_amount: int = 0, cash_from: str = "a",
) -> TradeCheck:
    """Si puo' scrivere questo scambio? Ritorna anche gli accoppiamenti e i saldi."""
    if team_a.id == team_b.id:
        return TradeCheck(False, "Le due squadre coincidono.")
    if not players_a and not players_b:
        return TradeCheck(False, "Nessun giocatore da scambiare.")
    if len(set(players_a)) != len(players_a) or len(set(players_b)) != len(players_b):
        return TradeCheck(False, "Lo stesso giocatore compare due volte.")

    slots_a = _slots(team_a, players_a)
    slots_b = _slots(team_b, players_b)
    missing = ([pid for pid in players_a if pid not in slots_a]
               + [pid for pid in players_b if pid not in slots_b])
    if missing:
        return TradeCheck(False, "Un giocatore non e' nella rosa della sua squadra.")

    pledged = _pledged_in_market(league, players_a + players_b)
    if pledged:
        return TradeCheck(
            False,
            f"{', '.join(pledged)}: c'e' un'offerta di mercato aperta che lo da' in "
            "svincolo. Decidila (o annullala) prima di scambiarlo.")

    pairs_a: list[tuple[int, int]] = []
    pairs_b: list[tuple[int, int]] = []
    if _is_classic(league):
        roles = league_role_map(league, players_a + players_b)
        senza = [pid for pid in players_a + players_b if pid not in roles]
        if senza:
            return TradeCheck(
                False, "Un giocatore non ha un ruolo congelato nel listone di questa lega.")
        count_a: dict[str, int] = {}
        count_b: dict[str, int] = {}
        for pid in players_a:
            count_a[roles[pid]] = count_a.get(roles[pid], 0) + 1
        for pid in players_b:
            count_b[roles[pid]] = count_b.get(roles[pid], 0) + 1
        if count_a != count_b:
            return TradeCheck(
                False,
                "In classic si scambia a coppie di pari ruolo: "
                + _role_mismatch(count_a, count_b))
        pairs_a = _pair_by_role(players_a, players_b, roles)
        pairs_b = [(b, a) for a, b in pairs_a]
    else:
        # Senza ruoli non c'e' niente da far combaciare: si accompagnano finche'
        # ce n'e' per entrambi, e il resto lascia (o riempie) una casella.
        for out_pid, in_pid in zip(players_a, players_b):
            pairs_a.append((out_pid, in_pid))
            pairs_b.append((in_pid, out_pid))

    out_a = sum(s.purchase_price for s in slots_a.values())
    out_b = sum(s.purchase_price for s in slots_b.values())
    cash_amount = int(cash_amount)
    if cash_amount < 0:
        return TradeCheck(False, "La contropartita non puo' essere negativa: "
                                 "cambia il verso, non il segno.")
    cash_a = -cash_amount if cash_from == "a" else cash_amount
    cash_b = -cash_a

    # Quanto vale in piu' il pacchetto che parte da A: sono i crediti che A versa
    # a B perche' nessuno dei due residui si muova (v. l'intestazione del modulo).
    # In aura non ci sono crediti e non c'e' niente da pareggiare.
    settlement = (out_a - out_b) if _is_classic(league) else 0

    remaining_a = remaining_b = 0
    if _is_classic(league):
        budgets = team_budgets(league)
        # Niente `out_a - out_b`: quella differenza la cancella il pareggio, e
        # l'unica cosa che resta a muovere i residui e' la contropartita. Contarla
        # anche qui era il modo in cui uno scambio alla pari finiva per liberare
        # crediti spesi mesi prima.
        remaining_a = budgets[team_a.id].remaining + cash_a
        remaining_b = budgets[team_b.id].remaining + cash_b
        short = [t.name for t, r in ((team_a, remaining_a), (team_b, remaining_b)) if r < 0]
        if short:
            return TradeCheck(
                False,
                f"{', '.join(short)} non ha i crediti per questa contropartita.")
    elif cash_amount:
        return TradeCheck(
            False, "In modalita' aura non ci sono crediti da scambiare.")

    return TradeCheck(True, pairs_a=pairs_a, pairs_b=pairs_b,
                      remaining_a=remaining_a, remaining_b=remaining_b,
                      settlement=settlement)


def _role_mismatch(count_a: dict[str, int], count_b: dict[str, int]) -> str:
    """«dai 1 CEN e ne ricevi 1 ATT» — la differenza, detta in giocatori."""
    parts = []
    for role in sorted(set(count_a) | set(count_b)):
        a, b = count_a.get(role, 0), count_b.get(role, 0)
        if a != b:
            parts.append(f"di {role} ne dai {a} e ne ricevi {b}")
    return ", ".join(parts) or "le due liste non combaciano."


def _payload_side(slots: dict[int, FantasyRosterSlot],
                  roles: dict[int, str]) -> list[dict]:
    return [
        {"player_id": pid, "name": s.player.short_name or s.player.full_name,
         "price": s.purchase_price, "role": roles.get(pid)}
        for pid, s in slots.items()
    ]


def apply_trade(
    league: FantasyLeague, team_a: FantasyTeam, team_b: FantasyTeam,
    players_a: list[int], players_b: list[int],
    cash_amount: int = 0, cash_from: str = "a", note: str = "",
    actor=None, now=None,
) -> PlayerTrade:
    """Esegue lo scambio. Da chiamare dentro una transazione.

    Ordine voluto: prima i contratti, poi i crediti, poi le formazioni. Le prime
    due cose sono lo scambio; la terza e' la conseguenza, e deve vedere le rose
    gia' come sono diventate.
    """
    check = check_trade(league, team_a, team_b, players_a, players_b,
                        cash_amount, cash_from)
    if not check.ok:
        raise EconomyError(check.reason)

    now = now or timezone.now()
    slots_a = _slots(team_a, players_a)
    slots_b = _slots(team_b, players_b)
    roles = (league_role_map(league, players_a + players_b)
             if _is_classic(league) else {})

    trade = PlayerTrade.objects.create(
        league=league, team_a=team_a, team_b=team_b, note=note[:200],
        created_by=actor, created_at=now,
        payload={
            "a": _payload_side(slots_a, roles),
            "b": _payload_side(slots_b, roles),
            "cash": {"amount": int(cash_amount), "from": cash_from} if cash_amount else None,
            # Il pareggio: nessuno l'ha pattuito, ma senza scriverlo qui una
            # riga di crediti dello scambio resterebbe senza spiegazione.
            "settlement": ({"amount": abs(check.settlement),
                            "from": "a" if check.settlement > 0 else "b"}
                           if check.settlement else None),
            "team_a_name": team_a.name, "team_b_name": team_b.name,
        },
    )

    _move(slots_a, team_b, now, trade)
    _move(slots_b, team_a, now, trade)

    # PRIMA la differenza fra i contratti, poi quello che i due si sono detti: il
    # pareggio riporta i residui dov'erano, e la contropartita si controlla — e si
    # legge — su quelli. Righe di ``BudgetGrant`` legate allo scambio come la
    # contropartita, perche' il saldo di un allenatore resta una somma di righe e
    # non c'e' un secondo posto da cui leggere i suoi crediti.
    if check.settlement:
        n = abs(check.settlement)
        payer, payee = ((team_a, team_b) if check.settlement > 0 else (team_b, team_a))
        grant_credits(league, [payer], -n,
                      f"Pareggio contratti nello scambio con {payee.name}",
                      actor=actor, now=now, trade=trade)
        grant_credits(league, [payee], n,
                      f"Pareggio contratti nello scambio con {payer.name}",
                      actor=actor, now=now, trade=trade)

    if cash_amount:
        payer, payee = (team_a, team_b) if cash_from == "a" else (team_b, team_a)
        reason = f"Contropartita scambio con {payee.name}"
        grant_credits(league, [payer], -int(cash_amount), reason,
                      actor=actor, now=now, trade=trade)
        grant_credits(league, [payee], int(cash_amount),
                      f"Contropartita scambio con {payer.name}",
                      actor=actor, now=now, trade=trade)

    _repair_lineups(league, team_a, check.pairs_a, players_a, now)
    _repair_lineups(league, team_b, check.pairs_b, players_b, now)
    lineup_baseline.ensure_for(team_a, now)
    lineup_baseline.ensure_for(team_b, now)
    return trade


def _move(slots: dict[int, FantasyRosterSlot], to_team: FantasyTeam, now,
          trade: PlayerTrade) -> None:
    """Il contratto cambia squadra senza cambiare prezzo.

    Chiuso a incasso pieno (``sale_price = purchase_price``): la cessione non
    lascia nessun buco, perche' non c'e' stata nessuna perdita — quello che il
    giocatore costava se lo porta dietro. Due righe invece di un ``team`` riscritto
    perche' lo storico serve a ricostruire le rose a una data qualunque, e una riga
    spostata direbbe che quel giocatore e' sempre stato di chi lo ha adesso.
    """
    for pid, slot in slots.items():
        slot.released_at = now
        slot.sale_price = slot.purchase_price
        slot.from_trade = trade
        slot.save(update_fields=["released_at", "sale_price", "from_trade"])
        FantasyRosterSlot.objects.create(
            team=to_team, player_id=pid, purchase_price=slot.purchase_price,
            acquired_at=now, from_trade=trade)


def _repair_lineups(league, team, pairs, leaving: list[int], now) -> None:
    """R2 dalle due parti: chi entra prende il posto di chi esce, dove il posto
    c'era. Quello che resta scoperto (solo in aura, dove le liste possono essere
    di lunghezze diverse) svuota la casella, come una rimozione a mano."""
    paired_out = {out for out, _ in pairs}
    manager = getattr(getattr(team, "manager", None), "user", None)
    for out_pid, in_pid in pairs:
        touched = lineup_repair.swap_player(league, team.id, out_pid, in_pid, now)
        if touched and manager is not None:
            league_notifications.on_commit(
                league_notifications.notify_lineup_repaired,
                league, manager, out_pid, in_pid, touched, "trade")
    for out_pid in leaving:
        if out_pid not in paired_out:
            lineup_repair.swap_player(league, team.id, out_pid, None, now)
