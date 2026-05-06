"""Constants shared across lead/ modules — no heavy imports."""

import itertools


# Canonical ordering of the 15 unordered pairs of {0..5}.
PAIRS_6 = list(itertools.combinations(range(6), 2))  # 15 tuples


def lead_pair_to_index(i: int, j: int) -> int:
    a, b = sorted((i, j))
    return PAIRS_6.index((a, b))
