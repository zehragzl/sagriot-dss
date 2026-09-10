"""Inference cost on the target hardware.

Three modes:

    python -m sagriot.measure <forecaster> [channel]   one method, in isolation
    python -m sagriot.measure cycle                    the whole forecast cycle
    python -m sagriot.measure power                    watts, idle against busy

The first is the per-method comparison. The second is what the device actually
does every ten minutes with the configuration in config.py, which is the number
that matters for deployment. The third answers whether that costs anything.

Run each method in its own process so the memory figure is attributable.
"""

import re
import resource
import subprocess
import sys
import threading
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


# ------------------------------------------------------------------- power
#
# The Raspberry Pi 5 carries a PMIC that reports the voltage and current of
# each of its supply rails, so board power can be read without a meter in the
# supply line. What this gives is the sum over the rails, not what the wall
# socket sees: it excludes the power-supply's own losses and anything a USB
# peripheral draws beyond the 5 V rail. That makes the absolute figure an
# underestimate of true consumption.
#
# The number this is for is not the absolute one. It is the difference between
# the board doing nothing and the board forecasting, because that difference is
# what the decision layer costs, and a difference is insensitive to the offset
# the method leaves out.

RAIL = re.compile(r"\s*(\S+)_([AV])\s+\w+\(\d+\)=([0-9.]+)[AV]")


def board_watts():
    """Sum V·I over every PMIC rail that reports both. None if unavailable."""
    try:
        output = subprocess.run(["vcgencmd", "pmic_read_adc"],
                                capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    amps, volts = {}, {}
    for line in output.splitlines():
        found = RAIL.match(line)
        if found:
            rail, kind, value = found.group(1), found.group(2), float(found.group(3))
            (amps if kind == "A" else volts)[rail] = value
    paired = [volts[rail] * amps[rail] for rail in amps if rail in volts]
    return sum(paired) if paired else None


class Sampler(threading.Thread):
    """Read board power in the background while something else runs."""

    def __init__(self, interval=0.2):
        super().__init__(daemon=True)
        self.interval = interval
        self.samples = []
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            watts = board_watts()
            if watts is not None:
                self.samples.append(watts)
            self._stop.wait(self.interval)

    def stop(self):
        self._stop.set()
        self.join(timeout=3)
        return np.array(self.samples)


def measure_power(idle_seconds=15, busy_seconds=25):
    if board_watts() is None:
        print("vcgencmd pmic_read_adc is not available - this needs a Pi 5.")
        return

    frame = load_recent(LOG_PATH)
    forecasters = build_forecasters()
    forecast_scenarios(frame, forecasters)          # warm up before measuring

    sampler = Sampler()
    sampler.start()
    time.sleep(idle_seconds)
    idle = np.array(sampler.samples)

    cycles, started = 0, time.perf_counter()
    while time.perf_counter() - started < busy_seconds:
        forecast_scenarios(frame, forecasters)
        cycles += 1
    elapsed = time.perf_counter() - started
    everything = sampler.stop()
    busy = everything[len(idle):]

    if not len(busy) or not len(idle):
        print("not enough samples - try longer intervals")
        return

    per_cycle = elapsed / cycles
    extra = busy.mean() - idle.mean()

    print("\nBoard power, summed over the PMIC rails")
    print(f"{'  idle':34s} {idle.mean():8.2f} W   n={len(idle)}")
    print(f"{'  forecasting continuously':34s} {busy.mean():8.2f} W   n={len(busy)}")
    print(f"{'  the forecast itself':34s} {extra:8.2f} W")
    print(f"\n{'  one cycle':34s} {per_cycle * 1000:8.1f} ms  ({cycles} in {elapsed:.0f} s)")
    print(f"{'  energy per decision':34s} {extra * per_cycle:8.3f} J")

    # What it costs in service, where the loop forecasts once every ten minutes.
    duty = per_cycle / 600
    print(f"{'  averaged over a 10 min period':34s} {extra * duty * 1000:8.2f} mW")
    print(f"{'  per day':34s} {extra * duty * 24 * 3600 / 3600:8.4f} Wh")
    print("\nRails only: excludes supply losses and USB draw, so the absolute\n"
          "figures are low. The difference between the two is the measurement.")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "cycle":
        measure_cycle()
    elif mode == "power":
        measure_power()
    else:
        measure_one(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "soil_vwc")
