from calc.mathops import add, compute_total, mean


def test_add():
    assert add(2, 3) == 5


def test_compute_total():
    assert compute_total([1, 2, 3, 4]) == 10


def test_mean():
    assert mean([2, 4, 6]) == 4
