import pytest

from toposort import toposort


def test_linear_chain():
    assert toposort({"c": ["b"], "b": ["a"], "a": []}) == ["a", "b", "c"]


def test_independent_nodes_are_sorted():
    assert toposort({"b": [], "a": []}) == ["a", "b"]


def test_dependency_only_nodes_are_included():
    result = toposort({"app": ["lib", "db"]})
    assert result[-1] == "app"
    assert set(result) == {"app", "lib", "db"}


def test_diamond():
    result = toposort({"d": ["b", "c"], "b": ["a"], "c": ["a"], "a": []})
    assert result == ["a", "b", "c", "d"]


def test_empty_graph():
    assert toposort({}) == []


def test_node_with_no_dependencies_comes_first():
    result = toposort({"x": [], "y": ["x"]})
    assert result.index("x") < result.index("y")


def test_two_node_cycle_raises():
    with pytest.raises(ValueError):
        toposort({"a": ["b"], "b": ["a"]})


def test_self_loop_raises():
    with pytest.raises(ValueError):
        toposort({"a": ["a"]})


def test_cycle_is_detected_even_when_part_of_the_graph_is_fine():
    with pytest.raises(ValueError):
        toposort({"ok": [], "a": ["b"], "b": ["c"], "c": ["a"]})


def test_result_is_a_valid_ordering():
    graph = {"a": [], "b": ["a"], "c": ["a"], "d": ["b", "c"], "e": ["d"]}
    result = toposort(graph)
    position = {node: index for index, node in enumerate(result)}
    for node, deps in graph.items():
        for dep in deps:
            assert position[dep] < position[node]
