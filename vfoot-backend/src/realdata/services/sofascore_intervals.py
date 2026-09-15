"""Gli intervalli in campo di una partita SofaScore, ricostruiti dagli incidents.

``PlayerOnPitchInterval`` e' la risposta canonica a «era in campo al minuto X»,
e fino al 15/09/2026 per la stagione in corso non lo scriveva nessuno: il comando
``import_sofascore_intervals`` lo faceva a mano, dalla cache, e in produzione la
2026-27 ne aveva ZERO — il termine di esposizione difensiva ripiegava sulla stima
«titolare dal 1', subentrato fino al 90'» per tutta la stagione. Adesso li scrive
l'importatore a ogni giro, dagli stessi incidents che ha gia' in mano per i
cartellini; il comando resta per i riempimenti a posteriori e usa questo stesso
codice, cosi' i due non possono divergere.

LA COPPIA. Gli intervalli dicevano il minuto del cambio ma non CHI e' entrato per
chi: con tre sostituzioni allo stesso minuto (il caso normale al 60')
l'accoppiamento per (lato, minuto) e' ambiguo, e gli incidents invece la coppia la
portano esatta. Si salva nel ``payload`` dell'intervallo, sotto due chiavi perche'
un subentrato puo' uscire a sua volta: ``entry`` e' il cambio che l'ha fatto
entrare, ``exit`` quello che l'ha fatto uscire, ciascuno ``{in, out, minute}``.
E' quella che il tabellino della partita vera legge per scrivere «esce · entra X»
come fa quello di lega.

PARTITA IN CORSO. Chi e' ancora in campo non ha una fine: l'intervallo arriva al
90 con ``unknown_end``, non con un fischio finale che non c'e' stato. I consumatori
leggono i minuti (``on_pitch_windows``) e per loro e' lo stesso; la ragione resta
onesta per chi la legge.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from django.db import transaction

from realdata.models import (
    INTERVAL_FINAL_WHISTLE, INTERVAL_RED_CARD, INTERVAL_STARTING_XI,
    INTERVAL_SUBSTITUTION_OFF, INTERVAL_SUBSTITUTION_ON, INTERVAL_UNKNOWN_END,
    Match, MatchAppearance, PROVIDER_SOFASCORE, PlayerOnPitchInterval, SIDE_HOME,
)

FULL_TIME = 90

_RED_CLASSES = ("red", "redyellow", "yellowred")


def appearances_of(match: Match) -> dict[int, dict]:
    """{player_id: {side, is_starter, minutes_played}} — la distinta come la
    conosciamo, che e' l'unico posto da cui si parte (chi non c'e' qui non ha
    intervalli, qualunque cosa dicano gli incidents)."""
    return {a["player_id"]: a for a in MatchAppearance.objects
            .filter(match=match).values("player_id", "side", "is_starter",
                                        "minutes_played")}


def build_intervals(match: Match, incidents_rows: Iterable[Mapping[str, Any]],
                    appearances: Mapping[int, Mapping[str, Any]],
                    ext_to_local: Mapping[str, int], *,
                    finished: bool = True) -> tuple[list[PlayerOnPitchInterval], int]:
    """Le righe da scrivere per QUESTA partita, e quante ne sono state scartate
    per incoerenza del fornitore (una fine prima dell'inizio: non ci si fida).

    ``ext_to_local`` traduce l'id SofaScore (stringa) nel nostro ``Player.id``; un
    id che non traduce si ignora, come fa il comando da sempre.
    """
    start = {pid: (0, INTERVAL_STARTING_XI)
             for pid, a in appearances.items() if a["is_starter"]}
    end: dict[int, tuple[int, str]] = {}
    entry: dict[int, dict] = {}   # pid -> il cambio che l'ha fatto entrare
    exit_: dict[int, dict] = {}   # pid -> il cambio che l'ha fatto uscire
    for inc in sorted(incidents_rows, key=lambda r: (r.get("time") or 0)):
        kind = inc.get("incidentType")
        minute = inc.get("time")
        if minute is None:
            continue
        if kind == "substitution":
            pin = ext_to_local.get(str((inc.get("playerIn") or {}).get("id")))
            pout = ext_to_local.get(str((inc.get("playerOut") or {}).get("id")))
            if pin is not None and pin == pout:
                # «X entra per X»: capita nei dati (Piotrowski all'85', 26-27
                # simulata). Non dice niente di leggibile, e presa alla lettera
                # cancellava il suo intervallo da titolare per lasciargli un
                # 85'-85'. Si ignora: resta quello che si sapeva prima.
                continue
            if pin is not None:
                start[pin] = (int(minute), INTERVAL_SUBSTITUTION_ON)
            if pout is not None:
                end[pout] = (int(minute), INTERVAL_SUBSTITUTION_OFF)
            if pin is not None and pout is not None:
                pair = {"in": pin, "out": pout, "minute": int(minute)}
                entry[pin] = pair
                exit_[pout] = pair
        elif kind == "card" and str(inc.get("incidentClass", "")).lower() in _RED_CLASSES:
            pid = ext_to_local.get(str((inc.get("player") or {}).get("id")))
            if pid is not None:
                end[pid] = (int(minute), INTERVAL_RED_CARD)

    open_end = (FULL_TIME, INTERVAL_FINAL_WHISTLE if finished else INTERVAL_UNKNOWN_END)
    rows: list[PlayerOnPitchInterval] = []
    skipped = 0
    for pid, (s_min, s_reason) in start.items():
        a = appearances.get(pid)
        if a is None:
            continue
        e_min, e_reason = end.get(pid, open_end)
        if e_min < s_min:
            skipped += 1
            continue
        ts = match.home_team if a["side"] == SIDE_HOME else match.away_team
        payload = {}
        if pid in entry:
            payload["entry"] = entry[pid]
        if pid in exit_:
            payload["exit"] = exit_[pid]
        rows.append(PlayerOnPitchInterval(
            match=match, player_id=pid, team_season=ts, team_side=a["side"],
            start_minute=s_min, start_elapsed_seconds=s_min * 60,
            end_minute=e_min, end_elapsed_seconds=e_min * 60,
            start_reason=s_reason, end_reason=e_reason,
            provider=PROVIDER_SOFASCORE, payload=payload))
    return rows, skipped


@transaction.atomic
def replace_intervals(match: Match, rows: list[PlayerOnPitchInterval]) -> None:
    """Idempotente per partita: butta gli intervalli SofaScore di questa e riscrive."""
    PlayerOnPitchInterval.objects.filter(match=match, provider=PROVIDER_SOFASCORE).delete()
    PlayerOnPitchInterval.objects.bulk_create(rows, batch_size=500)


def substitution_pairs(match_id: int) -> list[dict]:
    """Le sostituzioni di una partita come coppie ``{side, minute, out, in}``,
    lette dagli intervalli.

    Prima la coppia SALVATA (``payload.entry`` / ``payload.exit``), che e' esatta.
    Per gli intervalli scritti prima che si salvasse — quelli della 2025-26 in
    produzione, finche' non si rilancia il comando — si accoppia per (lato,
    minuto) e SOLO quando a quel minuto c'e' un'uscita e un'entrata: con due o tre
    cambi insieme l'accoppiamento sarebbe un'invenzione due volte su tre, e un nome
    sbagliato e' peggio di nessun nome.
    """
    ivs = list(PlayerOnPitchInterval.objects
               .filter(match_id=match_id)
               .values("player_id", "team_side", "start_minute", "start_reason",
                       "end_minute", "end_reason", "payload"))
    pairs: dict[tuple[int, int], dict] = {}
    lone_on: dict[tuple[str, int], list[int]] = {}
    lone_off: dict[tuple[str, int], list[int]] = {}
    for iv in ivs:
        payload = iv.get("payload") or {}
        for key in ("entry", "exit"):
            pair = payload.get(key)
            if pair and "in" in pair and "out" in pair and pair["in"] != pair["out"]:
                pairs[(pair["out"], pair["in"])] = {
                    "side": iv["team_side"], "minute": pair.get("minute"),
                    "out": pair["out"], "in": pair["in"]}
        if iv["start_reason"] == INTERVAL_SUBSTITUTION_ON and not payload.get("entry"):
            lone_on.setdefault((iv["team_side"], iv["start_minute"]), []).append(iv["player_id"])
        if iv["end_reason"] == INTERVAL_SUBSTITUTION_OFF and not payload.get("exit"):
            lone_off.setdefault((iv["team_side"], iv["end_minute"]), []).append(iv["player_id"])
    for key, ons in lone_on.items():
        offs = lone_off.get(key, [])
        if len(ons) == 1 and len(offs) == 1 and ons[0] != offs[0]:
            side, minute = key
            pairs.setdefault((offs[0], ons[0]), {"side": side, "minute": minute,
                                                 "out": offs[0], "in": ons[0]})
    return sorted(pairs.values(), key=lambda p: (p["side"], p["minute"] or 0, p["out"]))
