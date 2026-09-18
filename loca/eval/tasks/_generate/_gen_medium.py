"""One-off generator for the MEDIUM tier: cross-file work.

Same contract as _gen_simple.py. These tasks all span at least two modules, so
a fix that only touches one file will fail the grader.
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
        "id": "wire-in-missing-import",
        "title": "shapes.py uses geometry helpers it never imported",
        "difficulty": "medium",
        "tags": ["bugfix", "imports"],
        "prompt": (
            "shapes.py builds a one-line description of a circle from geometry.py, but "
            "calling describe_circle(1) raises NameError. Wire up the missing import so "
            "the two modules work together. Do not move the maths into shapes.py - the "
            "helpers belong in geometry.py."
        ),
        "seed": {
            "geometry.py": '''"""Circle geometry."""

import math


def circle_area(radius):
    if radius < 0:
        raise ValueError("radius must not be negative")
    return math.pi * radius**2


def circle_perimeter(radius):
    if radius < 0:
        raise ValueError("radius must not be negative")
    return 2 * math.pi * radius
''',
            "shapes.py": '''"""Report helpers for shape measurements."""

LABELS = {"area": "area", "perimeter": "perimeter"}


def describe_circle(radius):
    """Return a one-line description of a circle's area and perimeter."""
    return (
        f"radius {radius}: {LABELS['area']} {circle_area(radius):.2f}, "
        f"{LABELS['perimeter']} {circle_perimeter(radius):.2f}"
    )
''',
        },
        "hidden": {
            "test_shapes.py": '''import pytest

from shapes import describe_circle


def test_describes_both_measurements():
    assert describe_circle(1) == "radius 1: area 3.14, perimeter 6.28"


def test_two_decimal_places():
    assert describe_circle(2) == "radius 2: area 12.57, perimeter 12.57"


def test_negative_radius_propagates_value_error():
    with pytest.raises(ValueError):
        describe_circle(-1)
''',
        },
    },
    {
        "id": "implement-slugify-and-wire",
        "title": "Implement slugify, which blog.py already depends on",
        "difficulty": "medium",
        "tags": ["implementation", "strings", "cross-file"],
        "prompt": (
            "textutil.py declares slugify(text) but raises NotImplementedError, and "
            "blog.py already calls it to build post URLs. Implement it to the spec in its "
            "docstring. The rule that trips people up: only ASCII letters and digits "
            "survive, so accented characters are dropped rather than transliterated."
        ),
        "seed": {
            "textutil.py": '''"""Text helpers."""


def slugify(text):
    """Turn a title into a URL slug.

    - Lower-case everything.
    - Keep ASCII letters and digits (a-z, 0-9).
    - Replace every other character with a hyphen.
    - Collapse runs of hyphens into one.
    - Strip leading and trailing hyphens.

    "Hello,  World!" -> "hello-world"
    "  A_B  "        -> "a-b"
    "Study in C++"   -> "study-in-c"
    "Aero 2024"      -> "aero-2024"
    """
    raise NotImplementedError
''',
            "blog.py": '''"""Blog URL helpers."""

from textutil import slugify


def post_url(title, base="https://example.com/posts"):
    """Full URL for a post with the given title."""
    return f"{base}/{slugify(title)}"
''',
        },
        "hidden": {
            "test_slugify.py": '''import pytest

from blog import post_url
from textutil import slugify

CASES = [
    ("Hello,  World!", "hello-world"),
    ("  A_B  ", "a-b"),
    ("Study in C++", "study-in-c"),
    ("Aero 2024", "aero-2024"),
    ("--already--slugged--", "already-slugged"),
    ("???", ""),
]


def test_slugify_cases():
    for raw, expected in CASES:
        assert slugify(raw) == expected, raw


def test_post_url_uses_the_slug():
    assert post_url("Hello, World!") == "https://example.com/posts/hello-world"


def test_post_url_accepts_a_custom_base():
    assert post_url("Hi There", base="https://x.dev/p") == "https://x.dev/p/hi-there"
''',
        },
    },
    {
        "id": "add-dataclass-field",
        "title": "Add an email field to Account and update its callers",
        "difficulty": "medium",
        "tags": ["refactor", "dataclasses", "call-sites"],
        "prompt": (
            "Account in models.py needs a new required field, email, positioned after name. "
            "records.py builds Account objects from rows and those rows now carry three "
            "values: (id, name, email). Update both files so nothing is left behind - and "
            "keep the field required, do not default it to an empty string."
        ),
        "seed": {
            "models.py": '''"""Domain models."""

from dataclasses import dataclass


@dataclass
class Account:
    id: int
    name: str
''',
            "records.py": '''"""Builds model objects from raw rows."""

from models import Account


def build_accounts(rows):
    """Turn (id, name) rows into Account objects."""
    return [Account(id=row[0], name=row[1]) for row in rows]
''',
        },
        "hidden": {
            "test_accounts.py": '''import pytest

from models import Account
from records import build_accounts


def test_account_carries_email():
    account = Account(id=1, name="ada", email="ada@example.com")
    assert account.email == "ada@example.com"


def test_positional_order_is_id_name_email():
    account = Account(2, "alan", "alan@example.com")
    assert account.email == "alan@example.com"
    assert account.name == "alan"


def test_build_accounts_keeps_every_field():
    accounts = build_accounts([(1, "ada", "ada@example.com"), (2, "alan", "alan@example.com")])
    assert [a.email for a in accounts] == ["ada@example.com", "alan@example.com"]
    assert [a.name for a in accounts] == ["ada", "alan"]


def test_email_is_required_not_defaulted():
    with pytest.raises(TypeError):
        Account(id=3, name="grace")


def test_repr_mentions_email():
    assert "ada@example.com" in repr(Account(1, "ada", "ada@example.com"))
''',
        },
    },
    {
        "id": "fix-arity-mismatch",
        "title": "main.py calls format_row with one argument too many",
        "difficulty": "medium",
        "tags": ["bugfix", "interfaces", "cross-file"],
        "prompt": (
            "render() in main.py crashes with TypeError because it passes three arguments "
            "to report.format_row, which only takes two. report.format_row lays out two "
            "9-character columns (label left-aligned, value right-aligned), and every "
            "rendered line must stay 18 characters wide. Fix it on whichever side is right."
        ),
        "seed": {
            "report.py": '''"""Fixed-width row formatting."""


def format_row(label, value):
    """One row: two 9-character columns, label left- and value right-aligned."""
    return f"{label:<9}{value:>9}"
''',
            "main.py": '''"""Renders a small statistics table."""

from report import format_row

ROWS = [("reads", 12), ("writes", 3)]
WIDTH = 9


def render():
    lines = [format_row(label, value, WIDTH) for label, value in ROWS]
    return chr(10).join(lines)
''',
        },
        "hidden": {
            "test_render.py": '''from main import render
from report import format_row


def test_renders_two_lines():
    assert len(render().splitlines()) == 2


def test_every_line_is_eighteen_wide():
    for line in render().splitlines():
        assert len(line) == 18


def test_labels_and_values_are_present():
    lines = render().splitlines()
    assert lines[0].startswith("reads")
    assert lines[0].endswith("12")
    assert lines[1].startswith("writes")
    assert lines[1].endswith("3")


def test_format_row_contract():
    assert format_row("a", 1) == "a" + " " * 8 + " " * 8 + "1"
    assert len(format_row("a", 1)) == 18
''',
        },
    },
    {
        "id": "implement-plugin-registry",
        "title": "Implement the plugin registry that app.py uses",
        "difficulty": "medium",
        "tags": ["implementation", "registry", "cross-file"],
        "prompt": (
            "plugins.py is a stub: register/get/names all raise NotImplementedError, and "
            "app.py already depends on them. Implement the module to the contract in its "
            "docstrings. Registering the same name twice should overwrite the previous "
            "entry rather than fail."
        ),
        "seed": {
            "plugins.py": '''"""A tiny name -> callable registry."""

_REGISTRY = {}


def register(name, func):
    """Register `func` under `name`, replacing any previous entry."""
    raise NotImplementedError


def get(name):
    """Return the callable registered under `name`.

    Raise KeyError when the name is unknown.
    """
    raise NotImplementedError


def names():
    """Registered names, sorted alphabetically."""
    raise NotImplementedError
''',
            "app.py": '''"""A small app built on the plugin registry."""

from plugins import get, names, register


def shout(text):
    return text.upper()


def whisper(text):
    return text.lower()


def build():
    """Register the built-in plugins and return the sorted names."""
    register("shout", shout)
    register("whisper", whisper)
    return names()


def apply(name, text):
    """Run the plugin called `name` on `text`."""
    return get(name)(text)
''',
        },
        "hidden": {
            "test_plugins.py": '''import pytest

from app import apply, build
from plugins import get, names, register


def test_build_returns_sorted_names():
    assert build() == ["shout", "whisper"]


def test_apply_dispatches():
    build()
    assert apply("shout", "hi") == "HI"
    assert apply("whisper", "HI") == "hi"


def test_unknown_name_raises_keyerror():
    build()
    with pytest.raises(KeyError):
        apply("nope", "hi")


def test_registering_twice_overwrites():
    register("twice", lambda text: text)
    register("twice", lambda text: text + "!")
    assert get("twice")("x") == "x!"


def test_names_reflects_latest_registrations():
    register("zzz", lambda text: text)
    assert names() == sorted(names())
    assert "zzz" in names()
''',
        },
    },
    {
        "id": "move-module-and-update-callers",
        "title": "Move parse_duration out of utils.py into its own module",
        "difficulty": "medium",
        "tags": ["refactor", "cross-file"],
        "prompt": (
            "utils.py has grown a duration parser that does not belong there. Move "
            "parse_duration into a new module duration.py, and update main.py to import it "
            "from the new home. duration.py must own the code - re-exporting it from utils "
            "is not a move. The parsing behaviour itself must not change."
        ),
        "seed": {
            "utils.py": '''"""Assorted helpers."""

import re

_UNITS = {"h": 3600, "m": 60, "s": 1}
_PATTERN = re.compile(r"(\\d+)([hms])")


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

from utils import parse_duration


def total(texts):
    """Total seconds across a list of duration strings."""
    return sum(parse_duration(t) for t in texts)
''',
        },
        "hidden": {
            "test_duration.py": '''from pathlib import Path

import pytest

from duration import parse_duration
from main import total


def test_parser_lives_in_duration():
    assert parse_duration("30s") == 30
    assert parse_duration("1h30m") == 5400
    assert parse_duration("2m15s") == 135


def test_parsing_behaviour_is_unchanged():
    with pytest.raises(ValueError):
        parse_duration("")
    with pytest.raises(ValueError):
        parse_duration("abc")
    with pytest.raises(ValueError):
        parse_duration("1x")


def test_caller_was_updated():
    assert total(["1m", "30s"]) == 90


def test_duration_is_not_a_re_export():
    source = (Path(__file__).resolve().parent / "duration.py").read_text(encoding="utf-8")
    assert "utils" not in source
''',
        },
    },
    {
        "id": "add-validation-layer",
        "title": "Implement the validators config.py relies on",
        "difficulty": "medium",
        "tags": ["implementation", "validation", "cross-file"],
        "prompt": (
            "validators.py has two stubs and config.py already calls them to check user "
            "input. Implement both to the contract in their docstrings. Note the trap: "
            "True and False are instances of int in Python, but they are not acceptable "
            "retry counts."
        ),
        "seed": {
            "validators.py": '''"""Value validators used by the config loader."""


def require_int(name, value, minimum=0):
    """Return `value` when it is an int >= `minimum`.

    Otherwise raise ValueError whose message mentions `name`. A bool is NOT
    accepted, even though bool subclasses int.
    """
    raise NotImplementedError


def require_positive(name, value):
    """Return `value` when it is a number greater than zero.

    Otherwise raise ValueError whose message mentions `name`. A bool is NOT
    accepted.
    """
    raise NotImplementedError
''',
            "config.py": '''"""Config loading with validation."""

from validators import require_int, require_positive

DEFAULTS = {"retries": 2, "timeout": 30}


def load(raw):
    """Merge `raw` over DEFAULTS, validating the two known keys."""
    merged = {**DEFAULTS, **raw}
    require_int("retries", merged["retries"])
    require_positive("timeout", merged["timeout"])
    return merged
''',
        },
        "hidden": {
            "test_config.py": '''import pytest

from config import load
from validators import require_int, require_positive


def test_defaults():
    assert load({}) == {"retries": 2, "timeout": 30}


def test_overrides():
    assert load({"retries": 5, "timeout": 1.5}) == {"retries": 5, "timeout": 1.5}


def test_zero_retries_is_allowed():
    assert load({"retries": 0})["retries"] == 0


def test_negative_retries_rejected():
    with pytest.raises(ValueError, match="retries"):
        load({"retries": -1})


def test_non_integer_retries_rejected():
    with pytest.raises(ValueError, match="retries"):
        load({"retries": 1.5})


def test_bool_is_not_an_int():
    with pytest.raises(ValueError, match="retries"):
        load({"retries": True})


def test_zero_timeout_rejected():
    with pytest.raises(ValueError, match="timeout"):
        load({"timeout": 0})


def test_negative_timeout_rejected():
    with pytest.raises(ValueError, match="timeout"):
        load({"timeout": -5})


def test_non_numeric_timeout_rejected():
    with pytest.raises(ValueError, match="timeout"):
        load({"timeout": "30"})


def test_validators_return_the_value():
    assert require_int("n", 3, minimum=1) == 3
    assert require_positive("t", 0.5) == 0.5
''',
        },
    },
    {
        "id": "add-cli-lines-only-flag",
        "title": "Add a --lines-only flag to the wc clone",
        "difficulty": "medium",
        "tags": ["feature", "cli", "argparse"],
        "prompt": (
            "wc.py is a small clone of the Unix wc command. It already supports "
            "--words-only. Add --lines-only so it prints just the line count, and make the "
            "two flags mutually exclusive: passing both must fail with a non-zero exit "
            "code rather than silently picking one. The default output stays "
            "'<lines> <words> <chars>'."
        ),
        "seed": {
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
    parser.add_argument("--words-only", action="store_true", help="print only the word count")
    args = parser.parse_args(argv)

    text = Path(args.path).read_text(encoding="utf-8")
    result = counts(text)
    if args.words_only:
        print(result["words"])
    else:
        print(f"{result['lines']} {result['words']} {result['chars']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
''',
            "sample.txt": "one two\nthree\n",
        },
        "hidden": {
            "test_wc_cli.py": '''import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLE = str(HERE / "sample.txt")


def run_wc(*args):
    return subprocess.run(
        [sys.executable, "wc.py", *args],
        cwd=HERE,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


def test_default_prints_all_three():
    result = run_wc(SAMPLE)
    assert result.returncode == 0
    assert result.stdout.strip() == "2 3 14"


def test_words_only():
    assert run_wc(SAMPLE, "--words-only").stdout.strip() == "3"


def test_lines_only():
    result = run_wc(SAMPLE, "--lines-only")
    assert result.returncode == 0
    assert result.stdout.strip() == "2"


def test_flags_are_mutually_exclusive():
    result = run_wc(SAMPLE, "--lines-only", "--words-only")
    assert result.returncode != 0


def test_counts_helper_is_unchanged():
    import wc

    assert wc.counts("a b\\nc\\n") == {"lines": 2, "words": 3, "chars": 6}
''',
        },
    },
    {
        "id": "fix-page-boundary",
        "title": "Pagination is off by one page",
        "difficulty": "medium",
        "tags": ["bugfix", "off-by-one", "cross-file"],
        "prompt": (
            "The pager in formatter.py returns the wrong slice of ITEMS - page(1) gives the "
            "second page's items instead of the first. pager.page_bounds documents itself "
            "as taking a 1-based page number, so fix whichever side is actually wrong. A "
            "page past the end must return an empty list, not raise."
        ),
        "seed": {
            "pager.py": '''"""Slice bounds for paginated output."""


def page_bounds(total, page, size):
    """Return (start, end) slice bounds for 1-based `page`.

    Python slicing tolerates bounds past the end of a sequence, so a page
    beyond the last one simply yields an empty slice.
    """
    start = page * size
    return start, start + size
''',
            "formatter.py": '''"""Paginated rendering."""

from pager import page_bounds

ITEMS = list(range(1, 26))


def page(page_number, size=10):
    """Items on 1-based `page_number`."""
    start, end = page_bounds(len(ITEMS), page_number, size)
    return ITEMS[start:end]
''',
        },
        "hidden": {
            "test_pager.py": '''from formatter import ITEMS, page
from pager import page_bounds


def test_first_page():
    assert page(1) == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]


def test_second_page():
    assert page(2) == [11, 12, 13, 14, 15, 16, 17, 18, 19, 20]


def test_last_partial_page():
    assert page(3) == [21, 22, 23, 24, 25]


def test_beyond_the_end_is_empty():
    assert page(4) == []


def test_custom_size():
    assert page(1, size=5) == [1, 2, 3, 4, 5]
    assert page(5, size=5) == [21, 22, 23, 24, 25]


def test_bounds_are_consistent_with_page():
    for number in range(1, 6):
        start, end = page_bounds(len(ITEMS), number, 10)
        assert ITEMS[start:end] == page(number)
''',
        },
    },
    {
        "id": "implement-retry-helper",
        "title": "Implement call_with_retry",
        "difficulty": "medium",
        "tags": ["implementation", "retries"],
        "prompt": (
            "retry.py declares call_with_retry(func, times, delay=0.0, sleep=None) but "
            "raises NotImplementedError. Implement it to the docstring: it returns the "
            "first successful result, re-raises the last exception once every attempt has "
            "failed, and waits between attempts but never after the final one. Tests need "
            "to inject `sleep` so they do not actually wait."
        ),
        "seed": {
            "retry.py": '''"""A tiny retry helper."""


def call_with_retry(func, times, delay=0.0, sleep=None):
    """Call `func()` until it stops raising, up to `times` attempts.

    - Return the first successful result.
    - Re-raise the last exception when every attempt fails.
    - Call sleep(delay) between attempts, but never after the last one.
    - Raise ValueError when `times` is less than 1.
    - `sleep` defaults to time.sleep, but must be injectable for tests.
    """
    raise NotImplementedError
''',
        },
        "hidden": {
            "test_retry.py": '''import pytest

from retry import call_with_retry


class Boom(Exception):
    pass


def test_returns_the_first_success():
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise Boom("not yet")
        return "ok"

    assert call_with_retry(flaky, times=5) == "ok"
    assert len(calls) == 3


def test_succeeds_without_retrying_when_the_first_call_works():
    calls = []

    def fine():
        calls.append(1)
        return 42

    assert call_with_retry(fine, times=3) == 42
    assert len(calls) == 1


def test_reraises_the_last_error():
    def always():
        raise Boom("always")

    with pytest.raises(Boom):
        call_with_retry(always, times=3)


def test_gives_up_after_exactly_times_attempts():
    calls = []

    def always():
        calls.append(1)
        raise Boom("always")

    with pytest.raises(Boom):
        call_with_retry(always, times=4)
    assert len(calls) == 4


def test_sleeps_only_between_attempts():
    slept = []

    def always():
        raise Boom("x")

    with pytest.raises(Boom):
        call_with_retry(always, times=3, delay=0.5, sleep=slept.append)

    assert slept == [0.5, 0.5]


def test_rejects_zero_times():
    with pytest.raises(ValueError):
        call_with_retry(lambda: 1, times=0)


def test_rejects_negative_times():
    with pytest.raises(ValueError):
        call_with_retry(lambda: 1, times=-2)


def test_default_sleep_is_not_used_when_no_delay():
    slept = []

    def fine():
        return 1

    assert call_with_retry(fine, times=2, sleep=slept.append) == 1
    assert slept == []
''',
        },
    },
    {
        "id": "rename-and-update-callers",
        "title": "Rename calc_total to total everywhere",
        "difficulty": "medium",
        "tags": ["refactor", "rename", "call-sites"],
        "prompt": (
            "calc.py's calc_total is being renamed to total. Rename the function and update "
            "every caller in the project - a.py and b.py both import it. When you are done "
            "the old name must be gone from calc, not kept around as an alias."
        ),
        "seed": {
            "calc.py": '''"""Totalling helpers."""


def calc_total(items):
    """Sum of `items`."""
    return sum(items)
''',
            "a.py": '''"""First consumer of the totalling helper."""

from calc import calc_total


def report_a(items):
    return calc_total(items)
''',
            "b.py": '''"""Second consumer of the totalling helper."""

from calc import calc_total

OFFSET = 0


def report_b(items):
    return calc_total([item + OFFSET for item in items])
''',
        },
        "hidden": {
            "test_rename.py": '''import pytest

import calc
from a import report_a
from b import report_b


def test_new_name_works():
    assert calc.total([1, 2, 3]) == 6


def test_first_caller_was_updated():
    assert report_a([1, 2]) == 3


def test_second_caller_was_updated():
    assert report_b([4, 5]) == 9


def test_old_name_is_gone():
    assert not hasattr(calc, "calc_total")


def test_no_module_still_mentions_the_old_name():
    from pathlib import Path

    here = Path(__file__).resolve().parent
    for name in ("calc.py", "a.py", "b.py"):
        source = (here / name).read_text(encoding="utf-8")
        assert "calc_total" not in source, name
''',
        },
    },
    {
        "id": "implement-log-parser",
        "title": "Implement the log line parser used by summary.py",
        "difficulty": "medium",
        "tags": ["implementation", "parsing", "cross-file"],
        "prompt": (
            "logparse.py declares parse_line() but raises NotImplementedError, and "
            "summary.py already uses it to count log levels. Implement it to the docstring: "
            "both the timestamp and the level field are validated, and the message may "
            "itself contain spaces, so split off the first two fields and treat the rest as "
            "the message."
        ),
        "seed": {
            "logparse.py": '''"""Parsing for the application log format."""


def parse_line(line):
    """Parse one log line: '2024-05-01T10:00:00 LEVEL message'.

    The first field must be a timestamp of the form YYYY-MM-DDTHH:MM:SS
    (digits and separators only) and the second must be letters only.

    Return a dict with keys:
      - timestamp: the first field, unchanged
      - level: the second field, upper-cased
      - message: everything after the second field, with inner spacing kept,
        or "" when the line ends after the level

    Raise ValueError when either field is missing or malformed.
    """
    raise NotImplementedError
''',
            "summary.py": '''"""Log summarising."""

from collections import Counter

from logparse import parse_line


def count_levels(text):
    """Count log levels across a multi-line blob, skipping blank lines."""
    counter = Counter()
    for line in text.splitlines():
        if not line.strip():
            continue
        counter[parse_line(line)["level"]] += 1
    return dict(counter)
''',
        },
        "hidden": {
            "test_logparse.py": '''import pytest

from logparse import parse_line
from summary import count_levels

LOG = """2024-05-01T10:00:00 INFO started
2024-05-01T10:00:01 WARN slow call
2024-05-01T10:00:02 info done
"""


def test_parses_a_line():
    assert parse_line("2024-05-01T10:00:00 INFO started") == {
        "timestamp": "2024-05-01T10:00:00",
        "level": "INFO",
        "message": "started",
    }


def test_message_keeps_inner_spaces():
    assert parse_line("2024-05-01T10:00:01 WARN slow   call")["message"] == "slow   call"


def test_level_is_upper_cased():
    assert parse_line("2024-05-01T10:00:02 info done")["level"] == "INFO"


def test_message_may_be_empty():
    assert parse_line("2024-05-01T10:00:00 INFO")["message"] == ""


def test_rejects_junk():
    with pytest.raises(ValueError):
        parse_line("not a log line")


def test_summary_counts_levels():
    assert count_levels(LOG) == {"INFO": 2, "WARN": 1}


def test_summary_skips_blank_lines():
    assert count_levels("\\n2024-05-01T10:00:00 INFO a\\n\\n") == {"INFO": 1}
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
