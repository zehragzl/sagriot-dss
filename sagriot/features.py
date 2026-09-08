import math

MAX_GAP_SECONDS = 3600
MIN_DLI_COVERAGE = 0.9
STUCK_REPEATS = 60
WATCHED_CHANNELS = ("air_temp", "air_humidity", "co2", "lux")


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

class IrrigationWatch:
    """Notices that somebody watered.

    The soil model clips its rates at zero, because soil cannot gain water
    without input, so to the forecaster a watering is only an outlier. Nothing
    in the system knew that the state had changed, and on 2 September that was
    visible: the standing advice kept reading ADVISE NOW for ten minutes after
    the pot had been watered and the reading had already risen from 45 to 101
    %FC. With a valve on the end of it, that is a second irrigation.

    A rise of more than a few points between two consecutive readings cannot be
    anything else - the soil has no other way to gain water in thirty seconds.
    """

    def __init__(self, jump=3.0, channel="soil_vwc"):
        self.jump = jump
        self.channel = channel
        self._last = None

    def check(self, row):
        """Returns (before, after) when a watering is detected, else None."""
        value = row.get(self.channel)
        if value is None:
            return None
        previous, self._last = self._last, value
        if previous is None:
            return None
        return (previous, value) if value - previous >= self.jump else None


def night_baseline(frame, channel, start_hour=1, end_hour=4):
    """Median of a channel during the hours when it should be at rest.

    A dark room has a known light level and an empty room a known CO2 level, so
    a step in either between one night and the next has to be physical: a leaf
    across the sensor, a probe working loose, a drift in the device itself.
    Nothing else about the reading looks wrong, which is why the liveness checks
    never saw it - a covered sensor still returns fresh, plausible, changing
    values.

    Returns a Series indexed by date. Written from a habit that caught two real
    obstructions of the light sensor by hand; the point of putting it here is
    that nobody should have to remember to look.
    """
    if channel not in frame.columns:
        return None
    hours = frame.index.hour
    window = frame[(hours >= start_hour) & (hours <= end_hour)]
    if window.empty:
        return None
    return window[channel].groupby(window.index.date).median().dropna()


def baseline_alerts(frame, channels=("lux", "co2"), nights=7, tolerance=0.5):
    """Compare the most recent night against the nights before it.

    tolerance is a fraction of the reference: 0.5 reports a halving or a
    doubling. Channels rest at very different magnitudes, so a relative test is
    the only one that transfers between them.

    lux rather than par: par is lux times a small constant and rounds to zero
    overnight, which destroys exactly the resolution this check depends on.
    """
    alerts = []
    for channel in channels:
        series = night_baseline(frame, channel)
        if series is None or len(series) < 3:
            continue
        latest, history = series.iloc[-1], series.iloc[-(nights + 1):-1]
        if history.empty:
            continue
        reference = float(history.median())
        if reference <= 0:
            continue
        change = (float(latest) - reference) / reference
        if abs(change) >= tolerance:
            alerts.append({
                "channel": channel,
                "date": series.index[-1],
                "latest": round(float(latest), 3),
                "reference": round(reference, 3),
                "change": round(change, 3),
                "nights": len(history),
            })
    return alerts


class FreshnessTracker:
    def __init__(self, stuck_repeats=STUCK_REPEATS, channels=WATCHED_CHANNELS):
        self.stuck_repeats = stuck_repeats
        self.channels = channels
        self._last = {}
        self._repeats = {}

    def check(self, row):
        issues = []
        for channel in self.channels:
            if channel not in row:
                continue
            value = row[channel]
            if channel in self._last and value == self._last[channel]:
                self._repeats[channel] = self._repeats.get(channel, 0) + 1
            else:
                if self._repeats.get(channel, 0) >= self.stuck_repeats:
                    issues.append((channel, "recovered"))
                self._repeats[channel] = 0
            self._last[channel] = value
            if self._repeats[channel] == self.stuck_repeats:
                issues.append((channel, f"stuck at {value} for {self.stuck_repeats + 1} readings"))
        return issues