from names import normalize


def test_trims_and_cases():
    assert normalize("  ada lovelace  ") == "Ada Lovelace"


def test_inner_whitespace_collapsed():
    assert normalize("ada    lovelace") == "Ada Lovelace"


def test_already_clean_is_unchanged():
    assert normalize("Ada Lovelace") == "Ada Lovelace"


def test_hyphenated_name():
    assert normalize("jean-luc picard") == "Jean-Luc Picard"


def test_tabs_and_newlines_count_as_whitespace():
    assert normalize("ada\tlovelace") == "Ada Lovelace"
