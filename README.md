# SAgrIoT — Greenhouse Decision Support

A rule-based decision-support system for greenhouse and small-grower irrigation and
climate management, with a forecasting layer that moves each decision earlier in time.

The rules decide; the forecast only shifts the moment at which the rules are evaluated.
Nothing is actuated automatically — the system is advisory, and a person acts.

Developed during an internship at RPTU Kaiserslautern as part of the SAgrIoT project
(DAAD SDG-Partnerships; RPTU · NUST · GTÜ).

---

## Architecture

```
sensors ──► store (raw log) ──► features ──► rules ──► recommendations
                                    │
                                    └──► advise ──► forecast rows ──► rules ──► early warning
```

| Module | Responsibility |
|---|---|
| `plants.py` | Threshold tables for tomato, cucumber, strawberry; parameter metadata; plausibility ranges |
| `rules.py` | Seven decision rules. Plant-independent logic — no crop or site thresholds; both live in `plants.py` and `config.py` |
| `sensors.py` | Five I²C sensors plus an RS485 soil probe, each read behind its own error guard |
| `features.py` | Derived channels (VPD, DLI, disease-hours) and stuck-sensor detection |
| `store.py` | Appends raw readings and issued advice to CSV |
| `run_real.py` | Live loop: read every 30 s, forecast every 10 min |
| `advise.py` | Forecast → future rows → rules → earliest crossing → lead-time decision |
| `forecasters.py` | Persistence, seasonal naive, driven drying, TTM, Chronos, ensemble — each with a predictive band. Damped trend is kept but not selected |
| `evaluate.py` | Rolling-origin evaluation with signal-level and decision-level metrics |
| `benchmark.py` | Runs the evaluation across datasets and channels |
| `measure.py` | Inference latency and memory on the target hardware |
| `plots.py` | Report figures |
| `selftest.py` | Regression checks — run after any edit |

### Two layers

**Layer 1 — rule logic.** Which signals a rule looks at, how it combines or accumulates
them, and why a threshold is a valid trigger. Crop-independent. Lives in `rules.py`.

**Layer 2 — the numbers.** Threshold values are crop-specific and live in `plants.py`.
Adding a crop means adding a table, not editing a rule.

The scientific justification for each rule is documented separately, one chapter per rule,
with the sources and an explicit statement of what those sources do *not* support.

---

## Install

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

On the sensor node, additionally:

```bash
pip install -r requirements-pi.txt
pip install torch --index-url https://download.pytorch.org/whl/cpu
```

Chronos is optional. If `torch` is missing, the affected channels fall back to
persistence and the system reports the substitution at startup.

`requirements-pi-frozen.txt` is not for installing from. It records the exact versions
present on the node when the reported latency and memory figures were measured, because
those figures belong to a version of torch and transformers as much as to a model.

---

## Run

**Sensor node** — reads, logs, evaluates rules, and issues early warnings:

```bash
python -m sagriot.run_real
```

**Offline evaluation** — one channel, all forecasters:

```bash
python -m sagriot.evaluate data/real_log.csv soil_vwc
```

**Full benchmark** — every channel, one or more datasets:

```bash
python -m sagriot.benchmark data/real_log.csv
```

The loader detects the format from the header: a `timestamp` column means a log produced
by this system, otherwise it is read as an Autonomous Greenhouse Challenge export.

**End-to-end replay** — reconstructs what the early-warning layer would have issued over a
recorded log, and scores it against the rule activations that actually occurred:

```bash
python -m sagriot.advise replay
```

**Hardware cost**, one forecaster per invocation so memory is measured cleanly:

```bash
python -m sagriot.measure chronos_tiny
```

**Figures** and **self-test**:

```bash
python -m sagriot.plots
python -m sagriot.selftest
```

---

## Configuration

Everything site-specific is in `config.py`.

| Setting | Meaning |
|---|---|
| `PLANT` | Which threshold table the rules use |
| `VWC_FIELD_CAPACITY` | Volumetric water content at field capacity, measured once per pot or slab. Until it is set, `soil_fc` is not reported and the moisture rules stay silent |
| `LUX_TO_PAR` | Lux-to-PAR conversion. An approximation — see limitations |
| `PAR_DAY_THRESHOLD` | Above this PAR a reading is judged against the day band, below it against the night band. Site-dependent: on the office testbed PAR passed 10 once in 25,676 readings, so every daytime reading was judged against night limits |
| `DISEASE_HOURS_TRIGGER` | Accumulated favourable hours before the disease rule fires; twice this is critical |
| `DAY_END_HOUR` | Hour after which a shortfall in the day's light budget can be reported |
| `FORECASTERS` | Which method forecasts which channel |
| `TZ_NAME`, `SOIL_PORT`, `SOIL_SLAVE_ID` | Hardware and locale |

`FORECASTERS` is per channel because no single method wins everywhere; the assignment
below was measured, not assumed.

---

## Data

| File | Contents |
|---|---|
| `data/real_log.csv` | Raw sensor readings. Only measurements — derived channels are recomputed on load |
| `data/advice_log.csv` | Every recommendation and early warning the live system issued |
| `data/events.csv` | Manual annotations: irrigation, restarts, plant observations |
| `results/benchmark_*.csv` | Evaluation output |
| `figures/` | Report figures |

Logs are not tracked in git.

---

## What the measurements showed

- **Forecast accuracy and decision utility diverge.** Persistence had the lowest point
  error on several channels and never once predicted a threshold crossing.
- **The best method depends on the environment.** Seasonal naive was the strongest
  forecaster for light in a climate-controlled greenhouse and among the worst in an
  uncontrolled office — the daily cycle there is imposed by the controller, not by physics.
- **A grey-box model matched a pretrained transformer on the irrigation decision** —
  eleven crossings of twelve for both — and found the crossing time nearly three times
  more precisely, 16.8 min against 46.4. Measured on a Raspberry Pi 5 at 0.09 ms and no
  measurable memory against 35.3 ms and 728 MB. The advantage belongs to the regime and
  not to the model: in both reference greenhouses, where a controller refills the
  substrate on a schedule, the same two coefficients fall behind Chronos tiny.
- **What a model costs is its runtime, not its weights.** A one-million-parameter model
  holds 718 MB and a forty-eight-million one holds 884 MB, because both load the same
  deep-learning stack. A model of two coefficients avoids it entirely.
- **Being pretrained did not help.** TTM, pretrained on roughly 700 M samples, was never
  the most accurate and never the best detector in any of the twenty-one cases.
- **The decision costs nothing; the computer that makes it costs everything.** Read from
  the Pi 5 power-management chip: 1.90 W idle, 4.52 W forecasting, 0.27 J per decision,
  0.011 Wh a day against the 45.6 Wh of simply keeping the board powered. The case for a
  microcontroller is not that inference is expensive — it is that a microcontroller sleeps.
- **Some channels should not be forecast at all.** For electrical conductivity no method
  improved on carrying the last value forward.
- **The dominant cost was the log, not the model.** Reading the record took 581 ms of a
  699 ms cycle and grew with it; reading only the tail returns byte-identical output in
  47 ms on the Pi at 60,190 rows, and the whole cycle falls to 158 ms.

Details, figures and honest limitations are in the internship report.

---

## Known limitations

- Single pot, single plant, one location, twenty-one days of continuous recording
  (19 August – 9 September, 60,190 readings). The decision metrics rest on four
  physically distinct crossings there; the statistical weight is in the two reference
  greenhouses, which carry a hundred or more per channel.
- The surrogate plant is a chrysanthemum; thresholds are the tomato configuration and are
  used as fixed event markers, not as horticultural advice for that species.
- The RS485 probe reports bulk EC while the thresholds are defined for pore-water EC, so
  the fertilisation rule was not evaluated on the testbed.
- Lux-to-PAR conversion is an approximation; DLI inherits that error.
- VPD is computed from air rather than leaf temperature.
- The per-channel assignment in `config.py` was originally derived by point accuracy — the
  criterion this work argues against. On `air_temp` the selected method has never warned
  about a single crossing, which makes the ventilation early warning decorative on that
  channel. No better method exists there, so the entry is left in place with a comment.
- DLI and disease-hour accumulators reset on restart. The coverage check suppresses DLI
  rather than reporting an incomplete value, so this degrades safely.
- TimesFM and Moirai were considered and not implemented. The capability that made Moirai
  interesting — accepting exogenous covariates — was tested directly with the lightweight
  `DrivenDrying` model instead, so neither was pursued.

---

Zehra Betül Güzel · RPTU Kaiserslautern · 2026
