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
| `rules.py` | Seven decision rules. Plant-independent logic — contains no numeric thresholds |
| `sensors.py` | Five I²C sensors plus an RS485 soil probe, each read behind its own error guard |
| `features.py` | Derived channels (VPD, DLI, disease-hours) and stuck-sensor detection |
| `store.py` | Appends raw readings and issued advice to CSV |
| `run_real.py` | Live loop: read every 30 s, forecast every 10 min |
| `advise.py` | Forecast → future rows → rules → earliest crossing → lead-time decision |
| `forecasters.py` | Persistence, seasonal naive, damped trend, driven drying, Chronos, ensemble — each with a predictive band |
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
- **A grey-box model beat a pretrained transformer on the irrigation decision** — measured
  on a Raspberry Pi 5 at 0.07 ms and 0.1 MB against 34.5 ms and 359 MB.
- **Some channels should not be forecast at all.** For electrical conductivity no method
  improved on carrying the last value forward.

Details, figures and honest limitations are in the internship report.

---

## Known limitations

- Single pot, single plant, one location, seven days of continuous recording.
- The surrogate plant is a chrysanthemum; thresholds are the tomato configuration and are
  used as fixed event markers, not as horticultural advice for that species.
- The RS485 probe reports bulk EC while the thresholds are defined for pore-water EC, so
  the fertilisation rule was not evaluated on the testbed.
- Lux-to-PAR conversion is an approximation; DLI inherits that error.
- VPD is computed from air rather than leaf temperature.
- The context window is re-read from the full log on each cycle; a rolling buffer would be
  needed at longer deployment horizons.
- DLI and disease-hour accumulators reset on restart. The coverage check suppresses DLI
  rather than reporting an incomplete value, so this degrades safely.
- TimesFM and Moirai were considered and not implemented. The capability that made Moirai
  interesting — accepting exogenous covariates — was tested directly with the lightweight
  `DrivenDrying` model instead, so neither was pursued.

---

Zehra Betül Güzel · RPTU Kaiserslautern · 2026
