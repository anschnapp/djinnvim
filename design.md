# Keyhole Editor — Design Document

An MCP server providing vim-inspired, pattern-anchored file navigation and editing for AI agents. The core idea: the agent never reads whole files. It hops between search hits and edits through small "viewports" (peepholes), the way a human uses vim — `/search`, look at the screen, edit.

## Motivation

Current agent editing flows are token-expensive on both sides:

- **Read side:** agents load entire files into context (a 2000-line file ≈ 15k tokens) even when the task touches 10 lines.
- **Write side:** str_replace-style tools require reproducing long verbatim spans (old text + new text) for every edit.

Keyhole editing replaces both with:

- **Navigation by pattern** (`/regex`, `f"`, text objects) instead of by reading — position is always established by *content*, never by counting or by holding the file in context.
- **Compact edit commands** (`ciw`, `dap`, `cs"'`) drawn from vim's count-free normal-mode subset, which is small, compositional, semantic, and deeply represented in LLM training data.
- **Viewport echoes:** every cursor-moving or editing command returns a small viewport (default: 2 lines above, cursor line, 2 lines below). The tool result *is* the screen. Errors become visible immediately instead of silently corrupting the file.

### Design principles

1. **Only use syntax already in the weights.** No novel DSL. Vim motions, text objects, vim-surround, and ex-style substitution are all heavily represented in training data. New *semantics* are fine; alien *surface syntax* is not.
2. **No counts, no cursor arithmetic.** LLMs are unreliable at `7j` / `d5k`. Everything is anchored by pattern or by semantic text object. Counted motions are deliberately not implemented.
3. **Every action echoes a viewport.** Silent state changes are forbidden. Navigation echoes where you landed; edits echo the post-edit region. Write-verification comes free; no separate re-read call needed.
4. **Global awareness via search visibility, not content.** Keyhole mode is blind to non-local consequences (e.g., 12 other call sites of a renamed function). Compensate with cheap match listings (`/pattern` reports match count; `matches` lists one line per hit), never with full-file dumps.

## Prior Art (surveyed 2026-07-09)

No direct competitor combines vim surface syntax, pattern-anchored count-free commands, viewport echoes, and the never-read-the-file discipline as a standalone MCP server. Nearest neighbors:

- **[texted](https://blog.cultivated.engineer/p/introducing-texted-a-text-editor)** — closest in thesis: headless editor-for-LLMs as an MCP server, navigates by `search-forward` instead of reading files. Differs in surface syntax (Emacs Lisp subset), no text objects, no viewport echoes. Read before building.
- **Remote-control-real-Neovim MCP servers** — [mcp-neovim-server](https://github.com/bigcodegen/mcp-neovim-server), [vim-mcp](https://github.com/iggredible/vim-mcp), [VimGPT](https://github.com/nsbradford/VimGPT): attach an agent to a live editor session. Whole-buffer exposure, no token-economy framing. Validates that vim syntax is well represented in model weights.
- **[SWE-Edit](https://arxiv.org/abs/2604.26102)** (Microsoft, 2026) — same motivation (context cost of editing), different mechanism: Viewer/Editor subagents with clean contexts. Relevant related work + eval methodology.
- **[antirez's tag-based EDIT tool](https://antirez.com/news/166)** — write-side token savings via line-number + checksum edits; no navigation story.
- **[inspect_evals VimGolf task](https://ukgovernmentbeis.github.io/inspect_evals/evals/reasoning/vimgolf_challenges/)** — 612 public challenges. **Rejected as an eval (2026-07-09):** VimGolf rewards keystroke minimization, the opposite of the real-world, clean, error-unprone editing keyhole targets. Not a goal, not optional; at most a for-fun exercise far later.

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

## v0 Status & Layout (as of 2026-07-09, evening)

**v0 is implemented and green.** Package `keyhole-editor`, Python ≥3.11, MCP Python SDK (FastMCP), entry point `keyhole` (`keyhole.server:main`).

**v0.1 is implemented and green (2026-07-09, late evening):** all four
features pulled forward from dogfood #1 — anchored-edit ambiguity counts,
`substitute`, surround (`cs`/`ds`/`ysiw`), `f`/`F` motions.

```
src/keyhole/
  buffer.py      ✅ Buffer/Cursor dataclasses, open/write, disk-staleness check,
                    saved_lines snapshot (for write's "N lines changed" report)
  viewport.py    ✅ renderer: line-number gutter, → cursor line, ^ column marker,
                    2/1/2 default context; CURSOR_STYLE config flag (caret only in v0)
  motion.py      ✅ /  ?  n  N  :N  gg  G  f<char>  F<char>; wrapping search
                    reports `match i of n (wrapped)`; f/F are strictly
                    cursor-line-local; find_matches shared with edit's anchor
  edit.py        ✅ anchored `at [Nth] /pattern/ <cmd>`, summaries append
                    `(match i of n)` (file-order index); ciw/caw, ci/ca+di/da
                    for ( { [ " ' `, diw/daw, dd, cc, D, C, x, r, o/O
                    (multi-line), A/I; cs/ds/ysiw with vim-surround nuances
                    (open-bracket replacement pads inner spaces, open-bracket
                    target trims them; close bracket = no padding);
                    single-line find_object (brackets: enclosing-pair scan,
                    quotes: pair-up scan with backslash escapes)
  substitute.py  ✅ :%s///, :s/// (cursor line), :N,M / $ / . / /pat/,/pat/
                    ranges, flags g i, :g/pat/d; output = count + compact
                    ±diff of changed lines (pre-edit line numbers), capped at
                    60 with first/last-5 elision; zero matches is a loud error
  server.py      ✅ 6 tools wired with few-shot examples; KEYHOLE_ROOT path
                    sandboxing; staleness check before edit/substitute/write
tests/           ✅ 115 tests (motion, edit, substitute, server round-trips,
                    viewport format)
```

Verified end-to-end over the MCP stdio protocol (scripted client running the
example session below: open → motion → anchored edits → matches → write; a
second v0.1 script covering f/F → cs → anchored ciw → :%s//g → :g//d → write).

Conventions decided during implementation (in addition to the earlier ones —
0-based cursor internally / 1-based in output; failed commands never touch
buffer or cursor; every success echoes a viewport; write appends trailing newline):

- **TEXT separator:** exactly one whitespace char separates a command from its
  TEXT; everything after it is verbatim (so `o     x = 1` inserts an indented
  line, `I # ` keeps its trailing space).
- **Search is strictly-after-cursor** (vim semantics): a match at the cursor
  position is skipped; wrap-around is reported as `(wrapped)`.
- **`n` is always forward, `N` always backward** (direction of the original
  search is not stored) — simpler state, documented in the tool description.
- **Change requires TEXT, delete forbids it** (`ciw` alone and `diw oops` both
  fail loudly); bare `o`/`O`/`cc` insert/leave an empty line.
- **`I` inserts at the first non-blank** (vim semantics), not column 0.
- **Deleted-on-disk ≠ stale:** if the file vanishes underneath the buffer,
  edits proceed and `write` recreates it (the buffer is the only copy);
  *modified*-on-disk still blocks edit/write until re-open.
- Searches render the `^` column marker; `:N`/`gg`/`G` (line-wise) do not.

Added during v0.1 (2026-07-09, late evening):

- **Anchors land at match START** — `at /retries=3/ ciw 4` changes `retries`,
  not the `3`; anchor on the value you want changed (`at /3\)/ ciw 4`).
  Caught live by the v0.1 e2e script; the ambiguity-count summary plus
  viewport made the miss instantly visible. Tool description should warn
  about this (not yet done — candidate for the cold-agent description pass).
- **`substitute` replacement is Python `re` syntax** (`\1` for groups), not
  vim's; documented in the tool description alongside the regex dialect.
- **Pattern-range second address** (`:/a/,/b/`) is searched forward from the
  first address (block semantics), not from the cursor like vim's `,` —
  matches the intent "from A to the next B"; backwards ranges fail loudly.
- **`substitute` diff line numbers are pre-edit** (matters when a replacement
  inserts newlines or `:g//d` deletes lines); `s///` moves the cursor to the
  last changed line (like vim), `:g//d` to where the first deleted line was.
- **`f`/`F` can't target a literal space** — motion commands are
  whitespace-stripped, so `f ` parses as bare `f` (loud error); use `/ /`
  for that rare case.

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
2. **Cold-agent tool description pass** — descriptions must carry a cold
   Opus agent alone. Known must-fixes: `edit` must warn that anchors land at
   match START (anchor on the value you want changed, e.g. `at /15\)/ ciw 60`,
   not `at /timeout=15/`) and that the anchored form takes edit commands
   only, not motions — both hit twice now (v0.1 e2e + dogfood #2).
3. **Design + build the benchmark** — see "Benchmark rethink" under
   Evaluation Plan; add model (Opus vs Fable, cold) as a swept dimension
   alongside file size.

## MCP Tools

### `open`
Open a file and set it as the active buffer.

- **Input:** `path` (string)
- **Output:** file metadata (path, line count, size, detected language) + viewport at line 1. Never the full content.
- Multiple buffers may be open; commands operate on the active buffer. `open` on an already-open file switches to it without reloading unless changed on disk.

### `motion`
Move the cursor. Accepts one motion command per call.

Supported motions:

| Command | Meaning |
|---|---|
| `/pattern` | Search forward (regex). Cursor moves to first match **after** cursor. Response includes total match count in file: `match 3 of 14`. |
| `?pattern` | Search backward. |
| `n` / `N` | Next / previous match of last search. |
| `:N` (e.g. `:80`) | Go to line N. (Ex syntax chosen over `80G` to keep line numbers explicit and unambiguous.) |
| `gg` / `G` | First / last line. |
| `f{char}` / `F{char}` | Move to next/previous occurrence of char **on the cursor line**. Updates column. |
| `0` / `$` | Start / end of line. |
| `w` / `b` / `e` | Word forward / back / end (single step, no counts). |
| `{` / `}` | Previous / next paragraph (blank-line delimited). |
| `%` | Jump to matching bracket under/after cursor. |

- **Output:** viewport with cursor marker. If a search has zero matches: explicit `no match: pattern` error, cursor unchanged.

### `edit`
Perform an editing command at the current cursor position, or at a pattern anchor in the same call.

**Anchored form (preferred):** `at /pattern/ <command>` — moves to first match after cursor, then applies the command. Optional ordinal: `at 2nd /pattern/ <command>`. This keeps navigate+edit in one call for the common case.

Supported commands (count-free normal-mode subset):

| Command | Meaning |
|---|---|
| `ciw TEXT`, `caw TEXT` | Change inner/around word to TEXT |
| `ci( TEXT`, `ci{`, `ci[`, `ci"`, `ci'`, `` ci` ``, `cit` | Change inside delimiters / tag |
| `di(`, `da(`, `diw`, `dap`, `dit`, ... | Delete text object (same object set as `c`) |
| `dd` | Delete cursor line |
| `cc TEXT` | Replace cursor line with TEXT |
| `D` / `C TEXT` | Delete / change to end of line |
| `x` / `r{char}` | Delete / replace char under cursor |
| `o TEXT` / `O TEXT` | Insert new line(s) below / above cursor. TEXT may be multi-line. |
| `A TEXT` / `I TEXT` | Append to end / insert at start of line |
| `cs{old}{new}` | Change surround (vim-surround), e.g. `cs"'`, `cs({` |
| `ds{char}` | Delete surround |
| `ysiw{char}` | Surround word (e.g. `ysiw"`) |
| `J` | Join line with next |
| `>>` / `<<` | Indent / dedent cursor line |
| `.` | Repeat last edit at current cursor position |

Text object set: `w`, `W`, `p` (paragraph), `(`/`)`, `{`/`}`, `[`/`]`, `"`, `'`, `` ` ``, `t` (HTML/XML tag), with `i` (inner) and `a` (around) variants.

- **Output:** post-edit viewport of the affected region, plus a one-line summary (`changed line 80`, `deleted lines 45–52`). For multi-line effects the viewport expands to cover the whole affected span ±2 lines.
- **Errors:** if the text object cannot be resolved at the cursor (e.g. `ci(` with no enclosing parens on the line), fail loudly with an explanatory message; never guess.

### `substitute`
Ex-style substitution for repetitive, file-wide, or ranged changes — the cases where a single pattern edit beats many keyhole hops.

- **Input:** `command` in ex syntax: `:%s/old/new/g`, `:10,40s/foo/bar/`, `:g/DEBUG/d`, `:/def parse/,/^$/s/x/y/g`
- **Output:** number of substitutions + a compact diff of changed lines (unified-diff style, changed lines only, capped — see Limits). This is the fresh "anchor" restatement of file content the agent can attend to.

### `matches`
Global search visibility without content. The antidote to keyhole blindness.

- **Input:** `pattern` (regex), optional `context: 0|1` (lines around each hit)
- **Output:** grep-style listing, one line per match with line numbers, capped at 50 hits (then `... and N more`). Tens of tokens instead of thousands.

Agents should call `matches` before any rename-like refactor to see all affected sites.

### `viewport`
Explicitly view a region without moving anything, when the agent wants a bigger look.

- **Input:** either `around: "/pattern/"` or `lines: [start, end]`, optional `size` (default 5, max 100)
- **Output:** numbered lines with cursor marker if in range.

### `write`
Save the active buffer to disk.

- **Output:** confirmation + lines changed since last write. Buffers are in-memory until written; `open` warns if a buffer has unwritten changes.

### `undo` / `redo`
Per-buffer undo stack, one edit per step. Output: viewport of restored region.

## Viewport Format

```
  78  def parse_config(path):
  79      opts = {}
→ 80      for line in open(path):
                       ^
  81          key, val = line.split("=")
  82          opts[key.strip()] = val
```

- Line numbers, right-aligned, two-space gutter.
- `→` marks the cursor line.
- A `^` column marker on the line below the cursor line, **only when column matters** (after `f`, `%`, `w`/`b`/`e`, or before char-wise objects like `ci(` where multiple candidate pairs exist on the line). Omit it after purely line-wise motions to save tokens.
- Default viewport: 2 above + cursor + 2 below (≈40 tokens). Configurable per-call via `size`.

## Error Handling

- Every failure is loud and specific: `no match`, `no enclosing ( on line 80`, `pattern matched 0 times`, `line 999 out of range (file has 412 lines)`.
- Failed commands never modify the buffer or move the cursor.
- If the file changed on disk since `open`, any `edit`/`substitute` fails with a staleness error and prompts a re-`open`.

## Limits & Safeguards

- `substitute` diffs capped at ~60 changed lines in output; beyond that, report count + first/last changed regions and suggest `matches` to inspect.
- `matches` capped at 50 hits.
- Regex: use a linear-time engine (RE2-style) or timeout to avoid catastrophic backtracking.
- Read-only mode flag for exploration sessions.
- All paths validated against an allowed root directory.

## Non-Goals (deliberately excluded)

- **Counted motions** (`3j`, `d5w`) — the known LLM weakness; pattern anchoring replaces them entirely.
- **Registers, marks, macros, visual mode** — session state that models track poorly; low value once edits are pattern-anchored.
- **A novel command DSL** — everything must look like vim/ex/vim-surround that the model already knows.
- **Full-file read tool** — intentionally absent to force the keyhole discipline. (Agents can fall back to their native file-read tools if truly needed.)

## Example Session

Task: in `config.py`, rename `Word` in one place, fix quote style.

```
open config.py
→ metadata + viewport at line 1

motion /Tosearch
→ match 1 of 3, viewport at line 41

motion :1            # or wherever; L1 from user flow
edit at /Word/ ciw hello_world
→ viewport: line 12 now reads `hello_world = ...`

motion f"
→ viewport with ^ under the quote

edit cs"'
→ viewport: quotes on line 12 are now single

write
→ saved, 2 lines changed
```

Total context cost: ~200 tokens for a session that would otherwise require a full-file read.

## Evaluation Plan

### Benchmark rethink (2026-07-09, to design next session)

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

### Original plan

Benchmark keyhole sessions against the read-whole-file-then-edit baseline:

1. **Tasks:** refactors on realistic files (rename across call sites, signature change, quote-style normalization, delete-all-matching) with known start state and known target — check exact output match.
2. **Metrics per task:** total tokens (input + output, separated), number of tool calls, wall-clock, exact-match correctness, and *silent-error rate* (wrong result with no error surfaced).
3. **Ablations:** with/without viewport echoes; with/without `matches` pre-check on rename tasks; viewport size 5 vs 9.
4. **Hypothesis:** keyhole wins on tokens for localized/repetitive edits in large files; baseline wins on small files (<100 lines) and heavy-restructuring tasks. Silent-error rate should be ~0 given loud failures + echoes.

## Implementation Notes

- Suggested stack: Node/TypeScript or Python MCP SDK; buffer as line array with a gap or piece-table only if perf demands (it won't for typical files).
- Text-object resolution: implement bracket/quote matching directly (simple scans); `t` object via a lenient tag scanner. Optionally back objects with tree-sitter later for language-aware `if`/function objects — but keep the vim surface syntax.
- Regex dialect: document it clearly in tool descriptions (recommend Rust `regex` / RE2 semantics; no lookbehind) so the model doesn't assume PCRE.
- Tool descriptions in the MCP schema should include 2–3 few-shot examples each — in-context examples materially improve command formation.
