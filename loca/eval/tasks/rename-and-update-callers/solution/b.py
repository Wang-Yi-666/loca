"""Second consumer of the totalling helper."""

from calc import total

OFFSET = 0


def report_b(items):
    return total([item + OFFSET for item in items])
