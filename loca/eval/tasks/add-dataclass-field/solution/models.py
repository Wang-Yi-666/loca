"""Domain models."""

from dataclasses import dataclass


@dataclass
class Account:
    id: int
    name: str
    email: str
