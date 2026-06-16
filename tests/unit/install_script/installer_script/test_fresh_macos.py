# -*- coding: utf-8 -*-

"""
T-1.1 — Fresh macOS install produces the documented directory layout.

Spec: installer-script §"Scenario: Fresh install on macOS"
Tasks: T-1.1 [red] → T-1.1 [green] → T-1.1 [refactor]
"""

from __future__ import annotations

import os
import json
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


def _run_installer(env: dict, install_dir: Path, *args: str) -> subprocess.CompletedProcess:
    """Run scripts/install.sh in a subprocess with the given env additions."""
    full_env = os.environ.copy()
    full_env.update(env)
    cmd = ["bash", str(REPO_ROOT / "scripts" / "install.sh"), "--install-dir", str(install_dir), *args]
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_install_fresh_macos_layout(tmp_path, stub_curl, monkeypatch, fake_tarball):
    """
    T-1.1 — macOS fresh install creates the full layout under INSTALL_DIR.

    Asserts the post-install directory layout per the design doc:

        ${INSTALL_DIR}/
        ├── app/
        ├── app.prev/        (only if a previous install existed; not asserted)
        ├── venv/
        ├── bin/
        ├── state/
        └── logs/
    """
    install_dir = tmp_path / "KiroGateway"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("UNAME_S", "Darwin")
    # monkeypatch already puts stub_curl/bin first on PATH and sets
    # STUB_TARBALL_PATH; just run the installer with the patched env.
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }

    result = _run_installer(env, install_dir, "--version", "2.5.0", "--insecure")
    if result.returncode != 0:
        pytest.fail(
            f"installer exited {result.returncode}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )

    # The full macOS layout must exist per the design doc.
    expected = [
        install_dir / "app",
        install_dir / "venv",
        install_dir / "bin",
        install_dir / "state",
        install_dir / "logs",
    ]
    for path in expected:
        assert path.is_dir(), f"expected directory missing: {path}"
    assert not (install_dir / "state" / "credentials.json").exists()


def test_rendered_macos_service_starts_release_entrypoint_from_state(
    tmp_path, stub_curl
):
    """Execute the rendered launchd contract with a real temporary venv."""
    install_dir = tmp_path / "KiroGateway"
    env = {
        "HOME": str(tmp_path),
        "UNAME_S": "Darwin",
        "PATH": f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = _run_installer(env, install_dir, "--version", "2.5.0", "--insecure")
    assert result.returncode == 0, result.stderr

    plist_path = (
        tmp_path / "Library" / "LaunchAgents" / "com.jwadow.kiro-gateway.plist"
    )
    service = plistlib.loads(plist_path.read_bytes())
    marker = tmp_path / "startup.json"
    runtime_env = os.environ.copy()
    runtime_env.update(service["EnvironmentVariables"])
    runtime_env["STARTUP_MARKER"] = str(marker)
    started = subprocess.run(
        service["ProgramArguments"],
        cwd=service["WorkingDirectory"],
        env=runtime_env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert started.returncode == 0, started.stderr
    payload = json.loads(marker.read_text())
    assert payload["cwd"] == str(install_dir / "state")
    assert payload["script"] == str((install_dir / "app" / "main.py").resolve())
    assert payload["env_file"] == str(install_dir / "state" / ".env")
