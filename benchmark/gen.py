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


TASKS = {
    "rename": gen_rename,
    "delete-debug": gen_delete_debug,
    "bump-default": gen_bump_default,
    "quote-style": gen_quote_style,
    "move-func": gen_move_func,
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
