from intervals import merge


def test_merges_overlaps():
    assert merge([[1, 3], [2, 6], [8, 10], [15, 18]]) == [[1, 6], [8, 10], [15, 18]]


def test_unsorted_input():
    assert merge([[8, 10], [1, 3], [2, 6]]) == [[1, 6], [8, 10]]


def test_touching_intervals_merge():
    assert merge([[1, 2], [2, 3]]) == [[1, 3]]


def test_contained_interval_is_absorbed():
    assert merge([[1, 10], [2, 3]]) == [[1, 10]]


def test_identical_intervals():
    assert merge([[1, 5], [1, 5]]) == [[1, 5]]


def test_single_interval():
    assert merge([[4, 7]]) == [[4, 7]]


def test_empty_input():
    assert merge([]) == []


def test_disjoint_intervals_are_kept_apart():
    assert merge([[1, 2], [4, 5]]) == [[1, 2], [4, 5]]


def test_chain_of_touching_intervals():
    assert merge([[1, 2], [2, 3], [3, 4]]) == [[1, 4]]


def test_input_is_not_mutated():
    data = [[1, 3], [2, 6]]
    merge(data)
    assert data == [[1, 3], [2, 6]]
