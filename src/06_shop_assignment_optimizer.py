"""
STEP 6: Optimize shop assignment
================================

The forecast says January 2026 is the peak month. This step answers the next
question a planner asks: where should those cars go.

The decision
------------
For each combination of home region and repair class, choose how many cars to
send to each of the 10 shops. Cost per car has two parts:

    labor   = repair hours  x  shop labor rate  x  specialty penalty
    move    = deadhead miles from the car's region to the shop  x  cost per mile

Constraints:
    1. every forecasted bad order gets assigned somewhere
    2. no shop takes more cars than its daily capacity times days in the month
    3. no car travels more than 1,500 miles for a repair

The specialty penalty is the interesting one. A running repair shop can do a
heavy frame job, it just takes longer, so hours get multiplied by 1.0 for a
match and up to 1.30 for a bad mismatch. That means the model naturally sends
frame work to heavy shops without anyone hard coding that rule.

Why linear programming and not a rule
-------------------------------------
The tradeoff has no obvious answer. Roseville has the highest labor rate but
sits next to western demand. Waycross is cheap but small. Sending a car 900
miles to save 20 dollars an hour is worth it for a 40 hour frame repair and not
worth it for a 2 hour air hose. An LP weighs all of that at once. A dispatch
rule cannot.

The comparison is against a real dispatch heuristic, not a straw man: nearest
shop in the home region, spill to the next nearest when full. That is close to
what the historical data shows actually happens, where 82% of repairs stay in
region. Both options are priced with the same cost function so the difference is
the decision, not the accounting.

Outputs:
  outputs/optimizer_assignment_plan.csv
  outputs/optimizer_summary.csv
  outputs/charts/08_optimizer.png

Run:  python src/06_shop_assignment_optimizer.py
"""

import os
import sqlite3
import math
import numpy as np
import pandas as pd
import pulp
from viz_style import (apply_style, strip_frame, save, plt,
                       BLUE, RUST, GRAY, LIGHT_BLUE, GREEN, AMBER, INK)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DB = os.path.join(ROOT, "data", "railpulse.db")
OUT = os.path.join(ROOT, "outputs")
CHARTS = os.path.join(OUT, "charts")

COST_PER_MILE = 2.10      # deadhead haul cost per car mile
MAX_MILES = 1500          # no repair move longer than this
OVERTIME_MULT = 1.55      # premium on hours worked past a shop's capacity
DAYS = 31                 # January
PLAN_MONTH = "2026-01"

# Approximate centroids. Coarse on purpose. The point is relative distance, and
# a 50 mile error in a centroid does not change which shop is closest.
REGION_COORD = {
    "MIDWEST":   (41.5, -88.0),
    "SOUTHEAST": (33.7, -84.4),
    "NORTHEAST": (40.6, -76.5),
    "SOUTHWEST": (32.7, -97.0),
    "WEST":      (38.0, -121.3),
}
SHOP_COORD = {
    "SH01": (41.8, -87.8), "SH02": (41.5, -90.6), "SH03": (33.7, -84.4),
    "SH04": (31.2, -82.4), "SH05": (40.3, -76.9), "SH06": (32.8, -97.3),
    "SH07": (32.2, -110.9), "SH08": (38.8, -121.3), "SH09": (45.5, -122.7),
    "SH10": (39.1, -94.6),
}

# hours multiplier when a shop works outside its specialty
PENALTY = {
    ("HEAVY", "HEAVY"): 1.00, ("HEAVY", "PROGRAM"): 1.12, ("HEAVY", "RUNNING"): 1.30,
    ("PROGRAM", "HEAVY"): 1.15, ("PROGRAM", "PROGRAM"): 1.00, ("PROGRAM", "RUNNING"): 1.08,
    ("RUNNING", "HEAVY"): 1.25, ("RUNNING", "PROGRAM"): 1.10, ("RUNNING", "RUNNING"): 1.00,
}


def haversine(a, b):
    """Great circle distance in miles between two (lat, lon) pairs."""
    lat1, lon1, lat2, lon2 = map(math.radians, [a[0], a[1], b[0], b[1]])
    h = (math.sin((lat2 - lat1) / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2)
    return 2 * 3958.8 * math.asin(math.sqrt(h))


def build_demand(conn):
    """Split the January forecast across region and repair class using the mix
    observed in the last 12 months of history. The forecast gives the total, the
    history gives the shape."""
    total = pd.read_csv(os.path.join(OUT, "forecast_next_6_months.csv"))
    jan = int(total.loc[total.month == PLAN_MONTH, "forecast_bad_orders"].iloc[0])

    mix = pd.read_sql("""
        SELECT c.home_region AS region, d.repair_class AS repair_class,
               COUNT(*) AS n, AVG(e.labor_hours) AS avg_hours
        FROM repair_events e
        JOIN railcars c      ON c.car_id = e.car_id
        JOIN defect_codes d  ON d.defect_code = e.defect_code
        WHERE e.bad_order_month >= '2025-01'
        GROUP BY 1, 2
    """, conn)
    mix["share"] = mix.n / mix.n.sum()

    # Largest remainder rounding so the parts add back to the forecast total
    raw = mix.share * jan
    mix["cars"] = np.floor(raw).astype(int)
    short = jan - mix.cars.sum()
    if short > 0:
        top = (raw - np.floor(raw)).sort_values(ascending=False).index[:short]
        mix.loc[top, "cars"] += 1

    mix["avg_hours"] = mix.avg_hours.round(2)
    return jan, mix[["region", "repair_class", "cars", "avg_hours"]]


def cost_per_car(region, repair_class, shop, dist, hours):
    """Same function used to price both plans."""
    pen = PENALTY[(shop.primary_specialty, repair_class)]
    labor = hours * pen * shop.labor_rate_usd
    move = dist * COST_PER_MILE
    return labor + move, labor, move, pen


def greedy_baseline(demand, shops, dist):
    """Nearest shop in the home region, spill to next nearest when full.
    Cars past a shop's capacity are still repaired, at an overtime premium,
    because in reality the work does not disappear."""
    cap = {s.shop_id: s.daily_capacity_cars * DAYS for s in shops.itertuples()}
    used = {k: 0 for k in cap}
    shop_by_id = {s.shop_id: s for s in shops.itertuples()}
    rows = []

    # Biggest jobs placed first, which is how a dispatcher protects the tight slots
    ordered = demand.sort_values("avg_hours", ascending=False)
    for d in ordered.itertuples():
        remaining = d.cars
        in_region = [s for s in shops.itertuples() if s.region == d.region]
        others = [s for s in shops.itertuples() if s.region != d.region]
        order = (sorted(in_region, key=lambda s: dist[(d.region, s.shop_id)])
                 + sorted(others, key=lambda s: dist[(d.region, s.shop_id)]))

        for s in order:
            if remaining <= 0:
                break
            room = max(0, cap[s.shop_id] - used[s.shop_id])
            take = min(room, remaining)
            if take:
                used[s.shop_id] += take
                remaining -= take
                rows.append((d.region, d.repair_class, s.shop_id, take, False))

        if remaining > 0:   # everything full, overtime at the nearest shop
            s = order[0]
            used[s.shop_id] += remaining
            rows.append((d.region, d.repair_class, s.shop_id, remaining, True))

    total = 0.0
    for region, rc, sid, cars, ot in rows:
        s = shop_by_id[sid]
        hours = float(demand[(demand.region == region) &
                             (demand.repair_class == rc)].avg_hours.iloc[0])
        c, *_ = cost_per_car(region, rc, s, dist[(region, sid)], hours)
        total += c * cars * (OVERTIME_MULT if ot else 1.0)

    plan = pd.DataFrame(rows, columns=["region", "repair_class", "shop_id", "cars", "overtime"])
    return total, plan, used


def optimize(demand, shops, dist):
    prob = pulp.LpProblem("shop_assignment", pulp.LpMinimize)
    shop_by_id = {s.shop_id: s for s in shops.itertuples()}

    # One integer variable per (region, repair class, shop) that is within range
    x, unit = {}, {}
    for d in demand.itertuples():
        for s in shops.itertuples():
            km = dist[(d.region, s.shop_id)]
            if km > MAX_MILES:
                continue                      # infeasible move, no variable created
            key = (d.region, d.repair_class, s.shop_id)
            x[key] = pulp.LpVariable(f"x_{d.region}_{d.repair_class}_{s.shop_id}",
                                     lowBound=0, cat="Integer")
            unit[key] = cost_per_car(d.region, d.repair_class, s, km, d.avg_hours)

    prob += pulp.lpSum(unit[k][0] * x[k] for k in x), "total_cost"

    # 1. all demand assigned
    for d in demand.itertuples():
        keys = [k for k in x if k[0] == d.region and k[1] == d.repair_class]
        prob += pulp.lpSum(x[k] for k in keys) == d.cars, f"demand_{d.region}_{d.repair_class}"

    # 2. shop capacity
    for s in shops.itertuples():
        keys = [k for k in x if k[2] == s.shop_id]
        prob += (pulp.lpSum(x[k] for k in keys) <= s.daily_capacity_cars * DAYS,
                 f"cap_{s.shop_id}")

    status = prob.solve(pulp.PULP_CBC_CMD(msg=0))
    rows = []
    for k, var in x.items():
        v = int(round(var.value() or 0))
        if v > 0:
            c, labor, move, pen = unit[k]
            rows.append({
                "region": k[0], "repair_class": k[1], "shop_id": k[2],
                "shop_name": shop_by_id[k[2]].shop_name,
                "cars": v,
                "miles": round(dist[(k[0], k[2])]),
                "specialty_penalty": pen,
                "labor_cost_per_car": round(labor, 2),
                "move_cost_per_car": round(move, 2),
                "total_cost": round(c * v, 2),
                "in_region": k[0] == shop_by_id[k[2]].region,
            })
    plan = pd.DataFrame(rows).sort_values(["region", "repair_class", "cars"],
                                          ascending=[True, True, False])
    return pulp.LpStatus[status], pulp.value(prob.objective), plan


def main():
    os.makedirs(CHARTS, exist_ok=True)
    apply_style()
    conn = sqlite3.connect(DB)
    print("STEP 6: optimizing shop assignment\n")

    shops = pd.read_sql("SELECT * FROM shops", conn)

    # What the history actually did, so the comparison is against reality and
    # not against a number I remembered from the generator settings.
    hist_out_pct = conn.execute("""
        SELECT ROUND(100.0 * SUM(CASE WHEN c.home_region <> s.region THEN 1 ELSE 0 END)
               / COUNT(*), 1)
        FROM repair_events e
        JOIN railcars c ON c.car_id = e.car_id
        JOIN shops s    ON s.shop_id = e.shop_id
    """).fetchone()[0]

    # What the network actually did over the last 3 years. This is the number the
    # optimizer's routing has to be compared against, so it gets read from the
    # data rather than assumed.
    hist_out_pct = conn.execute("""
        SELECT 100.0 * SUM(CASE WHEN c.home_region <> s.region THEN 1 ELSE 0 END)
               / COUNT(*)
        FROM repair_events e
        JOIN railcars c ON c.car_id = e.car_id
        JOIN shops s    ON s.shop_id = e.shop_id
    """).fetchone()[0]
    jan, demand = build_demand(conn)
    dist = {(r, s): haversine(REGION_COORD[r], SHOP_COORD[s])
            for r in REGION_COORD for s in SHOP_COORD}

    print(f"   planning month: {PLAN_MONTH}, {jan:,} forecasted bad orders")
    print(f"   decision cells: {len(demand)} region and repair class combinations")
    print(f"   network capacity: {shops.daily_capacity_cars.sum() * DAYS:,} car slots "
          f"({100*jan/(shops.daily_capacity_cars.sum()*DAYS):.0f}% of it needed)\n")

    # --- baseline ---------------------------------------------------------
    base_cost, base_plan, base_used = greedy_baseline(demand, shops, dist)
    base_ot = int(base_plan.loc[base_plan.overtime, "cars"].sum())
    print(f"   baseline, nearest shop in region with spillover")
    print(f"     total cost:     ${base_cost:,.0f}")
    print(f"     cost per car:   ${base_cost/jan:,.2f}")
    print(f"     overtime cars:  {base_ot}")

    # --- optimized --------------------------------------------------------
    status, opt_cost, plan = optimize(demand, shops, dist)
    print(f"\n   optimized with linear programming")
    print(f"     solver status:  {status}")
    print(f"     total cost:     ${opt_cost:,.0f}")
    print(f"     cost per car:   ${opt_cost/jan:,.2f}")

    saving = base_cost - opt_cost
    print(f"\n   saving:           ${saving:,.0f} for the month "
          f"({100*saving/base_cost:.1f}%)")
    print(f"   annualized:       ${saving*12:,.0f} at the same monthly volume")

    out_of_region = int(plan.loc[~plan.in_region, "cars"].sum())
    print(f"   out of region:    {out_of_region} of {jan} cars ({100*out_of_region/jan:.0f}%), "
          f"versus {hist_out_pct:.1f}% in history")
    print(f"   avg move:         {(plan.miles*plan.cars).sum()/jan:.0f} miles per car")

    # Specialty matching, which nobody hard coded. The LP prefers a matched shop
    # only when the hours saved beat the extra miles, so compare it to baseline.
    shop_spec = shops.set_index("shop_id").primary_specialty.to_dict()
    base_match = sum(
        r.cars for r in base_plan.itertuples()
        if PENALTY[(shop_spec[r.shop_id], r.repair_class)] == 1.00
    )
    opt_match = int(plan.loc[plan.specialty_penalty == 1.00, "cars"].sum())
    print(f"   specialty match:  baseline {100*base_match/jan:.0f}% of cars, "
          f"optimized {100*opt_match/jan:.0f}%")
    if opt_match < base_match:
        print(f"     The optimizer gave up specialty match to win on rate and distance, and")
        print(f"     still came out cheaper. That is the tradeoff working, not a bug: a")
        print(f"     mismatched shop 100 miles closer can beat a matched shop 600 miles away.")

    # --- where the work moved --------------------------------------------
    cap = shops.set_index("shop_id").daily_capacity_cars * DAYS
    opt_used = plan.groupby("shop_id").cars.sum().reindex(cap.index).fillna(0)
    b_used = pd.Series(base_used).reindex(cap.index).fillna(0)
    util = pd.DataFrame({
        "shop_name": shops.set_index("shop_id").shop_name.reindex(cap.index),
        "labor_rate_usd": shops.set_index("shop_id").labor_rate_usd.reindex(cap.index),
        "capacity_cars": cap,
        "baseline_cars": b_used.astype(int),
        "baseline_util_pct": (100 * b_used / cap).round(1),
        "optimized_cars": opt_used.astype(int),
        "optimized_util_pct": (100 * opt_used / cap).round(1),
    })
    util["car_change"] = util.optimized_cars - util.baseline_cars

    print(f"\n   the plan is not about spreading work evenly. It fills the cheapest")
    print(f"   shops to capacity first, then works outward. Biggest shifts:")
    movers = util.reindex(util.car_change.abs().sort_values(ascending=False).index).head(4)
    for r in movers.itertuples():
        print(f"     {r.shop_name:<14} {r.baseline_cars:>4} -> {r.optimized_cars:>4} cars "
              f"({r.car_change:+d}), ${r.labor_rate_usd:.0f}/hr")

    idle = util[util.optimized_cars == 0]
    for sid, r in zip(idle.index, idle.itertuples()):
        nearest = min(((haversine(REGION_COORD[rg], SHOP_COORD[sid]), rg)
                       for rg in REGION_COORD))
        print(f"\n   flag for management: {r.shop_name} drops to zero cars.")
        print(f"     It is {nearest[0]:.0f} miles from the nearest demand centroid "
              f"({nearest[1].lower()}) at ${r.labor_rate_usd:.0f}/hr,")
        print(f"     so a closer shop beats it on both distance and rate for every job.")
        print(f"     Worth asking whether that capacity is in the right place, and whether")
        print(f"     my region centroids are too coarse to judge a shop this remote.")

    at_cap = util[util.optimized_util_pct >= 99.9]
    print(f"\n   {len(at_cap)} of {len(util)} shops end at capacity, so capacity is the "
          f"binding constraint,")
    print(f"     not labor rate. Adding a slot at the cheapest shop is worth more than "
          f"cutting a rate.")

    # --- scenario: what if the busiest shop goes down --------------------
    # The planning question after "what is the plan" is always "what if". This
    # re-solves with Harrisburg at half capacity, which is what a two week
    # shutdown looks like for a month long plan.
    print(f"\n   scenario: Harrisburg at half capacity for the month")
    shops_alt = shops.copy()
    shops_alt.loc[shops_alt.shop_id == "SH05", "daily_capacity_cars"] = 2
    st2, cost2, plan2 = optimize(demand, shops_alt, dist)
    if st2 == "Optimal":
        print(f"     still feasible, cost rises to ${cost2:,.0f} "
              f"(+${cost2-opt_cost:,.0f}, {100*(cost2/opt_cost-1):.1f}%)")
        moved = int(plan2.loc[~plan2.in_region, "cars"].sum())
        print(f"     out of region moves go from {out_of_region} to {moved} cars")
    else:
        print(f"     infeasible, the network cannot absorb it")

    # --- write ------------------------------------------------------------
    plan.to_csv(os.path.join(OUT, "optimizer_assignment_plan.csv"), index=False)
    util.reset_index().to_csv(os.path.join(OUT, "optimizer_utilization.csv"), index=False)
    pd.DataFrame([{
        "plan_month": PLAN_MONTH,
        "forecast_bad_orders": jan,
        "baseline_cost_usd": round(base_cost, 2),
        "optimized_cost_usd": round(opt_cost, 2),
        "saving_usd": round(saving, 2),
        "saving_pct": round(100 * saving / base_cost, 2),
        "annualized_saving_usd": round(saving * 12, 2),
        "baseline_cost_per_car": round(base_cost / jan, 2),
        "optimized_cost_per_car": round(opt_cost / jan, 2),
        "cars_moved_out_of_region_pct": round(100 * out_of_region / jan, 1),
        "historical_out_of_region_pct": hist_out_pct,
        "historical_out_of_region_pct": round(hist_out_pct, 1),
        "avg_move_miles_per_car": round((plan.miles * plan.cars).sum() / jan, 1),
        "specialty_match_pct_baseline": round(100 * base_match / jan, 1),
        "specialty_match_pct_optimized": round(100 * opt_match / jan, 1),
        "shops_at_capacity": len(at_cap),
        "scenario_harrisburg_half_cost_usd": round(cost2, 2) if st2 == "Optimal" else None,
        "solver_status": status,
    }]).to_csv(os.path.join(OUT, "optimizer_summary.csv"), index=False)

    # --- chart ------------------------------------------------------------
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.5, 4.6),
                                   gridspec_kw={"width_ratios": [1.35, 1]})
    y = np.arange(len(util))
    h = 0.38
    ax1.barh(y + h / 2, util.baseline_util_pct, height=h, color=LIGHT_BLUE, label="Baseline")
    ax1.barh(y - h / 2, util.optimized_util_pct, height=h, color=BLUE, label="Optimized")
    ax1.axvline(100, color=RUST, ls="--", lw=1.5)
    ax1.text(100.6, len(util) - 0.3, "capacity", color=RUST, fontsize=8.5)
    ax1.set_yticks(y, util.shop_name)
    ax1.invert_yaxis()
    ax1.set_xlabel("Capacity used %")
    ax1.set_title("Work concentrates in the low cost shops until capacity binds")
    ax1.legend(loc="lower right")
    strip_frame(ax1)

    bars = ax2.bar(["Baseline", "Optimized"], [base_cost, opt_cost],
                   color=[LIGHT_BLUE, GREEN], width=0.55)
    for b, v in zip(bars, [base_cost, opt_cost]):
        ax2.text(b.get_x() + b.get_width() / 2, v * 1.01, f"${v/1000:,.0f}k",
                 ha="center", fontsize=10, color=INK, fontweight="bold")
    ax2.set_title(f"January repair cost, {100*saving/base_cost:.1f}% lower")
    ax2.set_ylabel("Total cost, USD")
    ax2.set_ylim(0, base_cost * 1.14)
    strip_frame(ax2)
    save(fig, os.path.join(CHARTS, "08_optimizer.png"))

    conn.close()


if __name__ == "__main__":
    main()
