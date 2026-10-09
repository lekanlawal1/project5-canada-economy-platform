"""Export the warehouse to the static dashboard: site/data/*.json plus the Plotly bundle.

Design:
- The site is plain HTML, CSS and JavaScript on GitHub Pages. No server, nothing to keep
  running, and it costs nothing. Every page reads small pre-computed JSON files.
- JSON is columnar ({"month": [...], "value": [...]}) rather than a list of row objects:
  the same data in roughly a third of the bytes, and it is the shape Plotly wants.
- All numbers are computed in SQL (the marts). The browser only draws, so the dashboard
  can never disagree with the data tests or the AI briefing.
- plotly.min.js is copied from the pinned Python package instead of loaded from a CDN, so
  the chart library version is fixed by requirements.txt and the site has no third-party
  runtime dependency.

Usage:
    python -m src.site_export     (after src.build and src.forecast)
"""

from __future__ import annotations

import json
import math
import os
import shutil
import sys
from datetime import date, datetime, timezone

import duckdb

from src import data_tests
from src.config import DB_PATH, ROOT

SITE = ROOT / "site"
DATA_DIR = SITE / "data"
HEADLINE = "gender = 'Total - Gender' AND age_group = '15 years and over'"
# Full history: the date-range control lets readers pick any period StatCan publishes
# (LFS from 1976, CPI from 1914, new housing prices from 1981). Measured cost below.
HISTORY_START = "1900-01-01"


def clean(v):
    """JSON-safe values: dates to 'YYYY-MM', NaN to null, numpy scalars to Python."""
    if v is None:
        return None
    if isinstance(v, (date, datetime)):
        return v.strftime("%Y-%m")
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    if isinstance(v, float) and v == 0:
        return 0.0  # rounding can leave -0.0, which would display as "-0.0%"
    return v


def columns(con, sql: str, params=None) -> dict:
    cur = con.execute(sql, params or [])
    names = [d[0] for d in cur.description]
    rows = cur.fetchall()
    return {n: [clean(r[i]) for r in rows] for i, n in enumerate(names)}


def records(con, sql: str, params=None) -> list[dict]:
    cur = con.execute(sql, params or [])
    names = [d[0] for d in cur.description]
    return [{n: clean(v) for n, v in zip(names, r)} for r in cur.fetchall()]


def geos(con, levels=("country", "province")) -> list[str]:
    marks = ",".join("?" * len(levels))
    return [r[0] for r in con.execute(
        f"SELECT geo FROM dim_geo WHERE geo_level IN ({marks}) ORDER BY sort_order, geo", list(levels)).fetchall()]


# --------------------------------------------------------------------------- pages


def overview(con) -> dict:
    def latest(sql):
        return records(con, sql)[0]

    lab = latest(f"""SELECT month, unemployment_rate AS value, unemployment_rate_mom_pp AS change,
        unemployment_rate_mom_significant AS significant, employment_mom_k, employment_mom_significant
        FROM mart_labour_monthly WHERE geo = 'Canada' AND {HEADLINE} ORDER BY month DESC LIMIT 1""")
    cpi = latest("""SELECT month, yoy_pct AS value, yoy_change_pp AS change FROM mart_cpi_monthly
        WHERE geo = 'Canada' AND product = 'All-items' ORDER BY month DESC LIMIT 1""")
    core = latest("""SELECT month, yoy_pct AS value, yoy_change_pp AS change FROM mart_cpi_monthly
        WHERE geo = 'Canada' AND product = 'All-items excluding food and energy' ORDER BY month DESC LIMIT 1""")
    nhpi = latest("""SELECT month, yoy_pct AS value, use_with_caution FROM mart_housing_monthly
        WHERE geo = 'Canada' AND component = 'Total (house and land)' ORDER BY month DESC LIMIT 1""")
    jv = latest("""SELECT month, job_vacancy_rate AS value, job_vacancy_rate_yoy_pp AS change,
        unemployed_per_vacancy FROM mart_job_market_monthly WHERE geo = 'Canada' ORDER BY month DESC LIMIT 1""")
    gdp = latest("""SELECT month, mom_pct AS value, yoy_pct FROM mart_gdp_monthly
        WHERE naics_code = 'T001' ORDER BY month DESC LIMIT 1""")

    spark = lambda sql: columns(con, sql)
    tiles = [
        dict(key="unemployment", label="Unemployment rate", unit="%", **lab,
             spark=spark(f"SELECT month, unemployment_rate AS v FROM mart_labour_monthly WHERE geo='Canada' "
                         f"AND {HEADLINE} AND month >= (SELECT max(month) FROM mart_labour_monthly) - INTERVAL 35 MONTH ORDER BY month")),
        dict(key="cpi", label="Inflation (CPI, 12-month)", unit="%", **cpi,
             spark=spark("SELECT month, yoy_pct AS v FROM mart_cpi_monthly WHERE geo='Canada' AND product='All-items' "
                         "AND month >= (SELECT max(month) FROM mart_cpi_monthly) - INTERVAL 35 MONTH ORDER BY month")),
        dict(key="core", label="Core inflation (excl. food and energy)", unit="%", **core,
             spark=spark("SELECT month, yoy_pct AS v FROM mart_cpi_monthly WHERE geo='Canada' "
                         "AND product='All-items excluding food and energy' "
                         "AND month >= (SELECT max(month) FROM mart_cpi_monthly) - INTERVAL 35 MONTH ORDER BY month")),
        dict(key="housing", label="New home prices (12-month)", unit="%", **nhpi,
             spark=spark("SELECT month, yoy_pct AS v FROM mart_housing_monthly WHERE geo='Canada' "
                         "AND component='Total (house and land)' "
                         "AND month >= (SELECT max(month) FROM mart_housing_monthly) - INTERVAL 35 MONTH ORDER BY month")),
        dict(key="vacancies", label="Job vacancy rate", unit="%", **jv,
             spark=spark("SELECT month, job_vacancy_rate AS v FROM mart_job_market_monthly WHERE geo='Canada' "
                         "AND month >= (SELECT max(month) FROM mart_job_market_monthly) - INTERVAL 35 MONTH ORDER BY month")),
        dict(key="gdp", label="Real GDP, monthly change", unit="%", **gdp,
             spark=spark("SELECT month, mom_pct AS v FROM mart_gdp_monthly WHERE naics_code='T001' "
                         "AND month >= (SELECT max(month) FROM mart_gdp_monthly) - INTERVAL 35 MONTH ORDER BY month")),
    ]

    history = {
        "unemployment": columns(con, f"SELECT month, unemployment_rate AS v FROM mart_labour_monthly "
                                     f"WHERE geo='Canada' AND {HEADLINE} AND month >= '2022-01-01' ORDER BY month"),
        "cpi_yoy": columns(con, "SELECT month, yoy_pct AS v FROM mart_cpi_monthly WHERE geo='Canada' "
                                "AND product='All-items' AND month >= '2022-01-01' ORDER BY month"),
    }
    forecasts = records(con, "SELECT * FROM forecast_latest ORDER BY series, horizon")
    skill = records(con, """SELECT series, horizon, method, n, mae, skill_vs_naive, dm_p_value
        FROM forecast_scores WHERE period = 'excluding_covid' ORDER BY series, horizon, mae""")

    anomalies = records(con, """
        WITH latest AS (SELECT domain, max(month) AS m FROM mart_anomalies GROUP BY domain)
        SELECT a.month, a.domain, a.geo, a.series, a.change_value, a.change_unit, a.robust_z
        FROM mart_anomalies a
        WHERE a.month >= (SELECT max(month) FROM mart_anomalies) - INTERVAL 2 MONTH
        ORDER BY abs(a.robust_z) DESC LIMIT 10""")

    gdp_sectors = records(con, """SELECT industry, mom_pct, yoy_pct, share_of_total_pct, month
        FROM mart_gdp_monthly WHERE industry_type = 'sector'
        AND month = (SELECT max(month) FROM mart_gdp_monthly) ORDER BY mom_pct""")
    gdp_history = columns(con, "SELECT month, mom_pct AS v FROM mart_gdp_monthly WHERE naics_code='T001' "
                               "AND month >= '2022-01-01' ORDER BY month")
    return dict(tiles=tiles, history=history, forecasts=forecasts, skill=skill,
                anomalies=anomalies, gdp_sectors=gdp_sectors, gdp_history=gdp_history,
                so_what=so_what(con))


# --------------------------------------------------------------------------- "what it means for you"
# Plain-language cards for a renter, a job seeker and an employer. The sentences are fixed rules
# over numbers from the marts, not AI text, so they can never state a number the data does not hold.
# Kept separate from the SQL (so_what_facts) so the wording rules are unit-tested on their own.

SAME_PP = 0.2        # within this many points, two rates are "about the same"
SAME_RATIO = 0.1     # within this, unemployed-per-vacancy is "about the same" as a year ago
RENT_EXAMPLE = 2000  # illustrative monthly rent, dollars
SHOP_EXAMPLE = 250   # illustrative weekly grocery shop, dollars


def so_what_facts(con, geo: str) -> dict:
    def one(sql, params):
        r = records(con, sql, params)
        return r[0] if r else {}

    cpi = {}
    for key, product in (("all", "All-items"), ("rent", "Rent"), ("groceries", "Food purchased from stores")):
        cpi[key] = one("""SELECT month, yoy_pct FROM mart_cpi_monthly WHERE geo = ? AND product = ?
            AND yoy_pct IS NOT NULL ORDER BY month DESC LIMIT 1""", [geo, product])
    core = one("""SELECT month, yoy_pct FROM mart_cpi_monthly WHERE geo = 'Canada'
        AND product = 'All-items excluding food and energy' AND yoy_pct IS NOT NULL ORDER BY month DESC LIMIT 1""", [])
    lab = one(f"""SELECT month, unemployment_rate AS ur, unemployment_rate_yoy_pp AS ur_yoy,
        unemployment_rate_yoy_significant AS ur_yoy_sig FROM mart_labour_monthly
        WHERE geo = ? AND {HEADLINE} AND unemployment_rate IS NOT NULL ORDER BY month DESC LIMIT 1""", [geo])
    # unemployed per vacancy now and in the same month a year earlier (matched by calendar month)
    jobs = one("""SELECT j.month, j.unemployed_per_vacancy AS upv, j.job_vacancy_rate AS jvr,
            j.job_vacancy_rate_yoy_pp AS jvr_yoy, j.is_low_quality AS low_q, p.unemployed_per_vacancy AS upv_prev
        FROM mart_job_market_monthly j
        LEFT JOIN mart_job_market_monthly p ON p.geo = j.geo AND p.month = j.month - INTERVAL 12 MONTH
        WHERE j.geo = ? AND j.unemployed_per_vacancy IS NOT NULL ORDER BY j.month DESC LIMIT 1""", [geo])
    return {"geo": geo, "cpi": cpi, "core": core, "labour": lab, "jobs": jobs}


def _pct(v: float) -> str:
    return f"{v:.1f}%"


def _money(v: float) -> str:
    return f"${v:,.0f}"


def _month_name(ym: str) -> str:
    """'2026-07' -> 'July 2026'."""
    names = ["January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December"]
    return f"{names[int(ym[5:7]) - 1]} {ym[:4]}"


def _change(v: float, unit: str = "%") -> tuple[str, str]:
    """A signed change as (direction word, size): 'up'/'down'/'flat'."""
    if abs(v) < 0.05:
        return "flat", "0.0" + unit
    return ("up" if v > 0 else "down"), f"{abs(v):.1f}{unit}"


def so_what_cards(f: dict) -> list[dict]:
    """Facts for one geography -> three cards. Any card whose facts are missing is left out."""
    cards = []
    geo, cpi = f["geo"], f["cpi"]
    rent, allc, groc = cpi.get("rent", {}), cpi.get("all", {}), cpi.get("groceries", {})

    if rent.get("yoy_pct") is not None and allc.get("yoy_pct") is not None:
        r, a = rent["yoy_pct"], allc["yoy_pct"]
        pace = ("about the same pace as" if abs(r - a) < SAME_PP
                else "faster than" if r > a else "slower than")
        word, size = _change(r)
        if word == "flat":
            lines = [f"Rent in {geo} is level with a year ago, while prices overall moved {_pct(a)}."]
            head = "Rent flat over the year"
        else:
            lines = [f"Rent in {geo} is {word} {size} on a year ago, {pace} prices overall ({_pct(a)}).",
                     f"On {_money(RENT_EXAMPLE)} a month, a {size} change is about "
                     f"{_money(RENT_EXAMPLE * abs(r) / 100)} a month, or {_money(RENT_EXAMPLE * abs(r) / 100 * 12)} a year."]
            head = f"Rent {word} {size} in a year"
        if groc.get("yoy_pct") is not None:
            g = groc["yoy_pct"]
            gword, gsize = _change(g)
            if gword == "flat":
                lines.append("Grocery prices are level with a year ago.")
            else:
                lines.append(f"Groceries are {gword} {gsize}: a {_money(SHOP_EXAMPLE)} weekly shop costs about "
                             f"{_money(SHOP_EXAMPLE * abs(g) / 100)} {'more' if g > 0 else 'less'} than a year ago.")
        cards.append({"who": "Renter", "headline": head, "lines": lines,
                      "month": rent["month"],
                      "note": "The index is an average across all rentals; a single lease can move very differently."})

    lab, jobs = f["labour"], f["jobs"]
    if lab.get("ur") is not None:
        lines = []
        if lab.get("ur_yoy") is not None:
            d = lab["ur_yoy"]
            if abs(d) < 0.05:
                lines.append("That is unchanged from a year ago.")
            else:
                move = f"{'up' if d > 0 else 'down'} {abs(d):.1f} points from a year ago"
                lines.append(f"That is {move}" + ("." if lab.get("ur_yoy_sig") else
                             ", within the survey's margin of error, so not a clear change."))
        if jobs.get("upv") is not None:
            u, up = jobs["upv"], jobs.get("upv_prev")
            line = f"In {_month_name(jobs['month'])} there were {u:.1f} unemployed people for every open job"
            if up is not None:
                cmp = ("about the same as" if abs(u - up) < SAME_RATIO
                       else "more competition than" if u > up else "less competition than")
                line += f", {cmp} a year ago ({up:.1f})"
            lines.append(line + ".")
        cards.append({"who": "Job seeker", "headline": f"Unemployment is {_pct(lab['ur'])}", "lines": lines,
                      "month": lab["month"], "note": "Ages 15 and over, seasonally adjusted."})

    if jobs.get("upv") is not None:
        u, up = jobs["upv"], jobs.get("upv_prev")
        if up is None or abs(u - up) < SAME_RATIO:
            head = "Hiring: about as hard as a year ago"
        else:
            head = "Hiring: easier than a year ago" if u > up else "Hiring: harder than a year ago"
        lines = []
        if jobs.get("jvr") is not None:
            line = f"{_pct(jobs['jvr'])} of jobs are vacant"
            if jobs.get("jvr_yoy") is not None:
                d = jobs["jvr_yoy"]
                line += (", the same as a year ago" if abs(d) < 0.05
                         else f" ({'+' if d > 0 else '-'}{abs(d):.1f} points on a year ago)")
            lines.append(line + ".")
        if up is not None:
            lines.append(f"Each opening has {u:.1f} unemployed people who could fill it, against {up:.1f} a year ago.")
        core = f.get("core") or {}
        if core.get("yoy_pct") is not None:
            c = core["yoy_pct"]
            band = "inside" if 1 <= c <= 3 else "above" if c > 3 else "below"
            lines.append(f"Core inflation across Canada is {_pct(c)}, {band} the Bank of Canada's 1 to 3% range.")
        cards.append({"who": "Employer", "headline": head, "lines": lines, "month": jobs["month"],
                      "note": ("StatCan grades this vacancy estimate as low quality: read it with caution."
                               if jobs.get("low_q") else "Job vacancies run a month behind the other figures.")})
    return cards


def so_what(con) -> dict:
    out = {"geos": geos(con), "cards": {}}
    for g in out["geos"]:
        out["cards"][g] = so_what_cards(so_what_facts(con, g))
    return out


def labour(con) -> dict:
    out = {"geos": geos(con), "series": {}}
    for g in out["geos"]:
        out["series"][g] = {
            "headline": columns(con, f"""SELECT month, unemployment_rate AS ur, unemployment_rate_mom_pp AS ur_mom,
                unemployment_rate_mom_significant AS ur_sig, employment_mom_k AS emp_mom,
                employment_mom_significant AS emp_sig, employment_rate, participation_rate
                FROM mart_labour_monthly WHERE geo = ? AND {HEADLINE} AND month >= '{HISTORY_START}'
                ORDER BY month""", [g]),
            "ages": columns(con, f"""SELECT month,
                max(unemployment_rate) FILTER (WHERE age_group = '15 to 24 years') AS youth,
                max(unemployment_rate) FILTER (WHERE age_group = '25 to 54 years') AS core,
                max(unemployment_rate) FILTER (WHERE age_group = '55 years and over') AS older
                FROM mart_labour_monthly WHERE geo = ? AND gender = 'Total - Gender'
                AND month >= '{HISTORY_START}' GROUP BY month ORDER BY month""", [g]),
            "jobs": columns(con, """SELECT month, job_vacancy_rate, job_vacancy_rate_grade AS grade,
                unemployed_per_vacancy FROM mart_job_market_monthly WHERE geo = ? ORDER BY month""", [g]),
        }
    return out


PRODUCTS = ["All-items", "All-items excluding food and energy", "Food", "Food purchased from stores",
            "Shelter", "Rent", "Mortgage interest cost", "Household operations, furnishings and equipment",
            "Clothing and footwear", "Transportation", "Gasoline", "Energy", "Health and personal care",
            "Recreation, education and reading",
            "Alcoholic beverages, tobacco products and recreational cannabis"]


def prices(con) -> dict:
    out = {"geos": geos(con), "series": {}}
    for g in out["geos"]:
        out["series"][g] = {
            "headline": columns(con, f"""SELECT month,
                max(yoy_pct) FILTER (WHERE product = 'All-items') AS all_items,
                max(yoy_pct) FILTER (WHERE product = 'All-items excluding food and energy') AS core
                FROM mart_cpi_monthly WHERE geo = ? AND month >= '{HISTORY_START}'
                GROUP BY month ORDER BY month""", [g]),
            "components": records(con, """SELECT product, yoy_pct, mom_pct, month FROM mart_cpi_monthly
                WHERE geo = ? AND month = (SELECT max(month) FROM mart_cpi_monthly)""", [g]),
            "shelter": columns(con, f"""SELECT month,
                max(yoy_pct) FILTER (WHERE product = 'Rent') AS rent,
                max(yoy_pct) FILTER (WHERE product = 'Mortgage interest cost') AS mortgage,
                max(yoy_pct) FILTER (WHERE product = 'Food purchased from stores') AS groceries
                FROM mart_cpi_monthly WHERE geo = ? AND month >= '{HISTORY_START}'
                GROUP BY month ORDER BY month""", [g]),
        }
    return out


def housing(con) -> dict:
    latest = records(con, """SELECT h.geo, h.geo_level, h.province_code, h.yoy_pct, h.use_with_caution, h.month
        FROM mart_housing_monthly h WHERE component = 'Total (house and land)'
        AND month = (SELECT max(month) FROM mart_housing_monthly) AND yoy_pct IS NOT NULL
        ORDER BY yoy_pct DESC""")
    all_geos = [r[0] for r in con.execute("""SELECT DISTINCT h.geo, d.sort_order, d.geo_level FROM mart_housing_monthly h
        JOIN dim_geo d USING (geo) ORDER BY d.geo_level = 'metro', d.sort_order, h.geo""").fetchall()]
    series = {g: columns(con, f"""SELECT month, yoy_pct AS v, use_with_caution AS caution, index_value AS idx
        FROM mart_housing_monthly WHERE geo = ? AND component = 'Total (house and land)'
        AND month >= '{HISTORY_START}' ORDER BY month""", [g]) for g in all_geos}
    return dict(latest=latest, geos=all_geos, series=series)


def provinces(con) -> dict:
    score = records(con, "SELECT * FROM mart_province_scorecard ORDER BY sort_order")
    ur = {g: columns(con, f"""SELECT month, unemployment_rate AS v FROM mart_labour_monthly
            WHERE geo = ? AND {HEADLINE} AND month >= '2016-01-01' ORDER BY month""", [g]) for g in geos(con)}
    cpi = {g: columns(con, """SELECT month, yoy_pct AS v FROM mart_cpi_monthly
            WHERE geo = ? AND product = 'All-items' AND month >= '2016-01-01' ORDER BY month""", [g])
           for g in geos(con)}
    return dict(scorecard=score, unemployment=ur, cpi=cpi)


def meta(con) -> dict:
    results = data_tests.run_all(con)
    loads = records(con, """SELECT table_name, source_pid, source_last_modified, row_count, max_ref_date
        FROM _load_log QUALIFY row_number() OVER (PARTITION BY table_name ORDER BY loaded_at DESC) = 1
        ORDER BY source_pid""")
    labels = {"14100287": "Labour Force Survey", "18100004": "Consumer Price Index",
              "18100205": "New Housing Price Index", "14100371": "Job vacancies",
              "36100434": "GDP by industry"}
    for row in loads:
        pid = row["source_pid"]
        row["label"] = labels.get(pid, pid)
        row["table_code"] = f"{pid[:2]}-{pid[2:4]}-{pid[4:]}"
        row["url"] = f"https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid={pid}01"
    return dict(
        built_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        sources=loads,
        tests=dict(passed=sum(r.severity == "pass" for r in results),
                   warnings=[f"{r.name} ({r.detail})" for r in results if r.severity == "warn"],
                   errors=[f"{r.name} ({r.detail})" for r in results if r.severity == "error"]),
        repo="https://github.com/lekanlawal1/project5-canada-economy-platform",
    )


def write_json(name: str, payload) -> int:
    path = DATA_DIR / f"{name}.json"
    # No spaces after separators: the files are for machines; this saves about 15%.
    path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))
    return path.stat().st_size


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        for name, fn in (("overview", overview), ("labour", labour), ("prices", prices),
                         ("housing", housing), ("provinces", provinces), ("meta", meta)):
            size = write_json(name, fn(con))
            print(f"site/data/{name}.json  {size / 1024:,.0f} KB")

    import plotly
    bundle = os.path.join(os.path.dirname(plotly.__file__), "package_data", "plotly.min.js")
    (SITE / "assets").mkdir(exist_ok=True)
    shutil.copyfile(bundle, SITE / "assets" / "plotly.min.js")
    print(f"site/assets/plotly.min.js copied from plotly {plotly.__version__}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
