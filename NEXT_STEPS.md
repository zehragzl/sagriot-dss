# Next steps

Written 8 September 2026, at the end of the internship, for whoever continues —
including me.

The order is by value, not by effort. The first two are the graduation-project
scale ideas; the last two are small enough to do in an afternoon and both close
gaps this project found in itself.

---

## 1 · The system should choose its own forecasting method, on site

**The finding this comes from.** Method selection did not transfer between
environments. In every channel the best method differed between the two
commercial greenhouses and the office testbed, because much of the regularity in
a greenhouse is imposed by its controller rather than by physics. Seasonal naive
caught between 59 and 81 % of soil crossings in the greenhouses and 0 % in the
office; the driven-drying model did the opposite, 89 % in the office and 16–26 %
in the greenhouses.

The conclusion drawn from that was: *a method has to be measured at the site
where it will run.* At present the report says that and the code does not act on
it. `config.FORECASTERS` is a fixed table, written by hand, from one set of
measurements taken here.

**What to build.** Score every method continuously against what actually
happened, per channel, and use the one that is winning.

The mechanism is cheap because the work is already being done. At each forecast
cycle the system predicts three hours ahead; three hours later the truth is in
the log. So:

- keep a rolling window of the last N scored forecasts per (channel, method)
- score them at the decision level, not on error — did it warn before the
  crossing, was the warning right, how wrong was the timing
- select the method with the best score for that channel
- fall back to the configured default when there is not yet enough history

The cost is running more than one forecaster per channel. That is affordable
exactly where it matters: driven drying is 0.09 ms, persistence and seasonal
naive are effectively free. Running the three cheap methods in parallel forever
costs less than one Chronos inference.

**Why it matters for deployment.** SAgrIoT targets many small growers. Nobody is
going to hand-tune a forecaster table per greenhouse. A system that arrives, runs
several candidates, and settles on the one that works there is the difference
between a demonstration and something that can be installed.

**It would also have caught the mistake in this repository.** The per-channel
assignment was originally made by point accuracy — the exact criterion this work
argues against. On `air_temp` the selected method has a skill of 0.22 and has
never warned about a single crossing. A decision-level score would have driven it
out automatically instead of leaving it to be found by hand.

**Open questions.** How long a window before switching — too short and it
chatters, too long and it never adapts. Whether to switch or to blend. Whether
the selection itself needs a hold-down period. And how to score a channel that
produces very few crossings, which is most of them.

---

## 2 · Propagate driver uncertainty into the soil forecast

The soil model is driven by vapour pressure deficit, which is itself forecast.
In `forecast_scenarios` every quantile of the soil trajectory is currently driven
by the **median** atmosphere, so the reported band reflects only the residuals of
the rate fit and not the uncertainty in its drivers. This is documented as a
lower bound, and it means the scenario probabilities are understated.

The fix is to drive each quantile with its own atmosphere — the dry scenario with
the dry atmosphere — so the band widens honestly. Medium-sized work, and it makes
the probability something closer to a probability.

---

## 3 · Detect irrigation and invalidate standing advice

The model clips rates at zero because soil cannot gain water without input, so a
watering event is only an outlier to it. The system has no concept of *the user
acted on the advice*.

This was observed directly. On 2 September the forecast correctly predicted an
irrigation crossing ten minutes ahead; the pot was then watered, the reading rose
from 45 to 101 %FC, and the standing warning continued to display **ADVISE NOW**
on every reading for ten minutes until the next forecast cycle recomputed it.
With an automatic valve that is a second irrigation.

What to build: treat a rise above a few points in one step as an irrigation
event, drop any standing advice whose rule no longer fires on the present
reading, and record the event in `data/events.csv` automatically instead of by
hand. Small — an afternoon — and it is the difference between an advisory system
and one that could be trusted to actuate.

---

## 4 · Automate the quiet-state sensor check

The most useful diagnostic in this project was not built into it. At night an
unlit office has a known light reading, so any step in that baseline must be
physical rather than meteorological. Comparing the night baseline across days
found two separate obstructions of the light sensor, one lasting six days, and a
slow upward drift in the CO₂ baseline over eight nights. None of them produced a
stale reading, a missing value, or any other symptom the liveness checks were
designed to catch.

Both were found by a person looking. The second one was found from the log five
days after it began.

What to build: compute the 01:00–04:00 median for the channels that have a known
resting state, compare against a rolling reference of previous nights, and report
a step or a drift. A few hours of work, and it turns a habit into a feature.

---

## Not on this list, and why

**Threshold debounce.** A signal oscillating around a limit toggles a rule
repeatedly; this happened in three separate dry-downs and is the difference
between 29 raw crossings and 4 real ones. It is worth fixing, but it is a
presentation problem rather than a decision problem — the advice is the same
either way.

**The moisture term in the drying model.** Tested, and it reproduced this
project's own trade-off in miniature: accuracy and precision improved, one
crossing in twelve was missed, and the timing error grew from 17 to 22 minutes.
At four physical events the difference is not resolvable. The variant stays in
the code, unselected, until there is enough data to decide it — which is a
question about the cost of a wrong irrigation, not about goodness of fit.

**Two-directional evaluation levels.** `CROSSINGS` scores one direction while
Rules 3, 5 and 7 are two-sided. Changing it would alter the event set and make
past runs incomparable, so it is documented rather than changed.

---

## The hardware direction

Separately from the software: the irrigation decision needs a 24-hour buffer of
soil moisture and VPD — about 2.5 KB — one 2×2 least squares and one exponential,
and no framework. An ESP32 has 520 KB and costs a few euros; smaller RISC-V parts
would also serve, and the project proposal names RISC-V for the irrigation
controllers.

The goal is a low-cost node that runs the model continuously and reads the three
sensors it needs — air temperature, air humidity, soil moisture — and waters
according to the state of the plant rather than a clock.

That is a calculation, not a demonstration. The port is the work.
