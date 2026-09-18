from people import by_age


def test_oldest_first():
    assert by_age() == ["alan", "ada", "grace"]


def test_returns_names_not_dicts():
    assert all(isinstance(name, str) for name in by_age())


def test_original_table_is_untouched():
    import people

    assert [p["name"] for p in people.PEOPLE] == ["ada", "alan", "grace"]
