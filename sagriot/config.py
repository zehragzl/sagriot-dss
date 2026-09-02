SOIL_PORT = "/dev/ttyUSB0"
SOIL_BAUDRATE = 9600
SOIL_SLAVE_ID = 1

VWC_FIELD_CAPACITY = 64.9
LUX_TO_PAR = 0.0185
TZ_NAME = "Europe/Berlin"

PLANT = "tomato"
LOG_PATH = "data/real_log.csv"
ADVICE_PATH = "data/advice_log.csv"
READ_INTERVAL_SECONDS = 30

# Rule policy constants. These are not crop thresholds - they are the same for
# every crop - but they are site-dependent, so they belong here rather than in
# the rule logic.
#
# PAR_DAY_THRESHOLD decides whether a reading is evaluated against the day or
# the night band. The default suits a greenhouse. It does not suit every site:
# on the office testbed PAR exceeded 10 once in 25,676 readings, so every
# reading was judged against the night limits even in the middle of the day.
PAR_DAY_THRESHOLD = 10.0

# Accumulated hours of infection-favourable conditions before the disease rule
# fires. Twice this value is treated as critical.
DISEASE_HOURS_TRIGGER = 2.0

# Local hour after which the day's light budget is considered final, so that a
# shortfall can be reported. Before this hour the day may still catch up.
DAY_END_HOUR = 18

FORECASTERS = {
    # damped_trend was selected here by measurement and has been dropped along
    # with the method. This is an interim choice: chronos_tiny already holds the
    # other two atmospheric channels. Re-check it against the next benchmark.
    "air_temp":     "chronos_tiny",
    "air_humidity": "chronos_tiny",
    "par":          "persistence",        # chronos_tiny yerine
    "co2":          "persistence",
    "soil_vwc":     "driven_drying_vpd",  # _vpd_par yerine
    "soil_temp":    "chronos_tiny",
    "ec":           "persistence",
}