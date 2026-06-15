# -*- coding: utf-8 -*-

"""
Tests for the `update --rollback` subcommand (T-3.4).

The wrapper must:
- swap app/ and app.prev/ back, leaving no app.prev/ behind.
- reload the service.
- exit 0 on success.
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


def test_wrapper_update_rollback_restores_prev(tmp_path, monkeypatch, installed_env):
    """
    GIVEN app/ and app.prev/ contain different sentinel files
    WHEN `kiro-gateway update --rollback` is invoked
    THEN app/ now matches the old app.prev/ and app.prev/ is gone.
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
    monkeypatch.setenv("HOME", str(installed_env.parent / "home"))

    # installed_env already has app/VERSION=2.5.0 and app.prev/VERSION=2.4.0
    new_app_version = (installed_env / "app" / "VERSION").read_text()
    prev_app_version = (installed_env / "app.prev" / "VERSION").read_text()
    assert new_app_version != prev_app_version

    out = subprocess.run(
        ["bash", str(WRAPPER), "update", "--rollback"],
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )
    assert out.returncode == 0, (
        f"exit={out.returncode}\nstdout={out.stdout!r}\nstderr={out.stderr!r}"
    )

    # After rollback: app/VERSION == 2.4.0, app.prev/ gone.
    assert (installed_env / "app" / "VERSION").read_text() == "2.4.0\n"
    assert not (installed_env / "app.prev").exists(), "app.prev/ should be removed after rollback"
    # app.new/ should not exist either.
    assert not (installed_env / "app.new").exists()
    # The service was reloaded.
    log_content = log.read_text() if log.exists() else ""
    assert "bootstrap" in log_content, f"expected bootstrap in launchctl log; got: {log_content!r}"
