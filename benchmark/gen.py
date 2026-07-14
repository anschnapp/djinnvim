"""Generate benchmark documents: a start file, its exact target file, and the
task prompt. Generation and transformation come from the same seeded block
list, so correctness is a mechanical diff (see design.md, Benchmark v1).

Usage (eyeballing): python benchmark/gen.py rename 500 --seed 1 --out /tmp/x
"""

import argparse
import random
import re
from dataclasses import dataclass
from pathlib import Path

VERBS = ["merge", "filter", "collect", "resolve", "index", "trim", "group",
         "expand", "flatten", "score", "rank", "split", "pack", "audit",
         "sample", "rotate", "digest", "align", "probe", "stitch"]
NOUNS = ["items", "orders", "users", "events", "batches", "labels", "totals",
         "fields", "chunks", "groups", "paths", "frames", "queues", "tokens",
         "slots", "pages", "rows_", "keys_", "spans", "cells"]
KEYS = ["status", "kind", "owner", "region", "level", "stage", "source"]
WORDS = ["alpha", "beta", "gamma", "delta", "omega", "sigma", "theta"]

# Numeric literals used in filler bodies. 30 and 90 are excluded so the
# bump-default task's decoys stay under our control.
SAFE_NUMS = [7, 12, 17, 25, 42, 55, 64, 81, 120, 250]

FILENAME = "pipeline.py"


@dataclass
class Doc:
    filename: str
    start: str
    target: str
    prompt: str


def _header() -> list[str]:
    return [
        '"""Data pipeline helpers (generated benchmark document)."""',
        "",
        "import json",
        "import time",
        "",
        "BATCH_SIZE = 25",
        "MAX_RETRIES = 5",
    ]


def _name(rng: random.Random, used: set[str]) -> str:
    n = f"{rng.choice(VERBS)}_{rng.choice(NOUNS)}".rstrip("_")
    while n in used:  # combos exhaust around 400 fillers; suffix from there
        n = f"{n}_{rng.randrange(2, 100)}"
    used.add(n)
    return n


def _filler(rng: random.Random, used: set[str]) -> list[str]:
    name = _name(rng, used)
    key = rng.choice(KEYS)
    word = rng.choice(WORDS)
    n = rng.choice(SAFE_NUMS)
    template = rng.randrange(3)
    if template == 0:
        return [
            f"def {name}(items):",
            "    result = []",
            "    for item in items:",
            f"        if item.get('{key}'):",
            f"            result.append(item['{key}'])",
            "    return result",
        ]
    if template == 1:
        return [
            f"def {name}(value, scale):",
            "    total = value * scale",
            f"    if total > {n}:",
            f"        return {{'state': 'high', 'total': total}}",
            f"    return {{'state': 'low', 'total': total}}",
        ]
    return [
        f"def {name}(name, count):",
        f"    label = '{word}-' + name",
        f"    return f'{{label}}: {{count}}'",
    ]


def _assemble(chunks: list[list[str]]) -> str:
    parts = ["\n".join(c) for c in chunks]
    return "\n\n\n".join(parts) + "\n"


def _scale(size: int) -> int:
    """How many scattered task sites (call sites, debug lines) for a size."""
    return max(3, size // 80)


def _build(rng: random.Random, size: int, core: list[list[str]],
           scattered: list[list[str]]) -> list[list[str]]:
    """header + core defs up front, then fillers with the scattered task
    chunks mixed in at seeded positions, until ~size lines."""
    used: set[str] = set()
    chunks = [_header()] + core
    lines = sum(len(c) + 2 for c in chunks)
    body: list[list[str]] = list(scattered)
    while lines + sum(len(c) + 2 for c in body) < size:
        body.append(_filler(rng, used))
    rng.shuffle(body)
    return chunks + body


# --- tasks -----------------------------------------------------------------

def gen_rename(rng: random.Random, size: int) -> Doc:
    core = [
        [
            "def fetch_records(db, limit):",
            "    cursor = db.execute('SELECT * FROM records LIMIT ?', (limit,))",
            "    return cursor.fetchall()",
        ],
        [
            "_CACHE = {}",
            "",
            "",
            "def fetch_records_cached(db, limit):",
            "    if limit not in _CACHE:",
            "        _CACHE[limit] = fetch_records(db, limit)",
            "    return _CACHE[limit]",
        ],
    ]
    used: set[str] = set()
    scattered = []
    for i in range(_scale(size)):
        name = _name(rng, used)
        callee = "fetch_records_cached" if i % 3 == 2 else "fetch_records"
        scattered.append([
            f"def {name}(db):",
            f"    rows = {callee}(db, {rng.choice(SAFE_NUMS)})",
            "    return [row for row in rows if row]",
        ])
    chunks = _build(rng, size, core, scattered)
    start = _assemble(chunks)
    target = re.sub(r"\bfetch_records\b", "load_records", start)
    prompt = (
        f"In {FILENAME}, rename the function fetch_records to load_records "
        "everywhere it appears (its definition and every call site). Do NOT "
        "touch fetch_records_cached — that is a different function and must "
        "keep its name (though calls to fetch_records inside it must be "
        "renamed like any other call site)."
    )
    return Doc(FILENAME, start, target, prompt)


def gen_delete_debug(rng: random.Random, size: int) -> Doc:
    core = [
        [
            "def log_debug(msg):",
            "    print(f'DEBUG: {msg}')",
        ],
    ]
    used: set[str] = set()
    scattered = []
    for _ in range(_scale(size)):
        name = _name(rng, used)
        key = rng.choice(KEYS)
        scattered.append([
            f"def {name}(payload):",
            f"    log_debug('enter {name}')",
            f"    checked = payload.get('{key}', 0)",
            f"    return checked + {rng.choice(SAFE_NUMS)}",
        ])
    chunks = _build(rng, size, core, scattered)
    start = _assemble(chunks)
    target_lines = [l for l in start.split("\n") if "log_debug(" not in l
                    or l.startswith("def log_debug") or "print(" in l]
    target = "\n".join(target_lines)
    prompt = (
        f"In {FILENAME}, delete every line that calls log_debug. Keep the "
        "log_debug function definition itself. Change nothing else."
    )
    return Doc(FILENAME, start, target, prompt)


def gen_bump_default(rng: random.Random, size: int) -> Doc:
    core = [
        ["POLL_INTERVAL = 30"],
        [
            "def send_request(url, timeout=30, retries=3):",
            "    for attempt in range(retries):",
            "        response = _http_get(url, timeout)",
            "        if response is not None:",
            "            return response",
            "        time.sleep(1)",
            "    return None",
        ],
        [
            "def warm_cache(db):",
            "    for shard in range(30):",
            "        db.touch(shard)",
        ],
    ]
    chunks = _build(rng, size, core, [])
    start = _assemble(chunks)
    target = start.replace("def send_request(url, timeout=30, retries=3):",
                           "def send_request(url, timeout=90, retries=3):")
    prompt = (
        f"In {FILENAME}, the function send_request has a keyword default "
        "timeout=30. Change that default to 90. Change nothing else — other "
        "occurrences of 30 in the file are unrelated and must stay."
    )
    return Doc(FILENAME, start, target, prompt)


def gen_quote_style(rng: random.Random, size: int) -> Doc:
    chunks = _build(rng, size, [], [])
    start = _assemble(chunks)
    target = re.sub(r"'([^']*)'", r'"\1"', start)
    prompt = (
        f"In {FILENAME}, convert every single-quoted string literal to "
        "double quotes. The docstring already uses double quotes; change "
        "nothing else."
    )
    return Doc(FILENAME, start, target, prompt)


def gen_move_func(rng: random.Random, size: int) -> Doc:
    validate = [
        "def validate_row(row):",
        "    if not row:",
        "        return False",
        "    required = ['id', 'name', 'total']",
        "",
        "    for key in required:",
        "        if key not in row:",
        "            return False",
        "    return True",
    ]
    write_out = [
        "def write_output(path, rows):",
        "    valid = [row for row in rows if validate_row(row)]",
        "    with open(path, 'w') as fh:",
        "        json.dump(valid, fh, indent=2)",
        "    return len(valid)",
    ]
    used: set[str] = set()
    fillers: list[list[str]] = []
    lines = len(_header()) + len(validate) + len(write_out) + 6
    while lines < size:
        f = _filler(rng, used)
        fillers.append(f)
        lines += len(f) + 2
    # validate_row at ~25%, write_output at ~75% of the filler sequence
    i = max(1, len(fillers) // 4)
    j = max(i + 1, (3 * len(fillers)) // 4)
    body = fillers[:i] + [validate] + fillers[i:j] + [write_out] + fillers[j:]
    start = _assemble([_header()] + body)
    tbody = fillers[:i] + fillers[i:j] + [validate, write_out] + fillers[j:]
    target = _assemble([_header()] + tbody)
    prompt = (
        f"In {FILENAME}, move the function validate_row so that it sits "
        "directly above write_output. Keep exactly two blank lines between "
        "top-level functions and change nothing else."
    )
    return Doc(FILENAME, start, target, prompt)


# --- round 2: trap variants -------------------------------------------------
# Same decoys (or sharper ones), but natural prompts with no decoy warnings:
# the correct interpretation is still unambiguous, a naive regex silently
# corrupts. The metric these target is silent-error rate, not tokens.

def gen_rename_trap(rng: random.Random, size: int) -> Doc:
    doc = gen_rename(rng, size)
    prompt = (
        f"In {FILENAME}, rename the function fetch_records to load_records — "
        "its definition and all its call sites."
    )
    return Doc(FILENAME, doc.start, doc.target, prompt)


def gen_bump_trap(rng: random.Random, size: int) -> Doc:
    core = [
        ["POLL_INTERVAL = 30"],
        [
            "def send_request(url, timeout=30, retries=3):",
            "    for attempt in range(retries):",
            "        response = _http_get(url, timeout)",
            "        if response is not None:",
            "            return response",
            "        time.sleep(1)",
            "    return None",
        ],
    ]
    used: set[str] = set()
    scattered = []
    for i in range(_scale(size)):
        name = _name(rng, used)
        # explicit timeout=30 at call sites is a deliberate choice by the
        # caller and must survive a change of the *default*
        call = ("send_request(url, timeout=30)" if i % 2 == 0
                else "send_request(url)")
        scattered.append([
            f"def {name}(url):",
            f"    return {call}",
        ])
    chunks = _build(rng, size, core, scattered)
    start = _assemble(chunks)
    target = start.replace("def send_request(url, timeout=30, retries=3):",
                           "def send_request(url, timeout=90, retries=3):")
    prompt = (
        f"In {FILENAME}, the default timeout of send_request is too low: "
        "change it from 30 to 90."
    )
    return Doc(FILENAME, start, target, prompt)


def gen_delete_trap(rng: random.Random, size: int) -> Doc:
    core = [
        [
            "def log_debug(msg):",
            "    print(f'DEBUG: {msg}')",
        ],
        [
            "def log_debug_summary(stats):",
            "    return ', '.join(f'{k}={v}' for k, v in stats.items())",
        ],
    ]
    used: set[str] = set()
    scattered = []
    for i in range(_scale(size)):
        name = _name(rng, used)
        key = rng.choice(KEYS)
        if i % 3 == 2:
            scattered.append([
                f"def {name}(stats):",
                "    summary = log_debug_summary(stats)",
                f"    return '{rng.choice(WORDS)}: ' + summary",
            ])
        else:
            scattered.append([
                f"def {name}(payload):",
                f"    log_debug('enter {name}')",
                f"    checked = payload.get('{key}', 0)",
                f"    return checked + {rng.choice(SAFE_NUMS)}",
            ])
    chunks = _build(rng, size, core, scattered)
    start = _assemble(chunks)
    target = "\n".join(l for l in start.split("\n")
                       if "log_debug(" not in l or l.startswith("def "))
    prompt = (
        f"Remove all the log_debug calls from {FILENAME} (keep the "
        "log_debug function definition itself)."
    )
    return Doc(FILENAME, start, target, prompt)


APOS_COMMENTS = ["    # don't rescale here",
                 "    # this isn't the hot path",
                 "    # note: caller's dict is not copied"]


def gen_quote_trap(rng: random.Random, size: int) -> Doc:
    used: set[str] = set()
    chunks = [_header()]
    lines = sum(len(c) + 2 for c in chunks)
    while lines < size:
        f = _filler(rng, used)
        if rng.random() < 0.3:
            f = [f[0], rng.choice(APOS_COMMENTS)] + f[1:]
        chunks.append(f)
        lines += len(f) + 2
    start = _assemble(chunks)
    target = "\n".join(
        l if l.lstrip().startswith("#") else re.sub(r"'([^']*)'", r'"\1"', l)
        for l in start.split("\n"))
    prompt = (
        f"In {FILENAME}, convert every single-quoted string literal to "
        "double quotes."
    )
    return Doc(FILENAME, start, target, prompt)


# --- round 2: composite (dogfood-shaped) ------------------------------------

def gen_composite(rng: random.Random, size: int) -> Doc:
    header_s = _header() + ["DEFAULT_REGION = 'eu-west'"]
    header_t = [l for l in header_s]
    header_t.insert(header_t.index("MAX_RETRIES = 5") + 1,
                    "RETRY_BACKOFF = 2.5")
    header_t[header_t.index("DEFAULT_REGION = 'eu-west'")] = \
        "DEFAULT_REGION = 'us-east'"

    def ren(chunk: list[str]) -> list[str]:
        return [re.sub(r"\bfetch_records\b", "load_records", l)
                for l in chunk]

    pairs: list[tuple[list[str], list[str]]] = []
    fetch = ["def fetch_records(db, limit):",
             "    cursor = db.execute('SELECT * FROM records LIMIT ?', (limit,))",
             "    return cursor.fetchall()"]
    cached = ["_CACHE = {}", "", "",
              "def fetch_records_cached(db, limit):",
              "    if limit not in _CACHE:",
              "        _CACHE[limit] = fetch_records(db, limit)",
              "    return _CACHE[limit]"]
    poll_s = ["def poll_status(job, interval=30):",
              "    while not job.done():",
              "        time.sleep(interval)",
              "    return job.result()"]
    send_s = ["def send_request(url, timeout=30):",
              "    return _http_get(url, timeout)"]
    send_t = ["def send_request(url, logger, timeout=30):",
              "    return _http_get(url, timeout)"]
    logdef = ["def log_debug(msg):", "    print(f'DEBUG: {msg}')"]
    pairs += [(fetch, ren(fetch)), (cached, ren(cached)),
              (poll_s, [poll_s[0].replace("interval=30", "interval=90")]
               + poll_s[1:]),
              (send_s, send_t), (logdef, logdef)]

    used: set[str] = set()
    n = max(2, size // 150)
    for i in range(n):  # rename call sites (every 3rd via the decoy)
        name = _name(rng, used)
        callee = "fetch_records_cached" if i % 3 == 2 else "fetch_records"
        c = [f"def {name}(db):",
             f"    rows = {callee}(db, {rng.choice(SAFE_NUMS)})",
             "    return [row for row in rows if row]"]
        pairs.append((c, ren(c)))
    for _ in range(n):  # debug call sites
        name = _name(rng, used)
        key = rng.choice(KEYS)
        s = [f"def {name}(payload):",
             f"    log_debug('enter {name}')",
             f"    checked = payload.get('{key}', 0)",
             f"    return checked + {rng.choice(SAFE_NUMS)}"]
        pairs.append((s, [s[0]] + s[2:]))
    for _ in range(n):  # single-line send_request call sites
        name = _name(rng, used)
        s = [f"def {name}(endpoint, logger):",
             "    return send_request(endpoint)"]
        pairs.append((s, [s[0], "    return send_request(endpoint, logger)"]))
    for _ in range(n):  # multi-line send_request call sites (break sed)
        name = _name(rng, used)
        s = [f"def {name}(endpoint, logger):",
             "    response = send_request(",
             "        endpoint,",
             f"        timeout={rng.choice(SAFE_NUMS)},",
             "    )",
             "    return response"]
        pairs.append((s, s[:3] + ["        logger,"] + s[3:]))

    lines = len(header_s) + 2 + sum(len(s) + 2 for s, _ in pairs)
    while lines < size:
        f = _filler(rng, used)
        pairs.append((f, f))
        lines += len(f) + 2
    rng.shuffle(pairs)
    start = _assemble([header_s] + [s for s, _ in pairs])
    target = _assemble([header_t] + [t for _, t in pairs])
    prompt = (
        f"Apply these changes to {FILENAME}:\n"
        "1. Rename the function fetch_records to load_records (its "
        "definition and all call sites; fetch_records_cached is a separate "
        "function).\n"
        "2. Change poll_status's default interval from 30 to 90.\n"
        "3. Remove all log_debug calls (keep the definition).\n"
        "4. Change DEFAULT_REGION from 'eu-west' to 'us-east' (keep single "
        "quotes).\n"
        "5. Add a constant RETRY_BACKOFF = 2.5 on its own line directly "
        "below MAX_RETRIES.\n"
        "6. send_request now takes a logger as its second parameter: update "
        "its definition, and at every call site pass the logger variable "
        "(already in scope) as the second argument."
    )
    return Doc(FILENAME, start, target, prompt)


# --- round 2: multi-move ----------------------------------------------------

def gen_move_multi(rng: random.Random, size: int) -> Doc:
    def check(name: str, field: str) -> list[str]:
        return [f"def check_{name}(rows):",
                "    for row in rows:",
                f"        if not row.get('{field}'):",
                "            return False",
                "    return True"]

    ids, totals, names = check("ids", "id"), check("totals", "total"), \
        check("names", "name")
    run = ["def run_checks(rows):",
           "    return check_ids(rows) and check_totals(rows) "
           "and check_names(rows)"]

    used: set[str] = set()
    fillers: list[list[str]] = []
    lines = len(_header()) + 5 * 3 + len(run) + 10
    while lines < size:
        f = _filler(rng, used)
        fillers.append(f)
        lines += len(f) + 2
    k = len(fillers)
    i, j, m, r = max(1, k // 5), max(2, (2 * k) // 5), max(3, (3 * k) // 5), \
        max(4, (4 * k) // 5)
    body = (fillers[:i] + [names] + fillers[i:j] + [ids] + fillers[j:m]
            + [totals] + fillers[m:r] + [run] + fillers[r:])
    tbody = fillers[:r] + [ids, totals, names, run] + fillers[r:]
    start = _assemble([_header()] + body)
    target = _assemble([_header()] + tbody)
    prompt = (
        f"In {FILENAME}, the three check_* functions are scattered through "
        "the file. Move them so they sit directly above run_checks, in this "
        "order: check_ids, check_totals, check_names. Keep exactly two "
        "blank lines between top-level functions and change nothing else."
    )
    return Doc(FILENAME, start, target, prompt)


# --- round 3: purge marked blocks (batch-structural, regex-hostile) ---------
# High-K structural edit with no one-regex answer: variable-length multi-line
# blocks. `sed '/DEPRECATED/,/^$/d'` leaves a blank-line miscount (silent
# corruption); the honest baseline answer is awk paragraph mode or a script.
# Keyhole: `at each /# DEPRECATED/ dap` (batch) or the same anchored edit
# reissued per block (iterated) — the task lets both forms compete.

def gen_purge_blocks(rng: random.Random, size: int) -> Doc:
    used: set[str] = set()
    doomed: list[list[str]] = []
    for _ in range(_scale(size)):
        body = _filler(rng, used)
        alt = _name(rng, used)
        doomed.append([f"# DEPRECATED: use {alt} instead"] + body)

    body_chunks: list[tuple[list[str], bool]] = [(c, False) for c in doomed]
    lines = len(_header()) + 2
    while lines + sum(len(c) + 2 for c, _ in body_chunks) < size:
        body_chunks.append((_filler(rng, used), True))
    rng.shuffle(body_chunks)
    chunks = [(_header(), True)] + body_chunks
    start = _assemble([c for c, _ in chunks])
    target = _assemble([c for c, keep in chunks if keep])
    prompt = (
        f"In {FILENAME}, several functions are marked deprecated with a "
        "`# DEPRECATED: ...` comment on the line directly above their def. "
        "Remove every deprecated function entirely — the comment line and "
        "the whole function below it. Keep exactly two blank lines between "
        "the remaining top-level definitions."
    )
    return Doc(FILENAME, start, target, prompt)


TASKS = {
    "rename": gen_rename,
    "delete-debug": gen_delete_debug,
    "bump-default": gen_bump_default,
    "quote-style": gen_quote_style,
    "move-func": gen_move_func,
    "rename-trap": gen_rename_trap,
    "bump-trap": gen_bump_trap,
    "delete-trap": gen_delete_trap,
    "quote-trap": gen_quote_trap,
    "composite": gen_composite,
    "move-multi": gen_move_multi,
    "purge-blocks": gen_purge_blocks,
}


def generate(task: str, size: int, seed: int) -> Doc:
    rng = random.Random(f"{task}:{size}:{seed}")
    return TASKS[task](rng, size)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("task", choices=TASKS)
    ap.add_argument("size", type=int)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    doc = generate(args.task, args.size, args.seed)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / doc.filename).write_text(doc.start)
        (args.out / ("target_" + doc.filename)).write_text(doc.target)
        print(f"wrote {args.out}/{doc.filename} "
              f"({len(doc.start.splitlines())} lines) + target")
    else:
        print(doc.start, end="")
    print(f"--- prompt ---\n{doc.prompt}")


if __name__ == "__main__":
    main()
