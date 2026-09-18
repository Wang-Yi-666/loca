from counter import count_up


def test_counts_to_n_inclusive():
    assert count_up(3) == [1, 2, 3]


def test_large():
    assert count_up(10)[-1] == 10


def test_one():
    assert count_up(1) == [1]
