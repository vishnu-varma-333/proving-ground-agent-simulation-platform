"""Cohen's kappa between the judge's `resolved` verdict and a human
label, on a held-out labelled set - the spec's named metric for "judge
reliability". Implemented directly (no sklearn dependency) since it's
one well-known formula for two binary raters:

    kappa = (observed_agreement - expected_agreement) / (1 - expected_agreement)

where expected_agreement is what two raters would agree on by chance
alone, given each rater's own marginal rate of labelling True.
"""

from __future__ import annotations


def cohen_kappa(labels_a: list[bool], labels_b: list[bool]) -> float:
    if len(labels_a) != len(labels_b):
        raise ValueError("label lists must be the same length")
    n = len(labels_a)
    if n == 0:
        raise ValueError("need at least one labelled example")

    observed_agreement = sum(a == b for a, b in zip(labels_a, labels_b)) / n
    p_a_true = sum(labels_a) / n
    p_b_true = sum(labels_b) / n
    expected_agreement = p_a_true * p_b_true + (1 - p_a_true) * (1 - p_b_true)

    if expected_agreement == 1:
        return 1.0
    return (observed_agreement - expected_agreement) / (1 - expected_agreement)
