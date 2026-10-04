# Project 5: Canada Economy Intelligence Platform

A self-refreshing data platform on live Statistics Canada open data: scheduled ingestion,
SQL models with data tests, honest forecasts, a multi-page dashboard, and an AI-written
monthly briefing whose every number is verified in code. It fills the gap the other four
portfolio projects leave: a production-style, automated, tested pipeline.

## Context for whoever picks this up

- Part of Lekan Lawal's portfolio (Data Analyst, BI Analyst, AI Solutions Analyst roles in
  Canada). Earlier projects: BI dashboard, AI ticket triage, FIFA churn pipeline, NL to SQL
  agent, and Fine Print (iOS). Match their style: decisions documented with the "why",
  honest limits, evaluation before claims.
- **House style: no em dashes in any notes or documentation.** Use colons, commas or
  brackets instead.
- Free and public data only. StatCan bulk CSV downloads need no API key.
- Gemini (`gemini-3-flash-preview`) is used only for the briefing. Set
  `thinkingConfig.thinkingLevel = "low"`: in Fine Print, default thinking sometimes ran
  away to minutes per request. The key must come from an environment variable or secret,
  never a file in the repo.

## Data (all verified reachable, last updated September 2026)

Download URL pattern: `https://www150.statcan.gc.ca/n1/tbl/csv/<table>-eng.zip`

| Table | Content | Raw size |
|---|---|---|
| 14-10-0287 | Labour Force Survey: unemployment, employment by province (monthly) | 1.18 GB unzipped |
| 18-10-0004 | Consumer Price Index by region and product (monthly) | 161 MB |
| 18-10-0205 | New Housing Price Index | 9 MB |
| 14-10-0371 | Job vacancies (monthly) | 0.7 MB |
| 36-10-0434 | GDP by industry (monthly) | 57 MB |

Raw files are never committed (`data/raw/` is git-ignored). The 1.18 GB LFS file must be
streamed and filtered in DuckDB, not loaded whole into pandas.

## Phases

1. **Ingest:** an idempotent downloader that checks `Last-Modified` and skips unchanged
   tables; DuckDB reads the CSVs and keeps only needed slices.
2. **Clean and model in SQL:** raw, then staging, then marts, as versioned `.sql` files.
   Window functions for year-over-year change, 3-month averages, province rankings,
   rolling z-score anomaly flags. Every cleaning decision goes in a generated decision log.
3. **Data tests:** not-null, uniqueness, freshness, row-count sanity. Run in CI.
4. **Forecasts, honestly:** unemployment and CPI against a naive baseline, backtested with
   MAPE. If the model doesn't beat the baseline, the docs say so.
5. **Dashboard:** static multi-page site (Overview, Labour, Prices, Housing, Province
   Compare) on GitHub Pages, Plotly, one consistent look.
6. **AI briefing with a number verifier:** Gemini drafts a monthly narrative from computed
   figures; code checks every number in the text traces to the data, else falls back to a
   template. Same "AI drafts, code verifies" thesis as Fine Print.
7. **Automation:** a GitHub Actions cron job after StatCan release days rebuilds data and
   redeploys. `GEMINI_API_KEY` as a repository secret (the user adds it).

## Manual steps for the user
- Add `GEMINI_API_KEY` as a GitHub Actions secret when phase 6 starts.
- Turn on GitHub Pages for the dashboard when phase 5 is done.
