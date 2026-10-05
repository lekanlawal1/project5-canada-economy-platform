# Phase 4: Forecasts, honestly

```bash
python -m src.forecast    # about 2 minutes: backtest, scores, published forecast
```

The rules were written and committed **before** any result existed:
[04_forecast_protocol.md](04_forecast_protocol.md) (commit `46f3b0a`). Full generated
tables: [forecast_results.md](forecast_results.md).

## Headline

**Simple baselines are hard to beat, and mostly the models do not beat them.**

| Target | 1 month ahead | 3 months ahead | 6 months ahead |
|---|---|---|---|
| CPI inflation | **Model wins.** Seasonal ARIMA cuts error 19% (p < 0.001) | Model 16% lower error, not significant (p = 0.10). Naive published | Model 19% lower error, not significant (p = 0.23). Naive published |
| Unemployment rate | **Naive wins.** Both models are significantly worse (ARIMA 12% worse, p < 0.001) | Naive wins | Smoothing model 9.5% lower error, not significant (p = 0.32). Naive published |

Backtest: 199 monthly forecast origins, January 2010 to July 2026, 5,895 scored forecasts.
Scores above exclude COVID targets (March 2020 to December 2021), as the protocol set out
in advance. Including COVID changes no decision.

## What this means in plain words

**Unemployment behaves almost like a random walk at short horizons.** The best guess for
next month is this month: off by 0.12 points on average. ARIMA and exponential smoothing
read patterns into month-to-month noise and do worse. This matches the economics
literature, and a dashboard that claimed otherwise would be selling false precision.

**Inflation has a seasonal pattern a model can use, but only for the next month.** The
seasonal ARIMA learns that some months reliably push prices up or down (an unadjusted
series has these patterns), which gives a real 19% improvement one month out. At 3 and 6
months it still shows 16 to 19% lower error, but the evidence is too noisy to be confident,
so the rule publishes the naive forecast.

## Decisions and why

**The rules were fixed before the results.** Otherwise it is easy, even without meaning to,
to try models and periods until one looks good. The commit history proves the order.

**"Beats the baseline" needs significance, not just a lower average.** A Diebold-Mariano
test asks whether the difference in errors is larger than chance. Multi-month forecasts
made one month apart share most of their target window, so their errors are correlated; the
test's variance is corrected for that (Newey-West, lag h-1), or it would find significance
that is not there.

**The rule cost the model two horizons, and the rule stands.** CPI at 3 and 6 months shows
16 to 19% lower error, not significant. Loosening the rule after seeing this would undo the
reason for having one. In an interview: "the model may well be better, but 15 years of
monthly data cannot show it with confidence, so the dashboard says so."

**MAE is the main metric; MAPE is reported but not trusted for inflation.** Inflation was
as low as -0.4% in 2020, and a percentage error of a number near zero explodes. So CPI's
MAPE is computed on the index level, which is never near zero.

**Forecast ranges come from the track record, not the model's formula.** The 80% range is
the forecast plus the 10th and 90th percentiles of that method's actual backtest errors.
It needs no assumption that errors are normal, and it is exactly as wide as the method's
history says it should be.

**No look-ahead, tested.** A test corrupts every value after the forecast origin (adds 50
points to unemployment, triples the CPI index) and checks the forecasts do not change by
a single decimal. Run on the real data too: change 0.0.

**Two baselines turned out to be one.** The protocol listed a naive and a seasonal naive
baseline for CPI. Working through the formulas showed they are algebraically identical
(carrying the last 12-month rate forward is the same as repeating last year's monthly
pattern). It is reported once, and no new baseline was added after the fact.

## Published forecast (from August 2026)

| Target | For | Method | Forecast | 80% range |
|---|---|---|---|---|
| CPI inflation | Sep 2026 | Seasonal ARIMA | 2.9% | 2.5 to 3.2 |
| CPI inflation | Nov 2026 | Naive | 3.0% | 2.2 to 3.9 |
| CPI inflation | Feb 2027 | Naive | 3.0% | 1.8 to 4.0 |
| Unemployment rate | Sep 2026 | Naive | 6.4% | 6.2 to 6.6 |
| Unemployment rate | Nov 2026 | Naive | 6.4% | 6.1 to 6.6 |
| Unemployment rate | Feb 2027 | Naive | 6.4% | 6.0 to 6.8 |

The CPI naive forecast is stored as 3.03, because it is computed from unrounded index
values; it displays as 3.0, matching StatCan's published rate.

## Engineering note

The first version ran origins in a process pool and was still going after 10 minutes.
Profiling showed each origin takes about 0.6 seconds; the pool was slower because every
worker's maths library also spawned threads, and they fought over 4 cores. A plain loop
finishes in 95 seconds, so the parallelism was removed. The first version also held the
database write lock for the whole run; it now reads, closes, computes, then writes.

## Reproducibility

The decisions reproduce exactly; the third decimal does not. The same code, the same data and
identical package versions (statsmodels 0.15.0, numpy 2.4.6, scipy 1.17.1) gave slightly
different scores on this development machine and on GitHub's runner: the CPI 1-month model's
improvement was 19.2% in one and 19.7% in the other, and a 3-month p-value 0.100 versus 0.091.
The cause is the model fitting itself: the optimiser stops at very slightly different points
on different processors. Every published decision was identical on both machines, and the
figures quoted in these docs are rounded accordingly. The latest exact numbers are always in
the generated [forecast_results.md](forecast_results.md).

## Honest limits

- **Today's data, not real-time data.** Seasonally adjusted LFS history is revised, so
  forecasters at the time saw slightly different numbers. Errors here are somewhat
  optimistic for unemployment. CPI is never revised, so its results are unaffected.
- **Several tests, one threshold.** 9 significance tests at 0.05 means some chance of a
  false positive. The one claimed win (CPI, 1 month, p < 0.001) would survive a Bonferroni
  correction (0.05 / 9 = 0.0056).
- **Only univariate models.** None uses other data (oil prices, interest rates, job
  vacancies). Those could do better, and are a natural next step, with the same protocol.
- **The ranges assume the future errs like the past.** After a shock like 2020, they will
  be too narrow.
