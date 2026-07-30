# Resume Bullets and Application Copy

Written to the voice rules: no em dashes, contractions used, plain words, outcome first, metric in the first half of the bullet, one acronym maximum per bullet, exactly three bullets, readable by a smart non-technical person.

---

## Primary version, use this one

**RailPulse: Railcar Fleet Maintenance Analytics** | Python, SQL, scikit-learn, PuLP
*Personal project*

- Cut repair demand forecast error to 3.3% across six held-out months, beating a seasonal baseline by 37%, then rejected the higher-scoring gradient boosting model after showing it couldn't extrapolate a rising trend
- Found 2,909 data quality issues across nine automated checks on 30K maintenance records, quarantining unusable rows with documented reasons instead of dropping them silently
- Identified $366K in annual savings by building an integer program that assigns forecasted repairs across 10 shops on labor rate, distance, and capacity, then tested it against a shop shutdown scenario

**One note on wording.** The third bullet says "identified," not "saved." Nothing was deployed, and "saved" invites a follow-up question the honest answer can't survive. "Identified" is accurate and still lands.

---

## Alternate framings

### If the role leans reporting and BI

- Built a fleet maintenance dashboard over 29K repair records covering availability, dwell time, and bad order trends across 12,000 railcars, with every metric defined once in SQL so no two reports could disagree
- Cut reporting query time 28% by indexing the fact table on the columns the reports actually filtered on, verified by timing the query plan before and after rather than guessing
- Found 2,909 data quality issues across nine automated checks, including 228 orphan car IDs that would have quietly dropped out of every per-type breakdown while still counting in the totals

### If the role leans optimization and planning

- Identified $366K in annual savings with an integer program assigning forecasted repair demand across 10 shops on labor rate, deadhead distance, and shop capacity, measured against the dispatch rule already in use
- Showed capacity, not labor rate, was the binding constraint after five of ten shops finished at their limit, which reframes where the next dollar of investment should go
- Answered a shop shutdown scenario in one re-solve, quantifying the hit at 7.9% of monthly cost and doubling out-of-region moves

### Single line, if space is tight

- Built an end-to-end railcar maintenance analytics pipeline on 29K repair records: nine-check data quality gate, six-model forecast backtest at 3.3% error, and an integer program identifying $366K in annual shop assignment savings

---

## Portfolio site description

**RailPulse: Railcar Fleet Maintenance Analytics**

A 12,000 car railcar fleet generates about 800 bad orders a month. Somebody has to answer three questions every quarter: what's breaking, how much is coming next month, and which shop should fix it. RailPulse answers all three, from raw operational records to a published dashboard, in one command.

The interesting parts aren't the models. They're the judgment calls: why I shipped the second-place forecast model, why ranking shops by raw dwell time is unfair, and why the optimizer idling a working shop is a question for management rather than an answer from a model.

Python, SQL, scikit-learn, PuLP, SQLite. Runs end to end in 30 seconds and reproduces exactly.

---

## LinkedIn post draft

Most portfolio projects stop at a model with a good score. I wanted to build one that stops where the actual work stops.

So I built a railcar fleet maintenance pipeline: 12,000 cars, three years of repair history, forecast, optimizer, dashboard. And the part I keep coming back to is the model I threw away.

Gradient boosting won my backtest. 3.20% error against 3.31% for a linear model with seasonal terms. I shipped the linear one.

Two reasons. A tenth of a point on six data points is noise. And more importantly, a tree can't extrapolate. It predicts by averaging training observations, so it structurally can't output a number above the range it was trained on.

I didn't want to just assert that, so I tested it. Asked both models about the next 12 months:

Gradient boosting: -0.4% growth
Linear with seasonality: +3.4% growth
Actual history: about 3.3% a year, three years running

The tree projects the growth stopping dead. Not because it has a view about the fleet, but because it hit its ceiling.

The holdout months sat close to the training range, so this was completely invisible in the backtest. Your validation design can be correct and still fail to test the thing that matters.

If a model's job is to reach forward, extrapolation behavior is a requirement. No error column will tell you about it.

---

## Cover letter line

I built a railcar fleet maintenance analytics project recently, and the thing I'd want to talk about isn't the forecast accuracy. It's that ranking repair shops by average dwell time turned out to be unfair to the shops doing the hard work, and finding that took more thought than any of the modeling.

---

## Talking points

Have these ready. Each one is a decision with a reason, which is what interviewers are listening for.

**"Walk me through the project."** Three questions, one pipeline: what's breaking, what's coming, where to send it. Data quality gate first because nothing downstream is trustworthy without it. All definitions in SQL views so the dashboard and any ad hoc query can't drift apart. Six-model forecast backtest. Integer program for assignment. Self-contained dashboard where every number is read from a file the pipeline wrote.

**"What was the hardest decision?"** Shipping the second-place forecast model. Details in `docs/METHOD_NOTES.md` section 1.

**"What's the weakest part?"** The specialty penalty matrix. Nine multipliers that are my assumption rather than a measurement, and they drive routing. I'd validate them against real shop throughput before trusting the assignment plan.

**"What would you do next?"** Weather features, rolling multi-period optimization, and a survival model for individual cars. Predicting which car fails next is a different and more valuable problem than predicting how many will.

**Numbers to have memorized:** 12,000 cars. 30,072 raw records, 28,822 clean. 2,909 quality issues across nine checks. 3.3% forecast error against 5.2% seasonal naive. 3.2% cost reduction, $366K a year. Boxcars at 1.01 bad orders per car per year. Cars past 40 fail 90% more than cars under 10.

---

## What to say if asked whether the data is real

Say it plainly and early: the data is synthetic, generated by a seeded script in the repo. Railcar maintenance records aren't public.

Then say what that costs and what it doesn't. It means the findings aren't discoveries, because I chose the patterns the analysis then finds. That's circular and I say so in the README. It doesn't undercut the method: the quality gate, the backtest design, the extrapolation test, and the optimizer formulation all work the same way on real data, and the reasoning behind each one is the part worth evaluating.

Volunteering this is better than being asked. It reads as calibration rather than a gap.
