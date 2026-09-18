from dedupe import unique


def test_keeps_first_appearance_order():
    assert unique([3, 1, 3, 2, 1]) == [3, 1, 2]


def test_strings():
    assert unique(["b", "a", "b"]) == ["b", "a"]


def test_empty():
    assert unique([]) == []


def test_already_unique():
    assert unique([1, 2, 3]) == [1, 2, 3]


def test_all_the_same():
    assert unique(["x", "x", "x"]) == ["x"]
