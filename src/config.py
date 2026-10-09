"""Single source of truth for which StatCan tables the platform uses and where files live."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
# The manifest is committed (data/raw is not). Why: CI runners start empty, so the only way
# a scheduled job can tell "StatCan published nothing new" without downloading 1+ GB is to
# compare live Last-Modified headers against what the last successful run recorded.
MANIFEST_PATH = ROOT / "data" / "manifest.json"
DB_PATH = ROOT / "data" / "economy.duckdb"

URL_PATTERN = "https://www150.statcan.gc.ca/n1/tbl/csv/{pid}-eng.zip"

# Product IDs are the 8 digit form StatCan uses in URLs (14-10-0287 becomes 14100287).
TABLES = {
    "14100287": "Labour Force Survey: labour force characteristics by province, monthly",
    "18100004": "Consumer Price Index, monthly, not seasonally adjusted",
    "18100205": "New Housing Price Index, monthly",
    "14100371": "Job vacancies, payroll employees and job vacancy rate, monthly",
    "36100434": "GDP at basic prices by industry, monthly",
    "18100007": "Basket weights of the Consumer Price Index, annual",
}


SQL_DIR = ROOT / "sql"

# Which raw-layer SQL file slices which downloaded table.
RAW_MODELS = {
    "raw_lfs": ("14100287", "raw/01_raw_lfs.sql"),
    "raw_cpi": ("18100004", "raw/02_raw_cpi.sql"),
    "raw_nhpi": ("18100205", "raw/03_raw_nhpi.sql"),
    "raw_job_vacancies": ("14100371", "raw/04_raw_job_vacancies.sql"),
    "raw_gdp": ("36100434", "raw/05_raw_gdp.sql"),
    "raw_cpi_weights": ("18100007", "raw/06_raw_cpi_weights.sql"),
}


def table_url(pid: str) -> str:
    return URL_PATTERN.format(pid=pid)
