"""Load the raw layer: slice each downloaded CSV into a DuckDB table using sql/raw/*.sql.

Each run also appends to a _load_log table (table name, source product ID, StatCan's
Last-Modified, row count, max reference month, load time). Why: the freshness and
row-count data tests in phase 3 need a history to compare against, and it makes every
number on the dashboard traceable to a specific StatCan release.

Usage:
    python -m src.load_raw
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone

import duckdb

from src.config import DB_PATH, RAW_MODELS, SQL_DIR
from src.ingest import csv_path, load_manifest

MEMORY_LIMIT = "500MB"

LOG_DDL = """
CREATE TABLE IF NOT EXISTS _load_log (
    table_name       VARCHAR,
    source_pid       VARCHAR,
    source_last_modified VARCHAR,
    row_count        BIGINT,
    max_ref_date     VARCHAR,
    loaded_at        TIMESTAMP
)
"""


def load(con: duckdb.DuckDBPyConnection, manifest: dict) -> list[tuple]:
    con.execute(LOG_DDL)
    results = []
    for table, (pid, sql_file) in RAW_MODELS.items():
        src = csv_path(pid)
        if not src.exists():
            raise FileNotFoundError(f"{src} missing; run `python -m src.ingest` first")
        # Path is substituted as text because DuckDB does not accept a bound parameter in
        # the FROM clause of a CREATE TABLE AS. The path comes from our own config, not user input.
        sql = (SQL_DIR / sql_file).read_text().replace("{csv}", src.as_posix())
        start = time.perf_counter()
        con.execute(sql)
        rows, max_ref = con.execute(f"SELECT count(*), max(ref_date) FROM {table}").fetchone()
        con.execute(
            "INSERT INTO _load_log VALUES (?, ?, ?, ?, ?, ?)",
            [table, pid, manifest.get(pid, {}).get("last_modified"), rows, max_ref,
             datetime.now(timezone.utc).replace(tzinfo=None)],
        )
        results.append((table, rows, max_ref, time.perf_counter() - start))
    return results


def configure(con: duckdb.DuckDBPyConnection) -> None:
    # Progress bars flood CI logs with carriage returns.
    con.execute("SET enable_progress_bar = false")
    # Cap DuckDB's buffer pool so a small CI runner is safe. Measured on the 1.18 GB LFS
    # file: peak process memory about 830 MB uncapped (DuckDB uses spare RAM for parallel
    # scans), about 660 MB with this cap, same rows, same speed. The limit covers DuckDB's
    # buffers, not the whole Python process, so total memory sits a little above it.
    con.execute(f"SET memory_limit = '{MEMORY_LIMIT}'")


def main() -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(DB_PATH)) as con:
        configure(con)
        for table, rows, max_ref, secs in load(con, load_manifest()):
            print(f"{table:20s} {rows:>9,} rows  latest {max_ref}  ({secs:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
