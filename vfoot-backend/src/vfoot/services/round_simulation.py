"""«Con tutti a 6»: chi delle partite ancora da giocare entra nella simulazione.

La terza lettura di un turno in corso (v. ``classic_matchday_scoring.live_scorer``)
da' un 6 d'ufficio a chi deve ancora giocare, per rispondere a una domanda sola:
con delle semplici sufficienze, la sfida si vince o si perde? Non e' una
previsione — non pesa chi giochera' davvero — ma non deve nemmeno dare un 6 a chi
sappiamo che non ci sara': quello e' un senza voto, e la panchina lo copre come lo
coprira' a fine giornata.

Le esclusioni sono solo CERTEZZE, e vengono da tre fonti gia' usate dalle probabili
formazioni:

* la squalifica, dai cartellini (``lineup_forecast.suspensions_for``);
* l'assente dichiarato — infortunio, squalifica, nazionale, fuori squadra — dai
  ``missingPlayers`` di SofaScore o scritto a mano (``LineupEvidence`` con
  ``availability=out``); un «in dubbio» NON esclude;
* la distinta ufficiale, quando e' uscita (circa un'ora prima del calcio d'inizio):
  chi non c'e' non e' convocato.

Ognuna sbaglia, quando sbaglia, nella direzione innocua: un indisponibile che ci
sfugge prende il suo 6, che e' esattamente quello che farebbe la versione senza
esclusioni.
"""
from __future__ import annotations

from collections import defaultdict

from realdata.models import (
    LineupEvidence, LineupForecast, LineupForecastEntry, PlayerTeamStint,
)
from realdata.services.lineup_forecast import (
    _evidence_for, _played_before, suspensions_for,
)
from vfoot.services.match_resolver import matchday_fixtures_by_team

# Il voto della simulazione. Non e' il voto d'ufficio della lega (che puo' essere
# un 5): e' la sufficienza, che e' la domanda.
SIMULATED_VOTE = 6.0

# Sotto questo numero di giocatori agganciati una distinta ufficiale non si usa per
# escludere: undici titolari e almeno sette in panchina. Un giocatore che non
# siamo riusciti ad agganciare risulterebbe «non convocato», e lasciarlo dentro
# col suo 6 e' l'errore piccolo dei due.
MIN_OFFICIAL_SQUAD = 18


def unavailable_for_simulation(cs_id: int, real_matchday: int, player_ids) -> dict[int, str]:
    """{player_id: perche' non c'e'} fra ``player_ids``, giocatori di partite di
    questa giornata non ancora cominciate."""
    player_ids = set(player_ids)
    if not player_ids:
        return {}
    fixtures = matchday_fixtures_by_team(cs_id, real_matchday)
    team_of = dict(PlayerTeamStint.objects.filter(
        player_id__in=player_ids, team_season__competition_season_id=cs_id,
        end_date__isnull=True).values_list("player_id", "team_season_id"))
    match_of = {pid: fixtures[ts] for pid, ts in team_of.items() if ts in fixtures}
    if not match_of:
        return {}
    out: dict[int, str] = {}

    # 1. La distinta ufficiale, che quando c'e' sa tutto.
    matches = {m.id: m for m in match_of.values()}
    official = LineupForecast.objects.filter(
        match_id__in=list(matches), source=LineupForecast.SOURCE_SOFASCORE, official=True)
    squad: dict[int, set] = defaultdict(set)
    for ts, pid in (LineupForecastEntry.objects.filter(forecast__in=official)
                    .values_list("team_season_id", "player_id")):
        squad[ts].add(pid)
    for pid, ts in team_of.items():
        if len(squad.get(ts, ())) >= MIN_OFFICIAL_SQUAD and pid not in squad[ts]:
            out[pid] = "non convocato"

    # 2. Gli assenti dichiarati.
    for pid, rows in _evidence_for(cs_id, real_matchday, list(match_of)).items():
        hard = [e for e in rows if e.availability == LineupEvidence.AVAIL_OUT]
        if hard and pid not in out:
            out[pid] = hard[0].note or hard[0].get_kind_display().lower()

    # 3. Le squalifiche, contate fino al calcio d'inizio di CIASCUNA partita: una
    # sola lettura delle partite giocate, filtrata per istante, invece di una per
    # partita.
    kickoffs = {m.kickoff for m in matches.values() if m.kickoff is not None}
    if kickoffs:
        played = _played_before(cs_id, max(kickoffs))
        for k in kickoffs:
            banned = suspensions_for(cs_id, k, played=[m for m in played if m["kickoff"] < k])
            for pid, reason in banned.items():
                m = match_of.get(pid)
                if m is not None and m.kickoff == k and pid not in out:
                    out[pid] = reason
    return out
