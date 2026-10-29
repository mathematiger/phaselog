"""Export the aligned timeline as Chrome trace events, for Perfetto and its relatives.

The timeline page answers one question well — which worker waited, and for whom. Everything
past that (search, SQL over slices, flame charts, laying this trace beside a Kineto capture)
is what [Perfetto](https://ui.perfetto.dev) and ``chrome://tracing`` already do, and the
spans this package aligns map onto their input format one to one: a :class:`PlacedSpan` is a
complete-duration event, an :class:`Arrow` is a flow-event pair. Exporting is pure
derivation over an :class:`AlignedTrace` — no new measurement, no new clock read.

What deliberately does not survive the export: the findings (they are this package's
conclusions, not data), the GPU strip (1 Hz whole-device readings joined to nothing — see
the timeline's own note), and lifecycle marks (an aligned mark does not carry the lane that
recorded it, and inventing one would place it). The caveats travel in ``otherData`` instead
of vanishing: a viewer will render a skew-corrupted trace as confidently as a healthy one,
so the fields that disclose repairs must ride along for whoever reads the file later.
"""

from __future__ import annotations

from typing import Any

from phaselog.accounting.trace import (
    FLAG_ASYNC_UNSYNCED,
    FLAG_AUTO,
    FLAG_DEVICE_SYNC,
    FLAG_SAMPLED,
    UNMEASURED,
)
from phaselog.accounting.tracealign import AlignedTrace


def chrome_trace(aligned: AlignedTrace) -> dict[str, Any]:
    """Return the trace as a Chrome trace event document (the JSON object form).

    Test specifically:
        - every span becomes one ``X`` event whose ``ts``/``dur`` reproduce its nanoseconds
        - each lane appears once as a ``process_name`` metadata event, in lane order
        - an arrow becomes an ``s``/``f`` pair sharing an id, on the right lanes
        - a sampled span says so in its ``args`` rather than passing as measured
        - ``otherData`` carries the drop counts and clock disclosures
    """
    # One pid per worker and one tid per thread, which is what the two fields mean in the
    # format. The timeline's lanes are per worker *thread*, so they are not reused here:
    # ordering by first activity over the spans gives the same reading order without parsing
    # lane labels back apart.
    worker_pid: dict[str, int] = {}
    worker_role: dict[str, str] = {}
    for span in sorted(aligned.spans, key=lambda span: span.t0_ns):
        if span.worker not in worker_pid:
            worker_pid[span.worker] = len(worker_pid)
            worker_role[span.worker] = span.role
    for arrow in aligned.arrows:
        for endpoint in (arrow.src_worker, arrow.dst_worker):
            if endpoint not in worker_pid:
                worker_pid[endpoint] = len(worker_pid)
                worker_role[endpoint] = ""

    # Rebased so timestamps are run-relative: viewers cope with epoch-nanosecond values but
    # render them as unreadable 16-digit axes, and the epoch is preserved below.
    t_base = min((span.t0_ns for span in aligned.spans), default=0)
    events: list[dict[str, Any]] = []

    for worker, pid in worker_pid.items():
        role = worker_role[worker]
        name = f"{worker} ({role})" if role else worker
        events.append(
            {"ph": "M", "name": "process_name", "pid": pid, "tid": 0, "args": {"name": name}},
        )
        events.append(
            {"ph": "M", "name": "process_sort_index", "pid": pid, "tid": 0,
             "args": {"sort_index": pid}},
        )

    for span in aligned.spans:
        args: dict[str, Any] = {"path": "/".join(span.path)}
        if span.cpu_ns != UNMEASURED:
            args["cpu_us"] = _us(span.cpu_ns)
        if span.flags & FLAG_SAMPLED:
            args["sampled"] = True
        if span.flags & FLAG_ASYNC_UNSYNCED:
            args["async_unsynced"] = True
        if span.flags & FLAG_DEVICE_SYNC:
            args["device_sync"] = True
        if span.origin is not None:
            # The function's definition site, not the line that blocked — the same
            # distinction the timeline states wherever it renders an origin.
            args["defined_at"] = f"{span.origin.file}:{span.origin.line}"
        events.append(
            {
                "ph": "X",
                "name": span.path[-1],
                "cat": "auto" if span.flags & FLAG_AUTO else "phase",
                "ts": _us(span.t0_ns - t_base),
                "dur": _us(span.t1_ns - span.t0_ns),
                "pid": worker_pid[span.worker],
                "tid": span.thread_id,
                "args": args,
            },
        )

    for index, arrow in enumerate(aligned.arrows):
        common = {"cat": "link", "name": arrow.channel, "id": index, "args": {"key": arrow.key}}
        events.append(
            {"ph": "s", "ts": _us(arrow.src_t_ns - t_base),
             "pid": worker_pid[arrow.src_worker], "tid": 0, **common},
        )
        events.append(
            {"ph": "f", "bp": "e", "ts": _us(arrow.dst_t_ns - t_base),
             "pid": worker_pid[arrow.dst_worker], "tid": 0, **common},
        )

    return {
        "traceEvents": events,
        "displayTimeUnit": "ms",
        "otherData": {
            "generator": "phaselog",
            "epoch_ns": t_base,
            "dropped_spans": aligned.dropped_spans,
            "dropped_links": aligned.dropped_links,
            "unmatched_waits": len(aligned.unmatched_waits),
            "clock_steps": aligned.clock_steps,
            "clock_skew_ns": {
                f"{src}->{dst}": bound
                for (src, dst), bound in sorted(aligned.clock_skew_ns.items())
            },
        },
    }


def _us(ns: int) -> float:
    """Nanoseconds to the microseconds the format expects, keeping sub-µs precision."""
    return ns / 1000.0
