# Method Notes

The judgment calls, written out. The code says what I did. This says why, and what I would say if someone pushed back.

---

## 1. Why the model that won the backtest did not ship

**The situation.** Six models scored on six months none of them had seen. Gradient boosting came first at 3.20% MAPE. Trend plus Fourier came second at 3.31%. I shipped the second one.

**Why.** Two reasons, and the second is the real one.

First, 0.11 percentage points on six data points is noise. There is no meaningful difference between those two numbers with a sample that small. Treating a gap that thin as a result would be reading tea leaves.

Second, and this is the part that actually decides it: a tree cannot extrapolate. A gradient boosting model predicts by averaging training observations that land in the same leaf, so its output is structurally bounded by the range it was trained on. Ask it about a month with higher demand than anything it has seen and it returns the highest thing it has seen.

I did not want to assert that, so I tested it. Both models, asked for the next 12 months:

| | Next 12 months | Implied growth |
|---|---|---|
| Trailing 12 actual | 9,915 | n/a |
| Gradient boosting | 9,874 | **-0.4%** |
| Trend + Fourier | 10,250 | **+3.4%** |

The fleet has grown about 3.3% a year for three consecutive years and it is aging, which is the mechanism driving the growth. Gradient boosting projects that stopping dead. Not because it has a view about the fleet, but because it cannot output a number above its ceiling.

**The general lesson.** The holdout sat close to the training range, so the flaw was invisible in the backtest. A validation design can be correct and still fail to test the thing that matters. For a forecast whose entire job is to reach forward, extrapolation behavior is a requirement, not a nice-to-have, and no MAPE column will tell you about it.

**If someone pushes back:** "Couldn't you fix gradient boosting by detrending first?" Yes, and that is the right follow-up. Fit the trend linearly, model the residuals with a tree, add them back. I did not do it because with 36 observations the residuals after a trend and seasonal term are close to noise and there is nothing left for a tree to learn. At 5 years of history with weather and traffic features I would revisit it.

---

## 2. Why raw dwell time is an unfair way to rank shops

**The mistake I nearly shipped.** Average dwell days by shop, sorted ascending. It runs in one line of SQL and it is wrong.

Heavy repair shops look terrible on raw dwell because frame work takes 40 hours and waits on parts, everywhere, no matter who does it. So a ranking on raw dwell is mostly a ranking of which shops get sent hard jobs. Publishing it would have told Harrisburg to speed up when its actual problem was that it gets all the heavy work.

**The fix.** Compare each shop against the network average **within the same repair class**, then average the ratios:

```
for each shop and repair class:
    ratio = shop dwell for that class / network dwell for that class
mix adjusted = mean of that shop's ratios
```

This is stratification. Same idea as age-adjusting a mortality rate.

**What survived.** The ranking changed and the headline finding held. Waycross runs 24% above the network and Kansas City 14% below, after adjusting for what they actually work on. That is a scheduling and staffing gap, not a mix artifact, and it is now a claim I would defend in front of the shop manager.

**If someone pushes back:** "Doesn't repair class hide variation inside it?" Yes. `HEAVY` covers both a bearing job and a cracked sill, and those are not the same. Adjusting at the defect code level would be tighter. I did not, because some shop and defect cells drop below 20 events and the ratios get noisy. Three classes was the trade between fairness and stability. With more history I would go finer.

---

## 3. Why the quality gate repairs some rows and quarantines others

The rule: **nothing disappears silently.** Every row passes, gets repaired under a written rule, or lands in `quarantine.csv` with a reason. A silent drop is how a report ends up wrong in a way nobody can trace back.

The decision for each row is whether the record is recoverable.

**Quarantine when the row cannot be interpreted.** An orphan car ID cannot join to car type or build year. A release date before the bad order date means one of the two dates is wrong and there is no way to tell which. Guessing would fabricate data.

**Repair when only one field is wrong and the event is real.** Labor hours of 480 is a units error, but the repair happened. Dropping the row would understate repair volume, which is the number the entire forecast is built on. Capping at 240 keeps the event and limits the damage to one field.

**Why imputation is by defect code, not overall median.** A missing brake shoe job and a missing frame repair are not the same size. The overall median inflates the small ones and crushes the large ones, and the large ones are where the money is. The `labor_hours_imputed` flag stays on the row so any downstream cost figure can be audited, and query 7 in `sql/03_reporting_queries.sql` exists to check exactly that.

**Why 228 orphan rows matter more than 0.8% suggests.** They cannot join to car type, so they vanish from every per-type breakdown while still counting in the network total. Per-type numbers will not sum to the total and nobody will be able to say why. Small percentages of unjoinable rows cause disproportionate confusion, because the failure shows up as an inconsistency rather than an error.

---

## 4. Why linear programming instead of a dispatch rule

**The tradeoff has no fixed answer.** Roseville has the highest labor rate at $95/hour and sits next to western demand. Waycross is the cheapest at $68 and is small. Sending a car 900 miles to save $20 an hour is obviously right for a 40 hour frame repair and obviously wrong for a 2 hour air hose. The correct choice flips depending on job size, and a rule has to commit to one answer.

The cost function makes it explicit:

```
cost per car  =  hours × specialty penalty × shop rate  +  miles × $2.10
```

Labor scales with job size and the move does not. That single fact is why the answer flips, and an LP prices all 150 region-class-shop combinations against each other at once.

**Why integer and not continuous.** Cars are whole. The problem is small enough that CBC solves it instantly, so there is no reason to relax it.

**Why the baseline is not a straw man.** Nearest shop in the home region, spill to next nearest when full, biggest jobs placed first. That is close to what a dispatcher does, and the history backs it up: 14.2% of repairs went outside the home region. Both plans are priced with the identical cost function, so the gap is the decision and not the accounting. Comparing an optimizer to a deliberately stupid baseline is the most common way optimization results get inflated.

---

## 5. Why the savings number is small, and why I left it that way

3.2% of monthly cost. About $366k a year. That is a modest number and dressing it up would be the wrong instinct.

**The reason is structural.** The network has roughly 24% slack in the peak month. When capacity is loose, nearest-shop dispatch is already close to optimal, because the constraint that would force an expensive choice never binds. Optimization pays off when capacity is tight.

**Which makes it a forward-looking number.** Volume grew 6.8% over three years and the fleet is aging. As utilization climbs, the gap between a rule and an optimizer widens. Reporting 3.2% honestly and explaining the mechanism is more useful than a bigger number from a rigged baseline, because it tells you *when* to invest in the tool.

**What I would say in an interview:** the value here is not the 3.2%. It is that the model answered the shutdown scenario in one re-solve, and that it surfaced capacity as the binding constraint. Both of those change a budget conversation. The savings number is the smallest thing the optimizer produced.

---

## 6. What the optimizer found that I did not expect

**Five of ten shops finish at exactly capacity.** That is the answer to a question nobody asked: capacity is the binding constraint, not labor rate. So buying a slot at a cheap shop is worth more than negotiating a rate anywhere. Useful before a budget cycle.

**Specialty match went down, from 38% to 33%, and the plan is still cheaper.** The optimizer traded specialty match for rate and distance. That is the tradeoff working, not a bug: a mismatched shop 100 miles closer can beat a matched shop 600 miles away. Worth flagging in advance, because it is the number someone will point at to claim the model is broken.

**Tucson drops to zero cars, and the model does not get the last word.** It sits 711 miles from the nearest demand centroid, so a closer shop beats it on both distance and rate for every job. That is a real signal about whether the capacity is in the right place.

It is also partly an artifact of my own choice. I collapsed demand to five regional centroids, which is unfair to a shop serving a spread out area, since the real cars are not all sitting at 32.7°N, 97.0°W. Before anyone acted on this I would want demand geography at the yard level. Reporting the limitation alongside the finding is the difference between an analysis and a recommendation.

---

## 7. Why prediction intervals come from the holdout

The textbook interval uses the model's standard errors, which assumes the model is correctly specified. It is not. It is a five-parameter approximation of a fleet with weather, traffic, and parts availability driving it.

So the interval comes from how wrong the model actually was on months it had never seen: 3.3%. That number already contains every source of error, including the ones I did not think to model. It is empirical rather than theoretical, which for a planning number is the right trade.

It is also conservative in one direction I should name: 6 holdout months is a thin basis for an error estimate, so the interval itself has wide uncertainty. With more history I would use rolling-origin backtesting to get a distribution of errors rather than one number.

---

## 8. What I would build next

In the order I would actually do it:

1. **Weather features.** The seasonal term absorbs winter as an average effect. Actual degree days and freeze-thaw cycles would beat a monthly average, and wheel defects run 23-27% above average in winter, so there is real signal there.
2. **Rolling multi-period optimization.** Repairs cross month boundaries and shop queues carry over. Planning a month in isolation overstates available capacity on the first of the month.
3. **Survival model for individual cars.** Predicting *which* car fails next is a different and more valuable problem than predicting how many will. The repeat offender list is a crude first pass. Cox proportional hazards on car age, type, defect history, and mileage would be the real version.
4. **Rolling-origin backtesting.** Score every model on 12 successive 6-month windows instead of one, and get a distribution of errors rather than a point estimate.
5. **Yard-level demand geography.** Fixes the Tucson problem and makes the deadhead costs real.

---

## Interview questions I would expect

**"Why not ARIMA or Prophet?"** Reasonable, and Prophet in particular is a good fit for this shape of problem. With 36 observations, ARIMA's parameter selection is unstable and Prophet's changepoint detection has almost nothing to work with. Trend plus Fourier is what Prophet does with its defaults anyway, minus the machinery, and being able to write out the whole model in one line matters when a planner asks why January is 961.

**"3.3% MAPE seems too good."** It should be questioned. Two reasons it is plausible: the target is a monthly count aggregated over 12,000 cars, so the law of large numbers is doing a lot of the work, and the data is synthetic with a seasonal structure I chose. The per-car-type numbers are the honest check. They run 4.6% to 9.8%, and autoracks are worst at 9.8% on a 720 car fleet. Error rises as segments shrink, which is what you would expect and is why I published the per-segment numbers instead of only the network one.

**"How would this run in production?"** Steps 2 and 3 become a scheduled job on the operational feed, with the quality report as an alerting surface, so any HIGH severity check exceeding its baseline rate should page somebody. The forecast reruns monthly and the model comparison reruns quarterly, because model choice can go stale as history accumulates. The optimizer runs on demand, since it is a planning tool. The dashboard becomes Power BI or Fabric over the same views, which is the reason all the definitions live in SQL rather than in Python.

**"What is the weakest part?"** The specialty penalty matrix. Those nine multipliers are my assumption, not a measurement, and they drive routing. I would validate them against real shop throughput by repair class before trusting the assignment plan. The centroid geography is second.
