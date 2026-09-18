import subprocess
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

    assert wc.counts("a b\nc\n") == {"lines": 2, "words": 3, "chars": 6}
