# -*- coding: utf-8 -*-

"""
Tests for the `start` subcommand of the lifecycle wrapper.

T-3.1: macOS dispatches `launchctl bootstrap gui/$(id -u) <plist>`.
T-3.2: Linux dispatches `systemctl --user start kiro-gateway`.

These tests use a stub `launchctl` and `systemctl` on PATH that record
their arguments. The wrapper is invoked as a subprocess; the call log
is the assertion target.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

WRAPPER = Path(__file__).resolve().parents[4] / "scripts" / "kiro-gateway"


def _write_stub(tmp_path: Path, name: str, body: str) -> Path:
    """Write a stub binary to tmp_path/bin and return its path."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    p = bin_dir / name
    p.write_text(textwrap.dedent(body))
    p.chmod(0o755)
    return p


def test_wrapper_start_dispatches_launchctl_on_macos(tmp_path, monkeypatch, installed_env):
    """
    GIVEN macOS (UNAME_S=Darwin) and an installed kiro-gateway
    WHEN the user runs `kiro-gateway start`
    THEN `launchctl bootstrap gui/<uid> <plist>` is invoked.
    """
    log = tmp_path / "launchctl.log"
    # The wrapper checks `launchctl print` first; if it returns 0 it
    # assumes the service is already registered and skips bootstrap.
    # Simulate a fresh install (print fails) so bootstrap runs, while
    # the subsequent `kickstart` succeeds.
    _write_stub(
        tmp_path,
        "launchctl",
        f"""\
        #!/usr/bin/env bash
        echo "$@" >> "{log}"
        case "$1" in
            print) exit 1 ;;
            *) exit 0 ;;
        esac
        """,
    )
    # Ensure the wrapper picks up the stub on PATH.
    monkeypatch.setenv("PATH", f"{tmp_path}/bin:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("UNAME_S", "Darwin")
    monkeypatch.setenv("HOME", str(installed_env.parent / "home"))

    # Place the plist where the wrapper expects it.
    plist_dir = installed_env.parent / "home" / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist_path = plist_dir / "com.jwadow.kiro-gateway.plist"
    plist_path.write_text("<?xml version=\"1.0\"?><plist/>\n")

    rc = os.system(f"KIRO_INSTALL_DIR={installed_env} bash {WRAPPER} start >/dev/null 2>&1")
    assert rc == 0, f"wrapper exited {rc}; log was:\n{log.read_text() if log.exists() else '(no log)'}"

    content = log.read_text() if log.exists() else ""
    # The wrapper must have called launchctl bootstrap with the plist path.
    assert "bootstrap" in content, f"expected 'bootstrap' in launchctl log; got: {content!r}"
    assert "gui/" in content, f"expected 'gui/<uid>' in launchctl log; got: {content!r}"
    assert str(plist_path) in content, (
        f"expected plist path {plist_path} in launchctl log; got: {content!r}"
    )


def test_wrapper_start_dispatches_systemctl_on_linux(tmp_path, monkeypatch, installed_env):
    """
    GIVEN Linux (UNAME_S=Linux) and an installed kiro-gateway
    WHEN the user runs `kiro-gateway start`
    THEN `systemctl --user start kiro-gateway` is invoked.
    """
    log = tmp_path / "systemctl.log"
    _write_stub(
        tmp_path,
        "systemctl",
        f"""\
        #!/usr/bin/env bash
        echo "$@" >> "{log}"
        exit 0
        """,
    )
    monkeypatch.setenv("PATH", f"{tmp_path}/bin:{os.environ.get('PATH', '')}")
    monkeypatch.setenv("UNAME_S", "Linux")
    monkeypatch.setenv("HOME", str(installed_env.parent / "home"))

    rc = os.system(f"KIRO_INSTALL_DIR={installed_env} bash {WRAPPER} start >/dev/null 2>&1")
    assert rc == 0, f"wrapper exited {rc}; log was:\n{log.read_text() if log.exists() else '(no log)'}"

    content = log.read_text() if log.exists() else ""
    # The wrapper must have called systemctl --user start kiro-gateway.
    assert "--user" in content, f"expected '--user' in systemctl log; got: {content!r}"
    assert "start" in content, f"expected 'start' in systemctl log; got: {content!r}"
    assert "kiro-gateway" in content, (
        f"expected 'kiro-gateway' unit name in systemctl log; got: {content!r}"
    )
