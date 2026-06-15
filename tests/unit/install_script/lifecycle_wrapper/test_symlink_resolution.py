# -*- coding: utf-8 -*-

"""
Tests for symlink resolution (T-3.8).

The wrapper must work whether invoked via:
- ${INSTALL_DIR}/bin/kiro-gateway (canonical), OR
- ~/.local/bin/kiro-gateway (a symlink to the canonical path).

The wrapper resolves its own real path to find state/install.env.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

WRAPPER = Path(__file__).resolve().parents[4] / "scripts" / "kiro-gateway"


def _write_stub(tmp_path: Path, name: str, body: str) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    p = bin_dir / name
    p.write_text(textwrap.dedent(body))
    p.chmod(0o755)
    return p


def test_wrapper_symlink_resolution(tmp_path, monkeypatch, installed_env):
    """
    GIVEN ~/.local/bin/kiro-gateway is a symlink to ${INSTALL_DIR}/bin/kiro-gateway
    WHEN the user invokes it as `kiro-gateway status`
    THEN the wrapper locates install.env via the resolved real path.
    """
    log = tmp_path / "svc.log"
    _write_stub(
        tmp_path,
        "launchctl",
        f"""\
        #!/usr/bin/env bash
        echo "$@" >> "{log}"
        exit 0
        """,
    )
    monkeypatch.setenv("PATH", f"{tmp_path}/bin:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("UNAME_S", "Darwin")
    # No KIRO_INSTALL_DIR set — wrapper must resolve from $0.
    monkeypatch.delenv("KIRO_INSTALL_DIR", raising=False)

    # Create the symlink in ~/.local/bin pointing at the canonical wrapper.
    symlink_dir = installed_env.parent / "home" / ".local" / "bin"
    symlink_dir.mkdir(parents=True, exist_ok=True)
    symlink = symlink_dir / "kiro-gateway"
    symlink.symlink_to(installed_env / "bin" / "kiro-gateway")
    assert symlink.is_symlink()

    out = subprocess.run(
        ["bash", str(symlink), "version"],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    # version just prints the version from install.env; if the wrapper
    # resolved to the right install dir, the version printed is 2.5.0.
    assert out.returncode == 0, (
        f"exit={out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}"
    )
    assert "2.5.0" in (out.stdout + out.stderr), (
        f"expected 2.5.0 in output; got: stdout={out.stdout!r} stderr={out.stderr!r}"
    )
