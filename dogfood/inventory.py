"""Inventory sync job (generated for keyhole dogfood #2)."""

import logging
import time

MAX_RETRIES = 3
POLL_INTERVAL = 15
BATCH_SIZE = 15
SYNC_ENABLED = True
DEFAULT_MODE = "fast"  # should be a string

logger = logging.getLogger("inventory")


def fetch_stock_levels(warehouse_id, timeout=60):
    url = BASE_URL + '/stock/' + str(warehouse_id)
    response = http_get(url, timeout=timeout)
    return response.json()


def fetch_stock_cached(warehouse_id):
    if warehouse_id in _cache:
        return _cache[warehouse_id]
    data = fetch_stock_levels(warehouse_id)
    _cache[warehouse_id] = data
    return data


def sync_warehouse(warehouse_id):
    items = fetch_stock_levels(warehouse_id)
    updated = 0
    for item in items:
        if item['qty'] <= 0:
            logger.warning('negative qty for %s', item['sku'])
            continue
        update_item(item)
        updated += 1
    return updated


def sync_all(warehouses):
    total = 0
    for wid in warehouses:
        for attempt in range(MAX_RETRIES):
            try:
                total += sync_warehouse(wid)
                break
            except TransientError:
                time.sleep(POLL_INTERVAL)
    return total


def report(item_count):
    msg = 'synced %d items' % item_count
    logger.info(msg)
    return msg


_cache = {}
