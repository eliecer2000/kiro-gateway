# -*- coding: utf-8 -*-

"""
Tests for the `update --rollback` guard when no app.prev/ exists (T-3.10).

The wrapper must:
- exit 1 with the literal message "No previous version to roll back to."
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[4] / "scripts" / "kiro-gateway"


def test_rollback_no_prev_fails(tmp_path, monkeypatch, installed_env):
    """
    GIVEN app.prev/ does not exist
    WHEN `kiro-gateway update --rollback` is invoked
    THEN exit 1 and stderr contains the exact "No previous version to roll back to." message.
    """
    # Remove app.prev/ to simulate "no previous version".
    import shutil
    shutil.rmtree(installed_env / "app.prev")

    out = subprocess.run(
        ["bash", str(WRAPPER), "update", "--rollback"],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    assert out.returncode == 1, (
        f"expected exit 1, got {out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}"
    )
    combined = out.stdout + out.stderr
    assert "No previous version to roll back to." in combined, (
        f"expected exact error message; got: {combined!r}"
    )
