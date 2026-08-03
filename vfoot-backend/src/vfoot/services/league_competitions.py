"""Which competition a league MEANS when it does not say.

Most leagues have one championship and a cup or two, and "the standings" without
further qualification means the championship's. That shortcut is legitimate and
worth keeping — asking a page to name a competition it has no way of knowing would
only push the guess one level up.

What is not legitimate is guessing BADLY and silently, which is what happened
before: the answer was "the first round-robin BY ID", i.e. whichever was created
first. A league with two championships got one of the two with nothing to say why,
and a league whose cup happened to be created first got the cup.
"""
from __future__ import annotations

from django.db.models import Count, Q

from vfoot.models import FantasyCompetition, FantasyFixture


def main_competition(league) -> FantasyCompetition | None:
    """The league's principal competition, or None if it has none.

    THE MOST MATCHES WINS, and that is the whole heuristic. It is a good one because
    it measures the thing that actually makes a competition principal: a
    championship every team plays home and away — three times over, in a long league
    — dwarfs a cup, whose whole point is that most teams stop playing in it. It also
    needs no new field, no admin decision, and no migration: it reads what the league
    already is.

    Only ROUND-ROBIN competitions are candidates, because the caller wants a table
    and a knockout has none. A league made only of knockouts falls back to the
    largest of those rather than to nothing: half an answer beats an empty page, and
    the caller is told which competition it got.

    Ties break on the LOWEST ID — the oldest — purely so the answer is stable. Two
    round-robin competitions with the same number of matches are genuinely
    ambiguous, and no ordering here is more correct than another; what matters is
    that it does not change between two requests.
    """
    qs = (league.competitions
          .annotate(n=Count("fixtures", filter=Q(fixtures__isnull=False)))
          .order_by("-n", "id"))
    round_robin = [c for c in qs if c.competition_type == FantasyCompetition.TYPE_ROUND_ROBIN]
    return (round_robin or list(qs) or [None])[0]


def competition_match_counts(league) -> dict[int, int]:
    """{competition_id: fixtures} — what `main_competition` decided on, for anyone
    who needs to explain the choice rather than just make it."""
    return dict(
        FantasyFixture.objects.filter(competition__league=league)
        .values_list("competition_id")
        .annotate(n=Count("id"))
        .values_list("competition_id", "n")
    )
