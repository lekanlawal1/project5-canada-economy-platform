"""Forecasts with an honest backtest, following docs/04_forecast_protocol.md exactly.

Writes three tables to the warehouse:
    forecast_backtest  every backtest forecast next to the actual value
    forecast_scores    MAE, MAPE, skill and Diebold-Mariano p-value per method and horizon
    forecast_latest    the published forecast: winning method per horizon, with a range

and the generated results table docs/forecast_results.md.

Usage:
    python -m src.forecast
"""

from __future__ import annotations

import sys
import time
import warnings
from datetime import datetime, timezone

import duckdb
import numpy as np
import pandas as pd
from scipy import stats

from src.config import DB_PATH, ROOT

HORIZONS = [1, 3, 6]
MAX_H = max(HORIZONS)
BACKTEST_START = pd.Period("2010-01", "M")
ORDER_SELECTION_END = pd.Period("2009-12", "M")
CPI_TRAIN_START = pd.Period("1992-01", "M")
COVID = (pd.Period("2020-03", "M"), pd.Period("2021-12", "M"))
RESULTS_PATH = ROOT / "docs" / "forecast_results.md"

# --------------------------------------------------------------------------- data


def load_series(con) -> tuple[pd.Series, pd.Series, pd.Series]:
    ur = con.execute(
        "SELECT month, unemployment_rate FROM mart_labour_monthly WHERE geo = 'Canada' "
        "AND gender = 'Total - Gender' AND age_group = '15 years and over' ORDER BY month"
    ).fetchdf()
    cpi = con.execute(
        "SELECT month, index_value, yoy_pct FROM mart_cpi_monthly WHERE geo = 'Canada' "
        "AND product = 'All-items' ORDER BY month"
    ).fetchdf()
    to_idx = lambda df: pd.PeriodIndex(pd.to_datetime(df["month"]), freq="M")
    unemployment = pd.Series(ur["unemployment_rate"].values, index=to_idx(ur), name="unemployment")
    cpi_index = pd.Series(cpi["index_value"].values, index=to_idx(cpi), name="cpi_index")
    cpi_yoy = pd.Series(cpi["yoy_pct"].values, index=to_idx(cpi), name="cpi_yoy")
    for s in (unemployment, cpi_index):
        expected = pd.period_range(s.index.min(), s.index.max(), freq="M")
        if len(s) != len(expected):
            raise ValueError(f"{s.name} has gaps; the models assume a complete monthly series")
    return unemployment, cpi_index, cpi_yoy


# --------------------------------------------------------------------------- methods
# Each method takes the history up to the origin and returns MAX_H forecasts.


def naive(y: pd.Series) -> np.ndarray:
    return np.repeat(float(y.iloc[-1]), MAX_H)


def select_arima_order(y: pd.Series) -> tuple[int, int, int]:
    """AIC search over p, q in 0..2 with d=1, on data up to ORDER_SELECTION_END only."""
    from statsmodels.tsa.arima.model import ARIMA

    train = y[y.index <= ORDER_SELECTION_END]
    best = None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for p in range(3):
            for q in range(3):
                aic = ARIMA(train.values, order=(p, 1, q)).fit().aic
                if best is None or aic < best[0]:
                    best = (aic, (p, 1, q))
    return best[1]


def arima(y: pd.Series, order: tuple[int, int, int]) -> np.ndarray:
    from statsmodels.tsa.arima.model import ARIMA

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return np.asarray(ARIMA(y.values, order=order).fit().forecast(MAX_H))


def damped_ets(y: pd.Series) -> np.ndarray:
    from statsmodels.tsa.holtwinters import ExponentialSmoothing

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = ExponentialSmoothing(y.values, trend="add", damped_trend=True).fit()
        return np.asarray(fit.forecast(MAX_H))


def cpi_naive_index(idx: pd.Series) -> np.ndarray:
    """Carry the last 12-month rate forward, expressed as an index path.

    idx[T+h] = idx[T+h-12] * idx[T] / idx[T-12]. Note this is algebraically identical to the
    'seasonal naive' index forecast idx[T] * idx[T+h-12] / idx[T-12], so the protocol's two
    CPI baselines are one and the same; it is reported once.
    """
    t = len(idx) - 1
    return np.array([idx.iloc[t + h - 12] * idx.iloc[t] / idx.iloc[t - 12] for h in range(1, MAX_H + 1)])


def cpi_airline(idx: pd.Series) -> np.ndarray:
    from statsmodels.tsa.statespace.sarimax import SARIMAX

    train = idx[idx.index >= CPI_TRAIN_START]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = SARIMAX(np.log(train.values), order=(0, 1, 1), seasonal_order=(0, 1, 1, 12)).fit(disp=False)
        return np.exp(np.asarray(fit.forecast(MAX_H)))


# --------------------------------------------------------------------------- backtest


def _forecast_origin(args):
    """All methods at one origin. Top level so it can run in a worker process."""
    origin, unemployment, cpi_index, order = args
    rows = []
    hist_u = unemployment[unemployment.index <= origin]
    for method, fc in (("naive", naive(hist_u)), (f"arima{order}", arima(hist_u, order)),
                       ("damped_ets", damped_ets(hist_u))):
        rows += [("unemployment", method, origin, h, origin + h, float(fc[h - 1]), None) for h in range(1, MAX_H + 1)]
    hist_c = cpi_index[cpi_index.index <= origin]
    for method, path in (("naive", cpi_naive_index(hist_c)), ("sarima_airline", cpi_airline(hist_c))):
        for h in range(1, MAX_H + 1):
            base = cpi_index[origin + h - 12]  # known at the origin for h <= 12
            rows.append(("cpi_yoy", method, origin, h, origin + h,
                         100 * (path[h - 1] / base - 1), float(path[h - 1])))
    return rows


def run_backtest(unemployment, cpi_index, cpi_yoy, order, origins) -> pd.DataFrame:
    # Serial on purpose: about 0.6 s per origin, 2 minutes in total. A process pool was
    # slower here, because each worker's maths library also spawned threads and they fought
    # over the same 4 cores.
    rows = [r for o in origins for r in _forecast_origin((o, unemployment, cpi_index, order))]
    df = pd.DataFrame(rows, columns=["series", "method", "origin", "horizon", "target",
                                     "forecast", "forecast_index"])
    actual = {"unemployment": unemployment, "cpi_yoy": cpi_yoy}
    df["actual"] = [actual[s].get(t, np.nan) for s, t in zip(df["series"], df["target"])]
    df["actual_index"] = [cpi_index.get(t, np.nan) if s == "cpi_yoy" else np.nan
                          for s, t in zip(df["series"], df["target"])]
    df = df.dropna(subset=["actual"])
    df["error"] = df["actual"] - df["forecast"]
    df["covid_target"] = df["target"].apply(lambda t: COVID[0] <= t <= COVID[1])
    return df


# --------------------------------------------------------------------------- scoring


def diebold_mariano(e_model: np.ndarray, e_base: np.ndarray, h: int) -> float:
    """Two-sided p-value that absolute errors differ. HAC variance (lag h-1), Harvey correction."""
    d = np.abs(e_model) - np.abs(e_base)
    n = len(d)
    if np.allclose(d, 0):
        return 1.0  # identical errors: no evidence of any difference
    dc = d - d.mean()
    gamma = [np.dot(dc[k:], dc[: n - k]) / n for k in range(h)]
    var = (gamma[0] + 2 * sum(gamma[1:])) / n
    if var <= 0:
        var = gamma[0] / n
    dm = d.mean() / np.sqrt(var)
    dm *= np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    return float(2 * stats.t.sf(abs(dm), df=n - 1))


def score(bt: pd.DataFrame) -> pd.DataFrame:
    out = []
    for period, sub in (("all", bt), ("excluding_covid", bt[~bt["covid_target"]])):
        for (series, h), grp in sub[sub["horizon"].isin(HORIZONS)].groupby(["series", "horizon"]):
            base = grp[grp["method"] == "naive"].set_index("origin")
            base_mae = base["error"].abs().mean()
            for method, m in grp.groupby("method"):
                m = m.set_index("origin")
                if series == "cpi_yoy":  # MAPE on the index level, see protocol
                    mape = 100 * ((m["actual_index"] - m["forecast_index"]).abs() / m["actual_index"]).mean()
                else:
                    mape = 100 * (m["error"].abs() / m["actual"].abs()).mean()
                mae = m["error"].abs().mean()
                p = None if method == "naive" else diebold_mariano(
                    m["error"].values, base.loc[m.index, "error"].values, h)
                out.append(dict(period=period, series=series, horizon=h, method=method, n=len(m),
                                mae=mae, mape=mape, skill_vs_naive=1 - mae / base_mae, dm_p_value=p))
    return pd.DataFrame(out)


def pick_winners(scores: pd.DataFrame) -> dict[tuple[str, int], str]:
    """Protocol decision rule: lower MAE than the baseline AND DM p < 0.05, excluding COVID."""
    winners = {}
    ex = scores[scores["period"] == "excluding_covid"]
    for (series, h), grp in ex.groupby(["series", "horizon"]):
        models = grp[(grp["method"] != "naive") & (grp["skill_vs_naive"] > 0) & (grp["dm_p_value"] < 0.05)]
        winners[(series, h)] = models.sort_values("mae").iloc[0]["method"] if len(models) else "naive"
    return winners


def latest_forecasts(unemployment, cpi_index, order, bt, winners) -> pd.DataFrame:
    """Forecast from each series' own latest month with the winning method per horizon.

    The 80% range is the forecast plus the 10th and 90th percentiles of that method's
    backtest errors at that horizon (excluding COVID): an empirical range, which needs no
    distributional assumption and is as wide as the method's real track record says.
    """
    origin = min(unemployment.index.max(), cpi_index.index.max())
    latest = pd.DataFrame(_forecast_origin((origin, unemployment, cpi_index, order)),
                          columns=["series", "method", "origin", "horizon", "target", "forecast", "forecast_index"])
    ex = bt[~bt["covid_target"]]
    out = []
    for (series, h), method in sorted(winners.items()):
        f = latest[(latest["series"] == series) & (latest["method"] == method) & (latest["horizon"] == h)].iloc[0]
        errs = ex[(ex["series"] == series) & (ex["method"] == method) & (ex["horizon"] == h)]["error"]
        lo, hi = np.quantile(errs, [0.1, 0.9])
        out.append(dict(series=series, horizon=h, origin=f["origin"].strftime("%Y-%m"),
                        target=f["target"].strftime("%Y-%m"), method=method,
                        forecast=round(f["forecast"], 2), low_80=round(f["forecast"] + lo, 2),
                        high_80=round(f["forecast"] + hi, 2)))
    return pd.DataFrame(out)


def write_results(scores: pd.DataFrame, winners: dict, latest: pd.DataFrame, order, n_origins: int) -> None:
    built = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    names = {"unemployment": "Unemployment rate", "cpi_yoy": "CPI inflation (12-month %)"}
    lines = ["# Forecast results", "",
             f"Generated by `python -m src.forecast` on {built} from {n_origins} monthly forecast "
             f"origins. Rules: [04_forecast_protocol.md](04_forecast_protocol.md). "
             f"ARIMA order chosen on pre-2010 data: {order}.", ""]
    for period, title in (("excluding_covid", "Excluding COVID targets (decision period)"),
                          ("all", "All targets, including COVID")):
        lines += [f"## {title}", "",
                  "| Target | Horizon | Method | Forecasts | MAE (pp) | MAPE (%) | Skill vs naive | DM p-value |",
                  "|---|---|---|---|---|---|---|---|"]
        sub = scores[scores["period"] == period].sort_values(["series", "horizon", "mae"])
        for r in sub.itertuples():
            p = "" if pd.isna(r.dm_p_value) else f"{r.dm_p_value:.3f}"
            lines.append(f"| {names[r.series]} | {r.horizon} | {r.method} | {r.n} | {r.mae:.3f} | "
                         f"{r.mape:.2f} | {100 * r.skill_vs_naive:+.1f}% | {p} |")
        lines.append("")
    lines += ["## Decision (protocol rule)", "", "| Target | Horizon | Published method |", "|---|---|---|"]
    for (series, h), method in sorted(winners.items()):
        verdict = method if method != "naive" else "naive (no model beat the baseline with significance)"
        lines.append(f"| {names[series]} | {h} | {verdict} |")
    lines += ["", "## Published forecast", "",
              "| Target | From | For | Method | Forecast | 80% range |", "|---|---|---|---|---|---|"]
    for r in latest.itertuples():
        lines.append(f"| {names[r.series]} | {r.origin} | {r.target} | {r.method} | {r.forecast:.2f} | "
                     f"{r.low_80:.2f} to {r.high_80:.2f} |")
    RESULTS_PATH.write_text("\n".join(lines) + "\n")


def main() -> int:
    start = time.perf_counter()
    # Read, then close: the backtest takes minutes and must not hold the database lock.
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        unemployment, cpi_index, cpi_yoy = load_series(con)
    order = select_arima_order(unemployment)
    last = min(unemployment.index.max(), cpi_index.index.max())
    origins = list(pd.period_range(BACKTEST_START, last - 1, freq="M"))
    bt = run_backtest(unemployment, cpi_index, cpi_yoy, order, origins)
    scores = score(bt)
    winners = pick_winners(scores)
    latest = latest_forecasts(unemployment, cpi_index, order, bt, winners)

    with duckdb.connect(str(DB_PATH)) as con:
        for name, df in (("forecast_backtest", bt), ("forecast_scores", scores), ("forecast_latest", latest)):
            df = df.copy()
            for col in ("origin", "target"):
                if col in df and hasattr(df[col].iloc[0], "to_timestamp"):
                    df[col] = df[col].apply(lambda p: p.to_timestamp().date())
            con.register("df_view", df)
            con.execute(f"CREATE OR REPLACE TABLE {name} AS SELECT * FROM df_view")
            con.unregister("df_view")
    write_results(scores, winners, latest, order, len(origins))
    print(f"ARIMA order {order}; {len(origins)} origins; {len(bt):,} scored forecasts; "
          f"{time.perf_counter() - start:.0f}s")
    print(RESULTS_PATH.read_text())
    return 0


if __name__ == "__main__":
    sys.exit(main())
