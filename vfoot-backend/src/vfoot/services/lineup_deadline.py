"""What a manager may still change, once part of his lineup is on the pitch.

Under the per-player deadline a lineup is not open or closed but BOTH at once: the
striker who kicked off at three is decided, the one who plays on Monday is not. So
the question the save endpoint has to answer is no longer "is this round open" —
it is "does this submission move anybody who is already playing".

The rule, and the reason for each half of it:

* **a locked player keeps his place** — goal, XI, bench or out of the lineup
  entirely. Moving him is deciding with the result in hand, which is the one thing
  the deadline exists to forbid. Note that OUT counts: adding a player whose match
  is under way is the same offence read backwards, and it is what a manager with no
  saved lineup at all would otherwise be able to do at the ninetieth minute.
* **a locked player keeps his SLOT** — his number in the XI and his number on the
  bench. Not merely his order relative to the other frozen ones: the slot, because
  both lists are read in order at scoring time. On the bench, how many players sit
  AHEAD of him decides whether he comes on; in the XI, ``max_substitutions`` is a
  budget spent walking the starters in order, so reshuffling them chooses which
  unplayed man is left uncovered when it runs out. Either way the reason for wanting
  to reshuffle is that his 4.5 is already on the screen.

So the free players are permuted among the FREE slots and the frozen ones never
move. Nobody is passing anybody: with the 3rd frozen, the 2nd and the 4th exchange
places and the 3rd is still the 3rd, with the same two players ahead of him as
before. Everything else — the players nobody has taken the pitch with yet — is
ordinary editing, and the formation rules judge the result as usual.
"""
from __future__ import annotations

BUCKET_GK = "portiere"
BUCKET_XI = "titolari"
BUCKET_BENCH = "panchina"
BUCKET_OUT = "fuori"


def _as_ids(values) -> list[int]:
    out: list[int] = []
    for v in values or []:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def placement(lineup: dict) -> dict[int, str]:
    """player_id -> which bucket he sits in. Absent players are simply not here.

    The goalkeeper is his own bucket rather than one of the eleven: in classic he is
    the one starter whose slot is not interchangeable, and "he was in goal and now
    he is a fielder" has to read as a move.
    """
    out: dict[int, str] = {}
    for pid in _as_ids(lineup.get("bench_player_ids")):
        out[pid] = BUCKET_BENCH
    for pid in _as_ids(lineup.get("starter_player_ids")):
        out[pid] = BUCKET_XI
    gk = lineup.get("gk_player_id")
    if gk not in (None, ""):
        try:
            out[int(gk)] = BUCKET_GK
        except (TypeError, ValueError):
            pass
    return out


# The two ordered lists a lineup is made of, and the word for a place in each.
# The goalkeeper is not here: he has a field of his own, so he has no number to keep.
SLOTTED = [("starter_player_ids", "fra i titolari"), ("bench_player_ids", "in panchina")]


def slots(lineup: dict, key: str, only: set[int]) -> dict[int, int]:
    """{index: player} within one ordered list, for the players we care about."""
    return {i: pid for i, pid in enumerate(_as_ids(lineup.get(key))) if pid in only}


def violations(old: dict | None, new: dict, locked_ids: set[int],
               names: dict[int, str] | None = None) -> list[str]:
    """Which locked players this submission moves. Empty list = the save is legal."""
    if not locked_ids:
        return []
    names = names or {}
    old = old or {}
    was, now = placement(old), placement(new)
    out: list[str] = []
    for pid in sorted(locked_ids):
        before, after = was.get(pid, BUCKET_OUT), now.get(pid, BUCKET_OUT)
        if before == after:
            continue
        who = names.get(pid, f"giocatore {pid}")
        if before == BUCKET_OUT:
            out.append(f"{who} non può entrare in formazione: la sua partita è iniziata.")
        elif after == BUCKET_OUT:
            out.append(f"{who} non può uscire dalla formazione: la sua partita è iniziata.")
        else:
            out.append(f"{who} non può passare da {before} a {after}: la sua partita è iniziata.")

    for key, where in SLOTTED:
        before_slots = slots(old, key, locked_ids)
        after_slots = slots(new, key, locked_ids)
        for i, pid in sorted(before_slots.items()):
            if after_slots.get(i) == pid:
                continue
            moved_to = next((j for j, x in after_slots.items() if x == pid), None)
            if moved_to is None:
                continue        # he left the list entirely: the bucket rule said so
            out.append(
                f"{names.get(pid, f'giocatore {pid}')} non può passare dal posto "
                f"{i + 1} al posto {moved_to + 1} {where}: la sua partita è iniziata."
            )
    return out
