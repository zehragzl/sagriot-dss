import math

MAX_GAP_SECONDS = 3600
MIN_DLI_COVERAGE = 0.9


def compute_vpd(air_temp, air_humidity):
    es = 0.6108 * math.exp(17.27 * air_temp / (air_temp + 237.3))
    ea = es * air_humidity / 100.0
    return round(es - ea, 3)


class DailyLight:
    def __init__(self):
        self._day = None
        self._dli = 0.0
        self._last = None
        self._covered = 0.0

    def update(self, timestamp, par):
        day = timestamp.date()
        if day != self._day:
            self._day = day
            self._dli = 0.0
            self._last = None
            self._covered = 0.0
        if self._last is not None:
            gap = (timestamp - self._last).total_seconds()
            if 0 < gap <= MAX_GAP_SECONDS:
                self._dli += par * gap / 1e6
                self._covered += gap
        self._last = timestamp
        return round(self._dli, 3)

    def coverage(self, timestamp):
        midnight = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        elapsed = (timestamp - midnight).total_seconds()
        if elapsed <= 0:
            return 0.0
        return round(self._covered / elapsed, 3)


class DiseaseHours:
    def __init__(self, rh_trigger, vpd_trigger, temp_window=(15, 25), off_window_weight=0.3):
        self.rh_trigger = rh_trigger
        self.vpd_trigger = vpd_trigger
        self.temp_window = temp_window
        self.off_window_weight = off_window_weight
        self._hours = 0.0
        self._last = None

    def update(self, timestamp, air_humidity, vpd, air_temp=None):
        elapsed_hours = 0.0
        if self._last is not None:
            gap = (timestamp - self._last).total_seconds()
            if 0 < gap <= MAX_GAP_SECONDS:
                elapsed_hours = gap / 3600.0
        self._last = timestamp

        risky = air_humidity > self.rh_trigger and vpd < self.vpd_trigger
        if risky:
            weight = 1.0
            if air_temp is not None:
                low, high = self.temp_window
                if not (low <= air_temp <= high):
                    weight = self.off_window_weight
            self._hours += elapsed_hours * weight
        else:
            self._hours = max(0.0, self._hours - elapsed_hours)
        return round(self._hours, 3)


def enrich_row(timestamp, measured, light, disease):
    row = dict(measured)
    row["local_hour"] = timestamp.hour
    if "air_temp" in row and "air_humidity" in row:
        row["vpd"] = compute_vpd(row["air_temp"], row["air_humidity"])
    if "par" in row:
        dli = light.update(timestamp, row["par"])
        if light.coverage(timestamp) >= MIN_DLI_COVERAGE:
            row["dli"] = dli
    if "air_humidity" in row and "vpd" in row:
        row["disease_hours"] = disease.update(
            timestamp, row["air_humidity"], row["vpd"], row.get("air_temp")
        )
    return row