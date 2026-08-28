import time

from .config import PLANT, LOG_PATH, ADVICE_PATH, READ_INTERVAL_SECONDS
from .features import DailyLight, DiseaseHours, FreshnessTracker, enrich_row
from .rules import rules, get_thresholds
from .advise import (CONTEXT, HORIZON, STEP_MINUTES, load_recent, build_forecasters,
                     forecast_scenarios, advise_range)
from . import store

FORECAST_INTERVAL_SECONDS = 600
HORIZON_MINUTES = HORIZON * STEP_MINUTES


def show_upcoming(upcoming, age_minutes, announced, fresh):
    """Print the standing early warning, counted down to the present reading.

    The forecast is recomputed every FORECAST_INTERVAL_SECONDS, but it is shown
    on every reading, with the remaining time reduced by however long ago it was
    computed. Nothing is recomputed here; only the clock moves.
    """
    if not upcoming:
        return

    age = int(round(age_minutes))
    when = "next 3 h" if fresh else f"computed {age} min ago"
    print(f"   ~> EARLY WARNING ({when}):")

    for name, item in upcoming.items():
        remaining = max(0, item["when_minutes"] - age)
        earliest = max(0, item["earliest_minutes"] - age)
        latest = max(0, item["latest_minutes"] - age)
        advise_now = remaining - item["lead_minutes"] <= 0

        mark = "  *NEW*" if fresh and announced.get(name) != advise_now else ""
        if fresh:
            announced[name] = advise_now

        action = "ADVISE NOW" if advise_now else f"advise in {remaining - item['lead_minutes']} min"
        due = "due" if remaining == 0 else f"in {remaining:3d} min"
        print(f"      {item['rule']:24s} {due} "
              f"[{earliest}-{latest}, p={item['probability']:.0%}] "
              f"({item['status']}) — {action}{mark}")


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
    freshness = FreshnessTracker()
    print(f"[run_real] plant={PLANT}  disease trigger: RH>{rh_trigger}  VPD<{vpd_trigger}")
    print(f"[run_real] logging to {LOG_PATH} every {READ_INTERVAL_SECONDS} s")

    forecasters = build_forecasters()
    announced = {}
    last_forecast = 0.0
    pending = {}
    pending_at = None

    while True:
        started = time.monotonic()

        timestamp, measured = hub.read()
        store.append_row(LOG_PATH, timestamp, measured)
        row = enrich_row(timestamp, measured, light, disease)

        print(f"\n{timestamp:%Y-%m-%d %H:%M:%S}")
        for channel, value in sorted(row.items()):
            print(f"   {channel:14s} {value}")
        for channel, problem in freshness.check(measured):
            print(f"   ! {channel}: {problem}")
        recommendations = rules(row, PLANT)
        if not recommendations:
            print("   -> no recommendations")
        for rec in recommendations:
            print(f"   -> [{rec['status']}] {rec['rule']}: {rec['action']}")

        fresh = False
        if time.monotonic() - last_forecast >= FORECAST_INTERVAL_SECONDS:
            last_forecast = time.monotonic()
            try:
                recent = load_recent(LOG_PATH)
                if len(recent) >= CONTEXT:
                    scenarios = forecast_scenarios(recent, forecasters)
                    result = advise_range(
                        recent, scenarios, PLANT,
                        dli_now=row.get("dli", 0.0),
                        disease_hours_now=row.get("disease_hours", 0.0),
                        rh_trigger=rh_trigger, vpd_trigger=vpd_trigger,
                    )
                    for item in result["now"]:
                        store.append_advice(ADVICE_PATH, timestamp, "current", item)

                    upcoming = {item["rule"]: item for item in result["upcoming"]}
                    for item in upcoming.values():
                        store.append_advice(ADVICE_PATH, timestamp, "forecast", item)

                    for name in list(announced):
                        if name not in upcoming:
                            print(f"      {name:24s} no longer forecast")
                            del announced[name]

                    pending, pending_at, fresh = upcoming, timestamp, True
                else:
                    print(f"   ~> not enough history yet ({len(recent)}/{CONTEXT})")
            except Exception as error:
                print(f"   ~> forecast failed: {type(error).__name__}: {error}")

        # Shown on every reading, recomputed only every FORECAST_INTERVAL_SECONDS.
        if pending and pending_at is not None:
            age = (timestamp - pending_at).total_seconds() / 60
            if age > HORIZON_MINUTES:
                pending, pending_at, announced = {}, None, {}
            else:
                show_upcoming(pending, age, announced, fresh)

        elapsed = time.monotonic() - started
        time.sleep(max(0.0, READ_INTERVAL_SECONDS - elapsed))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[run_real] stopped")
