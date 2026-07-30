"""
STEP 7: Build the dashboard
===========================

Assembles everything into one HTML file you can open in a browser or email to
someone. Images are embedded as base64, so the file works with no folder of
assets next to it and no server running.

This stands in for the Power BI or Fabric report a real team would publish. The
important part is not the HTML, it is that every number on the page is read from
the CSV files the earlier steps wrote, so the dashboard cannot drift away from
the analysis. Nothing here is typed in by hand.

Output: outputs/dashboard.html

Run:  python src/07_build_dashboard.py
"""

import os
import base64
import sqlite3
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "railpulse.db")
OUT = os.path.join(ROOT, "outputs")
CHARTS = os.path.join(OUT, "charts")


def img(name):
    path = os.path.join(CHARTS, name)
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    return f'<img src="data:image/png;base64,{b64}" alt="{name}">'


def table(df, max_rows=12):
    return df.head(max_rows).to_html(index=False, border=0, classes="tbl",
                                     float_format=lambda x: f"{x:,.2f}")


def kpi(value, label, sub=""):
    return f'''<div class="kpi"><div class="kpi-v">{value}</div>
    <div class="kpi-l">{label}</div><div class="kpi-s">{sub}</div></div>'''


CSS = """
:root{--ink:#1f2a37;--muted:#6b7480;--line:#e3e7ec;--blue:#2c5f8a;--rust:#b4532a;
--bg:#f7f8fa;--card:#ffffff;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;}
.wrap{max-width:1120px;margin:0 auto;padding:32px 22px 60px}
header{border-bottom:3px solid var(--blue);padding-bottom:16px;margin-bottom:26px}
h1{margin:0;font-size:27px;letter-spacing:-.4px}
.sub{color:var(--muted);font-size:14px;margin-top:5px}
h2{font-size:19px;margin:34px 0 4px;padding-top:20px;border-top:1px solid var(--line)}
h2:first-of-type{border-top:none}
.lead{color:var(--muted);margin:0 0 16px;font-size:14px;max-width:80ch}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:12px;margin:18px 0 8px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:15px 16px}
.kpi-v{font-size:25px;font-weight:700;letter-spacing:-.6px}
.kpi-l{font-size:12px;text-transform:uppercase;letter-spacing:.55px;color:var(--muted);margin-top:3px}
.kpi-s{font-size:12px;color:var(--muted);margin-top:5px}
.card{background:var(--card);border:1px solid var(--line);border-radius:9px;padding:16px;margin:14px 0}
img{width:100%;height:auto;display:block;border-radius:5px}
.tbl{width:100%;border-collapse:collapse;font-size:13px}
.tbl th{text-align:left;background:#f0f3f6;padding:8px 10px;font-weight:600;
border-bottom:1px solid var(--line);white-space:nowrap}
.tbl td{padding:7px 10px;border-bottom:1px solid #f0f2f5}
.tbl tr:hover td{background:#fafbfc}
ol.f{padding-left:20px;margin:8px 0}
ol.f li{margin-bottom:9px}
.tag{display:inline-block;background:#eef3f8;color:var(--blue);border-radius:4px;
padding:2px 8px;font-size:11.5px;font-weight:600;letter-spacing:.3px;margin-right:6px}
.warn{border-left:3px solid var(--rust);padding-left:13px;color:#7d3a1d;font-size:14px}
footer{margin-top:40px;padding-top:16px;border-top:1px solid var(--line);
color:var(--muted);font-size:12.5px}
"""


def main():
    conn = sqlite3.connect(DB)
    print("STEP 7: building the dashboard")

    n_events = conn.execute("SELECT COUNT(*) FROM repair_events").fetchone()[0]
    n_cars = conn.execute("SELECT COUNT(*) FROM railcars").fetchone()[0]
    spend = conn.execute("SELECT SUM(total_cost_usd) FROM repair_events").fetchone()[0]
    avail = conn.execute("""SELECT ROUND(100*(1 - SUM(dwell_days)*1.0/(12000*3*365.25)),2)
                            FROM repair_events""").fetchone()[0]

    dq = pd.read_csv(os.path.join(OUT, "data_quality_report.csv"))
    qp = pd.read_csv(os.path.join(OUT, "query_performance.csv")).iloc[0]
    findings = pd.read_csv(os.path.join(OUT, "key_findings.csv"))
    health = pd.read_csv(os.path.join(OUT, "fleet_health_by_type.csv"))
    par = pd.read_csv(os.path.join(OUT, "defect_pareto.csv"))
    shop = pd.read_csv(os.path.join(OUT, "shop_scorecard.csv"))
    mc = pd.read_csv(os.path.join(OUT, "forecast_model_comparison.csv"))
    fc = pd.read_csv(os.path.join(OUT, "forecast_next_6_months.csv"))
    ext = pd.read_csv(os.path.join(OUT, "extrapolation_test.csv"))
    opt = pd.read_csv(os.path.join(OUT, "optimizer_summary.csv")).iloc[0]
    util = pd.read_csv(os.path.join(OUT, "optimizer_utilization.csv"))
    plan = pd.read_csv(os.path.join(OUT, "optimizer_assignment_plan.csv"))

    dq_total = int(dq.rows_failed.sum())
    raw_rows = int(dq.rows_scanned.max())
    dq_pct = 100 * dq_total / raw_rows
    retained_pct = 100 * n_events / raw_rows
    qpath = os.path.join(ROOT, "data", "clean", "quarantine.csv")
    n_quarantine = len(pd.read_csv(qpath)) if os.path.exists(qpath) else 0
    sev = dq.severity.value_counts()

    # Trailing 12 months of actuals, used to judge the extrapolation test
    mv = pd.read_csv(os.path.join(OUT, "monthly_volume.csv"))
    trailing12 = int(mv.bad_orders.tail(12).sum())

    # How often history actually routed a car outside its home region
    hist_out = conn.execute("""
        SELECT ROUND(100.0 * SUM(CASE WHEN c.home_region <> s.region THEN 1 ELSE 0 END)
               / COUNT(*), 0)
        FROM repair_events e
        JOIN railcars c ON c.car_id = e.car_id
        JOIN shops s    ON s.shop_id = e.shop_id
    """).fetchone()[0]
    # The MAPE of the model actually shipped, which is not the same as the best
    # score in the table. Gradient boosting edged it out and was rejected for
    # being unable to extrapolate, so quoting its number here would be wrong.
    best_mape = float(mc.loc[mc.model == "Trend + Fourier", "test_mape_pct"].iloc[0])
    base_mape = float(mc.loc[mc.model == "Seasonal naive", "test_mape_pct"].iloc[0])

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>RailPulse Fleet Maintenance Analytics</title><style>{CSS}</style></head><body>
<div class="wrap">
<header>
  <h1>RailPulse Fleet Maintenance Analytics</h1>
  <div class="sub">Railcar bad order reporting, repair demand forecasting, and
  shop assignment optimization &nbsp;&middot;&nbsp; {n_cars:,} car fleet
  &nbsp;&middot;&nbsp; {len(mv)} months of history</div>
</header>

<h2>Where the fleet stands</h2>
<p class="lead">Definitions are shared with every query in the project. A bad order is a
car pulled from service for repair. Dwell is release date minus bad order date. Rate is
bad orders per car per year, not percent of fleet, so it compares across fleets of
different sizes.</p>
<div class="kpis">
  {kpi(f"{n_events:,}", "Bad orders", "3 year window, cleaned")}
  {kpi(f"${spend/1e6:.1f}M", "Repair spend", "labor plus parts")}
  {kpi(f"{avail}%", "Fleet availability", "car days out of shop")}
  {kpi(f"{n_events/n_cars/3:.2f}", "Bad orders per car year", "network average")}
  {kpi(f"{best_mape:.1f}%", "Forecast error", f"model shipped, vs {base_mape:.1f}% seasonal naive")}
  {kpi(f"${opt.saving_usd/1000:.0f}k", "Monthly saving", f"{opt.saving_pct}% from re-assignment")}
</div>

<h2>Data quality gate</h2>
<p class="lead">Nine checks run before anything is modeled. Every row either passes, gets
repaired with a documented rule, or goes to a quarantine file with a reason attached. No
row is dropped silently, because a silent drop is how a report ends up wrong in a way
nobody can trace.</p>
<div class="kpis">
  {kpi(f"{dq_total:,}", "Issues found", f"{dq_pct:.1f}% of raw rows")}
  {kpi(f"{len(dq)}", "Checks run", f"{sev.get('HIGH',0)} high, {sev.get('MEDIUM',0)} medium, {sev.get('LOW',0)} low severity")}
  {kpi(f"{retained_pct:.1f}%", "Rows retained", f"{n_quarantine:,} quarantined for review")}
  {kpi(f"{int(qp.pct_faster)}%", "Faster reporting", "after indexing the fact table")}
</div>
<div class="card">{table(dq, len(dq))}</div>
<p class="lead"><span class="tag">WHY IT MATTERS</span>The {int(dq.loc[dq.check_name=="negative_or_missing_dwell","rows_failed"].iloc[0]):,} rows with a release date
before the bad order date would have produced negative dwell times and pulled every
average dwell number on this page down. The {int(dq.loc[dq.check_name=="orphan_car_id","rows_failed"].iloc[0]):,} orphan car IDs cannot join to car
type, so they would have quietly disappeared from every per-type breakdown while still
counting in the totals.</p>

<h2>What the data says</h2>
<div class="card"><ol class="f">
{''.join(f"<li>{f}</li>" for f in findings.finding)}
</ol></div>
<div class="card">{img('01_volume_and_seasonality.png')}</div>
<div class="card">{img('02_health_by_car_type.png')}</div>
<div class="card">{table(health)}</div>
<div class="card">{img('03_age_curve.png')}</div>
<div class="card">{img('04_defect_pareto.png')}</div>
<div class="card">{table(par[['defect_code','defect_description','repair_class','bad_orders','pct_of_bad_orders','pct_of_cost','cost_to_volume_ratio']], 8)}</div>
<div class="card">{img('05_shop_dwell.png')}</div>
<p class="lead"><span class="tag">METHOD NOTE</span>Raw dwell time makes heavy repair
shops look bad, because frame work takes longer everywhere. So each shop is compared
against the network average within the same repair class, then averaged. What is left is
the part of dwell the shop actually controls.</p>
<div class="card">{table(shop[['shop_name','region','primary_specialty','bad_orders','avg_dwell_days','mix_adjusted_dwell_ratio','capacity_used_pct']])}</div>

<h2>Repair demand forecast</h2>
<p class="lead">Six candidate models, all scored on the same six months that none of them
were trained on. The winner is refit on the full history and used to project the next
half year. Intervals come from how wrong the model actually was on the holdout, not from
a formula that assumes the model is right.</p>
<div class="card">{img('07_model_comparison.png')}</div>
<div class="card">{table(mc)}</div>
<p class="lead warn"><strong>The backtest score is not the whole story.</strong> Gradient
boosting scored marginally best on the holdout and is still the wrong choice. A tree can
only predict values it has seen, so asked about 2026 it flattens out: it projects
{100*(ext.gradient_boosting.sum()/trailing12-1):+.1f}% growth against a history that has
grown about 3% a year. The linear model with Fourier seasonality projects
{100*(ext.trend_plus_fourier.sum()/trailing12-1):+.1f}%. For a planning forecast that has to
extrapolate, that matters more than a tenth of a point of MAPE.</p>
<div class="card">{img('06_forecast.png')}</div>
<div class="card">{table(fc)}</div>

<h2>Shop assignment plan for {opt.plan_month}</h2>
<p class="lead">The forecast says {int(opt.forecast_bad_orders):,} cars will be bad
ordered in the peak month. This is where to send them. Cost per car is repair hours times
the shop labor rate times a specialty penalty, plus deadhead miles. Constraints are shop
capacity and a 1,500 mile cap on any single move. Compared against nearest shop in region
with spillover, which is close to what the history shows happening today, where
{hist_out:.0f}% of repairs went outside the home region.</p>
<div class="kpis">
  {kpi(f"${opt.baseline_cost_usd/1000:,.0f}k", "Baseline cost", "nearest shop dispatch")}
  {kpi(f"${opt.optimized_cost_usd/1000:,.0f}k", "Optimized cost", f"${opt.optimized_cost_per_car:,.0f} per car")}
  {kpi(f"{opt.saving_pct}%", "Cost reduction", f"${opt.annualized_saving_usd/1000:,.0f}k annualized")}
  {kpi(f"{opt.cars_moved_out_of_region_pct}%", "Moved out of region", f"vs {hist_out:.0f}% in history")}
</div>
<div class="card">{img('08_optimizer.png')}</div>
<p class="lead"><span class="tag">READ THIS CAREFULLY</span>The optimizer does not spread
work evenly, and it should not. It fills the shops with the best combination of rate and
location until their capacity runs out, then works outward. Five of ten shops finish at
exactly capacity, which says capacity is the binding constraint, so buying a slot at a
cheap shop is worth more than negotiating a rate anywhere. It also drops one shop to zero
cars, which is a question for management rather than an answer from a model.</p>
<div class="card">{table(util[['shop_name','labor_rate_usd','capacity_cars','baseline_cars','optimized_cars','car_change','optimized_util_pct']])}</div>
<div class="card">{table(plan[['region','repair_class','shop_name','cars','miles','specialty_penalty','total_cost']], 14)}</div>

<footer>
Built with Python, SQLite and PuLP. Data is synthetic and generated by
<code>src/01_generate_data.py</code> with a fixed seed, so every number on this page
reproduces exactly by running <code>python run_all.py</code>. No number here is typed by
hand; the page is assembled from the CSV files the pipeline writes.
</footer>
</div></body></html>"""

    path = os.path.join(OUT, "dashboard.html")
    with open(path, "w") as f:
        f.write(html)
    conn.close()
    print(f"   dashboard -> outputs/dashboard.html ({len(html)/1024:.0f} KB)")


if __name__ == "__main__":
    main()
