import resource
import sys
import time

import numpy as np

from .advise import CONTEXT, HORIZON, load_recent, make_forecaster
from .config import LOG_PATH
from .features import compute_vpd

REPEATS = 20


def peak_memory_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def main(name, channel="soil_vwc"):
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

    times = []
    for _ in range(REPEATS):
        started = time.perf_counter()
        forecaster.predict(history, HORIZON, exog_past, exog_future)
        times.append((time.perf_counter() - started) * 1000)

    times = np.array(times)
    print(f"{forecaster.name:28s} "
          f"mean={times.mean():8.2f} ms  "
          f"p95={np.percentile(times, 95):8.2f} ms  "
          f"rss_delta={after_load - before:7.1f} MB  "
          f"rss_total={after_load:7.1f} MB")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "soil_vwc")