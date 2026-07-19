# djinnvim — Design Document

Vim-inspired, pattern-anchored file navigation and editing for AI agents. The core idea: the agent never reads whole files. It hops between search hits and edits through small "viewports" (peepholes), the way a human uses vim — `/search`, look at the screen, edit.

**Naming (decided 2026-07-10):** the product is **djinnvim**; **"keyhole"** remains the term for the *interaction model* (keyhole editing, keyhole discipline) throughout this doc. Known caveat, accepted: `-vim` suffix names read like Neovim distros at first glance — the README must say "editing tool for AI agents, not a vim config" in sentence one.

## Interfaces (decided 2026-07-10)

Two user groups, two interfaces, **one program**: the same core is exposed both as an **MCP server** and as a **CLI driven by an agent skill**. Architecture that makes this cheap:

- All logic lives in an interface-neutral `Session` class (`session.py`): open buffers + active buffer as state, the six operations as string-in/string-out methods (errors included, as `error: ...` strings).
- `server.py` is a thin MCP wrapper (FastMCP registration + tool descriptions only). The future `cli.py` will be an equally thin argparse wrapper.
- **CLI state model (revised 2026-07-11): daemon + thin client, no state file.** A per-sandbox-root daemon holds the live `Session`; the CLI is a tiny client talking to it over a Unix socket. Reverses the 2026-07-10 state-file decision: undo stacks and registers made the serialize-every-`Session`-field burden grow with each feature, and a live process gives exact semantic parity with the MCP path — same in-memory `Session`, zero serialization drift. **Stateless session-to-session:** the `Session` lives and dies with the daemon process — nothing is persisted across restarts, matching the MCP server's semantics exactly (unwritten buffers, registers, and undo stacks are gone when the daemon exits; disk holds only what was `write`n). Lifecycle is ssh-agent-shaped (auto-spawn on first client call, idle self-exit, die/respawn on binary version mismatch). The daemon is conceptually just the MCP server kept alive for people who don't run MCP clients; **the agent-facing MCP interface itself stays local stdio** (spawned per client, as today) — the socket exists only because a fresh-process-per-command CLI needs something long-running to talk to. Open questions, to settle when the CLI is actually built (still post-benchmark): socket naming per root, exact spawn/shutdown policy, and whether the daemon speaks MCP framing over the socket (CLI = thin MCP client) or a minimal JSON-RPC.
- **Only the MCP stack is built and tested for now**; the CLI + skill come after the benchmark phase. The cold-agent description pass benefits both: the same descriptions that must carry a cold Opus agent over MCP become the backbone of the skill's SKILL.md.

## Motivation

Current agent editing flows are token-expensive on both sides:

- **Read side:** agents load entire files into context (a 2000-line file ≈ 15k tokens) even when the task touches 10 lines.
- **Write side:** str_replace-style tools require reproducing long verbatim spans (old text + new text) for every edit.

Keyhole editing replaces both with:

- **Navigation by pattern** (`/regex`, `f"`, text objects) instead of by reading — position is always established by *content*, never by counting or by holding the file in context.
- **Compact edit commands** (`ciw`, `dap`, `cs"'`) drawn from vim's count-free normal-mode subset, which is small, compositional, semantic, and deeply represented in LLM training data.
- **Viewport echoes:** every cursor-moving or editing command returns a small viewport (default: 2 lines above, cursor line, 2 lines below). The tool result *is* the screen. Errors become visible immediately instead of silently corrupting the file.

### The permission-management argument (added 2026-07-14; README candidate)

There is a second audience beyond token economy: users who run agents under
restrictive permissions. The strong baseline's editing power comes almost
entirely from Bash (`grep`+`sed`) — exactly the permission a cautious user
denies, since it's arbitrary command execution (and shell allowlisting is
leaky: `sed` allowed "for editing" can execute commands via its `e` flag).
Denying Bash today means losing powerful search (`grep`) and bulk
search-replace (`sed`) entirely. djinnvim gives that class of capability
back through a narrowly scoped multi-tool: `matches` is the grep, `substitute`
/ `at each` are the sed — with a containment story `sed -i` can't offer:

- `DJINNVIM_ROOT` sandboxing — every path validated against the root.
- Nothing touches disk until `write`; the buffer is a natural review point,
  plus undo, staleness checks, and echo discipline.
- Per-tool permission granularity: a client can allow read-only exploration
  (`open`/`motion`/`matches`) while gating `edit`/`substitute`/`write`.

Scope of the claim, stated honestly: this compensates for the *editing and
search* disadvantage of denying shell access, not the whole disadvantage
(a Bash-less agent still can't run tests, git, or builds). And the strong
angle is write-side blast radius and auditability, not confidentiality —
the agent can still read anything under the root via viewports, just slowly.
The benchmark's keyhole condition (all native file/shell tools disallowed)
doubles as evidence for this claim: it *is* the locked-down configuration.

### What this is and isn't: ed's discipline, vim's vocabulary (framed 2026-07-15; README candidate)

Settled in conversation after the honest objection "no vim user would work
like this — vim users compose long sequences, and LLMs could take one big
regex shot instead." Both halves of the objection are true; neither changes
the design. Recording why, because the framing is the answer:

- **This is not vim, and shouldn't claim vim's economy.** Vim optimizes
  keystroke count under *free feedback* — the screen is always there,
  updated instantly, so a human can afford long compositions and macros.
  For an LLM the economics are exactly inverted: emitting tokens is cheap,
  but every glance at the buffer costs a full round trip. A tool that
  faithfully reproduced vim's design point for agents would let them fire
  long keystroke sequences blind — precisely what this design rejects.
- **The true ancestor is ed/ex.** Pattern addressing, one command per
  call, terse echoes — ed's discipline existed because *its* feedback was
  expensive (a paper teletype). The LLM's constraint profile matches the
  teletype era, not the screen era. Vim is the *vocabulary donor* (text
  objects, surround — the genuinely vim-native additions ed never had,
  and the syntax dense in the weights); ed is the ancestor. "No vim user
  would work like this" is accepted: the agent isn't a vim user, it's a
  blind editor operator paying per glance — design for that user.
- **Declarative big shots stay open; imperative big shots stay closed.**
  LLMs genuinely are good at large complex regexes, and that lane exists:
  `substitute` takes arbitrary Python regex, groups, ranges, offsets —
  nothing stops the model from taking the big shot. But a regex is
  *declarative* (one pattern → one transformation, no intermediate state),
  while a keystroke *sequence* is *imperative*: the model must simulate
  the buffer state after each command to compose the next one, blind —
  the same weakness class as counting. That distinction, not regex
  skepticism, is why one-command-per-call holds and sequences/macros are
  rejected (see Non-Goals). The evidence so far says big shots are exactly
  where silent errors live: the composite escape leak (`load_records\(`
  written silently by one clever `:%s//g`), haiku's six blank-miscounting
  range deletes, the baseline's 6/36 silent trap failures — all big-shot
  regex or sed.
- **The one-command limit does NOT multiply `at each` cost.** The
  multiplication over *sites* is already gone (one call for N matches);
  the limit only multiplies over *commands*: a per-site transformation
  needing `ciw` then `cs"'` is two `at each` calls, not 2N — each pass
  transactional, each echoing its own diff before the next compounds on
  it. A 3-command refactor at 50 sites costs 3 calls instead of 1; the
  restriction's total price is C−1 calls, bought back as a diff between
  every pass. Honest residual gap: pass 2 must re-anchor on the
  *post-pass-1* text, occasionally awkward to pattern-match. If that
  bites in practice, the surgical concession is a short sequence inside
  `at each` only (where per-site viewports are already traded for a
  diff), still transactional — parked behind the evidence gate; no
  current benchmark task needs it.
- **README consequence:** the pitch is not "vim for AIs" — that framing
  invites exactly this objection, since real vim is sequences and macros.
  It's "ed's discipline with vim's vocabulary, because an agent's
  feedback channel costs what a teletype cost." The benchmark's baseline
  condition is literally the alternative hypothesis (let the model take
  big sed/regex shots); the silent-error column is the measured answer.

### Design principles

1. **Only use syntax already in the weights.** No novel DSL. Vim motions, text objects, vim-surround, and ex-style substitution are all heavily represented in training data. New *semantics* are fine; alien *surface syntax* is not.
   **Corollary — false friends are worse than honest English** (made explicit 2026-07-14; it's the line the anchored form already walked): vim spelling is used only where behavior is vim-exact. Wherever we deviate, the surface is plain-English glue (`at /pattern/ ciw foo`, the planned `at each /pattern/`) rather than a vim lookalike — a surface that *looks* like vim but behaves differently makes the model trust its priors over the tool description, and priors then actively generate the inputs we reject (in vim, `:g/pat/normal ciwfoo` is a keystroke stream with no TEXT separator and per-line addressing; a constrained `:g/normal` of ours would break on exactly the most idiomatic input). The weights pay for the *commands*; the addressing glue just has to be readable and described. And when a vim reflex hits a deliberately unsupported surface, the loud error names the supported form (`.` → reissue the anchored edit; `:g/pat/normal` → `at each`), converting the reflex into a signpost instead of a trap.
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
v1 design" under Evaluation Plan for the decisions. `benchmark/gen.py`
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
(see "Round 2 tasks" under Evaluation Plan for the analysis and the six
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

```
src/djinnvim/
  buffer.py      ✅ Buffer/Cursor dataclasses, open/write, disk-staleness check,
                    saved_lines snapshot (for write's "N lines changed" report);
                    v0.4: UndoEntry + capped undo_stack (MAX_UNDO 100)
  viewport.py    ✅ renderer: line-number gutter, → cursor line, ^ column marker,
                    2/1/2 default context; v0.7: labeled caret (`^ on "r" of
                    "retries"`, word = exact ciw span), CURSOR_STYLE via
                    DJINNVIM_CURSOR_STYLE env (caret-labeled default | caret)
  motion.py      ✅ /  ?  n  N  :N  gg  G  f<char>  F<char>; wrapping search
                    reports `match i of n (wrapped)`; f/F are strictly
                    cursor-line-local; find_matches shared with edit's anchor
  edit.py        ✅ anchored `at [Nth] /pattern/ <cmd>`, summaries append
                    `(match i of n)` (file-order index); ciw/caw, ci/ca+di/da
                    for ( { [ " ' `, diw/daw, cip/cap+dip/dap (paragraph,
                    line-wise), dd, cc, D, C, x, r, o/O (multi-line), A/I;
                    cs/ds/ysiw with vim-surround nuances (open-bracket
                    replacement pads inner spaces, open-bracket target trims
                    them; close bracket = no padding); single-line find_object
                    (brackets: enclosing-pair scan, quotes: pair-up scan with
                    backslash escapes); v0.3 registers: yy/y{i,a}{obj} yanks
                    (no dirty, no viewport — echo carries content), p/P paste
                    (linewise below/above, charwise within line), `"name`
                    prefix (word names take a space, `"ayy` vim-style works),
                    prefix composes with the anchor in either order; v0.4:
                    `u` undo (restored-region viewport, names the undone
                    command, remaining-step count); v0.6: i/a inserts
                    (before/after cursor char, anchored = at the match);
                    v0.8: `at each /pat/ <cmd>` global form (per-match,
                    bottom-up + revalidation, transactional, diff echo,
                    one undo step; y/p/u/registers rejected)
  registers.py   ✅ Register dataclass (lines + linewise kind), shared
                    preview/clip/display/missing-register helpers for both
                    surfaces
  substitute.py  ✅ :%s///, :s/// (cursor line), :N,M / $ / . / /pat/,/pat/
                    ranges, flags g i, :g/pat/d; output = count + compact
                    ±diff of changed lines (pre-edit line numbers), capped at
                    60 with first/last-5 elision; zero matches is a loud error;
                    ex-range register fallback: :RANGE y/d NAME, plain
                    :RANGE d (no register); :put removed in v0.3 (paste
                    with p/P in edit); v0.5: +N/-N address offsets on
                    patterns, line numbers, $ and .; v0.6: backslash-
                    punctuation in replacements unescaped vim-style;
                    v0.8: diff renderer public (diff_lines, shared with
                    edit's at-each; renders pure insertions), :g/pat/norm
                    signposts `at each`
  session.py     ✅ interface-neutral Session facade (2026-07-10): buffer
                    registry + active buffer + the six operations as
                    string-in/string-out methods; root path sandboxing;
                    staleness check before edit/substitute/write
  server.py      ✅ thin MCP wrapper: FastMCP registration + tool
                    descriptions with few-shot examples; DJINNVIM_ROOT env
                    var sets the sandbox root; v0.6: structured_output=False
                    on every tool (plain-text results — the structured
                    {"result": ...} form reached the model JSON-escaped)
                    + descriptions cut to ~half
tests/           ✅ 267 tests (motion, edit, substitute, registers, undo,
                    address offsets, i/a inserts, replacement unescaping,
                    at-each global edits, server round-trips, viewport
                    format + caret labels, benchmark gen/report; v0.9:
                    dogfood #4 echo regressions — exact at-each diff,
                    compact batch-undo diff, exact write count)
```

Verified end-to-end over the MCP stdio protocol (scripted client running the
example session below: open → motion → anchored edits → matches → write; a
second v0.1 script covering f/F → cs → anchored ciw → :%s//g → :g//d → write;
a third script covering a cross-file function move — updated for v0.3 to
anchored `"block dap` cut → wrong-name `p` recovery → `G` → `"block p` →
write, exact target diffs — kept in the repo at `e2e/e2e_registers.py`; run
with `.venv/bin/python`, not pytest).

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
   see "Benchmark rethink" under Evaluation Plan; add model (Opus vs Fable,
   cold) as a swept dimension alongside file size.

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

The original ex-only design below is kept for the record; its `:put` is
gone and its `:RANGE y/d NAME` forms remain as the fallback described above.

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
  surface), not the separate `undo` tool sketched earlier in this doc — one
  less tool description for a cold agent to discover.
- **One edit per step; `u` crosses `write` boundaries** (vim semantics —
  `write` isn't special from the buffer's perspective).
- **No redo** — "undid, then regretted it" is rare, and redo drags in
  branch-on-edit-after-undo semantics for no payoff. Stays deferred.
- **Echo:** viewport of the restored region (visibility rule as usual);
  summary names the undone command.
- Implementation: per-buffer snapshot stack of the line list (+ cursor)
  taken before each successful mutation; capped depth.

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

**Global form (v0.8):** `at each /pattern/ <command>` — applies one edit command at *every* match (per match, column-precise; bottom-up; transactional; one undo step). Echoes a substitute-style compact diff instead of a viewport. `y`/`p`/`u` and register prefixes are not allowed here.

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
| `i TEXT` / `a TEXT` | Insert before / append after the cursor char (v0.6). Anchored, `i` inserts before the match; `a` lands after the match's FIRST char (vim semantics — documented footgun). |
| `cs{old}{new}` | Change surround (vim-surround), e.g. `cs"'`, `cs({` |
| `ds{char}` | Delete surround |
| `ysiw{char}` | Surround word (e.g. `ysiw"`) |
| `J` | Join line with next |
| `>>` / `<<` | Indent / dedent cursor line |
| `yy`, `yiw`, `yap`, ... | Yank line / text object into a register (buffer untouched) |
| `p` / `P` | Paste register: below/above cursor line (linewise), after/at cursor (charwise) |
| `"name <cmd>` | Register prefix for `y`/`d`/`p`/`P`: `"block yap`, `"block dd` (cut), `"block p`. Word names take a space; single letters also work vim-style (`"ayy`). Bare `y`→unnamed register; bare deletes never touch registers. |

Text object set: `w`, `W`, `p` (paragraph), `(`/`)`, `{`/`}`, `[`/`]`, `"`, `'`, `` ` ``, `t` (HTML/XML tag), with `i` (inner) and `a` (around) variants.

- **Output:** post-edit viewport of the affected region, plus a one-line summary (`changed line 80`, `deleted lines 45–52`). For multi-line effects the viewport expands to cover the whole affected span ±2 lines.
- **Errors:** if the text object cannot be resolved at the cursor (e.g. `ci(` with no enclosing parens on the line), fail loudly with an explanatory message; never guess.

### `substitute`
Ex-style substitution for repetitive, file-wide, or ranged changes — the cases where a single pattern edit beats many keyhole hops.

- **Input:** `command` in ex syntax: `:%s/old/new/g`, `:10,40s/foo/bar/`, `:g/DEBUG/d`, `:/def parse/,/^$/s/x/y/g`
- **Output:** number of substitutions + a compact diff of changed lines (unified-diff style, changed lines only, capped — see Limits). This is the fresh "anchor" restatement of file content the agent can attend to.
- Also carries the ex-range register fallback: `:RANGE y NAME` / `:RANGE d NAME` for pattern-bounded blocks that text objects can't select (paste back with `p` in `edit`).

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
Superseded 2026-07-11 (see "Undo" above): undo is `u` inside `edit`, not a
separate tool; redo stays deferred.

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
- **`.` repeat (rejected 2026-07-14, moved here from the deferred list).**
  Its referent is invisible state — "what does `.` currently refer to" lives
  only in implicit history (murky across failed commands, `u`, intervening
  yanks/pastes), exactly the state-models-track-poorly category this section
  exists for. And it buys nothing: search is strictly-after-cursor, so
  **reissuing the identical anchored edit *is* the dot formula** — one call
  per site, re-anchored by pattern each time (safer than a blind replay at
  the cursor), each repeat echoing `(match i of n)`. Vim needs `.` because
  keystrokes cost humans effort; retyping a short explicit command costs an
  LLM ~10 tokens and is self-documenting. A cold agent that tries `.` gets
  the loud supported-commands error, buffer untouched — benign, unlike the
  undo case that justified waiving the evidence gate for `u`.
- **Invisible registers, marks, macros, visual mode** — session state that models track poorly. For macros/sequences specifically, the deeper reason is the declarative/imperative line drawn in "What this is and isn't" above: composing a sequence means simulating intermediate buffer state blind. Amended 2026-07-10: *visible* registers (every cut/yank echoes name + content; wrong names dump the full register list) are in-design — see "Registers: cut / yank / put". What stays excluded is register state the agent can't see in the transcript.
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

### Benchmark v1 design (decided 2026-07-11)

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

### Sweep scope revisions (decided 2026-07-15)

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

### Sweep results so far (recorded 2026-07-16)

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

### Post-sweep queue (recorded 2026-07-18)

1. **Bug, confirmed live, next session:** `motion`'s search status
   reports `match 1 of 1` even when multiple matches exist (user
   repro'd manually; `matches` lists several hits, `/pattern` claims
   1 of 1). Echo-discipline critical — the `match i of n` count is
   what principle #4 leans on for ambiguity awareness, and dogfoods
   #1–#3 credited it with catching decoys. A debugging breadcrumb
   (`ohits` + todo comment) is parked in `motion.py`; write a failing
   repro first, then fix.
2. **Discussion point, not yet decided: root confinement hardening.**
   Goal: djinnvim must operate on the correct project workdir and be
   unable to read/edit anything outside it — same containment posture
   as Claude Code's native Edit tool. Current state: `Session`
   resolves every path and rejects those not under the root
   (`session.py`); root = `DJINNVIM_ROOT` env var, **falling back to
   the server process's cwd**. Questions to settle in conversation:
   is the cwd fallback the right default for real MCP-client use
   (Claude Code spawns stdio servers with the project dir as cwd —
   but other clients may not, and a wrong cwd silently widens the
   sandbox to wherever the server happened to start); should the
   fallback be removed (require explicit `DJINNVIM_ROOT`, fail loudly
   without it) or announced (root stated in every `open` echo);
   symlink/TOCTOU review (`.resolve()` before the `is_relative_to`
   check handles symlink escapes — verify with tests, including a
   symlink *inside* the root pointing outside).

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
