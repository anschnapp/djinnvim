# djinnvim — Design Document

Vim-inspired, pattern-anchored file navigation and editing for AI agents. The core idea: the agent never reads whole files. It hops between search hits and edits through small "viewports" (peepholes), the way a human uses vim — `/search`, look at the screen, edit.

**Naming (decided 2026-07-10):** the product is **djinnvim**; **"keyhole"** remains the term for the *interaction model* (keyhole editing, keyhole discipline) throughout this doc. Known caveat, accepted: `-vim` suffix names read like Neovim distros at first glance — the README must say "editing tool for AI agents, not a vim config" in sentence one.

**How this doc is split (2026-07-26):** design.md describes the project as
it *is* - the shape, the surface, the reasoning that still binds. The
chronological record of how it got here (every version entry, dogfood
session, benchmark round, reversal) lives in
[decisions.md](decisions.md). Reading design.md alone is meant to be
enough to join a feature discussion; reach for decisions.md when you want
the argument behind a decision, or the evidence gate a parked feature is
waiting on.

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
  **(Reversed 2026-07-19, user decision:** the README *embraces* "vim
  for AIs" — it matches the logo and the project name, and the same
  argument is kept but inverted: a vim built honestly *for AIs* must
  work like ed, because an agent perceives like a teletype user, not a
  screen user. Same ed-discipline substance, friendlier front door;
  tagline is "Vim for AI agents: keyhole editing with vim's vocabulary
  and ed's discipline".)

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
- **Invisible registers, marks, macros, visual mode** — session state that models track poorly. For macros/sequences specifically, the deeper reason is the declarative/imperative line drawn in "What this is and isn't" above: composing a sequence means simulating intermediate buffer state blind. Amended 2026-07-10: *visible* registers (every cut/yank echoes name + content; wrong names dump the full register list) are in-design — see the register rules under Conventions. What stays excluded is register state the agent can't see in the transcript.
- **A novel command DSL** — everything must look like vim/ex/vim-surround that the model already knows.
- **Full-file read tool** — intentionally absent to force the keyhole discipline. (Agents can fall back to their native file-read tools if truly needed.)

## Architecture

**One program, two interfaces.** All logic lives in an interface-neutral
`Session` class (`session.py`): open buffers + active buffer as state, the
seven operations as string-in/string-out methods (errors included, as
`error: ...` strings). Both front ends are thin wrappers over it:

- **MCP server** (`server.py`): FastMCP registration + tool descriptions
  only. Spawned per client over local stdio. Tools are `async` with an
  injected `Context` so client roots can be fetched lazily.
  `structured_output=False` on every tool - results must reach the model as
  plain multi-line text, not JSON-escaped structured content.
- **CLI** (`cli.py`) + **daemon** (`daemon.py`): a fresh-process-per-command
  client talking to a long-lived daemon that holds the live `Session`. The
  daemon is conceptually just the MCP server kept alive for people who
  don't run MCP clients; it exists only because a stateless CLI needs
  something long-running to talk to.

**Why a daemon and not a state file:** undo stacks and registers made the
serialize-every-`Session`-field burden grow with each feature, and a live
process gives exact semantic parity with the MCP path - same in-memory
`Session`, zero serialization drift.

**Stateless session-to-session, both paths.** Nothing is persisted across
process death: unwritten buffers, registers, cursor and undo stacks are
gone when the server or daemon exits; disk holds only what was `write`n.
The failure is loud, not silent - the next command gets a fresh empty
`Session` and says "no active buffer" instead of operating on ghost state.

**Engine: from-scratch Python, no embedded Neovim.** Buffer is a plain list
of lines. The reason is control over exactly what the agent sees back,
which the echo discipline and the eval ablations both require.

### Code layout

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
                    for ( { [ " ' `, diw/daw, dip/dap (paragraph,
                    line-wise, delete only — v0.18 dropped cip/cap), dd,
                    cc, D, C, x, r, o/O (multi-line), A/I;
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
                    one undo step; y/p/u/registers rejected);
                    v0.17: literal anchors `at "text" <cmd>` (escaped,
                    composes with ordinal/offset/at-each), malformed-
                    anchor + ex-address signpost errors;
                    v0.18: `cc` autoindents like o/O (`cc!` opts out),
                    cip/cap removed with a two-step signpost
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
  printcmd.py    ✅ v0.16: the print tool — ex addressing reused from
                    substitute (_split_range/_resolve_range), window words
                    above/below/around × tiny(8)/middle(25)/long(50) or a
                    number, span cap 101, cursor moves only on an address
  session.py     ✅ interface-neutral Session facade (2026-07-10): buffer
                    registry + active buffer + the six operations as
                    string-in/string-out methods; staleness check before
                    edit/substitute/write; v0.11: multi-root sandboxing
                    (any-of-roots containment at open, resolve-before-
                    check, single-root relative resolution, write-time
                    revalidation); v0.19: _switch/_activate/_enter — the
                    optional `path` on every op but motion, switch note,
                    no-discard carve-out
  roots.py       ✅ v0.11: sandbox root resolution — DJINNVIM_ROOTS
                    (pathsep list, exclusive) / DJINNVIM_ROOT alias,
                    per-source `/`+$HOME sanity refusal,
                    CLAUDE_PROJECT_DIR→cwd fallback
  server.py      ✅ thin MCP wrapper: FastMCP registration + tool
                    descriptions with few-shot examples; v0.6:
                    structured_output=False on every tool (plain-text
                    results — the structured {"result": ...} form reached
                    the model JSON-escaped) + descriptions cut to ~half;
                    v0.11: async tools with injected Context — lazy client
                    roots/list fetch, list_changed → stale-flag refetch,
                    env roots pinned/exclusive; v0.18: INSTRUCTIONS
                    (server-level, cross-cutting guidance) +
                    _dedent_descriptions(), both under the 2048-char
                    client cap; v0.19: optional `path` params + selection
                    clauses leading each entry-point description
tests/           ✅ 390 tests (motion, edit, substitute, print, registers, undo,
                    address offsets, i/a inserts, replacement unescaping,
                    at-each global edits, server round-trips, viewport
                    format + caret labels, benchmark gen/report; v0.9:
                    dogfood #4 echo regressions — exact at-each diff,
                    compact batch-undo diff, exact write count; v0.11:
                    multi-root sandbox — traversal/symlink containment,
                    env parsing, per-source refusals, write revalidation,
                    server resolution chain; v0.19: optional-path wire
                    shape, CLI -f flag, selection clauses pinned)
```

## The seven tools

The same seven operations are the MCP tool set and the CLI verb set
(`open`, `motion`, `edit`, `matches`, `substitute`, `print`, `write`).
Descriptions in the MCP schema carry few-shot examples; on the CLI side
`skill/SKILL.md` plays that role.

**The guidance budget (v0.18).** Claude Code truncates every MCP-supplied
string at **2048 characters**, silently, appending `… [truncated]`. That is
a client limit, not an MCP one, and it applies per tool description, to the
server's `instructions`, and to prompt bodies. `edit` had grown to 3944 and
had been over the cap since 2026-07-14, so 48% of it - the indent rule,
registers, undo, every example - reached no model; the discovery is dogfood
#10's, recorded in decisions.md. Two consequences are now structural:

- **Cross-cutting guidance lives in `INSTRUCTIONS`** (`server.py`), the
  once-per-session channel shared by all seven tools: the keyhole loop, no
  counts / one command per call, TEXT-inline, the newline asymmetry, the
  indentation contract, buffer-versus-disk, read-the-echo. Descriptions
  keep only what is specific to their tool, and **one fact lives in one
  place** or the copies drift. The single deliberate duplicate is the
  indent rule, kept as a clause in `edit` as well, because instructions are
  a client courtesy while descriptions are the channel every client must
  pass to the model.
- **Descriptions are written as vim deltas.** Models know vim; the budget
  is spent on what differs (anchoring replaces moving the cursor, `at each`
  replaces `:g//normal`, TEXT is inline, no counts), not on teaching vim.
  This is also why making a command vim-exact *buys budget*: v0.18's `cc`
  fix shrank the indent rule from a paragraph to a clause.

### Being chosen: the selection problem (v0.19)

Everything above assumes the model already decided to use djinnvim. Live
use in a third-party harness (Copilot, Opus 4.8, ordinary source files)
showed it never getting picked at all, so v0.19 treats *selection* as its
own design surface. Two causes, and only the second is about wording:

- **The arithmetic was against us.** A minimal change cost `open` + `edit`
  + `write`, three calls, against a native editor's one stateless call.
  When the model has already read the file for other reasons, the read-side
  saving is spent before the edit even comes up, so on an ordinary file the
  model was pricing correctly. The fix is mechanical: **every op but
  `motion` takes an optional `path`** (see below), which removes the setup
  call and, just as important, makes each tool *read* as self-contained in
  the schema instead of "requires prior stateful setup".
- **Nothing in the schema said when to prefer this.** Every description
  answered *how*, in a tool list where selection is decided on the first
  sentence or two. Each entry-point description (`edit`, `matches`,
  `print`, `substitute`) now leads with the condition under which it wins,
  and `edit` carries the honest negative ("not for creating files or
  rewriting one wholesale"). The negative is load-bearing, not politeness:
  a tool that says where it loses gets believed about where it wins, and it
  is also what keeps this from degenerating into "always use djinnvim".

**Selection guidance is the second deliberate duplicate** (after the indent
rule) between `INSTRUCTIONS` and the descriptions. The reason is the same:
`instructions` is a client courtesy that several clients drop entirely, and
Copilot is exactly that case, so the reason to pick a tool has to survive in
the channel every client must pass on. Written as a lead clause replacing
each flat definition sentence, not as an added paragraph - the whole point
of the budget section is that there is nothing to spare. `edit` had to give
back ~90 chars to fit; one example line went, because it duplicated the
register paragraph above it verbatim.

Honest scope: on a 300-line file with one edit, djinnvim probably *should*
lose, and no description should try to win that case. The goal is being
picked when the condition holds, which requires the condition to be stated.

Both caps are enforced by tests plus `e2e/e2e_budget.py`, which measures
what actually crosses the wire. Docstring indentation counts against the
budget, so `_dedent_descriptions()` strips it at import.

### The optional `path` (v0.19)

`edit`, `substitute`, `print`, `matches` and `write` all take an optional
`path`, defined as **exactly `open(path)` first, nothing else changed** -
one rule, no per-tool drift. Consequences worth stating:

- **`open` becomes optional**, kept for when you want the file's header or
  to switch back to an already-open buffer. The three-call floor is gone: a
  one-line change is `edit(cmd, path=...)` then `write(path=...)`.
- **The switch is announced** - `[now on /abs/path — N lines]` prefixes the
  echo whenever the active buffer actually changed, and stays silent when
  the path names the buffer already active, so repeated calls carry no
  noise. A changed active buffer is a state change and the no-silent-state
  rule applies to it. `write` omits the note only because every one of its
  echoes names the path itself.
- **One carve-out: an implicit switch never discards unwritten changes.**
  Explicit `open` reloads a stale file and says so; `path=` on a buffer
  that is *both* dirty and stale raises the usual staleness error instead.
  Implicit actions must not destroy data. The visible cost is that
  `print(path=X)` can fail where bare `print()` succeeds, since `path` is a
  request to open and that open cannot be honored safely.
- **`motion` is deliberately excluded.** It is a within-file cursor op;
  "open this file and jump to a pattern" is what `print`/`matches` with a
  path already do better, and the surface stays smaller.
- **CLI: `-f/--file`** on the same five verbs. It matters more there than
  over MCP, since CLI processes are stateless and the file has to be named
  somewhere anyway.

### `open`
Open a file and set it as the active buffer. Optional since v0.19 (see above).

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

That list is exhaustive - `motion` supports exactly those. Sketched but
**never implemented, and never missed in nine dogfoods:** `0` / `$`
(start/end of line), `w` / `b` / `e` (word steps), `{` / `}` (paragraph
hops), `%` (matching bracket).

- **Output:** viewport with cursor marker. If a search has zero matches: explicit `no match: pattern` error, cursor unchanged.

### `edit`
Perform an editing command at the current cursor position, or at a pattern anchor in the same call.

**Anchored form (preferred):** `at /pattern/ <command>` — moves to first match after cursor, then applies the command. Optional ordinal: `at 2nd /pattern/ <command>`. This keeps navigate+edit in one call for the common case. **Literal form (v0.17):** `at "literal text" <command>` — the text is escaped, so an anchor full of regex punctuation needs no backslashes; ordinals, `+N`/`-N` offsets and `at each` all compose with it.

**Global form (v0.8):** `at each /pattern/ <command>` — applies one edit command at *every* match (per match, column-precise; bottom-up; transactional; one undo step). Echoes a substitute-style compact diff instead of a viewport. `y`/`p`/`u` and register prefixes are not allowed here.

**Anchor offsets (v0.14):** `at [Nth] /pattern/[+N|-N] <cmd>` — after
choosing the match the cursor moves N whole lines and lands at column 0
(line-wise, mirroring `substitute`'s address offsets; without an offset the
match column is kept). Out-of-range offsets are loud and touch nothing; the
summary note becomes `(match i of n, offset -1)`. The banner idiom is
`at /# Merge logic/-1 O text` — insert above the banner the match sits
inside, one call instead of three. `at each` is deliberately NOT extended:
its per-match column precision is the point, and an offset there breaks
site revalidation.

**Undo:** `u` undoes one edit step (per-buffer capped snapshot stack;
content-changing edits and substitutions push, yanks and failed commands
don't). It crosses `write` boundaries — `write` isn't special from the
buffer's perspective. Registers survive undo (vim semantics). An `at each`
batch is one step and echoes the inverted compact diff, not a
first-to-last-site viewport (which would be a full-file read in disguise).
No redo.

Supported commands (count-free normal-mode subset):

| Command | Meaning |
|---|---|
| `ciw TEXT`, `caw TEXT` | Change inner/around word to TEXT |
| `ci( TEXT`, `ci{`, `ci[`, `ci"`, `ci'`, `` ci` `` | Change inside delimiters |
| `di(`, `da(`, `diw`, `dap`, ... | Delete text object (same object set as `c`) |
| `dd` | Delete cursor line |
| `cc TEXT` | Replace cursor line with TEXT. **Inherits the line's own indentation** (v0.18, vim autoindent); `cc!` opts out to literal TEXT. |
| `D` / `C TEXT` | Delete / change to end of line |
| `x` / `r{char}` | Delete / replace char under cursor |
| `o TEXT` / `O TEXT` | Insert new line(s) below / above cursor. TEXT may be multi-line. **Inherits the reference line's indentation** (v0.15); TEXT's own leading whitespace stacks on top of it, blank lines within TEXT stay truly empty. Bare `o`/`O` inserts exactly one empty line. |
| `o! TEXT` / `O! TEXT` | Same, but literal TEXT — no inherited indent (for pasting an already-absolutely-indented block). Bang = vim's override, not a false friend. |
| `A TEXT` / `I TEXT` | Append to end / insert at start of line |
| `i TEXT` / `a TEXT` | Insert before / append after the cursor char (v0.6). Anchored, `i` inserts before the match; `a` lands after the match's FIRST char (vim semantics — documented footgun). |
| `cs{old}{new}` | Change surround (vim-surround), e.g. `cs"'`, `cs({` |
| `ds{char}` | Delete surround |
| `ysiw{char}` | Surround word (e.g. `ysiw"`) |
| `u` | Undo one step (see above) |
| `yy`, `yiw`, `yap`, ... | Yank line / text object into a register (buffer untouched) |
| `p` / `P` | Paste register: below/above cursor line (linewise), after/at cursor (charwise) |
| `"name <cmd>` | Register prefix for `y`/`d`/`p`/`P`: `"block yap`, `"block dd` (cut), `"block p`. Word names take a space; single letters also work vim-style (`"ayy`). Bare `y`→unnamed register; bare deletes never touch registers. |

Text object set: `w`, `W`, `p` (paragraph), `(`/`)`, `{`/`}`, `[`/`]`, `"`, `'`, `` ` ``, with `i` (inner) and `a` (around) variants. The paragraph object is **delete-only** (`dip`/`dap`): `cip`/`cap` were removed in v0.18 as the one case with no good answer to "what indent does this replacement get", and the loud error names the two-step (`dip` then `o TEXT`). Sketched but **not implemented:** `t` (HTML/XML tag), and the commands `J` (join) and `>>`/`<<` (indent/dedent).

- **Output:** post-edit viewport of the affected region, plus a one-line summary (`changed line 80`, `deleted lines 45–52`). For multi-line effects the viewport expands to cover the whole affected span ±2 lines. `o`/`O` echoes also state pre-edit blank-line counts on both sides of the insertion point (`2 blank line(s) above insertion point, 0 below`) — always, unconditionally.
- **Errors:** if the text object cannot be resolved at the cursor (e.g. `ci(` with no enclosing parens on the line), fail loudly with an explanatory message; never guess.
- **Signpost errors** turn a vim reflex into a redirect instead of a dead end: `.` and `:g/pat/normal` name the supported form, and an ex address (`:901 dd`, `1,5d`) points at `at /regex/ dd` / `at "literal" dd` / the `substitute` tool. A digit glued to letters (`5dd`) is a *count* reflex, not an address, and still falls through to the supported-command list. Any command starting with `at ` that matches neither anchor form gets a malformed-anchor error listing every shape.

### `substitute`
Ex-style substitution for repetitive, file-wide, or ranged changes — the cases where a single pattern edit beats many keyhole hops.

- **Input:** `command` in ex syntax: `:%s/old/new/g`, `:10,40s/foo/bar/`, `:g/DEBUG/d`, `:/def parse/,/^$/s/x/y/g`
- **Output:** number of substitutions + a compact diff of changed lines (unified-diff style, changed lines only, capped — see Limits). This is the fresh "anchor" restatement of file content the agent can attend to.
- Also carries the ex-range register fallback: `:RANGE y NAME` / `:RANGE d NAME` for pattern-bounded blocks that text objects can't select (paste back with `p` in `edit`).
- **Address offsets (v0.5):** `+N`/`-N` on any range address (`/^def /-1`, `$-1`, `10+2`). Both range addresses are inclusive, so `/pat/-1` is the "up to but not including" idiom. Numeric addresses go stale the instant the file changes; prefer pattern addresses.
- **Search is per-line** (`finditer`), so patterns cannot span lines; the *replacement* can, and `\n` in it inserts a real newline. Replacements are Python `re` syntax with one vim/sed concession: backslash-punctuation is unescaped (`\(` → `(`), so an escape copied from the pattern into the replacement can't silently land in the file.
- **Indent-capture recipe** for rewriting a line into several without retyping whitespace: `:s/^( +)tail/\1new\n\1  more/`.

### `matches`
Global search visibility without content. The antidote to keyhole blindness.

- **Input:** `pattern` (regex), optional `context: 0|1` (lines around each hit)
- **Output:** grep-style listing, one line per match with line numbers, capped at 50 hits (then `... and N more`). Tens of tokens instead of thousands.

Agents should call `matches` before any rename-like refactor to see all affected sites.

### `print`
Read-only window print, ed/vim's `:p` (v0.16). This is the *reading*
keyhole: dogfood #9 read a ~1200-line file once and then never again, small
`print` windows around anchors being enough. The span cap is what keeps it
a keyhole rather than a full-file read through the back door — the Non-Goals
entry stands.

- **Input:** `command` — `p` | `:ADDR p` | `:N,M p` | `p above|below|around
  COUNT` (COUNT = tiny/middle/long = 8/25/50, or a number; address +
  window combine, a two-address range takes no window word).
- **Output:** span header + the numbered viewport (`→` cursor marker,
  context 0, no caret). An address moves the cursor — that *is* the paging
  mechanism, the gutter numbers being the next hop targets; bare `p` moves
  nothing; an explicit two-address range moves to the last printed line, as
  vim does. `around` means that many lines on EACH side. Span capped at 101
  lines (a larger explicit range fails loudly suggesting paging); never
  dirties the buffer, no undo entry, no staleness check (like `motion`).

### `write`
Save the active buffer to disk.

- **Output:** confirmation + lines changed since last write. Buffers are in-memory until written; `open` warns if a buffer has unwritten changes.
- **`write(preview=True)`** (CLI `--preview`) renders the full pending
  buffer-vs-disk ±diff and writes nothing — the answer to "what am I about
  to save", and to the buffer/disk divergence confusion that native `Read`
  and test runs create (they see the disk, not the buffer). Honest caveat:
  this diff IS difflib-aligned (`autojunk=False`), unlike `at each`'s exact
  per-site tuples — with no operation-level spans for accumulated edits
  there is no alternative; content is exact, alignment around repeated
  lines may pick an equivalent pairing. The real write reports the same
  count as the preview.
- Nothing reaches disk until `write`. That boundary is load-bearing for the
  permission-management argument (allow `edit`, gate `write`) and is why
  auto-save is a Non-Goal.
- The write itself is atomic: content goes to a hidden same-directory temp
  file (`.<name>.<rand>.djinnvim-tmp`) which then replaces the target in one
  rename, so a process that dies mid-write can never leave a truncated
  source file. The temp is removed on every failure path this process can
  still run code on; a SIGKILL or power cut cannot, and does strand one next
  to the target (measured: 25 of 25 hard kills), so each write first sweeps
  stranded temps carrying that same target's prefix and older than a minute,
  and `open` sweeps too, so a crash on a file never written again is still
  cleared by reopening it. Creation itself cannot collide: `mkstemp` opens
  with `O_EXCL`, so it can never overwrite an existing file, real or ours.
  Two cases keep
  the old in-place write deliberately, because a rename swaps the inode and
  that is visible to others: hard-linked files (the other links would
  detach) and files we do not own (they would change hands). A read-only
  directory holding a writable file falls back too, rather than failing a
  write the old path would have completed.

## Conventions

Conventions decided during implementation (in addition to the earlier ones —
0-based cursor internally / 1-based in output; failed commands never touch
buffer or cursor; every success echoes a viewport; write appends trailing newline):

- **TEXT separator:** exactly one whitespace char separates a command from its
  TEXT; everything after it is verbatim (so `o     x = 1` inserts an indented
  line, `I # ` keeps its trailing space).
- **Newlines in TEXT are literal, 1:1 with vim's Enter** (v0.15, after two
  rounds of getting this wrong): every real newline character in TEXT opens
  a line, including trailing ones, and none are stripped. `o body` plus one
  newline leaves exactly one blank line below. **The asymmetry that bites:**
  the two *characters* backslash-n stay as typed in `edit` TEXT (they must —
  otherwise every `print("a\nb")` an agent inserts would be corrupted),
  while in a `substitute` *replacement* backslash-n does insert a newline.
  Same two characters, opposite meaning in two tools; both descriptions say
  so explicitly. The reopened risk of a stray client newline is accepted:
  an extra blank line is visible in the echo and cheap to `u`, unlike a
  silently eaten intentional one.
- **The indentation contract** (v0.18, one rule for all three line-wise
  inserts): `o`, `O` and `cc` take the reference line's indent and TEXT's
  own leading whitespace stacks on top, so callers pass only the indent
  BEYOND the anchor's; `o!`/`O!`/`cc!` insert TEXT literally; charwise
  commands never touch indentation; `substitute` replacements are always
  literal, which is why its indent-capture recipe exists. That last
  asymmetry was an active counter-signal - dogfood #10 generalized the
  capture recipe to `edit` and double-indented - so both texts now
  cross-reference the other.
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

- **Anchors land at match START** — `at /retries=3/ ciw 4` changes `retries`,
  not the `3`; anchor on the value you want changed (`at /3\)/ ciw 4`).
  Two independent live hits; the tool description warns about it, and the
  labeled caret makes it self-announcing *before* the edit.
- **The anchored form takes edit commands only** — no motions inside it
  (`at /timeout=15/ f1` fails loudly). Anchor on the text you want changed,
  not near it.
- **`o`/`O` are line-wise**, so they cannot say "after this multi-line
  statement"; anchor on the statement's LAST line.
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

Register rules (the "visible state" the Non-Goals amendment allows):

- **Registers live on `Session`, not per-buffer**, so cut in one file and
  paste in another works. They have **kinds**, vim-style: `yy`/`yap`/`dd`/
  ex-range ops are linewise (paste inserts whole lines above/below);
  `yiw`/`yi(` are charwise (paste lands within the line).
- **Anti-clobber rule:** only an *explicit* register name writes a register.
  `dd`, `diw`, `:g//d` and bare `:RANGE d` are plain deletes and never touch
  one, so a trivial cleanup mid-move can't destroy the block being carried.
  Bare `y…` writes the unnamed register; bare `p` reads it. `c` commands
  never touch registers (vim would; invisible side-channel, rejected).
- **Every register op echoes name + content preview**, so the register sits
  high in recent context and the model never reproduces the text — the tool
  holds the authoritative copy. A wrong-name paste fails loudly listing all
  registers with previews, so recovery is one glance, never a guess. That
  visibility is exactly what makes registers compatible with the no-invisible-
  state rule; the model's whole correctness burden is remembering one word.
- **Moves are three verified steps** (cut → navigate → paste), which is why
  `:m`/`:t` were rejected: they pack source range and destination into one
  blind call with no intermediate echo.
- **The move-a-function recipe:** cut the function *with* its trailing blanks
  (`:/def helper/,/^def /-1d fn`), then paste ABOVE the destination def with
  `"fn P` — spacing lands right on both sides with zero patch-up. Do NOT
  combine leading-blank and trailing-blank offsets in one cut; that carries
  blanks on both sides and starves the source.
- **Text objects under-grab on functions with internal blank lines** (a
  Python function is not one paragraph, so `dap` truncates). That is what the
  ex-range form is for; the redundancy is deliberate, since vim has both
  surfaces and the whole bet is that models already speak vim.

## Viewport Format

```
  78  def parse_config(path):
  79      opts = {}
→ 80      for line in open(path):
                       ^ on "l" of "line"
                       indentation is 4 spaces deeper than line above
  81          key, val = line.split("=")
  82          opts[key.strip()] = val
```

- Line numbers, right-aligned, two-space gutter. `→ ` on the cursor line is
  exactly as wide as the two-space prefix on the others: **the indentation
  shown is exact.** (Reported twice as "the marker eats a column"; checked
  byte-wise both times and false — the friction is that a model cannot see
  glyph alignment, which is the same weakness class the labels below answer.)
- A `^` column marker on the line below the cursor line, **only when column
  matters** (searches and `f`/`F`, not line-wise motions).
- **The caret is labeled** (v0.7): `^ on "h" of "hello"` on a word char,
  `^ on ")"` on punctuation, `^ at end of line` past the last column,
  `on tab` / `on " "` on whitespace. Factual only, no interpretation. The
  word is extracted with the *same* `_word_span` logic `ciw` uses, so
  `of "hello"` names exactly what `ciw` would change — that consistency is
  the safety property, and single-char words keep the `of` so its presence
  always means "ciw works here and changes this".
- **Plus an indentation fact** (v0.15) wherever the caret fires: `indentation
  matches line above` / `is N spaces deeper than line above` / `differs from
  line above (tabs vs spaces)`. Omitted on the first line of a file; mixed
  units never get a numeric comparison, since a tab has no fixed width.
- Why label at all: a model cannot *see* whitespace alignment, and extracting
  a column means counting characters — the known weakness (this doc has a
  confirmed case of a model miscounting blank lines it could see). So the
  render **states the fact instead of asking the model to count it**, in the
  compiler-diagnostic style (`^ help: ...`) that is dense in the weights.
- Cursor rendering is a config flag — `DJINNVIM_CURSOR_STYLE`,
  `caret-labeled` (default) or `caret` (bare marker) — which is exactly the
  knob the never-run rendering ablation would turn. ANSI/reverse-video was
  considered and rejected: MCP results are plain text; escape codes get
  stripped or tokenize as garbage inside line content.
- Default viewport: 2 above + cursor + 2 below (≈40 tokens). A bigger,
  explicit look is the `print` tool's job, not a `size` parameter.

## Error Handling

- Every failure is loud and specific: `no match`, `no enclosing ( on line 80`, `pattern matched 0 times`, `line 999 out of range (file has 412 lines)`.
- Failed commands never modify the buffer or move the cursor.
- If the file changed on disk since `open`, any `edit`/`substitute` fails with a staleness error and prompts a re-`open`.

## Limits & Safeguards

- `substitute` diffs capped at ~60 changed lines in output; beyond that, report count + first/last changed regions and suggest `matches` to inspect.
- `matches` capped at 50 hits; `print` spans capped at 101 lines.
- All paths validated against the sandbox roots (see Sandboxing below).
- Catastrophic backtracking is bounded: every pattern-taking op runs under a
  time budget (10 s default, `DJINNVIM_OP_BUDGET_SECONDS`), enforced by a
  forked oracle child, because `re` releases neither signals nor the GIL and
  so no in-process timeout can interrupt it. Overrun is a loud `error:` that
  changes nothing, and buffers survive it. See `guard.py`.
- Not implemented, still on the list: a linear-time regex engine (RE2-style),
  the dialect is bare Python `re` today, and a read-only mode flag for
  exploration sessions.

## Example Session

Task: in `config.py`, bump one retry default, quote a bare value, and drop
every debug line.

```
open config.py
→ metadata + viewport at line 1

matches retries
→ 3 hits, one line each: the default, a call site, a comment

edit at /retries=15/ ciw 30
→ error-free, but the caret said `^ on "r" of "retries"` — anchors land at
  match START, so re-anchor on the value

edit at /15\)/ ciw 30
→ viewport: line 41 now reads `..., retries=30)`  (match 1 of 1)

edit at "timeout = 30" ysiw"        # literal anchor: no escaping needed
→ viewport: the value is quoted

substitute :g/log_debug/d
→ 6 deletions + compact ±diff of the removed lines

write preview
→ full pending buffer-vs-disk diff, nothing written yet

write
→ saved, 8 lines changed
```

Total context cost: ~200 tokens for a session that would otherwise require a full-file read.

## Sandboxing: the multi-root model

Same containment posture as Claude Code's native `Edit` tool - and that
posture is literally obtainable, because the MCP `roots/list` request
returns exactly the set native `Edit` operates under (session launch dir +
every `--add-dir` / `/add-dir` / `additionalDirectories` grant), with
`notifications/roots/list_changed` on changes.

**Trust model.** Every root exists because a *user* granted it; the client
is trusted by construction (it spawns the server process and controls
env/cwd already) and the *model* cannot expand the set. The adversary this
sandbox confines is the agent (model-generated paths, prompt injection),
NOT a hostile local user: TOCTOU races and hardlinks-into-the-root are
consciously out of scope, since native `Edit` has identical exposure.

- **Resolution chain:** `DJINNVIM_ROOTS` (explicit, exclusive) ->
  `DJINNVIM_ROOT` (one-entry alias) -> MCP `roots/list` (requested lazily
  on the first tool call; `list_changed` honored via a stale flag) ->
  `CLAUDE_PROJECT_DIR` -> server cwd.
- **`DJINNVIM_ROOTS` is `os.pathsep`-separated** (`:` POSIX / `;` Windows,
  the PATH convention so `C:\` survives) and **exclusive**: when set,
  client roots are ignored entirely - the cautious user's pinned boundary
  that no client chatter can widen. The permission-management argument
  depends on this.
- **All roots are peers, no primary/secondary.** Consequence for relative
  paths: allowed only when exactly one root is configured; with several, a
  relative `open` fails loudly naming the roots, and that error doubles as
  the sandbox announcement.
- **`/` and `$HOME` are refused as roots** from every non-explicit source
  (client `roots/list`, `CLAUDE_PROJECT_DIR`, cwd). Via `DJINNVIM_ROOTS`
  they are accepted: explicit = deliberate.
- **One choke point:** containment is checked in `Session.open`, with
  `.resolve()` BEFORE the check, so symlink escapes (including a symlink
  inside a root pointing out) are rejected. Defense in depth: `write`
  re-validates, so a buffer opened under a since-revoked root fails loudly
  instead of writing.
- **One asymmetry recorded honestly:** native tools can re-prompt per edit
  depending on mode; djinnvim's `write`, once allowed as a tool, is allowed
  across the whole sandbox - the same shape as native `acceptEdits`, a
  comparable posture rather than a regression.

## CLI, daemon, skill, distribution

**Command surface:** `djinnvim mcp` runs the stdio server; the seven verbs
mirror the tool names; `djinnvim status` / `djinnvim shutdown [--all]` make
the daemon discoverable and killable ("hidden" must mean "auto-managed",
never "unkillable", for exactly the cautious-user audience);
`djinnvim install-skill` writes the packaged SKILL.md to
`~/.claude/skills/djinnvim/SKILL.md` (or `./.claude/skills` with
`--project`). Bare `djinnvim` still runs the MCP server.

**Daemon lifecycle (ssh-agent-shaped):**

- **Socket** under `$XDG_RUNTIME_DIR/djinnvim/`, keyed by
  sha256(sorted resolved roots + a session discriminator). The
  discriminator chain is `DJINNVIM_SESSION` -> `CLAUDE_CODE_SESSION_ID` ->
  parent-shell PID; per-root sharing was rejected because concurrent agent
  sessions would share one `Session` (cursor, registers, undo), silently
  breaking the exact-MCP-parity argument that justifies the daemon.
- **Auto-spawn:** compute socket path -> connect; on failure re-exec the
  own binary as a detached daemon (`python -m djinnvim daemon`, roots and
  discriminator pinned in env), poll until the socket accepts, proceed.
  Stale sockets unlinked; spawn races resolved by bind exclusivity.
- **Idle self-exit** after `DJINNVIM_IDLE_SECONDS` (default 1800).
- **Version handshake on every request:** a daemon running a stale binary
  replies "restarting" and exits; the client respawns. No skew.
- **Wire protocol: minimal newline-delimited JSON**, one request per
  connection (`{"v", "op", "args"}` -> `{"ok", "result"/"error"}`), not MCP
  framing - parity lives in the shared `Session`, not the wire format.
  Tool-level `error: ...` strings are ok-results (loud errors are content);
  `ok: false` means the daemon itself broke.

**CLI quoting: strict one-argument rule.** `djinnvim edit at /p/ ciw x`
(unquoted) is a loud exit-2 error with a quote-it hint - re-joining argv on
spaces would silently collapse the whitespace TEXT preserves verbatim.
Exit codes: 0 ok, 1 = editor said `error: ...` (stdout carries it),
2 = usage/daemon failure. Agent cwd and env do not persist between shell
calls, so SKILL.md's rule is to pin `DJINNVIM_ROOTS` inside every command.

**Skill is CLI-only - the MCP ships without one.** The MCP's tool
descriptions and server `instructions` ARE its skill: the whole benchmark
ran cold agents on those alone, so "works cold from descriptions" is a
*measured* claim a bundled skill would only dilute, and a second copy of
the guidance is a hand-sync drift hazard. If discoverability ever fails,
the fix is descriptions and naming, not a skill. The CLI gets one because
it has no schema channel at all, and since v0.18 SKILL.md is the CLI's copy
of what MCP clients get from `INSTRUCTIONS`; a test pins the contracts that
must appear in both. SKILL.md ships as package data, version-locked to the
binary.

**Distribution: one package, one channel.** Single PyPI package, no
`[cli]` extras. Blessed paths would be `uvx djinnvim mcp` in MCP configs
and `pipx install djinnvim` for CLI users; **PyPI publishing is currently
deferred**, so git-URL installs (`uvx --from git+...`,
`pipx install git+...`) are the supported channel, with a **plain-pip path
documented alongside them** (clone, `python3 -m venv .venv`,
`.venv/bin/pip install .`, then point the MCP client at
`.venv/bin/djinnvim mcp` by absolute path) so neither uv nor pipx is a hard
dependency - the absolute path is the load-bearing part, since clients spawn
the server with their own cwd and `PATH`. `publish.yml` (test ->
build -> trusted publishing on `v*` tags) stays wired and dormant.
Accepted risk: the `djinnvim` name stays unreserved on PyPI. Docker was
rejected - host-vs-container path identity breaks the roots semantics, and
its confinement value duplicates the sandbox above.

## Status (2026-07-28)

**v0.19, implemented and green: 390 tests, twelve e2e scripts over real MCP
stdio, one over the real console script.** The full surface is built - the
seven tools, registers, undo, at-each batch edits, anchor and address
offsets, literal anchors, write preview, indent-inheriting `o`/`O`/`cc`,
the labeled caret, the multi-root sandbox, the CLI + daemon + skill,
(v0.18) server `instructions` as the cross-cutting guidance channel, and
(v0.19) the optional `path` plus per-tool selection guidance.

**Open question v0.19 answers only on paper:** whether the tools now get
*chosen* in a foreign harness. The change was made from one negative
observation (Copilot + Opus 4.8, never selected); the next external session
is the measurement, and if it still loses, the remaining lever is naming,
not more words.

Public as `anschnapp/djinnvim` (Apache-2.0), README carries the findings
tables, `docs/cost-explorer.html` is served via GitHub Pages. Ten dogfood
sessions run (five of them on a real external project with Opus 5 over
MCP); the benchmark sweep is closed.

**Resolved follow-up from dogfood #10 (README candidate):** the sweep ran
partly under truncation. `results/*.jsonl` records a `djinnvim_version`
commit per trial; all but one batch ran on a 2170-char `edit` description,
122 over the cap, and the 122 chars lost were exactly the last three
examples - the `at each /# obsolete/ dap` structural example, the register
cut/paste pair, and `edit("u")`. So the keyhole condition, including the
move/composite task the README calls "cut/yank/put register territory", was
measured with the register and undo examples missing. It cuts in our
favour (the numbers were achieved on less guidance than we believed we
shipped), which is why it belongs in the README's existing
numbers-predate-the-current-version note rather than being left unsaid.

Honest position: benchmarked, feature-complete for its thesis, ~zero
real-world adoption, and only Claude Code has been tested as a client.

**e2e discipline learned the hard way (v0.16):** unit tests passing is not
enough - a semantics change (v0.15's literal `\n`) left an e2e script
stale and nobody noticed until the next session. Re-run every e2e when
command semantics change.

**Canonical copies, do not re-derive from prose:** benchmark numbers live
in the README findings tables and the explorer's embedded DATA; the
explorer's task descriptions are mirrored from the README **by hand** -
keep them in sync on edit. Regenerate the README's explorer screenshot on
explorer changes:
`google-chrome --headless=new --window-size=1200,700
--screenshot=docs/explorer-preview.png docs/cost-explorer.html`.

## Parked, deferred, and their evidence gates

The project's standing rule is an **evidence gate**: a feature waits until
live use produces the friction it would remove. It has been consciously
waived four times (registers, undo, `at each`, and the literal anchor's
sibling arguments) - always recorded as a waiver, never as evidence.

Parked with a stated gate:

- **`blanks N above|below`** - a declarative blank-line command, designed
  in conversation and rejected for now: the one-call idioms that make it
  unnecessary (bare `o`/`O`, `at /pattern/ dd`) had never been *tried*,
  and v0.17 documented them. Gate: if the next real-project dogfood still
  burns calls on whitespace with that guidance in place, build it.
- **Multi-line patterns in `substitute`'s search** (the replacement
  already takes `\n`). One live hit; workarounds exist.
- **Multi-file `matches`** - deliberately sequenced *before* any
  multi-file batch editing, because the missing primitive is batch
  *visibility*, not batch editing.
- **A short command sequence inside `at each` only** - the surgical
  concession if pass-2 re-anchoring on post-pass-1 text proves awkward.
  Still transactional, still no general sequences.
- **Read-only mode flag**, and a linear-time (RE2-style) regex engine
  instead of bare Python `re`. Both come from the original safeguards list;
  the timeout half of that entry shipped as v0.20's op budget, these two
  did not.
- **Refusing an ambiguous anchor on destructive commands.** `at /pat/ dd`
  with a pattern matching several sites edits the first and says `match 1
  of N`; it does not refuse. Reviewed 2026-08-01 and deliberately kept:
  during that session the behavior misfired twice on me, and both times
  the count plus the echoed viewport caught it within one call and `u`
  restored it, which is the echo discipline doing exactly its job. Gate:
  if a real session ever lands a wrong-site destructive edit that the echo
  does *not* catch, make `dd`/`cc` demand an unambiguous anchor.

Deliberately not built (distinct from parked - these are decisions, not
queues):

- **Motions `0`, `$`, `w`/`b`/`e`, `{`/`}`, `%`** and edit commands `J`,
  `>>`/`<<`, and the `t` (tag) text object appear in the tables below as
  design sketches but are **not implemented**; no dogfood ever wanted
  them. `motion` supports exactly `/pattern ?pattern n N :N gg G f<char>
  F<char>`; the text-object set is `w`, `W`, `p`, the bracket and quote
  pairs, and backtick.
- **Auto-save.** It would gut the permission-management claim (both
  "nothing touches disk until `write`" and the allow-edit-gate-write
  granularity depend on the buffer boundary) and would put every
  mid-refactor state on disk for tests and watchers to see. The
  buffer/disk confusion it would "fix" is a *visibility* problem, answered
  by `write(preview=True)`.
- **Parse/LSP feedback on `write`.** A Python-only `compile()` note was on
  the table and rejected as the first step onto the LSP slope. Correctness
  comes from running the file or the tests, per SKILL.md's
  write-before-testing rule.
- **Redo.** Undo crosses `write` boundaries; redo would drag in
  branch-on-edit-after-undo semantics for no payoff.
- **`.` repeat, macros, sequences, `:m`/`:t`, counted motions** - see
  Non-Goals for the reasoning, which is load-bearing rather than
  incidental.

Never run, still cheap: the **ablations** (cursor rendering style down to
the bare caret, viewport size, `matches` pre-check on rename tasks).

## Benchmark: what it measures, and what it showed

The harness lives in `benchmark/` (not part of the installed package):
`gen.py` builds each task's start file from a seeded block list and the
target file from the same list with the transformation applied, so
correctness is a mechanical diff; `runner.py` drives headless Claude Code
(`claude -p --output-format stream-json`, fresh temp workdir and fresh
session per trial, resumable JSONL, per-trial budget cap); `report.py`
aggregates.

**Three conditions, one prompt:** *keyhole* (djinnvim MCP only, native
file/shell tools disallowed), *baseline* (stock native tools including
Bash, i.e. grep+sed), and *no-bash* (native tools minus shell execution -
the measured version of the permission-management argument). Twelve task
generators; the seven round-2 tasks are the discriminating ones, built as
traps where a naive sed one-shot silently corrupts. Sizes 500 / 2000 /
10000 lines; models haiku and sonnet.

**Two grading columns:** *exact* (byte-identical to target, primary) and
*semantic* (Python `ast` equality, tolerating formatting-only divergence).
Whole-cell swap policy: a cell whose outputs were lost may only be
replaced by a full 3-trial re-run kept regardless of outcome, never a
per-trial retry.

What the closed sweep supports, in order of defensibility:

1. **Every confirmed silent failure in the grid is haiku's.** Sonnet is
   semantically clean in all three conditions; at the frontier the
   difference is money, not correctness.
2. **Where they fail differs - the strongest pro-keyhole claim.** Haiku
   keyhole's silent failures sit on its genuinely hardest tasks; haiku
   baseline's include simple tasks where a tempting sed one-shot exists.
   Baseline fails where the *trap* is; keyhole fails where the *work* is
   hard.
3. **Silent-failure counts favour keyhole only directionally** (3 vs 5 vs
   4 on ~62 trials per condition, n=3 per cell) - do not oversell beyond
   "slight favour".
4. **Cost: keyhole is flat in file size; every read-the-file condition
   grows.** Honest caveat: at 500 lines the Bash-armed baseline is
   *cheaper* than keyhole. Keyhole's win is the flat curve and the
   lockdown story, not small-file economy.
5. **The lockdown story is task-shaped:** deny Bash to a cheap model and
   correctness collapses on structural/file-wide tasks; deny it to a
   frontier model and correctness holds but cost grows with size and blows
   through a $3 per-trial cap on the high-K structural task (~14x keyhole
   once the cap is lifted). Keyhole is unaffected at either tier.

Numbers, per-cell tables and provenance: README + `docs/cost-explorer.html`
(canonical), with the round-by-round record in decisions.md. No opus round
was run and the README deliberately claims no higher-tier data.
