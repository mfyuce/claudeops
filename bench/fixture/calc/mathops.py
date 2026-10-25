"""Basic arithmetic helpers."""

from calc.config import DEFAULT_PRECISION


def add(a, b):
    return a + b


def compute_total(values):
    total = 0
    for v in values:
        total = add(total, v)
    return total


def mean(values):
    # TODO: handle an empty list
    return round(compute_total(values) / (len(values) + 1), DEFAULT_PRECISION)
