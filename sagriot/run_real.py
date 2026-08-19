import time

from .config import PLANT, LOG_PATH, READ_INTERVAL_SECONDS
from .features import DailyLight, DiseaseHours, enrich_row
from .rules import rules, get_thresholds
from . import store


def disease_triggers(plant):
    thresholds = get_thresholds(plant)
    humidity = thresholds["air_humidity_night"]
    vpd = thresholds["vpd"]
    rh_trigger = humidity["warn_high"]
    vpd_trigger = vpd["crit_low"] if vpd["crit_low"] is not None else vpd["warn_low"]
    return rh_trigger, vpd_trigger


def main():
    from .sensors import SensorHub

    hub = SensorHub()
    print(f"[run_real] sensors: {hub.available}")

    light = DailyLight()
    rh_trigger, vpd_trigger = disease_triggers(PLANT)
    disease = DiseaseHours(rh_trigger, vpd_trigger)
    print(f"[run_real] plant={PLANT}  disease trigger: RH>{rh_trigger}  VPD<{vpd_trigger}")
    print(f"[run_real] logging to {LOG_PATH} every {READ_INTERVAL_SECONDS} s")

    while True:
        started = time.monotonic()

        timestamp, measured = hub.read()
        store.append_row(LOG_PATH, timestamp, measured)
        row = enrich_row(timestamp, measured, light, disease)

        print(f"\n{timestamp:%Y-%m-%d %H:%M:%S}")
        for channel, value in sorted(row.items()):
            print(f"   {channel:14s} {value}")
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