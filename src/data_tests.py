"""Data tests: run against the built warehouse after every build, locally and in CI.

Unit tests (tests/) prove the SQL logic on tiny hand-made data. These tests prove the REAL
data is sane: keys unique, required values present, codes valid, tables fresh, row counts
plausible, and headline numbers equal to what StatCan officially published.

Each check has a severity:
    error: the build is wrong or unusable; exit code 1, CI fails, nothing is deployed.
    warn:  worth a human look, but the data is still publishable.

Usage:
    python -m src.data_tests                    run all checks
    python -m src.data_tests --update-baseline  also record today's row counts as the baseline
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date

import duckdb

from src.config import DB_PATH, ROOT

BASELINE_PATH = ROOT / "data" / "row_counts.json"

# Primary keys. A duplicate here would double count in every chart downstream.
UNIQUE_KEYS = {
    "dim_geo": ["geo"],
    "stg_lfs": ["month", "geo", "characteristic", "gender", "age_group", "data_type"],
    "stg_cpi": ["month", "geo", "product"],
    "stg_nhpi": ["month", "geo", "component"],
    "stg_job_vacancies": ["month", "geo"],
    "stg_gdp": ["month", "naics_code"],
    "mart_labour_monthly": ["month", "geo", "gender", "age_group"],
    "mart_cpi_monthly": ["month", "geo", "product"],
    "mart_housing_monthly": ["month", "geo", "component"],
    "mart_job_market_monthly": ["month", "geo"],
    "mart_gdp_monthly": ["month", "naics_code"],
    "mart_province_scorecard": ["geo"],
    "forecast_latest": ["series", "horizon"],
}

# Columns that must never be NULL. Value columns are included where staging promises a value.
NOT_NULL = {
    "dim_geo": ["geo", "geo_level"],
    "stg_lfs": ["month", "geo", "estimate"],
    "stg_cpi": ["month", "geo", "product", "index_value", "index_base"],
    "stg_nhpi": ["month", "geo", "index_value"],
    "stg_gdp": ["month", "naics_code", "gdp_millions"],
    "mart_province_scorecard": ["labour_month", "unemployment_rate", "cpi_month", "cpi_yoy_pct"],
}

# (description, SQL that counts violating rows)
RULES = [
    ("CPI uses only the 2002=100 base (year-over-year math depends on it)",
     "SELECT count(*) FROM stg_cpi WHERE index_base <> '2002=100'"),
    ("Every province and territory in dim_geo has a province code",
     "SELECT count(*) FROM dim_geo WHERE geo_level IN ('province', 'territory', 'metro') "
     "AND province_code IS NULL"),
    ("Exactly 10 provinces in dim_geo",
     "SELECT abs(count(*) - 10) FROM dim_geo WHERE geo_level = 'province'"),
    ("Job vacancy quality grades are A to F",
     "SELECT count(*) FROM stg_job_vacancies WHERE job_vacancies_grade NOT IN ('A','B','C','D','E','F')"),
    ("GDP industry types are total, aggregate or sector",
     "SELECT count(*) FROM stg_gdp WHERE industry_type NOT IN ('total', 'aggregate', 'sector')"),
    ("Exactly one GDP total series (T001)",
     "SELECT abs(count(DISTINCT naics_code) - 1) FROM stg_gdp WHERE industry_type = 'total'"),
    ("Rates are percentages between 0 and 100",
     "SELECT count(*) FROM mart_labour_monthly WHERE unemployment_rate NOT BETWEEN 0 AND 100 "
     "OR employment_rate NOT BETWEEN 0 AND 100 OR participation_rate NOT BETWEEN 0 AND 100"),
    ("Job vacancy rate between 0 and 100",
     "SELECT count(*) FROM stg_job_vacancies WHERE job_vacancy_rate NOT BETWEEN 0 AND 100"),
    ("Price indexes and GDP are positive",
     "SELECT (SELECT count(*) FROM stg_cpi WHERE index_value <= 0) "
     "+ (SELECT count(*) FROM stg_nhpi WHERE index_value <= 0) "
     "+ (SELECT count(*) FROM stg_gdp WHERE gdp_millions <= 0)"),
    ("Labour force = employment + unemployment, within rounding (Canada, 15+, SA)",
     "SELECT count(*) FROM mart_labour_monthly WHERE geo = 'Canada' AND gender = 'Total - Gender' "
     "AND age_group = '15 years and over' "
     "AND abs(labour_force_k - employment_k - unemployment_k) > 0.2"),
    ("Scorecard covers Canada and all 10 provinces",
     "SELECT 11 - count(*) FROM mart_province_scorecard"),
    ("Latest labour month has all 11 geographies for the headline series",
     "SELECT 11 - count(*) FROM mart_labour_monthly WHERE gender = 'Total - Gender' "
     "AND age_group = '15 years and over' AND month = (SELECT max(month) FROM mart_labour_monthly)"),
    ("Latest CPI month has all 11 geographies for all-items",
     "SELECT 11 - count(*) FROM mart_cpi_monthly WHERE product = 'All-items' "
     "AND month = (SELECT max(month) FROM mart_cpi_monthly)"),
    ("Published forecast has 2 targets x 3 horizons, each with an ordered 80% range",
     "SELECT abs(count(*) - 6) + count(*) FILTER (WHERE low_80 > high_80) FROM forecast_latest"),
    ("Every forecast method was scored at every horizon in the backtest",
     "SELECT 2 * 3 * 5 - count(*) FROM forecast_scores"),
    # The 2% sum check below cannot see a missing small sector (management of companies is
    # 0.02% of GDP), so sector presence is checked by count as well.
    ("Latest GDP month has all 20 two-digit sectors",
     "SELECT 20 - count(*) FROM stg_gdp WHERE industry_type = 'sector' "
     "AND month = (SELECT max(month) FROM stg_gdp)"),
    ("Sectors sum to the GDP total within 2% (chained dollars are not perfectly additive)",
     "SELECT count(*) FROM (SELECT month, sum(gdp_millions) FILTER (WHERE industry_type = 'sector') s, "
     "max(gdp_millions) FILTER (WHERE industry_type = 'total') t FROM stg_gdp GROUP BY month) "
     "WHERE abs(s / t - 1) > 0.02"),
]

# Freshness: (table, how many months behind today the latest month may be before warning).
# Typical StatCan lags: LFS about 1 month, CPI and NHPI about 1.5, vacancies and GDP about
# 2.5. One extra month beyond the threshold is an error: a whole release was missed.
FRESHNESS = {
    "stg_lfs": 2,
    "stg_cpi": 2,
    "stg_nhpi": 2,
    "stg_job_vacancies": 3,
    "stg_gdp": 3,
}

# Official figures, copied from StatCan's releases in The Daily.
# CPI (not seasonally adjusted) is never revised once published, so these checks are
# permanent errors. Seasonally adjusted LFS figures are revised every January when StatCan
# updates its seasonal factors, so LFS checks are warnings, re-pinned after each revision.
CPI_RELEASE = "https://www150.statcan.gc.ca/n1/daily-quotidien/260914/dq260914a-eng.htm"
LFS_RELEASE = "https://www150.statcan.gc.ca/n1/daily-quotidien/260904/dq260904a-eng.htm"
REFERENCE_VALUES = [
    # (severity, label, SQL returning one value, official value, source)
    ("error", "CPI all-items, Canada, Aug 2026, 12-month %",
     "SELECT yoy_pct FROM mart_cpi_monthly WHERE geo='Canada' AND product='All-items' AND month='2026-08-01'",
     3.0, CPI_RELEASE),
    ("error", "CPI all-items, Canada, Jul 2026, 12-month %",
     "SELECT yoy_pct FROM mart_cpi_monthly WHERE geo='Canada' AND product='All-items' AND month='2026-07-01'",
     3.0, CPI_RELEASE),
    ("error", "CPI all-items, Canada, Aug 2026, monthly %",
     "SELECT mom_pct FROM mart_cpi_monthly WHERE geo='Canada' AND product='All-items' AND month='2026-08-01'",
     -0.1, CPI_RELEASE),
    ("error", "CPI food purchased from stores, Canada, Aug 2026, 12-month %",
     "SELECT yoy_pct FROM mart_cpi_monthly WHERE geo='Canada' AND product='Food purchased from stores' AND month='2026-08-01'",
     2.8, CPI_RELEASE),
    ("error", "CPI shelter, Canada, Aug 2026, 12-month %",
     "SELECT yoy_pct FROM mart_cpi_monthly WHERE geo='Canada' AND product='Shelter' AND month='2026-08-01'",
     1.5, CPI_RELEASE),
    ("error", "CPI transportation, Canada, Aug 2026, 12-month %",
     "SELECT yoy_pct FROM mart_cpi_monthly WHERE geo='Canada' AND product='Transportation' AND month='2026-08-01'",
     7.5, CPI_RELEASE),
    ("error", "CPI gasoline, Canada, Aug 2026, 12-month %",
     "SELECT yoy_pct FROM mart_cpi_monthly WHERE geo='Canada' AND product='Gasoline' AND month='2026-08-01'",
     22.8, CPI_RELEASE),
    ("warn", "Unemployment rate, Canada, Aug 2026",
     "SELECT unemployment_rate FROM mart_labour_monthly WHERE geo='Canada' AND gender='Total - Gender' "
     "AND age_group='15 years and over' AND month='2026-08-01'",
     6.4, LFS_RELEASE),
    ("warn", "Unemployment rate, Newfoundland and Labrador, Aug 2026",
     "SELECT unemployment_rate FROM mart_labour_monthly WHERE geo='Newfoundland and Labrador' "
     "AND gender='Total - Gender' AND age_group='15 years and over' AND month='2026-08-01'",
     8.6, LFS_RELEASE),
    ("warn", "Unemployment rate change, Prince Edward Island, Aug 2026, points",
     "SELECT unemployment_rate_mom_pp FROM mart_labour_monthly WHERE geo='Prince Edward Island' "
     "AND gender='Total - Gender' AND age_group='15 years and over' AND month='2026-08-01'",
     1.1, LFS_RELEASE),
    ("warn", "Employment, Canada, Aug 2026, thousands (release rounds to 21,173,000)",
     "SELECT round(employment_k) FROM mart_labour_monthly WHERE geo='Canada' AND gender='Total - Gender' "
     "AND age_group='15 years and over' AND month='2026-08-01'",
     21173.0, LFS_RELEASE),
]

# Row counts: shrinking means StatCan dropped data or our filter broke. Rows normally only
# grow, by roughly one month of data per release.
MAX_GROWTH = 0.10


@dataclass
class Result:
    name: str
    severity: str  # "pass", "warn" or "error"
    detail: str = ""


def months_between(later: date, earlier: date) -> int:
    return (later.year - earlier.year) * 12 + later.month - earlier.month


def check_unique(con) -> list[Result]:
    out = []
    for table, keys in UNIQUE_KEYS.items():
        cols = ", ".join(keys)
        dupes = con.execute(
            f"SELECT count(*) FROM (SELECT {cols} FROM {table} GROUP BY ALL HAVING count(*) > 1)"
        ).fetchone()[0]
        out.append(Result(f"unique: {table} ({cols})", "error" if dupes else "pass",
                          f"{dupes} duplicated keys" if dupes else ""))
    return out


def check_not_null(con) -> list[Result]:
    out = []
    for table, cols in NOT_NULL.items():
        for col in cols:
            n = con.execute(f"SELECT count(*) FROM {table} WHERE {col} IS NULL").fetchone()[0]
            out.append(Result(f"not null: {table}.{col}", "error" if n else "pass",
                              f"{n} NULLs" if n else ""))
    return out


def check_rules(con) -> list[Result]:
    out = []
    for name, sql in RULES:
        n = con.execute(sql).fetchone()[0]
        out.append(Result(f"rule: {name}", "error" if n else "pass", f"{n} violations" if n else ""))
    return out


def check_freshness(con, today: date) -> list[Result]:
    out = []
    for table, allowed in FRESHNESS.items():
        latest = con.execute(f"SELECT max(month) FROM {table}").fetchone()[0]
        behind = months_between(today, latest)
        severity = "pass" if behind <= allowed else ("warn" if behind == allowed + 1 else "error")
        out.append(Result(f"fresh: {table}", severity,
                          f"latest {latest:%Y-%m}, {behind} months behind (allowed {allowed})"))
    return out


def check_reference_values(con) -> list[Result]:
    out = []
    for severity, label, sql, official, source in REFERENCE_VALUES:
        row = con.execute(sql).fetchone()
        ours = row[0] if row else None
        # float(): DuckDB returns DECIMAL for some expressions, which cannot subtract a float.
        ok = ours is not None and abs(float(ours) - official) < 1e-9
        out.append(Result(f"official: {label}", "pass" if ok else severity,
                          f"ours {ours}, StatCan {official}" + ("" if ok else f" ({source})")))
    return out


def current_counts(con) -> dict[str, int]:
    return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in UNIQUE_KEYS}


def check_row_counts(con, baseline: dict[str, int]) -> list[Result]:
    out = []
    for table, now in current_counts(con).items():
        before = baseline.get(table)
        if before is None:
            out.append(Result(f"rows: {table}", "warn", f"{now:,} rows, no baseline yet"))
        elif now < before:
            out.append(Result(f"rows: {table}", "error", f"shrank from {before:,} to {now:,}"))
        elif before and (now - before) / before > MAX_GROWTH:
            out.append(Result(f"rows: {table}", "warn",
                              f"grew {100 * (now - before) / before:.0f}% ({before:,} to {now:,})"))
        else:
            out.append(Result(f"rows: {table}", "pass", f"{before:,} to {now:,}"))
    return out


def run_all(con, today: date | None = None, baseline: dict | None = None) -> list[Result]:
    today = today or date.today()
    if baseline is None:
        baseline = json.loads(BASELINE_PATH.read_text()) if BASELINE_PATH.exists() else {}
    return (check_unique(con) + check_not_null(con) + check_rules(con)
            + check_freshness(con, today) + check_reference_values(con)
            + check_row_counts(con, baseline))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--update-baseline", action="store_true",
                        help="after a run with no errors, save current row counts as the baseline")
    args = parser.parse_args(argv)

    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        results = run_all(con)
        counts = current_counts(con)

    marks = {"pass": "PASS", "warn": "WARN", "error": "FAIL"}
    for r in results:
        print(f"[{marks[r.severity]}] {r.name}" + (f"  ({r.detail})" if r.detail else ""))
    tally = {s: sum(r.severity == s for r in results) for s in marks}
    print(f"\n{tally['pass']} passed, {tally['warn']} warnings, {tally['error']} errors")

    if tally["error"]:
        return 1
    if args.update_baseline:
        BASELINE_PATH.write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n")
        print(f"baseline updated: {BASELINE_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
