"""Forgiving name matching, server side.

TWIN OF ``vfoot-frontend/src/utils/text.ts``. The two must agree: the listone and
the market filter their (fully loaded) lists in the browser, while the auction
room asks the server — and a search that behaves differently depending on which
page you are on is worse than one that is merely strict. ``tests_name_search``
pins the shared cases; change one side and change the other.

Why fuzzy at all: player names are full of things nobody types the way they are
stored — diacritics (Leão, Çalhanoğlu, Szczęsny), apostrophes that vary by source
(and our own data has doubled ones), and spellings you have to have seen to
reproduce (Mkhitaryan). Requiring the exact string hides the player and reads as
a broken search.
"""
from __future__ import annotations

import unicodedata

_PUNCT = "’'`´-."


def fold(value: str | None) -> str:
    """Case-, accent- and punctuation-free form, for comparing typed with stored."""
    text = unicodedata.normalize("NFD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    for ch in _PUNCT:
        text = text.replace(ch, "")
    return text.lower().strip()


def _edit_distance_within(a: str, b: str, max_dist: int) -> int:
    """Levenshtein, abandoned as soon as it cannot come in under ``max_dist``."""
    if abs(len(a) - len(b)) > max_dist:
        return max_dist + 1
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        row = [i]
        best = i
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            v = min(prev[j] + 1, row[j - 1] + 1, prev[j - 1] + cost)
            row.append(v)
            best = min(best, v)
        if best > max_dist:
            return max_dist + 1
        prev = row
    return prev[len(b)]


def allowed_errors(needle: str) -> int:
    """How wrong a word may be and still count as the one that was meant. Short
    needles get no slack: on three letters, one error matches half the roster."""
    if len(needle) <= 3:
        return 0
    if len(needle) <= 6:
        return 1
    return 2


def matches(needle: str, *fields: str | None) -> bool:
    """Does ``needle`` match any of ``fields``, allowing accents, punctuation and
    a typo or two? An empty needle matches everything."""
    q = fold(needle)
    if not q:
        return True
    slack = allowed_errors(q)
    for field in fields:
        hay = fold(field)
        if not hay:
            continue
        if q in hay:
            return True
        if not slack:
            continue
        for word in hay.split():
            if _edit_distance_within(word, q, slack) <= slack:
                return True
            # Compare only the opening of a longer word, so a typo in a prefix
            # still lands: "gianluigy" vs "gianluigi donnarumma".
            if len(word) > len(q):
                head = word[: len(q) + slack]
                if _edit_distance_within(head, q, slack) <= slack:
                    return True
    return False
