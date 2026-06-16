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


def _path_without_systemctl(original_path: str) -> str:
    """
    Return PATH with any directory containing a `systemctl` binary removed.
    This is critical on CI runners (e.g. GitHub Actions ubuntu-latest) that
    ship a real `/usr/bin/systemctl`. Without filtering, `command -v
    systemctl` would find the real binary and bypass the installer's
    non-systemd preflight.
    """
    cleaned: list[str] = []
    for entry in original_path.split(":"):
        if entry and not Path(entry, "systemctl").exists():
            cleaned.append(entry)
    return ":".join(cleaned)


@pytest.fixture
def empty_systemctl_dir(tmp_path: Path, stub_curl, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Any]:
    """
    Build a bin dir that has NO `systemctl` and NO `service` command, so
    `command -v systemctl` returns empty. The bin dir is put FIRST on
    PATH; the stub_curl bin dir comes second. Critically, this fixture
    DELETES the systemctl stub from stub_curl's bin dir AND filters the
    trailing real PATH so a system `systemctl` (e.g. on CI Linux runners)
    cannot satisfy the lookup.
    """
    bin_dir = tmp_path / "empty-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    # Put a stub `uname` that reports Linux.
    uname_path = bin_dir / "uname"
    uname_path.write_text("#!/usr/bin/env bash\necho Linux\n")
    uname_path.chmod(0o755)

    # Remove the systemctl stub that stub_curl installs in its own bin
    # dir; otherwise `command -v systemctl` finds it via PATH fallback.
    curl_bin = stub_curl["bin_dir"]
    systemctl_in_curl = curl_bin / "systemctl"
    if systemctl_in_curl.exists():
        systemctl_in_curl.unlink()

    real_path = _path_without_systemctl(os.environ.get("PATH", ""))
    new_path = f"{bin_dir}:{curl_bin}:{real_path}"
    monkeypatch.setenv("PATH", new_path)
    monkeypatch.setenv("STUB_EMPTY_SYSTEMCTL_BIN", str(bin_dir))
    return {"bin_dir": bin_dir}


def test_non_systemd_linux_refused(
    tmp_path: Path, stub_curl, empty_systemctl_dir, monkeypatch
) -> None:
    """
    With no `systemctl` on PATH on Linux, the installer MUST exit non-zero
    AND print the spec's exact message. The install-dir state MUST NOT be
    created.
    """
    install_dir = tmp_path / ".local" / "share" / "kiro-gateway"
    home = tmp_path
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("UNAME_S", "Linux")
    real_path = _path_without_systemctl(os.environ.get("PATH", ""))
    env = {
        "HOME": str(home),
        "UNAME_S": "Linux",
        "PATH": f"{empty_systemctl_dir['bin_dir']}:{stub_curl['bin_dir']}:{real_path}",
        "STUB_TARBALL_PATH": str(stub_curl["tarball_path"]),
    }
    result = _run_installer(env, install_dir, "--version", "2.5.0", "--insecure")
    assert result.returncode != 0, (
        f"installer should have refused but exited 0:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    combined = result.stdout + result.stderr
    assert "Non-systemd Linux detected" in combined, (
        f"missing refusal message in:\n{combined}"
    )
    assert "kiro-gateway requires systemd --user" in combined, (
        f"missing systemd hint in:\n{combined}"
    )
    assert "Docker" in combined, f"missing Docker hint in:\n{combined}"

    # The install-dir state MUST NOT have been created (the refusal is
    # preflight, not after lay_out_state).
    assert not (install_dir / "state").exists(), (
        f"state dir was created despite refusal: {install_dir / 'state'}"
    )
