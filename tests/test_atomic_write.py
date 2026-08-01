"""Atomic writes (buffer._atomic_write).

`write_text` truncates in place, so a process that dies mid-write leaves the
user's source file cut in half. The fix is a same-directory temp file plus
one `os.replace`, and most of these tests are not about atomicity at all -
they are about the temp file staying out of everyone's way, which is the
condition under which this trade is worth making.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from djinnvim.buffer import (
    TMP_STALE_SECONDS,
    TMP_SUFFIX,
    Buffer,
    _atomic_write,
)

TMP_MARK = TMP_SUFFIX


def _litter(d: Path) -> list[str]:
    return [p.name for p in d.iterdir() if TMP_MARK in p.name]


def test_writes_the_content(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("old\n")
    _atomic_write(f, "new\n")
    assert f.read_text() == "new\n"


def test_leaves_no_temp_file_behind(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("old\n")
    _atomic_write(f, "new\n")
    assert _litter(tmp_path) == [], "temp file survived a successful write"
    assert [p.name for p in tmp_path.iterdir()] == ["a.py"]


def test_temp_is_hidden_and_marked(tmp_path, monkeypatch):
    """Whatever exists mid-write must be a dotfile (watchers and `ls` skip
    it) and must name us, so anyone who does see it knows its owner."""
    seen = []
    real_replace = os.replace

    def spy(src, dst):
        seen.append(Path(src).name)
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    f = tmp_path / "pipeline.py"
    f.write_text("old\n")
    _atomic_write(f, "new\n")
    assert len(seen) == 1
    assert seen[0].startswith(".pipeline.py."), seen
    assert seen[0].endswith(".djinnvim-tmp"), seen


def test_preserves_file_mode(tmp_path):
    """mkstemp creates 0600; silently tightening a 0644 source file would
    be its own kind of damage."""
    f = tmp_path / "a.py"
    f.write_text("old\n")
    os.chmod(f, 0o644)
    _atomic_write(f, "new\n")
    assert oct(f.stat().st_mode)[-3:] == "644"


def test_executable_bit_survives(tmp_path):
    f = tmp_path / "hook.sh"
    f.write_text("#!/bin/sh\n")
    os.chmod(f, 0o755)
    _atomic_write(f, "#!/bin/sh\necho hi\n")
    assert os.access(f, os.X_OK)


def test_hardlinked_file_is_written_in_place(tmp_path):
    """A rename swaps the inode and detaches every other link. Keeping the
    old path here is deliberate: the user's other name must keep tracking."""
    f = tmp_path / "a.py"
    f.write_text("old\n")
    link = tmp_path / "b.py"
    os.link(f, link)
    _atomic_write(f, "new\n")
    assert link.read_text() == "new\n", "hard link stopped tracking the file"
    assert f.stat().st_ino == link.stat().st_ino
    assert _litter(tmp_path) == []


def test_readonly_directory_falls_back_instead_of_failing(tmp_path):
    """A writable file in a read-only dir: the temp cannot be created, but
    the old in-place write would have worked, so it still must."""
    d = tmp_path / "ro"
    d.mkdir()
    f = d / "a.py"
    f.write_text("old\n")
    os.chmod(d, 0o555)
    try:
        _atomic_write(f, "new\n")
        assert f.read_text() == "new\n"
    finally:
        os.chmod(d, 0o755)


def test_failure_after_creation_never_falls_back(tmp_path, monkeypatch):
    """If filling the temp failed, an in-place write would fail the same way
    but destructively. The original must survive untouched."""
    f = tmp_path / "a.py"
    f.write_text("original\n")

    def boom(*a, **k):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        _atomic_write(f, "new\n")
    assert f.read_text() == "original\n", "original was clobbered"
    assert _litter(tmp_path) == [], "temp litter left after a failed write"


def test_buffer_write_uses_it(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = 1\n")
    buf = Buffer.open(f)
    buf.lines = ["x = 2"]
    buf.dirty = True
    buf.write()
    assert f.read_text() == "x = 2\n"
    assert not buf.dirty
    assert _litter(tmp_path) == []


BIG_LINES = 200000
BIG = "".join(f"line {i}\n" for i in range(BIG_LINES))
SMALL = "short\n"

# Writes one big change, once, then holds still. The reader watches the
# whole transition: old content, then new content, and nothing in between.
_ONE_BIG_WRITE = r"""
import sys, time
from pathlib import Path
from djinnvim.buffer import _atomic_write
target = Path(sys.argv[1])
big = "".join(f"line {i}\n" for i in range(%d))
time.sleep(0.3)          # let the reader start sampling first
_atomic_write(target, big)
time.sleep(5)            # stay alive so the reader can confirm the result
""" % BIG_LINES

# Cycles forever, to be hard-killed mid-write.
_CYCLING_WRITE = r"""
import sys
from pathlib import Path
from djinnvim.buffer import _atomic_write
target = Path(sys.argv[1])
big = "".join(f"line {i}\n" for i in range(%d))
while True:
    _atomic_write(target, big)
    _atomic_write(target, "short\n")
""" % BIG_LINES


def _spawn(src: str, target: Path) -> subprocess.Popen:
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    return subprocess.Popen(
        [sys.executable, "-c", src, str(target)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_big_change_lands_whole_and_is_never_seen_partial(tmp_path):
    """The full story of one write, start to finish.

    A concurrent reader samples continuously while a 200 000-line change is
    written. Two things must hold: every single sample is one of the two
    *complete* versions (never a partial file), and the loop ends with the
    new content actually all there. Proving only the first would be
    satisfied by a write that never happened.
    """
    target = tmp_path / "big.py"
    target.write_text(SMALL)
    p = _spawn(_ONE_BIG_WRITE, target)
    try:
        saw_old = partial = samples = 0
        landed = False
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            samples += 1
            try:
                text = target.read_text()
            except FileNotFoundError:
                partial += 1  # the swap must never expose a gap either
                continue
            if text == SMALL:
                saw_old += 1
            elif text == BIG:
                landed = True
                break  # the whole thing is there: done
            else:
                partial += 1

        assert partial == 0, f"{partial} of {samples} samples saw a partial file"
        assert landed, "the big change never completed"
        assert saw_old, "sampling started too late to witness the transition"

        # And it is still complete once the writer is idle: byte-exact,
        # right line count, correct last line.
        final = target.read_text()
        assert final == BIG
        assert len(final.splitlines()) == BIG_LINES
        assert final.endswith(f"line {BIG_LINES - 1}\n")
    finally:
        p.kill()
        p.wait()


def _wait_until(predicate, timeout=30.0) -> bool:
    """Poll instead of sleeping a fixed amount.

    An earlier version slept 0.6s and assumed the spawned writer had got
    going by then. Under a loaded machine it sometimes had not, and the
    test failed in the full suite while passing alone. Waiting for the
    observable fact removes the assumption.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def _strand_a_temp(tmp_path: Path) -> Path:
    """A stranded temp, made directly.

    What a hard kill leaves behind is measured by the test below; these
    sweep tests only need the leftover to exist, so they build it instead
    of racing a subprocess for it. Aged past the cutoff, since that is the
    state the sweep is meant to act on.
    """
    stranded = tmp_path / f".big.py.deadbeef{TMP_SUFFIX}"
    stranded.write_text("half-written wreckage")
    old = time.time() - (TMP_STALE_SECONDS + 60)
    os.utime(stranded, (old, old))
    return stranded


def test_hard_kill_mid_write_leaves_target_complete_but_strands_a_temp(tmp_path):
    """The original motivation, with a real SIGKILL rather than a simulated
    failure. Two facts, and the second is the one we got wrong at first:
    the target is never truncated, but a temp *is* stranded, because a hard
    kill runs no cleanup code. The sweep exists to answer the second."""
    target = tmp_path / "big.py"
    stranded_at_least_once = False

    for _ in range(3):
        target.write_text(SMALL)
        p = _spawn(_CYCLING_WRITE, target)
        try:
            # Kill only once the writer is demonstrably mid-loop, so this
            # can neither pass vacuously nor fail because the box was busy.
            started = _wait_until(
                lambda: bool(_litter(tmp_path)) or target.read_text() == BIG
            )
            assert started, "writer never got going; nothing was tested"
        finally:
            p.kill()
            p.wait()

        assert target.read_text() in (SMALL, BIG), "target left truncated"
        if _litter(tmp_path):
            stranded_at_least_once = True
            for name in _litter(tmp_path):
                (tmp_path / name).unlink()

    assert stranded_at_least_once, (
        "no hard kill stranded a temp; if SIGKILL now cleans up, the sweep "
        "and the docs claiming this leftover are both wrong"
    )


def test_next_write_sweeps_a_stranded_temp(tmp_path):
    """Litter must not accumulate in the user's tree: the next write of that
    file clears what an earlier crash left."""
    target = tmp_path / "big.py"
    target.write_text(SMALL)
    stranded = _strand_a_temp(tmp_path)
    assert stranded.exists()

    _atomic_write(target, SMALL)
    assert _litter(tmp_path) == [], "stranded temp survived the next write"


def test_opening_a_file_sweeps_its_stranded_temps(tmp_path):
    """The recovery path a user actually takes after a crash: reopen the
    file. Without this, a temp stranded on a file that is never written
    again would sit there forever, since only a write cleared them."""
    target = tmp_path / "big.py"
    target.write_text(SMALL)
    stranded = _strand_a_temp(tmp_path)
    assert stranded.exists()

    Buffer.open(target)  # a fresh session opening the file, no write involved
    assert _litter(tmp_path) == [], "reopening the file left the temp behind"


def test_open_sweep_spares_a_live_temp(tmp_path):
    """Opening must be as careful as writing: a concurrent writer's
    in-flight temp is not ours to remove."""
    target = tmp_path / "a.py"
    target.write_text(SMALL)
    live = tmp_path / f".{target.name}.inflight{TMP_SUFFIX}"
    live.write_text("half written")
    Buffer.open(target)
    assert live.exists(), "open swept a live temp"
    live.unlink()


def test_sweep_spares_a_fresh_temp_from_a_concurrent_writer(tmp_path):
    """The sweep must never eat a write that is still in flight."""
    target = tmp_path / "a.py"
    target.write_text(SMALL)
    live = tmp_path / f".{target.name}.inflight{TMP_SUFFIX}"
    live.write_text("half written")
    _atomic_write(target, "new\n")
    assert live.exists(), "sweep deleted a concurrent writer's live temp"
    live.unlink()


def test_sweep_ignores_other_files_temps(tmp_path):
    """Only this target's own leftovers are ours to remove."""
    target = tmp_path / "a.py"
    target.write_text(SMALL)
    other = tmp_path / f".b.py.stale{TMP_SUFFIX}"
    other.write_text("not ours")
    old = time.time() - (TMP_STALE_SECONDS + 60)
    os.utime(other, (old, old))
    _atomic_write(target, "new\n")
    assert other.exists(), "sweep removed another file's temp"
