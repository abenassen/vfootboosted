"""Classic-mode fantavoto scoring — the shared production engine.

Composes a fantasy team's fantatotale from per-player fantavoto "lines" (voto puro
+ bonus/malus, one per player, each taken from the real match that player played),
applying, in order:

  1. bench substitutions for senza-voto (s.v.) starters, up to ``max_substitutions``,
     walking the bench in the manager's priority order and keeping the XI legal
     (``apply_classic_substitutions``);
  2. the effective-XI sum — an s.v. starter that CANNOT be substituted contributes
     NOTHING (excluded from the sum: not a 0, not a 6 — he is a player who got no
     vote);
  3. a set of league MODIFIERS resolved through a small registry (extensible): today
     the defence modifier and the optional keeper-clean-sheet (+1) bonus;
  4. conversion of the final total to match-goals via the 66/+6 ladder
     (``fantavote_to_goals``).

The same engine is meant to back BOTH the live matchday conclusion and the demo
seed, so a league played forward reproduces exactly what the seed materialises.

Input contract — each "line" is a dict with at least:
    player_id:int, name:str, lineup_role:str (GK/DEF/MID/ATT),
    sv:bool, voto_puro:float|None, fantavoto:float|None
and, for the goalkeeper, ``conceded:int`` (goals conceded while on the pitch) so the
keeper-clean-sheet modifier can tell an imbattuto keeper. Both ``classic_pagella._line``
and the seed's ``_line`` already produce this shape (``conceded`` is added when wiring).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from vfoot.services.defense_bonus import GATE_STARTERS, compute_defense_bonus
from vfoot.services.lineup_substitution import apply_classic_substitutions
from vfoot.services.scoring_engine import fantavote_to_goals

# Bump when the FIXED rules change (bonus/malus schema in classic_pagella, or the
# 66/+6 goal thresholds). Stored in the per-matchday snapshot so an old result stays
# interpretable even after the fixed rules evolve.
RULES_VERSION = 1


# --------------------------------------------------------------------------- #
# Ruleset — the per-league knobs that affect the calculation.                 #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Ruleset:
    max_substitutions: int | None = 5
    defense_enabled: bool = True
    defense_mode: str = "add_own"  # add_own | subtract_opponent
    # Which lineup the >=4-defenders gate counts: "starters" (the XI as sent) or
    # "effective" (the XI as it ended, defenders with a vote). See defense_bonus.
    defense_gate: str = GATE_STARTERS
    # Voto d'ufficio per un titolare senza voto che la panchina non ha coperto.
    # 0 = spento (il buco non vale niente, la regola classica).
    sv_office_vote: float = 0.0
    keeper_clean_sheet_enabled: bool = False
    keeper_clean_sheet_value: float = 1.0
    # Fattore campo: quanto vale giocare in casa. 0 = spento. SE valga, in una data
    # partita, non lo decide la lega ma il calendario — v. FantasyFixture.home_advantage.
    home_advantage_bonus: float = 0.0

    @classmethod
    def from_league(cls, league) -> "Ruleset":
        return cls(
            max_substitutions=league.max_substitutions,
            defense_enabled=league.defense_bonus_enabled,
            defense_mode=league.defense_bonus_mode,
            defense_gate=getattr(league, "defense_bonus_gate", None) or GATE_STARTERS,
            sv_office_vote=float(getattr(league, "sv_office_vote", 0.0) or 0.0),
            # Field added during wiring; getattr keeps the engine usable before then.
            keeper_clean_sheet_enabled=bool(getattr(league, "keeper_clean_sheet_enabled", False)),
            keeper_clean_sheet_value=float(getattr(league, "keeper_clean_sheet_value", 1.0)),
            home_advantage_bonus=float(getattr(league, "home_advantage_bonus", 0.0) or 0.0),
        )

    def to_snapshot(self) -> dict:
        """The frozen ruleset stored on the matchday at conclusion (for audit + the
        manual recompute). Keep every knob that can change a score."""
        return {
            "rules_version": RULES_VERSION,
            "max_substitutions": self.max_substitutions,
            "defense_enabled": self.defense_enabled,
            "defense_mode": self.defense_mode,
            "defense_gate": self.defense_gate,
            "sv_office_vote": self.sv_office_vote,
            "keeper_clean_sheet_enabled": self.keeper_clean_sheet_enabled,
            "keeper_clean_sheet_value": self.keeper_clean_sheet_value,
            "home_advantage_bonus": self.home_advantage_bonus,
        }

    @classmethod
    def from_snapshot(cls, snap: dict) -> "Ruleset":
        return cls(
            max_substitutions=snap.get("max_substitutions", 5),
            defense_enabled=snap.get("defense_enabled", True),
            defense_mode=snap.get("defense_mode", "add_own"),
            # A matchday concluded before the gate existed was scored on the XI as
            # sent, so that is what an old snapshot has to keep meaning.
            defense_gate=snap.get("defense_gate") or GATE_STARTERS,
            sv_office_vote=snap.get("sv_office_vote", 0.0) or 0.0,
            keeper_clean_sheet_enabled=snap.get("keeper_clean_sheet_enabled", False),
            keeper_clean_sheet_value=snap.get("keeper_clean_sheet_value", 1.0),
            home_advantage_bonus=snap.get("home_advantage_bonus", 0.0),
        )


# --------------------------------------------------------------------------- #
# Modifier registry — the extension point.                                    #
# A modifier reads the team context + ruleset and yields a magnitude and a     #
# scope; new modifiers are added by appending one function to MODIFIERS.        #
# --------------------------------------------------------------------------- #
SELF_ADD = "self_add"          # add the value to the team's OWN total
OPP_SUBTRACT = "opp_subtract"  # subtract the value from the OPPONENT's total


@dataclass
class ModifierResult:
    key: str
    eligible: bool
    value: float           # magnitude (>= 0); only applied when eligible
    scope: str             # SELF_ADD | OPP_SUBTRACT
    detail: dict = field(default_factory=dict)


def _mod_defense(ctx: dict, rs: Ruleset) -> ModifierResult | None:
    if not rs.defense_enabled:
        return None
    d = compute_defense_bonus(ctx["starter_lineup_roles"], ctx["def_votes"], ctx["gk_vote"],
                              rs.defense_gate)
    scope = OPP_SUBTRACT if rs.defense_mode == "subtract_opponent" else SELF_ADD
    return ModifierResult(
        key="defense", eligible=bool(d["eligible"]), value=float(d["bonus"]),
        scope=scope, detail=d,
    )


def _mod_keeper_clean_sheet(ctx: dict, rs: Ruleset) -> ModifierResult | None:
    if not rs.keeper_clean_sheet_enabled:
        return None
    gk = ctx["gk_line"]
    # Imbattuto = the effective keeper played (has a vote) and conceded no goals.
    # An OFFICE vote is explicitly not enough: it is a ruling on the vote, not a
    # match that was played, and there is no clean sheet to be had in a game nobody
    # played — reading its conceded=0 as one would be inventing an event. The
    # league's ``sv_office_vote`` rides the same ``office`` flag and is refused by
    # the same line: it is that same statement made about a keeper who is not there
    # at all.
    imbattuto = bool(gk and not gk.get("sv") and not gk.get("office")
                     and (gk.get("conceded") or 0) == 0)
    return ModifierResult(
        key="keeper_clean_sheet", eligible=imbattuto,
        value=rs.keeper_clean_sheet_value if imbattuto else 0.0,
        scope=SELF_ADD, detail={"conceded": (gk or {}).get("conceded")},
    )


# Order is irrelevant: each modifier's magnitude is computed independently and
# summed in resolve_fixture. Append here to add a future modifier.
MODIFIERS = [_mod_defense, _mod_keeper_clean_sheet]


def _fill_unresolved(s_by: dict, unresolved: list[int], vote: float) -> list[int]:
    """Give the league's voto d'ufficio to the starters left without one, in place.

    A hole is a starter with no vote whom the bench could not cover — for whatever
    reason: nobody eligible, or the substitution budget spent. It costs the team his
    whole fantavoto, which on a keeper (the one starter a bench rarely covers,
    because only another keeper will do) is the difference between a bad weekend and
    a lost one. A league may decide that a hole is worth 3 or 4 rather than nothing.

    Two slots are deliberately left empty even so:

    * a line whose match is still MOVING (``provisional``). Mid-round every player
      on the pitch is momentarily voteless, and filling those would show a team
      "leading" on eleven office votes at the fifth minute, then sliding as the
      real ones arrive. A hole is only a hole once the match that made it is over.
    * a VACANT slot — a player the team no longer has, in a lineup the manager never
      submitted for this round (see ``build_team_lines``). That is not a hole in a
      team that was fielded; it is the absence of one, and paying for it would pay a
      manager for not turning up.

    Returns the player_ids actually filled (empty when the league has it off).
    """
    if not vote:
        return []
    filled: list[int] = []
    for pid in unresolved:
        line = s_by.get(pid)
        if line is None or line.get("provisional") or line.get("vacant"):
            continue
        # ``office``: the SAME channel an admin ruling travels on (_office_line),
        # so everything downstream — no bonus/malus, no clean sheet, the "ufficio"
        # chip in the tabellino — already knows what this line is. ``sv_filled``
        # only records WHO imposed it: the league's standing rule, not a ruling on
        # a particular match.
        line.update(sv=False, office=True, sv_filled=True, voto_puro=float(vote),
                    bonus=0.0, malus=0.0, fantavoto=float(vote))
        filled.append(pid)
    return filled


# --------------------------------------------------------------------------- #
# Per-team scoring.                                                            #
# --------------------------------------------------------------------------- #
def score_team(starters: list[dict], bench: list[dict], rs: Ruleset,
               def_locked: bool = False) -> dict:
    """Score one fantasy team for one matchday.

    ``starters``/``bench`` are ordered lists of line dicts (bench in the manager's
    priority order). Mutates the line dicts (sets entered/replaced_by) like the seed
    does, so pass fresh copies. Returns a per-team dict; cross-team modifier
    application (e.g. subtract-from-opponent) happens later in ``resolve_fixture``.
    """
    roles = {l["player_id"]: l["lineup_role"] for l in starters + bench}
    s_by = {l["player_id"]: l for l in starters}
    b_by = {l["player_id"]: l for l in bench}
    s_ids = [l["player_id"] for l in starters]
    b_ids = [l["player_id"] for l in bench]
    voted = {pid for pid in s_ids + b_ids if not (s_by.get(pid) or b_by.get(pid))["sv"]}
    # A player whose real match has not been played yet is s.v. on paper but is NOT
    # a hole the bench should cover — see apply_classic_substitutions. On the bench
    # he is simply never eligible, which he already is by not being in ``voted``.
    frozen = {pid for pid in s_ids if s_by[pid].get("pending")}

    # ``def_locked``: la formazione e' stata cambiata a giornata cominciata, in una
    # lega col modificatore difesa. Da li' in poi la panchina non puo' piu' spostare
    # il numero di difensori in campo — v. apply_classic_substitutions.
    res = apply_classic_substitutions(s_ids, b_ids, roles, voted,
                                      max_subs=rs.max_substitutions, frozen=frozen,
                                      def_locked=def_locked)

    name = {l["player_id"]: l.get("name", str(l["player_id"])) for l in starters + bench}
    subs = []
    for out_pid, in_pid in res.subs:
        s_by[out_pid]["replaced_by"] = {"player_id": in_pid, "name": name[in_pid]}
        b_by[in_pid]["entered"] = True
        b_by[in_pid]["entered_for"] = {"player_id": out_pid, "name": name[out_pid]}
        subs.append({"out": {"player_id": out_pid, "name": name[out_pid]},
                     "in": {"player_id": in_pid, "name": name[in_pid]}})

    filled = _fill_unresolved(s_by, res.unresolved, rs.sv_office_vote)

    # Effective XI. An UNRESOLVED s.v. (fantavoto None) contributes nothing — it is
    # excluded from the sum (DEC-1), so the team simply sums fewer than 11 voti.
    # Unless the league fills the hole with its voto d'ufficio, in which case the
    # line has a vote by the time we get here and sums like any other.
    eff_lines = [(s_by.get(pid) or b_by.get(pid)) for pid in res.effective]
    base_total = round(sum(l["fantavoto"] for l in eff_lines if l["fantavoto"] is not None), 2)

    # Modifier context. The defence gate counts EITHER list depending on the league
    # (see defense_bonus); the votes always come from the EFFECTIVE XI, so a
    # substitute defender's vote counts towards the average under both readings.
    ctx = {
        "starter_lineup_roles": [l["lineup_role"] for l in starters],
        "def_votes": [l["voto_puro"] for l in eff_lines
                      if l["lineup_role"] == "DEF" and l["voto_puro"] is not None],
        "gk_line": next((l for l in eff_lines if l["lineup_role"] == "GK"), None),
        "effective": eff_lines,
    }
    ctx["gk_vote"] = ctx["gk_line"]["voto_puro"] if ctx["gk_line"] else None

    mods = [m for m in (fn(ctx, rs) for fn in MODIFIERS) if m is not None]

    # Legacy "defense" key kept for the existing match-detail payload/UI.
    defense = next((m.detail for m in mods if m.key == "defense"),
                   {"eligible": False, "reason": "disattivato", "avg": None, "bonus": 0.0,
                    "gate": None})

    return {
        "starters": [s_by[l["player_id"]] for l in starters],
        "bench": [b_by[l["player_id"]] for l in bench],
        "substitutions": subs,
        # The holes, and — of those — the ones the league's voto d'ufficio covered.
        # Both, because they are two different facts: the first says the manager
        # was left short, the second says what the rules did about it.
        "unresolved_sv": list(res.unresolved),
        "sv_filled": filled,
        # Fielded players whose real match has not been played: what the league has
        # to decide about (wait for the recovery, or impose an office vote).
        "pending": sorted(frozen),
        "base_total": base_total,
        "modifiers": mods,
        "defense": defense,
    }


# --------------------------------------------------------------------------- #
# Fixture resolution — apply cross-team modifiers and convert to goals.        #
# --------------------------------------------------------------------------- #
def resolve_fixture(home: dict, away: dict, rs: Ruleset, home_advantage: bool = False) -> dict:
    """Given the two ``score_team`` dicts, apply every modifier (self-add or
    subtract-from-opponent), convert each total to goals, and decide the result.
    Mutates ``home``/``away`` (adds applied/total/goals) and returns a summary.

    ``home_advantage`` è un fatto della PARTITA, non della lega: la lega dice
    quanto vale giocare in casa, il calendario dice se in questa partita giocare
    in casa vuol dire qualcosa (andata e ritorno sì, gara secca no). Arriva da
    ``FantasyFixture.home_advantage``; il default è "campo neutro" perché il
    motore viene usato anche dove una partita non c'è (simulazioni, prove).
    """
    totals = {"home": home["base_total"], "away": away["base_total"]}
    applied = {"home": 0.0, "away": 0.0}
    sides = {"home": home, "away": away}

    # Un modificatore come gli altri, così entra nel conteggio e nel tabellino
    # senza che nulla a valle debba conoscerlo: ha solo una condizione che
    # nessun altro ha, cioè da che parte del campo si gioca.
    if home_advantage and rs.home_advantage_bonus:
        home["modifiers"] = list(home["modifiers"]) + [ModifierResult(
            key="home_advantage", eligible=True, value=float(rs.home_advantage_bonus),
            scope=SELF_ADD, detail={"bonus": float(rs.home_advantage_bonus)})]

    for side, team in sides.items():
        other = "away" if side == "home" else "home"
        for m in team["modifiers"]:
            if not m.eligible or not m.value:
                continue
            if m.scope == SELF_ADD:
                totals[side] += m.value
                applied[side] += m.value
            elif m.scope == OPP_SUBTRACT:
                totals[other] -= m.value
                applied[other] -= m.value

    for side, team in sides.items():
        team["applied"] = round(applied[side], 2)
        team["total"] = round(totals[side], 2)
        team["goals"] = fantavote_to_goals(team["total"])
        # Keep legacy defense.applied/mode for the UI (only the defence bonus).
        team["defense"]["mode"] = rs.defense_mode
        team["defense"]["applied"] = round(
            sum((m.value if m.scope == SELF_ADD else -m.value)
                for t in sides.values() for m in t["modifiers"]
                if m.key == "defense" and m.eligible and (
                    (m.scope == SELF_ADD and t is team) or (m.scope == OPP_SUBTRACT and t is not team)
                )),
            2,
        )

    hg, ag = home["goals"], away["goals"]
    return {
        "home": home, "away": away,
        "home_goals": hg, "away_goals": ag,
        "home_total": home["total"], "away_total": away["total"],
        "result": "home" if hg > ag else "away" if ag > hg else "draw",
    }
