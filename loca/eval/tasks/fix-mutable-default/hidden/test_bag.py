from bag import add_item, add_many


def test_calls_do_not_leak_into_each_other():
    assert add_item("a") == ["a"]
    assert add_item("b") == ["b"]


def test_explicit_list_is_mutated_in_place():
    target = []
    result = add_item("x", target)
    assert result == ["x"]
    assert target == ["x"]


def test_add_many_is_isolated_too():
    assert add_many([1, 2]) == [1, 2]
    assert add_many([3]) == [3]


def test_add_many_mutates_explicit_list():
    target = ["z"]
    assert add_many([1], target) == ["z", 1]
    assert target == ["z", 1]
