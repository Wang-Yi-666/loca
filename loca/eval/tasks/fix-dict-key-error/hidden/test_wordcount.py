from wordcount import count_words


def test_counts_repeats():
    assert count_words("a b a") == {"a": 2, "b": 1}


def test_case_insensitive():
    assert count_words("The the THE") == {"the": 3}


def test_empty_text():
    assert count_words("") == {}


def test_punctuation_is_part_of_the_word():
    assert count_words("hi hi!") == {"hi": 1, "hi!": 1}


def test_whitespace_variants():
    assert count_words("a\tb\na") == {"a": 2, "b": 1}
