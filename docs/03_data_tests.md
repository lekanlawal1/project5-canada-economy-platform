# Phase 3: Data tests

```bash
python -m pytest              # unit tests: logic on hand-made data, offline, 3 seconds
python -m src.data_tests      # data tests: the real warehouse, after python -m src.build
```

Both run in GitHub Actions on every push (`.github/workflows/ci.yml`). A data test error
fails the run; in phase 7 that will also block the dashboard from being redeployed with bad
data.

## Two kinds of test, on purpose

| | Unit tests (`tests/`) | Data tests (`src/data_tests.py`) |
|---|---|---|
| Question | Is the logic right? | Is today's data sane? |
| Data | Tiny hand-made rows with a known answer | The real StatCan download |
| Example | A month missing from a series gives a NULL change, not a 2 month change | No duplicate keys in 12 tables |
| Network | None | Downloads about 85 MB |

Correct logic can still produce wrong output if StatCan changes its data, so both are needed.

## What the data tests check (75 checks)

| Group | Checks | Severity |
|---|---|---|
| Unique keys | 12 tables, each on its natural key | error |
| Not null | Keys and promised value columns | error |
| Business rules | CPI base is 2002=100; codes valid; rates within 0 to 100; indexes positive; labour force = employment + unemployment; all 20 GDP sectors present and summing to the total within 2%; latest month has every province | error |
| Freshness | Each table's latest month versus today | warn when one release late, error when two |
| Official figures | 7 CPI and 4 LFS numbers copied from StatCan's releases | error for CPI, warn for LFS |
| Row counts | Versus `data/row_counts.json` from the last good run | error if a table shrinks, warn if it grows over 10% |

## Decisions and why

**Checked against StatCan's own published numbers.** The tests compare our computed figures
with the figures in StatCan's official releases (The Daily). All 11 match today: for
example, CPI all-items 3.0% in August 2026, gasoline 22.8%, unemployment 6.4%. This
is the strongest test in the suite, because it checks the whole chain (download, slice,
clean, compute, round) against an independent answer.

**CPI reference checks are errors; LFS ones are warnings.** CPI is never revised once
published, so a mismatch can only mean our pipeline is wrong. Seasonally adjusted LFS
figures are revised every January when StatCan updates seasonal factors, so an LFS mismatch
in January is expected; it warns, and the reference values get re-pinned.

**Freshness has a warning band.** A table one release behind warns; two behind fails. A
single StatCan delay should not page anyone, but a missed release should stop deployment.
Thresholds come from each table's normal publishing lag (LFS about 1 month after the
reference month, vacancies and GDP about 2.5).

**Row counts are compared with the last good run, not a fixed number.** Rows grow by
about a month of data each release, so a fixed number would be wrong next month. A shrink
is an error (StatCan dropped data or one of our filters broke); growth over 10% is a
warning (a filter may have widened by accident). `--update-baseline` saves new counts, and
only after a run with zero errors, so a bad build can never become the new baseline.

**GDP sectors are allowed to miss the total by 2%.** Chained-dollar GDP is not exactly
additive: each industry is deflated with its own price index. Measured gap: 0.3% on
average, 0.86% at worst, since 1997. The 2% limit catches a missing large sector without
failing on the method itself. It cannot see a missing small one (management of companies
is 0.02% of GDP, arts and recreation 0.83%), so a separate check counts that all 20
sectors are present in the latest month.

## Proof the tests can fail

A test suite that has never failed proves little. Six realistic faults were injected into a
copy of the real warehouse; each was caught by the check designed for it:

| Fault injected | Caught by |
|---|---|
| Duplicate CPI row | unique key on `stg_cpi` |
| StatCan rebases one CPI series to 202404=100 | CPI base rule |
| NULL unemployment rate in the scorecard | not null on the scorecard |
| CPI headline changed from 3.0 to 3.1 | official figure check |
| Quebec missing from the latest labour month | completeness rule and row count |
| GDP rows before 2000 deleted | row count shrink |

A simulated run date of January 2027 also failed every freshness check, as it should.

Writing the unit tests caught one real bug: a value DuckDB returned as `Decimal` could not
be compared with a float, which would have crashed the official figure check.

## Honest limits

- **Reference values are hand-copied** from The Daily. They cover only August 2026 and need
  re-pinning after LFS revisions. Scraping releases automatically would be brittle.
- **The checks catch broken data, not wrong-but-plausible data.** A StatCan error that
  stays within every rule passes.
- **Freshness depends on the run date.** Run the tests against an old build and they will
  fail on freshness alone, by design.
