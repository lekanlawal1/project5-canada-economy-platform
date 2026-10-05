# Canada Economy Intelligence Platform

**Live dashboard: https://lekanlawal1.github.io/project5-canada-economy-platform/**

A self-refreshing data platform on Statistics Canada open data. Every weekday it checks
whether StatCan published anything new; when it did, it downloads the tables, rebuilds a
tested SQL warehouse, re-runs backtested forecasts, has an AI draft a monthly briefing whose
every number is checked by code, and redeploys the dashboard. No server, no cost, no manual
steps.

```mermaid
flowchart LR
    S[StatCan: 5 tables, 1.4 GB of CSV] -->|ingest: only what changed| R[Raw slices]
    R -->|SQL| ST[Staging] -->|SQL| M[Marts]
    M --> T{80 data tests}
    T -->|any error| X[Stop: live site keeps last good version]
    T -->|pass| F[Forecasts, backtested]
    F --> E[Dashboard JSON]
    E --> B[Gemini briefing, every number verified]
    B --> P[GitHub Pages]
```

## What it shows

Five pages: **Overview** (headline numbers, forecasts, GDP, unusual moves, AI briefing),
**Labour**, **Prices**, **Housing** and **Province compare**. Every chart has a table view,
dark mode, and works on phones and tablets (tested at iPhone SE to iPad Pro sizes).

## Results worth knowing

- **Matches StatCan's official releases exactly.** 11 headline figures (CPI 3.0%, gasoline
  22.8%, unemployment 6.4%, and more) are compared with StatCan's published numbers on every
  build. All 11 match.
- **Most monthly job moves are noise.** Each change is tested against StatCan's own margin
  of error. August 2026's employment drop of 41,700 sounds like news; it is not significant,
  and the chart shows it grey.
- **Simple forecasts are hard to beat, and the dashboard says so.** Backtested on 199 monthly
  origins (2010 to 2026) under rules committed before any result: a seasonal model beats the
  no-change forecast for next month's inflation (19% less error, p < 0.001). For unemployment,
  no model beats "next month equals this month", so that is what the site publishes.
- **The AI briefing cannot publish a wrong number.** Code checks every number in the draft for
  the right value, the right measure and the right direction. It caught 15 of 15 planted
  errors with 0 false alarms on correct drafts. A failed draft gets one retry, then a verified
  template is published instead. In 30 live Gemini runs, the first batch published an AI draft
  only 5 times in 10; reading every failure led to fixes on both sides (mostly verifier false
  alarms), and the next 20 runs all published a verified AI draft.

## Engineering highlights

| Area | What and why |
|---|---|
| Ingest | Conditional downloads (`304 Not Modified`), atomic writes, and the 1.18 GB labour file streamed through DuckDB, never loaded into memory whole |
| SQL models | Raw, staging, marts as versioned `.sql` files; prior months joined by calendar date because suppressed cells leave gaps that would break `LAG()` |
| Anomalies | Robust z-scores (median and MAD): a classic z-score called the September 2020 unemployment drop normal because COVID inflated the variance |
| Data tests | 80 checks: keys, nulls, business rules, freshness with a warning band, row counts against the last good run, and StatCan's official figures. Each failure mode was proven by injecting it |
| Forecasts | Rolling-origin backtest, Diebold-Mariano significance test, ranges from real past errors |
| AI | Gemini drafts, code verifies, template fallback, model output escaped as untrusted input |
| Automation | Daily cheap check, full rebuild only on new data, refreshed manifest committed back so the next check compares against what was published |

Every decision, with its reason and its limits, is written up in `docs/`.

## Run it locally

```bash
pip install -r requirements.txt
python -m src.ingest          # download (about 85 MB of zips)
python -m src.build           # raw, staging, marts, decision log (about 10 s)
python -m src.forecast        # backtest and forecasts (about 2 min)
python -m src.data_tests      # 80 checks against the real data
python -m src.site_export     # dashboard data
python -m src.briefing        # needs GEMINI_API_KEY for the AI path; template otherwise
cd site && python -m http.server   # open http://localhost:8000
python -m pytest              # unit tests, offline
```

## Documentation

| Doc | Covers |
|---|---|
| [01_ingest.md](docs/01_ingest.md) | Downloads, slicing, traps found while profiling |
| [02_models.md](docs/02_models.md) | SQL layers, significance, anomalies, check against official figures |
| [decision_log.md](docs/decision_log.md) | Every cleaning decision with rows affected, regenerated each build |
| [03_data_tests.md](docs/03_data_tests.md) | The 80 checks and proof each can fail |
| [04_forecast_protocol.md](docs/04_forecast_protocol.md) | Evaluation rules, committed before results |
| [04_forecasts.md](docs/04_forecasts.md) | Results in plain words |
| [05_dashboard.md](docs/05_dashboard.md) | Design decisions and browser testing |
| [06_briefing.md](docs/06_briefing.md) | The number verifier and its evaluation |
| [07_automation.md](docs/07_automation.md) | Schedule, refresh logic and failure handling |

## Honest limits

- Forecasts use each series' own history only; no outside drivers.
- The verifier checks numbers, not reasoning, and has two documented gaps.
- StatCan revises history; the platform always uses the latest vintage and does not track revisions.
- Data: Statistics Canada, under the Open Government Licence: Canada.
