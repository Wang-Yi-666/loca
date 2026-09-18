from median import median_of_three


def test_middle_wins():
    assert median_of_three(1, 2, 3) == 2


def test_unsorted_arguments():
    assert median_of_three(3, 1, 2) == 2


def test_middle_argument_is_the_median():
    assert median_of_three(2, 3, 1) == 2


def test_duplicates():
    assert median_of_three(5, 5, 1) == 5


def test_all_equal():
    assert median_of_three(4, 4, 4) == 4


def test_floats_and_negatives():
    assert median_of_three(-1.5, -2.0, -0.5) == -1.5
