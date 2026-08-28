"""Inference cost on the target hardware.

Two modes:

    python -m sagriot.measure <forecaster> [channel]   one method, in isolation
    python -m sagriot.measure cycle                    the whole forecast cycle

The first is the per-method comparison. The second is what the device actually
does every ten minutes with the configuration in config.py, which is the number
that matters for deployment.

Run each method in its own process so the memory figure is attributable.
"""

import resource
import sys
import time

import numpy as np

from .advise import (CONTEXT, HORIZON, load_recent, make_forecaster,
                     build_forecasters, forecast_scenarios, advise_range)
from .config import LOG_PATH, PLANT
from .features import compute_vpd

REPEATS = 20


def peak_memory_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def timed(function, repeats=REPEATS):
    samples = []
    for _ in range(repeats):
        started = time.perf_counter()
        function()
        samples.append((time.perf_counter() - started) * 1000)
    return np.array(samples)


def report(label, samples, memory=None):
    line = (f"{label:34s} mean={samples.mean():8.2f} ms  "
            f"p95={np.percentile(samples, 95):8.2f} ms")
    if memory is not None:
        line += f"  rss={memory:7.1f} MB"
    print(line)


def measure_one(name, channel="soil_vwc"):
    frame = load_recent(LOG_PATH)
    history = frame[channel].to_numpy(dtype=float)[-CONTEXT:]

    vpd = np.array([compute_vpd(t, h) for t, h in
                    zip(frame["air_temp"][-CONTEXT:], frame["air_humidity"][-CONTEXT:])])
    exog_past = {"vpd": vpd, "par": frame["par"].to_numpy(dtype=float)[-CONTEXT:]}
    exog_future = {"vpd": vpd[:HORIZON], "par": exog_past["par"][:HORIZON]}

    before = peak_memory_mb()
    forecaster = make_forecaster(name)
    forecaster.predict(history, HORIZON, exog_past, exog_future)
    after_load = peak_memory_mb()

    point = timed(lambda: forecaster.predict(history, HORIZON, exog_past, exog_future))
    bands = timed(lambda: forecaster.predict_quantiles(history, HORIZON,
                                                       exog_past, exog_future))

    print(f"\n{forecaster.name}")
    report("  predict (point)", point)
    report("  predict_quantiles (band)", bands)
    print(f"{'  memory added by this method':34s} {after_load - before:7.1f} MB"
          f"   process total {after_load:7.1f} MB")


def measure_cycle():
    """What run_real does every FORECAST_INTERVAL_SECONDS."""
    before = peak_memory_mb()
    frame = load_recent(LOG_PATH)
    forecasters = build_forecasters()
    loaded = peak_memory_mb()

    scenarios = forecast_scenarios(frame, forecasters)

    forecast = timed(lambda: forecast_scenarios(frame, forecasters))
    rules = timed(lambda: advise_range(frame, scenarios, PLANT))
    reading = timed(lambda: load_recent(LOG_PATH), repeats=5)

    print("\nOne forecast cycle, with the configuration in config.py")
    report("  read and resample the log", reading)
    report("  forecast every channel (bands)", forecast)
    report("  rule engine over all scenarios", rules)
    total = reading.mean() + forecast.mean() + rules.mean()
    print(f"{'  total per cycle':34s} {total:8.2f} ms")
    print(f"{'  resident memory':34s} {loaded:8.1f} MB  "
          f"(models added {loaded - before:.1f} MB)")

    # The loop runs this once every ten minutes.
    duty = total / (600 * 1000) * 100
    print(f"{'  duty cycle':34s} {duty:8.3f} %  of wall-clock time")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "cycle":
        measure_cycle()
    else:
        measure_one(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "soil_vwc")
