"""Bench substitution at scoring time — the reason lineup ORDER is stored.

A submitted lineup carries an ORDERED bench. When a starter gets no vote (s.v. — he
didn't play / wasn't rated), a benched player takes his place. The two game modes
resolve that differently, and both consume the stored order (even when one of them
doesn't strictly need it):

  * CLASSIC: walk the bench in PRIORITY order (the order the manager set) and bring in
    the FIRST player who (a) has a vote and (b) keeps the XI legal under the classic
    role constraints. Bench order is decisive.
  * AURA: the substitute is simply the BEST available benched player (by a provided
    score); there are no role constraints. Order is stored but only breaks ties.

Both return the same shape so the scoring path is mode-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vfoot.services.formation_rules import is_legal_classic


@dataclass
class SubResult:
    effective: list[int]                 # the 11 player_ids that actually score
    subs: list[tuple[int, int]] = field(default_factory=list)   # (out, in)
    unresolved: list[int] = field(default_factory=list)         # s.v. starters with no sub


def apply_classic_substitutions(
    starters: list[int],
    bench: list[int],
    roles: dict[int, str],
    voted: set[int],
    max_subs: int | None = None,
) -> SubResult:
    """Classic: first benched player (in stored order) with a vote that keeps the
    formation legal replaces each s.v. starter. ``bench`` is the priority order.
    ``max_subs`` caps how many substitutions are made (None = unlimited); once the
    cap is hit, remaining s.v. starters stay unresolved."""
    effective = list(starters)
    cur_roles = [roles.get(p, "MID") for p in starters]
    used: set[int] = set()
    subs: list[tuple[int, int]] = []
    unresolved: list[int] = []

    for i, starter in enumerate(starters):
        if starter in voted:
            continue
        if max_subs is not None and len(subs) >= max_subs:
            unresolved.append(starter)
            continue
        chosen = None
        for b in bench:
            if b in used or b not in voted:
                continue
            trial = list(cur_roles)
            trial[i] = roles.get(b, "MID")
            if is_legal_classic(trial):
                chosen = b
                break
        if chosen is None:
            unresolved.append(starter)
            continue
        used.add(chosen)
        effective[i] = chosen
        cur_roles[i] = roles.get(chosen, "MID")
        subs.append((starter, chosen))

    return SubResult(effective=effective, subs=subs, unresolved=unresolved)


def apply_aura_substitutions(
    starters: list[int],
    bench: list[int],
    voted: set[int],
    score: dict[int, float] | None = None,
) -> SubResult:
    """Aura: replace each s.v. starter with the BEST available benched player (highest
    ``score``); no role constraints. Stored order is the tie-breaker only."""
    effective = list(starters)
    used: set[int] = set()
    subs: list[tuple[int, int]] = []
    unresolved: list[int] = []
    score = score or {}
    # candidates sorted best-first, stable on the stored bench order for ties
    order = {b: i for i, b in enumerate(bench)}

    for i, starter in enumerate(starters):
        if starter in voted:
            continue
        cands = [b for b in bench if b not in used and b in voted]
        if not cands:
            unresolved.append(starter)
            continue
        chosen = min(cands, key=lambda b: (-score.get(b, 0.0), order.get(b, 1_000_000)))
        used.add(chosen)
        effective[i] = chosen
        subs.append((starter, chosen))

    return SubResult(effective=effective, subs=subs, unresolved=unresolved)
