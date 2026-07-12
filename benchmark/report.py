"""Aggregate benchmark results.jsonl into per-cell tables.

Usage: python benchmark/report.py [results.jsonl]
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

RESULTS_DEFAULT = Path(__file__).resolve().parent / "results" / "results.jsonl"

ABORT_MARKERS = ("session limit", "usage limit")


def iter_records(path: Path):
    """Yield result records; tolerant of records glued onto one line and of
    truncated/corrupt lines (skips to the next line)."""
    dec = json.JSONDecoder()
    text = path.read_text()
    i, n = 0, len(text)
    while i < n:
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n:
            break
        try:
            obj, i = dec.raw_decode(text, i)
        except json.JSONDecodeError:
            nl = text.find("\n", i)
            i = n if nl == -1 else nl + 1
            continue
        yield obj


def is_aborted(r: dict) -> bool:
    """Environment failure (session/usage limit, timeout, crash) rather than
    an agent outcome — excluded from aggregates, rerun on resume."""
    if r.get("aborted"):
        return True
    if r.get("subtype") != "success":
        return True
    result = (r.get("agent_result") or "").lower()
    return any(m in result for m in ABORT_MARKERS)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else RESULTS_DEFAULT
    cells = defaultdict(list)
    aborted = []
    for r in iter_records(path):
        if is_aborted(r):
            aborted.append(r)
            continue
        cells[(r["task"], r["size"], r["model"], r["condition"])].append(r)

    hdr = (f"{'task':<14}{'size':>6} {'model':<7}{'cond':<10}"
           f"{'n':>3} {'ok':>5} {'cost$':>7} {'in':>8} {'out':>7} "
           f"{'cache_r':>9} {'calls':>6} {'turns':>6} {'wall_s':>7}")
    print(hdr)
    print("-" * len(hdr))
    for key in sorted(cells):
        rs = cells[key]
        task, size, model, cond = key
        ok = sum(1 for r in rs if r.get("exact_match"))
        print(f"{task:<14}{size:>6} {model:<7}{cond:<10}"
              f"{len(rs):>3} {ok:>2}/{len(rs):<2} "
              f"{mean([r.get('cost_usd') for r in rs]):>7.3f} "
              f"{mean([r.get('input_tokens') for r in rs]):>8.0f} "
              f"{mean([r.get('output_tokens') for r in rs]):>7.0f} "
              f"{mean([r.get('cache_read_tokens') for r in rs]):>9.0f} "
              f"{mean([r.get('tool_calls') for r in rs]):>6.1f} "
              f"{mean([r.get('num_turns') for r in rs]):>6.1f} "
              f"{mean([r.get('wall_s') for r in rs]):>7.1f}")

    # silent errors: wrong result but the run finished "successfully"
    silent = [r for rs in cells.values() for r in rs
              if not r.get("exact_match")]
    if silent:
        print(f"\nsilent errors (finished ok, wrong diff): {len(silent)}")
        for r in silent:
            print(f"  {r['task']} size={r['size']} {r['model']} "
                  f"{r['condition']} trial={r['trial']} -> {r.get('workdir')}")

    if aborted:
        print(f"\naborted trials (excluded from aggregates): {len(aborted)}")
        for r in aborted:
            why = r.get("subtype") or "?"
            hint = (r.get("agent_result") or "")[:60]
            print(f"  {r.get('task')} size={r.get('size')} {r.get('model')} "
                  f"{r.get('condition')} trial={r.get('trial')} "
                  f"[{why}] {hint}")


if __name__ == "__main__":
    main()
