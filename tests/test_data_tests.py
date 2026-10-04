"""Threshold logic of the data tests, on tiny in-memory tables (no download needed)."""

from datetime import date

import duckdb
import pytest

from src import data_tests as dt


@pytest.fixture
def con():
    c = duckdb.connect()
    for table in dt.FRESHNESS:
        c.execute(f"CREATE TABLE {table} AS SELECT DATE '2026-08-01' AS month")
    return c


@pytest.mark.parametrize("today, expected", [
    (date(2026, 10, 4), "pass"),   # 2 months behind, allowed 2
    (date(2026, 11, 20), "warn"),  # 3 behind: one release late
    (date(2026, 12, 20), "error"), # 4 behind: a whole release missed
])
def test_freshness_has_a_warning_band_before_failing(con, today, expected):
    lfs = next(r for r in dt.check_freshness(con, today) if r.name == "fresh: stg_lfs")
    assert lfs.severity == expected


def test_row_counts_fail_on_shrink_warn_on_big_growth(monkeypatch):
    monkeypatch.setattr(dt, "current_counts", lambda con: {"a": 90, "b": 120, "c": 101, "d": 5})
    results = {r.name: r.severity for r in dt.check_row_counts(None, {"a": 100, "b": 100, "c": 100})}
    assert results == {"rows: a": "error", "rows: b": "warn", "rows: c": "pass", "rows: d": "warn"}


def test_reference_value_mismatch_uses_its_severity(monkeypatch):
    c = duckdb.connect()
    monkeypatch.setattr(dt, "REFERENCE_VALUES", [
        ("error", "never revised", "SELECT 3.1", 3.0, "src"),
        ("warn", "revised yearly", "SELECT 6.5", 6.4, "src"),
        ("error", "matches", "SELECT 2.8", 2.8, "src"),
    ])
    assert [r.severity for r in dt.check_reference_values(c)] == ["error", "warn", "pass"]
