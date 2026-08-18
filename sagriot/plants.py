# Parametre meta bilgisi — bitkiden bağımsız, bir kez tanımlanır
PARAMS = {
    "air_temp_day":   {"unit": "°C",            "label": "Air temperature (day)"},
    "air_temp_night": {"unit": "°C",            "label": "Air temperature (night)"},
    "air_humidity":   {"unit": "% RH",          "label": "Air humidity"},
    "vpd":            {"unit": "kPa",           "label": "Vapour pressure deficit"},
    "co2":            {"unit": "ppm",           "label": "CO2 concentration"},
    "dli":            {"unit": "mol/m²/day",    "label": "Daily light integral"},
    "soil_fc":        {"unit": "% FC",          "label": "Soil moisture"},
    "soil_temp":      {"unit": "°C",            "label": "Root-zone temperature"},
    "ec":             {"unit": "dS/m",          "label": "Electrical conductivity"},
}

PLANTS = {
    "tomato": {
        "label": "Tomato (Solanum lycopersicum)",
        "stages": {
            "default": {
                "air_temp_day":   {"crit_low": 12,   "warn_low": 21,  "warn_high": 27,   "crit_high": 32},
                "air_temp_night": {"crit_low": 12,   "warn_low": 16,  "warn_high": 18,   "crit_high": 32},
                "air_humidity":   {"crit_low": None, "warn_low": 60,  "warn_high": 85,   "crit_high": None},
                "vpd":            {"crit_low": 0.3,  "warn_low": 0.5, "warn_high": 0.8,  "crit_high": 1.0},
                "co2":            {"crit_low": 400,  "warn_low": 800, "warn_high": 1000, "crit_high": None},
                "dli":            {"crit_low": None, "warn_low": 25,  "warn_high": 35,   "crit_high": None},
                "soil_fc":        {"crit_low": 60,   "warn_low": 70,  "warn_high": 80,   "crit_high": None},
                "soil_temp":      {"crit_low": 14,   "warn_low": 15,  "warn_high": 22,   "crit_high": 35},
                "ec":             {"crit_low": None, "warn_low": 1.2, "warn_high": 3.5,  "crit_high": 5.0},
            },
            "seedling": {
                "ec":             {"crit_low": None, "warn_low": 1.2, "warn_high": 2.5,  "crit_high": 4.0},
            },
        },
    },
    "cucumber": {
        "label": "Cucumber (Cucumis sativus)",
        "stages": {
            "default": {
                "air_temp_day":   {"crit_low": 12,   "warn_low": 16,   "warn_high": 25,   "crit_high": 32},
                "air_temp_night": {"crit_low": 12,   "warn_low": 14,   "warn_high": 23,   "crit_high": 32},
                "air_humidity":   {"crit_low": None, "warn_low": 60,   "warn_high": 70,   "crit_high": None},
                "vpd":            {"crit_low": 0.35, "warn_low": 0.75, "warn_high": 1.35, "crit_high": None},
                "co2":            {"crit_low": 400,  "warn_low": 800,  "warn_high": 1000, "crit_high": None},
                "dli":            {"crit_low": 15,   "warn_low": 20,   "warn_high": 35,   "crit_high": None},
                "soil_fc":        {"crit_low": 65,   "warn_low": 70,   "warn_high": 80,   "crit_high": None},
                "soil_temp":      {"crit_low": 19,   "warn_low": 20,   "warn_high": 25,   "crit_high": 33},
                "ec":             {"crit_low": None, "warn_low": 1.2,  "warn_high": 3.5,  "crit_high": 5.0},
            },
        },
    },

    "strawberry": {
        "label": "Strawberry (Fragaria x ananassa)",
        "stages": {
            "default": {
                "air_temp_day":   {"crit_low": 12,   "warn_low": 18,  "warn_high": 25,   "crit_high": 32},
                "air_temp_night": {"crit_low": 12,   "warn_low": 15,  "warn_high": 20,   "crit_high": 32},
                "air_humidity":   {"crit_low": None, "warn_low": 65,  "warn_high": 75,   "crit_high": None},
                "vpd":            {"crit_low": None, "warn_low": 0.2, "warn_high": 0.4,  "crit_high": None},
                "co2":            {"crit_low": 400,  "warn_low": 800, "warn_high": 1000, "crit_high": None},
                "dli":            {"crit_low": 12,   "warn_low": 20,  "warn_high": 25,   "crit_high": 30},
                "soil_fc":        {"crit_low": 65,   "warn_low": 75,  "warn_high": 85,   "crit_high": None},
                "soil_temp":      {"crit_low": 12,   "warn_low": 16,  "warn_high": 20,   "crit_high": 30},
                "ec":             {"crit_low": None, "warn_low": 0.8, "warn_high": 1.5,  "crit_high": 2.0},
            },
        },
    },
}


def _check():
    order = ["crit_low", "warn_low", "warn_high", "crit_high"]
    for plant, cfg in PLANTS.items():
        assert "default" in cfg["stages"], f"{plant}: missing 'default' stage"
        assert set(cfg["stages"]["default"]) == set(PARAMS), \
            f"{plant}/default: parameter set mismatch"
        for stage, params in cfg["stages"].items():
            for name, b in params.items():
                assert name in PARAMS, f"{plant}/{stage}: unknown parameter {name}"
                vals = [b[k] for k in order if b.get(k) is not None]
                assert vals == sorted(vals), f"{plant}/{stage}/{name}: limits are not sorted {b}"

_check()