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
    frozen: set[int] | None = None,
    def_locked: bool = False,
) -> SubResult:
    """Classic: first benched player (in stored order) with a vote that keeps the
    formation legal replaces each s.v. starter. ``bench`` is the priority order.
    ``max_subs`` caps how many substitutions are made (None = unlimited); once the
    cap is hit, remaining s.v. starters stay unresolved.

    ``frozen`` are starters that must NOT be substituted even though they have no
    vote: their real match has not been played yet (a postponement). A bench player
    is the answer to "he didn't play", not to "his match hasn't happened" — using
    one there would burn a substitution over a game that is still to come. They stay
    in the XI contributing nothing, and are not reported as unresolved s.v. either:
    they are a different thing and the league decides them separately (wait for the
    recovery, or impose an office vote).

    ``def_locked`` — LE SOSTITUZIONI NON CAMBIANO QUANTI DIFENSORI GIOCANO. Acceso
    per una formazione che e' stata MODIFICATA a giornata gia' cominciata, in una
    lega col modificatore difesa. Un difensore lo rimpiazza un difensore, e uno
    slot che difensore non e' non lo puo' occupare un difensore.

    Serve nei due versi, e il secondo e' meno ovvio del primo. Il modificatore vale
    la media dei TRE voti piu' alti fra i difensori dell'XI EFFETTIVO piu' quello
    del portiere (v. ``compute_defense_bonus``: ``voted[:3]``), sotto entrambi i
    gate. Quindi:

    * vietare solo DIF <- non-DIF chiuderebbe la fuga (schierare quattro difensori,
      vederne due prendere 5 e far entrare un attaccante al posto del terzo);
    * ma lascerebbe aperto il RIPARO: basta un centrocampista s.v. per far entrare
      un quarto difensore dalla panchina, e i tre migliori buttano fuori i due voti
      brutti. La media puo' solo migliorare, ed e' un cricchetto azionabile a voti
      visti.

    Centrocampista e attaccante restano liberi di scambiarsi: il modificatore non
    li guarda, e vietare anche loro sarebbe una regola senza il suo motivo.
    """
    effective = list(starters)
    cur_roles = [roles.get(p, "MID") for p in starters]
    used: set[int] = set()
    subs: list[tuple[int, int]] = []
    unresolved: list[int] = []
    frozen = frozen or set()

    for i, starter in enumerate(starters):
        if starter in voted or starter in frozen:
            continue
        if max_subs is not None and len(subs) >= max_subs:
            unresolved.append(starter)
            continue
        chosen = None
        starter_is_def = roles.get(starter, "MID") == "DEF"
        for b in bench:
            if b in used or b not in voted:
                continue
            if def_locked and (roles.get(b, "MID") == "DEF") != starter_is_def:
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
