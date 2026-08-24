import numpy as np
import pandas as pd
import sys

from .config import FORECASTERS, LOG_PATH, VWC_FIELD_CAPACITY
from .features import compute_vpd
from .forecasters import (Persistence, SeasonalNaive, DampedTrend,
                          ChronosForecaster, DrivenDrying)
from .rules import rules
from .config import PLANT

STEP_MINUTES = 5
RESAMPLE = f"{STEP_MINUTES}min"
CONTEXT_HOURS = 24
CONTEXT = CONTEXT_HOURS * 60 // STEP_MINUTES
HORIZON = 3 * 60 // STEP_MINUTES
SEASON = 24 * 60 // STEP_MINUTES

MEASURED = ["air_temp", "air_humidity", "co2", "par", "soil_vwc", "soil_temp", "ec"]
STEP_SECONDS = STEP_MINUTES * 60
DRIVEN_CHANNELS = ("air_temp", "air_humidity", "par", "co2", "soil_temp", "ec")

LEAD_MINUTES = {
    "Irrigation":             60,
    "Water stress":           60,
    "Fertilization":         120,
    "Ventilation":            30,
    "Lighting":              120,
    "Disease risk":          180,
    "Root-zone temperature":  60,
}
DEFAULT_LEAD = 60

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
    cache = {}
    built = {}
    for channel, name in mapping.items():
        if not name:
            built[channel] = Persistence()
            continue
        if name in cache:
            built[channel] = cache[name]
            continue
        try:
            forecaster = make_forecaster(name)
            forecaster.predict([0.0] * CONTEXT, HORIZON)
            cache[name] = forecaster
            built[channel] = forecaster
        except Exception as error:
            print(f"[advise] {channel}: {name} kullanilamiyor ({error}) - persistence'a dusuldu")
            built[channel] = Persistence()
    return built

def forecast_channels(frame, forecasters, horizon=HORIZON, context=CONTEXT):
    history = {c: frame[c].to_numpy(dtype=float)[-context:] for c in frame.columns}
    predictions = {}

    for channel in DRIVEN_CHANNELS:
        if channel in forecasters and channel in history:
            predictions[channel] = forecasters[channel].predict(history[channel], horizon)

    vpd_past = np.array([compute_vpd(t, h)
                         for t, h in zip(history["air_temp"], history["air_humidity"])])
    vpd_future = np.array([compute_vpd(t, h)
                           for t, h in zip(predictions["air_temp"], predictions["air_humidity"])])
    predictions["vpd"] = vpd_future

    if "soil_vwc" in forecasters and "soil_vwc" in history:
        exog_past = {"vpd": vpd_past, "par": history["par"]}
        exog_future = {"vpd": vpd_future, "par": predictions["par"]}
        predictions["soil_vwc"] = forecasters["soil_vwc"].predict(
            history["soil_vwc"], horizon, exog_past, exog_future
        )
    return predictions

def build_future_rows(last_timestamp, predictions, dli_now=0.0, disease_hours_now=0.0,
                      rh_trigger=85, vpd_trigger=0.3, horizon=HORIZON):
    rows = []
    dli = dli_now
    disease_hours = disease_hours_now
    step_hours = STEP_MINUTES / 60

    for index in range(horizon):
        moment = last_timestamp + pd.Timedelta(minutes=STEP_MINUTES * (index + 1))
        row = {channel: float(values[index]) for channel, values in predictions.items()}
        row["local_hour"] = moment.hour

        if "soil_vwc" in row and VWC_FIELD_CAPACITY:
            row["soil_fc"] = round(row["soil_vwc"] / VWC_FIELD_CAPACITY * 100, 1)

        if moment.date() == last_timestamp.date():
            dli += row.get("par", 0.0) * STEP_SECONDS / 1e6
        else:
            dli = 0.0
        row["dli"] = round(dli, 3)

        risky = row.get("air_humidity", 0) > rh_trigger and row.get("vpd", 99) < vpd_trigger
        disease_hours = max(0.0, disease_hours + (step_hours if risky else -step_hours))
        row["disease_hours"] = round(disease_hours, 3)

        row["minutes_ahead"] = STEP_MINUTES * (index + 1)
        row["timestamp"] = moment
        rows.append(row)
    return rows
def current_row(frame, dli_now=0.0, disease_hours_now=0.0):
    last = frame.iloc[-1]
    row = {c: float(last[c]) for c in frame.columns if pd.notna(last[c])}
    row["local_hour"] = frame.index[-1].hour
    if "air_temp" in row and "air_humidity" in row:
        row["vpd"] = compute_vpd(row["air_temp"], row["air_humidity"])
    if "soil_vwc" in row and VWC_FIELD_CAPACITY:
        row["soil_fc"] = round(row["soil_vwc"] / VWC_FIELD_CAPACITY * 100, 1)
    row["dli"] = dli_now
    row["disease_hours"] = disease_hours_now
    return row


def advise(frame, rows, plant=PLANT, dli_now=0.0, disease_hours_now=0.0):
    now = current_row(frame, dli_now, disease_hours_now)
    active = {rec["rule"] for rec in rules(now, plant)}

    upcoming = {}
    for row in rows:
        for rec in rules(row, plant):
            if rec["rule"] in active or rec["rule"] in upcoming:
                continue
            lead = LEAD_MINUTES.get(rec["rule"], DEFAULT_LEAD)
            minutes = row["minutes_ahead"]
            upcoming[rec["rule"]] = {
                "rule": rec["rule"],
                "when_minutes": minutes,
                "status": rec["status"],
                "action": rec["action"],
                "lead_minutes": lead,
                "advise_now": minutes - lead <= 0,
            }

    return {
        "now": [{"rule": r["rule"], "status": r["status"], "action": r["action"]}
                for r in rules(now, plant)],
        "upcoming": sorted(upcoming.values(), key=lambda r: r["when_minutes"]),
    }

def row_at(frame, position, dli=0.0, disease_hours=0.0):
    timestamp = frame.index[position]
    data = frame.iloc[position]
    row = {c: float(data[c]) for c in frame.columns if pd.notna(data[c])}
    row["local_hour"] = timestamp.hour
    if "air_temp" in row and "air_humidity" in row:
        row["vpd"] = compute_vpd(row["air_temp"], row["air_humidity"])
    if "soil_vwc" in row and VWC_FIELD_CAPACITY:
        row["soil_fc"] = round(row["soil_vwc"] / VWC_FIELD_CAPACITY * 100, 1)
    row["dli"] = dli
    row["disease_hours"] = disease_hours
    return timestamp, row


def actual_onsets(frame, plant=PLANT, start_position=0):
    onsets, active = [], set()
    for position in range(len(frame)):
        timestamp, row = row_at(frame, position)
        current = {rec["rule"] for rec in rules(row, plant)}
        if position >= start_position:
            for rule in current - active:
                onsets.append({"rule": rule, "at": timestamp})
        active = current
    return pd.DataFrame(onsets)


def replay(path, plant=PLANT, stride_minutes=30):
    frame = load_recent(path, hours=100000)
    forecasters = build_forecasters()
    stride = max(1, stride_minutes // STEP_MINUTES)

    issued = []
    for end in range(CONTEXT, len(frame) - HORIZON, stride):
        window = frame.iloc[end - CONTEXT:end]
        predictions = forecast_channels(window, forecasters)
        rows = build_future_rows(window.index[-1], predictions)
        for item in advise(window, rows, plant)["upcoming"]:
            issued.append({
                "rule": item["rule"],
                "issued_at": window.index[-1],
                "predicted_at": window.index[-1] + pd.Timedelta(minutes=item["when_minutes"]),
            })
    return pd.DataFrame(issued), actual_onsets(frame, plant, CONTEXT)

def score(issued, onsets, max_lead_minutes=180):
    results = []
    for _, onset in onsets.iterrows():
        window = issued[(issued["rule"] == onset["rule"]) &
                        (issued["issued_at"] <= onset["at"]) &
                        (issued["issued_at"] >= onset["at"] - pd.Timedelta(minutes=max_lead_minutes))]
        if len(window):
            first = window["issued_at"].min()
            lead = (onset["at"] - first).total_seconds() / 60
            results.append({"rule": onset["rule"], "at": onset["at"],
                            "warned": True, "lead_minutes": round(lead, 1)})
        else:
            results.append({"rule": onset["rule"], "at": onset["at"],
                            "warned": False, "lead_minutes": None})
    return pd.DataFrame(results)

if __name__ == "__main__":
    frame = load_recent(LOG_PATH)
    print(f"{len(frame)} nokta (gereken: {CONTEXT})")

    forecasters = build_forecasters()
    predictions = forecast_channels(frame, forecasters)
    rows = build_future_rows(frame.index[-1], predictions)

    columns = ["minutes_ahead", "air_temp", "air_humidity", "vpd", "par",
               "soil_vwc", "soil_fc", "dli", "disease_hours"]
    table = pd.DataFrame(rows)
    table = table[[c for c in columns if c in table.columns]]
    print()
    print(table.iloc[::6].round(2).to_string(index=False))
    result = advise(frame, rows)

    print("\n--- su an ---")
    for item in result["now"] or [{"rule": "-", "status": "-", "action": "no recommendations"}]:
        print(f"   [{item['status']}] {item['rule']}: {item['action']}")

    print("\n--- gelecek 3 saat ---")
    if not result["upcoming"]:
        print("   yeni bir esik gecisi ongorulmuyor")
    for item in result["upcoming"]:
        flag = "SIMDI UYAR" if item["advise_now"] else f"{item['when_minutes'] - item['lead_minutes']} dk sonra uyar"
        print(f"   {item['rule']}: {item['when_minutes']} dk sonra ({item['status']}) - {flag}")

    if len(sys.argv) > 1 and sys.argv[1] == "replay":
        issued, onsets = replay(LOG_PATH)
        print(f"\nuretilen uyari: {len(issued)}, gercek tetiklenme: {len(onsets)}")
        print()
        print(score(issued, onsets).to_string(index=False))
        raise SystemExit