"""Benchmark runner: drives headless Claude Code (`claude -p`) over the
task × size × model × condition grid, one fresh process + fresh workdir per
trial, and appends one JSON line per trial to the results file.

Usage:
  python benchmark/runner.py --tasks rename --sizes 100,500 \
      --models opus,fable --conditions keyhole,baseline --trials 5

Resumable: trials already present in the results file are skipped.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from gen import TASKS, generate

REPO = Path(__file__).resolve().parent.parent
DJINNVIM_BIN = REPO / ".venv" / "bin" / "djinnvim"
RESULTS_DEFAULT = REPO / "benchmark" / "results" / "results.jsonl"

DJINNVIM_TOOLS = ["open", "motion", "edit", "substitute", "matches", "write"]

PREAMBLE_KEYHOLE = (
    "You are editing a file with the djinnvim MCP editor tools (open, "
    "motion, edit, substitute, matches, write). They are your only way to "
    "view or modify files — native file tools are disabled. Work "
    "autonomously; do not ask questions.\n\nTask: "
)
PREAMBLE_BASELINE = (
    "Work autonomously; do not ask questions.\n\nTask: "
)


def build_cmd(condition: str, model: str, prompt: str, workdir: Path,
              budget: float) -> list[str]:
    cmd = ["claude", "-p", prompt,
           "--output-format", "stream-json", "--verbose",
           "--model", model,
           "--max-budget-usd", str(budget),
           "--strict-mcp-config"]
    if condition == "keyhole":
        mcp = {"mcpServers": {"djinnvim": {
            "command": str(DJINNVIM_BIN),
            "env": {"DJINNVIM_ROOT": str(workdir)},
        }}}
        allowed = ",".join(f"mcp__djinnvim__{t}" for t in DJINNVIM_TOOLS)
        cmd += ["--mcp-config", json.dumps(mcp),
                "--allowedTools", allowed,
                "--disallowedTools",
                "Read,Edit,Write,MultiEdit,NotebookEdit,Bash,Grep,Glob,"
                "WebFetch,WebSearch,Task"]
    elif condition == "baseline":
        cmd += ["--permission-mode", "bypassPermissions"]
    else:
        raise ValueError(condition)
    return cmd


def run_trial(task: str, size: int, model: str, condition: str, trial: int,
              budget: float, keep_dirs: Path | None) -> dict:
    doc = generate(task, size, seed=trial)
    base = keep_dirs if keep_dirs else Path(tempfile.gettempdir())
    base.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(
        prefix=f"djb-{task}-{size}-{model}-{condition}-t{trial}-", dir=base))
    (workdir / doc.filename).write_text(doc.start)

    preamble = PREAMBLE_KEYHOLE if condition == "keyhole" else PREAMBLE_BASELINE
    cmd = build_cmd(condition, model, preamble + doc.prompt, workdir, budget)

    t0 = time.time()
    proc = subprocess.run(cmd, cwd=workdir, capture_output=True, text=True,
                          timeout=1800)
    wall = time.time() - t0

    tool_calls: Counter[str] = Counter()
    result_event: dict = {}
    for line in proc.stdout.splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "assistant":
            for block in ev.get("message", {}).get("content", []):
                if block.get("type") == "tool_use":
                    tool_calls[block.get("name", "?")] += 1
        elif ev.get("type") == "result":
            result_event = ev

    final = (workdir / doc.filename).read_text() \
        if (workdir / doc.filename).exists() else None
    exact = final == doc.target
    (workdir / ("target_" + doc.filename)).write_text(doc.target)
    (workdir / "transcript.jsonl").write_text(proc.stdout)

    usage = result_event.get("usage", {})
    record = {
        "task": task, "size": size, "model": model, "condition": condition,
        "trial": trial,
        "exact_match": exact,
        "cost_usd": result_event.get("total_cost_usd"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "cache_read_tokens": usage.get("cache_read_input_tokens"),
        "cache_write_tokens": usage.get("cache_creation_input_tokens"),
        "num_turns": result_event.get("num_turns"),
        "tool_calls": sum(tool_calls.values()),
        "tool_calls_by_name": dict(tool_calls),
        "duration_ms": result_event.get("duration_ms"),
        "wall_s": round(wall, 1),
        "subtype": result_event.get("subtype"),
        "is_error": result_event.get("is_error"),
        "agent_result": (result_event.get("result") or "")[:500],
        "start_lines": doc.start.count("\n"),
        "workdir": str(workdir),
        "exit_code": proc.returncode,
        "stderr": proc.stderr[-500:] if proc.returncode != 0 else "",
    }
    return record


def done_keys(results: Path) -> set[tuple]:
    keys = set()
    if results.exists():
        for line in results.read_text().splitlines():
            try:
                r = json.loads(line)
                keys.add((r["task"], r["size"], r["model"], r["condition"],
                          r["trial"]))
            except (json.JSONDecodeError, KeyError):
                continue
    return keys


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default=",".join(TASKS))
    ap.add_argument("--sizes", default="100,500,2000,10000")
    ap.add_argument("--models", default="opus,fable")
    ap.add_argument("--conditions", default="keyhole,baseline")
    ap.add_argument("--trials", type=int, default=5)
    ap.add_argument("--budget", type=float, default=3.0,
                    help="per-trial --max-budget-usd cap")
    ap.add_argument("--results", type=Path, default=RESULTS_DEFAULT)
    ap.add_argument("--workdirs", type=Path, default=None,
                    help="keep trial workdirs under this dir (default: tmp)")
    args = ap.parse_args()

    tasks = args.tasks.split(",")
    sizes = [int(s) for s in args.sizes.split(",")]
    models = args.models.split(",")
    conditions = args.conditions.split(",")
    args.results.parent.mkdir(parents=True, exist_ok=True)
    done = done_keys(args.results)

    cells = [(t, s, m, c, i) for t in tasks for s in sizes for m in models
             for c in conditions for i in range(args.trials)]
    todo = [k for k in cells if k not in done]
    print(f"{len(cells)} trials in grid, {len(cells) - len(todo)} done, "
          f"{len(todo)} to run")

    for n, (t, s, m, c, i) in enumerate(todo, 1):
        print(f"[{n}/{len(todo)}] {t} size={s} {m} {c} trial={i} ... ",
              end="", flush=True)
        try:
            rec = run_trial(t, s, m, c, i, args.budget, args.workdirs)
        except subprocess.TimeoutExpired:
            rec = {"task": t, "size": s, "model": m, "condition": c,
                   "trial": i, "exact_match": False, "subtype": "timeout"}
        with args.results.open("a") as fh:
            fh.write(json.dumps(rec) + "\n")
        print(f"{'OK' if rec.get('exact_match') else 'MISMATCH'} "
              f"cost=${rec.get('cost_usd') or 0:.2f} "
              f"calls={rec.get('tool_calls')}")


if __name__ == "__main__":
    main()
