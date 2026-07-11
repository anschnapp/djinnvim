"""Render pipeline summaries for the console."""

from pipeline import summarize_orders


def render_summary(rows):
    stats = summarize_orders(rows)
    return f"{stats['orders']} orders, {stats['units']} units"


def validate_row(row):
    """Check a single order row for required fields."""
    missing = []
    for field in ("id", "sku", "qty"):
        if not row.get(field):
            missing.append(field)

    if missing:
        return False, missing
    return True, []


def render_failures(failures):
    lines = []
    for row_id, missing in failures:
        lines.append(f"row {row_id}: missing {', '.join(missing)}")
    return "\n".join(lines)
