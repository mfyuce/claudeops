"""Plain-text report built on top of mathops."""

from calc.mathops import compute_total


def summary(values):
    # TODO: support a JSON output format
    return f"n={len(values)} total={compute_total(values)}"
