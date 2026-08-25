import os
import sys

import pandas as pd

from .evaluate import (load_frame, evaluate, summarise,
                       channels_for, CROSSINGS, SOIL_MOISTURE)
from .forecasters import (Persistence, SeasonalNaive, DampedTrend,
                          ChronosForecaster, DrivenDrying)

RESAMPLE = "5min"
STEP_MINUTES = 5
CONTEXT = 24 * 60 // STEP_MINUTES
HORIZON = 3 * 60 // STEP_MINUTES
STRIDE = 60 // STEP_MINUTES
SEASON = 24 * 60 // STEP_MINUTES
DRIVERS = ("vpd", "par")


def run(paths):
    base_models = [
        Persistence(),
        SeasonalNaive(SEASON),
        DampedTrend(),
        ChronosForecaster("amazon/chronos-bolt-tiny"),
        ChronosForecaster("amazon/chronos-bolt-small"),
    ]
    driven_models = [DrivenDrying(("vpd",)), DrivenDrying(("vpd", "par"))]

    collected = []
    for path in paths:
        dataset = os.path.basename(path).replace(".csv", "")
        channels = channels_for(path)
        frame = load_frame(path, channels, resample=RESAMPLE)
        print(f"\n########## {dataset} — {len(frame)} nokta ##########")

        for channel in channels:
            values = frame[channel].to_numpy(dtype=float)
            threshold, direction = None, "below"
            if channel in CROSSINGS:
                quantile, direction = CROSSINGS[channel]
                threshold = float(pd.Series(values).quantile(quantile))

            models = list(base_models)
            if channel in SOIL_MOISTURE:
                models += driven_models

            results = evaluate(frame, channel, models, CONTEXT, HORIZON,
                               STRIDE, SEASON, threshold=threshold,
                               direction=direction, drivers=DRIVERS)
            table = summarise(results, STEP_MINUTES)

            print(f"\n--- {dataset} / {channel} ---")
            if threshold is not None:
                print(f"esik: {threshold:.1f} ({direction})")
            print(table.to_string())

            tidy = table.reset_index()
            tidy.insert(0, "channel", channel)
            tidy.insert(0, "dataset", dataset)
            collected.append(tidy)

    combined = pd.concat(collected, ignore_index=True)
    os.makedirs("results", exist_ok=True)
    names = "_".join(os.path.basename(p).replace(".csv", "") for p in paths)
    out_path = f"results/benchmark_{names}.csv"
    combined.to_csv(out_path, index=False)
    print(f"\nkaydedildi: {out_path}")
    return combined


if __name__ == "__main__":
    run(sys.argv[1:])