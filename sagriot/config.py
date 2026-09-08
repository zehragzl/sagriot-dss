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

# Per-channel choice, re-measured on the 2 September benchmark (testbed rows).
#
# One entry here is a known weakness rather than a choice. On air_temp the most
# accurate method available is also one that never warns: chronos_tiny has a
# skill of 0.221 and a recall of 0.000 on nine crossings. The only method with
# useful recall on that channel is seasonal naive (0.333), and its skill is
# -2.300, which in this room means wild forecasts. So the early warning for
# Rule 4 is, on temperature, close to decorative. This is the exact mistake
# this work is about - a forecaster chosen by error - found in its own
# configuration. It is left visible instead of quietly patched.
FORECASTERS = {
    "air_temp":     "chronos_tiny",       # accurate, recall 0.000 - see note above
    "air_humidity": "chronos_tiny",       # recall 0.200; chronos_small gains 0.025 for 3.5x the cost
    # chronos_tiny forecasts par far more accurately here (skill 0.290 against
    # 0.000) and it is not worth taking. par has no threshold of its own; it
    # feeds the daily light budget, and no rule outcome on this site changes
    # with a better par forecast. The accurate method costs 33 ms instead of
    # 0.014 ms - two thousand times more compute for no decision. Worth
    # re-checking at a site where the light budget actually crosses 25 mol.
    "par":          "persistence",
    "co2":          "persistence",        # every other method scores below zero here
    "soil_vwc":     "driven_drying_vpd",  # recall 0.889, 13.1 min, 0.23 ms - unchanged
    "soil_temp":    "chronos_tiny",       # recall 0.500 and better timing than chronos_small
    "ec":           "persistence",        # no method beats it; the EC scale artefact is upstream
}