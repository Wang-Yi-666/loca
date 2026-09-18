import math

from graph import shortest_path

EDGES = [
    ("a", "b", 1),
    ("b", "c", 2),
    ("a", "c", 10),
    ("c", "d", 3),
    ("b", "d", 20),
]


def test_cheapest_route_is_taken():
    cost, path = shortest_path(EDGES, "a", "d")
    assert cost == 6
    assert path == ["a", "b", "c", "d"]


def test_direct_edge_loses_to_a_cheaper_detour():
    cost, path = shortest_path(EDGES, "a", "c")
    assert cost == 3
    assert path == ["a", "b", "c"]


def test_start_equals_goal():
    cost, path = shortest_path(EDGES, "a", "a")
    assert cost == 0
    assert path == ["a"]


def test_unreachable_goal():
    cost, path = shortest_path(EDGES, "d", "a")
    assert math.isinf(cost)
    assert path == []


def test_empty_graph():
    cost, path = shortest_path([], "a", "b")
    assert math.isinf(cost)
    assert path == []


def test_multi_hop_chain():
    edges = [("s", "a", 1), ("a", "b", 1), ("b", "c", 1), ("c", "t", 1)]
    cost, path = shortest_path(edges, "s", "t")
    assert cost == 4
    assert path == ["s", "a", "b", "c", "t"]


def test_path_starts_and_ends_correctly():
    cost, path = shortest_path(EDGES, "a", "b")
    assert cost == 1
    assert path[0] == "a"
    assert path[-1] == "b"


def test_cycles_do_not_hang():
    edges = [("a", "b", 1), ("b", "a", 1), ("b", "c", 1)]
    cost, path = shortest_path(edges, "a", "c")
    assert cost == 2
    assert path == ["a", "b", "c"]
