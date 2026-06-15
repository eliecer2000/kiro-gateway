# -*- coding: utf-8 -*-

"""
Tests for the `help` subcommand (T-3.7).

The wrapper must:
- exit 0 when invoked with `help`, `--help`, `-h`, or no args.
- print all subcommands to stdout.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[4] / "scripts" / "kiro-gateway"


@pytest.mark.parametrize("args", [["help"], ["--help"], ["-h"], []])
def test_wrapper_help_exits_zero(args, tmp_path, monkeypatch, installed_env):
    """
    GIVEN the wrapper is invoked with help / --help / -h / no args
    WHEN the script runs
    THEN exit 0 and stdout contains all subcommands.
    """
    monkeypatch.setenv("UNAME_S", "Darwin")
    out = subprocess.run(
        ["bash", str(WRAPPER), *args],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, (
        f"args={args} exit={out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}"
    )
    combined = out.stdout + out.stderr
    for sub in ("start", "stop", "restart", "status", "logs", "update", "uninstall", "version"):
        assert sub in combined, f"args={args} expected {sub!r} in output; got: {combined!r}"
