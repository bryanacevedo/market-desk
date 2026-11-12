"""Every statistic the screens show, checked against a published or independently computed value."""
from __future__ import annotations

import pytest

from market import stats


def test_wilson_newcombe_1998_table():
    # Newcombe (1998), Statistics in Medicine 17:857, Table I: 81/263, score interval 0.2553 to 0.3662.
    lo, hi = stats.wilson(81, 263, conf=0.95)
    assert lo == pytest.approx(0.2553, abs=5e-5) and hi == pytest.approx(0.3662, abs=5e-5)


def test_newcombe_hybrid_1998_example():
    # Newcombe (1998), Statistics in Medicine 17:873, example (a): 56/70 against 48/80, method 10: 0.0524 to 0.3339.
    d, lo, hi = stats.newcombe(56, 70, 48, 80, conf=0.95)
    assert d == pytest.approx(0.2)
    assert lo == pytest.approx(0.0524, abs=5e-5) and hi == pytest.approx(0.3339, abs=5e-5)


def test_fisher_two_sided_lady_tasting_tea():
    # Fisher's tea-tasting table [[3, 1], [1, 3]]: R fisher.test gives p = 0.4857.
    assert stats.fisher_two_sided(3, 1, 1, 3) == pytest.approx(0.4857, abs=1e-4)


def test_fisher_two_sided_wikipedia_example():
    # Wikipedia "Fisher's exact test", dieting example [[1, 9], [11, 3]]: two-sided p = 0.002759.
    assert stats.fisher_two_sided(1, 9, 11, 3) == pytest.approx(0.002759, abs=1e-6)


def test_holm_step_down():
    # Sorted 0.005 <= 0.05/4, 0.01 <= 0.05/3, 0.03 > 0.05/2: stop.
    assert stats.holm([0.01, 0.04, 0.03, 0.005]) == [True, False, False, True]
    assert stats.holm([]) == []


def test_mantel_haenszel_against_statsmodels():
    """Reference computed once with statsmodels 0.14 StratifiedTable on these three strata (2026-11-11):
    oddsratio_pooled 2.82011, confint (1.46914, 5.41337), logodds_pooled_se 0.332709 (Robins, Breslow, Greenland)."""
    or_, lo, hi = stats.mantel_haenszel([(12, 18, 8, 32), (20, 10, 15, 25), (5, 40, 3, 52)])
    assert or_ == pytest.approx(2.82011, abs=1e-5)
    assert lo == pytest.approx(1.46914, abs=1e-4) and hi == pytest.approx(5.41337, abs=1e-4)


def test_mantel_haenszel_skips_empty_strata():
    assert stats.mantel_haenszel([(0, 0, 3, 4), (0, 0, 1, 1)]) is None


def test_median_interval_order_statistics():
    # n = 10 at 95%: the 2nd and 9th order statistics (Conover, Practical Nonparametric Statistics, table A3).
    med, lo, hi = stats.median_ci([float(i) for i in range(1, 11)])
    assert (med, lo, hi) == (5.5, 2.0, 9.0)
    assert stats.median_ci([1, 2, 3, 4, 5]) is None


def test_n_per_arm_copied_from_account_desk():
    # The plan's reviewer computed 103 held-back accounts for a 10% base and a 10-point lift.
    assert stats.n_per_arm(0.10, 0.10) == 103


def test_quantile_linear():
    assert stats.quantile([1, 2, 3, 4], 0.25) == pytest.approx(1.75)
