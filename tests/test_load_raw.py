"""Raw layer SQL tests on tiny synthetic CSVs shaped like the real StatCan files.

They check the slicing rules (what is kept and dropped) without needing the 1.18 GB
download, so they run in CI in under a second.
"""

import duckdb

from src.config import SQL_DIR

STD = "UOM,UOM_ID,SCALAR_FACTOR,SCALAR_ID,VECTOR,COORDINATE,VALUE,STATUS,SYMBOL,TERMINATED,DECIMALS"


def run_sql(tmp_path, sql_file, header, rows):
    csv = tmp_path / "in.csv"
    csv.write_text("\n".join([header] + rows) + "\n")
    con = duckdb.connect()
    con.execute((SQL_DIR / sql_file).read_text().replace("{csv}", csv.as_posix()))
    return con


def test_lfs_keeps_estimates_and_change_errors_and_drops_trend_cycle(tmp_path):
    header = ('REF_DATE,GEO,DGUID,Labour force characteristics,Gender,Age group,Statistics,'
              'Data type,' + STD)
    tail = "Percent,239,units,0,v1,1.1,6.4,,,,1"
    rows = [
        f"2026-08,Canada,x,Unemployment rate,Total - Gender,15 years and over,Estimate,Seasonally adjusted,{tail}",
        f"2026-08,Canada,x,Unemployment rate,Total - Gender,15 years and over,Estimate,Trend-cycle,{tail}",
        f"2026-08,Canada,x,Unemployment rate,Total - Gender,15 to 19 years,Estimate,Seasonally adjusted,{tail}",
        f"2026-08,Canada,x,Unemployment rate,Total - Gender,15 years and over,Standard error of month-to-month change,Seasonally adjusted,{tail}",
    ]
    con = run_sql(tmp_path, "raw/01_raw_lfs.sql", header, rows)
    assert sorted(con.execute("SELECT data_type, age_group, statistic FROM raw_lfs").fetchall()) == [
        ("Seasonally adjusted", "15 years and over", "Estimate"),
        ("Seasonally adjusted", "15 years and over", "Standard error of month-to-month change"),
    ]


def test_cpi_drops_cities_and_unlisted_products(tmp_path):
    header = "REF_DATE,GEO,DGUID,Products and product groups," + STD
    tail = "2002=100,17,units,0,v41690973,1.2,165.1,,,,1"
    rows = [
        f"2026-08,Canada,x,All-items,{tail}",
        f'2026-08,"Toronto, Ontario",x,All-items,{tail}',
        f"2026-08,Canada,x,Fresh milk,{tail}",
    ]
    con = run_sql(tmp_path, "raw/02_raw_cpi.sql", header, rows)
    assert con.execute("SELECT geo, product FROM raw_cpi").fetchall() == [("Canada", "All-items")]


def test_gdp_keeps_sectors_and_aggregates_only(tmp_path):
    header = ('REF_DATE,GEO,DGUID,Seasonal adjustment,Prices,'
              'North American Industry Classification System (NAICS),' + STD)
    sa, ch = "Seasonally adjusted at annual rates", "Chained (2017) dollars"
    tail = "Dollars,81,millions,6,v1,1.1,2000000,,,,1"
    rows = [
        f'2026-07,Canada,x,{sa},{ch},All industries [T001],{tail}',
        f'2026-07,Canada,x,{sa},{ch},Manufacturing [31-33],{tail}',
        f'2026-07,Canada,x,{sa},{ch},Software publishers [5132],{tail}',
        f'2026-07,Canada,x,Trading-day adjusted,2017 constant prices,All industries [T001],{tail}',
    ]
    con = run_sql(tmp_path, "raw/05_raw_gdp.sql", header, rows)
    assert sorted(con.execute("SELECT naics_code FROM raw_gdp").fetchall()) == [("31-33",), ("T001",)]
