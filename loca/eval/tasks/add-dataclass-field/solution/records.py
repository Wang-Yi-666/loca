"""Builds model objects from raw rows."""

from models import Account


def build_accounts(rows):
    """Turn (id, name, email) rows into Account objects."""
    return [Account(id=row[0], name=row[1], email=row[2]) for row in rows]
