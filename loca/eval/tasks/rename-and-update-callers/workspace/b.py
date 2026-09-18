"""Second consumer of the totalling helper."""

from calc import calc_total

OFFSET = 0


def report_b(items):
    return calc_total([item + OFFSET for item in items])
