from .plants import PLANTS, PARAMS, PLAUSIBLE

def get_thresholds(plant, stage="default"):
    """Return thresholds for a plant, with stage overrides applied over default."""
    if plant not in PLANTS:
        raise ValueError(f"Unknown plant: {plant}")
    stages = PLANTS[plant]["stages"]
    if stage not in stages:
        raise ValueError(f"Unknown stage: {stage} for plant: {plant}")

    merged = {name: dict(bounds) for name, bounds in stages["default"].items()}
    if stage != "default":
        for name, bounds in stages[stage].items():
            merged[name] = dict(bounds)
    return merged


CRIT_LOW  = -2
WARN_LOW  = -1
NORMAL    =  0
WARN_HIGH =  1
CRIT_HIGH =  2

LEVEL_NAMES = {
    -2: "critical-low", -1: "warning-low", 0: "healthy",
     1: "warning-high", 2: "critical-high",
}

def classify(value, bounds):
    """Classify a value into 5 directional levels.
    """
    if bounds["crit_low"] is not None and value < bounds["crit_low"]:
        return CRIT_LOW
    if bounds["crit_high"] is not None and value > bounds["crit_high"]:
        return CRIT_HIGH
    if bounds["warn_low"] is not None and value < bounds["warn_low"]:
        return WARN_LOW
    if bounds["warn_high"] is not None and value > bounds["warn_high"]:
        return WARN_HIGH
    return NORMAL


def _rec(rule, signals, action, level=None):
    """Build one recommendation. signals: list of (param, value, level)."""
    worst = level if level is not None else min(signals, key=lambda s: -abs(s[2]))[2]
    parts = [f"{PARAMS[p]['label']} {v} {PARAMS[p]['unit']} ({LEVEL_NAMES[lv]})"
             for p, v, lv in signals]
    return {
        "rule":    rule,
        "signals": [{"param": p, "value": v, "level": lv} for p, v, lv in signals],
        "level":   worst,
        "status":  LEVEL_NAMES[worst],
        "action":  action,
        "message": " + ".join(parts) + f" → {action}",
    }

def _band(row, base):
    """Pick the day or night band of a parameter based on light."""
    return f"{base}_day" if row.get("par", 0) > 10 else f"{base}_night"

DISEASE_HOURS_TRIGGER = 2.0

def _usable(row):
    clean = {}
    for channel, value in row.items():
        if value is None or value != value:
            continue
        low_high = PLAUSIBLE.get(channel)
        if low_high and not (low_high[0] <= value <= low_high[1]):
            continue
        clean[channel] = value
    return clean

def rules(row, plant, stage="default"):
    """Return a list of recommendations for a given plant and stage."""
    
    th = get_thresholds(plant, stage)
    row = _usable(row)
    recs = []

    # Rule 1 — Water stress
    if "vpd" in row and "soil_fc" in row:
        lv_vpd  = classify(row["vpd"], th["vpd"])
        lv_soil = classify(row["soil_fc"], th["soil_fc"])
        if lv_vpd >= WARN_HIGH and lv_soil <= WARN_LOW:
            recs.append(_rec("Water stress",
                             [("vpd", row["vpd"], lv_vpd),
                              ("soil_fc", row["soil_fc"], lv_soil)],
                             "irrigate and/or lower VPD"))

    # Rule 2 — Irrigation
    if "soil_fc" in row:
        lv = classify(row["soil_fc"], th["soil_fc"])
        if lv <= WARN_LOW:
            recs.append(_rec("Irrigation",
                             [("soil_fc", row["soil_fc"], lv)],
                             "irrigate now"))

    # Rule 3 — Fertilization
    if "ec" in row:
        lv = classify(row["ec"], th["ec"])
        if lv <= WARN_LOW:
            recs.append(_rec("Fertilization",
                             [("ec", row["ec"], lv)],
                             "add nutrients"))
        elif lv >= WARN_HIGH:
            recs.append(_rec("Fertilization",
                             [("ec", row["ec"], lv)],
                             "flush the root zone"))

    # Rule 4 — Ventilation
    sig = []
    trigger = False
    if "air_temp" in row:
        param = _band(row, "air_temp")
        lv = classify(row["air_temp"], th[param])
        if lv >= WARN_HIGH:
            sig.append((param, row["air_temp"], lv))
            trigger = True
    if "air_humidity" in row:
        param = _band(row, "air_humidity")
        lv = classify(row["air_humidity"], th[param])
        if lv >= WARN_HIGH:
            sig.append((param, row["air_humidity"], lv))
            trigger = True
    if trigger and "co2" in row:
        sig.append(("co2", row["co2"], classify(row["co2"], th["co2"])))
    if trigger:
        recs.append(_rec("Ventilation", sig, "ventilate"))

    # Rule 5 — Lighting
    if "dli" in row:
        b = th["dli"]
        lv = classify(row["dli"], b)
        if lv > 0 and row.get("par", 0) > 10:
            recs.append(_rec("Lighting", [("dli", row["dli"], lv)],
                             "Shade or reduce supplemental lighting"))
        elif lv < 0 and row.get("local_hour", 24) >= 18:
            recs.append(_rec("Lighting", [("dli", row["dli"], lv)],
                             "Add supplemental light"))

    # Rule 6 — Disease risk
    hours = row.get("disease_hours", 0)
    if hours >= DISEASE_HOURS_TRIGGER:
        sig = []
        if "air_humidity" in row:
            param = _band(row, "air_humidity")
            sig.append((param, row["air_humidity"], classify(row["air_humidity"], th[param])))
        if "vpd" in row:
            sig.append(("vpd", row["vpd"], classify(row["vpd"], th["vpd"])))
        if sig:
            level = 2 if hours >= 2 * DISEASE_HOURS_TRIGGER else 1
            recs.append(_rec("Disease risk", sig, "Ventilate or dehumidify", level=level))

    # Rule 7 — Root-zone temperature
    if "soil_temp" in row:
        lv = classify(row["soil_temp"], th["soil_temp"])
        if lv <= WARN_LOW:
            recs.append(_rec("Root-zone temperature",
                             [("soil_temp", row["soil_temp"], lv)],
                             "warm the root zone"))
        elif lv >= WARN_HIGH:
            recs.append(_rec("Root-zone temperature",
                             [("soil_temp", row["soil_temp"], lv)],
                             "cool the root zone"))
        
    return sorted(recs, key=lambda r: -abs(r["level"]))

if __name__ == "__main__":
    d = get_thresholds("tomato")
    s = get_thresholds("tomato", "seedling")
    print("default params :", len(d))
    print("seedling params:", len(s))
    print("seedling ec    :", s["ec"])
    print("seedling vpd   :", s["vpd"], "(default'tan geldi)")
    print("PLANTS intact  :", PLANTS["tomato"]["stages"]["default"]["ec"])

    row = {"air_temp": 29.0, "air_humidity": 88, "vpd": 1.15, "co2": 950, "par": 300,
           "dli": 20.0, "local_hour": 19, "soil_fc": 63.0, "soil_temp": 20.0,
           "ec": 4.2, "disease_hours": 2.5}

    for plant in PLANTS:
        print(f"\n=== {plant} ===")
        for r in rules(row, plant):
            print(f"  [{r['level']:+d}] {r['rule']:14} {r['action']}")

    print("\n=== healthy row (should be empty) ===")
    ok = {"air_temp": 24, "air_humidity": 70, "vpd": 0.65, "co2": 900, "par": 400,
          "dli": 30, "local_hour": 19, "soil_fc": 75, "soil_temp": 19,
          "ec": 2.5, "disease_hours": 0}
    print(" ", rules(ok, "tomato"))

    print("=== tomato, midday, too much light ===")
    print(rules({"dli": 40.0, "par": 500.0, "local_hour": 14}, "tomato"))

    print("=== strawberry, same row ===")
    print(rules({"dli": 40.0, "par": 500.0, "local_hour": 14}, "strawberry"))

    print("=== tomato, evening, too little light ===")
    print(rules({"dli": 12.0, "par": 0.0, "local_hour": 19}, "tomato"))

    print("=== tomato, morning, low DLI but day not over ===")
    print(rules({"dli": 4.0, "par": 300.0, "local_hour": 9}, "tomato"))