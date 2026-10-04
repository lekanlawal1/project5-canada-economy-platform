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
}


def table_url(pid: str) -> str:
    return URL_PATTERN.format(pid=pid)
