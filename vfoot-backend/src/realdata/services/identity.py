"""Cross-provider identity helpers: name normalisation + DOB sanity.

Shared by the Transfermarkt roster importer and the SofaScore adapter so both use
ONE definition of "same name" and "obviously-bogus birth date". Matching players
across providers (SofaScore <-> Transfermarkt) leans on (name, date-of-birth): the
name disambiguates DOB collisions, the DOB disambiguates transliterated/nicknamed
names — but neither is clean on its own (SofaScore ships Jan-1 placeholders and the
odd off-by-a-few-days date), so these helpers encode the rules that let each field
back up the other.
"""

from __future__ import annotations

import unicodedata
from datetime import date
from difflib import SequenceMatcher


def norm_name(name: str | None) -> str:
    """Lowercase, strip accents/punctuation, collapse spaces.

    'Milan Đurić' -> 'milan duric'; 'Łukasz Skorupski' -> 'lukasz skorupski'.
    """
    if not name:
        return ""
    nfkd = unicodedata.normalize("NFKD", name)
    no_marks = "".join(c for c in nfkd if not unicodedata.combining(c))
    cleaned = "".join(c if c.isalnum() else " " for c in no_marks.lower())
    return " ".join(cleaned.split())


def name_similarity(a: str | None, b: str | None) -> float:
    """Similarity in [0,1], robust to token reordering (surname-first vs -last)."""
    na, nb = norm_name(a), norm_name(b)
    if not na or not nb:
        return 0.0
    direct = SequenceMatcher(None, na, nb).ratio()
    sa, sb = set(na.split()), set(nb.split())
    token = len(sa & sb) / len(sa | sb) if (sa | sb) else 0.0
    return max(direct, token)


def is_placeholder_dob(d: date | None) -> bool:
    """SofaScore uses Jan 1 when the real birth date is unknown — treat as missing."""
    return bool(d) and d.month == 1 and d.day == 1
