import numpy as np
import pandas as pd

from .plants import PLANTS
from .rules import get_thresholds, classify, rules, CRIT_LOW, CRIT_HIGH, NORMAL
from .forecasters import (QUANTILE_LEVELS, Persistence, SeasonalNaive, DampedTrend,
                          DrivenDrying, Ensemble)
from .advise import (CONTEXT, HORIZON, MEASURED, STEP_MINUTES, LEAD_MINUTES,
                     build_forecasters, forecast_channels, build_future_rows,
                     forecast_scenarios, advise_range, advise, current_row)
from .config import VWC_FIELD_CAPACITY

HEALTHY = {"air_temp": 24, "air_humidity": 70, "vpd": 0.65, "co2": 900, "par": 400,
           "dli": 30, "local_hour": 19, "soil_fc": 75, "soil_temp": 19,
           "ec": 2.5, "disease_hours": 0}

STRESSED = {"air_temp": 29.0, "air_humidity": 88, "vpd": 1.15, "co2": 950, "par": 300,
            "dli": 20.0, "local_hour": 19, "soil_fc": 63.0, "soil_temp": 20.0,
            "ec": 4.2, "disease_hours": 2.5}


def check(name, condition):
    print(f"  {'OK  ' if condition else 'FAIL'}  {name}")
    return condition


def _synthetic_frame():
    index = pd.date_range("2026-08-01 12:00", periods=CONTEXT, freq=f"{STEP_MINUTES}min",
                          tz="Europe/Berlin")
    return pd.DataFrame({
        "air_temp":     np.linspace(20.0, 24.0, CONTEXT),
        "air_humidity": np.linspace(70.0, 50.0, CONTEXT),
        "co2":          np.full(CONTEXT, 450.0),
        "par":          np.linspace(0.0, 300.0, CONTEXT),
        "soil_vwc":     np.linspace(50.0, 46.0, CONTEXT),
        "soil_temp":    np.full(CONTEXT, 20.0),
        "ec":           np.full(CONTEXT, 1.5),
    }, index=index)


def advise_checks():
    ok = True
    frame = _synthetic_frame()

    mapping = {channel: "persistence" for channel in MEASURED}
    mapping["soil_vwc"] = "driven_drying_vpd"
    forecasters = build_forecasters(mapping)
    ok &= check("build_forecasters covers every measured channel",
                all(channel in forecasters for channel in MEASURED))

    predictions = forecast_channels(frame, forecasters)
    ok &= check("forecast_channels derives vpd", "vpd" in predictions)
    ok &= check("forecast_channels covers soil_vwc",
                len(predictions.get("soil_vwc", [])) == HORIZON)

    rows = build_future_rows(frame.index[-1], predictions, dli_now=2.0, disease_hours_now=0.0)
    ok &= check("future rows match the horizon", len(rows) == HORIZON)
    ok &= check("first row is one step ahead", rows[0]["minutes_ahead"] == STEP_MINUTES)
    ok &= check("last row is at the horizon", rows[-1]["minutes_ahead"] == HORIZON * STEP_MINUTES)
    ok &= check("timestamps increase", all(rows[i]["timestamp"] < rows[i + 1]["timestamp"]
                                           for i in range(len(rows) - 1)))
    ok &= check("soil_fc derived from forecast vwc", "soil_fc" in rows[0])
    ok &= check("dli carries forward, not reset", rows[0]["dli"] >= 2.0)
    ok &= check("dli accumulates over the horizon", rows[-1]["dli"] >= rows[0]["dli"])
    ok &= check("disease_hours stays non-negative", all(r["disease_hours"] >= 0 for r in rows))

    result = advise(frame, rows, "tomato")
    ok &= check("advise returns now and upcoming",
                set(result) == {"now", "upcoming"})

    dry = frame.copy()
    dry["soil_vwc"] = 40.0
    dry_rows = []
    for row in rows:
        copy = dict(row)
        copy["soil_vwc"] = 39.0
        copy["soil_fc"] = round(39.0 / VWC_FIELD_CAPACITY * 100, 1)
        dry_rows.append(copy)
    dry_result = advise(dry, dry_rows, "tomato")
    dry_active = {item["rule"] for item in dry_result["now"]}
    dry_upcoming = {item["rule"] for item in dry_result["upcoming"]}
    ok &= check("already-dry soil triggers Irrigation now", "Irrigation" in dry_active)
    ok &= check("an active rule is not repeated as upcoming",
                "Irrigation" not in dry_upcoming)

    wet = frame.copy()
    wet["soil_vwc"] = 50.0
    falling = []
    for index, row in enumerate(rows):
        copy = dict(row)
        value = 50.0 - 0.2 * (index + 1)
        copy["soil_vwc"] = value
        copy["soil_fc"] = round(value / VWC_FIELD_CAPACITY * 100, 1)
        falling.append(copy)
    forward = advise(wet, falling, "tomato")
    ok &= check("a future crossing is detected as upcoming",
                "Irrigation" in {item["rule"] for item in forward["upcoming"]})
    ok &= check("that rule is not active yet",
                "Irrigation" not in {item["rule"] for item in forward["now"]})

    for item in forward["upcoming"]:
        expected = LEAD_MINUTES.get(item["rule"], 60)
        ok &= check(f"{item['rule']}: lead time is {expected} min",
                    item["lead_minutes"] == expected)
        ok &= check(f"{item['rule']}: advise_now matches lead arithmetic",
                    item["advise_now"] == (item["when_minutes"] - item["lead_minutes"] <= 0))

    scenarios = forecast_scenarios(frame, forecasters)
    ok &= check("one scenario per quantile level", set(scenarios) == set(QUANTILE_LEVELS))
    ok &= check("every scenario carries soil_vwc and vpd",
                all("soil_vwc" in s and "vpd" in s for s in scenarios.values()))
    low, high = scenarios[min(QUANTILE_LEVELS)], scenarios[max(QUANTILE_LEVELS)]
    ok &= check("the dry scenario is never wetter than the wet one",
                np.all(low["soil_vwc"] <= high["soil_vwc"] + 1e-9))

    banded = advise_range(wet, {level: {**channels,
                                        "soil_vwc": np.array([50.0 - 0.2 * (i + 1)
                                                              for i in range(HORIZON)])}
                                for level, channels in scenarios.items()}, "tomato")
    ok &= check("advise_range returns now and upcoming",
                set(banded) == {"now", "upcoming"})
    for item in banded["upcoming"]:
        ok &= check(f"{item['rule']}: earliest <= expected <= latest",
                    item["earliest_minutes"] <= item["when_minutes"] <= item["latest_minutes"])
        ok &= check(f"{item['rule']}: probability in (0, 1]",
                    0 < item["probability"] <= 1)

    now = current_row(frame)
    ok &= check("current_row computes vpd", "vpd" in now)
    ok &= check("current_row uses the last reading",
                abs(now["soil_vwc"] - frame["soil_vwc"].iloc[-1]) < 1e-9)
    return ok


def main():
    ok = True

    bounds = get_thresholds("tomato")["ec"]
    ok &= check("classify: below crit_low is CRIT_LOW", classify(0.1, {"crit_low": 1, "warn_low": 2, "warn_high": 3, "crit_high": 4}) == CRIT_LOW)
    ok &= check("classify: above crit_high is CRIT_HIGH", classify(9.0, {"crit_low": 1, "warn_low": 2, "warn_high": 3, "crit_high": 4}) == CRIT_HIGH)
    ok &= check("classify: inside band is NORMAL", classify(2.5, {"crit_low": 1, "warn_low": 2, "warn_high": 3, "crit_high": 4}) == NORMAL)
    ok &= check("classify: None bound is ignored", classify(-5, {"crit_low": None, "warn_low": None, "warn_high": None, "crit_high": None}) == NORMAL)

    seedling = get_thresholds("tomato", "seedling")
    ok &= check("stage merge keeps all parameters", len(seedling) == len(get_thresholds("tomato")))
    ok &= check("stage override applies", seedling["ec"]["warn_high"] == 2.5)
    ok &= check("stage inherits default", seedling["vpd"] == get_thresholds("tomato")["vpd"])
    ok &= check("PLANTS not mutated", PLANTS["tomato"]["stages"]["default"]["ec"]["warn_high"] == 3.5)

    result = rules(HEALTHY, "tomato")
    ok &= check("rules returns a list", isinstance(result, list))
    ok &= check("healthy row gives no recommendation", result == [])

    stressed = rules(STRESSED, "tomato")
    ok &= check("stressed row gives recommendations", len(stressed) > 0)
    ok &= check("recommendations sorted by severity", all(
        abs(stressed[i]["level"]) >= abs(stressed[i + 1]["level"]) for i in range(len(stressed) - 1)))

    per_plant = {p: len(rules(STRESSED, p)) for p in PLANTS}
    ok &= check(f"same row differs by plant {per_plant}", len(set(per_plant.values())) > 1)

    from .rules import _band
    from .config import PAR_DAY_THRESHOLD, DISEASE_HOURS_TRIGGER, DAY_END_HOUR
    ok &= check("day band above the configured PAR threshold",
                _band({"par": PAR_DAY_THRESHOLD + 1}, "air_temp") == "air_temp_day")
    ok &= check("night band below it",
                _band({"par": PAR_DAY_THRESHOLD - 1}, "air_temp") == "air_temp_night")
    ok &= check("a missing PAR reading falls back to the night band",
                _band({}, "air_temp") == "air_temp_night")
    ok &= check("rule policy constants live in config, not in rules",
                all(isinstance(v, (int, float))
                    for v in (PAR_DAY_THRESHOLD, DISEASE_HOURS_TRIGGER, DAY_END_HOUR)))

    ok &= check("missing channels do not raise", rules({"local_hour": 12}, "tomato") == [])
    ok &= check("NaN is dropped", rules({**HEALTHY, "soil_fc": float("nan")}, "tomato") == [])
    ok &= check("implausible value is dropped", rules({**HEALTHY, "soil_temp": -40}, "tomato") == [])

    history = np.linspace(60, 50, 288)
    exog_past = {"vpd": np.linspace(1.0, 1.4, 288), "par": np.linspace(0, 400, 288)}
    exog_future = {"vpd": np.full(36, 1.2), "par": np.full(36, 200.0)}
    models = [Persistence(), SeasonalNaive(288), DampedTrend(),
              DrivenDrying(("vpd",)), DrivenDrying(("vpd", "par")),
              DrivenDrying(("vpd",), decay=0.99),
              Ensemble([Persistence(), DrivenDrying(("vpd",))])]
    for model in models:
        out = model.predict(history, 36, exog_past, exog_future)
        ok &= check(f"{model.name}: returns 36 finite values",
                    len(out) == 36 and np.all(np.isfinite(out)))

        bands = model.predict_quantiles(history, 36, exog_past, exog_future)
        ok &= check(f"{model.name}: a band for every level",
                    set(bands) == set(QUANTILE_LEVELS))
        ok &= check(f"{model.name}: bands are the right length and finite",
                    all(len(b) == 36 and np.all(np.isfinite(b)) for b in bands.values()))
        ordered = [bands[level] for level in sorted(bands)]
        ok &= check(f"{model.name}: quantiles never cross",
                    all(np.all(ordered[i] <= ordered[i + 1] + 1e-9)
                        for i in range(len(ordered) - 1)))

    flat = Persistence().predict_quantiles(history, 36)
    ok &= check("persistence has no spread - it can never cross a threshold",
                np.allclose(flat[min(QUANTILE_LEVELS)], flat[max(QUANTILE_LEVELS)]))

    spread = DrivenDrying(("vpd",)).predict_quantiles(history, 36, exog_past, exog_future)
    width = spread[max(QUANTILE_LEVELS)] - spread[min(QUANTILE_LEVELS)]
    ok &= check("driven_drying band widens with the horizon", width[-1] > width[0])

    drying = DrivenDrying(("vpd",)).predict(history, 36, exog_past, exog_future)
    ok &= check("driven_drying is non-increasing", np.all(np.diff(drying) <= 1e-9))
    ok &= check("no scenario rises above the last observation",
                np.all(spread[max(QUANTILE_LEVELS)] <= history[-1] + 1e-9))

    without_exog = DrivenDrying(("vpd",)).predict(history, 36)
    ok &= check("driven_drying falls back to persistence without drivers",
                np.allclose(without_exog, history[-1]))

    ok &= advise_checks()

    print("\nPASSED" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())