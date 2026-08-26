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

FORECASTERS = {
    "soil_vwc":     "driven_drying_vpd_par",
    "par":          "chronos_tiny",
    "air_temp":     "chronos_tiny",
    "air_humidity": "chronos_tiny",
    "soil_temp":    "chronos_tiny",
    "co2":          "persistence",
    "ec":           "persistence",
}