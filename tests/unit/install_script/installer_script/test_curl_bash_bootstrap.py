# -*- coding: utf-8 -*-

"""
T-BUG-1 — `curl ... | bash` bootstrap must work end-to-end.

When a user runs `curl -fsSL .../install.sh | bash -s -- install`, the
script receives its content from stdin. In that scenario:

* `BASH_SOURCE[0]` is unset (verified empirically on macOS bash 3.2).
* `set -euo pipefail` (line 5 of install.sh) explodes on the unset var.
* `SCRIPT_DIR` falls back to the user's home dir, and the lib cannot
  be sourced as a sibling file.

The fix: install.sh must detect the stdin bootstrap, fetch
`scripts/lib/install-common.sh` from the same GitHub origin to a temp
dir, and source it from there. When run from a local checkout, the
existing sibling-relative behavior is preserved.

This test pipes install.sh content into bash the same way `curl|bash`
does, with a stubbed `curl` that serves the real install-common.sh
when asked. It asserts the bootstrap:
  1. Fetches install-common.sh via curl (not from a sibling file).
  2. Successfully sources it (no `unbound variable` / `No such file`).
  3. Reaches the `--help` short-circuit and exits 0 with usage text.
"""

from __future__ import annotations

import os
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.unit.install_script.conftest import (
    INSTALL_COMMON_SH,
    INSTALL_SH,
    REPO_ROOT,
)


@pytest.fixture
def stub_curl_serving_lib(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> dict[str, Path]:
    """
    A curl stub specialized for the stdin bootstrap test.

    Serves the real install-common.sh content when the URL ends in
    install-common.sh, so the bootstrap can fetch it without hitting
    the network. Also serves the network probe and /releases/latest
    endpoint, so the install flow can complete if a test drives it
    past --help.

    Args:
        tmp_path: pytest's per-test temporary directory fixture.
        monkeypatch: pytest's fixture for environment/PATH overrides.

    Returns:
        A dict with keys ``bin_dir`` (Path to the stub bin directory)
        and ``calls_log`` (Path to the file capturing curl
        invocations).
    """
    bin_dir = tmp_path / "bootstrap-stub-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)

    lib_log = tmp_path / "bootstrap-curl-calls.log"
    lib_content = INSTALL_COMMON_SH.read_text()

    curl_script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        # Stub curl for the stdin bootstrap test. Captures the URL and
        # -o output path; doesn't bother parsing every curl flag.
        set -uo pipefail

        URL=""
        OUT=""
        WRITE_OUT=0
        while [[ $# -gt 0 ]]; do
          case "$1" in
            -o) OUT="$2"; shift 2 ;;
            -w) WRITE_OUT=1; shift ;;
            http*://*)
              if [[ -z "$URL" ]]; then URL="$1"; fi
              shift ;;
            *) shift ;;
          esac
        done

        echo "URL=$URL" >> "{lib_log}"
        echo "OUT=$OUT" >> "{lib_log}"

        if [[ "$URL" == *"install-common.sh" ]]; then
          if [[ -n "$OUT" ]]; then
            printf '%s' '{lib_content.replace("%", "%%").replace("'", "'\\''")}' > "$OUT"
          else
            printf '%s' '{lib_content.replace("%", "%%").replace("'", "'\\''")}'
          fi
          exit 0
        fi

        if [[ "$URL" == *"/releases/latest"* ]]; then
          printf '{{"tag_name":"v2.5.0","name":"v2.5.0"}}\n'
          exit 0
        fi

        if [[ "$URL" == *"/SHA256SUMS"* ]]; then
          exit 22
        fi

        if [[ "$WRITE_OUT" == "1" ]]; then
          printf '200'
        fi
        exit 0
        """
    )

    curl_path = bin_dir / "curl"
    curl_path.write_text(curl_script)
    curl_path.chmod(0o755)

    new_path = f"{bin_dir}:{os.environ.get('PATH', '')}"
    monkeypatch.setenv("PATH", new_path)

    return {"bin_dir": bin_dir, "calls_log": lib_log}


def test_stdin_bootstrap_fetches_lib_and_exits_zero(
    stub_curl_serving_lib: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Pipe install.sh into bash (curl|bash simulation), pass --help, and
    assert the bootstrap fetched install-common.sh and --help succeeded.
    """
    install_sh_content = INSTALL_SH.read_text()
    lib_log = stub_curl_serving_lib["calls_log"]

    new_path = f"{stub_curl_serving_lib['bin_dir']}:{os.environ.get('PATH', '')}"
    result = subprocess.run(
        ["bash", "-s", "--", "--help"],
        input=install_sh_content,
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": new_path},
        timeout=15,
    )

    # Always show subprocess output on failure for debuggability.
    def _debug_context() -> str:
        """Build a debug context string with exit code, stdout, stderr, and curl log."""
        try:
            log_text = lib_log.read_text()
        except (FileNotFoundError, OSError):
            log_text = "<log not created>"
        return (
            f"\n--- exit code ---\n{result.returncode}"
            f"\n--- stdout ---\n{result.stdout}"
            f"\n--- stderr ---\n{result.stderr}"
            f"\n--- curl log ---\n{log_text}"
        )

    # The bootstrap must have called curl to fetch install-common.sh.
    log_text = lib_log.read_text() if lib_log.exists() else ""
    assert "install-common.sh" in log_text, (
        f"install-common.sh was not fetched.{_debug_context()}"
    )

    # The script must not have died on the bootstrap.
    assert "unbound variable" not in result.stderr, (
        f"BASH_SOURCE unbound error.{_debug_context()}"
    )
    assert "No such file" not in result.stderr, (
        f"lib not found.{_debug_context()}"
    )

    # And --help must have short-circuited to a clean exit 0 with usage.
    assert result.returncode == 0, (
        f"--help did not exit 0.{_debug_context()}"
    )
    assert "Usage:" in result.stdout or "--help" in result.stdout, (
        f"--help output missing.{_debug_context()}"
    )


def test_local_checkout_still_uses_sibling_lib(stub_curl: dict[str, Path]) -> None:
    """
    When install.sh is run as a real file (./scripts/install.sh), the
    bootstrap must still use the sibling file path — NOT fetch the lib
    over the network. This guards against the regression of the fix
    always self-fetching even in the checkout case.
    """
    new_path = f"{stub_curl['bin_dir']}:{os.environ.get('PATH', '')}"
    result = subprocess.run(
        ["bash", str(INSTALL_SH), "--help"],
        cwd=str(REPO_ROOT),
        env={**os.environ, "PATH": new_path},
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, (
        f"exit {result.returncode}: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "Usage:" in result.stdout

    # The sibling-path bootstrap must NOT have called curl to fetch
    # install-common.sh. The local checkout already has the file.
    curl_log = stub_curl["calls_log"].read_text() if stub_curl["calls_log"].exists() else ""
    assert "install-common.sh" not in curl_log, (
        f"local checkout unexpectedly fetched the lib over the network:\n{curl_log}"
    )
