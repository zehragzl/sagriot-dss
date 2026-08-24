import pandas as pd

from .config import FORECASTERS, LOG_PATH
from .forecasters import (Persistence, SeasonalNaive, DampedTrend,
                          ChronosForecaster, DrivenDrying)

STEP_MINUTES = 5
RESAMPLE = f"{STEP_MINUTES}min"
CONTEXT_HOURS = 24
CONTEXT = CONTEXT_HOURS * 60 // STEP_MINUTES
HORIZON = 3 * 60 // STEP_MINUTES
SEASON = 24 * 60 // STEP_MINUTES

MEASURED = ["air_temp", "air_humidity", "co2", "par", "soil_vwc", "soil_temp", "ec"]


def load_recent(path, hours=CONTEXT_HOURS + 1, resample=RESAMPLE):
    frame = pd.read_csv(path, parse_dates=["timestamp"])
    frame = frame.sort_values("timestamp").set_index("timestamp")
    cutoff = frame.index[-1] - pd.Timedelta(hours=hours)
    frame = frame.loc[cutoff:]
    columns = [c for c in MEASURED if c in frame.columns]
    numeric = frame[columns].apply(pd.to_numeric, errors="coerce")
    numeric = numeric.resample(resample).mean()
    return numeric.interpolate(limit=3, limit_area="inside")


def make_forecaster(name):
    if name == "persistence":
        return Persistence()
    if name == "seasonal_naive":
        return SeasonalNaive(SEASON)
    if name == "damped_trend":
        return DampedTrend()
    if name == "driven_drying_vpd":
        return DrivenDrying(("vpd",))
    if name == "driven_drying_vpd_par":
        return DrivenDrying(("vpd", "par"))
    if name.startswith("chronos"):
        size = name.rsplit("_", 1)[-1]
        return ChronosForecaster(f"amazon/chronos-bolt-{size}")
    raise ValueError(f"Unknown forecaster: {name}")


def build_forecasters(mapping=None):
    mapping = FORECASTERS if mapping is None else mapping
    built = {}
    for channel, name in mapping.items():
        if not name:
            built[channel] = Persistence()
            continue
        try:
            forecaster = make_forecaster(name)
            forecaster.predict([0.0] * CONTEXT, HORIZON)
            built[channel] = forecaster
        except Exception as error:
            print(f"[advise] {channel}: {name} kullanilamiyor ({error}) - persistence'a dusuldu")
            built[channel] = Persistence()
    return built


if __name__ == "__main__":
    frame = load_recent(LOG_PATH)
    print(f"{len(frame)} nokta (gereken: {CONTEXT})")
    print(frame.tail(3).round(2).to_string())
    print()
    for channel, forecaster in build_forecasters().items():
        print(f"  {channel:14s} {forecaster.name}")