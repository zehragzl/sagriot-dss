import time

from .config import MODE, PLANT, LOG_PATH, READ_INTERVAL_SECONDS
from .features import compute_vpd, DailyLight, DiseaseHours
from .validation import validate, FreshnessTracker
from .rules import rules, get_thresholds
from . import store

MIN_DLI_COVERAGE = 0.9


def disease_thresholds(plant):
    thresholds = get_thresholds(plant)
    humidity = thresholds["air_humidity"]
    vpd = thresholds["vpd"]
    rh_trigger = humidity["warn_high"]
    vpd_trigger = vpd["crit_low"] if vpd["crit_low"] is not None else vpd["warn_low"]
    return rh_trigger, vpd_trigger


def build_row(timestamp, clean, light, disease):
    row = dict(clean)
    row["local_hour"] = timestamp.hour
    if "air_temp" in row and "air_humidity" in row:
        row["vpd"] = compute_vpd(row["air_temp"], row["air_humidity"])
    if "par" in row:
        dli = light.update(timestamp, row["par"])
        if light.coverage(timestamp) >= MIN_DLI_COVERAGE:
            row["dli"] = dli
    if "air_humidity" in row and "vpd" in row:
        row["disease_hours"] = disease.update(
            timestamp, row["air_humidity"], row["vpd"], row.get("air_temp")
        )
    return row


def main():
    if MODE != "REAL":
        raise SystemExit(f"MODE is {MODE}, run_real expects REAL")

    from .sensors import SensorHub

    hub = SensorHub()
    print(f"[run_real] sensors: {hub.available}")

    tracker = FreshnessTracker()
    light = DailyLight()
    rh_trigger, vpd_trigger = disease_thresholds(PLANT)
    disease = DiseaseHours(rh_trigger, vpd_trigger)
    print(f"[run_real] plant={PLANT}  disease trigger: RH>{rh_trigger}  VPD<{vpd_trigger}")
    print(f"[run_real] logging to {LOG_PATH} every {READ_INTERVAL_SECONDS} s")

    while True:
        started = time.monotonic()

        timestamp, raw = hub.read()
        clean, issues = validate(raw)
        issues = issues + tracker.check(clean, timestamp)
        store.append_row(LOG_PATH, timestamp, clean)
        row = build_row(timestamp, clean, light, disease)

        print(f"\n{timestamp:%Y-%m-%d %H:%M:%S}")
        for channel, value in sorted(row.items()):
            print(f"   {channel:14s} {value}")
        for channel, problem in issues:
            print(f"   ! {channel}: {problem}")
        recommendations = rules(row, PLANT)
        if not recommendations:
            print("   -> no recommendations")
        for rec in recommendations:
            print(f"   -> [{rec['status']}] {rec['rule']}: {rec['action']}")

        elapsed = time.monotonic() - started
        time.sleep(max(0.0, READ_INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[run_real] stopped")