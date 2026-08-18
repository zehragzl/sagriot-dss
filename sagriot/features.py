import math
from datetime import datetime


def compute_vpd(air_temp, air_humidity):
    es = 0.6108 * math.exp(17.27 * air_temp / (air_temp + 237.3))
    ea = es * air_humidity / 100.0
    return round(es - ea, 3)


def local_hour(timestamp):
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp)
    return timestamp.hour


MAX_GAP_SECONDS = 3600


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
            dt = (timestamp - self._last).total_seconds()
            if 0 < dt <= MAX_GAP_SECONDS:
                self._dli += par * dt / 1e6
                self._covered += dt
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
        dt_hours = 0.0
        if self._last is not None:
            dt = (timestamp - self._last).total_seconds()
            if 0 < dt <= MAX_GAP_SECONDS:
                dt_hours = dt / 3600.0
        self._last = timestamp

        risky = air_humidity > self.rh_trigger and vpd < self.vpd_trigger
        if risky:
            weight = 1.0
            if air_temp is not None:
                lo, hi = self.temp_window
                if not (lo <= air_temp <= hi):
                    weight = self.off_window_weight
            self._hours += dt_hours * weight
        else:
            self._hours = max(0.0, self._hours - dt_hours)

        return round(self._hours, 3)

if __name__ == "__main__":
    print(compute_vpd(25, 60))
    print(compute_vpd(20, 90))