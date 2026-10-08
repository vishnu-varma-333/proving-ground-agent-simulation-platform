import pytest
from judge.calibration import cohen_kappa


def test_perfect_agreement_gives_kappa_of_one():
    labels = [True, False, True, True, False, False]
    assert cohen_kappa(labels, labels) == 1.0


def test_agreement_matching_chance_gives_kappa_near_zero():
    # Both raters say True half the time, agreeing only as often as chance
    # predicts: a 50/50 rater for an independent 50/50 ground truth.
    a = [True, False, True, False, True, False, True, False]
    b = [True, True, False, False, False, False, True, True]
    kappa = cohen_kappa(a, b)
    assert -0.3 < kappa < 0.3


def test_anti_correlated_raters_give_negative_kappa():
    # Both raters split 50/50, but always disagree - worse than chance.
    a = [True, False, True, False]
    b = [False, True, False, True]
    assert cohen_kappa(a, b) < 0


def test_one_constant_rater_gives_kappa_of_zero():
    # A rater with no variance can't do better or worse than chance by
    # this formula's own definition (expected agreement is already 0).
    a = [True, True, True, True]
    b = [False, False, False, False]
    assert cohen_kappa(a, b) == 0.0


def test_raises_on_mismatched_lengths():
    with pytest.raises(ValueError):
        cohen_kappa([True], [True, False])


def test_raises_on_empty_input():
    with pytest.raises(ValueError):
        cohen_kappa([], [])
