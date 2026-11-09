"""Execution-match scoring: does the predicted result contain the gold result?

Two results match when:
  - they have the same number of rows, and
  - every gold column can be paired with a distinct predicted column so that the
    projected rows are equal (as a multiset, or in order when `ordered`).
Extra predicted columns are allowed: "What's the longest movie?" may return the title
plus its running time. Numbers match within rounding; text matches case-insensitively.
"""
from collections import Counter
from itertools import permutations

ABS_TOL = 0.051     # "6.8" vs "6.83" (models round differently)
REL_TOL = 0.005     # 0.5% for large numbers


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        try:
            return float(v.strip().rstrip("%"))
        except ValueError:
            return None
    return None


def values_equal(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    na, nb = _num(a), _num(b)
    if na is not None and nb is not None:
        return abs(na - nb) <= max(ABS_TOL, REL_TOL * abs(nb))
    return str(a).strip().casefold() == str(b).strip().casefold()


def _key(v):
    """Canonical form for multiset comparison (numbers rounded to 1 decimal)."""
    n = _num(v)
    if n is not None:
        return ("n", round(n, 1))
    return ("s", None if v is None else str(v).strip().casefold())


def _rows_match(gold: list[tuple], pred: list[tuple], ordered: bool) -> bool:
    if ordered:
        return all(values_equal(p, g) for gr, pr in zip(gold, pred) for g, p in zip(gr, pr))
    # Exact multiset first; fall back to pairing rows with tolerance (handles 6.85 vs 6.849).
    if Counter(map(lambda r: tuple(map(_key, r)), gold)) == Counter(map(lambda r: tuple(map(_key, r)), pred)):
        return True
    remaining = list(pred)
    for g in gold:
        hit = next((i for i, p in enumerate(remaining) if all(map(values_equal, g, p))), None)
        if hit is None:
            return False
        remaining.pop(hit)
    return True


def results_match(gold: list[tuple], pred: list[tuple], ordered: bool = False) -> bool:
    if len(gold) != len(pred):
        return False
    if not gold:
        return True
    n_gold, n_pred = len(gold[0]), len(pred[0])
    if n_pred < n_gold:
        return False
    # Try every way of picking gold-many predicted columns (results here are narrow, so this is cheap).
    for cols in permutations(range(n_pred), n_gold):
        projected = [tuple(row[c] for c in cols) for row in pred]
        if _rows_match(gold, projected, ordered):
            return True
    return False
