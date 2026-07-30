# RailPulse

**Railcar fleet maintenance analytics: bad order reporting, repair demand forecasting, and shop assignment optimization.**

A 12,000 car railcar fleet generates about 800 bad orders a month. Somebody has to answer three questions every quarter: what is breaking, how much of it is coming next month, and which shop should fix it. RailPulse answers all three, end to end, from raw operational records to a published dashboard.

Everything runs with one command and reproduces exactly, because the data generator is seeded.

```bash
pip install -r requirements.txt
python run_all.py
# then open outputs/dashboard.html
```

Runs in about 30 seconds. No database server, no cloud account, no API keys.

---

## Why this project exists

Most portfolio projects stop at a model with a good score. Operational analytics does not work that way. The model is maybe a fifth of the job. The rest is knowing whether the data can be trusted, defining a metric so two reports agree on it, deciding what to do with the forecast once you have it, and being able to explain the whole chain to a planner who does not care what a Fourier term is.

So this project is built in the order the work actually happens:

**dirty data → validated data → shared definitions in SQL → analysis → forecast → decision → dashboard**

The interesting parts are the judgment calls, and I have written each one down in the code where it happens. Three of them are worth reading even if you skip everything else:

- Why I threw out the model that won the backtest ([step 5](#step-5-forecast-repair-demand))
- Why raw dwell time is an unfair way to rank shops ([step 4](#step-4-fleet-health-analysis))
- Why the optimizer idles a perfectly good shop, and why that is a question for management rather than an answer from a model ([step 6](#step-6-optimize-shop-assignment))

---

## Results

| | |
|---|---|
| Records processed | 30,072 raw → 28,822 clean (95.8% retained) |
| Data quality issues found | **2,909** across 9 checks (9.7% of raw rows) |
| Reporting query speedup | **~28% faster** after indexing the fact table |
| Forecast error | **3.3% MAPE** on 6 held out months, against 5.2% for seasonal naive |
| Optimizer saving | **3.2%** of monthly repair cost, about **$366k a year** |
| Scenario tested | Half capacity at the busiest shop adds 7.9% to monthly cost |
| Runtime, end to end | ~31 seconds |

### What the analysis found

1. Repair volume grew **6.8%** over three years, on top of a strong seasonal cycle. December runs 17% above an average month and June 13% below, a **34% swing** peak to trough. Any plan built on an annual average is wrong half the year.
2. **Boxcars** are the problem fleet at **1.01 bad orders per car per year**, 79% above autoracks.
3. Age matters, but not smoothly. Failure rate is flat to about 20 years, then bends up. Cars past 40 fail **90% more often** than cars under 10.
4. **9 of 14 defect codes** cause 80% of bad orders, led by thin wheel flanges.
5. Cracked sills and frames are only **2.9% of bad orders but 13.4% of repair spend**, a 4.6x ratio. A report ranked by volume would put this near the bottom of the page.
6. Shop turnaround is uneven in a way repair mix does not explain. After adjusting for what each shop actually works on, **Waycross holds cars 24% longer** than the network and **Kansas City 14% shorter**. That is a scheduling gap, not a mix difference.
7. **515 cars, 4.3% of the fleet**, had six or more bad orders in three years and account for **11.7% of repair spend**. That is a candidate list for full inspection instead of another patch.

---

## The pipeline

| Step | File | What it does |
|---|---|---|
| 1 | `src/01_generate_data.py` | Builds a realistic 12,000 car fleet and 3 years of repair events, then dirties about 7% of the rows on purpose |
| 2 | `src/02_data_quality.py` | Runs 9 validation checks, repairs what can be repaired, quarantines the rest with reasons |
| 3 | `src/03_build_database.py` | Loads SQLite, creates 6 reporting views, benchmarks the indexes |
| 4 | `src/04_fleet_health_report.py` | Trend, seasonality, car type, age curve, defect Pareto, shop scorecard |
| 5 | `src/05_repair_demand_forecast.py` | Six candidate models, backtested, then a 6 month forecast |
| 6 | `src/06_shop_assignment_optimizer.py` | Integer program assigning forecasted demand to shops, plus a what-if |
| 7 | `src/07_build_dashboard.py` | Assembles one self-contained HTML dashboard |

### Step 1: Generate the data

Real railcar maintenance data is not public, so this builds a stand-in with structure worth finding: older cars fail more, boxcars fail more than autoracks, winter is worse than summer, and volume drifts up as the fleet ages.

Then it breaks about 7% of it. Duplicate billing submissions, release dates before bad order dates, missing labor hours, orphan car IDs, defect codes with inconsistent casing and separators, and a handful of labor hour entries off by a factor of sixty. Clean synthetic data would make step 2 theater.

### Step 2: Validate and clean

Nine checks. The rule I follow is that no row disappears silently. Each one passes, gets repaired under a documented rule, or lands in `data/clean/quarantine.csv` with a reason column so somebody can go ask the shop what happened.

| Check | Severity | Rows | Action |
|---|---|---|---|
| Duplicate event IDs | HIGH | 618 | Keep first, drop the rest |
| Defect code formatting | MEDIUM | 756 | Normalize casing and separators |
| Defect code not in master | HIGH | 0 | Quarantine |
| Orphan car IDs | HIGH | 228 | Quarantine |
| Orphan shop IDs | HIGH | 0 | Quarantine |
| Negative or missing dwell | HIGH | 404 | Quarantine |
| Dwell over 180 days | LOW | 0 | Flag, keep |
| Labor hour outliers | MEDIUM | 30 | Cap at 240 hours |
| Missing labor hours | MEDIUM | 873 | Impute with median for that defect code |

Two decisions in there that I would defend in a review:

**Outliers get capped, not dropped.** A repair logged at 480 hours is a units error, but the repair still happened. Dropping the row would understate repair volume, which is the number the whole forecast is built on. Capping keeps the event and limits the damage to the cost figure.

**Missing hours are imputed by defect code, not by overall median.** A missing brake shoe job and a missing frame repair are not the same size. The overall median would inflate the small ones and crush the large ones, and the large ones are where the money is.

**Why the orphan IDs matter more than the count suggests.** 228 rows is 0.8%, which sounds ignorable. It is not. Those rows cannot join to car type or build year, so they vanish from every per-type and per-age breakdown while still sitting in the network total. That is exactly the kind of gap that makes two reports disagree and nobody can say why.

### Step 3: Database and views

SQLite, so the project runs anywhere, with SQL standard enough to move to Azure SQL or Fabric with small edits. One fact table at the grain of one bad order event, three dimensions.

Six views in `sql/02_views.sql` hold every shared definition: `v_monthly_demand`, `v_fleet_health_by_type`, `v_shop_scorecard`, `v_defect_pareto`, `v_age_band_reliability`, `v_repeat_offenders`. Bad order rate is defined once. The dashboard, the forecast, and any ad hoc query all read the same definition, so they cannot drift apart.

The index work is measured rather than asserted. The script drops the indexes, times a realistic shop report query 60 times, restores them, and times it again:

```
without indexes:   5.53 ms   (SCAN repair_events)
with indexes:      3.96 ms   (SEARCH USING INDEX idx_events_shop)
                   28% faster
```

Honest caveat: this is a small win in absolute terms, it lands somewhere between 26% and 29% depending on the machine, and I am reporting it because the method is right, not because 1.5 milliseconds matters. The reason to show it is that the same query plan change is what separates a two second dashboard from a two minute one at 30 million rows, and the way you find out is by measuring instead of guessing which columns to index.

### Step 4: Fleet health analysis

All aggregation happens in SQL against the views. Python only formats and charts. That split is deliberate: definitions live in one place.

The part I would talk about in an interview is the shop scorecard. Ranking shops by average dwell time is unfair and I nearly shipped it that way. Heavy repair shops look terrible on raw dwell because frame work takes longer everywhere, so the ranking would mostly be measuring which shops get sent hard jobs. The fix is to compare each shop against the network average **within the same repair class**, then average those ratios. What is left is the part of dwell the shop actually controls.

The ranking changes when you do this, and the finding survives it: Waycross is genuinely slow, not just unlucky in its job mix.

### Step 5: Forecast repair demand

36 monthly observations. That is a small sample, and the honest thing to do with a small sample is to admit what it can support: a trend and a seasonal shape, roughly five parameters. So rather than reach for the most sophisticated model, I tested six on six months none of them had seen.

```
Train: 2023-01 to 2025-06  (30 months)
Test:  2025-07 to 2025-12  ( 6 months, fully held out)
```

| Model | MAPE | MAE (cars) |
|---|---|---|
| Gradient boosting | **3.20%** | 25.3 |
| Trend + Fourier | 3.31% | 26.1 |
| Trend + month dummies | 3.61% | 28.1 |
| Seasonal naive | 5.24% | 43.7 |
| Naive mean | 8.62% | 73.2 |
| Trend only | 9.19% | 76.3 |

**I shipped the second place model, and this is the most important paragraph in the README.**

Gradient boosting won by a tenth of a point on six data points, which is noise. But there is a real reason to reject it that has nothing to do with the score. A tree can only predict values it has already seen. It cannot extrapolate. So I asked both models about 2026 and compared:

| | Next 12 months | Implied growth |
|---|---|---|
| Trailing 12 actual | 9,915 | n/a |
| Gradient boosting | 9,874 | **-0.4%** |
| Trend + Fourier | 10,250 | **+3.4%** |

History has grown about 3.3% a year for three straight years. Gradient boosting projects the growth stopping, not because it has a view about the fleet but because it structurally cannot output a number above its training range. On a holdout that sits close to the training data, that flaw is invisible. On a forecast that has to reach forward twelve months, it is the whole ballgame.

`Trend + month dummies` is in the table for a related reason. It has the same information as the Fourier version and more parameters, twelve of them on thirty rows, and it scored worse. That is what overfitting looks like when you can see it.

**Prediction intervals** come from the holdout error, not from a textbook formula. If the model was off by 3.3% on months it had never seen, then 3.3% is what I quote, rather than a standard error that assumes the model is correctly specified.

**Per car type**, the same spec gives 4.6% to 9.8% MAPE. Error rises as segments shrink, and autoracks are worst at 9.8% on a 720 car fleet. I report that rather than hide it, because a planner using the autorack number needs to know it is softer than the network number.

Forecast for the first half of 2026:

| Month | Bad orders | 95% range | Labor hours | Cars per day |
|---|---|---|---|---|
| 2026-01 | 961 | 901 to 1,021 | 8,476 | 31.6 |
| 2026-02 | 925 | 867 to 983 | 8,162 | 30.4 |
| 2026-03 | 862 | 808 to 916 | 7,606 | 28.4 |
| 2026-04 | 805 | 754 to 855 | 7,098 | 26.5 |
| 2026-05 | 774 | 725 to 823 | 6,828 | 25.5 |
| 2026-06 | 770 | 721 to 818 | 6,789 | 25.3 |

January is 16% above the trailing twelve month average. That is the month to staff for.

### Step 6: Optimize shop assignment

The forecast says 961 cars in January. This decides where they go.

An integer program over region, repair class, and shop. Cost per car is:

```
labor  =  repair hours  x  shop labor rate  x  specialty penalty
move   =  deadhead miles from region to shop  x  $2.10 per mile
```

Subject to: all demand assigned, no shop over capacity, no move longer than 1,500 miles.

The specialty penalty is the part I like. A running repair shop can do a heavy frame job, it just takes longer, so hours get multiplied by 1.00 for a match and up to 1.30 for a bad mismatch. Nobody hard codes "send frame work to heavy shops." The cost function makes that happen on its own, and it also lets the model override it when geography says otherwise.

**Why an optimizer and not a rule.** The tradeoff genuinely has no obvious answer. Roseville has the highest labor rate but sits next to western demand. Waycross is cheap but small. Sending a car 900 miles to save $20 an hour is clearly right for a 40 hour frame repair and clearly wrong for a 2 hour air hose. A rule has to pick one answer. An LP prices all 150 combinations at once.

**The baseline is not a straw man.** It is nearest shop in the home region, spill to next nearest when full, biggest jobs placed first. That is close to what a dispatcher does and close to what the history shows: 14.2% of repairs went outside the home region. Both plans are priced with the same cost function, so the difference is the decision and not the accounting.

| | Baseline | Optimized |
|---|---|---|
| Total cost | $953,024 | **$922,553** |
| Cost per car | $992 | **$960** |
| Moved out of region | 0% | 5.6% (14.2% in history) |
| Average move | 0 miles | 89 miles |

**3.2% saving, about $366k a year at this volume.** That number is small and I am not dressing it up. The network already has 24% slack in the peak month, and when capacity is loose, nearest shop dispatch is already close to right. The saving would grow as utilization tightens, which is exactly what the volume trend in step 4 says is coming.

Three findings that matter more than the dollar figure:

**The plan concentrates work, it does not spread it.** Five of ten shops finish at exactly capacity. That says capacity is the binding constraint, not labor rate, so buying a slot at a cheap shop is worth more than negotiating a rate anywhere. That is a useful thing to know before the next budget conversation.

**Specialty match went down, from 38% to 33%, and the plan is still cheaper.** The optimizer traded specialty match for rate and distance. That is the tradeoff working rather than a bug: a mismatched shop 100 miles closer can beat a matched shop 600 miles away. Worth flagging because someone will look at that number and think the model is broken.

**Tucson drops to zero cars, and I do not think the model gets the last word on that.** It sits 711 miles from the nearest demand centroid, so a closer shop beats it on both distance and rate for every job. That is a real signal worth a conversation about whether the capacity is in the right place. It is also partly an artifact of my own modeling choice: I collapsed demand to five regional centroids, which is unfair to a shop that serves a spread out area. I would want finer geography before anyone acted on it. Flagging the limitation is part of the finding.

**Scenario test.** The question after "what is the plan" is always "what if." Halving the busiest shop's capacity, which is what a two week shutdown looks like across a month, is still feasible but adds **7.9% to monthly cost** and pushes out of region moves from 54 to 116 cars. Answering that takes one re-solve, which is the practical argument for building the optimizer in the first place.

### Step 7: Dashboard

One HTML file, images embedded, opens in any browser, survives being emailed. It stands in for the Power BI or Fabric report a real team would publish.

The part that matters is that every figure on the page is read from the CSV files the earlier steps wrote. Nothing is typed in. The dashboard cannot drift away from the analysis, and rerunning the pipeline updates it.

---

## What I would do differently with more time

Being straight about the gaps, since somebody will ask:

- **The data is synthetic.** I chose the patterns the analysis then finds, which is circular. What the project demonstrates is method, not discovery.
- **36 months is not enough** to separate trend from a long cycle. With five years I would test whether the growth is a trend or the upswing of something slower.
- **No weather data.** The seasonal term absorbs winter as an average effect. A cold snap forecast would be a real feature and probably beat the seasonal average.
- **The optimizer plans a month at a time.** Repairs cross month boundaries and shop queues carry over, so a rolling multi period model would be more honest about capacity.
- **Region centroids are coarse.** Five points for the continental United States is enough to rank shops roughly and not enough to conclude anything about a remote one, as the Tucson finding shows.
- **No survival model.** Predicting which specific car fails next is a different and more valuable problem than predicting how many will. The repeat offender list is a crude first pass at it.

---

## Repository layout

```
railpulse/
├── README.md
├── requirements.txt
├── run_all.py                          run everything
├── sql/
│   ├── 01_schema.sql                   tables and indexes
│   ├── 02_views.sql                    6 reporting views, all shared definitions
│   └── 03_reporting_queries.sql        standalone queries for ad hoc work
├── src/
│   ├── 01_generate_data.py
│   ├── 02_data_quality.py
│   ├── 03_build_database.py
│   ├── 04_fleet_health_report.py
│   ├── 05_repair_demand_forecast.py
│   ├── 06_shop_assignment_optimizer.py
│   ├── 07_build_dashboard.py
│   └── viz_style.py                    shared chart styling
├── docs/
│   ├── DATA_DICTIONARY.md              every table, column, and metric definition
│   ├── METHOD_NOTES.md                 the judgment calls, written out
│   └── RESUME_BULLETS.md
├── data/                               generated, not committed
└── outputs/
    ├── dashboard.html                  start here
    ├── charts/                         8 PNG charts
    └── *.csv                           every table behind the dashboard
```

## Stack

Python 3.12, pandas, numpy, scikit-learn, PuLP with CBC, matplotlib, SQLite. Standard library for everything else.

```bash
pip install -r requirements.txt
```

## Reproducing

Seeded throughout. `python run_all.py` produces the numbers in this README exactly. The one exception is the index benchmark in step 3, which measures wall clock time and will vary by a millisecond or two by machine.
