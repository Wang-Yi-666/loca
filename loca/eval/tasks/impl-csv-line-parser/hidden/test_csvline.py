from csvline import parse_line


def test_plain_fields():
    assert parse_line("a,b,c") == ["a", "b", "c"]


def test_single_field():
    assert parse_line("solo") == ["solo"]


def test_empty_fields_are_preserved():
    assert parse_line("a,,c") == ["a", "", "c"]


def test_trailing_empty_field():
    assert parse_line("a,b,") == ["a", "b", ""]


def test_quoted_field_with_comma():
    assert parse_line('a,"b,c",d') == ["a", "b,c", "d"]


def test_escaped_quote_inside_quotes():
    assert parse_line('"say ""hi""",x') == ['say "hi"', "x"]


def test_quoted_empty_field():
    assert parse_line('""') == [""]


def test_quote_in_the_middle_is_literal():
    assert parse_line('ab"cd,e') == ['ab"cd', "e"]


def test_quoted_field_with_spaces():
    assert parse_line('"  padded  ",x') == ["  padded  ", "x"]
