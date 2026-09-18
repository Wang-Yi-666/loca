from access import can_vote


def test_exactly_eighteen_can_vote():
    assert can_vote(18) is True


def test_seventeen_cannot():
    assert can_vote(17) is False


def test_adult_can():
    assert can_vote(40) is True


def test_zero_cannot():
    assert can_vote(0) is False
