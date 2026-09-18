"""One-off generator for the HARD tier: self-contained algorithm work.

Same contract as the other two generators. These tasks are single-file but the
spec is tighter - every edge case the grader checks is spelled out in the seed
docstring, so a failure means the model missed the spec rather than guessed it
wrongly.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

# This file lives in loca/eval/tasks/_generate/, so the task set is its
# grandparent directory.
TASKS_ROOT = Path(__file__).resolve().parent.parent

TASKS = [
    {
        "id": "impl-lru-cache",
        "title": "Implement an LRU cache",
        "difficulty": "hard",
        "tags": ["implementation", "data-structures"],
        "prompt": (
            "Implement cache.py's LRUCache. Both get and put count as a use of a key; put "
            "on a full cache evicts the least recently used entry; overwriting an existing "
            "key must not grow the cache. get returns None for a missing key. Aim for O(1) "
            "operations."
        ),
        "seed": {
            "cache.py": '''"""A fixed-capacity cache with least-recently-used eviction."""


class LRUCache:
    """Capacity-bounded cache.

    - get(key) returns the stored value, or None when the key is absent.
    - get(key) counts as a use, as does put() on a key that already exists.
    - put(key, value) on a full cache evicts the least recently used entry.
    - put() on an existing key replaces the value without changing the size.
    """

    def __init__(self, capacity):
        raise NotImplementedError

    def get(self, key):
        raise NotImplementedError

    def put(self, key, value):
        raise NotImplementedError

    def __len__(self):
        raise NotImplementedError
''',
        },
        "hidden": {
            "test_cache.py": '''import pytest

from cache import LRUCache


def test_put_and_get():
    cache = LRUCache(2)
    cache.put("a", 1)
    assert cache.get("a") == 1
    assert cache.get("missing") is None


def test_evicts_the_least_recently_used():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.get("a")
    cache.put("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3


def test_put_refreshes_recency():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("a", 10)
    cache.put("c", 3)
    assert cache.get("b") is None
    assert cache.get("a") == 10


def test_overwrite_does_not_grow_the_cache():
    cache = LRUCache(2)
    cache.put("a", 1)
    cache.put("a", 2)
    cache.put("b", 3)
    cache.put("c", 4)
    assert cache.get("a") is None
    assert cache.get("c") == 4
    assert cache.get("b") == 3


def test_capacity_of_one():
    cache = LRUCache(1)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") is None
    assert cache.get("b") == 2


def test_len_tracks_entries():
    cache = LRUCache(3)
    assert len(cache) == 0
    cache.put("a", 1)
    cache.put("b", 2)
    assert len(cache) == 2
    cache.put("a", 9)
    assert len(cache) == 2


def test_zero_capacity_stores_nothing():
    cache = LRUCache(0)
    cache.put("a", 1)
    assert cache.get("a") is None
    assert len(cache) == 0


def test_values_may_be_falsy():
    cache = LRUCache(2)
    cache.put("zero", 0)
    cache.put("none", None)
    assert cache.get("zero") == 0
    assert cache.get("none") is None
    assert len(cache) == 2
''',
        },
    },
    {
        "id": "impl-topological-sort",
        "title": "Implement topological sort with cycle detection",
        "difficulty": "hard",
        "tags": ["implementation", "graphs"],
        "prompt": (
            "Implement toposort() in toposort.py. The result must be deterministic: when "
            "several nodes are ready at the same time, take them in alphabetical order. "
            "Nodes that only ever appear as dependencies must still be included, and a "
            "cycle (including a self-loop) must raise ValueError."
        ),
        "seed": {
            "toposort.py": '''"""Topological sorting."""


def toposort(graph):
    """Topologically sort a mapping of {node: [dependencies]}.

    - Every node appears after all of its dependencies.
    - Nodes that appear only as dependencies are included in the result.
    - Ties are broken alphabetically, so the output is deterministic.
    - Raise ValueError when the graph contains a cycle (a self-loop counts).
    """
    raise NotImplementedError
''',
        },
        "hidden": {
            "test_toposort.py": '''import pytest

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
''',
        },
    },
    {
        "id": "impl-csv-line-parser",
        "title": "Implement a CSV line parser with quoted fields",
        "difficulty": "hard",
        "tags": ["implementation", "parsing"],
        "prompt": (
            "Implement parse_line() in csvline.py. Quoted fields may contain commas, a "
            "doubled quote inside a quoted field means one literal quote, and quotes are "
            "only special at the start of a field. Empty fields must be preserved. Do not "
            "use the csv module - write the parser."
        ),
        "seed": {
            "csvline.py": '''"""A single-line CSV field splitter."""


def parse_line(line):
    """Split one CSV line into a list of fields.

    - Fields are separated by commas.
    - A field starting with a double quote may contain commas.
    - Inside a quoted field, "" means one literal quote character.
    - Quotes are only special at the start of a field; in the middle of an
      unquoted field they are ordinary characters.
    - Empty fields are preserved, including a trailing empty field.
    """
    raise NotImplementedError
''',
        },
        "hidden": {
            "test_csvline.py": '''from csvline import parse_line


def test_plain_fields():
    assert parse_line("a,b,c") == ["a", "b", "c"]


def test_single_field():
    assert parse_line("solo") == ["solo"]


def test_empty_fields_are_preserved():
    assert parse_line("a,,c") == ["a", "", "c"]


def test_trailing_empty_field():
    assert parse_line("a,b,") == ["a", "b", ""]


def test_quoted_field_with_comma():
    assert parse_line('a,"b,c",d') == ["a", "b,c", "d"]


def test_escaped_quote_inside_quotes():
    assert parse_line('"say ""hi""",x') == ['say "hi"', "x"]


def test_quoted_empty_field():
    assert parse_line('""') == [""]


def test_quote_in_the_middle_is_literal():
    assert parse_line('ab"cd,e') == ['ab"cd', "e"]


def test_quoted_field_with_spaces():
    assert parse_line('"  padded  ",x') == ["  padded  ", "x"]
''',
        },
    },
    {
        "id": "impl-roman-numerals",
        "title": "Implement Roman numeral conversion both ways",
        "difficulty": "hard",
        "tags": ["implementation", "algorithms", "validation"],
        "prompt": (
            "Implement to_roman() and from_roman() in roman.py. The two must round-trip "
            "exactly: from_roman has to reject anything whose canonical form differs from "
            "what to_roman would produce, so 'IIII' and 'VV' are errors even though they "
            "look readable."
        ),
        "seed": {
            "roman.py": '''"""Roman numeral conversion."""

MIN_VALUE = 1
MAX_VALUE = 3999


def to_roman(value):
    """Convert an integer in 1..3999 to a Roman numeral.

    Raise ValueError outside that range.
    """
    raise NotImplementedError


def from_roman(text):
    """Parse an upper-case Roman numeral for a value in 1..3999.

    The input must be in canonical upper-case form: from_roman(to_roman(n))
    == n for every n in range, and anything to_roman would never emit (such as
    "IIII" or "VV") raises ValueError. Lower-case input is rejected too.
    """
    raise NotImplementedError
''',
        },
        "hidden": {
            "test_roman.py": '''import pytest

from roman import from_roman, to_roman

CASES = [
    (1, "I"),
    (2, "II"),
    (3, "III"),
    (4, "IV"),
    (5, "V"),
    (9, "IX"),
    (14, "XIV"),
    (40, "XL"),
    (44, "XLIV"),
    (49, "XLIX"),
    (90, "XC"),
    (400, "CD"),
    (900, "CM"),
    (1990, "MCMXC"),
    (2024, "MMXXIV"),
    (3888, "MMMDCCCLXXXVIII"),
    (3999, "MMMCMXCIX"),
]


def test_to_roman():
    for value, expected in CASES:
        assert to_roman(value) == expected, value


def test_from_roman():
    for value, text in CASES:
        assert from_roman(text) == value, text


def test_round_trip_over_the_whole_range():
    for value in range(1, 4000):
        assert from_roman(to_roman(value)) == value


@pytest.mark.parametrize("bad", [0, -1, 4000])
def test_to_roman_range(bad):
    with pytest.raises(ValueError):
        to_roman(bad)


@pytest.mark.parametrize("bad", ["", "ABC", "IIII", "VV", "IC", "XM", "MCMC"])
def test_non_canonical_input_is_rejected(bad):
    with pytest.raises(ValueError):
        from_roman(bad)


def test_lowercase_input_is_rejected():
    with pytest.raises(ValueError):
        from_roman("xiv")
''',
        },
    },
    {
        "id": "impl-expression-evaluator",
        "title": "Implement an arithmetic expression evaluator",
        "difficulty": "hard",
        "tags": ["implementation", "parsing", "recursion"],
        "prompt": (
            "Implement evaluate() in expr.py: an arithmetic evaluator supporting + - * / "
            "with the usual precedence (and left associativity), parentheses, and "
            "whitespace anywhere. Use integer division for /. Malformed input and "
            "unbalanced parentheses must raise ValueError. Do not use eval()."
        ),
        "seed": {
            "expr.py": '''"""A small arithmetic expression evaluator."""


def evaluate(text):
    """Evaluate an arithmetic expression over integers.

    - Operators: + - * / with the usual precedence, evaluated left to right.
    - Parentheses group sub-expressions.
    - Whitespace is ignored.
    - / is integer division (7/2 == 3).
    - Raise ValueError for malformed input or unbalanced parentheses.
    """
    raise NotImplementedError
''',
        },
        "hidden": {
            "test_expr.py": '''import pytest

from expr import evaluate


def test_single_number():
    assert evaluate("42") == 42


def test_precedence():
    assert evaluate("2+3*4") == 14


def test_left_associativity():
    assert evaluate("10-3-2") == 5
    assert evaluate("100/10/2") == 5


def test_parentheses():
    assert evaluate("(2+3)*4") == 20


def test_nested_parentheses():
    assert evaluate("2*(3+(4-1))") == 12


def test_whitespace_is_ignored():
    assert evaluate("  2 + 3 * 4 ") == 14
    assert evaluate("( 1 + 2 ) * 3") == 9


def test_integer_division():
    assert evaluate("7/2") == 3


def test_mixed_expression():
    assert evaluate("1+2*3-4/2") == 5


def test_deeply_nested():
    assert evaluate("((((1+1))))") == 2


@pytest.mark.parametrize("bad", ["", "(1+2", "1+", "*3", "1++2", "()", "abc"])
def test_malformed_input_is_rejected(bad):
    with pytest.raises(ValueError):
        evaluate(bad)
''',
        },
    },
    {
        "id": "impl-merge-intervals",
        "title": "Implement interval merging",
        "difficulty": "hard",
        "tags": ["implementation", "algorithms"],
        "prompt": (
            "Implement merge() in intervals.py. Intervals are closed [start, end] pairs and "
            "the input is not sorted. Overlapping intervals merge, and so do intervals that "
            "merely touch (so [1,2] and [2,3] become [1,3]). The input list must not be "
            "modified."
        ),
        "seed": {
            "intervals.py": '''"""Interval merging."""


def merge(intervals):
    """Merge overlapping or touching closed intervals.

    - Input is a list of [start, end] pairs, in any order.
    - Return a new list of [start, end] pairs, sorted by start.
    - Intervals that only touch, like [1, 2] and [2, 3], are merged.
    - The input must not be mutated.
    """
    raise NotImplementedError
''',
        },
        "hidden": {
            "test_intervals.py": '''from intervals import merge


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
''',
        },
    },
    {
        "id": "impl-word-wrap",
        "title": "Implement greedy word wrapping",
        "difficulty": "hard",
        "tags": ["implementation", "strings"],
        "prompt": (
            "Implement wrap() in wrap.py: greedy word wrap to a maximum width. Words longer "
            "than the width go on a line of their own and are never split. An existing "
            "newline in the text ends the current line. Lines must not carry trailing "
            "spaces, and the original words must not be altered."
        ),
        "seed": {
            "wrap.py": '''"""Greedy word wrapping."""


def wrap(text, width):
    """Wrap `text` into lines of at most `width` characters.

    - Greedy: pack as many whole words as fit, then start a new line.
    - A word longer than `width` goes on its own line, unbroken.
    - An existing newline ends the current line.
    - No line has trailing whitespace.
    - Raise ValueError when width is less than 1.
    """
    raise NotImplementedError
''',
        },
        "hidden": {
            "test_wrap.py": '''import pytest

from wrap import wrap

NEWLINE = chr(10)


def test_simple_wrap():
    assert wrap("the quick brown fox", 10) == ["the quick", "brown fox"]


def test_exact_fit():
    assert wrap("aaa bbb", 7) == ["aaa bbb"]


def test_one_word_per_line_when_narrow():
    assert wrap("aa bb cc", 2) == ["aa", "bb", "cc"]


def test_long_word_is_not_split():
    assert wrap("a supercalifragilistic b", 5) == ["a", "supercalifragilistic", "b"]


def test_existing_newline_forces_a_break():
    assert wrap("one two" + NEWLINE + "three four", 20) == ["one two", "three four"]


def test_empty_text():
    assert wrap("", 10) == []


def test_no_trailing_whitespace():
    for line in wrap("a b c d e f g", 3):
        assert line == line.rstrip()


def test_all_words_are_preserved():
    text = "alpha beta gamma delta epsilon"
    joined = " ".join(wrap(text, 11))
    assert joined.split() == text.split()


@pytest.mark.parametrize("bad", [0, -1])
def test_width_must_be_positive(bad):
    with pytest.raises(ValueError):
        wrap("x", bad)


def test_width_of_one():
    assert wrap("a b", 1) == ["a", "b"]
''',
        },
    },
    {
        "id": "impl-json-pointer",
        "title": "Implement RFC 6901 JSON Pointer resolution",
        "difficulty": "hard",
        "tags": ["implementation", "spec", "data-structures"],
        "prompt": (
            "Implement resolve() in jsonptr.py following RFC 6901. Mind the escaping order: "
            "~1 becomes / and ~0 becomes ~, and they must be unescaped in that order so a "
            "key containing the literal text ~1 survives a round trip. Missing object keys "
            "raise KeyError; list indexes that are missing or not integers raise IndexError."
        ),
        "seed": {
            "jsonptr.py": '''"""RFC 6901 JSON Pointer resolution."""


def resolve(document, pointer):
    """Resolve a JSON Pointer against a parsed JSON document.

    - "" returns the whole document.
    - "/a/b" walks into nested objects and lists.
    - "~1" decodes to "/" and "~0" to "~", unescaped in that order.
    - Raise KeyError for a missing object key.
    - Raise IndexError for a list index that is absent, not an integer, or
      written with a leading zero ("01" is not a valid index).
    """
    raise NotImplementedError
''',
        },
        "hidden": {
            "test_jsonptr.py": '''import pytest

from jsonptr import resolve

DOC = {
    "a": {"b": [10, 20, {"c": "deep"}]},
    "m~n": 1,
    "p/q": 2,
    "": 3,
    " ": 4,
    "~1": 5,
}


def test_empty_pointer_returns_the_document():
    assert resolve(DOC, "") == DOC


def test_escaped_tilde():
    assert resolve(DOC, "/m~0n") == 1


def test_escaped_slash():
    assert resolve(DOC, "/p~1q") == 2


def test_literal_tilde_one_key():
    assert resolve(DOC, "/~01") == 5


def test_list_index():
    assert resolve(DOC, "/a/b/1") == 20


def test_nested_object_in_a_list():
    assert resolve(DOC, "/a/b/2/c") == "deep"


def test_empty_key():
    assert resolve(DOC, "/") == 3


def test_space_key():
    assert resolve(DOC, "/ ") == 4


def test_missing_key_raises_keyerror():
    with pytest.raises(KeyError):
        resolve(DOC, "/nope")


def test_missing_index_raises_indexerror():
    with pytest.raises(IndexError):
        resolve(DOC, "/a/b/9")


def test_non_numeric_index_raises_indexerror():
    with pytest.raises(IndexError):
        resolve(DOC, "/a/b/x")


def test_leading_zero_index_is_rejected():
    with pytest.raises(IndexError):
        resolve(DOC, "/a/b/01")
''',
        },
    },
    {
        "id": "impl-dijkstra",
        "title": "Implement Dijkstra shortest path",
        "difficulty": "hard",
        "tags": ["implementation", "graphs", "algorithms"],
        "prompt": (
            "Implement shortest_path() in graph.py. It takes a list of (source, target, "
            "weight) triples for a directed graph with positive weights and returns "
            "(cost, path). When the goal cannot be reached, return (math.inf, []). A start "
            "that equals the goal costs 0."
        ),
        "seed": {
            "graph.py": '''"""Shortest paths over a directed weighted graph."""


def shortest_path(edges, start, goal):
    """Dijkstra over the edges given as (source, target, weight) triples.

    Weights are positive. Return (total_cost, [nodes]) for the cheapest route
    from `start` to `goal`. When `goal` is unreachable return (math.inf, []).
    When `start` equals `goal` return (0, [start]).
    """
    raise NotImplementedError
''',
        },
        "hidden": {
            "test_graph.py": '''import math

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
''',
        },
    },
    {
        "id": "impl-sliding-window-limiter",
        "title": "Implement a sliding-window rate limiter",
        "difficulty": "hard",
        "tags": ["implementation", "state", "algorithms"],
        "prompt": (
            "Implement SlidingWindowLimiter in limiter.py. Time is passed in as a float so "
            "behaviour is deterministic - do not read the clock. Watch the window boundary: "
            "an event recorded at time t stops counting once now - t is greater than or "
            "equal to the window. Rejected calls must not consume budget."
        ),
        "seed": {
            "limiter.py": '''"""A sliding-window rate limiter."""


class SlidingWindowLimiter:
    """Allow at most `limit` events in any `window`-second span.

    Time is supplied by the caller as a float, so the limiter is fully
    deterministic and never reads the clock itself.

    - allow(now) returns True and records the event when the budget allows.
    - allow(now) returns False and records nothing when it does not.
    - An event recorded at time t stops counting once now - t >= window.
    """

    def __init__(self, limit, window):
        raise NotImplementedError

    def allow(self, now):
        raise NotImplementedError
''',
        },
        "hidden": {
            "test_limiter.py": '''from limiter import SlidingWindowLimiter


def test_allows_up_to_the_limit():
    limiter = SlidingWindowLimiter(limit=3, window=10)
    assert [limiter.allow(0.0) for _ in range(3)] == [True, True, True]
    assert limiter.allow(0.0) is False


def test_old_events_leave_the_window():
    limiter = SlidingWindowLimiter(limit=2, window=10)
    assert limiter.allow(0.0) is True
    assert limiter.allow(1.0) is True
    assert limiter.allow(1.0) is False
    assert limiter.allow(10.0) is True


def test_rejected_calls_do_not_consume_budget():
    limiter = SlidingWindowLimiter(limit=1, window=5)
    assert limiter.allow(0.0) is True
    assert limiter.allow(1.0) is False
    assert limiter.allow(5.0) is True


def test_window_boundary_is_half_open():
    limiter = SlidingWindowLimiter(limit=1, window=10)
    assert limiter.allow(0.0) is True
    assert limiter.allow(9.9) is False
    assert limiter.allow(10.0) is True


def test_spread_out_calls_are_all_allowed():
    limiter = SlidingWindowLimiter(limit=2, window=10)
    assert limiter.allow(0.0) is True
    assert limiter.allow(5.0) is True
    assert limiter.allow(10.0) is True
    assert limiter.allow(15.0) is True


def test_time_may_go_backwards_without_crashing():
    limiter = SlidingWindowLimiter(limit=2, window=10)
    assert limiter.allow(100.0) is True
    assert limiter.allow(0.0) is True
    assert limiter.allow(0.0) is False


def test_limit_of_one():
    limiter = SlidingWindowLimiter(limit=1, window=1)
    assert limiter.allow(0.0) is True
    assert limiter.allow(0.5) is False
    assert limiter.allow(1.0) is True
''',
        },
    },
]


def main() -> None:
    for task in TASKS:
        root = TASKS_ROOT / task["id"]
        if root.exists():
            shutil.rmtree(root)
        (root / "workspace").mkdir(parents=True)
        (root / "hidden").mkdir(parents=True)

        for name, content in task["seed"].items():
            (root / "workspace" / name).write_text(content, encoding="utf-8", newline="\n")
        for name, content in task["hidden"].items():
            (root / "hidden" / name).write_text(content, encoding="utf-8", newline="\n")

        manifest = {
            "id": task["id"],
            "title": task["title"],
            "difficulty": task["difficulty"],
            "tags": task["tags"],
            "prompt": task["prompt"],
            "checks": {"kind": "pytest", "paths": sorted(task["hidden"])},
        }
        (root / "task.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        print(f"wrote {task['id']}")


if __name__ == "__main__":
    main()
