# -*- coding: utf-8 -*-

"""
Tests for the `missing install` guard (T-3.6).

The wrapper must:
- exit 1 with the actionable error message if INSTALL_DIR/state/install.env
  does not exist.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[4] / "scripts" / "kiro-gateway"


def test_wrapper_missing_install_exits_nonzero(tmp_path, monkeypatch):
    """
    GIVEN INSTALL_DIR/state/install.env does not exist
    WHEN the wrapper is invoked with any subcommand (here: `start`)
    THEN it prints the actionable error message and exits 1.
    """
    fake_install = tmp_path / "nonexistent-install"
    monkeypatch.setenv("KIRO_INSTALL_DIR", str(fake_install))
    monkeypatch.setenv("UNAME_S", "Darwin")

    out = subprocess.run(
        ["bash", str(WRAPPER), "start"],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    assert out.returncode == 1, (
        f"expected exit 1, got {out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}"
    )
    combined = out.stdout + out.stderr
    assert "kiro-gateway is not installed" in combined, (
        f"expected 'kiro-gateway is not installed' in output; got: {combined!r}"
    )
    # The one-liner install command should appear too.
    assert "install.sh" in combined, f"expected install one-liner; got: {combined!r}"
