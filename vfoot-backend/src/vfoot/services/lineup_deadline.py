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


# The bench is the only list whose order is the MANAGER's. The XI's is derived —
# see ``normalise_xi`` — so there is nothing there to defend and nothing to forge.
# The goalkeeper is in neither: he has a field of his own, so he has no number.
SLOTTED = [("bench_player_ids", "in panchina")]

# P-D-C-A, the order the formation is read in everywhere else.
_ROLE_ORDER = ["DEF", "MID", "ATT"]


def normalise_xi(outfield_ids: list[int], roles: dict[int, str],
                 previous_ids: list[int] | None = None,
                 locked_ids: set[int] | None = None) -> list[int]:
    """The XI in P-D-C-A order, each frozen player kept at his place INSIDE his role.

    Why the XI is normalised rather than policed. Its order is read at scoring time
    (``apply_classic_substitutions`` walks the starters, spending the substitution
    budget and testing legality as it goes) but it is not something a manager ever
    chose: the page groups the XI by role and offers no way to reorder it, so what
    got stored was an accident of the clicks — a promoted substitute landed at the
    end of the list while appearing among his own on screen. Deriving it makes the
    order match what is on the page, and makes a forged one impossible by
    construction instead of by validation.

    The freeze still bites, one role at a time: a player whose match has started
    keeps his number WITHIN his own block, so the free ones are sorted around him.
    His absolute position can still move when the module does — dropping a defender
    lifts every midfielder by one — and that is the price of an XI that always reads
    P-D-C-A. It costs a real change of formation, which is not a way of re-deciding
    anything with the results in hand.
    """
    locked_ids = locked_ids or set()
    prev_slot: dict[int, int] = {}
    seen: dict[str, int] = {}
    # The stored lists hold whatever was posted — the seeds write strings, the page
    # numbers — so the previous order is coerced rather than compared as it lies.
    for pid in _as_ids(previous_ids):
        role = roles.get(pid, "MID")
        i = seen.get(role, 0)
        seen[role] = i + 1
        if pid in locked_ids:
            prev_slot[pid] = i

    out: list[int] = []
    for role in _ROLE_ORDER:
        block = [pid for pid in outfield_ids if roles.get(pid, "MID") == role]
        if not block:
            continue
        placed: list[int | None] = [None] * len(block)
        for pid in sorted((p for p in block if p in prev_slot), key=lambda p: prev_slot[p]):
            # His old number, or the nearest one still free below it: a block that
            # has shrunk under him has no place left to give.
            i = min(prev_slot[pid], len(block) - 1)
            while i >= 0 and placed[i] is not None:
                i -= 1
            if i < 0:
                i = placed.index(None)
            placed[i] = pid
        free = iter(pid for pid in block if pid not in prev_slot)
        out.extend(pid if pid is not None else next(free) for pid in placed)

    # Anything whose role we could not name keeps the tail rather than vanishing.
    out.extend(pid for pid in outfield_ids if pid not in out)
    return out


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
