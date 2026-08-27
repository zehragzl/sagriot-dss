import csv
import os
from datetime import datetime

COLUMNS = ["timestamp", "air_temp", "air_humidity", "co2", "pressure",
           "lux", "par", "soil_temp", "soil_vwc", "soil_fc", "ec"]


ADVICE_COLUMNS = ["timestamp", "kind", "rule", "status", "action",
                  "when_minutes", "lead_minutes", "advise_now",
                  "earliest_minutes", "latest_minutes", "probability", "scenarios"]


def _prepare(path, columns):
    """Make sure the file is ready to receive a row, and say whether it is new.

    If an existing file was written with a different set of columns, appending
    to it would silently misalign every field from that point on. The old file
    is set aside with a timestamp instead, and a fresh one is started.
    """
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)

    if not os.path.exists(path):
        return True

    with open(path, newline="") as handle:
        header = next(csv.reader(handle), None)

    if header is None:
        return True
    if header != columns:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        archived = f"{os.path.splitext(path)[0]}_{stamp}.csv"
        os.rename(path, archived)
        print(f"  [store] {os.path.basename(path)}: columns changed, "
              f"previous file kept as {os.path.basename(archived)}")
        return True
    return False


def append_advice(path, timestamp, kind, item):
    is_new = _prepare(path, ADVICE_COLUMNS)
    with open(path, "a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=ADVICE_COLUMNS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        record = {"timestamp": timestamp.isoformat(), "kind": kind}
        record.update(item)
        writer.writerow(record)


def append_row(path, timestamp, row):
    is_new = _prepare(path, COLUMNS)
    with open(path, "a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS, extrasaction="ignore")
        if is_new:
            writer.writeheader()
        record = {"timestamp": timestamp.isoformat()}
        record.update(row)
        writer.writerow(record)
