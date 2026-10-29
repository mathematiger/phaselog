"""Tests for how the CLI is *reached*, rather than what it measures.

Nothing here profiles anything. This is a packaging assertion: that the CLI is reachable
through ``python -m`` when the console script is not on ``PATH``. The failure costs a
first-time reader minutes and produces an error that names neither cause.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from phaselog.accounting.cli import main as cli_main


def test_python_dash_m_runs_the_cli(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    """The console script is not always on ``PATH`` — an unactivated virtualenv, a
    ``pip install --user``, a batch job running ``python`` by absolute path. The module form
    works wherever the package is importable, which is where the profiler was."""
    (tmp_path / "workers").mkdir(parents=True)

    completed = subprocess.run(
        [sys.executable, "-m", "phaselog", "report", str(tmp_path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0
    assert cli_main(["report", str(tmp_path)]) == 0
    assert completed.stdout.strip() == capsys.readouterr().out.strip()
