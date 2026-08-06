"""Tests for Streamlit entrypoint bootstrap behavior."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_entrypoint_runs_outside_repository_root(tmp_path: Path) -> None:
    repository_root = Path(__file__).resolve().parents[1]
    entrypoint = repository_root / "frontend" / "app.py"
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, str(entrypoint)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "No module named 'frontend'" not in completed.stderr
