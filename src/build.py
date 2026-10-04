"""Build the warehouse: raw slices, then staging, then marts, then the decision log.

Every layer is rebuilt from scratch on each run (CREATE OR REPLACE). Why not incremental:
the whole build takes seconds, and StatCan revises past months, so an incremental build
would need revision tracking to stay correct. Full rebuilds are simpler and always right.

Files run in filename order within each layer, which is why they carry numeric prefixes.

Usage:
    python -m src.build
"""

from __future__ import annotations

import sys
import time

import duckdb

from src import decision_log, load_raw
from src.config import DB_PATH, SQL_DIR
from src.ingest import load_manifest

LAYERS = ["staging", "marts"]


def run_layer(con: duckdb.DuckDBPyConnection, layer: str) -> None:
    for path in sorted((SQL_DIR / layer).glob("*.sql")):
        start = time.perf_counter()
        con.execute(path.read_text())
        table = path.stem.split("_", 1)[1]
        rows = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        print(f"  {layer}/{path.name:32s} {rows:>9,} rows  ({time.perf_counter() - start:.1f}s)")


def build(con: duckdb.DuckDBPyConnection) -> None:
    print("raw")
    for table, rows, max_ref, secs in load_raw.load(con, load_manifest()):
        print(f"  {table:39s} {rows:>9,} rows  ({secs:.1f}s)  latest {max_ref}")
    for layer in LAYERS:
        print(layer)
        run_layer(con, layer)
    path = decision_log.write(con)
    print(f"decision log written to {path.relative_to(SQL_DIR.parent)}")


def main() -> int:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(DB_PATH)) as con:
        load_raw.configure(con)
        build(con)
    return 0


if __name__ == "__main__":
    sys.exit(main())
