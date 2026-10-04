# Phase 4: Forecast evaluation protocol (written before any results)

This file was committed before the backtest was run, so the rules below could not be bent
to fit the results. The results are in [04_forecasts.md](04_forecasts.md).

## What is forecast

| Target | Series | Why |
|---|---|---|
| Unemployment rate | Canada, 15+, all genders, seasonally adjusted, % | The headline labour number |
| CPI inflation | Canada, all-items, 12-month % change | The headline price number, and what the Bank of Canada targets |

Horizons: 1, 3 and 6 months ahead.

## Methods

Baselines (no fitting, no parameters):

- **Naive:** the next months equal the last known value. For inflation, the last known
  12-month rate carries forward.
- **Seasonal naive (CPI only):** each future month's index moves by the same percentage as
  the same month one year earlier. Strong for an unadjusted series with a seasonal pattern.

Models (refit at every forecast origin on data up to that origin only):

- **Unemployment, ARIMA(p,1,q):** the order is chosen once by AIC over p, q in 0 to 2, using
  only data up to December 2009 (before the first backtest origin), then held fixed.
- **Unemployment, damped trend exponential smoothing.**
- **CPI, seasonal ARIMA (0,1,1)(0,1,1)12 on the log index** (the classic "airline" model,
  fixed in advance, no search). Training starts January 1992, after the Bank of Canada
  adopted inflation targeting, so the model does not learn the 1970s and 80s regime.
  A 12-month rate is then computed from the forecast index and the actual index 12 months
  earlier, which is already known at the origin for horizons up to 12.

## Backtest

- Rolling origin, expanding window: one forecast origin per month from January 2010 to the
  latest month for which the 6-month-ahead actual exists.
- A model only ever sees data up to its origin. No future data, no tuning on the test period.
- Data used is today's StatCan vintage. Real-time forecasters saw earlier, unrevised data,
  so these errors are somewhat optimistic for the seasonally adjusted labour series. CPI is
  never revised, so this does not apply to it.

## Scoring

- **MAE** (mean absolute error, in percentage points) is the primary metric for both targets.
- **MAPE** is reported as the plan requires, with one deliberate change: for inflation it is
  computed on the index level, not the rate. Inflation was near 0% in 2020 (as low as -0.4%),
  and percentage errors of a number near zero explode, so MAPE of the rate would be
  dominated by a few months and say nothing useful.
- **Skill** = 1 minus model MAE / baseline MAE. Positive means better than the baseline.
- **Diebold-Mariano test** on absolute errors, with variance corrected for overlapping
  multi-month forecasts (Newey-West, lag h-1) and the Harvey small-sample adjustment.

## Periods

Every score is reported twice, decided now:

1. **All targets** from 2010 on.
2. **Excluding COVID:** targets from March 2020 to December 2021 removed. The pandemic was a
   one-off shock no time series model could forecast; including it lets 22 months decide a
   15-year comparison. Both views are always shown, so the exclusion cannot hide anything.

## Decision rule

At each horizon, a model **beats the baseline** only if, in the excluding-COVID period, its
MAE is lower than every baseline's AND the Diebold-Mariano p-value is below 0.05 against the
best baseline. A lower MAE without significance is reported as "no evidence of improvement".

The dashboard publishes the forecast of the winning method at each horizon. If no model
wins, it publishes the naive forecast and says so. Forecast ranges come from the empirical
10th and 90th percentiles of that method's backtest errors at that horizon (excluding COVID).
