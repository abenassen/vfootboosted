from __future__ import annotations

import math


def fantavote_to_goals(fantavote_total: float) -> int:
    """Legacy-compatible optional conversion."""
    if fantavote_total < 66:
        return 0
    return math.floor((fantavote_total - 66) / 6) + 1
