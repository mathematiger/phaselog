"""Differential tests: one workload, both event backends, the two records compared.

Every other line-profiler test asserts against an expectation written by hand, and
[tests/test_profiler.py](tests/test_profiler.py) runs each of them under both backends — which
proves each backend satisfies the expectation, and says nothing about whether the two agree
where no expectation was written. That gap is where the two worst defects in this package
lived: ``PY_YIELD`` was never registered, so a suspended generator was billed its consumer's
whole between-pulls time, and ``PY_RETURN`` fired for frames the profiler did not own, so a
multi-frame library call reported a fraction of its duration. Both are events ``sys.settrace``
delivers correctly and the monitoring port dropped or over-delivered. Neither backend's own
suite could see them, because every timing test either stayed fully in-project or called
single-frame C functions.

``settrace`` is the specification here. It is the older backend, the only one 3.10 and 3.11
can use, and the one the timing model was written against; where the two disagree, the
question to ask is what monitoring is doing differently, not which number looks nicer.

The workloads are therefore chosen for the shape that defeats a port rather than for coverage:
frames the project does not own, on both sides of the project's own code. What is compared is
what a port can silently get wrong — which lines were recorded, how many times, and how much
time landed on each — at a tolerance loose enough that the two backends' differing overhead
cannot produce a failure, and tight enough that an event dropped or delivered twice must.
"""
from __future__ import annotations

import importlib.util
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from phaselog import LineProfiler
from phaselog.profiler import _MONITORING, Backend

THIS_DIR = str(Path(__file__).resolve().parent)

pytestmark = pytest.mark.skipif(
    _MONITORING is None,
    reason="a differential test needs both backends; sys.monitoring arrived in 3.12",
)

_TIMED_FLOOR_S = 0.03
"""How much time a line must carry before the two records are compared on it.

Below this the figure is bookkeeping noise and the two backends' overheads differ by more
than the measurement, so comparing it would be a flaky test rather than a strict one. Both
defects this file exists for moved tens of milliseconds onto or off a single line."""

_AGREEMENT = 0.5
"""Fraction of the larger reading the smaller must reach. Deliberately loose: the two backends
carry different per-event costs, so exact agreement is not a property either can have. The
defects it has to catch turned a 0.06 s line into 0.0002 s and a 0 s line into 0.12 s."""

_SLEEP_S = 0.06
"""Sleep each workload spends outside the project, where attribution is the whole question."""


def _module_outside_the_project(tmp_path: Path, name: str, source: str) -> SimpleNamespace:
    """Import ``source`` from a file outside the project folder, so it is never admitted.

    The point of every workload here is a frame the profiler must *not* trace but must still
    account for, and a helper defined in this file would be traced like any other.
    """
    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Recording and comparing
# --------------------------------------------------------------------------- #
_LineRecord = dict[tuple[str, int], tuple[int, float]]
"""``(function name, line number)`` to ``(hits, seconds)``, for one backend's run."""


def _record(backend: Backend, workload: Callable[[], None], recorder: str) -> _LineRecord:
    """Everything ``backend`` recorded for this file while ``workload`` ran.

    ``recorder`` names the function holding the ``with`` block, and its rows are dropped. The
    two backends legitimately disagree about it: ``sys.monitoring`` delivers ``LINE`` for a
    frame already on the stack when the profiler starts, and ``sys.settrace`` cannot — its
    ``call`` event fires only on entry, which has already happened. That asymmetry is
    documented and tested elsewhere; leaving it in here would fail every comparison for the
    one reason that is not a defect.
    """
    profiler = LineProfiler(project_folder=THIS_DIR, backend=backend)
    with profiler:
        workload()

    recorded: _LineRecord = {}
    for (filename, name, _first_line), function in profiler.get_stats().items():
        if filename != __file__ or name == recorder:
            continue
        for line, stats in function.line_stats.items():
            recorded[(name, line)] = (stats.hits, stats.total_time)
    return recorded


def _both_backends(workload: Callable[[], None]) -> tuple[_LineRecord, _LineRecord]:
    """Run ``workload`` under each backend in turn and return ``(settrace, monitoring)``.

    Both run in this one interpreter, which is also the scenario ``restart_events()`` exists
    for: a code object monitoring returned ``DISABLE`` for stays disabled for the life of the
    process, so a backend that forgot to clear the opt-outs would record a confident nothing
    on the second pass and be caught here as a disagreement.
    """
    return _record("settrace", workload, "_record"), _record("monitoring", workload, "_record")


def _assert_backends_agree(workload: Callable[[], None]) -> _LineRecord:
    """Fail unless both backends recorded the same lines, hits and — where it matters — time.

    Returns the settrace record, so a caller can additionally assert what the *right* answer
    is. Agreement alone would be satisfied by two backends that are wrong together.
    """
    settrace, monitoring = _both_backends(workload)

    assert settrace, "the workload recorded nothing, so the comparison proves nothing"
    assert set(settrace) == set(monitoring), (
        "the backends recorded different lines: "
        f"settrace only {sorted(set(settrace) - set(monitoring))}, "
        f"monitoring only {sorted(set(monitoring) - set(settrace))}"
    )

    for key, (hits, seconds) in sorted(settrace.items()):
        other_hits, other_seconds = monitoring[key]
        assert hits == other_hits, (
            f"{key} was hit {hits} times under settrace and {other_hits} under monitoring"
        )
        largest = max(seconds, other_seconds)
        if largest < _TIMED_FLOOR_S:
            continue
        assert min(seconds, other_seconds) >= _AGREEMENT * largest, (
            f"{key} was billed {seconds:.4f}s under settrace and {other_seconds:.4f}s under "
            "monitoring — one of them is attributing a frame the other is not"
        )
    return settrace


def _billed(record: _LineRecord, function: str) -> float:
    """Seconds the record puts on ``function``, across all of its lines."""
    return sum(seconds for (name, _line), (_hits, seconds) in record.items() if name == function)


# --------------------------------------------------------------------------- #
# Workloads: the project's code with frames it does not own on either side
# --------------------------------------------------------------------------- #
def ticker() -> Iterator[int]:
    yield 1
    yield 2
    yield 3


def test_a_generator_drained_by_non_project_code_is_billed_alike(tmp_path: Path) -> None:
    """The consumer's time belongs to the consumer under either backend.

    ``sys.settrace`` fires ``return`` when a generator suspends; ``PY_YIELD`` is its
    monitoring counterpart, and without it the yield line absorbed everything the consumer
    did before pulling again — a confident, plausible figure on the wrong line.
    """
    consumer = _module_outside_the_project(
        tmp_path,
        "slow_consumer",
        "import time\n"
        "def drain(gen):\n"
        "    for _ in gen:\n"
        f"        time.sleep({_SLEEP_S})\n",
    )

    def workload() -> None:
        consumer.drain(ticker())

    record = _assert_backends_agree(workload)

    assert _billed(record, "ticker") < _SLEEP_S, (
        "a suspended generator must not be billed what its consumer did next"
    )


def test_a_multiframe_library_call_is_billed_alike(tmp_path: Path) -> None:
    """A non-project callee's whole duration belongs to the project line that called it.

    ``PY_RETURN`` fired for every Python frame, so the callee's *first* inner return closed
    the caller's armed line and everything after it vanished. Nearly every site-packages call
    has more than one Python frame, which is what made this the more damaging of the two.
    """
    library = _module_outside_the_project(
        tmp_path,
        "slow_library",
        "import time\n"
        "def _quick():\n"
        "    return 1\n"
        "def slow_multiframe():\n"
        "    _quick()\n"
        f"    time.sleep({_SLEEP_S})\n"
        "    return 1\n",
    )

    def calls_the_library() -> None:
        library.slow_multiframe()

    def workload() -> None:
        calls_the_library()

    record = _assert_backends_agree(workload)

    assert _billed(record, "calls_the_library") > _SLEEP_S * 0.8, (
        "the calling line must carry the library call's whole duration"
    )


def test_a_callback_into_project_code_from_outside_is_billed_alike(tmp_path: Path) -> None:
    """Control flow crossing the boundary twice — the shape a sort key or a hook takes.

    The project's code is entered from a frame that was never admitted, so the caller's line
    is not armed when it starts and there is no obvious owner for the gap. Both backends have
    to reach the same answer about it, whatever that answer is.
    """
    library = _module_outside_the_project(
        tmp_path,
        "slow_caller",
        "import time\n"
        "def apply(fn, values):\n"
        "    out = []\n"
        "    for value in values:\n"
        "        out.append(fn(value))\n"
        f"        time.sleep({_SLEEP_S / 3})\n"
        "    return out\n",
    )

    def double(value: int) -> int:
        doubled = value * 2
        return doubled

    def workload() -> None:
        library.apply(double, [1, 2, 3])

    record = _assert_backends_agree(workload)

    assert _billed(record, "double") < _SLEEP_S, (
        "the callback must not absorb what the caller did between calls"
    )


def test_in_project_work_around_a_sleep_is_billed_alike() -> None:
    """The control: no foreign frame at all, so a failure here is the timing model itself.

    Without it a change that broke both backends the same way would leave every comparison
    above green, since they only ever ask whether the two agree.
    """
    def leaf(count: int) -> int:
        total = 0
        for index in range(count):
            total += index
        return total

    def workload() -> None:
        for _ in range(3):
            leaf(200)
        time.sleep(_SLEEP_S)

    record = _assert_backends_agree(workload)

    assert _billed(record, "workload") > _SLEEP_S * 0.8, (
        "the sleeping line must dominate, or the two agree on a broken timing model"
    )
