"""One-off generator for the reference solutions.

Every task gets a ``solution/`` directory holding the files a correct answer
would produce. It is written next to ``workspace/`` and never seeded into the
agent's sandbox, so it doubles as documentation of the intended fix and as the
input to the task-set integrity check (seed fails, seed+solution passes).

If a task has no solution that makes its grader pass, the task is broken - that
is exactly what this file exists to prove.
"""

from __future__ import annotations

import shutil
from pathlib import Path

# This file lives in loca/eval/tasks/_generate/, so the task set is its
# grandparent directory.
TASKS_ROOT = Path(__file__).resolve().parent.parent

SOLUTIONS: dict[str, dict[str, str]] = {
    # ---- simple ---------------------------------------------------------
    "fix-off-by-one": {
        "counter.py": '''"""Small helpers for numbering things."""


def count_up(n):
    """Return the list [1, 2, ..., n]."""
    return list(range(1, n + 1))
''',
    },
    "fix-mutable-default": {
        "bag.py": '''"""A little bag of items."""


def add_item(item, items=None):
    if items is None:
        items = []
    items.append(item)
    return items


def add_many(new_items, items=None):
    if items is None:
        items = []
    for item in new_items:
        items.append(item)
    return items
''',
    },
    "fix-truthy-string": {
        "parity.py": '''"""Number parity helpers."""


def is_even(n):
    return n % 2 == 0
''',
    },
    "fix-integer-division": {
        "stats.py": '''"""Basic descriptive statistics."""


def average(numbers):
    """Arithmetic mean. Raise ValueError for an empty input."""
    if not numbers:
        raise ValueError("cannot average an empty sequence")
    total = 0
    for number in numbers:
        total += number
    return total / len(numbers)
''',
    },
    "fix-slice-bounds": {
        "ends.py": '''"""Helpers for inspecting the ends of a sequence."""


def first_and_last(items):
    """Return (first, last) of a non-empty sequence."""
    return items[0], items[-1]
''',
    },
    "fix-name-normalisation": {
        "names.py": '''"""Display-name helpers."""


def normalize(name):
    """Trim, collapse inner whitespace, and title-case a name."""
    return " ".join(name.split()).title()
''',
    },
    "fix-dict-key-error": {
        "wordcount.py": '''"""Word frequency counting."""


def count_words(text):
    """Count whitespace-separated words, case-insensitively."""
    counts = {}
    for word in text.split():
        key = word.lower()
        counts[key] = counts.get(key, 0) + 1
    return counts
''',
    },
    "fix-recursion-base-case": {
        "maths.py": '''"""Small integer maths helpers."""


def factorial(n):
    """n! for n >= 0."""
    if n < 0:
        raise ValueError("factorial is not defined for negative numbers")
    if n <= 1:
        return 1
    return n * factorial(n - 1)
''',
    },
    "fix-sort-key": {
        "people.py": '''"""A tiny in-memory table."""

PEOPLE = [
    {"name": "ada", "age": 36},
    {"name": "alan", "age": 41},
    {"name": "grace", "age": 9},
]


def by_age():
    """Names of PEOPLE, oldest first."""
    return [p["name"] for p in sorted(PEOPLE, key=lambda p: p["age"], reverse=True)]
''',
    },
    "fix-dedupe-order": {
        "dedupe.py": '''"""De-duplication helpers."""


def unique(items):
    """De-duplicate, keeping the order of first appearance."""
    return list(dict.fromkeys(items))
''',
    },
    "fix-comparison-boundary": {
        "access.py": '''"""Eligibility checks."""


def can_vote(age):
    """True when `age` is old enough to vote (18 or over)."""
    return age >= 18
''',
    },
    "fix-missing-return": {
        "pricing.py": '''"""Price calculations."""


def total_with_tax(prices, rate):
    """Sum of `prices` plus `rate` tax (0.2 means 20%)."""
    subtotal = 0.0
    for price in prices:
        subtotal += price
    taxed = subtotal * (1 + rate)
    return taxed
''',
    },
    "fix-none-guard": {
        "textutil.py": '''"""Text helpers."""


def initials(name):
    """Initials of a full name, e.g. "Ada Lovelace" -> "AL".

    A blank or missing name yields "".
    """
    if not name:
        return ""
    parts = name.split()
    return "".join(part[0] for part in parts).upper()
''',
    },
    "implement-median-of-three": {
        "median.py": '''"""Middle-value helpers."""


def median_of_three(a, b, c):
    """Return the middle value of the three."""
    return sorted((a, b, c))[1]
''',
    },
    # ---- medium ---------------------------------------------------------
    "wire-in-missing-import": {
        "shapes.py": '''"""Report helpers for shape measurements."""

from geometry import circle_area, circle_perimeter

LABELS = {"area": "area", "perimeter": "perimeter"}


def describe_circle(radius):
    """Return a one-line description of a circle's area and perimeter."""
    return (
        f"radius {radius}: {LABELS['area']} {circle_area(radius):.2f}, "
        f"{LABELS['perimeter']} {circle_perimeter(radius):.2f}"
    )
''',
    },
    "implement-slugify-and-wire": {
        "textutil.py": '''"""Text helpers."""


def slugify(text):
    """Turn a title into a URL slug.

    - Lower-case everything.
    - Keep ASCII letters and digits (a-z, 0-9).
    - Replace every other character with a hyphen.
    - Collapse runs of hyphens into one.
    - Strip leading and trailing hyphens.
    """
    pieces = []
    for char in text.lower():
        if char.isascii() and char.isalnum():
            pieces.append(char)
        else:
            pieces.append("-")
    slug = "".join(pieces)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")
''',
    },
    "add-dataclass-field": {
        "models.py": '''"""Domain models."""

from dataclasses import dataclass


@dataclass
class Account:
    id: int
    name: str
    email: str
''',
        "records.py": '''"""Builds model objects from raw rows."""

from models import Account


def build_accounts(rows):
    """Turn (id, name, email) rows into Account objects."""
    return [Account(id=row[0], name=row[1], email=row[2]) for row in rows]
''',
    },
    "fix-arity-mismatch": {
        "main.py": '''"""Renders a small statistics table."""

from report import format_row

ROWS = [("reads", 12), ("writes", 3)]
WIDTH = 9


def render():
    lines = [format_row(label, value) for label, value in ROWS]
    return chr(10).join(lines)
''',
    },
    "implement-plugin-registry": {
        "plugins.py": '''"""A tiny name -> callable registry."""

_REGISTRY = {}


def register(name, func):
    """Register `func` under `name`, replacing any previous entry."""
    _REGISTRY[name] = func


def get(name):
    """Return the callable registered under `name`.

    Raise KeyError when the name is unknown.
    """
    return _REGISTRY[name]


def names():
    """Registered names, sorted alphabetically."""
    return sorted(_REGISTRY)
''',
    },
    "move-module-and-update-callers": {
        "duration.py": '''"""Duration parsing."""

import re

_UNITS = {"h": 3600, "m": 60, "s": 1}
_PATTERN = re.compile(r"([0-9]+)([hms])")


def parse_duration(text):
    """Parse '1h30m' into seconds. Raise ValueError on anything unparsable."""
    if not text:
        raise ValueError("empty duration")
    matches = _PATTERN.findall(text)
    if not matches or "".join(n + u for n, u in matches) != text:
        raise ValueError(f"cannot parse {text!r}")
    return sum(int(n) * _UNITS[u] for n, u in matches)
''',
        "main.py": '''"""Reporting helpers."""

from duration import parse_duration


def total(texts):
    """Total seconds across a list of duration strings."""
    return sum(parse_duration(t) for t in texts)
''',
        "utils.py": '''"""Assorted helpers."""
''',
    },
    "add-validation-layer": {
        "validators.py": '''"""Value validators used by the config loader."""


def require_int(name, value, minimum=0):
    """Return `value` when it is an int >= `minimum`."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer, got {type(value).__name__}")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}, got {value}")
    return value


def require_positive(name, value):
    """Return `value` when it is a number greater than zero."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number, got {type(value).__name__}")
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero, got {value}")
    return value
''',
    },
    "add-cli-lines-only-flag": {
        "wc.py": '''"""Count lines, words and characters - a tiny wc clone."""

import argparse
from pathlib import Path


def counts(text):
    """Line, word and character counts for `text`."""
    return {
        "lines": len(text.splitlines()),
        "words": len(text.split()),
        "chars": len(text),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(prog="wc")
    parser.add_argument("path")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--words-only", action="store_true", help="print only the word count")
    group.add_argument("--lines-only", action="store_true", help="print only the line count")
    args = parser.parse_args(argv)

    text = Path(args.path).read_text(encoding="utf-8")
    result = counts(text)
    if args.words_only:
        print(result["words"])
    elif args.lines_only:
        print(result["lines"])
    else:
        print(f"{result['lines']} {result['words']} {result['chars']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
    },
    "fix-page-boundary": {
        "pager.py": '''"""Slice bounds for paginated output."""


def page_bounds(total, page, size):
    """Return (start, end) slice bounds for 1-based `page`.

    Python slicing tolerates bounds past the end of a sequence, so a page
    beyond the last one simply yields an empty slice.
    """
    start = (page - 1) * size
    return start, start + size
''',
    },
    "implement-retry-helper": {
        "retry.py": '''"""A tiny retry helper."""

import time


def call_with_retry(func, times, delay=0.0, sleep=None):
    """Call `func()` until it stops raising, up to `times` attempts."""
    if times < 1:
        raise ValueError("times must be at least 1")
    sleeper = sleep if sleep is not None else time.sleep
    last: Exception | None = None
    for attempt in range(times):
        try:
            return func()
        except Exception as exc:
            last = exc
            if attempt < times - 1:
                sleeper(delay)
    raise last
''',
    },
    "rename-and-update-callers": {
        "calc.py": '''"""Totalling helpers."""


def total(items):
    """Sum of `items`."""
    return sum(items)
''',
        "a.py": '''"""First consumer of the totalling helper."""

from calc import total


def report_a(items):
    return total(items)
''',
        "b.py": '''"""Second consumer of the totalling helper."""

from calc import total

OFFSET = 0


def report_b(items):
    return total([item + OFFSET for item in items])
''',
    },
    "implement-log-parser": {
        "logparse.py": '''"""Parsing for the application log format."""

import re

_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}")
_LEVEL = re.compile(r"[A-Za-z]+")


def parse_line(line):
    """Parse one log line: '2024-05-01T10:00:00 LEVEL message'."""
    parts = line.split(" ", 2)
    if len(parts) < 2:
        raise ValueError(f"not a log line: {line!r}")
    timestamp, level = parts[0], parts[1]
    if not _TIMESTAMP.fullmatch(timestamp) or not _LEVEL.fullmatch(level):
        raise ValueError(f"not a log line: {line!r}")
    message = parts[2] if len(parts) > 2 else ""
    return {"timestamp": timestamp, "level": level.upper(), "message": message}
''',
    },
    # ---- hard -----------------------------------------------------------
    "impl-lru-cache": {
        "cache.py": '''"""A fixed-capacity cache with least-recently-used eviction."""

from collections import OrderedDict


class LRUCache:
    """Capacity-bounded cache."""

    def __init__(self, capacity):
        self.capacity = capacity
        self._entries = OrderedDict()

    def get(self, key):
        if key not in self._entries:
            return None
        self._entries.move_to_end(key)
        return self._entries[key]

    def put(self, key, value):
        if key in self._entries:
            self._entries.move_to_end(key)
        self._entries[key] = value
        while len(self._entries) > self.capacity:
            self._entries.popitem(last=False)

    def __len__(self):
        return len(self._entries)
''',
    },
    "impl-topological-sort": {
        "toposort.py": '''"""Topological sorting."""


def toposort(graph):
    """Topologically sort a mapping of {node: [dependencies]}."""
    nodes = set(graph)
    for dependencies in graph.values():
        nodes.update(dependencies)

    pending = {node: set(graph.get(node, [])) for node in nodes}
    result = []
    while pending:
        ready = sorted(node for node, deps in pending.items() if not deps)
        if not ready:
            raise ValueError("graph contains a cycle")
        for node in ready:
            result.append(node)
            del pending[node]
        for deps in pending.values():
            deps.difference_update(ready)
    return result
''',
    },
    "impl-csv-line-parser": {
        "csvline.py": '''"""A single-line CSV field splitter."""


def parse_line(line):
    """Split one CSV line into a list of fields."""
    fields = []
    index = 0
    length = len(line)
    while True:
        if index < length and line[index] == '"':
            index += 1
            buffer = []
            while index < length:
                char = line[index]
                if char == '"':
                    if index + 1 < length and line[index + 1] == '"':
                        buffer.append('"')
                        index += 2
                        continue
                    index += 1
                    break
                buffer.append(char)
                index += 1
            fields.append("".join(buffer))
        else:
            start = index
            while index < length and line[index] != ",":
                index += 1
            fields.append(line[start:index])
        if index < length and line[index] == ",":
            index += 1
            continue
        break
    return fields
''',
    },
    "impl-roman-numerals": {
        "roman.py": '''"""Roman numeral conversion."""

MIN_VALUE = 1
MAX_VALUE = 3999

_TABLE = [
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
]

_DIGITS = set("MDCLXVI")


def to_roman(value):
    """Convert an integer in 1..3999 to a Roman numeral."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("value must be an integer")
    if value < MIN_VALUE or value > MAX_VALUE:
        raise ValueError(f"value must be in {MIN_VALUE}..{MAX_VALUE}")
    pieces = []
    remaining = value
    for amount, numeral in _TABLE:
        while remaining >= amount:
            pieces.append(numeral)
            remaining -= amount
    return "".join(pieces)


def from_roman(text):
    """Parse a canonical upper-case Roman numeral."""
    if not isinstance(text, str) or not text:
        raise ValueError("empty numeral")
    if text != text.upper() or any(char not in _DIGITS for char in text):
        raise ValueError(f"invalid numeral {text!r}")
    value = 0
    index = 0
    for amount, numeral in _TABLE:
        while text.startswith(numeral, index):
            value += amount
            index += len(numeral)
    if index != len(text) or to_roman(value) != text:
        raise ValueError(f"non-canonical numeral {text!r}")
    return value
''',
    },
    "impl-expression-evaluator": {
        "expr.py": '''"""A small arithmetic expression evaluator."""


class _Parser:
    def __init__(self, text):
        self.chars = [char for char in text if not char.isspace()]
        self.position = 0

    def peek(self):
        if self.position < len(self.chars):
            return self.chars[self.position]
        return None

    def parse_expression(self):
        value = self.parse_term()
        while self.peek() in ("+", "-"):
            operator = self.chars[self.position]
            self.position += 1
            right = self.parse_term()
            value = value + right if operator == "+" else value - right
        return value

    def parse_term(self):
        value = self.parse_factor()
        while self.peek() in ("*", "/"):
            operator = self.chars[self.position]
            self.position += 1
            right = self.parse_factor()
            value = value * right if operator == "*" else int(value / right)
        return value

    def parse_factor(self):
        char = self.peek()
        if char is None:
            raise ValueError("unexpected end of expression")
        if char == "(":
            self.position += 1
            value = self.parse_expression()
            if self.peek() != ")":
                raise ValueError("unbalanced parentheses")
            self.position += 1
            return value
        if char.isdigit():
            start = self.position
            while self.peek() is not None and self.peek().isdigit():
                self.position += 1
            return int("".join(self.chars[start : self.position]))
        raise ValueError(f"unexpected character {char!r}")


def evaluate(text):
    """Evaluate an arithmetic expression over integers."""
    parser = _Parser(text)
    if not parser.chars:
        raise ValueError("empty expression")
    value = parser.parse_expression()
    if parser.position != len(parser.chars):
        raise ValueError("unexpected trailing input")
    return value
''',
    },
    "impl-merge-intervals": {
        "intervals.py": '''"""Interval merging."""


def merge(intervals):
    """Merge overlapping or touching closed intervals."""
    if not intervals:
        return []
    ordered = sorted((list(pair) for pair in intervals), key=lambda pair: (pair[0], pair[1]))
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last = merged[-1]
        if start <= last[1]:
            last[1] = max(last[1], end)
        else:
            merged.append([start, end])
    return merged
''',
    },
    "impl-word-wrap": {
        "wrap.py": '''"""Greedy word wrapping."""


def wrap(text, width):
    """Wrap `text` into lines of at most `width` characters."""
    if width < 1:
        raise ValueError("width must be at least 1")
    lines = []
    for paragraph in text.split(chr(10)):
        current = ""
        for word in paragraph.split():
            if not current:
                current = word
            elif len(current) + 1 + len(word) <= width:
                current = current + " " + word
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines
''',
    },
    "impl-json-pointer": {
        "jsonptr.py": '''"""RFC 6901 JSON Pointer resolution."""


def _decode(token):
    """Unescape a reference token. Order matters: ~1 before ~0."""
    return token.replace("~1", "/").replace("~0", "~")


def resolve(document, pointer):
    """Resolve a JSON Pointer against a parsed JSON document."""
    if pointer == "":
        return document
    if not pointer.startswith("/"):
        raise ValueError(f"invalid pointer {pointer!r}")
    current = document
    for token in pointer[1:].split("/"):
        key = _decode(token)
        if isinstance(current, dict):
            if key not in current:
                raise KeyError(key)
            current = current[key]
        elif isinstance(current, list):
            if not key.isdigit() or (len(key) > 1 and key[0] == "0"):
                raise IndexError(key)
            index = int(key)
            if index >= len(current):
                raise IndexError(key)
            current = current[index]
        else:
            raise KeyError(key)
    return current
''',
    },
    "impl-dijkstra": {
        "graph.py": '''"""Shortest paths over a directed weighted graph."""

import heapq
import math


def shortest_path(edges, start, goal):
    """Dijkstra over the edges given as (source, target, weight) triples."""
    graph = {}
    for source, target, weight in edges:
        graph.setdefault(source, []).append((target, weight))
        graph.setdefault(target, [])

    if start == goal:
        return 0, [start]

    best = {start: 0}
    previous = {}
    queue = [(0, start)]
    while queue:
        cost, node = heapq.heappop(queue)
        if cost > best.get(node, math.inf):
            continue
        for target, weight in graph.get(node, []):
            candidate = cost + weight
            if candidate < best.get(target, math.inf):
                best[target] = candidate
                previous[target] = node
                heapq.heappush(queue, (candidate, target))

    if goal not in best:
        return math.inf, []
    path = [goal]
    while path[-1] != start:
        path.append(previous[path[-1]])
    path.reverse()
    return best[goal], path
''',
    },
    "impl-sliding-window-limiter": {
        "limiter.py": '''"""A sliding-window rate limiter."""


class SlidingWindowLimiter:
    """Allow at most `limit` events in any `window`-second span."""

    def __init__(self, limit, window):
        self.limit = limit
        self.window = window
        self._events = []

    def allow(self, now):
        self._events = [t for t in self._events if now - t < self.window]
        if len(self._events) >= self.limit:
            return False
        self._events.append(now)
        return True
''',
    },
}


def main() -> None:
    missing = []
    for task_id, files in sorted(SOLUTIONS.items()):
        root = TASKS_ROOT / task_id
        if not root.is_dir():
            missing.append(task_id)
            continue
        target = root / "solution"
        if target.exists():
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for name, content in files.items():
            (target / name).write_text(content, encoding="utf-8", newline="\n")
        print(f"solved {task_id}")

    if missing:
        raise SystemExit(f"unknown task ids: {missing}")


if __name__ == "__main__":
    main()
