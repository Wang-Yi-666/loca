"""Fixed-width row formatting."""


def format_row(label, value):
    """One row: two 9-character columns, label left- and value right-aligned."""
    return f"{label:<9}{value:>9}"
