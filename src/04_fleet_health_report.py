"""
STEP 4: Fleet health analysis
=============================

Everything here runs as SQL against the views, then Python only formats the
answer and draws the chart. That split is on purpose: the definitions live in
one place, so the dashboard and any ad hoc query cannot disagree.

Five questions, five answers:

  1. Is repair volume going up, and is it seasonal?
  2. Which car types cost us the most availability?
  3. How much does age actually matter?
  4. Which defects should we attack first?
  5. Are all shops turning cars around at the same speed?

Outputs: CSV extracts in outputs/, PNG charts in outputs/charts/

Run:  python src/04_fleet_health_report.py
"""

import os
import sqlite3
import numpy as np
import pandas as pd
from viz_style import (apply_style, strip_frame, save, plt,
                       BLUE, RUST, GRAY, LIGHT_BLUE, GREEN, AMBER, INK, SERIES)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "railpulse.db")
OUT = os.path.join(ROOT, "outputs")
CHARTS = os.path.join(OUT, "charts")

findings = []


def note(text):
    findings.append(text)
    print(f"   FINDING: {text}")


def main():
    os.makedirs(CHARTS, exist_ok=True)
    apply_style()
    conn = sqlite3.connect(DB)
    print("STEP 4: fleet health analysis\n")

    # =====================================================================
    # 1. Volume trend and seasonality
    # =====================================================================
    monthly = pd.read_sql("""
        SELECT month, SUM(bad_orders) AS bad_orders, SUM(labor_hours) AS labor_hours,
               SUM(total_cost_usd) AS cost
        FROM v_monthly_demand GROUP BY month ORDER BY month
    """, conn)
    monthly["date"] = pd.to_datetime(monthly["month"])
    monthly["rolling_12"] = monthly["bad_orders"].rolling(12).mean()

    y23 = monthly[monthly.date.dt.year == 2023]["bad_orders"].sum()
    y25 = monthly[monthly.date.dt.year == 2025]["bad_orders"].sum()
    growth = 100 * (y25 / y23 - 1)
    note(f"repair volume grew {growth:.1f}% from 2023 to 2025 ({y23:,} to {y25:,} bad orders)")

    monthly["mo"] = monthly.date.dt.month
    seasonal = monthly.groupby("mo")["bad_orders"].mean()
    idx = seasonal / seasonal.mean()
    peak_mo, low_mo = idx.idxmax(), idx.idxmin()
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    note(f"winter peak is real: {names[peak_mo-1]} runs {100*(idx.max()-1):.0f}% above "
         f"average and {names[low_mo-1]} runs {100*(1-idx.min()):.0f}% below, "
         f"a {100*(idx.max()/idx.min()-1):.0f}% swing between peak and trough")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.2),
                                   gridspec_kw={"width_ratios": [1.7, 1]})
    ax1.plot(monthly.date, monthly.bad_orders, color=BLUE, lw=1.8, label="Monthly bad orders")
    ax1.plot(monthly.date, monthly.rolling_12, color=RUST, lw=2.2, ls="--",
             label="12 month rolling average")
    ax1.set_title("Repair volume is trending up on top of a strong winter cycle")
    ax1.set_ylabel("Bad orders")
    ax1.legend(loc="lower right")
    strip_frame(ax1)

    colors = [RUST if v > 1.08 else (LIGHT_BLUE if v < 0.95 else BLUE) for v in idx]
    ax2.bar(names, idx.values, color=colors)
    ax2.axhline(1.0, color=GRAY, lw=1.2)
    ax2.set_title("Seasonal index (1.0 = average month)")
    ax2.set_ylim(0.8, 1.35)
    strip_frame(ax2)
    save(fig, os.path.join(CHARTS, "01_volume_and_seasonality.png"))

    monthly.drop(columns=["mo"]).to_csv(os.path.join(OUT, "monthly_volume.csv"), index=False)

    # =====================================================================
    # 2. Health by car type
    # =====================================================================
    by_type = pd.read_sql("SELECT * FROM v_fleet_health_by_type", conn)
    worst, best = by_type.iloc[0], by_type.iloc[-1]
    note(f"{worst.car_type} is the problem fleet at {worst.bad_orders_per_car_year} bad orders "
         f"per car per year, {100*(worst.bad_orders_per_car_year/best.bad_orders_per_car_year-1):.0f}% "
         f"above {best.car_type}")

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.2))
    lbl = [t.replace("_", " ").title() for t in by_type.car_type]
    ax1.barh(lbl, by_type.bad_orders_per_car_year, color=[RUST] + [BLUE] * 4)
    ax1.invert_yaxis()
    ax1.set_title("Bad orders per car per year")
    for i, v in enumerate(by_type.bad_orders_per_car_year):
        ax1.text(v + 0.015, i, f"{v:.2f}", va="center", fontsize=9, color=INK)
    ax1.set_xlim(0, by_type.bad_orders_per_car_year.max() * 1.18)
    strip_frame(ax1)

    ax2.barh(lbl, by_type.availability_pct, color=GREEN)
    ax2.invert_yaxis()
    ax2.set_xlim(98.5, 99.6)
    ax2.set_title("Fleet availability percent")
    for i, v in enumerate(by_type.availability_pct):
        ax2.text(v + 0.01, i, f"{v:.2f}%", va="center", fontsize=9, color=INK)
    strip_frame(ax2)
    save(fig, os.path.join(CHARTS, "02_health_by_car_type.png"))
    by_type.to_csv(os.path.join(OUT, "fleet_health_by_type.csv"), index=False)

    # =====================================================================
    # 3. Age curve
    # =====================================================================
    age = pd.read_sql("SELECT * FROM v_age_band_reliability", conn)
    lift = 100 * (age.bad_orders_per_car_year.iloc[-1] / age.bad_orders_per_car_year.iloc[0] - 1)
    note(f"cars past 40 years fail {lift:.0f}% more often than cars under 10, and the curve "
         f"is flat until about 20 years then bends up")

    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.plot(age.age_band, age.bad_orders_per_car_year, marker="o", ms=8,
            color=BLUE, lw=2.4)
    for x, y in zip(age.age_band, age.bad_orders_per_car_year):
        ax.annotate(f"{y:.2f}", (x, y), textcoords="offset points",
                    xytext=(0, 11), ha="center", fontsize=9, color=INK)
    ax.set_title("Failure rate is flat to 20 years, then climbs")
    ax.set_ylabel("Bad orders per car per year")
    ax.set_ylim(0.6, age.bad_orders_per_car_year.max() * 1.15)
    strip_frame(ax)
    save(fig, os.path.join(CHARTS, "03_age_curve.png"))
    age.to_csv(os.path.join(OUT, "age_band_reliability.csv"), index=False)

    # =====================================================================
    # 4. Defect Pareto
    # =====================================================================
    par = pd.read_sql("SELECT * FROM v_defect_pareto", conn)
    par["cum_pct"] = par.pct_of_bad_orders.cumsum()
    n80 = int((par.cum_pct <= 80).sum() + 1)
    note(f"{n80} of {len(par)} defect codes cause 80% of all bad orders, led by "
         f"{par.defect_description.iloc[0].lower()}")

    # Volume ranking and cost ranking are not the same list. The defect with the
    # biggest gap between its share of dollars and its share of events is the one
    # a volume-only report would underrate.
    par["cost_to_volume_ratio"] = (par.pct_of_cost / par.pct_of_bad_orders).round(2)
    heavy = par.sort_values("cost_to_volume_ratio", ascending=False).iloc[0]
    note(f"{heavy.defect_description.lower()} is only {heavy.pct_of_bad_orders}% of bad orders "
         f"but {heavy.pct_of_cost}% of repair spend, a {heavy.cost_to_volume_ratio}x ratio, so a "
         f"volume-ranked report would underrate it")

    fig, ax = plt.subplots(figsize=(11, 4.6))
    ax.bar(par.defect_code, par.pct_of_bad_orders, color=BLUE, label="% of bad orders")
    ax.set_ylabel("% of bad orders", color=BLUE)
    ax.set_title("A handful of defect codes drive most of the volume")
    ax.tick_params(axis="x", rotation=45)
    ax2 = ax.twinx()
    ax2.plot(par.defect_code, par.cum_pct, color=RUST, marker="o", ms=4, lw=2)
    ax2.axhline(80, color=GRAY, ls=":", lw=1.4)
    ax2.text(len(par) - 1.4, 82, "80%", color=GRAY, fontsize=9)
    ax2.set_ylabel("Cumulative %", color=RUST)
    ax2.set_ylim(0, 105)
    ax2.grid(False)
    strip_frame(ax)
    save(fig, os.path.join(CHARTS, "04_defect_pareto.png"))
    par.to_csv(os.path.join(OUT, "defect_pareto.csv"), index=False)

    # =====================================================================
    # 5. Shop turnaround
    # =====================================================================
    # The interesting one. Dwell is not in any dimension table, so the only way
    # to see it is to compare shops against the network on equal footing. Raw
    # dwell is unfair to heavy repair shops, so also compare within repair class.
    shop = pd.read_sql("SELECT * FROM v_shop_scorecard", conn).sort_values("avg_dwell_days")
    net = pd.read_sql("SELECT AVG(dwell_days) d FROM repair_events", conn).d.iloc[0]

    adj = pd.read_sql("""
        SELECT s.shop_id, s.shop_name, d.repair_class,
               AVG(e.dwell_days) AS shop_dwell
        FROM repair_events e
        JOIN shops s        ON s.shop_id = e.shop_id
        JOIN defect_codes d ON d.defect_code = e.defect_code
        GROUP BY s.shop_id, d.repair_class
    """, conn)
    cls_avg = adj.groupby("repair_class")["shop_dwell"].mean().rename("class_avg")
    adj = adj.join(cls_avg, on="repair_class")
    adj["ratio"] = adj.shop_dwell / adj.class_avg
    mix_adj = (adj.groupby(["shop_id", "shop_name"])["ratio"].mean()
                 .reset_index().sort_values("ratio"))

    slow = mix_adj.iloc[-1]
    fast = mix_adj.iloc[0]
    note(f"shop turnaround is uneven after adjusting for repair mix: {slow.shop_name} holds "
         f"cars {100*(slow.ratio-1):.0f}% longer than the network and {fast.shop_name} "
         f"{100*(1-fast.ratio):.0f}% shorter, which is a scheduling problem, not a mix problem")

    fig, ax = plt.subplots(figsize=(9, 4.4))
    cols = [RUST if r > 1.10 else (GREEN if r < 0.95 else BLUE) for r in mix_adj.ratio]
    ax.barh(mix_adj.shop_name, mix_adj.ratio, color=cols)
    ax.axvline(1.0, color=GRAY, lw=1.4)
    ax.set_title("Mix adjusted dwell time by shop (1.0 = network average)")
    ax.set_xlabel("Ratio to network average for the same repair classes")
    ax.set_xlim(0.8, 1.5)
    for i, v in enumerate(mix_adj.ratio):
        ax.text(v + 0.012, i, f"{v:.2f}", va="center", fontsize=9, color=INK)
    strip_frame(ax)
    save(fig, os.path.join(CHARTS, "05_shop_dwell.png"))

    shop.merge(mix_adj[["shop_id", "ratio"]], on="shop_id").rename(
        columns={"ratio": "mix_adjusted_dwell_ratio"}
    ).to_csv(os.path.join(OUT, "shop_scorecard.csv"), index=False)

    # =====================================================================
    # 6. Repeat offenders
    # =====================================================================
    rep = pd.read_sql("SELECT * FROM v_repeat_offenders", conn)
    fleet_n = pd.read_sql("SELECT COUNT(*) n FROM railcars", conn).n.iloc[0]
    total_cost = pd.read_sql("SELECT SUM(total_cost_usd) c FROM repair_events", conn).c.iloc[0]
    note(f"{len(rep):,} cars ({100*len(rep)/fleet_n:.1f}% of the fleet) had 6 or more bad orders "
         f"in 3 years and account for {100*rep.total_cost_usd.sum()/total_cost:.1f}% of repair spend")
    rep.to_csv(os.path.join(OUT, "repeat_offenders.csv"), index=False)

    pd.DataFrame({"finding": findings}).to_csv(
        os.path.join(OUT, "key_findings.csv"), index=False)
    conn.close()
    print(f"\n   {len(findings)} findings written to outputs/key_findings.csv")


if __name__ == "__main__":
    main()
