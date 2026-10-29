"""The Chrome trace export: spans and arrows survive, qualifications ride along.

The unit tests build the ``AlignedTrace`` by hand, because the assertions are arithmetic —
a viewer will render whatever numbers appear, so ``ts``/``dur`` reproducing the aligned
nanoseconds *is* the correctness property. The end-to-end test runs a real profiler through
the CLI, because the wiring between ``align_run`` and the exporter is what a hand-made trace
cannot prove.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from phaselog.accounting import Profiler
from phaselog.accounting.chrometrace import chrome_trace
from phaselog.accounting.cli import main as cli_main
from phaselog.accounting.trace import FLAG_SAMPLED, UNMEASURED, Origin
from phaselog.accounting.tracealign import AlignedTrace, Arrow, PlacedSpan

_MS = 1_000_000
_EPOCH = 1_700_000_000_000_000_000


def _span(
    worker: str,
    path: tuple[str, ...],
    t0_ms: int,
    t1_ms: int,
    cpu_ns: int = UNMEASURED,
    flags: int = 0,
    origin: Origin | None = None,
    role: str = "actor",
) -> PlacedSpan:
    return PlacedSpan(
        worker=worker,
        role=role,
        thread_id=7,
        path=path,
        t0_ns=_EPOCH + t0_ms * _MS,
        t1_ns=_EPOCH + t1_ms * _MS,
        cpu_ns=cpu_ns,
        flags=flags,
        origin=origin,
    )


def _two_lane_trace() -> AlignedTrace:
    return AlignedTrace(
        spans=[
            _span("w0", ("iteration",), 0, 10, cpu_ns=4 * _MS),
            _span("w0", ("iteration", "collect"), 1, 9, flags=FLAG_SAMPLED),
            _span("w1", ("train",), 2, 12, role="learner",
                  origin=Origin(file="pipeline.py", function="train", line=41)),
        ],
        arrows=[
            Arrow(channel="batch", key="3", src_worker="w0", dst_worker="w1",
                  src_t_ns=_EPOCH + 9 * _MS, dst_t_ns=_EPOCH + 11 * _MS),
        ],
        lanes=["w0", "w1"],
        roles={"w0": "actor", "w1": "learner"},
        dropped_spans=5,
        clock_steps={"w1": 2},
    )


def test_every_span_becomes_one_event_reproducing_its_nanoseconds() -> None:
    document = chrome_trace(_two_lane_trace())
    slices = [e for e in document["traceEvents"] if e["ph"] == "X"]
    assert len(slices) == 3
    first = next(e for e in slices if e["args"]["path"] == "iteration")
    # Timestamps are rebased to the run's first span and expressed in microseconds.
    assert first["ts"] == 0.0
    assert first["dur"] == 10_000.0
    assert first["pid"] == 0
    assert first["tid"] == 7
    assert first["args"]["cpu_us"] == 4_000.0
    nested = next(e for e in slices if e["args"]["path"] == "iteration/collect")
    assert nested["ts"] == 1_000.0
    assert nested["name"] == "collect"


def test_each_lane_appears_once_as_process_metadata_in_lane_order() -> None:
    document = chrome_trace(_two_lane_trace())
    names = [e for e in document["traceEvents"] if e.get("name") == "process_name"]
    assert [(e["pid"], e["args"]["name"]) for e in names] == [
        (0, "w0 (actor)"),
        (1, "w1 (learner)"),
    ]


def test_an_arrow_becomes_a_flow_pair_sharing_an_id_on_the_right_lanes() -> None:
    document = chrome_trace(_two_lane_trace())
    starts = [e for e in document["traceEvents"] if e["ph"] == "s"]
    ends = [e for e in document["traceEvents"] if e["ph"] == "f"]
    assert len(starts) == len(ends) == 1
    assert starts[0]["id"] == ends[0]["id"]
    assert starts[0]["pid"] == 0
    assert ends[0]["pid"] == 1
    assert ends[0]["ts"] - starts[0]["ts"] == 2_000.0
    assert starts[0]["name"] == "batch"


def test_a_sampled_span_says_so_rather_than_passing_as_measured() -> None:
    document = chrome_trace(_two_lane_trace())
    slices = [e for e in document["traceEvents"] if e["ph"] == "X"]
    sampled = next(e for e in slices if e["args"]["path"] == "iteration/collect")
    assert sampled["args"]["sampled"] is True
    unsampled = next(e for e in slices if e["args"]["path"] == "iteration")
    assert "sampled" not in unsampled["args"]
    # CPU time that was never measured is absent, not zero — the sentinel must not leak.
    assert "cpu_us" not in sampled["args"]


def test_an_origin_is_exported_as_a_definition_site() -> None:
    document = chrome_trace(_two_lane_trace())
    train = next(
        e for e in document["traceEvents"] if e["ph"] == "X" and e["args"]["path"] == "train"
    )
    assert train["args"]["defined_at"] == "pipeline.py:41"


def test_the_drop_counts_and_clock_disclosures_ride_along() -> None:
    document = chrome_trace(_two_lane_trace())
    other = document["otherData"]
    assert other["dropped_spans"] == 5
    assert other["clock_steps"] == {"w1": 2}
    assert other["clock_skew_ns"] == {}
    assert other["epoch_ns"] == _EPOCH


def test_an_empty_trace_exports_an_empty_but_valid_document() -> None:
    document = chrome_trace(AlignedTrace())
    assert document["traceEvents"] == []
    json.dumps(document)


def test_the_cli_writes_a_chrome_trace_a_json_parser_accepts(tmp_path: Path) -> None:
    profiler = Profiler(
        run_dir=tmp_path, role="worker", enabled=True,
        snapshot_interval_s=None, sample_interval_s=None, trace=True,
    )
    with profiler:
        for _ in range(3):
            with profiler.phase("iteration"):
                time.sleep(0.005)

    out = tmp_path / "trace.chrome.json"
    assert cli_main(["trace", str(tmp_path), "--format", "chrome", "-q", "-o", str(out)]) == 0
    document = json.loads(out.read_text(encoding="utf-8"))
    slices = [e for e in document["traceEvents"] if e["ph"] == "X"]
    assert len(slices) == 3
    lanes = [e for e in document["traceEvents"] if e.get("name") == "process_name"]
    assert len(lanes) == 1
    assert all(e["pid"] == 0 for e in slices)
