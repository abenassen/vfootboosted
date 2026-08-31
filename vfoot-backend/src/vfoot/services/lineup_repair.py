"""Keeping saved lineups true when the roster changes under them.

The rule the league plays by: **the lineup you submitted is what counts**. It is
frozen at its matchday's lock and scored exactly as sent, whatever happens to the
roster afterwards — a player sold in January still scores for the team that fielded
him in December, which is what makes a postponed round score the same whether it is
concluded on time or six weeks late.

That rule only holds if a lineup is never left holding a player its manager no
longer has AT THE MOMENT OF THE LOCK. Three invariants do it, and this module is
the second:

* **R1 — a locked lineup is immutable.** WHEN it locks is the league's own
  deadline (``lineup_lock_mode``), and R1 answers "fino a quando si salva".
* **R2 — a settlement repairs the lineups of matchdays NOT YET BEGUN.** The
  market's same-role rule means every acquisition covers exactly the role the
  release empties, so the incoming player takes the outgoing one's PLACE — in the
  XI, in goal or on the bench, in the same position. The XI stays eleven, the
  module stays legal, and the manager is told.
* **R4 — schierabile e' chi era in rosa al primo calcio d'inizio del turno**
  (``services/frozen_roster``), che risponde a "chi puo' giocare" — un'altra
  domanda, e per questo un'altra regola.

R3 NON C'E' PIU'. Diceva «nessuna validazione mentre si gioca», ed era il modo di
tenere in piedi R2 dove R2 non poteva funzionare: a turno iniziato la
riparazione avrebbe messo in formazione un giocatore che quel turno non poteva
giocarlo, e allora si vietava alla rosa di cambiare. Il prezzo lo pagava
l'allenatore, che con un acquisto in attesa di validazione restava con i crediti
prenotati e senza poter offrire per nessun altro, per giorni. R4 dice la stessa
cosa in modo piu' preciso — non "la rosa non cambia", ma "la rosa di QUESTA
giornata non cambia" — e cosi' il mercato puo' andare avanti.

A manual roster removal by an admin has no incoming player to swap in, so there the
slot is simply vacated: honest, and recoverable because the lineup is not locked.
"""
from __future__ import annotations

import logging

from vfoot.models import SavedLineupSnapshot
from vfoot.services import matchday_state

log = logging.getLogger(__name__)


def _open_snapshots(league, team_id: int, now=None) -> list:
    """This team's saved lineups for matchdays that have NOT BEGUN (R2).

    NON PIU' «non ancora chiusa», MA «non ancora cominciata». Sono due confini
    diversi e in mezzo ci stava il danno: una giornata gia' in campo puo' essere
    ancora modificabile (modalita' ``player`` sempre, ``own`` fino al primo
    giocatore della squadra), e li' la riparazione infilava nella formazione un
    giocatore che quella giornata non poteva giocarla — a volte con il voto gia'
    noto, perche' ``swap_player`` guarda se l'USCENTE ha gia' giocato e mai se
    l'entrante l'ha fatto.

    Ora non c'e' piu' niente da riparare li' dentro: la rosa di una giornata e'
    quella del suo primo calcio d'inizio (``frozen_roster``), quindi in un turno
    cominciato il ceduto resta schierabile e l'acquistato non lo e'. La
    formazione e' gia' giusta com'e', e la sostituzione arriva dal turno dopo.
    """
    csid = league.reference_season_id
    started = (matchday_state.locked_matchdays(csid, now)
               if csid is not None and league.enforce_lineup_deadline else set())
    out = []
    for snap in SavedLineupSnapshot.objects.filter(
        league_id=str(league.id), lineup_id__startswith=f"team{team_id}"
    ):
        # lineup_id is "team<id>" or "team<id>:comp<id>": startswith would also match
        # team12 when looking for team1, so confirm the boundary.
        rest = snap.lineup_id[len(f"team{team_id}"):]
        if rest and not rest.startswith(":"):
            continue
        try:
            md = int(snap.matchday_id)
        except (TypeError, ValueError):
            continue
        # Un confine solo per tutta la lega, e letto in una query sola per tutta
        # la stagione: prima serviva ``is_closed_for``, che deve sapere la
        # modalita' di scadenza e, in modalita' ``own``, interrogare la squadra
        # snapshot per snapshot. La riparazione ha smesso di dipendere dalla
        # modalita', ed e' il groviglio che la rendeva difficile da ragionare.
        if md not in started:
            out.append(snap)
    return out


def swap_player(league, team_id: int, out_pid: int, in_pid: int | None, now=None) -> list[int]:
    """Replace ``out_pid`` with ``in_pid`` (or remove him) in every open lineup.

    Returns the real matchdays actually touched — what the manager is told about.
    Position is preserved: the incoming player inherits the exact slot, so a manager
    who had him in goal still has a goalkeeper and the bench order is untouched.
    """
    touched: list[int] = []
    out_s, in_s = str(out_pid), (str(in_pid) if in_pid is not None else None)

    # QUI C'ERA un guardiano sul singolo giocatore: sotto la scadenza per giocatore
    # una giornata aperta poteva contenere qualcuno gia' in campo, e la
    # riparazione non doveva sfilarlo da una formazione che si stava scorando.
    # Ora e' irraggiungibile — ``_open_snapshots`` rende solo turni non ancora
    # cominciati, e in un turno non cominciato nessuno ha ancora giocato — e
    # copriva comunque meta' del problema: guardava l'uscente e mai l'entrante.
    for snap in _open_snapshots(league, team_id, now):
        changed = False

        if snap.gk_player_id is not None and str(snap.gk_player_id) == out_s:
            snap.gk_player_id = in_s
            changed = True

        for field in ("starter_player_ids", "bench_player_ids"):
            ids = [str(x) for x in (getattr(snap, field) or [])]
            if out_s not in ids:
                continue
            if in_s is None:
                new = [x for x in ids if x != out_s]
            else:
                new = [in_s if x == out_s else x for x in ids]
            setattr(snap, field, new)
            changed = True

        # Stored but never read by the classic engine; still, leaving a ghost id in
        # a field the UI does render would be sloppy.
        backups = snap.starter_backups or []
        if backups:
            repaired = []
            for row in backups:
                if not isinstance(row, dict):
                    repaired.append(row)
                    continue
                starter = str(row.get("starter_player_id", ""))
                pool = [str(x) for x in (row.get("backup_player_ids") or [])]
                if starter == out_s:
                    if in_s is None:
                        changed = True
                        continue
                    row = {**row, "starter_player_id": in_s}
                    changed = True
                if out_s in pool:
                    row = {**row, "backup_player_ids": (
                        [x for x in pool if x != out_s] if in_s is None
                        else [in_s if x == out_s else x for x in pool])}
                    changed = True
                repaired.append(row)
            snap.starter_backups = repaired

        if changed:
            snap.save(update_fields=["gk_player_id", "starter_player_ids",
                                     "bench_player_ids", "starter_backups"])
            try:
                touched.append(int(snap.matchday_id))
            except (TypeError, ValueError):
                pass

    if touched:
        log.info("Formazioni riparate: lega=%s squadra=%s %s->%s giornate=%s",
                 league.id, team_id, out_pid, in_pid, sorted(set(touched)))
    return sorted(set(touched))
