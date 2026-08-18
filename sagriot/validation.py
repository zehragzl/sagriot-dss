PLAUSIBLE = {
    "air_temp":     (5.0, 50.0),
    "air_humidity": (0.0, 100.0),
    "co2":          (300.0, 5000.0),
    "par":          (0.0, 2500.0),
    "soil_fc":      (0.0, 100.0),
    "soil_temp":    (0.0, 50.0),
    "ec":           (0.0, 10.0),
}

STUCK_REPEATS = 12
MAX_AGE_SECONDS = 900


def validate(row):
    clean, issues = {}, []
    for channel, value in row.items():
        if channel not in PLAUSIBLE:
            clean[channel] = value
            continue
        if value is None:
            issues.append((channel, "missing"))
            continue
        low, high = PLAUSIBLE[channel]
        if not (low <= value <= high):
            issues.append((channel, f"out of range: {value} (expected {low}-{high})"))
            continue
        clean[channel] = value
    return clean, issues


class FreshnessTracker:
    def __init__(self, stuck_repeats=STUCK_REPEATS, max_age_seconds=MAX_AGE_SECONDS):
        self.stuck_repeats = stuck_repeats
        self.max_age_seconds = max_age_seconds
        self._last_value = {}
        self._repeats = {}
        self._last_seen = {}

    def check(self, row, timestamp):
        issues = []
        for channel, value in row.items():
            if channel in self._last_value and value == self._last_value[channel]:
                self._repeats[channel] = self._repeats.get(channel, 0) + 1
            else:
                self._repeats[channel] = 0
            self._last_value[channel] = value
            self._last_seen[channel] = timestamp
            if self._repeats[channel] >= self.stuck_repeats:
                issues.append((channel, f"stuck: same value {value} for {self._repeats[channel] + 1} readings"))
        for channel, seen in self._last_seen.items():
            if channel not in row:
                age = (timestamp - seen).total_seconds()
                if age > self.max_age_seconds:
                    issues.append((channel, f"stale: no reading for {int(age)} s"))
        return issues