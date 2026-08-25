import time

from .config import PLANT, LOG_PATH, READ_INTERVAL_SECONDS
from .features import DailyLight, DiseaseHours, enrich_row
from .rules import rules, get_thresholds
from .advise import (CONTEXT, load_recent, build_forecasters,
                     forecast_channels, build_future_rows, advise as make_advice)
from . import store

FORECAST_INTERVAL_SECONDS = 600


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

    forecasters = build_forecasters()
    announced = {}
    last_forecast = 0.0

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

        if time.monotonic() - last_forecast >= FORECAST_INTERVAL_SECONDS:
            last_forecast = time.monotonic()
            try:
                recent = load_recent(LOG_PATH)
                if len(recent) >= CONTEXT:
                    predictions = forecast_channels(recent, forecasters)
                    future = build_future_rows(
                        recent.index[-1], predictions,
                        dli_now=row.get("dli", 0.0),
                        disease_hours_now=row.get("disease_hours", 0.0),
                        rh_trigger=rh_trigger, vpd_trigger=vpd_trigger,
                    )
                    result = make_advice(
                        recent, future, PLANT,
                        dli_now=row.get("dli", 0.0),
                        disease_hours_now=row.get("disease_hours", 0.0),
                    )
                    upcoming = {item["rule"]: item for item in result["upcoming"]}
                    for name, item in upcoming.items():
                        if announced.get(name) == item["advise_now"]:
                            continue
                        announced[name] = item["advise_now"]
                        when = "SIMDI UYAR" if item["advise_now"] else \
                               f"{item['when_minutes'] - item['lead_minutes']} dk sonra uyar"
                        print(f"   ~> ONGORU: {item['rule']} — {item['when_minutes']} dk sonra "
                              f"({item['status']}) — {when}")
                    for name in list(announced):
                        if name not in upcoming:
                            del announced[name]
                else:
                    print(f"   ~> tahmin icin yeterli gecmis yok ({len(recent)}/{CONTEXT})")
            except Exception as error:
                print(f"   ~> tahmin basarisiz: {error}")

        elapsed = time.monotonic() - started
        time.sleep(max(0.0, READ_INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[run_real] stopped")