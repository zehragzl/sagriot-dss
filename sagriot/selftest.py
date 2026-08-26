import numpy as np

from .plants import PLANTS
from .rules import get_thresholds, classify, rules, CRIT_LOW, CRIT_HIGH, NORMAL
from .forecasters import (Persistence, SeasonalNaive, DampedTrend, DrivenDrying)

HEALTHY = {"air_temp": 24, "air_humidity": 70, "vpd": 0.65, "co2": 900, "par": 400,
           "dli": 30, "local_hour": 19, "soil_fc": 75, "soil_temp": 19,
           "ec": 2.5, "disease_hours": 0}

STRESSED = {"air_temp": 29.0, "air_humidity": 88, "vpd": 1.15, "co2": 950, "par": 300,
            "dli": 20.0, "local_hour": 19, "soil_fc": 63.0, "soil_temp": 20.0,
            "ec": 4.2, "disease_hours": 2.5}


def check(name, condition):
    print(f"  {'OK  ' if condition else 'FAIL'}  {name}")
    return condition


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

    ok &= check("missing channels do not raise", rules({"local_hour": 12}, "tomato") == [])
    ok &= check("NaN is dropped", rules({**HEALTHY, "soil_fc": float("nan")}, "tomato") == [])
    ok &= check("implausible value is dropped", rules({**HEALTHY, "soil_temp": -40}, "tomato") == [])

    history = np.linspace(60, 50, 288)
    exog_past = {"vpd": np.linspace(1.0, 1.4, 288), "par": np.linspace(0, 400, 288)}
    exog_future = {"vpd": np.full(36, 1.2), "par": np.full(36, 200.0)}
    for model in [Persistence(), SeasonalNaive(288), DampedTrend(),
                  DrivenDrying(("vpd",)), DrivenDrying(("vpd", "par"))]:
        out = model.predict(history, 36, exog_past, exog_future)
        ok &= check(f"{model.name}: returns 36 finite values",
                    len(out) == 36 and np.all(np.isfinite(out)))

    drying = DrivenDrying(("vpd",)).predict(history, 36, exog_past, exog_future)
    ok &= check("driven_drying is non-increasing", np.all(np.diff(drying) <= 1e-9))

    print("\nPASSED" if ok else "\nFAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())