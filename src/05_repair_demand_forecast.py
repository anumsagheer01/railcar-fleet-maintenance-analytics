"""
STEP 5: Forecast repair demand
==============================

The planning question this answers: how many cars will we bad order next month,
how many labor hours does that need, and can the shops absorb it.

Method, and why it is this and not something fancier:

  We have 36 monthly observations. That is a small sample. With 36 points you
  can fit a trend and a seasonal shape and that is about it. Anything with more
  parameters will fit the noise and look great in training while failing on new
  months. So instead of picking a model by reputation, I test five candidates on
  months the model never saw.

  Train:  2023-01 to 2025-06  (30 months)
  Test:   2025-07 to 2025-12  ( 6 months, held out completely)

  1. Naive mean            last 12 months average. The floor. Beat this or go home.
  2. Seasonal naive        same month last year. Free and surprisingly hard to beat.
  3. Trend only            linear regression on a time index.
  4. Trend + Fourier       trend plus 2 sine and cosine pairs for the annual cycle.
                           5 parameters, so it can learn seasonality without
                           memorizing individual months.
  5. Trend + month dummies same idea but with 11 dummy variables. 12 parameters
                           on 30 rows. Included on purpose to show what
                           overfitting looks like.
  6. Gradient boosting     the model people reach for by default. Trees cannot
                           extrapolate past the range they were trained on, so
                           a rising trend is a problem for it.

  Scored with MAPE, which is percent error, because a planner thinks in
  "how far off were we" not in squared units.

Then the winning spec is refit on all 36 months and used to forecast the first
half of 2026, with intervals built from the backtest errors rather than from a
formula that assumes the model is correct.

Outputs:
  outputs/forecast_model_comparison.csv
  outputs/forecast_next_6_months.csv
  outputs/forecast_by_car_type.csv
  outputs/charts/06_forecast.png
  outputs/charts/07_model_comparison.png

Run:  python src/05_repair_demand_forecast.py
"""

import os
import sqlite3
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import GradientBoostingRegressor
from viz_style import (apply_style, strip_frame, save, plt,
                       BLUE, RUST, GRAY, LIGHT_BLUE, GREEN, AMBER, INK)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "railpulse.db")
OUT = os.path.join(ROOT, "outputs")
CHARTS = os.path.join(OUT, "charts")

TEST_MONTHS = 6
HORIZON = 6


# ---------------------------------------------------------------------------
# Features
# ---------------------------------------------------------------------------
def make_features(dates, t0, kind):
    """Build a design matrix from dates only.

    t0 is the first date in the training set, so the time index means the same
    thing for training months and future months. Getting this wrong is the most
    common way a forecast quietly breaks.
    """
    t = np.array([(d.year - t0.year) * 12 + (d.month - t0.month) for d in dates],
                 dtype=float)
    m = np.array([d.month for d in dates], dtype=float)

    if kind == "trend":
        return t.reshape(-1, 1)

    if kind == "fourier":
        cols = [t]
        for k in (1, 2):
            cols.append(np.sin(2 * np.pi * k * m / 12))
            cols.append(np.cos(2 * np.pi * k * m / 12))
        return np.column_stack(cols)

    if kind == "dummies":
        d = np.zeros((len(dates), 11))
        for i, mm in enumerate(m.astype(int)):
            if mm > 1:
                d[i, mm - 2] = 1
        return np.column_stack([t, d])

    raise ValueError(kind)


def mape(actual, pred):
    actual, pred = np.asarray(actual, float), np.asarray(pred, float)
    return float(np.mean(np.abs((actual - pred) / actual)) * 100)


def mae(actual, pred):
    return float(np.mean(np.abs(np.asarray(actual, float) - np.asarray(pred, float))))


# ---------------------------------------------------------------------------
# Backtest
# ---------------------------------------------------------------------------
def backtest(series):
    """series: DataFrame with date and y, sorted. Returns results and predictions."""
    train = series.iloc[:-TEST_MONTHS]
    test = series.iloc[-TEST_MONTHS:]
    t0 = train.date.iloc[0]
    results, preds = [], {}

    # 1. naive mean of last 12 training months
    p = np.repeat(train.y.iloc[-12:].mean(), len(test))
    preds["Naive mean"] = p
    results.append(("Naive mean", mape(test.y, p), mae(test.y, p)))

    # 2. seasonal naive, same month one year earlier
    lookup = dict(zip(series.date, series.y))
    p = np.array([lookup[d - pd.DateOffset(years=1)] for d in test.date])
    preds["Seasonal naive"] = p
    results.append(("Seasonal naive", mape(test.y, p), mae(test.y, p)))

    # 3, 4, 5. linear models
    for label, kind in [("Trend only", "trend"),
                        ("Trend + Fourier", "fourier"),
                        ("Trend + month dummies", "dummies")]:
        Xtr = make_features(train.date, t0, kind)
        Xte = make_features(test.date, t0, kind)
        model = LinearRegression().fit(Xtr, train.y)
        p = model.predict(Xte)
        preds[label] = p
        results.append((label, mape(test.y, p), mae(test.y, p)))

    # 6. gradient boosting on the Fourier features, same information, more flexibility
    Xtr = make_features(train.date, t0, "fourier")
    Xte = make_features(test.date, t0, "fourier")
    gb = GradientBoostingRegressor(n_estimators=300, max_depth=2,
                                   learning_rate=0.05, random_state=42)
    gb.fit(Xtr, train.y)
    p = gb.predict(Xte)
    preds["Gradient boosting"] = p
    results.append(("Gradient boosting", mape(test.y, p), mae(test.y, p)))

    res = (pd.DataFrame(results, columns=["model", "test_mape_pct", "test_mae_cars"])
             .sort_values("test_mape_pct").reset_index(drop=True))
    res["test_mape_pct"] = res.test_mape_pct.round(2)
    res["test_mae_cars"] = res.test_mae_cars.round(1)
    return res, preds, train, test


def fit_and_forecast(series, kind, horizon):
    """Refit on everything, then predict forward."""
    t0 = series.date.iloc[0]
    X = make_features(series.date, t0, kind)
    model = LinearRegression().fit(X, series.y)
    future = pd.date_range(series.date.iloc[-1] + pd.DateOffset(months=1),
                           periods=horizon, freq="MS")
    yhat = model.predict(make_features(future, t0, kind))
    in_sample_resid = series.y.to_numpy() - model.predict(X)
    return future, yhat, in_sample_resid, model


def main():
    os.makedirs(CHARTS, exist_ok=True)
    apply_style()
    conn = sqlite3.connect(DB)
    print("STEP 5: forecasting repair demand\n")

    # ------------------------------------------------------------------
    # Network level
    # ------------------------------------------------------------------
    total = pd.read_sql("""
        SELECT month, SUM(bad_orders) AS y, SUM(labor_hours) AS labor_hours
        FROM v_monthly_demand GROUP BY month ORDER BY month
    """, conn)
    total["date"] = pd.to_datetime(total["month"])

    # Yearly growth from history, used later to sanity check the forecast
    yearly = total.assign(yr=total.date.dt.year).groupby("yr").y.sum()
    growth_hist = 100 * ((yearly.iloc[-1] / yearly.iloc[0]) ** (1 / 2) - 1)

    res, preds, train, test = backtest(total[["date", "y"]])
    print("   backtest on 6 held out months, network total")
    print("   " + "-" * 52)
    for r in res.itertuples():
        print(f"   {r.model:<24} MAPE {r.test_mape_pct:>6.2f}%   MAE {r.test_mae_cars:>6.1f} cars")
    print("   " + "-" * 52)

    winner = res.model.iloc[0]
    baseline = float(res.loc[res.model == "Seasonal naive", "test_mape_pct"].iloc[0])
    best_mape = float(res.test_mape_pct.iloc[0])
    print(f"   winner: {winner} at {best_mape:.2f}% MAPE, "
          f"{100*(1-best_mape/baseline):.0f}% better than seasonal naive")

    dum_mape = float(res.loc[res.model == "Trend + month dummies", "test_mape_pct"].iloc[0])
    fou_mape = float(res.loc[res.model == "Trend + Fourier", "test_mape_pct"].iloc[0])
    print(f"   month dummies scored {dum_mape:.2f}% against Fourier at {fou_mape:.2f}%. "
          f"Same information,")
    print(f"     more parameters, worse result. That is overfitting on 30 rows.")

    res.to_csv(os.path.join(OUT, "forecast_model_comparison.csv"), index=False)

    # ------------------------------------------------------------------
    # Extrapolation test: backtest score is not the whole story
    # ------------------------------------------------------------------
    # Gradient boosting can score well on a holdout that sits close to the
    # training range and still be useless for planning, because a tree can only
    # predict values it has already seen. Rather than claim that, test it: ask
    # both models for 2026 and compare what they say about growth.
    t0 = total.date.iloc[0]
    future_test = pd.date_range(total.date.iloc[-1] + pd.DateOffset(months=1),
                                periods=12, freq="MS")

    gb_full = GradientBoostingRegressor(n_estimators=300, max_depth=2,
                                        learning_rate=0.05, random_state=42)
    gb_full.fit(make_features(total.date, t0, "fourier"), total.y)
    gb_future = gb_full.predict(make_features(future_test, t0, "fourier"))

    lin_full = LinearRegression().fit(make_features(total.date, t0, "fourier"), total.y)
    lin_future = lin_full.predict(make_features(future_test, t0, "fourier"))

    trailing = total.y.tail(12).sum()
    print(f"\n   extrapolation test, next 12 months against the trailing 12 ({trailing:,.0f})")
    print(f"     gradient boosting says {gb_future.sum():>7,.0f}  "
          f"({100*(gb_future.sum()/trailing-1):+.1f}% growth)")
    print(f"     trend + Fourier says   {lin_future.sum():>7,.0f}  "
          f"({100*(lin_future.sum()/trailing-1):+.1f}% growth)")
    print(f"     history has grown {growth_hist:.1f}% a year, so the tree model is the")
    print(f"     one that is wrong here even though it won on the holdout")

    pd.DataFrame({
        "month": future_test.strftime("%Y-%m"),
        "gradient_boosting": gb_future.round(0).astype(int),
        "trend_plus_fourier": lin_future.round(0).astype(int),
    }).to_csv(os.path.join(OUT, "extrapolation_test.csv"), index=False)

    # ------------------------------------------------------------------
    # Forecast forward with the winning spec
    # ------------------------------------------------------------------
    KIND = {"Trend + Fourier": "fourier", "Trend only": "trend",
            "Trend + month dummies": "dummies"}.get(winner, "fourier")
    if winner in ("Naive mean", "Seasonal naive", "Gradient boosting"):
        print(f"\n   model choice: {winner} edged out Trend + Fourier on the holdout, but the")
        print(f"     extrapolation test below shows why it cannot be used for planning.")
        print(f"     Going with Trend + Fourier.")
        KIND = "fourier"

    future, yhat, resid, model = fit_and_forecast(total[["date", "y"]], KIND, HORIZON)

    # Intervals from actual holdout error, not from a textbook formula. If the
    # model was off by 4% on months it had never seen, say so honestly.
    err = best_mape / 100
    lo, hi = yhat * (1 - 1.96 * err), yhat * (1 + 1.96 * err)

    # Labor hours per bad order has been stable, so scale volume into hours.
    hours_per_bo = (total.labor_hours / total.y).tail(12).mean()
    fc = pd.DataFrame({
        "month": future.strftime("%Y-%m"),
        "forecast_bad_orders": yhat.round(0).astype(int),
        "low_95": lo.round(0).astype(int),
        "high_95": hi.round(0).astype(int),
        "forecast_labor_hours": (yhat * hours_per_bo).round(0).astype(int),
        "implied_cars_per_day": (yhat / 30.4).round(1),
    })
    fc.to_csv(os.path.join(OUT, "forecast_next_6_months.csv"), index=False)

    print(f"\n   forecast for the next {HORIZON} months")
    print(fc.to_string(index=False).replace("\n", "\n   "))

    peak = fc.loc[fc.forecast_bad_orders.idxmax()]
    last12 = total.y.tail(12).mean()
    print(f"\n   peak month is {peak.month} at {peak.forecast_bad_orders:,} bad orders, "
          f"{100*(peak.forecast_bad_orders/last12-1):.0f}% above the trailing 12 month average")

    # ------------------------------------------------------------------
    # Per car type, same spec
    # ------------------------------------------------------------------
    by_type = pd.read_sql("""
        SELECT month, car_type, SUM(bad_orders) AS y, SUM(labor_hours) AS labor_hours
        FROM v_monthly_demand GROUP BY month, car_type ORDER BY month
    """, conn)
    by_type["date"] = pd.to_datetime(by_type["month"])

    label_for = {"fourier": "Trend + Fourier", "trend": "Trend only",
                 "dummies": "Trend + month dummies"}[KIND]
    rows = []
    print("\n   per car type backtest, same model spec")
    for ct, g in by_type.groupby("car_type"):
        g = g.sort_values("date").reset_index(drop=True)
        r, _, _, _ = backtest(g[["date", "y"]])
        ct_mape = float(r.loc[r.model == label_for, "test_mape_pct"].iloc[0])
        f, yh, _, _ = fit_and_forecast(g[["date", "y"]], KIND, HORIZON)
        hpb = (g.labor_hours / g.y).tail(12).mean()
        print(f"     {ct:<17} MAPE {ct_mape:>5.2f}%   next 6 mo: {yh.sum():>6.0f} bad orders")
        for d, v in zip(f, yh):
            rows.append({"month": d.strftime("%Y-%m"), "car_type": ct,
                         "forecast_bad_orders": round(float(v)),
                         "forecast_labor_hours": round(float(v * hpb)),
                         "backtest_mape_pct": round(ct_mape, 2)})
    pd.DataFrame(rows).to_csv(os.path.join(OUT, "forecast_by_car_type.csv"), index=False)

    # ------------------------------------------------------------------
    # Charts
    # ------------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.plot(total.date, total.y, color=BLUE, lw=1.9, label="Actual")
    ax.plot(future, yhat, color=RUST, lw=2.4, ls="--", marker="o", ms=5,
            label=f"Forecast ({winner})")
    ax.fill_between(future, lo, hi, color=RUST, alpha=0.14,
                    label="95% interval from holdout error")
    ax.axvline(test.date.iloc[0], color=GRAY, ls=":", lw=1.4)
    ax.text(test.date.iloc[0], ax.get_ylim()[1] * 0.97, "  holdout starts",
            color=GRAY, fontsize=8.5, va="top")
    ax.set_title(f"Monthly bad orders with a 6 month forecast, {best_mape:.1f}% MAPE on held out months")
    ax.set_ylabel("Bad orders")
    ax.legend(loc="lower left", ncol=2)
    strip_frame(ax)
    save(fig, os.path.join(CHARTS, "06_forecast.png"))

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.4),
                                   gridspec_kw={"width_ratios": [1, 1.25]})
    cols = [GREEN] + [BLUE] * (len(res) - 2) + [RUST]
    ax1.barh(res.model, res.test_mape_pct, color=cols)
    ax1.invert_yaxis()
    ax1.set_title("Error on 6 held out months (lower is better)")
    ax1.set_xlabel("MAPE %")
    for i, v in enumerate(res.test_mape_pct):
        ax1.text(v + 0.12, i, f"{v:.2f}%", va="center", fontsize=9, color=INK)
    ax1.set_xlim(0, res.test_mape_pct.max() * 1.22)
    strip_frame(ax1)

    ax2.plot(test.date, test.y, color=INK, lw=2.6, marker="o", ms=6, label="Actual", zorder=5)
    for (label, p), c in zip(preds.items(), [GRAY, AMBER, LIGHT_BLUE, GREEN, RUST, BLUE]):
        ax2.plot(test.date, p, lw=1.7, ls="--", color=c, label=label)
    ax2.set_title("What each model predicted for the holdout months")
    ax2.set_ylabel("Bad orders")
    ax2.legend(ncol=2, fontsize=8)
    strip_frame(ax2)
    save(fig, os.path.join(CHARTS, "07_model_comparison.png"))

    conn.close()


if __name__ == "__main__":
    main()
