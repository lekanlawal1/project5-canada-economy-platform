"""Mart logic tests on hand-built staging rows where the right answer is known in advance."""

from datetime import date

import duckdb
import pandas as pd
import pytest

from src.config import SQL_DIR


def month(y, m):
    return date(y, m, 1)


def add_months(d, n):
    y, m = divmod(d.month - 1 + n, 12)
    return date(d.year + y, m + 1, 1)


@pytest.fixture
def con():
    c = duckdb.connect()
    c.execute("""CREATE TABLE dim_geo AS SELECT * FROM (VALUES
        ('Canada', 'country', NULL, 0), ('Ontario', 'province', 'ON', 6),
        ('Quebec', 'province', 'QC', 5)) t(geo, geo_level, province_code, sort_order)""")
    c.execute("""CREATE TABLE stg_lfs (month DATE, geo VARCHAR, characteristic VARCHAR,
        gender VARCHAR, age_group VARCHAR, data_type VARCHAR, unit VARCHAR,
        estimate DOUBLE, se_level DOUBLE, se_mom DOUBLE, se_yoy DOUBLE)""")
    return c


def add_rate(con, geo, d, rate, se_mom=0.1, se_yoy=0.2):
    con.execute("INSERT INTO stg_lfs VALUES (?, ?, 'Unemployment rate', 'Total - Gender', "
                "'15 years and over', 'Seasonally adjusted', 'percent', ?, 0.1, ?, ?)",
                [d, geo, rate, se_mom, se_yoy])


def build_labour(con):
    con.execute((SQL_DIR / "marts/01_mart_labour_monthly.sql").read_text())


def row(con, geo, d):
    return con.execute("SELECT * FROM mart_labour_monthly WHERE geo = ? AND month = ?",
                       [geo, d]).fetchdf().iloc[0]


def test_prior_month_is_matched_by_calendar_not_by_row(con):
    """A suppressed month leaves a gap; the change must be NULL, not a 2 month change."""
    add_rate(con, "Canada", month(2026, 1), 6.0)
    add_rate(con, "Canada", month(2026, 3), 7.0)  # February missing
    build_labour(con)
    assert pd.isna(row(con, "Canada", month(2026, 3))["unemployment_rate_mom_pp"])


def test_change_is_rounded_to_published_precision(con):
    add_rate(con, "Canada", month(2026, 1), 0.3)
    add_rate(con, "Canada", month(2026, 2), 0.1)  # 0.1 - 0.3 is -0.19999999999999998 in float
    build_labour(con)
    assert row(con, "Canada", month(2026, 2))["unemployment_rate_mom_pp"] == -0.2


def test_significance_uses_statcan_standard_error(con):
    add_rate(con, "Canada", month(2026, 1), 6.0)
    add_rate(con, "Canada", month(2026, 2), 6.1, se_mom=0.1)  # 0.1 < 1.96 x 0.1
    add_rate(con, "Canada", month(2026, 3), 6.4, se_mom=0.1)  # 0.3 > 0.196
    build_labour(con)
    assert not row(con, "Canada", month(2026, 2))["unemployment_rate_mom_significant"]
    assert row(con, "Canada", month(2026, 3))["unemployment_rate_mom_significant"]


def test_province_rank_excludes_canada(con):
    d = month(2026, 1)
    add_rate(con, "Canada", d, 6.0)
    add_rate(con, "Ontario", d, 7.0)
    add_rate(con, "Quebec", d, 5.0)
    build_labour(con)
    assert row(con, "Quebec", d)["province_rank_unemployment"] == 1
    assert row(con, "Ontario", d)["province_rank_unemployment"] == 2
    assert pd.isna(row(con, "Canada", d)["province_rank_unemployment"])


def test_anomaly_needs_history_and_flags_a_real_spike(con):
    start = month(2020, 1)
    rate = 6.0
    # 40 months of small alternating moves, then a 2 point jump.
    for i in range(40):
        rate += 0.1 if i % 2 else -0.1
        add_rate(con, "Canada", add_months(start, i), round(rate, 1))
    spike_month = add_months(start, 40)
    add_rate(con, "Canada", spike_month, round(rate + 2.0, 1))
    build_labour(con)

    early = row(con, "Canada", add_months(start, 10))
    assert not early["is_anomaly"], "fewer than 24 months of history: must not score"
    spike = row(con, "Canada", spike_month)
    assert spike["is_anomaly"]
    assert spike["unemployment_rate_mom_robust_z"] > 3.5
    normal = row(con, "Canada", add_months(start, 39))
    assert not normal["is_anomaly"]
