"""Count lines, words and characters - a tiny wc clone."""

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
