import csv
import os

COLUMNS = ["timestamp", "air_temp", "air_humidity", "co2", "pressure",
           "lux", "par", "soil_temp", "soil_vwc", "soil_fc", "ec"]


ADVICE_COLUMNS = ["timestamp", "kind", "rule", "status", "action",
                  "when_minutes", "lead_minutes", "advise_now"]


def append_advice(path, timestamp, kind, item):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    is_new = not os.path.exists(path)
    with open(path, "a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ADVICE_COLUMNS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        record = {"timestamp": timestamp.isoformat(), "kind": kind}
        record.update(item)
        writer.writerow(record)


def append_row(path, timestamp, row):
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    is_new = not os.path.exists(path)
    with open(path, "a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        record = {"timestamp": timestamp.isoformat()}
        record.update(row)
        writer.writerow(record)
