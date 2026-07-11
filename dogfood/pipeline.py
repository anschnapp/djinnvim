"""Order pipeline: load, validate, transform, and summarize order rows."""

import csv

BATCH_SIZE = 100
DEFAULT_STATUS = "pending"


def load_orders(path):
    rows = []
    with open(path) as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(row)
    return rows


def normalize_status(row):
    status = row.get("status") or DEFAULT_STATUS
    row["status"] = status.strip().lower()
    return row


def batch(rows):
    chunks = []
    for i in range(0, len(rows), BATCH_SIZE):
        chunks.append(rows[i : i + BATCH_SIZE])
    return chunks


def apply_discounts(rows):
    for row in rows:
        qty = int(row["qty"])
        if qty >= 10:
            row["discount"] = 0.15
        elif qty >= 5:
            row["discount"] = 0.05
        else:
            row["discount"] = 0.0
    return rows


def summarize_orders(rows):
    total = 0
    for row in rows:
        total += int(row["qty"])
    return {"orders": len(rows), "units": total}
