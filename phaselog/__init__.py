"""Two independent profiling tools for Python, sharing nothing but this distribution.

``phaselog.accounting`` is the flagship: low-overhead accounting for phases *you* name,
aggregated across every process in a long multi-process run. ``phaselog.LineProfiler``,
re-exported here, is a context-manager line-by-line profiler for a bounded region you
already suspect.
"""

from phaselog.profiler import (
    FunctionStats,
    LineProfiler,
    LineStats,
    start_profiling,
    stop_profiling,
)

__all__ = [
    "FunctionStats",
    "LineProfiler",
    "LineStats",
    "start_profiling",
    "stop_profiling",
]

__version__ = "0.11.0"
