# -*- coding: utf-8 -*-

"""
T-2.10 — On Linux without systemd (Alpine, Void, NixOS, etc.), the
installer MUST abort with a clear Docker recommendation. No install-dir
state is created.

Spec: service-management §"Requirement: Non-systemd Linux is refused with
a friendly message".
Tasks: T-2.10 [red] → T-2.10 [green] → T-2.10 [refactor]
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

from tests.unit.install_script.conftest import REPO_ROOT


def _run_installer(env: dict, install_dir: Path, *args: str) -> subprocess.CompletedProcess:
    full_env = os.environ.copy()
    full_env.update(env)
    cmd = [
        "bash",
        str(REPO_ROOT / "scripts" / "install.sh"),
        "--install-dir",
        str(install_dir),
        *args,
    ]
    return subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=60,
    )


@pytest.fixture
def empty_systemctl_dir(tmp_path: Path, stub_curl, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """
    Build a bin dir that shadows the real `systemctl` with a shim that
    returns exit 1. The installer's preflight_systemd() does two checks:
      1. `command -v systemctl` — passes because the shim exists in PATH.
      2. `systemctl --user show-environment` — fails because the shim
         exits 1, triggering the "systemd --user is not available" error.
    The bin dir is put FIRST on PATH, so it shadows the real
    `/usr/bin/systemctl` on CI runners. The real PATH is preserved
    unchanged so `bash`, `env`, `tar`, and other essentials remain
    available to subprocess.run() invocations.
    """
    bin_dir = tmp_path / "empty-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    # Stub `uname` so the installer thinks it's running on Linux.
    uname_path = bin_dir / "uname"
    uname_path.write_text("#!/usr/bin/env bash\necho Linux\n")
    uname_path.chmod(0o755)

    # Shim `systemctl` that always fails. `command -v systemctl` finds
    # this (returns 0), but any `systemctl ...` invocation exits 1,
    # which the installer treats as "systemd --user not available".
    systemctl_shim = bin_dir / "systemctl"
    systemctl_shim.write_text("#!/usr/bin/env bash\nexit 1\n")
    systemctl_shim.chmod(0o755)

    # Remove any systemctl shim that stub_curl places in its own bin dir
    # to prevent fallback resolution to it.
    curl_bin = stub_curl["bin_dir"]
    systemctl_in_curl = curl_bin / "systemctl"
    if systemctl_in_curl.exists():
        systemctl_in_curl.unlink()

    # Keep the real PATH intact — the shim wins by being first.
    new_path = f"{bin_dir}:{curl_bin}:{os.environ.get('PATH', '')}"
    monkeypatch.setenv("PATH", new_path)
    monkeypatch.setenv("STUB_EMPTY_SYSTEMCTL_BIN", str(bin_dir))
    return {"bin_dir": bin_dir}


def test_non_systemd_linux_refused(
    tmp_path: Path, stub_curl, empty_systemctl_dir, monkeypatch
) -> None:
    """
    With a systemctl shim that fails on Linux, the installer MUST exit
    non-zero AND print the spec's refusal message. The install-dir state
    MUST NOT be created.
    """
    install_dir = tmp_path / ".local" / "share" / "kiro-gateway"
    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("UNAME_S", "Linux")
    env = {
        "HOME": str(home),
        "UNAME_S": "Linux",
        "PATH": f"{empty_systemctl_dir['bin_dir']}:{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = _run_installer(env, install_dir, "--version", "2.5.0", "--insecure")
    assert result.returncode != 0, (
        f"installer should have refused but exited 0:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    combined = result.stdout + result.stderr
    # The shim makes the second preflight check fail with this message.
    assert "systemd --user is not available" in combined, (
        f"missing systemd --user refusal message in:\n{combined}"
    )
    assert "Docker" in combined, f"missing Docker hint in:\n{combined}"

    # The install-dir state MUST NOT have been created (the refusal is
    # preflight, not after lay_out_state).
    assert not (install_dir / "state").exists(), (
        f"state dir was created despite refusal: {install_dir / 'state'}"
    )
