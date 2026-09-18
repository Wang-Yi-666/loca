import pytest

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
