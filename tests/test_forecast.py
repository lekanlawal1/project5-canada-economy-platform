"""Forecast machinery: no look-ahead, correct baseline maths, correct significance test,
and the protocol's decision rule."""

import numpy as np
import pandas as pd
import pytest

from src import forecast as f


@pytest.fixture
def series():
    idx = pd.period_range("1990-01", "2015-12", freq="M")
    rng = np.random.default_rng(0)
    unemployment = pd.Series(7 + np.cumsum(rng.normal(0, 0.1, len(idx))), index=idx)
    seasonal = 1 + 0.003 * np.sin(2 * np.pi * idx.month / 12)
    cpi = pd.Series(100 * 1.002 ** np.arange(len(idx)) * seasonal, index=idx)
    return unemployment, cpi


def test_no_look_ahead(series):
    """Corrupting everything after the origin must not change any forecast."""
    unemployment, cpi = series
    origin = pd.Period("2012-06", "M")
    before = f._forecast_origin((origin, unemployment, cpi, (1, 1, 0)))
    u2, c2 = unemployment.copy(), cpi.copy()
    u2[u2.index > origin] += 50
    c2[c2.index > origin] *= 3
    after = f._forecast_origin((origin, u2, c2, (1, 1, 0)))
    assert [r[5] for r in before] == [r[5] for r in after]


def test_cpi_naive_carries_the_last_yearly_rate_forward(series):
    _, cpi = series
    path = f.cpi_naive_index(cpi)
    last_rate = cpi.iloc[-1] / cpi.iloc[-13]
    for h in range(1, f.MAX_H + 1):
        assert path[h - 1] / cpi.iloc[-1 + h - 12] == pytest.approx(last_rate)


def test_diebold_mariano_detects_a_real_difference_and_not_noise():
    rng = np.random.default_rng(1)
    base = rng.normal(0, 1, 300)
    much_better = base * 0.5
    same_quality = rng.normal(0, 1, 300)
    assert f.diebold_mariano(much_better, base, h=1) < 0.001
    assert f.diebold_mariano(same_quality, base, h=1) > 0.05
    assert f.diebold_mariano(base, base, h=3) == 1.0


def test_decision_rule_needs_lower_error_and_significance():
    rows = [
        # series, horizon, method, skill, p
        ("s", 1, "naive", 0.0, None),
        ("s", 1, "model", 0.2, 0.01),   # better and significant: wins
        ("s", 3, "naive", 0.0, None),
        ("s", 3, "model", 0.2, 0.20),   # better but not significant: naive
        ("s", 6, "naive", 0.0, None),
        ("s", 6, "model", -0.1, 0.01),  # significantly WORSE: naive
    ]
    scores = pd.DataFrame([dict(period="excluding_covid", series=s, horizon=h, method=m,
                                skill_vs_naive=k, dm_p_value=p, mae=1 - k) for s, h, m, k, p in rows])
    assert f.pick_winners(scores) == {("s", 1): "model", ("s", 3): "naive", ("s", 6): "naive"}
