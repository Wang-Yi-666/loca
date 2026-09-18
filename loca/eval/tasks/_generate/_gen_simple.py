"""One-off generator for the SIMPLE tier of the loca eval task set.

Run once, then delete. Each entry becomes:

    loca/eval/tasks/<id>/task.json
    loca/eval/tasks/<id>/workspace/<seed files>
    loca/eval/tasks/<id>/hidden/<grader files>

File contents are kept in triple-single-quoted strings so the generated
Python can use double quotes freely. No backslash escapes are used anywhere,
so nothing needs double-escaping.
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
        "id": "fix-off-by-one",
        "title": "count_up drops the last number",
        "difficulty": "simple",
        "tags": ["bugfix", "off-by-one"],
        "prompt": (
            "counter.py has a helper count_up(n) that is supposed to return the list "
            "[1, 2, ..., n]. Right now n itself is always missing, so count_up(3) gives "
            "[1, 2]. Fix it without renaming the function or changing its signature."
        ),
        "seed": {
            "counter.py": '''"""Small helpers for numbering things."""


def count_up(n):
    """Return the list [1, 2, ..., n]."""
    return list(range(1, n))
''',
        },
        "hidden": {
            "test_counter.py": '''from counter import count_up


def test_counts_to_n_inclusive():
    assert count_up(3) == [1, 2, 3]


def test_large():
    assert count_up(10)[-1] == 10


def test_one():
    assert count_up(1) == [1]
''',
        },
    },
    {
        "id": "fix-mutable-default",
        "title": "Default list argument is shared between calls",
        "difficulty": "simple",
        "tags": ["bugfix", "python-semantics"],
        "prompt": (
            "bag.py lets you add items to a list, but each call seems to remember the "
            "previous one: add_item('a') then add_item('b') returns ['a', 'b'] instead of "
            "['b']. Callers that DO pass their own list must still have that exact list "
            "mutated in place, so do not just copy the input."
        ),
        "seed": {
            "bag.py": '''"""A little bag of items."""


def add_item(item, items=[]):
    items.append(item)
    return items


def add_many(new_items, items=[]):
    for item in new_items:
        items.append(item)
    return items
''',
        },
        "hidden": {
            "test_bag.py": '''from bag import add_item, add_many


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
''',
        },
    },
    {
        "id": "fix-truthy-string",
        "title": "is_even returns strings instead of booleans",
        "difficulty": "simple",
        "tags": ["bugfix", "types"],
        "prompt": (
            "Callers of parity.py keep taking the wrong branch. It turns out is_even "
            "returns the strings 'True' and 'False', and both are truthy, so "
            "if is_even(n) is always true. Make it return real booleans."
        ),
        "seed": {
            "parity.py": '''"""Number parity helpers."""


def is_even(n):
    if n % 2 == 0:
        return "True"
    return "False"
''',
        },
        "hidden": {
            "test_parity.py": '''from parity import is_even


def test_even_is_true():
    assert is_even(4) is True


def test_odd_is_false():
    assert is_even(5) is False


def test_zero_is_even():
    assert is_even(0) is True


def test_negative_is_handled():
    assert is_even(-3) is False


def test_not_a_string():
    assert not isinstance(is_even(2), str)
''',
        },
    },
    {
        "id": "fix-integer-division",
        "title": "average truncates and crashes on empty input",
        "difficulty": "simple",
        "tags": ["bugfix", "arithmetic"],
        "prompt": (
            "stats.py has an average() helper with two problems: it truncates the result "
            "(average([1, 2, 3, 4]) returns 2 instead of 2.5 because of integer division), "
            "and it blows up with ZeroDivisionError on an empty list instead of raising "
            "ValueError."
        ),
        "seed": {
            "stats.py": '''"""Basic descriptive statistics."""


def average(numbers):
    """Arithmetic mean. Raise ValueError for an empty input."""
    total = 0
    for number in numbers:
        total += number
    return total // len(numbers)
''',
        },
        "hidden": {
            "test_stats.py": '''import pytest

from stats import average


def test_mean_is_exact():
    assert average([1, 2, 3, 4]) == 2.5


def test_whole_number_mean():
    assert average([2, 4]) == 3


def test_single_value():
    assert average([5]) == 5


def test_floats():
    assert average([0.5, 0.25]) == 0.375


def test_empty_raises_value_error():
    with pytest.raises(ValueError):
        average([])
''',
        },
    },
    {
        "id": "fix-slice-bounds",
        "title": "first_and_last indexes one past the end",
        "difficulty": "simple",
        "tags": ["bugfix", "off-by-one", "sequences"],
        "prompt": (
            "ends.py exposes first_and_last(items) which should return a tuple of the "
            "first and last element. With [1, 2] it raises IndexError. An empty sequence "
            "should still raise IndexError."
        ),
        "seed": {
            "ends.py": '''"""Helpers for inspecting the ends of a sequence."""


def first_and_last(items):
    """Return (first, last) of a non-empty sequence."""
    return items[0], items[len(items)]
''',
        },
        "hidden": {
            "test_ends.py": '''import pytest

from ends import first_and_last


def test_two_items():
    assert first_and_last([1, 2]) == (1, 2)


def test_many_items():
    assert first_and_last("abcd") == ("a", "d")


def test_single_item():
    assert first_and_last(["only"]) == ("only", "only")


def test_empty_still_raises():
    with pytest.raises(IndexError):
        first_and_last([])
''',
        },
    },
    {
        "id": "fix-name-normalisation",
        "title": "normalize only lower-cases the name",
        "difficulty": "simple",
        "tags": ["bugfix", "strings"],
        "prompt": (
            "names.py is meant to turn raw user input into a display name: trimmed, with "
            "runs of whitespace collapsed to one space, and title-cased. Right now it just "
            "lower-cases everything, so '  ada lovelace ' comes out as '  ada lovelace '. "
            "Hyphenated names should title-case each part, so 'jean-luc picard' becomes "
            "'Jean-Luc Picard'."
        ),
        "seed": {
            "names.py": '''"""Display-name helpers."""


def normalize(name):
    """Trim, collapse inner whitespace, and title-case a name."""
    return name.lower()
''',
        },
        "hidden": {
            "test_names.py": '''from names import normalize


def test_trims_and_cases():
    assert normalize("  ada lovelace  ") == "Ada Lovelace"


def test_inner_whitespace_collapsed():
    assert normalize("ada    lovelace") == "Ada Lovelace"


def test_already_clean_is_unchanged():
    assert normalize("Ada Lovelace") == "Ada Lovelace"


def test_hyphenated_name():
    assert normalize("jean-luc picard") == "Jean-Luc Picard"


def test_tabs_and_newlines_count_as_whitespace():
    assert normalize("ada\\tlovelace") == "Ada Lovelace"
''',
        },
    },
    {
        "id": "fix-dict-key-error",
        "title": "count_words raises KeyError on the first occurrence",
        "difficulty": "simple",
        "tags": ["bugfix", "dicts"],
        "prompt": (
            "wordcount.py counts words case-insensitively, but it raises KeyError as soon "
            "as it meets a word it has not seen before. Make it work; the result should be "
            "a dict mapping lower-cased words to counts."
        ),
        "seed": {
            "wordcount.py": '''"""Word frequency counting."""


def count_words(text):
    """Count whitespace-separated words, case-insensitively."""
    counts = {}
    for word in text.split():
        key = word.lower()
        counts[key] = counts[key] + 1
    return counts
''',
        },
        "hidden": {
            "test_wordcount.py": '''from wordcount import count_words


def test_counts_repeats():
    assert count_words("a b a") == {"a": 2, "b": 1}


def test_case_insensitive():
    assert count_words("The the THE") == {"the": 3}


def test_empty_text():
    assert count_words("") == {}


def test_punctuation_is_part_of_the_word():
    assert count_words("hi hi!") == {"hi": 1, "hi!": 1}


def test_whitespace_variants():
    assert count_words("a\\tb\\na") == {"a": 2, "b": 1}
''',
        },
    },
    {
        "id": "fix-recursion-base-case",
        "title": "factorial never reaches its base case",
        "difficulty": "simple",
        "tags": ["bugfix", "recursion"],
        "prompt": (
            "maths.py has factorial(n) for n >= 0. Calling factorial(0) hangs and then "
            "raises RecursionError. Fix the base case so the whole documented range works."
        ),
        "seed": {
            "maths.py": '''"""Small integer maths helpers."""


def factorial(n):
    """n! for n >= 0."""
    if n == 1:
        return 1
    return n * factorial(n - 1)
''',
        },
        "hidden": {
            "test_maths.py": '''import pytest

from maths import factorial


def test_zero():
    assert factorial(0) == 1


def test_one():
    assert factorial(1) == 1


def test_three():
    assert factorial(3) == 6


def test_six():
    assert factorial(6) == 720


def test_negative_is_rejected():
    with pytest.raises(ValueError):
        factorial(-1)
''',
        },
    },
    {
        "id": "fix-sort-key",
        "title": "People are sorted by the string form of their age",
        "difficulty": "simple",
        "tags": ["bugfix", "sorting"],
        "prompt": (
            "people.py sorts a small table of people by age, oldest first. The order comes "
            "out as grace, alan, ada, which is wrong. Fix the sort so it uses the numeric "
            "age."
        ),
        "seed": {
            "people.py": '''"""A tiny in-memory table."""

PEOPLE = [
    {"name": "ada", "age": 36},
    {"name": "alan", "age": 41},
    {"name": "grace", "age": 9},
]


def by_age():
    """Names of PEOPLE, oldest first."""
    return [p["name"] for p in sorted(PEOPLE, key=lambda p: str(p["age"]), reverse=True)]
''',
        },
        "hidden": {
            "test_people.py": '''from people import by_age


def test_oldest_first():
    assert by_age() == ["alan", "ada", "grace"]


def test_returns_names_not_dicts():
    assert all(isinstance(name, str) for name in by_age())


def test_original_table_is_untouched():
    import people

    assert [p["name"] for p in people.PEOPLE] == ["ada", "alan", "grace"]
''',
        },
    },
    {
        "id": "fix-dedupe-order",
        "title": "unique() loses the original order",
        "difficulty": "simple",
        "tags": ["bugfix", "ordering"],
        "prompt": (
            "dedupe.py's unique() de-duplicates but the order comes out scrambled, because "
            "it goes through a set. It must keep the order in which items first appear."
        ),
        "seed": {
            "dedupe.py": '''"""De-duplication helpers."""


def unique(items):
    """De-duplicate, keeping the order of first appearance."""
    return list(set(items))
''',
        },
        "hidden": {
            "test_dedupe.py": '''from dedupe import unique


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
''',
        },
    },
    {
        "id": "fix-comparison-boundary",
        "title": "can_vote excludes people who are exactly 18",
        "difficulty": "simple",
        "tags": ["bugfix", "boundary"],
        "prompt": (
            "access.py has can_vote(age), documented as 'old enough to vote (18 or over)'. "
            "Someone who is exactly 18 is currently rejected. Fix the boundary. It should "
            "keep returning real booleans."
        ),
        "seed": {
            "access.py": '''"""Eligibility checks."""


def can_vote(age):
    """True when `age` is old enough to vote (18 or over)."""
    return age > 18
''',
        },
        "hidden": {
            "test_access.py": '''from access import can_vote


def test_exactly_eighteen_can_vote():
    assert can_vote(18) is True


def test_seventeen_cannot():
    assert can_vote(17) is False


def test_adult_can():
    assert can_vote(40) is True


def test_zero_cannot():
    assert can_vote(0) is False
''',
        },
    },
    {
        "id": "fix-missing-return",
        "title": "total_with_tax computes the total but returns None",
        "difficulty": "simple",
        "tags": ["bugfix", "return"],
        "prompt": (
            "pricing.py's total_with_tax(prices, rate) sums the prices and applies tax, but "
            "callers always get None back. An empty price list should give 0.0."
        ),
        "seed": {
            "pricing.py": '''"""Price calculations."""


def total_with_tax(prices, rate):
    """Sum of `prices` plus `rate` tax (0.2 means 20%)."""
    subtotal = 0.0
    for price in prices:
        subtotal += price
    taxed = subtotal * (1 + rate)
''',
        },
        "hidden": {
            "test_pricing.py": '''import pytest

from pricing import total_with_tax


def test_basic():
    assert total_with_tax([10.0, 5.0], 0.2) == pytest.approx(18.0)


def test_empty_is_zero():
    assert total_with_tax([], 0.5) == pytest.approx(0.0)


def test_no_tax():
    assert total_with_tax([1.0, 2.0], 0.0) == pytest.approx(3.0)


def test_returns_a_number_not_none():
    assert isinstance(total_with_tax([1.0], 0.0), float)
''',
        },
    },
    {
        "id": "fix-none-guard",
        "title": "initials crashes on a missing name",
        "difficulty": "simple",
        "tags": ["bugfix", "edge-cases"],
        "prompt": (
            "textutil.py's initials(name) turns a full name into initials: 'Ada Lovelace' "
            "becomes 'AL'. Its docstring says a blank or missing name yields an empty "
            "string, but passing None raises AttributeError today. Make the documented "
            "behaviour true, and make sure extra whitespace is handled."
        ),
        "seed": {
            "textutil.py": '''"""Text helpers."""


def initials(name):
    """Initials of a full name, e.g. "Ada Lovelace" -> "AL".

    A blank or missing name yields "".
    """
    parts = name.split()
    return "".join(part[0] for part in parts).upper()
''',
        },
        "hidden": {
            "test_textutil.py": '''from textutil import initials


def test_two_names():
    assert initials("Ada Lovelace") == "AL"


def test_blank_returns_empty():
    assert initials("") == ""


def test_none_returns_empty():
    assert initials(None) == ""


def test_extra_whitespace():
    assert initials("  grace   hopper ") == "GH"


def test_single_name():
    assert initials("ada") == "A"
''',
        },
    },
    {
        "id": "implement-median-of-three",
        "title": "Implement median_of_three",
        "difficulty": "simple",
        "tags": ["implementation", "algorithms"],
        "prompt": (
            "median.py has a placeholder median_of_three(a, b, c) that raises "
            "NotImplementedError. Implement it so it returns the middle value of the "
            "three, handling duplicates, floats and negative numbers. Do not use the "
            "statistics module."
        ),
        "seed": {
            "median.py": '''"""Middle-value helpers."""


def median_of_three(a, b, c):
    """Return the middle value of the three."""
    raise NotImplementedError
''',
        },
        "hidden": {
            "test_median.py": '''from median import median_of_three


def test_middle_wins():
    assert median_of_three(1, 2, 3) == 2


def test_unsorted_arguments():
    assert median_of_three(3, 1, 2) == 2


def test_middle_argument_is_the_median():
    assert median_of_three(2, 3, 1) == 2


def test_duplicates():
    assert median_of_three(5, 5, 1) == 5


def test_all_equal():
    assert median_of_three(4, 4, 4) == 4


def test_floats_and_negatives():
    assert median_of_three(-1.5, -2.0, -0.5) == -1.5
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
