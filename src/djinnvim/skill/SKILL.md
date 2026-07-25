---
name: djinnvim
description: Edit files with the djinnvim CLI — vim-style, pattern-anchored keyhole editing that never reads whole files. Use for any file editing when djinnvim is installed, especially when file/shell tools are restricted or files are large.
---

# djinnvim: keyhole editing from the shell

You edit through small viewports, the way a vim user does: search by
pattern, look at the echo, edit. Never read a whole file — every command
returns the few lines around what it did, and that echo IS your
verification (no re-reads needed).

## Setup — every command, two rules

1. **Pin the sandbox root in the same shell command** (shell env does not
   persist between your calls):

   ```
   export DJINNVIM_ROOTS=/abs/path/to/project; djinnvim open src/app.py
   ```

2. **Pass each editor command as ONE quoted argument.** Single-quote it;
   switch to double quotes only when the text itself contains a single
   quote:

   ```
   djinnvim edit 'at /old_name/ ciw new_name'
   djinnvim substitute ":%s/'eu-west'/'us-east'/"
   ```

State (open buffers, cursor, registers, undo) persists across your shell
calls via an auto-spawned per-session daemon — nothing to start or manage.
`djinnvim status` shows it, `djinnvim shutdown` stops it (unwritten buffers
die with it; only `write` touches disk). Exit codes: 1 = the editor said
`error: ...` (read it — the buffer is untouched), 2 = usage/daemon problem.

## The six verbs

- `djinnvim open PATH` — open/switch the active buffer. Relative paths
  resolve against the root, not your cwd.
- `djinnvim motion CMD` — move the cursor, one motion per call:
  `/pattern` (regex, forward), `?pattern` (back), `n`/`N` (next/prev —
  n is ALWAYS forward, N ALWAYS backward, unlike vim), `:80` (line),
  `gg`/`G`, `fx`/`Fx` (char on the cursor line). Search is strictly after
  the cursor and wraps, reporting `match i of n (wrapped)`.
- `djinnvim matches PATTERN [-C 1]` — grep-style listing of every match
  (capped at 50). **Call this before any rename-like edit** to see all
  sites and decoys.
- `djinnvim edit CMD` — vim normal-mode edit (details below).
- `djinnvim substitute CMD` — ex command (details below).
- `djinnvim write` — save the active buffer; reports lines changed.

## edit

Anchored form (preferred): `at /pattern/ <cmd>` (ordinal: `at 2nd /pat/
<cmd>`). **The anchor lands at the START of the match — anchor on the
exact text to change:** `at /15\)/ ciw 60` changes the 15 in
`retries(15)`; `at /retries=15/ ciw 60` would change `retries`.

`at each /pattern/ <cmd>` applies one edit command at EVERY match
(transactional: any failure changes nothing; one undo step; returns a
±diff). Text objects make it structural: `at each /# obsolete/ dap`
deletes every marked paragraph whole — no line counting. To go
match-by-match instead, reissue the same `at /pat/ <cmd>`; it anchors on
the NEXT match each time.

Commands: `ciw`/`caw TEXT`, `ci(`/`{`/`[`/`"`/`' TEXT` (`di`/`da`
delete), `cip`/`cap`/`dip`/`dap` (paragraph), `dd`, `cc TEXT`, `D`,
`C TEXT`, `x`, `r<char>`, `o`/`O TEXT` (line below/above; multi-line OK),
`A`/`I TEXT` (line end/start), `i`/`a TEXT` (before/after the cursor
char), `cs"'` / `ds"` / `ysiw"` (surround). Changes need TEXT, deletes
take none; everything after the first space is TEXT, verbatim (indent
included: `o     x = 1`). One trailing newline is stripped as the
terminator; further ones are blank lines (`o body\n\n` inserts body plus
one blank). `o`/`O` are line-wise — to insert below a multi-line
statement, anchor on its LAST line, not its first.

Registers: `yy` / `y<i|a><obj>` yank, `p`/`P` paste. `"name` prefix
composes with the anchor: `at /def helper/ "fn dap` cuts the function,
`"fn p` pastes it (works across files). Only "name-prefixed deletes write
registers; a wrong name on `p` lists them all.

`u` undoes the last buffer change (repeat to go further; crosses writes;
no redo). Any bad echo → `u` reverts it whole.

## substitute

Ex forms: `:%s/old/new/g` (file), `:s/old/new/` (cursor line),
`:10,40s/foo/bar/`, `:/start/,/end/s/x/y/g`, `:g/pat/d` (delete matching
lines). Flags `g`, `i`. **Regex and replacement are Python `re` syntax**
(`\1` groups): escape parens in the PATTERN (`send_request\(x\)`) but
write them plainly in the replacement. Both range addresses are
inclusive; any address takes `+N`/`-N` — end on `/pat/-1` for "up to but
not including". Zero matches is a loud error, never a silent no-op.
Numeric addresses go stale after every edit; prefer pattern addresses.

Line-shaped only: to remove whole blocks at every match use
`edit 'at each /pat/ dap'`, not hand-counted ranges. Register ranges for
blocks text objects can't grab (function with internal blank lines):
`:/def helper/,/^def /-1d fn`, then paste with `at /def target/ "fn P`.

## Workflow

1. `open` the file (echo shows size — you never need more than that).
2. `matches` the symbols you'll touch: counts expose decoys
   (`fetch_records` vs `fetch_records_cached` → use `\b...\b`) and plan
   scoping before any edit.
3. Edit smallest-first tool: one-site → anchored `edit`; many-line regex
   → `substitute`; many-site structural → `at each`.
4. **Read every echo.** The diff/viewport is the verification; a wrong
   echo → `edit u` immediately.
5. `write`, and check the reported changed-line count against what you
   expect.
6. **Write before running anything against the file.** Tests, linters,
   and file reads see only the disk — never unwritten buffer state. (A
   disk change under an open buffer fails loudly on the next edit/write;
   re-open to continue.)
