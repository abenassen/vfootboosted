"""The two properties a scenario is worth nothing without.

A simulated season exists so a state can be returned to. That needs more than
"looks plausible": it needs the SAME state to come back, and a LATER state to be
the same match seen further on rather than a new one. Both were broken in the first
version — the clock shortened the simulation instead of cutting its output, and
each fixture drew from a shared stream — and neither failure is visible until the
clock actually moves, which is exactly when you have stopped watching for it.

No database: the generator is fed hand-built squads and a two-entry donor pool, so
these run in milliseconds and fail for one reason only.
"""
from __future__ import annotations

import random

from django.test import SimpleTestCase

from realdata.services.season_simulator import (
    DonorPool,
    SimPlayer,
    SimTeam,
    simulate_match,
)


def _donor(minutes: int, rating: float) -> dict:
    """A stat blob shaped like the provider's, thin but complete enough."""
    return {"minutesPlayed": minutes, "rating": rating, "touches": 55,
            "totalPass": 40, "accuratePass": 33, "duelWon": 4, "duelLost": 3,
            "ballRecovery": 5, "defensiveValueNormalized": 0.1, "position": "M"}


def _pool() -> DonorPool:
    buckets = {}
    for position in ("G", "D", "M", "F"):
        for bucket in range(4):
            buckets[(position, bucket)] = [_donor(90, 5.9), _donor(90, 6.4),
                                           _donor(90, 7.1)]
    return DonorPool(by_key=buckets)


def _team(team_id: int, name: str) -> SimTeam:
    roles = ["POR"] * 3 + ["DIF"] * 8 + ["CEN"] * 8 + ["ATT"] * 6
    players = [
        SimPlayer(player_id=team_id * 100 + i, sofa_id=str(team_id * 100 + i),
                  name=f"{name} {i}", short_name=f"{name[:3]}{i}", dob_ts=None,
                  role=role, value_eur=(30 - i) * 1_000_000, quality=(25 - i) / 25)
        for i, role in enumerate(roles)
    ]
    team = SimTeam(team_season_id=team_id, sofa_id=str(team_id), name=name,
                   short_name=name[:3], players=players)
    team.depth = {r: [p for p in players if p.role == r]
                  for r in ("POR", "DIF", "CEN", "ATT")}
    return team


def _play(clock: int, seed: str = "s:12345"):
    return simulate_match(_team(1, "Alfa"), _team(2, "Beta"), 22, _pool(),
                          random.Random(seed), clock=clock)


class DeterminismTests(SimpleTestCase):
    def test_same_seed_same_match(self):
        """The scenario's promise, at its smallest: ask twice, get the same match."""
        a, b = _play(90), _play(90)
        self.assertEqual((a.home_goals, a.away_goals), (b.home_goals, b.away_goals))
        self.assertEqual(a.shotmap, b.shotmap)
        self.assertEqual(a.incidents, b.incidents)

    def test_a_different_fixture_is_a_different_match(self):
        """Keyed on identity, so the seed has to actually reach the draw."""
        a, b = _play(90, seed="s:12345"), _play(90, seed="s:99999")
        self.assertNotEqual((a.home_goals, a.away_goals, len(a.shotmap)),
                            (b.home_goals, b.away_goals, len(b.shotmap)))


class ClockTests(SimpleTestCase):
    """Watching the same match at different minutes."""

    def test_the_score_never_goes_backwards(self):
        """A goal scored at the 20th minute is still there at the 90th.

        This is what the first implementation could not promise: the clock shortened
        the simulation, so every later draw shifted and a side could lead 1-0 at the
        35th minute and finish 0-0. Nothing about a live pipeline can be tested
        against a match that re-rolls itself.
        """
        previous = (0, 0)
        for clock in (10, 25, 40, 60, 75, 90):
            match = _play(clock)
            self.assertGreaterEqual(match.home_goals, previous[0],
                                    f"home score fell at minute {clock}")
            self.assertGreaterEqual(match.away_goals, previous[1],
                                    f"away score fell at minute {clock}")
            previous = (match.home_goals, match.away_goals)

    def test_the_final_score_is_the_full_match(self):
        full = _play(90)
        self.assertEqual((full.home_goals, full.away_goals),
                         (_play(120).home_goals, _play(120).away_goals))

    def test_nothing_has_happened_after_the_current_minute(self):
        clock = 37
        match = _play(clock)
        for shot in match.shotmap:
            self.assertLessEqual(shot["time"], clock)
        for incident in match.incidents:
            self.assertLessEqual(incident["time"], clock)

    def test_earlier_events_are_a_prefix_of_later_ones(self):
        """Not merely 'as many', but THE SAME ONES: a live feed that reshuffled who
        scored while keeping the count would pass a weaker test and be just as
        useless."""
        early = {(s["time"], s["player"]["id"], s["shotType"]) for s in _play(40).shotmap}
        late = {(s["time"], s["player"]["id"], s["shotType"]) for s in _play(90).shotmap}
        self.assertTrue(early <= late, "the shots seen at 40' are not among the 90'")

    def test_nobody_has_played_more_than_the_clock(self):
        clock = 52
        match = _play(clock)
        for side in ("home", "away"):
            for entry in match.lineups[side]["players"]:
                self.assertLessEqual(entry["statistics"].get("minutesPlayed", 0), clock)

    def test_the_squad_sheet_is_complete_while_in_progress(self):
        """A substitute who has not come on yet is still ON THE BENCH, and the
        conclusion has to be able to tell that from not being in the squad — the
        first is an s.v., the second is nothing at all."""
        for side in ("home", "away"):
            self.assertEqual(len(_play(30).lineups[side]["players"]),
                             len(_play(90).lineups[side]["players"]))
