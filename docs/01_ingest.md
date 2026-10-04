# Phase 1: Ingest

Two steps, both re-runnable at any time:

```bash
pip install -r requirements.txt
python -m src.ingest      # download only the StatCan tables that changed
python -m src.load_raw    # slice each CSV into DuckDB (data/economy.duckdb)
python -m pytest          # offline tests, no download needed
```

## What gets downloaded

| Table | Content | Zip | Unzipped | Rows | Rows kept | Latest month |
|---|---|---|---|---|---|---|
| 14-10-0287 | Labour Force Survey | 60 MB | 1,180 MB | 5,466,528 | 2,033,152 | 2026-08 |
| 18-10-0004 | Consumer Price Index | 15 MB | 161 MB | 1,152,913 | 93,896 | 2026-08 |
| 18-10-0205 | New Housing Price Index | 0.4 MB | 9 MB | 65,760 | 65,760 | 2026-08 |
| 14-10-0371 | Job vacancies | 0.05 MB | 0.7 MB | 5,460 | 5,460 | 2026-07 |
| 36-10-0434 | GDP by industry | 7 MB | 57 MB | 265,185 | 11,715 | 2026-07 |

Measured on 4 October 2026. A full first download took 18 seconds and the raw load took
about 5 seconds. The resulting DuckDB file is 20 MB, so 1.4 GB of CSV becomes 20 MB of
queryable data.

## Decisions and why

**Only download what changed.** Each request is a conditional GET carrying the
`Last-Modified` and `ETag` from the previous download. Verified against the live server:
StatCan answers `304 Not Modified` to both headers, so a run on a day with no new release
costs five tiny requests instead of 85 MB of zips. A second run right after the first
skips all five tables.

**The manifest is committed, the data is not.** `data/manifest.json` records each table's
`Last-Modified`, `ETag`, size and SHA-256. CI runners start empty, so this file is the
only way the scheduled job can ask "did StatCan publish anything?" without downloading.
`python -m src.ingest --check` answers that and exits with code 1 when something changed.

**A table is skipped only if it is unchanged and present on disk.** A fresh clone has the
manifest but no CSVs, and must still download. A test covers exactly this case.

**No half-written files.** Downloads go to a `.part` file, the byte count is checked
against `Content-Length`, and only then is the file renamed into place. A dropped
connection cannot leave a truncated zip that a later run would trust.

**Stream, never load whole.** The zip is unpacked by streaming the data CSV out of it (the
metadata CSV is skipped and the zip deleted). DuckDB then scans the CSV and applies the
filters during the scan. Measured peak memory for the 1.18 GB file: about 830 MB
uncapped, about 660 MB with DuckDB's buffer pool capped at 500 MB, same result either way.
Loading the same file into pandas as text would need several GB.

## What each raw table keeps, and why

Profiled every column first, then chose the slices. The full reasoning is in the comment
at the top of each file in `sql/raw/`.

- **Labour Force Survey:** the estimate and its standard error (so the dashboard can say
  whether a monthly move is real or within sampling noise), seasonally adjusted and
  unadjusted series. Trend-cycle is dropped because StatCan revises its latest points
  heavily. Four non-overlapping age groups. Canada and the 10 provinces (this table does not
  cover the territories).
- **CPI:** Canada and the 10 provinces, and 15 product groups: all-items, the core measure
  excluding food and energy, the 8 major components, and the series people ask about most
  (rent, mortgage interest, gasoline, groceries, energy). City series are dropped because
  many are short or discontinued.
- **New Housing Price Index and job vacancies:** small, kept whole.
- **GDP:** seasonally adjusted at annual rates, in chained 2017 dollars (StatCan's
  headline real GDP measure). The all-industry total, the 2-digit sectors and StatCan's
  special aggregates (goods vs services, energy sector, and so on). Finer sub-sector detail
  is dropped as too granular for a monthly overview.

## Traps found while profiling

- **CPI mixes 11 index bases** (`2002=100`, `201812=100`, and others) in one file.
  Year-over-year math across different bases would be wrong. Every series kept uses
  `2002=100` today; phase 3 adds a test that fails loudly if StatCan ever rebases one.
- **Job vacancy `STATUS` is a quality grade** from A (excellent) to F (unreliable), not
  a footnote. 115 rows are graded F. The grade is kept so the dashboard can grey out weak
  estimates instead of presenting them with false confidence.
- **The release months differ:** LFS, CPI and NHPI run to August 2026, while job vacancies
  and GDP run to July. Every chart and the AI briefing must state each figure's own
  reference month rather than assuming one "current month".

## Honest limits

- The slices are chosen for this dashboard. A new question (for example, city-level CPI)
  means widening a `WHERE` clause and re-running, which takes seconds.
- StatCan revises past months. The pipeline always reloads the latest file, so history can
  change between runs. Snapshotting each release to measure revisions is out of scope.
- `_load_log` records every load, but nothing reads it yet. The freshness and row-count
  tests in phase 3 will.
