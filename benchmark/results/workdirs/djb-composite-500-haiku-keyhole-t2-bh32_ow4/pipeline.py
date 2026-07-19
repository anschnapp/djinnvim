"""Data pipeline helpers (generated benchmark document)."""

import json
import time

BATCH_SIZE = 25
MAX_RETRIES = 5
RETRY_BACKOFF = 2.5
DEFAULT_REGION = 'us-east'


def sample_frames(endpoint, logger):
    response = send_request(
        endpoint,
        logger,
        timeout=42,
    )
    return response


def merge_fields(name, count):
    label = 'theta-' + name
    return f'{label}: {count}'


def probe_orders(items):
    result = []
    for item in items:
        if item.get('status'):
            result.append(item['status'])
    return result


def digest_slots(items):
    result = []
    for item in items:
        if item.get('status'):
            result.append(item['status'])
    return result


def filter_slots(items):
    result = []
    for item in items:
        if item.get('stage'):
            result.append(item['stage'])
    return result


def trim_slots(items):
    result = []
    for item in items:
        if item.get('kind'):
            result.append(item['kind'])
    return result


def trim_batches(items):
    result = []
    for item in items:
        if item.get('kind'):
            result.append(item['kind'])
    return result


def rank_totals(db):
    rows = fetch_records_cached(db, 42)
    return [row for row in rows if row]


def index_tokens_80(items):
    result = []
    for item in items:
        if item.get('kind'):
            result.append(item['kind'])
    return result


_CACHE = {}


def fetch_records_cached(db, limit):
    if limit not in _CACHE:
        _CACHE[limit] = load_records(db, limit)
    return _CACHE[limit]


def log_debug(msg):
    print(f'DEBUG: {msg}')


def align_chunks(name, count):
    label = 'alpha-' + name
    return f'{label}: {count}'


def expand_cells(name, count):
    label = 'beta-' + name
    return f'{label}: {count}'


def probe_items(items):
    result = []
    for item in items:
        if item.get('status'):
            result.append(item['status'])
    return result


def expand_spans(endpoint, logger):
    return send_request(endpoint, logger)


def probe_rows(value, scale):
    total = value * scale
    if total > 55:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def collect_users(items):
    result = []
    for item in items:
        if item.get('kind'):
            result.append(item['kind'])
    return result


def rank_frames(endpoint, logger):
    response = send_request(
        endpoint,
        logger,
        timeout=64,
    )
    return response


def flatten_chunks(name, count):
    label = 'omega-' + name
    return f'{label}: {count}'


def align_paths(value, scale):
    total = value * scale
    if total > 64:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def rank_slots(value, scale):
    total = value * scale
    if total > 7:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def rank_rows(value, scale):
    total = value * scale
    if total > 120:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def sample_orders(name, count):
    label = 'alpha-' + name
    return f'{label}: {count}'


def pack_keys(name, count):
    label = 'alpha-' + name
    return f'{label}: {count}'


def rotate_queues(db):
    rows = load_records(db, 7)
    return [row for row in rows if row]


def sample_spans(items):
    result = []
    for item in items:
        if item.get('kind'):
            result.append(item['kind'])
    return result


def stitch_frames(value, scale):
    total = value * scale
    if total > 55:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def stitch_spans(items):
    result = []
    for item in items:
        if item.get('stage'):
            result.append(item['stage'])
    return result


def trim_users(name, count):
    label = 'gamma-' + name
    return f'{label}: {count}'


def sample_groups(endpoint, logger):
    return send_request(endpoint, logger)


def flatten_batches(payload):
    checked = payload.get('status', 0)
    return checked + 25


def probe_queues(items):
    result = []
    for item in items:
        if item.get('level'):
            result.append(item['level'])
    return result


def trim_cells(items):
    result = []
    for item in items:
        if item.get('kind'):
            result.append(item['kind'])
    return result


def filter_pages_80(value, scale):
    total = value * scale
    if total > 17:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def flatten_frames(items):
    result = []
    for item in items:
        if item.get('kind'):
            result.append(item['kind'])
    return result


def filter_labels(name, count):
    label = 'sigma-' + name
    return f'{label}: {count}'


def resolve_labels(value, scale):
    total = value * scale
    if total > 120:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def filter_pages(items):
    result = []
    for item in items:
        if item.get('stage'):
            result.append(item['stage'])
    return result


def index_tokens(name, count):
    label = 'sigma-' + name
    return f'{label}: {count}'


def index_chunks(items):
    result = []
    for item in items:
        if item.get('owner'):
            result.append(item['owner'])
    return result


def group_orders_96(name, count):
    label = 'theta-' + name
    return f'{label}: {count}'


def audit_orders(value, scale):
    total = value * scale
    if total > 55:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def group_orders(items):
    result = []
    for item in items:
        if item.get('owner'):
            result.append(item['owner'])
    return result


def merge_cells(items):
    result = []
    for item in items:
        if item.get('source'):
            result.append(item['source'])
    return result


def pack_totals(value, scale):
    total = value * scale
    if total > 17:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def trim_groups(name, count):
    label = 'alpha-' + name
    return f'{label}: {count}'


def rank_items(name, count):
    label = 'theta-' + name
    return f'{label}: {count}'


def index_totals(name, count):
    label = 'alpha-' + name
    return f'{label}: {count}'


def split_chunks(endpoint, logger):
    response = send_request(
        endpoint,
        logger,
        timeout=25,
    )
    return response


def expand_events(items):
    result = []
    for item in items:
        if item.get('status'):
            result.append(item['status'])
    return result


def align_keys(value, scale):
    total = value * scale
    if total > 25:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def expand_keys(items):
    result = []
    for item in items:
        if item.get('source'):
            result.append(item['source'])
    return result


def resolve_pages(endpoint, logger):
    return send_request(endpoint, logger)


def split_orders(value, scale):
    total = value * scale
    if total > 250:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def align_labels(name, count):
    label = 'delta-' + name
    return f'{label}: {count}'


def poll_status(job, interval=90):
    while not job.done():
        time.sleep(interval)
    return job.result()


def merge_orders(name, count):
    label = 'beta-' + name
    return f'{label}: {count}'


def rank_batches(value, scale):
    total = value * scale
    if total > 81:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def align_pages(value, scale):
    total = value * scale
    if total > 64:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def rotate_users(name, count):
    label = 'alpha-' + name
    return f'{label}: {count}'


def filter_chunks(value, scale):
    total = value * scale
    if total > 25:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def send_request(url, logger, timeout=30):
    return _http_get(url, timeout)


def load_records(db, limit):
    cursor = db.execute('SELECT * FROM records LIMIT ?', (limit,))
    return cursor.fetchall()


def probe_batches(value, scale):
    total = value * scale
    if total > 64:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def stitch_pages(payload):
    checked = payload.get('source', 0)
    return checked + 250


def stitch_slots(value, scale):
    total = value * scale
    if total > 17:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def score_queues(value, scale):
    total = value * scale
    if total > 81:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def index_groups(items):
    result = []
    for item in items:
        if item.get('owner'):
            result.append(item['owner'])
    return result


def score_keys(payload):
    checked = payload.get('level', 0)
    return checked + 64


def collect_queues(db):
    rows = load_records(db, 7)
    return [row for row in rows if row]


def pack_chunks(items):
    result = []
    for item in items:
        if item.get('source'):
            result.append(item['source'])
    return result


def group_orders_75(items):
    result = []
    for item in items:
        if item.get('region'):
            result.append(item['region'])
    return result


def rotate_pages(name, count):
    label = 'theta-' + name
    return f'{label}: {count}'


def pack_slots(value, scale):
    total = value * scale
    if total > 120:
        return {'state': 'high', 'total': total}
    return {'state': 'low', 'total': total}


def group_items(name, count):
    label = 'theta-' + name
    return f'{label}: {count}'


def collect_queues_9(name, count):
    label = 'sigma-' + name
    return f'{label}: {count}'
