"""The comparison renderer's qualifications: estimates stay labelled, evidence stays honest.

``compare`` inherited two silent misstatements from treating every phase as fully measured:
a sampled phase's scaled ``calls`` counted as evidence (200 claimed samples for 2 measured
entries defeats the thin-evidence mark exactly when it is needed), and nothing anywhere in
the comparison said a row was an estimate — the one contract (`sample_stride`'s docstring)
this layer states most emphatically. A third defect was arithmetic: ``tail_moved`` compared
mean and median ratios by absolute difference, so a uniform 5x slowdown whose median
quantised to 4.6x was called a tail change, confidently and wrongly.
"""

from __future__ import annotations

import json
from pathlib import Path

from phaselog.accounting import merge_run
from phaselog.accounting.compare import PhaseDelta, compare, render_comparison
from phaselog.accounting.histogram import bucket_index


def _write_run(
    run_dir: Path,
    phases: dict[str, dict[str, object]],
    pid: int = 4001,
) -> None:
    """One worker with the given phases, written straight to disk like the golden fixture."""
    workers = run_dir / "workers"
    workers.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "pid": pid,
        "role": "worker",
        "started_at": 1_700_000_000.0,
        "written_at": 1_700_000_090.0,
        "backend": None,
        "phases": phases,
    }
    (workers / f"w_{pid}_{pid:08x}.json").write_text(json.dumps(payload), encoding="utf-8")


def _phase(
    calls: int,
    wall_ms: float,
    sample_stride: int = 0,
) -> dict[str, object]:
    wall_ns = int(wall_ms * 1e6)
    per_call = max(1, wall_ns // max(1, calls))
    return {
        "calls": calls,
        "wall_ns": wall_ns,
        "cpu_ns": wall_ns,
        "child_wall_ns": 0,
        "hist": {str(bucket_index(per_call)): calls},
        "counters": {},
        "sample_stride": sample_stride,
    }


def test_a_sampled_phase_is_marked_as_an_estimate_in_the_comparison(tmp_path: Path) -> None:
    """A row scaled from a sample must not read like the measured rows around it.

    The report already prefixes such rows with ``~`` and names the stride; the comparison
    rendered them bare, so the one place two runs are judged against each other presented
    an estimate with the same authority as a measurement.
    """
    run_a, run_b = tmp_path / "a", tmp_path / "b"
    _write_run(run_a, {"work": _phase(1000, 100.0)})
    _write_run(run_b, {"work": _phase(1000, 200.0, sample_stride=10)})

    text = render_comparison(merge_run(run_a), merge_run(run_b), "A", "B")

    work_row = next(line for line in text.splitlines() if line.startswith(("work", "≈")))
    assert "≈" in work_row, f"sampled row carries no estimate mark: {work_row!r}"
    assert "1 entry in 10" in text, "the note must name the sampling rate, like the report"


def test_scaled_sample_counts_do_not_masquerade_as_evidence(tmp_path: Path) -> None:
    """calls holds stride-scaled totals; the evidence column must hold measured entries.

    Two measured entries scaled by 100 used to print n=200 and defeat the thin-evidence
    mark exactly where it mattered most.
    """
    run_a, run_b = tmp_path / "a", tmp_path / "b"
    _write_run(run_a, {"work": _phase(200, 100.0, sample_stride=100)})
    _write_run(run_b, {"work": _phase(200, 100.0, sample_stride=100)})

    (delta,) = compare(merge_run(run_a), merge_run(run_b))
    assert delta.samples == 2, f"200 scaled calls counted as {delta.samples} samples"
    assert delta.is_thin, "2 measured entries must be marked thin, whatever the scaling"


def test_a_fully_measured_comparison_is_unchanged(tmp_path: Path) -> None:
    run_a, run_b = tmp_path / "a", tmp_path / "b"
    _write_run(run_a, {"work": _phase(1000, 100.0)})
    _write_run(run_b, {"work": _phase(1000, 100.0)})

    (delta,) = compare(merge_run(run_a), merge_run(run_b))
    assert delta.samples == 1000
    assert not delta.is_thin
    text = render_comparison(merge_run(run_a), merge_run(run_b), "A", "B")
    assert "≈" not in text


def test_a_uniform_slowdown_is_not_called_a_tail_change() -> None:
    """Mean 5.0x and median 4.6x is the histogram's ~9% bucket resolution, not a tail.

    The old absolute test (|5.0 - 4.6| > 0.25) flagged every large uniform shift as a tail
    change and printed "the mean moved but the median did not" about a phase whose median
    had moved 4.6x.
    """
    uniform = PhaseDelta(
        phase="work", calls_a=100, calls_b=100,
        per_call_a=1000.0, per_call_b=5000.0, p50_a=1000.0, p50_b=4600.0,
    )
    assert not uniform.tail_moved


def test_a_genuine_tail_change_is_still_flagged() -> None:
    tail = PhaseDelta(
        phase="work", calls_a=100, calls_b=100,
        per_call_a=1000.0, per_call_b=2000.0, p50_a=1000.0, p50_b=1050.0,
    )
    assert tail.tail_moved
