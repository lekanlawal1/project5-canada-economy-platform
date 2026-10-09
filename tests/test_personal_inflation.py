"""The personal inflation calculator's arithmetic (src/site_export.personal_rate) and the mart
behind it. The data test in src/data_tests.py checks the same thing on real data: official
spending weights must reproduce the published all-items rate."""

import duckdb
import pytest

from src.site_export import personal_rate

CATS = [{"category": "rent", "yoy_pct": 5.0}, {"category": "gas", "yoy_pct": 20.0},
        {"category": "food", "yoy_pct": 2.0}]


def test_weighted_by_spending():
    # $1,000 rent at +5% and $1,000 food at +2%: 3.5%
    assert personal_rate({"rent": 1000, "food": 1000}, CATS) == pytest.approx(3.5)


def test_categories_you_do_not_buy_do_not_count():
    # no car: gasoline's +20% must not move the rate
    assert personal_rate({"rent": 1500, "food": 500, "gas": 0}, CATS) == pytest.approx(4.25)


def test_nothing_entered_gives_no_rate():
    assert personal_rate({}, CATS) is None
    assert personal_rate({"rent": 0}, CATS) is None


def test_negative_amounts_are_ignored():
    assert personal_rate({"rent": 1000, "food": -500}, CATS) == pytest.approx(5.0)


def test_derived_other_category_reproduces_the_group():
    """'Other home costs' is derived so that rent + other, at their weights, equals shelter."""
    con = duckdb.connect()
    # DOUBLE, like the mart's columns (bare literals would be fixed-point decimals)
    con.execute("CREATE TABLE g AS SELECT 28.3::DOUBLE w_s, 4.0::DOUBLE y_s, 7.45::DOUBLE w_r, 6.0::DOUBLE y_r")
    w_o, y_o = con.execute("SELECT w_s - w_r, (w_s * y_s - w_r * y_r) / (w_s - w_r) FROM g").fetchone()
    assert (7.45 * 6.0 + w_o * y_o) / 28.3 == pytest.approx(4.0)
