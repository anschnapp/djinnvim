# djinnvim - Decision & Dogfood Log

The chronological record: every design decision, reversal, dogfood session
and benchmark round, in the order it happened. Sections are verbatim as
written at the time, so **entries can be superseded by later ones** - a
statement here describes what was true on its date, not necessarily today.

For the current shape of the project, read [design.md](design.md); it is
self-contained and is the document to read before a feature discussion.
This log is for the "why did we decide that" question, and for the
evidence-gate arguments behind parked features.

## v0 Prototype Scope (decided 2026-07-09)

First prototype is a deliberately small experiment to test whether the keyhole interaction model works for LLMs at all.

- **Engine: from-scratch Python.** No embedded Neovim. Full control over the buffer and — critically — over exactly what the agent sees back, which the eval ablations require. Buffer is a plain list of lines.
- **Tools in v0:** `open`, `motion`, `edit`, `matches`, `write`.
  - `motion` subset: `/pattern`, `?pattern`, `n`/`N`, `:N`, `gg`/`G`. Deferred: `f`/`F`, `w`/`b`/`e`, `0`/`$`, `{`/`}`, `%`.
  - `edit` subset: anchored `at /pattern/` form; `ciw`/`caw`, `ci`+`(`/`{`/`[`/`"`/`'` (and `di`/`da` variants), `diw`, `dd`, `cc`, `o`/`O`, `A`/`I`, `D`/`C`, `x`/`r`. Deferred: surround (`cs`/`ds`/`ysiw`), `.` repeat, `t` tag object, `dap`, `J`, `>>`/`<<`.
  - Deferred tools: `substitute`, `viewport`, `undo`/`redo`.
- **Echo discipline (unchanged from core design):** every state change returns a viewport — 2 above + affected line(s) + 2 below, line-number gutter, `→` on the cursor line, `^` column marker on the line below when column matters (compiler-diagnostic style, the most weight-familiar column marker). ANSI/reverse-video cursor rendering was considered and rejected: MCP results are plain text; escape codes get stripped or tokenize as garbage inside line content.
- **Cursor rendering is a config flag** (`caret` / inline marker / block) — cheap future ablation: which cursor rendering do LLMs follow best.
- **Eval:** deferred to a second phase; v0 is validated by dogfooding from Claude Code. Eval will use generated documents (see Evaluation Plan); VimGolf was considered and rejected.

## Dogfood #1 findings (2026-07-09, evening)

First live dogfood from Claude Code (Fable, warm operator — had just read this
doc). Task: 6-part refactor of a generated 65-line Python file (rename across
2 call sites, constant bump, quote normalization ×2, delete debug lines,
signature default change, insert constant). Result: **14 tool calls, 14
first-try successes, zero malformed commands, exact target reached, file
never read in full.**

What the design got right, confirmed live:

- Vim syntax needed no thought to produce — principle #1 (no novel DSL) held.
- Viewport echoes fully replaced verification re-reads — never wanted `Read`.
- `matches` pre-check caught a real ambiguity (`timeout=10` vs `range(10)`)
  before an anchored edit could hit the wrong site — principle #4 held.
- All friction encountered was already on the deferred list; nothing
  unanticipated broke.

Friction → features pulled forward (v0.1, in priority order):

1. **Ambiguity count in anchored-edit summaries** — `at /30/ ciw 60` succeeded
   by luck; the summary should read `changed line 9 (match 1 of 3)` so a
   wrong-site risk is visible at a glance, like `motion` already does.
2. **`substitute`** — multi-site rename costs one `ciw` call per site; the
   most common refactor shape needs the ex-style tool.
3. **Surround `cs`/`ds`/`ysiw`** — quote normalization took 3 calls
   (`r"` → `motion /'` → `r"`) or a full `cc` line retype (the verbatim
   reproduction cost keyhole exists to avoid); `cs"'` is one call.
4. **`f`/`F` motions** — no natural idiom for sub-line hops (e.g. to a
   closing quote) without them.

Still deferred, still no evidence of need: `viewport`, `undo`/`redo`,
`w`/`b`/`e`, `0`/`$`, `{`/`}`, `%`, `.` repeat, `J`, `>>`/`<<`, `dap`, `t`
tag objects.

## Benchmark rethink (2026-07-09, to design next session)

Direction decided in conversation, details to be worked out next session:

- **Self-contained benchmark with generated documents.** The harness *creates*
  the start-state files itself (synthetic but realistic: config files, code
  with N call sites of a symbol, prose with quote-style noise), runs the same
  edit tasks twice — once with the keyhole MCP tools, once without (agent uses
  its native read-file + edit tools) — and diffs both results against a known
  target document. Generation gives exact ground truth for free and makes
  correctness a mechanical `diff`, no judging needed.
- **File size is the headline variable.** Keyhole's expected strength is big
  files; the baseline must pay the full-file read, keyhole must not. Sweep
  size (e.g. ~100 / ~500 / ~2 000 / ~10 000 lines) with the *same* edit task,
  and plot tokens-vs-size for both conditions. It is explicitly fine that the
  benchmark is built to showcase the big-file regime — the point of v1 of the
  eval is to demonstrate there is a reason for this tool to exist at all, not
  to be adversarially fair. (Design honestly: also report the small-file end,
  where the baseline is expected to win — that contrast *is* the result.)
- **VimGolf is abandoned (decided 2026-07-09).** Not a benchmark, not an
  optimization target, not even an optional goal (at most a for-fun exercise
  much later). Rationale: VimGolf rewards minimal keystrokes, which actively
  favors clever-but-fragile command golf — the opposite of the real-world,
  clean, error-unprone editing keyhole is designed for. We optimize for
  correctness, loud failures, and token economy; never for command brevity
  for its own sake.
- **Model is a swept dimension (added 2026-07-09 after dogfood #1):** run at
  least Opus (the intended workhorse) and Fable, always cold — the dogfood
  operator was warm Fable, so it validated the interaction model but not the
  "syntax in the weights of the production model" bet.
- **Open questions for next session:** which task types beyond
  rename-across-call-sites; how the no-keyhole baseline agent is run
  (same model, same prompt, minus the MCP server?); token accounting
  (input vs output, per tool call); how many trials per cell for variance.

## v0 -> v0.6 status log (running, from 2026-07-09 evening)

**v0 is implemented and green.** Package `djinnvim` (renamed from `keyhole-editor` 2026-07-10), Python ≥3.11, MCP Python SDK (FastMCP), entry point `djinnvim` (`djinnvim.server:main`).

**v0.1 is implemented and green (2026-07-09, late evening):** all four
features pulled forward from dogfood #1 — anchored-edit ambiguity counts,
`substitute`, surround (`cs`/`ds`/`ysiw`), `f`/`F` motions.

**v0.2 is implemented and green (2026-07-10):** registers — `:RANGE y NAME`,
`:RANGE d NAME` (cut), `:put NAME`, wrong-name recovery — see "Registers:
cut / yank / put".

**v0.3 is implemented and green (2026-07-11):** the register surface
revision (see "Registers: yank / cut / paste") — normal-mode `yy` /
`y{i,a}{object}` / `p` / `P` with the `"name` prefix in `edit`, paragraph
text object `ip`/`ap` (for c/d/y), linewise vs charwise register kinds,
`:put` removed, shared machinery extracted to `registers.py` — plus the
cold-agent tool description pass (anchor-lands-at-match-START warning +
anchor-on-the-value idiom, anchored-form-takes-edit-commands-only,
TEXT-verbatim and change-needs-TEXT/delete-forbids-it conventions,
n-always-forward/N-always-backward deviation, pattern-range
second-address semantics, register discoverability in both edit and
substitute descriptions). 151 tests; e2e script updated to the
normal-mode move (anchored `"block dap` cut → wrong-name `p` recovery →
cross-file paste).

**v0.4 is implemented and green (2026-07-11):** undo (see "Undo") — `u` in
`edit`, per-buffer capped snapshot stack (`UndoEntry`, pushed by any
content-changing edit or substitute command; yanks and failed commands push
nothing), dirty recomputed against `saved_lines` so undoing across a write
is exact, registers survive undo (vim semantics), echo = restored-region
viewport naming the undone command + remaining step count. Tool
descriptions updated (undo paragraph in `edit`, one-undo-step note in
`substitute`). 168 tests; new e2e (`e2e/e2e_undo.py`): over-matching
`:%s//g` caught in the diff → `u` reverts it whole → scoped redo →
`dd`+`write`+`u` across the write boundary.

**v0.5 is implemented and green (2026-07-11):** address offsets — vim-style
`+N`/`-N` on any range address (`/^def /-1`, `$-1`, `10+2`), fixing the
dogfood #3 over-grab (see "Dogfood #3 findings"): both range addresses are
inclusive, so `/pat/-1` is the "up to but not including" idiom. Loud
out-of-range errors; the comma-in-pattern-address parse crash fixed along
the way (`_split_range` now returns the address list instead of re-joining
on ","). `substitute` docstring + tool description updated with the
move-a-function recipe (cut `:/def a/,/^def /-1d fn` → paste ABOVE the
destination def with `"fn P`, so carried trailing blanks land right).
177 tests; new e2e (`e2e/e2e_offsets.py`): old idiom over-grabs visibly →
`u` → offset cut → cross-file `P` paste, exact target diffs.

**Benchmark harness is built and smoke-tested (2026-07-11):** see "Benchmark
v1 design" below for the decisions. `benchmark/gen.py`
(5 seeded task generators, start+target from the same block list, 20 pytest
regressions), `benchmark/runner.py` (headless `claude -p --output-format
stream-json` per trial, fresh temp workdir + fresh session each, resumable
JSONL results, `--max-budget-usd` cap), `benchmark/report.py` (per-cell
table + silent-error listing). Smoke run (haiku, rename@100, 1 trial each
condition): both exact-match, keyhole used only djinnvim tools, baseline
used Read/Edit/Bash; usage/cost/tool-call capture verified. Known caveat:
headless Claude Code defers MCP tool schemas behind ToolSearch, so keyhole
pays ~2 extra calls per run to fetch them (baseline's native tools are
never deferred) — logged per-tool, so it can be subtracted analytically.
197 tests total. **The full sweep has not been run** — it spends real API
budget and is the user's call (start with a subset, e.g.
`--tasks rename --sizes 100,2000 --trials 2`).

**Round 2 tasks built (2026-07-11, later):** first opus cells (rename,
100/2000, 2 trials) showed the baseline solving rename via grep+sed in 2-3
Bash calls without reading the file — one-regex tasks don't discriminate
(see "Round 2 tasks" under "Benchmark v1 design" for the analysis and the six
new tasks: rename-trap, bump-trap, delete-trap, quote-trap, composite,
move-multi). 221 tests total; all 11 tasks validated to parse at every
size including 10000 lines.

**v0.6 is implemented and green (2026-07-13):** fixes driven by the first
full haiku round-2 run (stopped at the session limit; its results are now
obsolete — see below):

- **Structured-output bug (headline find, from reading a benchmark
  transcript):** FastMCP wraps a `str` return as structured content
  `{"result": ...}`, and headless Claude Code delivered THAT form to the
  model — every viewport arrived as a single JSON-escaped line (`\n`,
  `\"`), with no visual alignment and extra escape tokens. Every keyhole
  benchmark cell to date ran handicapped; keyhole still went 36/36 on the
  trap tasks (baseline 30/36 — all 6 silent errors were baseline's, so the
  silent-error story held even hobbled). Fixed:
  `structured_output=False` on every tool registration.
- **Composite task failures diagnosed** (keyhole 2/3 @500, 0/3 @2000, all
  silent): the three 2000-line misses were one identical defect — the
  inserted `logger,` line landed with 9/10/12 leading spaces instead of 8
  at every call site (indentation judged inside the escaped one-line blob;
  re-measure after the rendering fix). The 500-line miss was an escape
  leak: the model escaped the paren in the REPLACEMENT as in the pattern
  (`:%s/fetch_records\(/load_records\(/g`) and Python `re` kept the
  backslash, silently writing `load_records\(` to the file. Fixed:
  vim/sed-style unescape of backslash-punctuation in replacements
  (`\(` → `(`; group refs, letter escapes, and `\\` pass through).
- **`i`/`a` added** (decided in conversation, reversing the v0 omission):
  the persistent cursor column was never the real obstacle — `x`/`r`/`D`
  are equally column-dependent; the operative rule is no column
  *arithmetic*, and anchored `i` ("insert before the match") is fully
  pattern-defined. `a` is vim-exact — after the cursor char, i.e. after
  the match's FIRST char — a known footgun, stated in the description.
- **Tool descriptions cut to roughly half** (decided in conversation):
  every deviation-from-vim warning kept (anchor-at-START, n/N, Python
  `re`, TEXT rules, inclusive range addresses); prose and redundant
  examples dropped. Whether the shorter descriptions still carry a cold
  agent is folded into what the re-run measures.
- **Runner stamps `djinnvim_version`** (short git SHA, `-dirty` suffix)
  into every results row, so mixed-version tables are impossible to
  produce silently. All pre-v0.6 results moved to
  `benchmark/results/obsolete-pre-v0.6/` — superseded by the fixes.
- 235 tests; new e2e-style check verifying over real MCP stdio that
  results arrive as plain multi-line text (no structuredContent), plus
  the escape fix and anchored `i` end-to-end.
- **Full benchmark re-run planned, all on v0.6: haiku → sonnet → opus.**
  Publish framing decided after opus: silent-error rate is the headline
  claim, flat cost-vs-size the second; if opus baseline wins outright,
  the honest writeup is "native tools win at the frontier, keyhole pays
  off below it."

Verified end-to-end over the MCP stdio protocol (scripted client running the
example session below: open → motion → anchored edits → matches → write; a
second v0.1 script covering f/F → cs → anchored ciw → :%s//g → :g//d → write;
a third script covering a cross-file function move — updated for v0.3 to
anchored `"block dap` cut → wrong-name `p` recovery → `G` → `"block p` →
write, exact target diffs — kept in the repo at `e2e/e2e_registers.py`; run
with `.venv/bin/python`, not pytest).

## Interfaces (decided 2026-07-10)

Two user groups, two interfaces, **one program**: the same core is exposed both as an **MCP server** and as a **CLI driven by an agent skill**. Architecture that makes this cheap:

- All logic lives in an interface-neutral `Session` class (`session.py`): open buffers + active buffer as state, the six operations as string-in/string-out methods (errors included, as `error: ...` strings).
- `server.py` is a thin MCP wrapper (FastMCP registration + tool descriptions only). The future `cli.py` will be an equally thin argparse wrapper.
- **CLI state model (revised 2026-07-11): daemon + thin client, no state file.** A per-sandbox-root daemon holds the live `Session`; the CLI is a tiny client talking to it over a Unix socket. Reverses the 2026-07-10 state-file decision: undo stacks and registers made the serialize-every-`Session`-field burden grow with each feature, and a live process gives exact semantic parity with the MCP path — same in-memory `Session`, zero serialization drift. **Stateless session-to-session:** the `Session` lives and dies with the daemon process — nothing is persisted across restarts, matching the MCP server's semantics exactly (unwritten buffers, registers, and undo stacks are gone when the daemon exits; disk holds only what was `write`n). Lifecycle is ssh-agent-shaped (auto-spawn on first client call, idle self-exit, die/respawn on binary version mismatch). The daemon is conceptually just the MCP server kept alive for people who don't run MCP clients; **the agent-facing MCP interface itself stays local stdio** (spawned per client, as today) — the socket exists only because a fresh-process-per-command CLI needs something long-running to talk to. Open questions, to settle when the CLI is actually built (still post-benchmark): socket naming per root, exact spawn/shutdown policy, and whether the daemon speaks MCP framing over the socket (CLI = thin MCP client) or a minimal JSON-RPC.
- **Only the MCP stack is built and tested for now**; the CLI + skill come after the benchmark phase. The cold-agent description pass benefits both: the same descriptions that must carry a cold Opus agent over MCP become the backbone of the skill's SKILL.md.

## Dogfood #2 findings (2026-07-10)

Second live dogfood (Fable, warm operator), targeting the v0.1 features.
Task: 8-part refactor of a generated 61-line Python file (insert constant,
quote a bare value, quote-style fix, default bump with decoy values, rename
with a prefix-collision trap, delete 3 debug lines, comparison operator fix,
scoped variable rename). Result: **13 tool calls, 12 successes, 1 loud
command error, exact target reached (mechanical diff), file never read in
full.**

v0.1 features under live fire:

- **`substitute` carried the round:** 4 calls (`:g//d`, `:%s//g` with `\b`,
  cursor-line `:s`, `:/def report/,$` pattern range) replaced what v0 would
  have done in ~10 anchored edits. The compact diff output doubled as
  verification; the pattern range scoped a rename away from an identically
  named variable in another function on the first try.
- **`ysiw"` / `cs'"`:** each quote task was 1 call (3 calls each in
  dogfood #1). No surprises.
- **Ambiguity counts + `matches` pre-checks composed into a planning tool:**
  the `fetch_stock` listing showed 6 hits — 2 inside DEBUG strings scheduled
  for deletion — which suggested reordering (delete first, then rename 3 real
  sites) and confirmed `\b` would spare `fetch_stock_cached`. Every anchored
  edit reported `match 1 of 1`; ordinals were never needed because unique
  anchor patterns were always available.
- **The one error:** `at /timeout=15/ f1` — tried to use a motion inside the
  anchored edit form to reach the value. Failed loudly (supported-command
  list, buffer untouched); recovery was anchoring on the value itself
  (`at /15\)/ ciw 60`), which is the better idiom anyway. Same lesson as the
  v0.1 e2e catch: **anchor on the text you want changed, not near it.** Now
  two independent hits on the same missing guidance → the `edit` tool
  description must state (a) anchored form takes edit commands only, and
  (b) the anchor-on-the-value idiom.
- **`f`/`F` went unused** — the only sub-line case fell to cursor-line `:s`.
  No new friction; nothing new pulled forward. Feature set feels complete
  for the benchmark phase.

Caveats that shape the next steps: the operator was warm (knew this doc) and
the strongest available model (Fable). **The production workhorse will be
Opus** — the "syntax already in the weights" bet must be validated there,
cold, with only the tool descriptions as guidance. Model is therefore a
benchmark dimension (run at least Opus + Fable), and tool descriptions must
carry a cold agent on their own.

Next session (in rough priority order):

1. ~~**Implement v0.1 features**~~ ✅ done same evening (see v0.1 status
   above); validated live in dogfood #2 (2026-07-10).
2. ~~**Cold-agent tool description pass**~~ ✅ done 2026-07-11 as part of
   v0.3 (see v0.3 status above): anchor-at-match-START warning +
   anchor-on-the-value idiom and examples, anchored-form-takes-edit-commands-
   only, TEXT conventions, n/N deviation, pattern-range semantics, register
   discoverability. Cold-Opus validation still pending — that's what the
   benchmark measures.
3. ~~**Implement undo**~~ ✅ done 2026-07-11 (`u` in `edit`, no redo —
   see "Undo" and v0.4 status).
4. ~~**Dogfood #3 with a move-a-block task**~~ ✅ done 2026-07-11 — see
   "Dogfood #3 findings". Registers + undo validated live; one
   description bug found (over-grabbing `:/a/,/^def /` example).
5. ~~**Fix the `substitute` description's range example**~~ ✅ done
   2026-07-11 as v0.5: `+N`/`-N` address offsets implemented
   (regression-tested, e2e'd — see v0.5 status), description example now
   `:/def helper/,/^def /-1d fn` + the move-a-function recipe.
6. **Design + build the benchmark** (sequencing confirmed 2026-07-11:
   undo → dogfood #3 → benchmark) (decided 2026-07-10: next session) —
   see "Benchmark rethink" above; add model (Opus vs Fable,
   cold) as a swept dimension alongside file size.

## Registers: cut / yank / put (designed & built 2026-07-10)

Moving text is the one real capability gap: today it means delete + retype
via `o`, paying the verbatim-reproduction cost keyhole exists to avoid.
`:m`/`:t` were considered and rejected — they pack source range *and*
destination into one blind call with no intermediate verification. Cut →
navigate → put splits a move into three steps, each echoing a viewport:
the block is seen leaving, the landing spot is confirmed before pasting,
the result is verified after.

Why this doesn't violate the no-state rule: the rule is no *invisible*
state (cursor and buffers are state too). Every cut/yank echoes the
register name + content, so the register sits high in recent context; the
model never reproduces the text — the tool holds the authoritative copy,
the echo is for planning only. The model's entire correctness burden is
remembering one word.

Design:

- Ex syntax, riding the existing pattern-range parser in `substitute.py`:
  - `:RANGE y NAME` — yank range into register NAME
  - `:RANGE d NAME` — cut: delete range into register NAME
  - `:put NAME` — insert register contents below the cursor line
- Register names may be whole words (`:put helper`) — semantic extension
  with ex-shaped surface, low risk under principle #1; letter-vs-word is a
  cheap future ablation.
- **Two kinds of delete (the anti-clobber rule):** only an *explicit*
  register target writes a register. `dd`, `diw`, `:g//d`, and bare
  `:RANGE d` are plain deletes and never touch registers — a trivial
  cleanup mid-move can't destroy the block being carried. Bare `:y` writes
  the unnamed register (a yank has no other purpose); bare `:put` reads it.
- **Echo format:** `cut 8 lines into register "helper"` plus a stripped
  content preview (full text for short blocks; first/last lines with an
  elision marker for long ones). `:put` echoes the standard post-edit
  viewport.
- **Wrong-name recovery:** `:put` with an unknown name fails loudly, and
  the error lists *all* registers — name + stripped contents each — so
  recovery is one glance at the error, never a guess.

**Built same day (2026-07-10)** — the evidence gate was waived by decision
(the design was cheap: it rides `substitute.py`'s existing range parser).
Registers live on `Session`, not per-buffer, so cut in one file / put in
another works — verified in the e2e script (cross-file function move +
wrong-name recovery). Dogfood #3's move-a-block task now *validates* the
feature live instead of gating it. Implementation notes:

- Register ops enter through the `substitute` MCP tool (it's the ex-command
  surface). Naming smell: a tool called `substitute` also doing `:put` may
  hurt cold-agent discovery — candidate question for the description pass
  (rename to `ex`?).
- Yank moves nothing (cursor stays); cut/`:put` set the cursor like
  `:g//d`/`o` do. `:put` inserts below the cursor line and echoes the
  standard post-edit viewport; `:put` takes no range (position with motion
  first, keeping the land-then-paste steps separately verified).
- Preview format: blocks ≤7 lines echo in full, longer ones first/last 3
  with `... N more line(s) ...`; lines clipped at 120 chars.

## Registers: yank / cut / paste (revised 2026-07-10, later)

**Surface revision (decided in conversation 2026-07-10, after v0.2):** the
primary register surface is **normal-mode**, not ex. Rationale: `y`/`d`/`p`
compose for free with the existing text-object machinery and the anchored
form (`at /def helper/ yap` is a one-call "yank this function"), it is the
vim surface the user (and presumably the weights) actually speak, and it
slims `substitute` back to a near-pure ex surface — dissolving the
`substitute`→`ex` rename question from dogfood #2.

- **Normal-mode ops in `edit`:** `yy`, `y{i,a}{object}` (all existing
  objects + new paragraph object), `p`/`P` (paste below/above for linewise,
  after/at cursor for charwise). Register targeting via vim's quote prefix:
  `"name yap`, `"name dd` (cut), `"name p` — word names take a space after
  the register (`"block yy`), vim's no-space form works for single letters
  (`"ayy`). Same mild semantic extension (word-named registers) as before.
- **Registers have kinds (vim semantics):** `yy`/`yap`/`dd`/ex-range ops are
  linewise (paste inserts whole lines below/above cursor); `yiw`/`yi(`/… are
  charwise (paste inserts after/at the cursor column).
- **Paragraph text object `ip`/`ap` pulled off the deferred list** — `yap`/
  `dap` need it; blank-line-delimited, vim semantics (`ap` takes trailing
  blanks).
- **Ex-range `:RANGE y/d NAME` stays as fallback** for arbitrary
  pattern-bounded blocks — the case text objects can't select: a Python
  function with internal blank lines is *not* one paragraph, so `yap` under-
  grabs; `:/def helper/,/^def /d name` is the reliable form there.
  Redundancy accepted deliberately: vim itself has both surfaces, and the
  whole bet is that models already speak vim.
- **`:put` removed** — pure redundancy with `p`/`P`, and the weaker idiom.
- **Anti-clobber rule unchanged:** only an explicit register name writes a
  register (`"name dd` cuts, bare `dd`/`dap`/`:RANGE d` are plain deletes);
  bare `y…` writes the unnamed register (a yank has no other purpose); bare
  `p` reads it. `c` commands never touch registers (vim would; invisible
  side-channel, rejected).
- **Echoes:** yanks echo name + stripped content preview and do not dirty
  the buffer; register cuts echo the content leaving (preview, like ex
  cuts); `p`/`P` echo the standard post-edit viewport; wrong-name paste
  fails loudly listing all registers with previews (unchanged).

The original ex-only design above is kept for the record; its `:put` is
gone and its `:RANGE y/d NAME` forms remain as the fallback described above.

## Undo (decided 2026-07-11)

Pulled off the deferred list, to be built **before the benchmark**. Rationale:
the uncovered failure case is *succeeded-but-wrong* destructive edits (an
over-matching `:g//d`, an oversized `dap`, a misplaced `p`) — failed commands
never touch the buffer and re-`open` covers the full-reset case, but granular
recovery today means retyping the pre-image (the verbatim-reproduction cost
keyhole exists to avoid; for bare deletes the content isn't even in the echo)
or losing every good edit since the last write. And cold agents will type `u`
after a bad echo whether it exists or not — that reflex is in the weights; if
it fails, the likely fallback is bailing to native full-file tools
mid-benchmark. Evidence gate waived knowingly (same shape as registers): warm
dogfooders never reached for what they knew was absent, and cold benchmark
agents can't file friction reports.

Decisions:

- **Surface: `u` inside `edit`** (it's a normal-mode command; that's the vim
  surface), not the separate `undo` tool sketched in the appendix below — one
  less tool description for a cold agent to discover.
- **One edit per step; `u` crosses `write` boundaries** (vim semantics —
  `write` isn't special from the buffer's perspective).
- **No redo** — "undid, then regretted it" is rare, and redo drags in
  branch-on-edit-after-undo semantics for no payoff. Stays deferred.
- **Echo:** viewport of the restored region (visibility rule as usual);
  summary names the undone command.
- Implementation: per-buffer snapshot stack of the line list (+ cursor)
  taken before each successful mutation; capped depth.

## Dogfood #3 findings (2026-07-11)

Third live dogfood (Fable, warm operator), targeting the v0.3 register
surface and v0.4 undo. Task: move-a-block refactor across two generated
files (`dogfood/pipeline.py` 59 lines, `dogfood/report.py` 15 lines):
cross-file function move (`validate_row`, which has an *internal blank
line*), in-file function reorder (`batch` above `apply_discounts`),
cross-file rename with a docstring decoy, constant bump. Result: **16 tool
calls, 0 malformed commands, exact mechanical diff on both files, both
compile, files never read in full.** Plus a 2-call post-run probe.

What held up:

- **The full move loop worked first try in both shapes:** anchored
  `"b dap` cut → `"b P` paste (in-file reorder, one call each) and
  ex-range cut → cross-file `p` paste. The `"name` prefix composed with
  the anchor as designed; cut/yank previews served as the verification —
  no re-reads, no retyping of moved text.
- **`dap` under-grab on a function with internal blanks, confirmed live**
  (deliberate probe): the cut preview showed the truncation *instantly* —
  echo discipline made a succeeded-but-wrong destructive edit visible in
  the same tool result. `u` restored the region whole; the wrong register
  content survived undo (vim semantics, as designed) and was simply
  overwritten by the follow-up ex-range cut.
- **Undo's first live outing (3 uses):** restored-region viewport naming
  the undone command was exactly right for confidence; an unwritten
  probe-then-undo left the disk byte-identical.
- **`matches` decoy catch again:** the pipeline docstring contained
  "summarize"; the pre-check showed 2 hits → scoped anchored `ciw`
  instead of `:%s//g`. (In report.py the pre-check cleared `:%s//g` for
  file-wide use.) Principle #4 keeps earning its keep.

New idiom discovered — **cut the leading blank lines with the block**:
`:22,33d fn` (2 blanks + function) makes the linewise paste between
functions land with correct spacing on both sides, zero patch-up. Without
it a function move costs 2 `dd` at the source and 2 bare `O` at the
destination. The line numbers came straight from a `matches` listing —
matches as a range-planning tool. Candidate for the tool descriptions /
future SKILL.md.

**Bug-shaped finding (post-run probe, confirmed live):** the `substitute`
tool description's own example `:/def helper/,/^def /d fn` **over-grabs** —
the second address is inclusive (standard ex), so the *next* `def` line
goes into the register too. A cold agent copying the doc example verbatim
would corrupt the file (loudly — the preview shows it — but a benchmark
agent may not look closely). Must fix before the benchmark: replace the
example with a reliable end anchor (last-line pattern or line numbers from
`matches`), and/or implement vim's address offsets (`:/a/,/^def /-1`),
which would also subsume the leading-blanks idiom (`:/def f/-2,/.../`).
Two independent wants for offsets in one session → v0.5 candidate.
**Fixed same day as v0.5** (offsets implemented, description example
corrected — see v0.5 status). Note learned while fixing: do NOT combine
`-2` leading blanks *and* `/^def /-1` in one cut — that carries blanks on
both sides (4 total) and starves the source. The clean recipe is cut
function + trailing blanks (`/^def /-1`), paste above the destination
def with `P`; it's now the description's example.

## Benchmark v1 design (decided 2026-07-11)

Open questions from the rethink, settled in conversation:

- **Driver: headless Claude Code** (`claude -p --output-format stream-json`).
  Settles token accounting for free: the result event carries exact usage
  (input/output/cache-read/cache-write tokens), `total_cost_usd`,
  `num_turns`, `duration_ms` — per trial, programmatically. The stream also
  lets us count tool calls per tool. No scraping, not rough.
- **Baseline condition = stock Claude Code:** same model, same prompt, all
  commonly allowed native tools (Read/Edit/Write/Grep/Bash — if the agent
  reaches for `sed`, that's legitimate baseline behavior),
  `--permission-mode bypassPermissions` inside the throwaway trial dir,
  `--strict-mcp-config` with no servers so the user's global MCP config
  can't leak in.
- **Keyhole condition = djinnvim only:** `--mcp-config` pointing at the
  repo's `djinnvim` binary with `DJINNVIM_ROOT` = trial dir,
  `--strict-mcp-config`, native file/shell tools disallowed
  (`--disallowedTools Read Edit Write MultiEdit NotebookEdit Bash Grep
  Glob`). The prompt tells the agent its editor is the djinnvim tools and
  nothing else; all operating knowledge must come from the tool
  descriptions (the cold-agent bet under test).
- **Cold sessions:** every trial is a fresh `claude -p` process in a fresh
  temp workdir (no project CLAUDE.md), fresh generated files. Trials per
  cell configurable, default 5.
- **Task types (5), all with dogfood provenance:**
  1. `rename` — whole-word rename across K scattered call sites with a
     prefix-collision decoy (`fetch_records` vs `fetch_records_cached`).
  2. `delete-debug` — remove every `log_debug(...)` line, scattered.
  3. `bump-default` — change one keyword default in one function
     (needle-in-haystack single edit; numeric decoys elsewhere).
  4. `quote-style` — normalize single→double quotes file-wide.
  5. `move-func` — move a function (with an internal blank line) to a
     different position in the file.
- **Generation = ground truth:** each task builds the start file from a
  seeded block list and the target file from the same list with the
  transformation applied — correctness is a mechanical exact diff.
  Sizes swept: ~100 / ~500 / ~2000 / ~10000 lines; task difficulty scales
  naturally (more call sites / debug lines in bigger files).
- **Models swept:** `opus` (intended workhorse) and `fable`, both cold.
  `haiku` worth adding: Opus is sed-fluent, so keyhole's edge may be
  largest where a cheaper model would fumble shell quoting.
- **Round 2 tasks (decided 2026-07-11, after the first opus cells):** the
  first four tasks are all one-regex tasks — the opus baseline solved
  rename@2000 in 2 Bash calls (grep+sed, file never read), so tokens stay
  flat with size and the cost gap is noise. grep -B2 is a viewport and sed
  is an anchored edit; scenarios must break one of those to discriminate:
  1. **Trap variants** (`rename-trap`, `bump-trap`, `delete-trap`,
     `quote-trap`): same generators plus decoys, but *natural* prompts
     with no decoy warnings (the originals hand-hold: "do NOT touch
     fetch_records_cached"). Correct interpretation stays unambiguous;
     naive sed silently corrupts (missing \b, explicit timeout=30 at call
     sites vs the default, log_debug_summary collision, apostrophes in
     comments). Headline metric becomes silent-error rate, where echo
     discipline is the product bet.
  2. **`composite`**: one dogfood-shaped task = 6 heterogeneous small
     edits (rename w/ decoy, bump default w/ explicit-arg decoys, delete
     debug lines, constant value change, insert constant, add `logger`
     2nd arg at every send_request call site — some call sites
     multi-line, which breaks line-based sed). The most representative
     task of real usage.
  3. **`move-multi`**: gather three scattered check_* functions directly
     above run_checks in a stated order — no regex answer, registers'
     home turf, scales with file size.
- **Metrics per trial:** exact-match bool, tokens by kind, cost USD, tool
  calls (total + per tool), turns, wall clock, and claimed-success vs
  actual-diff for the silent-error rate. Results appended to a JSONL;
  a report script aggregates per cell. `--max-budget-usd` caps runaway
  trials.
- Layout: `benchmark/` (generator, tasks, runner, report) — separate from
  `src/`, not part of the installed package.

## Labeled caret (decided 2026-07-14, to build next session)

The `^` column marker is pure whitespace alignment
(`" " * (2 + width + 2 + col) + "^"`) — but a model can't *see* alignment;
extracting the column means counting characters, the known weakness. The
design has always leaned on the caret being confirmation (the cursor got
there by a pattern the model chose), not measurement. Decision: add a prose
label to the caret line, compiler-diagnostic style (Rust/Clang
`^ help: ...` — weight-familiar), converting position-to-count into
fact-to-read:

```
→ 12      retries=15)
          ^ on "r" of "retries"
```

- **Format:** `^ on "h" of "hello"` on a word char, `^ on ")"` on
  punctuation, `^ at end of line` past the last column. Factual only, no
  interpretation.
- **The label must never lie:** word extraction reuses the same
  `_word_span` logic `ciw` uses, so `of "hello"` names exactly what `ciw`
  would change — that consistency is the safety property.
- **Same trigger as today** (`show_column` only); ~8 extra tokens on
  column-relevant echoes, nothing on line-wise motions.
- **Why it earns its place:** the anchor-lands-at-match-START mistake (two
  live dogfood hits) becomes self-announcing *before* the edit — a model
  that meant to change the 15 sees `on "r" of "retries"` and re-anchors.
- Implemented as a third `CURSOR_STYLE` value (`caret-labeled`), default
  for the benchmark; the cursor-rendering ablation can measure its worth
  by ablating *down* to the bare caret.

**v0.7 is implemented and green (2026-07-14):** the labeled caret, as
specced above. `CURSOR_STYLE` now reads the `DJINNVIM_CURSOR_STYLE` env var
(default `caret-labeled`; `caret` = the bare marker, for the ablation).
Label extraction lives in `viewport._caret_label`, reusing `edit._is_word`
+ `edit._word_span` (no import cycle — edit never imports viewport), so
`of "word"` is exactly the `ciw` span; single-char words keep the `of`
(`on "x" of "x"`) so its presence always means "ciw works here and changes
this"; tab renders as `on tab`; whitespace as `on " "`. Tool descriptions
deliberately unchanged — the label is self-explanatory prose, and the v0.6
half-length descriptions stay as they are. 242 tests; new e2e
(`e2e/e2e_labeled_caret.py`): `/retries=15/` lands at match START and the
label *says so* before any edit → re-anchor on the value → `ciw` changes
exactly what the label named; punctuation and end-of-line label shapes
verified as plain multi-line text over real MCP stdio.

## Global anchored edit: `at each` (decided 2026-07-14, v0.8)

The `:g/pat/normal {cmds}` capability question, settled in conversation.

**The gap is narrow but real.** "Do X at every match" splits three ways:
regex-shaped bulk edits (`:%s//g` covers them), delete-matching-lines
(`:g/pat/d`), and everything else — where today the idiom is *reissuing
the identical anchored edit*: search is strictly-after-cursor, so repeating
`at /pat/ dap` walks the matches one per call with a per-site echo. That
iterated form is fine (arguably better) at low K; at high K in a big file,
N round trips for one *structural* edit (text object, surround, `A`/`I`) —
the class a substitution can't express — is the uncovered cost.

Decisions:

- **Surface: `at each /pattern/ <cmd>` in `edit`**, NOT `:g/pat/normal` —
  per the false-friend corollary under principle #1. Real vim's `:normal`
  takes keystroke streams (`ciwfoo`, no TEXT separator) and `:g` addresses
  per-line; a constrained lookalike would break on exactly the most
  idiomatic input the weights generate. `at each` is a one-word delta on
  the anchored form a cold agent already learns.
- **One edit command from the existing set.** No sequences, no macros
  (that's the VimGolf-shaped fragility the design rejects). `y`/`p`/`u`
  and `"name` register prefixes are rejected loudly (yank-at-N-sites has
  no sane register semantics; paste-at-each deferred until wanted).
- **Per-MATCH, column-precise** — deliberate deviation from `:g`'s
  per-line: the cursor lands at each match start, so `ciw`/`ci(` hit the
  matched site, exactly what `at /pat/` already means. Two matches on one
  line = two edits.
- **Bottom-up execution with per-site revalidation:** matches are
  collected up front and applied last-first, so earlier positions stay
  valid; before each edit the pattern is re-checked at the recorded
  position — a match consumed by a previous edit in the batch (two
  `DEPRECATED` markers in one paragraph under `dap`) is *skipped and
  reported*, never blindly edited.
- **Transactional:** if the command fails at any surviving site (`ci(`
  with no parens on that line), the whole batch rolls back and the error
  names the site — "failed commands never touch the buffer" extends to
  batches.
- **Echo: count + the same compact ±diff `substitute` uses** (renderer
  shared, extended to render pure insertions), not a viewport. One undo
  step for the whole batch.
- **Signpost error** (same pattern as `.`): `:g/pat/normal ...` in
  `substitute` fails loudly pointing at `at each /pat/ <cmd>` — the vim
  reflex becomes a redirect, costing one call.
- **Single file only.** Multi-file batch editing deferred, and
  deliberately sequenced *behind* cross-file `matches`: the missing
  multi-file primitive is batch **visibility** (a keyhole-only agent can't
  even discover which files to touch), not batch editing.
- **New benchmark task `purge-blocks`** (added to the sweep's task set):
  remove every function block marked with a `# DEPRECATED` comment —
  high-K, structural, regex-hostile (`sed '/DEPRECATED/,/^$/d'` leaves a
  blank-line miscount = silent corruption; awk paragraph mode is the
  baseline's honest answer). Also lets the iterated anchored form compete
  against the batch form, so the batch's worth is measured, not assumed.
- **Evidence gate consciously waived a third time** (registers, undo, now
  this) — decided in conversation; the benchmark task is the validation.
  Lands BEFORE the sweep so the one-SHA rule holds.

**v0.8 is implemented and green (2026-07-14):** the global anchored edit,
as specced above. `at each /pattern/ <cmd>` in `edit` (bottom-up with
per-site revalidation, transactional rollback naming the failing site,
skipped-as-consumed reporting, one undo step); echo is the shared compact
±diff — `substitute._diff` renamed to the public `diff_lines` and extended
to render pure insertions (`+` line without a `-`), `edit` imports it (no
cycle: substitute never imports edit). `:g/pat/norm(al)` in `substitute`
now signposts `at each`. Tool description: one new paragraph in `edit`
(including the reissue-the-anchored-edit iterated idiom — the `.`
replacement made explicit to cold agents). New benchmark task
`purge-blocks` (12 tasks total), generator regression-tested (removal-only,
dap-safe single-paragraph blocks, two-blank normalization). 264 tests; new
e2e (`e2e/e2e_each.py`): matches pre-check → `:g//normal` reflex signposted
→ transactional `ci(` failure leaves the file untouched → batch `dap`
removes both marked blocks with a plain-text diff echo → one `u` reverts
the whole batch → redo → write, exact target diff.

## Dogfood #4 findings (2026-07-14, pre-sweep probe)

Fourth live dogfood (Fable, warm operator), decided in conversation as the
cheap probe before spending sweep budget: the v0.8 surfaces had never run
live. Task: the new `purge-blocks` generator's own output (501 lines,
seed 99, 6 marked blocks). Result: **exact target match, ~10 keyhole
calls, file never read in full** — one iterated anchored `dap` plus one
`at each /# DEPRECATED/ dap` for the remaining 5; two-blank spacing came
out right everywhere with zero patch-up.

What held up, live: labeled caret in both shapes (`^ on "#"`;
`^ on "s" of "use"` names the exact ciw span even landing mid-word); the
`:g//normal` signpost fires and carries the user's pattern into the
suggested `at each` form; transactional rollback names the failing site
and touches nothing; batch + iterated forms compose (iterated first, batch
for the rest, `match i of n` bookkeeping consistent throughout).

Three echo-layer bugs found (buffer semantics were correct throughout —
every miss was in what the tool *said*, not what it did):

1. **`_each_diff` misalignment.** It re-derived the batch diff by running
   difflib over pre/post, discarding the per-site spans `_each` already
   had. Around repeated lines (blanks, `    pass`) difflib picks an
   equivalent-but-misleading alignment — minimal repro echoed
   `- 2      pass` from the *surviving* function as deleted. A
   truthful-but-wrong-looking diff is echo-discipline poison: a cold agent
   would `u` a good edit. Fix: build the changed-list from exact per-site
   prefix/suffix trims (substitute already builds its diffs from the
   operation, never difflib).
2. **Batch undo dumped a ~420-line viewport** — the "restored region" of
   an `at each` undo spans first-to-last site, a full-file read in
   disguise (the exact cost keyhole exists to avoid), silently eaten by
   any benchmark trial where the agent undoes a batch. Fix: the undo entry
   carries the batch's exact changed-tuples; `u` echoes the inverted
   compact diff (symmetric with the batch echo) instead of a viewport.
   Known sibling, noted not fixed: `u` after a large `substitute`
   (`:%s//g`, `:g//d`) has the same bomb shape — its entries carry no
   tuples yet; extend the same mechanism if it shows up in practice.
3. **`write`'s changed-count inflated by difflib `autojunk`:** reported
   "769 line(s) changed" for a 41-line deletion (blank lines are
   "popular" on 200+-line files and get junked, wrecking alignment;
   verified: `autojunk=False` gives exactly 41). `_each_diff` already
   passed `autojunk=False`; `session.py`'s write didn't.

All three fixed as **v0.9** (regression tests written failing-first);
the sweep SHA moves from v0.8 to v0.9.

**v0.9 is implemented and green (2026-07-14, same session):** the three
fixes above. `_each` collects exact per-site changed-tuples (guarded
prefix/suffix trim per site, `_site_delta`; same-line matches merged into
one old→new pair; difflib gone from edit.py) and returns them alongside
the report; `UndoEntry` carries the tuples (`push_undo(..., changed=)`)
so `u` on a batch echoes the inverted compact diff (pure insertions,
post-undo numbering) instead of a spanning viewport; `session.py`'s write
count passes `autojunk=False`. 267 tests (3 new, each written failing
with the live symptom first: the misattributed `- 2      pass`, the
`(0, 247)` span viewport, the "769 line(s) changed"). Manual probe over
fresh MCP stdio replayed dogfood #4 on the same generated file: batch
diff names the blocks (comment-first, trailing blanks), undo echo 42
lines (was ~420), write reports exactly 41 changed, exact target match.

## Haiku probe & description routing pass (2026-07-14, v0.10)

First probe cells on v0.9 (haiku): rename-trap green across sizes both
conditions, but **keyhole failed purge-blocks@500 with a silent success
claim** (baseline passed). The tool profile is the diagnosis: 11 matches,
23 motion, 6 substitute, 1 write — **zero `edit` calls**. Haiku did six
per-block range deletes in substitute and miscounted blanks; it never
touched `at each` or `dap`.

Root-cause layer found while diagnosing: **Claude Code defers MCP tool
schemas behind ToolSearch in interactive sessions too**, not just headless
(confirmed live — the dogfooding sessions themselves get the djinnvim
tools deferred). The model starts with tool *names* only; descriptions
enter context per-ToolSearch-fetch (default max_results 5, we have 6
tools). The failing trial made exactly 2 ToolSearch calls — whether
`edit`'s description (the only home of `at each`/`dap`) ever entered its
context is unknowable because the runner discards the stream-json.
Consequences, decided in conversation:

- **Deferral stays the default benchmark condition** — it is the real
  condition for Claude Code users. A preloaded-schemas preamble becomes an
  *ablation cell* (isolates discoverability cost from description
  quality), not the default.
- **Runner must save per-trial transcripts** (pending) — without the
  ToolSearch queries, "never loaded edit" vs "loaded it, didn't use it"
  can't be attributed.
- **Renaming `edit` considered and parked:** in the deferred world the
  name is the pre-fetch signal, and `edit` is the strongest keyword magnet
  an editing task has; the vim-native alternative `normal` is exactly the
  false friend principle #1's corollary warns about. If any name smells,
  it's `substitute` (already on record from dogfood #2). Revisit only if
  transcripts show ToolSearch ranking it wrong.
- **Description routing pass (v0.10, landed):** three changes, all
  description-only, no behavior change — (1) `substitute` states it is
  line/regex-shaped and signposts `at each /pat/ <cmd>` for whole-block
  work (static sibling of the `:g//normal` runtime signpost — haiku was
  *in* substitute six times; that's where the redirect must live);
  (3) `edit`'s at-each paragraph gains the structural idiom + example
  (`at each /# obsolete/ dap` — deliberately NOT the benchmark's literal
  `# DEPRECATED` marker, to avoid teaching to the test); (4) `open` (the
  one tool every trial fetches first) gains a one-line tool-routing hint.
  Runtime signpost on block-shaped range deletes (#2) deferred — possibly
  noisy for legitimate range deletes. 267 tests green; sweep SHA moves to
  v0.10.

**Opus probe on v0.10 (same day, 2 trials, purge-blocks@500 keyhole):
both exact-match.** Each trial: ONE `edit` call and it was the intended
idiom (`at each /# DEPRECATED/ dap`) after `matches` pre-checks; $0.35 /
$0.58, 16 / 28 calls. Deferral evidence: opus issued a single
`select:`-all-six ToolSearch (max_results 10) up front — it loads every
schema before working, so the haiku failure mode (2 ToolSearch calls,
possibly never fetching `edit`) is model behavior under deferral, not a
harness constant. Transcripts now durable: runner already wrote
`transcript.jsonl` per workdir; the fix was `--workdirs
benchmark/results/workdirs` instead of default /tmp (no code change).
Haiku re-probe on v0.10 still pending. Rows stamped `6c8261d-dirty`
(v0.10 uncommitted at probe time).

**Next session:** ~~(1) build the labeled caret + tests, verify over MCP
stdio~~ ✅ done 2026-07-14 (v0.7 above); (2) start the benchmark re-run —
haiku → sonnet → opus, every row version-stamped, one SHA for the whole
sweep (now v0.9: dogfood #4's three echo fixes must land BEFORE trial
one; no mid-sweep tool changes). Composite and move-multi included —
composite is the cell that diagnoses whether the rendering fix cures the
indentation misses.

## Sweep scope revisions (decided 2026-07-15)

Two decisions, settled in conversation while the sonnet round ran:

- **Full opus round dropped.** Sonnet 5 sits close enough to opus-class
  that the top rung of the haiku → sonnet → opus ladder is nearly
  redundant, and an opus sweep burns the usage limit several times over
  for a result the sonnet data already sketches: near-parity on
  correctness with a lean toward worse for keyhole (sonnet keyhole missed
  3 cells, baseline 1), comparable cost. Writeup framing adopted now:
  **keyhole pays off on cheaper models; at the frontier it's near parity
  with a hang to worse.** An opus *spot-check* on the discriminating
  cells only (composite@2000/@10000, quote-trap@10000, ~12 trials)
  remains open as the cheap defense against "you skipped the strongest
  model" — decision deferred until the sonnet round and the grader
  question are settled.
- **Third condition `no-bash`** — the locked-down baseline: stock native
  tools minus shell execution (`--disallowedTools
  Bash,BashOutput,KillShell,Task`, still `bypassPermissions`). This is
  the measured version of the permission-management argument (see that
  section): the strong baseline's power is almost entirely grep+sed via
  Bash (232 of 398 baseline tool calls across all result rows to date
  were Bash), and Bash is exactly what a cautious user denies. If
  keyhole beats the no-bash baseline where it only ties the full one,
  djinnvim's case broadens from "token economy" to "the editing
  capability you get back when you lock the agent down." Containment
  verified against real transcripts: Bash is Claude Code's only exec
  tool (baseline trials used exactly Bash/Edit/Read/Write, nothing
  else); MCP bypass is impossible (`--strict-mcp-config` with no
  `--mcp-config` loads zero servers); `Task` is disallowed so a
  subagent can't reintroduce Bash. Planned cells: haiku + sonnet first
  (where the sonnet keyhole-vs-baseline comparison already exists to
  anchor against). Prompt is the baseline preamble unchanged — the
  model simply doesn't see the tools, like a real denied-permission
  session.

## Sweep results so far (recorded 2026-07-16)

**Sonnet round complete** (all 7 round-2 tasks × 500/2000/10000 × 3 trials,
both conditions, committed `f7a500d`). Clean scores — session-limit aborts
are flagged `aborted: true` in the JSONL and must be excluded (4 exist
file-wide; keep the rows, filter on the flag):

- keyhole **61/63** — only misses: composite@2000, composite@10000, both
  suspected instances of the known grader-strictness artifact (exact-match
  grader fails formatting-only divergence the prompt never specifies).
- baseline **61/63** — misses: quote-trap@10000, purge-blocks@500, both
  *real* silent errors.

**Framing correction pending the grader decision:** the 2026-07-15 "near
parity with a hang to worse at the frontier" line was computed with an
abort counted as a keyhole miss. If the two composite misses are confirmed
AST-identical formatting divergence (as haiku's were), sonnet keyhole is
semantically 63/63 vs baseline's 2 silent errors — *ahead* at the
frontier, not behind. Caveat: the sonnet round kept no workdirs, so the
composite output files are gone; confirming means re-running those cells
with `--workdirs` or AST-normalizing the grader and re-grading… which
needs the outputs. Practical path: re-run composite sonnet keyhole
@2000/@10000 (~4 trials) with workdirs kept.

**Haiku no-bash round complete** (21 cells × 2 trials, 2026-07-16, user's
launch; one composite@2000 abort + re-run). Score **34/42** vs old haiku
round's baseline 36/40, keyhole 37/40 (keyhole misses were the composite
formatting artifact; its trap-task silent errors were 0). The no-bash
story splits cleanly by task shape:

- **One-regex trap tasks (rename/bump/delete/quote-trap partially):
  no-bash is *fine* — 16/16 on rename/bump/delete-trap**, including the
  two cells where the full baseline silently sed-corrupted
  (rename-trap@500, delete-trap@2000). Without sed the model grinds
  through per-site Edit calls and the decoys don't bite. The old
  baseline's silent errors were a *sed* problem, not a tooling-gap
  problem — the same "big blind shots are where silent errors live"
  claim from the ed-discipline section, measured from another angle.
- **Structural / file-wide tasks are where it breaks: all 8 misses are
  quote-trap (2), composite (3), purge-blocks (3)**, ~6 of them silent
  (claimed success). purge-blocks@10000 went 0/2.
- **Cost tracks baseline's growth curve, then blows past it at size:**
  delete-trap@10000 $1.05, composite@10000 $1.13, purge-blocks@10000
  $0.89 — 10–20× keyhole's flat ~$0.05–0.08.

Net for the permission-management argument: denying Bash costs the
baseline correctness on exactly the structural/file-wide tasks *and*
10–20× cost at size, while keyhole is unaffected by the lockdown — the
claim holds, but the honest version is task-shaped, not blanket.

Cross-round caveats: no-bash ran 2 trials/cell vs 3; the haiku
keyhole/baseline round predates CLI-version stamping (no-bash rows are
CLI 2.1.211, sonnet 2.1.210) and the older CLI surfaced native tools
slightly differently (Glob/Grep absent from its init tool list).
no-bash containment was smoke-verified before the round: init event
shows Bash/BashOutput/KillShell/Task(+Output/Stop) absent, zero MCP
servers.

**Sonnet no-bash round complete (2026-07-18) — and the sweep is closed.**
7 tasks × 3 sizes × 3 trials; 67 rows (7 aborted, excluded), stamped
`9a638a5[-dirty]`. Clean score: **60/60 exact-match on every completed
cell** — the frontier model makes *zero* correctness errors without Bash,
unlike haiku no-bash (34/42). The lockdown cost shows up elsewhere:

- **Cost climbs with size instead of staying flat:** no-bash mean
  $0.21 / $0.56 / $0.83 at 500/2000/10000 lines, vs sonnet keyhole's
  flat $0.34 / $0.33 / $0.34 and the full (Bash-armed) baseline's
  $0.21 / $0.28 / $0.39. At 10000 lines no-bash runs ~2.5× keyhole's
  mean and its worst trials reach $1.8.
- **purge-blocks@10000 is a hard wall: zero clean trials.** All 5
  attempts aborted — 4 hit the runner's default $3 per-trial budget
  cap (`error_max_budget_usd`, $3.13–$3.50 spent; one of those had
  actually reached the exact target before the cap), 1 hit the
  session limit at $1.95. (Correction 2026-07-18: originally recorded
  as all session-limit.) Grinding a high-K structural edit through
  per-site Edit calls at size costs ≥8× keyhole; whether it *can*
  finish under a raised cap is untested — re-run with `--budget 8`
  if a clean number is wanted. Same cell for comparison: keyhole
  $0.33–0.46 clean 3/3, full baseline ~$0.36 clean 3/3.
  (Update 2026-07-19: tested — with `--budget 8` the cell completes
  2/2 exact at $4.61/$4.66 per trial, ~14× keyhole. A budget cap
  converts the cost blowup into loud failure; raising it converts it
  back into money.)
- The two remaining aborts (quote-trap@10000, move-multi@500) are
  ordinary session-limit noise, not task-shaped.

Net permission-management claim, now measured at both ends of the model
ladder: **deny Bash to a cheap model and correctness collapses on
structural/file-wide tasks (haiku: 8 misses, ~6 silent); deny it to a
frontier model and correctness holds but cost grows with file size and
blows through a $3 per-trial budget on the structural high-K task — while
keyhole is unaffected by the lockdown at either tier.** Honest caveat
unchanged from the sonnet round: at 500 lines the full baseline is
cheaper than keyhole ($0.21 vs $0.34) — keyhole's win is the flat curve
and the lockdown story, not small-file economy.

**Sweep concluded (decided 2026-07-18): no opus round, no opus
spot-check.** The runs are slow and costly, and the existing grid
(haiku/sonnet × keyhole/baseline/no-bash × 3 sizes × 7 tasks) already
carries the reason-for-existence claims: silent-error rate under big
blind shots, flat cost-vs-size, and the task-shaped lockdown story.
Haiku n=2 → n=3 top-ups also dropped.

Still open from the benchmark phase: **the composite grader decision
only** (AST-normalize vs report-as-is vs both columns) — load-bearing
for the frontier framing (sonnet keyhole may be semantically 63/63,
ahead of baseline's 61/63, not behind); settling it means re-running
composite sonnet keyhole @2000/@10000 (~4 trials) with `--workdirs`
since the original outputs were discarded. That mini-re-run is the one
benchmark expenditure still on the table; decide before the writeup.
**(Resolved — see "Grader decision and final verified results" below.)**

## Post-sweep queue (recorded 2026-07-18)

1. ~~**Bug: `motion` reports `match 1 of 1` despite multiple
   matches.**~~ **Closed 2026-07-20 as a false alarm.** Diagnosis:
   `motion`'s count and `matches` run the identical per-line
   `re.finditer` over the same buffer (only asymmetry: `motion`
   strips trailing whitespace from the command, which can only
   broaden a pattern); a scan of all 672 logged sessions (benchmark
   transcripts + interactive dogfoods) found zero motion-vs-matches
   count disagreements; and the live repro (`/Rejected` in edit.py →
   `match 1 of 1`) was correct — the pattern occurs exactly once,
   and the "several listed hits" were the viewport's *context lines*
   (2 above + cursor + 2 below) misread as a match listing. UX note
   kept from the episode: a human skimming a motion echo can mistake
   the numbered viewport for a grep-style hit list; no model did in
   any session, so the agent-facing format stays unchanged.
2. ~~**Discussion point, not yet decided: root confinement
   hardening.**~~ **Settled 2026-07-20 — see "Root confinement:
   multi-root sandbox" below.** (Original questions: cwd fallback
   right for non-Claude-Code clients? remove vs announce?
   symlink/TOCTOU test review.)

## Root confinement: multi-root sandbox (decided 2026-07-20)

Settles post-sweep queue item 2, discussed in conversation. Goal
unchanged: same containment posture as Claude Code's native Edit tool
— and it turns out that posture is literally obtainable: the MCP
`roots/list` request returns exactly the set native Edit operates
under (session launch dir + every `--add-dir` / `/add-dir` /
`additionalDirectories` grant), with `notifications/roots/list_changed`
on changes (Claude Code ≥ 2.1.203; docs explicitly recommend servers
that limit filesystem access implement it). Verified empirically the
same day: Claude Code spawns stdio servers with cwd = project dir and
sets `CLAUDE_PROJECT_DIR` in the server env.

**Trust model.** Every root exists because a *user* granted it; the
client is trusted by construction (it spawns the server process and
controls env/cwd/conversation already), and the *model* cannot expand
the set — root additions go through user approval. So honoring all
client roots is not a widening of trust. The adversary this sandbox
confines is the agent (model-generated paths, prompt injection), NOT
a hostile local user: TOCTOU races (dir component swapped for a
symlink between validation and write) and hardlinks-into-the-root are
consciously out of scope — native Edit has identical exposure, and
closing them needs `openat2(RESOLVE_BENEATH)`-class syscalls for an
attacker who already owns the project dir. One README sentence states
this ("confines the agent, not a hostile local user").

Decisions:

- **Multiple roots, all peers — NO primary/secondary distinction**
  (user call: "primary" is arbitrary and unknowable, and the
  `CLAUDE_PROJECT_DIR`-matching heuristic it would need is exactly
  the complexity to avoid). Consequence for relative paths: allowed
  only when exactly one root is configured (resolved against it —
  the overwhelmingly common case); with multiple roots, a relative
  `open` fails loudly, names the roots, and says to use an absolute
  path — that error doubles as the sandbox announcement.
- **`DJINNVIM_ROOT` → `DJINNVIM_ROOTS`**, an `os.pathsep`-separated
  list (`:` POSIX / `;` Windows — the PATH convention, so `C:\` paths
  survive). First-class and exclusive: when set, client roots are
  ignored entirely — the cautious user's pinned boundary that no
  client chatter can widen (the permission-management story depends
  on this). `DJINNVIM_ROOT` (singular) stays accepted as a one-entry
  alias — benchmark runner + existing docs set it.
- **Resolution chain:** `DJINNVIM_ROOTS` (explicit, exclusive) →
  `DJINNVIM_ROOT` (alias) → MCP `roots/list` (requested lazily on
  first tool call — it can't run before initialize; `list_changed`
  honored) → `CLAUDE_PROJECT_DIR` → server cwd.
- **Sanity refusal on `/` and `$HOME`:** refused as roots with a loud
  error ("set DJINNVIM_ROOTS explicitly if you mean this") from every
  NON-explicit source — client `roots/list`, `CLAUDE_PROJECT_DIR`,
  and cwd (a client that spawns the server in `$HOME` is precisely
  the sloppy-client case this guards). Via `DJINNVIM_ROOTS` they are
  accepted: explicit = deliberate.
- **Validation stays at the single choke point** (`Session.open`,
  `.resolve()` BEFORE the containment check — symlink escapes,
  including a symlink inside a root pointing outside, resolve to
  their true target and are rejected), generalized to
  any-of-roots. One defense-in-depth addition: re-validate at
  `write`, so a buffer opened under a since-revoked root
  (`list_changed` shrink) fails loudly instead of writing.
- **Tests to write with the implementation:** `..` traversal,
  absolute path outside, symlink-inside-pointing-out, multi-root
  accept/reject, relative-path-with-multiple-roots error, the
  `/`/`$HOME` refusals per source, write-time revalidation.
- One asymmetry recorded honestly (README containment section, not
  swept under "same as Edit"): native tools can re-prompt per edit
  depending on mode; djinnvim's `write`, once allowed as a tool, is
  allowed across the whole sandbox — same shape as native
  `acceptEdits`, a comparable posture rather than a regression.

**v0.11 is implemented and green (2026-07-20):** the multi-root sandbox,
as specced above. New `roots.py` (env parsing, per-source sanity refusal,
fallback chain); `Session` takes `roots: list[Path] | None` (None = not
yet resolved), containment generalized to any-of-roots at the `open`
choke point, relative paths resolve against a single root / fail loudly
naming all roots when there are several, `write` revalidates against the
current roots. Server side: all six tools became `async` with an
injected `Context` — the lazy `roots/list` fetch is an awaited client
request on the first tool call (env roots, when set, short-circuit it
entirely); `notifications/roots/list_changed` sets a stale flag via the
low-level server's notification-handler hook, and the next tool call
refetches. Client root URIs are sanity-checked (`/`/`$HOME` refused,
source named); refusals surface as `error:` tool results. Tool
descriptions deliberately unchanged — the multi-root relative-path error
is the announcement. 296 tests (29 new in `test_roots.py`: traversal,
absolute-outside, symlink-inside-pointing-out, multi-root peers,
relative-with-multiple-roots, env parsing incl. pathsep lists and the
explicit-`/`-accepted case, per-source refusals, write-time
revalidation, the server resolution chain incl. pinned-env and
stale-refetch). New e2e (`e2e/e2e_roots.py`, real MCP stdio, NO env
roots): client-granted root drives a relative open → outside path
rejected → grant revoked mid-buffer via `list_changed` and `write`
refuses → re-grant and the same `write` lands → two roots make a
relative open fail naming both. All five prior e2es re-run green
(the `DJINNVIM_ROOT` alias path). README gained a "Sandboxing" section
(resolution chain, pinned env roots, the confines-the-agent sentence,
the acceptEdits-shaped write asymmetry).

## Grader decision and final verified results (recorded 2026-07-20)

**Grader decision (2026-07-19): report both columns.** *Exact* =
byte-identical to target (primary, mechanical). *Semantic* = Python
`ast` equality (same program, formatting-only divergence tolerated).
Every non-exact trial is AST-classified against its retained output;
the explorer's embedded DATA carries the verdict per trial as
`sem: true` (formatting-only) / `sem: false` (silent failure).

**Whole-cell swap policy (user decision 2026-07-19/20).** Some early
cells lost their outputs before the AST sweep because workdirs
defaulted to system tmp (`--workdirs` not passed — always pass
`--workdirs benchmark/results/workdirs` from now on). A cell with lost
outputs may only be replaced by a **full 3-trial re-run kept regardless
of outcome** — never a per-trial retry, which would be
retry-until-pass bias. Applied twice:

- 2026-07-19: sonnet keyhole composite @2000/@10000 replaced by the
  `regrade-composite.jsonl` re-runs (exact *fell* 61→59/63; semantic
  63/63 now verified, not argued).
- 2026-07-20: the remaining 8 cells with unverified misses re-run by
  the user ($12.41, `rerun-unverified.jsonl`, 24 trials + 1 abort
  properly excluded/re-run) and swapped in. **Zero unverified trials
  remain in the grid; the semantic column is a measurement, not a
  lower bound.**

**Final verified numbers** (canonical copies: README findings tables +
`docs/cost-explorer.html` DATA — regenerate views from those, not from
this prose):

| model × condition | exact | semantic | confirmed silent fails |
|---|---|---|---|
| haiku keyhole | 49/62 | 59/62 | 3 |
| haiku baseline | 53/62 | 57/62 | 5 |
| haiku no-bash | 56/63 | 59/63 | 4 |
| sonnet keyhole | 59/63 | 63/63 | 0 |
| sonnet baseline | 62/63 | 63/63 | 0 |
| sonnet no-bash | 62/62 | 62/62 | 0 |

Reading, in order of defensibility:

1. **Every confirmed silent failure in the grid is haiku's (12).**
   Sonnet is semantically clean in all three conditions; at the
   frontier the difference is money, not correctness.
2. **Where they fail differs (the strongest pro-keyhole claim):**
   haiku keyhole's 3 silent fails all sit on its genuinely hardest
   tasks (composite ×2, move-multi); haiku baseline's 5 include
   rename-trap and delete-trap — simple tasks where the tempting sed
   one-shot exists. Baseline fails where the *trap* is; keyhole fails
   where the *work* is hard. Keyhole removes the avoidable failure
   mode.
3. **Silent-fail counts favor keyhole only directionally** (3 vs 5 vs
   4 on ~62 trials/condition) — not statistically significant at
   n=3/cell; don't oversell it beyond "slight favour".
4. **Cost story unchanged:** keyhole flat (~$0.11 haiku / ~$0.33
   sonnet at every size); read-the-file conditions grow with size;
   sonnet no-bash purge-blocks@10000 needs $4.6/trial (~14× keyhole)
   once the $3 cap is lifted.

**Data provenance:** `results.jsonl` (main grid) +
`probe-haiku-v0.10.jsonl` (haiku keyhole/baseline round) +
`regrade-composite.jsonl` (swap 1) + `rerun-unverified.jsonl`
(swap 2); filter `aborted: true` rows; dedup/selection is baked into
the explorer DATA. `results.jsonl` also holds 2 informal **opus**
keyhole trials (purge-blocks@500, both exact, $0.35/$0.58) — carried
in explorer DATA but inert (no UI button); README deliberately claims
no higher-tier data.

**Deliverables shipped (2026-07-19/20):** README (idea, vim-for-AIs/
ed-discipline framing, 7 task-trap descriptions, findings 1–3 with
both grading columns, per-task tables, methodology incl. swap policy),
compressed logo `djinnvim.png`, and `docs/cost-explorer.html` — a
self-contained interactive cost chart (per-trial dots, red ✗ = silent
failure, per-condition fail badges, data table; task descriptions
mirrored from the README **by hand — keep them in sync on edit**).
Serve via GitHub Pages (`Settings → Pages → main /docs`).

## CLI + skill: distribution & daemon lifecycle (decided 2026-07-25)

First slice of the post-benchmark CLI phase, settled in conversation;
builds on the daemon + thin client decision under "Interfaces".

**Skill is CLI-only — the MCP ships without one.** The MCP's tool
descriptions ARE its skill: the whole benchmark ran cold agents on
descriptions alone (sonnet keyhole semantically 63/63), so "works cold
from descriptions" is a *measured* claim a bundled skill would only
dilute — and skills are a Claude-Code concept while MCP must carry any
client, and a second copy of the guidance in context is the same
hand-sync drift hazard as the cost explorer's mirrored task text. If
discoverability ever fails (haiku-style unfetched schema), the fix is
descriptions/naming, not a skill. The CLI gets the skill because it has
no schema channel at all; SKILL.md plays exactly the role the tool
descriptions play on the MCP side, and is built from them as planned.

**Distribution: one package, one channel (combined — no split).** A
separate CLI package would mean duplicated core or two version-matched
packages, bought for nothing; the CLI is a thin client around the same
`Session` the MCP wraps. Single PyPI package, no `[cli]` extras
(FastMCP is light; always installed). Blessed paths: `uvx djinnvim mcp`
in MCP configs (zero-install, self-updating), `pipx install djinnvim`
for CLI+skill users (skill needs the binary durably on PATH). Git-URL
installs (`uvx --from git+…`, `pipx install git+…`) documented for
advanced users — they work pre-PyPI, so the install story can be
beta-tested before publishing. Release mechanics: PyPI trusted
publishing (OIDC, no tokens) via a GitHub Actions workflow firing on
version tags. **Docker rejected:** host-vs-container path identity
breaks `DJINNVIM_ROOTS`/roots-list semantics (the conversation talks in
host paths), and its confinement value duplicates the v0.11 sandbox —
the product's own feature.

**Command surface: subcommands, settled before first publish** (while
breaking changes are free): `djinnvim mcp` = the stdio server; CLI
verbs mirror the six tool names (`open`, `motion`, `edit`, `matches`,
`substitute`, `write`) so the skill reuses the benchmark-validated
vocabulary; `djinnvim install-skill` writes the packaged SKILL.md into
place (skill ships as package data → version-locked with the binary,
sync problem dissolved); `djinnvim status` / `djinnvim shutdown` make
the daemon discoverable and killable — "hidden" must mean "auto-managed",
never "unkillable", for exactly the cautious-user audience.

**Daemon lifecycle (ssh-agent-shaped, now concrete):**

- **Socket keyed by resolved sandbox roots + a session discriminator**
  (decided: parity-via-discriminator, NOT one shared daemon per root —
  per-root sharing would give concurrent agent sessions one shared
  `Session` (cursor, registers, undo), silently breaking the
  exact-MCP-parity argument that justified the daemon design).
  Discriminator via `DJINNVIM_SESSION` env (set by the skill),
  defaulting to something session-stable like the parent shell PID.
  Socket lives under `$XDG_RUNTIME_DIR/djinnvim/`.
- **Auto-spawn:** client computes socket path → connect; on failure
  (no socket / stale socket refusing) it re-execs its own binary as a
  detached daemon, polls until the socket accepts, proceeds. Stale
  sockets unlinked; concurrent-spawn races resolved by bind
  exclusivity (loser exits, client retries connect).
- **Idle self-exit** (~30 min, exact value open): unwritten buffers
  die with the daemon — stateless by design, matching MCP-server-exit
  semantics. The failure is loud, not silent: the next command spawns
  a fresh empty `Session` and gets "no active buffer" instead of
  operating on ghost state.
- **Version handshake on every request:** a daemon running a stale
  binary (pipx upgrade under a live daemon) replies "restarting" and
  exits; the client respawns the new version. No skew.

**Publish timing (user decision 2026-07-25): full story in one shot.**
No MCP-only early publish — the first PyPI release ships MCP + CLI +
skill together. Rationale: the launch announcement (Reddit etc.) is a
one-shot; it must include the CLI angle, since many devs prefer the
CLI over MCP config. Name reservation is not worth splitting the
story.

**Open, to settle when building:** exact idle timeout; the socket
protocol (MCP framing vs minimal
JSON-RPC — still open from "Interfaces"); `install-skill` target
(`~/.claude/skills` vs project `.claude/skills`, or both via flag);
argument quoting ergonomics for the CLI verbs (agents will pass
`at /pat/ ciw x` through a shell).

**Build order (agreed 2026-07-25, next session):** (1) subcommand
restructure (`djinnvim mcp`, old entry point kept working until
configs/runner flip); (2) daemon + thin client (socket derivation,
auto-spawn, idle exit, version handshake, `status`/`shutdown` —
protocol question settled here); (3) CLI verbs (thin `Session`
mapping + quoting check); (4) CLI dogfood *before* the skill exists,
to learn what SKILL.md must say; (5) SKILL.md + `install-skill`;
(6) packaging + trusted-publishing CI; then the one-shot release.

**v0.12 is implemented and green (2026-07-25): build-order steps 1–6
all landed** (same session; only the release itself remains). The
open questions, settled while building:

- **Socket protocol: minimal newline-delimited JSON**, one request per
  connection (`{"v", "op", "args"}` → `{"ok", "result"/"error"}`), NOT
  MCP framing — the client would need a full MCP client for six
  string-in/string-out calls, and parity lives in the shared `Session`,
  not the wire format. Tool-level `error: ...` strings are ok-results
  (loud errors are content); `ok: false` means the daemon itself broke.
- **Idle timeout: 1800 s default**, `DJINNVIM_IDLE_SECONDS` override
  (tests use fractions of a second).
- **Session discriminator chain: `DJINNVIM_SESSION` →
  `CLAUDE_CODE_SESSION_ID` → parent-shell PID.** The middle rung was
  discovered live: Claude Code exports `CLAUDE_CODE_SESSION_ID` into
  Bash, session-stable across calls — so under Claude Code the daemon
  keys correctly with zero configuration and no skill-set env var.
- **Quoting: strict one-argument rule.** `djinnvim edit at /p/ ciw x`
  (unquoted) is a loud exit-2 error with a quote-it hint — re-joining
  argv on spaces would silently collapse the whitespace TEXT preserves
  verbatim, exactly the silent-mangling class the design forbids.
  Validated in dogfood: the error was hit once, instantly self-fixing.
- **Exit codes:** 0 ok, 1 = editor said `error: ...` (stdout carries
  it), 2 = usage/daemon failure.
- **`install-skill` target: `~/.claude/skills/djinnvim/SKILL.md`**
  default, `--project` for `./.claude/skills`. SKILL.md ships as
  package data (version-locked, verified present in the built wheel).

Implementation: `cli.py` (argparse subcommands: `mcp`, the six verbs,
`status`, `shutdown [--all]`, `install-skill`, internal `daemon`;
bare `djinnvim` still runs the MCP server until configs flip — the
benchmark runner already flipped to `args: ["mcp"]`), `daemon.py`
(socket under `$XDG_RUNTIME_DIR/djinnvim/` keyed by
sha256(sorted roots + discriminator); auto-spawn via
`python -m djinnvim daemon` with roots+discriminator pinned in env;
bind-exclusivity spawn races; version handshake on every request —
stale daemon replies restart + exits, client respawns; `status` and
`shutdown` deliberately work across versions so pinging can't kill and
killing always works), `__main__.py`, `skill/SKILL.md` (built from the
tool descriptions + dogfood findings), `.github/workflows/publish.yml`
(test → build → trusted publishing on `v*` tags; PyPI-side publisher
config is a pre-release TODO, as is the LICENSE file). 313 tests
(17 new: socket keying, auto-spawn + cross-request state, version
mismatch restart, idle exit, shutdown, malformed requests, CLI
dispatch/quoting/exit codes, install-skill); new `e2e/e2e_cli.py`
over the real console script (fresh process per verb: over-matching
`:%s//g` caught in the diff → `u` → scoped redo → exact target →
status/shutdown).

**CLI dogfood (#5, 2026-07-25, same session, warm Fable):** composite
task from the benchmark generator (150 lines, seed 7, 6 heterogeneous
edits) driven entirely through the CLI from agent Bash calls — fresh
shell per command, exactly the skill's operating shape. **Exact target
match, ~14 calls, file never read.** Findings that shaped SKILL.md:
(1) agent cwd/env do NOT persist between shell calls (the harness even
resets cwd), so the skill's rule is "pin `DJINNVIM_ROOTS` inside every
command"; (2) the `CLAUDE_CODE_SESSION_ID` fallback held state across
all ~14 fresh shells with zero setup; (3) three operator slips —
unquoted command, unescaped `(` in two patterns — all failed loudly
with the buffer untouched (the paren-escaping papercut got its own
SKILL.md line: escape parens in the PATTERN, write them plainly in the
replacement); (4) `matches -C 1` + `motion :N` fully covered the
look-at-a-call-site need; no `viewport` tool wanted.

**Remaining before release:** add LICENSE (Apache 2.0, user's GitHub
flow), configure the PyPI trusted publisher, then tag `v0.1.0`.

## Going public: README polish + PyPI deferral (2026-07-25, later session)

**README polish landed** (the agreed 5-point plan): honest early-phase
status note (benchmarked, full surface built, ~zero real-world adoption,
only Claude Code tested as client, feedback wanted); "Where it fits"
merged into "Who is this for" (token economy, lockdown, run-your-own-
benchmarks via `benchmark/`, vim-curious with the ed-feedback caveat);
new "Getting started" section (git-URL installs: `claude mcp add … uvx
--from git+…` / `.mcp.json` snippet for MCP, `pipx install git+…` +
`install-skill` for CLI, quoting rule shown); cost-explorer link now
points at the GitHub Pages URL; roadmap refreshed (wider client
testing, multi-file matches, PyPI deferred). URLs assume
**`anschnapp/djinnvim`** — repo not created at edit time (no git
remote); user creates it themselves, then enables Pages (main /docs).

**PyPI release deferred (user decision, this session)** — revises the
2026-07-25 "full story in one shot on PyPI" decision: the git-URL
installs are the supported channel for now; no trusted-publisher
config, no `v0.1.0` tag needed yet. `publish.yml` stays wired and
dormant. Known accepted risk, flagged at decision time: the `djinnvim`
name stays unreserved on PyPI (a squatter would poison a later
`pipx install djinnvim`); publishing once would lock it.

Later same session: static mermaid charts replaced by a means table
(cost stated as Claude API usage pricing); context-consumption
paragraph added to finding 2 (cache-write tokens as proxy, caveat in
methodology fine print); explorer embedded up front as a clickable
screenshot `docs/explorer-preview.png` (iframes are stripped from
GitHub READMEs) — regenerate on explorer changes via
`google-chrome --headless=new --window-size=1200,700
--screenshot=docs/explorer-preview.png docs/cost-explorer.html`.
Em dashes swept to plain hyphens in README + explorer prose (user
preference; the `<td>—</td>` empty-cell placeholder stays).

Also fixed this session: argparse `%`-interpolation bug in `cli.py`
(the `substitute` subcommand help contained a bare `:%s/…`, which
argparse expanded into a parser-internals dict in `--help`; escaped
to `%%s`).

## Dogfood #6 findings (2026-07-25, first external real-project session)

First feedback from outside the benchmark loop: the user drove a real
programming session in another project with **Opus 5** via the MCP tools
(agent effectively cold on design.md; djinnvim use was required by the
user's session rules). Task shape: ~240 lines of structural insertion
(a 182-line class block as ONE anchored `O`, ~15 sequential pattern-
anchored insertions with zero line-number recomputation), a
`matches`-driven decision to introduce a helper (`is_free()`) from a
5-site listing, and ranged `substitute` one-liners. Exact working
result; ~30 tool calls. The agent's own retrospective named the
design's two central bets unprompted: anchors stable under 240 lines of
growth, and `matches` as the plan-the-refactor tool.

Friction reported, triaged against the code:

1. **Trailing blank lines swallowed by `o`/`O` — confirmed bug-shaped**
   (~5 of ~30 calls were blank-line repair: `at /anchor/ O` with empty
   TEXT after every block insertion ending in a blank). Root cause
   `edit.py`'s top-level `rstrip("\n")` — ALL trailing newlines
   stripped, violating the TEXT-verbatim convention for newlines
   specifically. Not vim semantics (vim has no string payload); pure
   TEXT-contract territory. **Fixed as v0.13** (below).
2. **No multi-line patterns in `substitute`** (`\n` works in the
   replacement, not the search — per-line `finditer`). One live hit
   (two adjacent clamp lines rewritten as a unit); workarounds exist
   (two commands, or rewrite-the-anchor-line with `\n` in the
   replacement — the idiom the agent found itself). **Parked behind
   the evidence gate** (user decision this session).
3. **Buffer/disk divergence confusion** — `Read`/tests see the disk,
   not the buffer; cost one confused tool call. Inherent to the
   design; answered with guidance, not mechanism (v0.13 description +
   SKILL.md additions). **Correction on the agent's report:** its
   claimed mixed-tool hazard ("the next write silently clobbers a
   native Edit change") is FALSE — `_check_fresh` runs before
   edit/substitute/write, so a disk change under an open buffer fails
   loudly ("changed on disk since open"). The loud direction was
   verified in code; only the disk-lags-buffer direction is real, and
   it is discipline-shaped.
4. **`O` above a multi-line statement misplaces** (line-wise `o`/`O`
   can't say "after this multi-line statement"; landed between the two
   lines of a definition). Predictable, caught by the echo; answered
   with the anchor-on-its-LAST-line idiom in guidance.
5. **Numeric ranges (`:1188s/...`) stale the instant the file
   changes** — worked only because the agent had just viewed the line.
   Guidance: prefer pattern addresses.

**v0.13 is implemented and green (2026-07-25):** the trailing-newline
fix + the guidance pass. TEXT now strips exactly ONE trailing newline
(the payload terminator — defensive against stray client newlines);
further ones are content (`o body\n\n` inserts body plus one blank
line; a stray double newline now yields a *visible* extra blank in the
echo instead of a silently swallowed one — the right side of the loud/
silent trade). Guidance additions in both the tool descriptions and
SKILL.md: the trailing-newline rule, o/O-are-line-wise anchor-on-the-
last-line idiom (`edit`), numeric-addresses-go-stale (`substitute`),
and write-before-running-tests (`write` description; SKILL.md workflow
rule 6, including the loud-staleness note). 316 tests (3 new, written
failing-first with the live symptom: trailing blank kept on `o`/`O`,
single terminator newline still stripped).

## Dogfood #7 findings (2026-07-25, second external real-project session)

Same real project as #6, again Opus 5 over MCP, post-v0.13. Result good
(pattern anchors held under hundreds of shifted lines; a 187-line class
insert in one call with verbatim indentation; `matches`-then-`:%s` for
twin guard sites; write's changed-count as sanity check). Friction,
triaged against the code:

1. **Mid-expression edits** (cc-replacing one comprehension line with two,
   hand-typing both indents) — real, but partly an idiom gap: capturing
   the indent with a regex group (`:s/^( +)tail/\1new\n\1  more/`) already
   avoids retyping it; nothing taught it. Not a second hit for multi-line
   patterns (the pattern here was single-line; replacement `\n` is
   supported). → guidance.
2. **"Cursor marker eats a column" — claim checked and FALSE byte-wise:**
   the `→ ` prefix is exactly as wide as other lines' two-space prefix
   (`viewport.py` render). The friction is perceptual — the model can't
   see glyph alignment and `→` reads wide. Same weakness class the
   labeled caret answers; answered with one guidance line ("indentation
   shown is exact"), marker-style ablation noted as an option if it
   recurs.
3. **Insert-above-a-comment-banner cost 3 calls** — accurate; the
   backward-search idiom (`?^# ---` then `O`) is also 3. → anchor
   offsets (below), the one-call form.
4. **Regex escaping on long anchors** (anchor as long as the old_string
   for long unique lines) — known papercut; a literal anchor form stays
   **parked** behind the evidence gate.
5. **No whole-buffer diff before write** — true; confidence came from
   py_compile + tests (the SKILL.md workflow). → write preview (below).

**Auto-save considered and rejected (user question, settled in
conversation):** auto-saving every edit would (a) gut the
permission-management claim — "nothing touches disk until write" and the
allow-edit-gate-write granularity both depend on the buffer boundary —
and (b) put every mid-refactor intermediate state on disk for tests/
watchers to see. The buffer stays; the #6/#7 confusion is a *visibility*
problem, answered by making the pending state inspectable (the preview),
not by eliminating it.

## v0.14 (implemented and green, 2026-07-25)

The three dogfood #7 items, decided in conversation:

- **Anchor offsets on the anchored form:** `at [Nth] /pattern/[+N|-N]
  <cmd>` — after choosing the match, the cursor moves N whole lines and
  lands at column 0 (line-wise, mirroring v0.5's substitute address
  offsets; without an offset the match column is kept as before).
  Out-of-range offsets are loud and touch nothing; the summary note
  becomes `(match i of n, offset -1)`. `at each` deliberately NOT
  extended (its per-match column precision is the point; an offset there
  breaks site revalidation). Banner idiom in the `edit` description:
  `at /# Merge logic/-1 O text` inserts above the banner the match sits
  inside — one call, was three.
- **Write preview:** `write(preview=True)` / CLI `djinnvim write
  --preview` — renders the full pending buffer-vs-disk ±diff via the
  shared `diff_lines` (disk-side pre-edit numbering, DIFF_CAP elision)
  and writes nothing. Session grew `_saved_delta` (SequenceMatcher,
  autojunk=False — the dogfood #4 lesson); the real write's changed
  count is now `len(_saved_delta)`, so preview and write report the
  same number. Known honest caveat: this diff IS difflib-aligned
  (unlike at-each's exact per-site tuples) — with no operation-level
  spans for accumulated edits it's the only option; content is exact,
  alignment around repeated lines may pick an equivalent pairing.
  Staleness still checks first (a diff against a changed disk would
  lie); preview skips the write-time root revalidation (read-only).
- **Guidance pass** (descriptions + SKILL.md): the indent-capture
  recipe (`substitute`), the offset/banner idiom (`edit`), the
  arrow-is-exactly-two-chars note (`open` description; SKILL.md
  workflow rule 4), preview in the `write` description and SKILL.md
  (verb list + workflow rule 5).

326 tests (10 new: offsets — above/below/linewise-col-0/ordinal-compose/
out-of-range-restores/no-offset-keeps-column; preview — diff-without-
writing + count parity, clean-buffer, pure-insertion and pure-deletion
rows; CLI `--preview` dispatch). New e2e (`e2e/e2e_preview_offsets.py`,
real MCP stdio): one-call insert above the banner with `-1`, loud
out-of-range, two pending edits reviewed with `preview=True` (disk
byte-identical), write reports the same count, post-write preview clean.
All prior e2es re-run green.

## Dogfood #8 findings (2026-07-26, third external real-project session)

Same real project as #6/#7, again Opus 5 over MCP, post-v0.14. Result good
(pattern-anchored insertion beat `Edit`'s exact-match requirement for a
whole section drop above a banner comment; a pattern-addressed
`substitute` range delete removed a nine-line function body without
restating it; buffer/write separation gave ~20 edits, one write, one
syntax check; the viewport echo replaced re-reads throughout). Friction,
triaged in conversation (not against the code first this time — the fixes
were designed live):

1. **Blank-line management ate roughly a third of the calls** — `dd` a
   duplicate blank, `O` a missing one, a bare `motion` just to look for
   one. Root-caused to two compounding gaps, not one: (a) `o`/`O` never
   inherited the reference line's indentation (real vim's `o` does; TEXT
   was always literal), so every section insert needed hand-typed
   indentation and a spacing guess; (b) the v0.13 "exactly one trailing
   newline is the payload terminator" rule broke the 1:1 `\n`-to-Enter
   mapping a vim-literate model expects — `o body\n` (one apparent
   trailing blank) silently produced *no* blank line, so getting a
   trailing blank right required typing `\n\n`, an unintuitive doubling
   discovered only after a wrong-looking echo.
2. **Implicit cursor state bit once** — cursor-line `:s/` targeted the
   wrong line after the cursor had moved from an earlier insert; failed
   loudly (good), recovered with `:%s/`. Judged working-as-designed, not
   a gap: cursor position is exactly the kind of state the echo already
   surfaces (the caret/indentation facts below reduce the need to reason
   about cursor position blind).
3. **`-1` offset semantics required re-reasoning at every use site** —
   "insert above the line above the match" (v0.14's banner idiom) is
   useful but not self-evident from the syntax alone.
4. **"Not a reading tool"** — comprehension of unfamiliar code still fell
   to native `Read`/grep. Confirmed as the accepted Non-Goal, not new
   friction (see "Full-file read tool" in Non-Goals); a pattern-anchored,
   named-size-tier read command (`tiny`/`middle`, no line numbers — the
   user's proposal, echoing the deferred v0 `viewport` tool but staying
   count-free) was discussed and **parked, not decided** — no design
   consensus yet on whether the gap is "no bigger keyhole exists" or
   "the agent reaches for `Read` out of habit."
5. **No structural feedback on a large single-block insert** — a
   112-line block dropped via one `o` had no confirmation of internal
   indentation coherence beyond `py_compile`. Judged adequately answered
   by existing `write(preview=True)` (v0.14); not actioned further.

Item 1 is the one with a real, scoped fix — see "v0.15" below. Two
sub-threads worth recording from the design conversation itself: dropping
the newline-terminator rule reopens the exact stray-trailing-newline
concern v0.13 introduced it to guard against, but for *every* command,
not just `o`/`O` (the strip runs on the raw command string before the
command type is even known) — accepted deliberately, since a stray
extra blank line is visible in the echo and cheap to `u`, unlike a
silently eaten intentional one. And the caret's new indentation fact
(below) is the same move as the labeled caret itself: this doc already
has a confirmed case of a model miscounting blank lines it could see
(v0.6, "haiku's six blank-miscounting range deletes") — visible-in-the-
render is not the same as reliably countable, so state the fact instead
of asking the model to count it.

## v0.15 (decided 2026-07-26, same session)

Four changes, all scoped to the blank-line/indentation tax:

1. **`o`/`O` inherit indentation by default.** The reference line is the
   line the cursor sits on when the command runs (post-anchor/offset
   resolution); if that line is itself blank, walk upward to the nearest
   non-blank line (vim autoindent behavior — a blank line is treated as
   sitting at the surrounding indent level, not indent zero, which is
   also how blank lines read in indent-sensitive languages like Python).
   TEXT's own leading whitespace is **relative, stacking on top** of the
   inherited indent (`'  next thing'` after a 4-space reference line
   lands at 6 spaces) — this cascades naturally across multi-line TEXT,
   preserving whatever relative indentation the agent typed between its
   own lines (the same shape as vim's `]p`/`[p` reindent-paste, applied
   to typed TEXT instead of a register). Blank lines *within* TEXT
   (`\n\n`) are never padded — they stay truly empty.
2. **`o!`/`O!` opt out to literal TEXT** — today's pre-v0.15 behavior,
   for the case of pasting an already-absolutely-indented block (e.g. a
   moved function). Bang chosen over a plain-English `raw` keyword
   because the latter collides with legitimate TEXT that happens to
   start with the word "raw" (`o raw = get_input()`); vim's bang already
   means "override/force" (`:w!`, `:q!`), so `o!`/`O!` is vim-authentic,
   not a false friend. Bang only changes indentation; multi-line
   line-opening behavior is identical to non-bang `o`/`O`.
3. **The newline-terminator-stripping rule is dropped entirely.** Every
   `\n` in the command string is now literal, full stop — `o body\n`
   presses Enter once after "body", leaving exactly one blank line below
   it, matching real vim's `o` 1:1. (Previously this required `o
   body\n\n`.) Applies to every command, not just `o`/`O`, since the
   strip ran on the whole raw command string before the command type was
   known; the reopened stray-newline risk is accepted (see findings
   above).
4. **Two new factual echo additions**, same discipline as the v0.7
   labeled caret (state don't-count):
   - **Caret indentation fact:** wherever the labeled caret already
     fires (column-relevant echoes — motions, not `o`/`O`, which are
     line-wise and don't trigger it), it now also states the current
     line's indentation relative to the line above: `indentation matches
     line above` / `indentation is 2 spaces deeper than line above` /
     `indentation differs from line above (tabs vs spaces)`. Omitted on
     the first line of a file. Mixed-unit lines (tabs vs spaces) never
     get a numeric comparison — a tab isn't a fixed width, so a count
     would mislead.
   - **Blank-run fact on `o`/`O`:** every `o`/`O` echo states pre-edit
     blank-line counts immediately outside the insertion boundary —
     `2 blank line(s) above insertion point, 0 below` — computed from
     the buffer before the edit landed, at both sides of wherever the
     new lines went in. Always included, no condition (cheap, and
     consistency beat trying to guess when it's "relevant enough").

**v0.15 is implemented and green (2026-07-26):** all four changes, as
specced. `edit.py`: `_INSERT_CMD` accepts `o!`/`O!` tokens; new
`_reference_indent` (blank-line walk-up) and `_blank_run_note` helpers;
`execute()`'s top-level `removesuffix("\n")` removed. `viewport.py`: new
`_indent_note`/`_indent_kind` helpers, wired into the caret-labeled
render path alongside the existing `_caret_label`. Tool description
(`server.py`) and `SKILL.md` updated: the o/O indent-inherit + bang
paragraph, the literal-`\n` rule, the caret's new indentation clause in
the workflow section. 340 tests (14 new: indent-inherit default,
TEXT's-own-whitespace-is-relative, bang opt-out for both `o` and `O`,
indent-walks-up-past-a-blank-line, TEXT-internal blanks stay unpadded,
blank-run notes on both `o` and `O`; caret indentation fact — matches,
deeper, singular-unit "1 space", tabs-vs-spaces, first-line-omitted); 3
pre-existing trailing-newline tests updated to the new literal semantics
(`o added\n` now leaves a trailing blank, `o added\n\n` leaves two).

## `print`: the reading keyhole (decided 2026-07-26, v0.16)

Settles dogfood #8's parked item 4 ("not a reading tool") with the
user's proposal made concrete: mimic ed/vim's `:p` as a **seventh,
standalone tool** — read-only viewport printing with pattern/line
addressing and named size tiers. Decisions, settled in conversation:

- **Own tool named `print`, NOT folded into `substitute`.** Folding was
  considered (rides the existing ex-range parser, avoids a 7th
  ToolSearch discovery cost) and the tool-rename `substitute` → `ex`
  briefly agreed — then reversed by the user: the rename fallout
  (benchmark results were measured against the name `substitute`, which
  is also the stronger search-replace keyword magnet) outweighs the
  discovery overhead of one more tool, and a print command living in a
  tool called `substitute` was never liked. `substitute` stays
  untouched.
- **Surface:** `[:][ADDR[,ADDR]] p [above|below|around COUNT]` — ex
  addressing reused verbatim from `substitute` (line numbers, `$`, `.`,
  `/pattern/`, all with `+N`/`-N` offsets), plus plain-English window
  glue per the false-friend corollary (there is no vim spelling for
  "middle"; inventing ex-lookalike syntax would be the trap).
- **COUNT:** `tiny`=8, `middle`=25, `long`=50 lines, or a plain
  integer. `above`/`below` = that many lines on that side plus the
  cursor line; `around` = that many on EACH side (user decision: the
  whole count both sides, so `around tiny` is 8+1+8).
- **Cursor semantics (vim/ed-faithful):** bare `p` prints the current
  line and moves nothing; an address moves the cursor there (that's the
  paging mechanism — the gutter's line numbers are the hop targets for
  successive prints); an explicit two-address range moves to the last
  printed line, as vim does. Window glue combines with a single address
  (`:/def load/ p around middle`) but not with a two-address range.
- **Span cap 101 lines** (= `around long`): a larger explicit range
  fails loudly suggesting paging — the cap is what keeps `print` a
  keyhole instead of a full-file read through the back door (the
  Non-Goals entry stands).
- **Rendering:** the standard viewport format (gutter numbers, `→`
  cursor marker), context 0, no caret; header states the span. Never
  dirties the buffer, no undo entry, no staleness check (like
  `motion`).

**v0.16 is implemented and green (2026-07-26):** the print tool, as
specced. New `printcmd.py` (reuses substitute's `_split_range` /
`_resolve_range` — printcmd imports substitute, never the reverse, no
cycle); `Session.print`; MCP tool registered as `print` via
`@mcp.tool(name="print")` (module function `print_`, avoiding the
builtin); CLI verb `djinnvim print [CMD]` (bare = `p`, one-quoted-
argument rule applies); daemon `SESSION_OPS` extended. `open`'s
tool-routing hint now names `print` as the reading tool; SKILL.md's verb
list grew the print entry ("The seven verbs"); README's CLI line updated
to seven. 364 tests (23 new in `test_print.py`: bare-p cursor-unchanged,
address/pattern/offset moves, range-cursor-to-last-line, window words ×
categories and numbers, each-side around, edge clamping,
address+window combine, range+window rejected, span cap at exactly 101
and loud beyond, `%` capped on big / allowed on small files, bad count,
no-dirty/no-undo, Session render shape; plus CLI dispatch and a server
round-trip). New e2e (`e2e/e2e_print.py`, real MCP stdio): pattern-
address jump + `around tiny` window → bare `p` → gutter-number paging
with an explicit range → span cap loud → `write preview` confirms
nothing pending and disk untouched. All prior e2es re-run green — after
fixing one found stale from v0.15: `e2e_preview_offsets.py` still sent
`O MERGE_LIMIT = 4\n`, which under the literal-`\n` rule inserts an
extra blank line (3 lines differ, not the asserted 2); the v0.15
session updated the unit tests but never re-ran the e2es. The `\n`
dropped; assertion semantics unchanged.

## Dogfood #9 findings (2026-07-26, fourth external real-project session)

Same real project, Opus 5 over MCP, post-v0.16. Result net positive and
better than #8: pattern anchors survived a 184-line mid-file insertion
(the agent's own note: a line-based tool would have forced two re-reads),
the 184-line module went in as ONE `O!` with exact literal whitespace, the
viewport echo caught a missing blank line before it reached disk, `u`
cleaned up a mistake with no residue, and `main.py` (~1200 lines) was never
re-read after the initial `Read` — small `print` windows around anchors
were enough. That last point closes dogfood #8's parked item 4: `print`
did the job it was built for.

Friction, triaged against the code before designing anything. **Three of
the six reported items were not gaps:**

1. **The `\n` burn is our wording, and the real trap is an asymmetry.**
   The agent read "every `\n` in TEXT is literal (one Enter each,
   vim-exact)" as "becomes a newline" and sent the two characters
   backslash-n, which landed as content. Cost one `u` plus a retry.
   Translating backslash-n in TEXT is a non-starter (it would corrupt
   every `print("a\nb")` an agent inserts), so this is description
   territory — but the sharp edge is that `substitute`'s *replacement*
   DOES turn `\n` into a newline (verified live: `:s/a = 1/x\ny/` splits
   the line). Same two characters, opposite meaning in two tools. The fix
   states the asymmetry explicitly in both descriptions and SKILL.md
   rather than just re-wording "literal".
2. **"No way to insert an empty line directly" is false.** Bare `o`/`O`
   with no TEXT inserts exactly one empty line and composes with anchors
   (`at /pat/ O`), which is why the agent's `:/pat/s/^/\n/` workaround and
   five `:N,Nd` cleanup calls were never necessary. Pure discoverability:
   the tool description never said so. **Blank-line handling stays
   guidance-only (user decision):** a declarative `blanks N above|below`
   command was designed in conversation and rejected for now — the
   documented one-call idioms have never actually been tried, so building
   a new surface would be guessing at a tax that plain guidance may
   remove. If dogfood #10 still burns calls on whitespace with the
   guidance in place, the evidence gate is met and `blanks` is the
   candidate.
3. **"`edit(':901 dd')` is rejected, so line deletion forces numeric
   addresses" is also false** — `at /pattern/ dd` is exactly the
   pattern-addressed line delete. But the error dead-ended in the
   supported-command list without naming it, so the ex-address reflex had
   nowhere to go. Fixed as a signpost, same shape as `.` and
   `:g//normal`.
4. **Regex escaping in anchors — second live hit** (dogfood #7 item 4 was
   the first), and this time the workaround was worse than the papercut:
   the agent dodged `# merge (skip blocks…)` with a `.` wildcard, which
   is fine until a wildcard silently matches a site it did not intend.
   That is the silent-wrong-site failure mode the whole design exists to
   remove, so the evidence gate is met — see v0.17.
5. **Hand-indented edits inside wrapped expressions** — the v0.14
   indent-capture recipe covers it and the agent did not use it;
   guidance, not a gap. Not re-actioned this session.
6. **No parse/LSP feedback** ("an edit that leaves the file unparseable
   would sail through silently"). Real, and **deliberately skipped (user
   decision)**: a Python-only `compile()` note on `write` was on the
   table and rejected as the first step onto the LSP slope. Correctness
   keeps coming from running the file or tests, per SKILL.md workflow
   rule 6, which already says write-before-testing.

## v0.17 (decided and implemented 2026-07-26, same session)

**The literal anchor: `at "literal text" <cmd>`.** Quotes mean literal,
slashes stay regex. Not a false friend — vim has no anchor syntax at all
here (the `at` glue is already plain English per principle #1's
corollary), and quoting-to-mean-literal is the reflex every shell and
search box trains. The literal is `re.escape`d and reuses the identical
anchor path, so ordinals and `+N`/`-N` offsets compose unchanged
(`at 2nd "f(x)"+1 cc done`) and `at each "literal" <cmd>` works too.
A literal cannot contain a double quote; that case says so and points at
the `/regex/` form. Errors show the text as typed, never the escaped
regex. Empty literals and unterminated quotes fail loudly: any command
starting with `at ` that matches neither anchor form now gets a
malformed-anchor error listing all the shapes, instead of falling through
to the unknown-command list.

**Ex-address signpost in `edit`:** a command starting with `:`/`%`/`$` or
a line number followed by a separator (`:901 dd`, `1,5d`) now errors with
"address by pattern instead (`at /regex/ dd`, `at "literal text" dd`,
`at each /regex/ dd`), or use the substitute tool for ex commands". A
digit glued to letters (`5dd`) is a *count* reflex, not an address, and
still falls through to the supported-command list.

**Guidance pass** (tool description + SKILL.md + module docstring): the
literal-anchor form; the newline rule restated as "real newline
characters, one Enter each; the two characters backslash-n stay as typed"
plus the explicit `substitute`-replacement asymmetry; bare `o`/`O`
inserts exactly one empty line and `at /pattern/ dd` removes one, with
"don't reach for substitute to fix spacing"; `dd` addressed by pattern.

372 tests (8 new: literal anchor needs no escaping, literal does not
match as a regex, composes with ordinal+offset, no-match shows the text
as typed, `at each` literal, empty literal loud, unterminated quote
loud, ex-address signpost). New e2e (`e2e/e2e_literal_anchor.py`, real
MCP stdio): the regex form misses `# merge (skip blocks...)` unescaped →
the literal form hits it → `:9 dd` signposted → `at /^debug_line/ dd` →
bare `O` adds the blank line → multi-line TEXT with real newlines and a
surviving literal backslash-n → `at each "a + b"` → exact target match.
All nine prior e2es re-run green.

## Dogfood #10 findings (2026-07-26, fifth external real-project session)

Same real project, Opus 5 over MCP, post-v0.17. Roughly 8 corrective calls
out of ~25. The agent's own triage put the ratio at 5 guidance : 2 command
design : 1 its own error, and its verdict on the task ("mostly big clean
insertions at findable anchors") was "about a wash with Edit: better on
tokens and on targeting ambiguous sites, worse on round-trips". What worked
was the part we already believed: anchored edits beat quoting context for
uniqueness, a 145-line block went in as one call with exact indentation,
`matches` then `at 2nd /ax, ay = a.center\(\)/` disambiguated two identical
lines with no context quoting at all, and every mistake was caught by the
echo rather than by a later test run.

**The finding that reframes the previous three sessions: the guidance was
never delivered.** The agent noted in passing that the `edit` description
arrived cut off mid-sentence. Verified directly: Claude Code (2.1.220)
truncates every MCP-supplied string at **2048 characters** - constant `LB`
in the bundle, applied to tool descriptions, server instructions and prompt
bodies alike - and appends "… [truncated]" with no error anywhere. `edit`
had grown to 3944 chars, so **1898 chars, 48 percent, reached no model**:
the o/O indent rule, `o!`/`O!`, the blank-line-count guidance, all of
registers and paste, `u`, and every one of the six examples.

Git history of that docstring: 1067 chars (07-10), over the cap since
2026-07-14 (2170), then 2398, 2621, 3076, 3944. So every guidance fix
written into it since v0.6's shortening pass - including v0.15's indent
paragraph, which existed precisely to prevent dogfood #10's top complaint -
landed in the invisible half. That is the "spinning in circles on
indentation" feeling: we kept fixing the docs in a place no model reads.
The other six descriptions were all under the cap; `edit` was the only
casualty.

**Was the benchmark itself truncated? Yes, mildly - checked, not guessed.**
`benchmark/results/*.jsonl` records a `djinnvim_version` commit per trial.
All but one batch (`6c8261d`, 82 trials, 1977 chars, whole) ran on a
2170-char description, 122 over the cap. The lost 122 chars were exactly
the last three examples: `edit("at each /# obsolete/ dap")`, the register
pair `at /def helper/ "fn dap` then `"fn p`, and `edit("u")`. So the
keyhole condition - including the move/composite task the README calls
"cut/yank/put register territory" - was measured with the register and
undo examples missing from the description. The direction is favourable
(the numbers came from less guidance than we thought we shipped), which is
exactly why it should be stated rather than sat on; the natural home is the
README's existing "the numbers predate the current version" note.

The rest of the triage:

1. **`cc` was a genuine false friend.** `o`/`O` inherit indent (v0.15) and
   `cc` did not, so a replacement landed at column 0 inside an 8-space
   block. Vim's `cc` under autoindent keeps the line's own indent, so this
   was our deviation from the model the tool otherwise follows exactly -
   the corollary in principle 1 says vim spelling is used only where
   behavior is vim-exact. Fixed, not documented around.
2. **The `substitute` indent-capture recipe is an active counter-signal.**
   `:s/^( +)tail/\1new/` teaches "retype the indent", which the agent
   generalized to `edit`. Both copies now cross-reference the other.
3. **Doubled blank lines** (five `:Nd` calls to clean up after `O` plus a
   trailing newline). The agent proposed auto-collapsing them, using the
   blank-line counts the echo already reports. **Rejected:** that reverses
   v0.15's literal-newline decision, taken after getting it wrong twice,
   and it is silent state mutation. Guidance, not behavior.
4. **`:s/` scoped to the cursor line after the cursor had drifted** - the
   agent's own error, documented plainly, left alone.
5. **"Nothing validates syntax"** - already decided (parse/LSP feedback on
   `write` rejected); correctness comes from running the tests.

## v0.18 (decided and implemented 2026-07-26, same session)

**The guidance budget is now a first-class constraint.** Two channels, each
capped at 2048 chars by the client:

- **Server `instructions`** (`FastMCP(instructions=...)`, previously unset,
  1801 chars): loaded once, shared by all seven tools, and the home of
  everything cross-cutting - the keyhole loop, the no-counts/one-command
  rule, TEXT-inline, the newline asymmetry, the indentation contract,
  buffer-versus-disk, read-the-echo. Confirmed delivered on the wire in
  `initialize` by a new e2e.
- **Tool descriptions** keep only what is specific to one tool. `edit`
  dropped 3944 -> 1878 with nothing lost, because the cross-cutting half
  moved rather than being deleted.

Three supporting decisions. **One fact, one place:** if a rule is in
instructions, a description points at it in a few words instead of
restating it, or the two copies drift. The one deliberate exception is the
indent rule, which stays as a clause in `edit` too, because server
instructions are a client courtesy while descriptions are the channel every
client must pass to the model, and a client that drops instructions would
otherwise silently corrupt indentation. **Docstring indentation is billed
against the budget** (123 chars in `edit` alone), so `_dedent_descriptions()`
strips it at import. **The framing for descriptions is now the vim delta:**
models know vim, so the text spends its budget on what differs (anchoring
replaces moving the cursor, `at each` replaces `:g//normal`, TEXT is inline,
no counts) rather than on teaching vim.

**`cc` joins `o`/`O` under vim autoindent**, with `cc!` as the literal
opt-out, reusing `_reference_indent` unchanged (so a `cc` on a blank line
takes the indent of the nearest non-blank line above, as `o`/`O` do). One
contract for all three line-wise inserts; the payoff beyond correctness is
that vim-exact behavior needs no explanation, which is how the indent rule
shrank from a paragraph to a clause.

**`cip`/`cap` removed** (`dip`/`dap` stay). A multi-line replacement of a
whole paragraph was the one place with no good answer to "what indent does
this get", it had exactly one test and no dogfood ever used it, and
deleting it settled the question by subtraction. The loud error names the
two-step (`dip` then `o <text>`) and points at `substitute` for a ranged
rewrite. `dap` is untouched and remains load-bearing: `at each /# obsolete/
dap` is the headline structural idiom.

382 tests (10 new: the 2048-char budget for every description and for
instructions, instructions carry the cross-cutting contracts, SKILL.md
mirrors them and no longer advertises removed commands, `cc` inherits the
replaced line's indent, TEXT indent stacks on it, multi-line `cc` indents
every line while blanks stay empty, `cc!` literal, `cc` on a blank line
takes the indent above, `cip` removed with a signpost). New e2e
(`e2e/e2e_budget.py`, real MCP stdio): instructions advertised and under
cap, all seven descriptions under cap and untruncated, `cc` autoindent,
`cc!` literal, `cip` signposted, `dap` still structural. All ten prior e2es
re-run green.

## Dogfood #11 findings (2026-07-28, first foreign-harness session)

First use outside Claude Code: the user's normal harness (Copilot, Opus 4.8)
with the MCP server installed, ordinary source files, no huge inputs. One
finding, and it is the largest one the project has had: **the tools were
never chosen at all.** Not misused, not preferred for the wrong tasks -
simply not selected, with the native editor doing everything. Every prior
dogfood measured how well djinnvim works *once picked*; this one measured
whether it gets picked, and the answer was no.

Two causes, separated because only one is about wording:

1. **The call arithmetic.** A one-line change cost `open` + `edit` +
   `write` against a native editor's single stateless call, and in a real
   session the model has usually already read the file for other reasons,
   so the read-side saving is spent before the edit comes up. On an
   ordinary file the model was pricing correctly. This is not a
   presentation problem and no description could have fixed it.
2. **Nothing in the schema said when to prefer djinnvim.** All seven
   descriptions answer *how*, in a list where selection is decided on the
   first sentence or two. The v0.18 vim-delta framing is right for a model
   that has already committed and says nothing to one that has not. The
   pitch was never written, only the manual.

A third factor was noted and left alone: `edit`/`print`/`write` collide by
name with native tools. Renaming was rejected - it would break benchmark
provenance and the vim-vocabulary principle for a cosmetic gain - but it is
the remaining lever if v0.19 does not move the needle.

Also confirmed: server `instructions` cannot be assumed delivered. Several
clients drop the channel, which makes the v0.18 one-fact-one-place rule
unsafe for anything selection-critical.

## v0.19 (decided and implemented 2026-07-28, same session)

Both halves of dogfood #11, with the user's constraint that the description
side stay compact and not oversell.

**The optional `path`** on `edit`, `substitute`, `print`, `matches` and
`write`, defined as exactly `open(path)` first and nothing else - one rule,
no per-tool drift. It kills the setup call and makes each tool read as
self-contained in the schema, which is a selection signal in itself. Three
sub-decisions: the switch is **announced** (`[now on ... — N lines]`) but
only when the active buffer really changed, so repeated calls stay quiet
and the no-silent-state rule still holds; an implicit switch **never
discards unwritten changes**, so a dirty *and* stale buffer gets the
staleness error where explicit `open` would reload and say so (implicit
actions must not destroy data; the visible cost is that `print(path=X)` can
fail where bare `print()` succeeds); and **`motion` is excluded**, being a
within-file cursor op that `print`/`matches` with a path already cover. CLI
gets `-f/--file` on the same five verbs, where it matters more still, since
CLI processes are stateless.

**Selection clauses** leading `edit`, `matches`, `print` and `substitute`,
written as a rewrite of each flat definition sentence rather than an added
paragraph - there is no budget to spare. `edit` carries the honest negative
("not for creating files or rewriting one wholesale"), which is
load-bearing rather than polite: a tool that says where it loses is
believed about where it wins, and it is what keeps the change from
degenerating into "always use djinnvim". Same sentence added to
`INSTRUCTIONS` and SKILL.md; **selection guidance is now the second
deliberate duplicate** after the indent rule, for the reason dogfood #11
confirmed - instructions are a courtesy, descriptions are the only
guaranteed channel.

Budget: `edit` had to give back ~90 chars and ends at 2033/2048.
`INSTRUCTIONS` at 2022/2048. The freed chars came from wording, plus one
example line that duplicated the register paragraph above it verbatim.

Recorded honestly: this is a fix built from a single negative observation,
and it is only measured on paper. The next foreign-harness session is the
real test, and if selection still fails, the lever left is naming, not more
words.

390 tests (8 new: one-call edit through `path`, the note only on an actual
switch, `path` reaching every op but motion, the no-discard carve-out, the
no-buffer error advertising `path=`, the CLI `-f` wire shape, motion
rejecting `-f`, and the descriptions pinning their selection clauses). New
e2e (`e2e/e2e_path.py`, real MCP stdio): the schema advertises `path`
optional on five tools and absent on motion, one call edits an unopened
file, cross-file switches announce themselves, `write(path=)` picks its
buffer, and the stale-dirty refusal holds. All eleven prior e2es re-run
green.

## v0.20: the op time budget (decided and implemented 2026-08-01)

Found in a pre-launch security review, not in a dogfood session: `matches`
with a catastrophic pattern (`(a+)+$b` over a 60-char line) pinned the
daemon at 100% CPU forever. The damage was not the hang itself but that it
was **unrecoverable**: `djinnvim shutdown`, the documented escape, also
timed out, because the wedged daemon never returns to `accept()`. SIGTERM
did not land either. It took `kill -9`. Same defect on the MCP side, where
every tool is `async def`, so one bad pattern blocks the event loop and the
whole server stops answering.

**The first fix was wrong, and measuring it is what saved us.** The obvious
answer is a watchdog thread that times the op out. It cannot work: CPython's
`re` neither checks for signals nor releases the GIL while backtracking, so
no other Python thread is ever scheduled. Measured, not reasoned about:
`Thread.join(2.0)` against such a pattern does not return in 2 s, it does
not return at all. That kills every in-process timeout, the watchdog thread
included, and it is pinned now as `test_regex_never_releases_the_gil` so a
future CPython change surfaces here instead of in an argument.

**What shipped is a fork oracle.** The op runs twice: first in a forked
child used purely as a *termination oracle* (its result is discarded, we
only ask whether it finished inside the budget, and it is SIGKILLed if it
did not), then for real in the parent, now knowing this pattern terminates
on this content. `fork` hands the child a copy-on-write snapshot of the
live Session for free, so there is nothing to serialize and no state to
merge back, which is what keeps this out of the session internals entirely.

The alternative was killing the process on overrun and letting the next
command respawn. Rejected: it takes every unwritten buffer with it because
one pattern was bad. The oracle keeps the contract every other djinnvim
failure keeps, a loud `error:` that changes nothing, and the e2e asserts
exactly that (an unwritten change made before the runaway pattern is still
pending after it, and still writes correctly).

Three honest costs. Every guarded op runs **twice**: measured at 3.2 ms →
13.5 ms per `matches` on a 10 000-line file, which is noise against a model
round trip, but it is real and it is not free. Only pure in-memory,
pattern-taking ops are guarded (`PATTERN_OPS`); `write` touches disk and
`open` takes no user regex, so a throwaway child must never repeat them.
And `fork` is POSIX, so the guard degrades to running inline where it is
missing rather than pretending to protect.

Budget is 10 s, `DJINNVIM_OP_BUDGET_SECONDS` overrides, `<= 0` disables it.

399 tests (9 new, including the GIL measurement, side-effect-runs-once, and
a check that the oracle child is actually reaped rather than the wedge just
moving into an orphan). New `e2e/e2e_guard.py` over real MCP stdio, which
is where this had to be proven: a unit test cannot see that the *server*
kept answering after the runaway pattern. All twelve prior e2es re-run
green.

## Appendix: superseded designs

Sketches and plans that were replaced. Kept because the replacement
reasoning only makes sense against them.

## The `viewport` tool sketch (superseded 2026-07-26 by `print`)
Superseded 2026-07-26 by `print` (same intent — an explicit bigger look —
but with ex addressing, cursor-moving paging, and named size tiers instead
of a `size` parameter). Original sketch:

- **Input:** either `around: "/pattern/"` or `lines: [start, end]`, optional `size` (default 5, max 100)
- **Output:** numbered lines with cursor marker if in range.

## The `undo` / `redo` tools (superseded 2026-07-11 by `u` in `edit`)
Superseded 2026-07-11 (see "Undo" above): undo is `u` inside `edit`, not a
separate tool; redo stays deferred.

## Evaluation: the original plan (superseded by the benchmark design)

Benchmark keyhole sessions against the read-whole-file-then-edit baseline:

1. **Tasks:** refactors on realistic files (rename across call sites, signature change, quote-style normalization, delete-all-matching) with known start state and known target — check exact output match.
2. **Metrics per task:** total tokens (input + output, separated), number of tool calls, wall-clock, exact-match correctness, and *silent-error rate* (wrong result with no error surfaced).
3. **Ablations:** with/without viewport echoes; with/without `matches` pre-check on rename tasks; viewport size 5 vs 9.
4. **Hypothesis:** keyhole wins on tokens for localized/repetitive edits in large files; baseline wins on small files (<100 lines) and heavy-restructuring tasks. Silent-error rate should be ~0 given loud failures + echoes.

## Implementation Notes (early stack sketch, largely superseded)

- Suggested stack: Node/TypeScript or Python MCP SDK; buffer as line array with a gap or piece-table only if perf demands (it won't for typical files).
- Text-object resolution: implement bracket/quote matching directly (simple scans); `t` object via a lenient tag scanner. Optionally back objects with tree-sitter later for language-aware `if`/function objects — but keep the vim surface syntax.
- Regex dialect: document it clearly in tool descriptions (recommend Rust `regex` / RE2 semantics; no lookbehind) so the model doesn't assume PCRE.
- Tool descriptions in the MCP schema should include 2–3 few-shot examples each — in-context examples materially improve command formation.
