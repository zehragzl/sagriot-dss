import sys
import time

import numpy as np
import pandas as pd

from .forecasters import (Persistence, SeasonalNaive, DampedTrend,
                          ChronosForecaster, DrivenDrying, Ensemble, TTMForecaster)
from .features import compute_vpd


WAGENINGEN = {
    "air_temp":     "compartment/air_temperature",
    "air_humidity": "compartment/relative_humidity",
    "par":          "compartment/par",
    "co2":          "compartment/co2_concentration",
    "soil_temp":    "compartment/substrate/substrate_temperature",
    "soil_fc":      "compartment/substrate/relative_permittivity",
}

WAGENINGEN_CHANNELS = ["air_temp", "air_humidity", "par", "co2", "soil_fc", "soil_temp", "ec"]
REAL_CHANNELS = ["air_temp", "air_humidity", "par", "co2", "soil_vwc", "soil_temp", "ec"]

CROSSINGS = {
    "air_temp":     (0.85, "above"),
    "air_humidity": (0.85, "above"),
    "soil_fc":      (0.15, "below"),
    "soil_vwc":     (0.15, "below"),
    "soil_temp":    (0.15, "below"),
    "ec":           (0.85, "above"),
}

# A percentile is how each level was first derived. The value is then frozen,
# because a level recomputed from the data moves whenever the record grows: on
# the testbed log the soil-moisture level fell from 46.15 to 40.73 when two
# further days were added, which silently changed the event set and made the
# two runs incomparable. The values below were derived on the record as it
# stood on 26 August 2026, the version the reported results were produced from.
FROZEN_LEVELS = {
    "real": {
        "air_temp":     24.74,
        "air_humidity": 62.46,
        "soil_vwc":     46.15,
        "soil_temp":    18.20,
        "ec":            0.23,
    },
    "wageningen": {},
}

SOIL_MOISTURE = ("soil_fc", "soil_vwc")


def level_for(path, channel, values):
    """Returns (level, direction, source) for a channel, or (None, ..., None)."""
    if channel not in CROSSINGS:
        return None, "below", None
    quantile, direction = CROSSINGS[channel]
    header = pd.read_csv(path, nrows=0)
    kind = "real" if "timestamp" in header.columns else "wageningen"
    frozen = FROZEN_LEVELS.get(kind, {}).get(channel)
    if frozen is not None:
        return float(frozen), direction, "frozen"
    return float(np.quantile(values, quantile)), direction, f"p{int(quantile * 100)}"


def load_wageningen(path, channel, resample=None):
    raw = pd.read_csv(path, low_memory=False)
    index = pd.to_datetime(raw["time"], utc=True).dt.tz_convert("Europe/Amsterdam")

    def replicates(base):
        columns = [c for c in (base, base + ".1", base + ".2") if c in raw.columns]
        return raw[columns].apply(pd.to_numeric, errors="coerce").mean(axis=1)

    if channel == "ec":
        permittivity = replicates("compartment/substrate/relative_permittivity")
        bulk = replicates("compartment/substrate/bulk_ec")
        values = 80.3 * bulk / (permittivity - 4.1)
        values[permittivity < 5.0] = float("nan")
    else:
        values = replicates(WAGENINGEN[channel])
        if channel == "soil_fc":
            values = (values / values.quantile(0.95) * 100).clip(0, 100)

    series = pd.Series(values.to_numpy(), index=index).sort_index()
    if resample:
        series = series.resample(resample).mean()
    return series.interpolate(limit=3, limit_area="inside").dropna()


def load_series(path, channel, resample=None):
    frame = pd.read_csv(path, parse_dates=["timestamp"])
    frame = frame.sort_values("timestamp").set_index("timestamp")
    series = pd.to_numeric(frame[channel], errors="coerce")
    if resample:
        series = series.resample(resample).mean()
    return series.interpolate(limit=3, limit_area="inside").dropna()


def load_any(path, channel, resample=None):
    header = pd.read_csv(path, nrows=0)
    if "timestamp" in header.columns:
        return load_series(path, channel, resample)
    return load_wageningen(path, channel, resample)


def channels_for(path):
    header = pd.read_csv(path, nrows=0)
    return REAL_CHANNELS if "timestamp" in header.columns else WAGENINGEN_CHANNELS


def load_frame(path, channels, resample=None):
    data = {channel: load_any(path, channel, resample) for channel in channels}
    frame = pd.DataFrame(data)
    if "air_temp" in frame.columns and "air_humidity" in frame.columns:
        frame["vpd"] = [compute_vpd(t, h)
                        for t, h in zip(frame["air_temp"], frame["air_humidity"])]
    return frame.dropna()


def crossing_step(values, threshold, direction):
    for index, value in enumerate(values):
        if direction == "below" and value < threshold:
            return index
        if direction == "above" and value > threshold:
            return index
    return None


def evaluate(frame, target, models, context, horizon, step, season,
             threshold=None, direction="below", drivers=()):
    values = frame[target].to_numpy(dtype=float)
    driver_values = {d: frame[d].to_numpy(dtype=float) for d in drivers}
    records = []

    for model in models:
        try:
            model.warm_up(context, horizon)
        except Exception:
            pass

    start = max(context, season)
    for origin in range(start, len(values) - horizon + 1, step):
        history = values[origin - context:origin]
        truth = values[origin:origin + horizon]

        exog_past = {d: v[origin - context:origin] for d, v in driver_values.items()}
        exog_future = {d: v[origin - season:origin - season + horizon]
                       for d, v in driver_values.items()}

        already = False
        truth_cross = None
        if threshold is not None:
            current = history[-1]
            already = current < threshold if direction == "below" else current > threshold
            truth_cross = crossing_step(truth, threshold, direction)

        for model in models:
            started = time.perf_counter()
            prediction = model.predict(history, horizon, exog_past, exog_future)
            elapsed = time.perf_counter() - started

            record = {
                "model": model.name,
                "origin": origin,
                "mae": float(np.mean(np.abs(prediction - truth))),
                "rmse": float(np.sqrt(np.mean((prediction - truth) ** 2))),
                "seconds": elapsed,
            }
            if threshold is not None and not already:
                predicted_cross = crossing_step(prediction, threshold, direction)
                record["warned"] = predicted_cross is not None
                record["crossed"] = truth_cross is not None
                if truth_cross is not None and predicted_cross is not None:
                    record["cross_error"] = abs(predicted_cross - truth_cross)
            records.append(record)

    return pd.DataFrame(records)


def summarise(results, step_minutes):
    grouped = results.groupby("model")
    table = grouped.agg(
        mae=("mae", "mean"),
        rmse=("rmse", "mean"),
        ms=("seconds", lambda s: s.mean() * 1000),
        windows=("mae", "size"),
    )
    if "persistence" in table.index:
        table["skill"] = 1 - table["mae"] / table.loc["persistence", "mae"]

    if "crossed" in results.columns:
        valid = results.dropna(subset=["crossed"])
        rows = {}
        for name, part in valid.groupby("model"):
            crossed = part["crossed"].astype(bool)
            warned = part["warned"].astype(bool)
            hits = int((crossed & warned).sum())
            misses = int((crossed & ~warned).sum())
            false_alarms = int((~crossed & warned).sum())
            rejects = int((~crossed & ~warned).sum())
            cross_err = float("nan")
            if "cross_error" in part.columns:
                cross_err = part["cross_error"].mean() * step_minutes
            rows[name] = {
                "events": int(crossed.sum()),
                "recall": hits / (hits + misses) if hits + misses else float("nan"),
                "precision": hits / (hits + false_alarms) if hits + false_alarms else float("nan"),
                "false_alarm": false_alarms / (false_alarms + rejects) if false_alarms + rejects else float("nan"),
                "cross_err_min": cross_err,
            }
        table = table.join(pd.DataFrame(rows).T)

    return table.sort_values("mae").round(3)


if __name__ == "__main__":
    path = sys.argv[1]
    channel = sys.argv[2] if len(sys.argv) > 2 else "air_temp"

    RESAMPLE = "5min"
    STEP_MINUTES = 5
    # Third argument overrides the context length. The reported results use 288
    # (24 h). 512 exists for one diagnostic: TTM cannot accept 288 and is
    # normally padded up to 512, so running everything at 512 shows whether
    # that padding, rather than the model, is what loses.
    CONTEXT = int(sys.argv[3]) if len(sys.argv) > 3 else 24 * 60 // STEP_MINUTES
    HORIZON = 3 * 60 // STEP_MINUTES
    STRIDE = 60 // STEP_MINUTES
    SEASON = 24 * 60 // STEP_MINUTES

    frame = load_frame(path, channels_for(path), resample=RESAMPLE)
    values = frame[channel].to_numpy(dtype=float)
    print(f"{channel}: {len(frame)} points, {frame.index[0]} -> {frame.index[-1]}")
    print(f"context: {CONTEXT} steps ({CONTEXT * STEP_MINUTES / 60:.1f} h)"
          + ("  [TTM padded from here to 512]" if CONTEXT < 512 else "  [TTM unpadded]"))

    THRESHOLD, DIRECTION, SOURCE = level_for(path, channel, values)
    if THRESHOLD is not None:
        print(f"evaluation level: {THRESHOLD:.2f} ({DIRECTION}, {SOURCE})")

    models = [
        Persistence(),
        SeasonalNaive(SEASON),
        ChronosForecaster("amazon/chronos-bolt-tiny"),
        # Pretrained like Chronos but about a million parameters instead of
        # nine. See TTMForecaster for the padding it needs and what that costs.
        TTMForecaster(),
    ]
    if channel in SOIL_MOISTURE:
        models += [
            DrivenDrying(("vpd",)),
            DrivenDrying(("vpd", "par")),
            # Recency weighting was measured and did not help: within a 24 h
            # context the drying rate is effectively constant, so there is
            # nothing for the weights to track. Kept here, out of the production
            # benchmark, so the negative result stays reproducible.
            DrivenDrying(("vpd",), decay=0.99),
            Ensemble([DrivenDrying(("vpd",)),
                      ChronosForecaster("amazon/chronos-bolt-tiny")]),
        ]

    results = evaluate(frame, channel, models, CONTEXT, HORIZON, STRIDE, SEASON,
                       threshold=THRESHOLD, direction=DIRECTION, drivers=("vpd", "par"))

    print()
    print(summarise(results, STEP_MINUTES).to_string())