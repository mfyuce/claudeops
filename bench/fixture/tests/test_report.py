from calc.report import summary


def test_summary():
    assert summary([1, 2, 3]) == "n=3 total=6"
