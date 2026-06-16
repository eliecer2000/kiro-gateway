# -*- coding: utf-8 -*-

"""
Shared fixtures for install-script unit tests.

These fixtures are reused by the installer-script, source-distribution,
service-management, and lifecycle-wrapper test modules. They isolate the
shell scripts from the network, the real filesystem, and platform-specific
binaries (`curl`, `launchctl`, `systemctl`, `python3`).
"""

from __future__ import annotations

import gzip
import io
import os
import stat
import sys
import tarfile
import textwrap
from pathlib import Path

import pytest

# Repo root + scripts dir are useful as absolute anchors.
REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = REPO_ROOT / "scripts"
INSTALL_SH = SCRIPTS_DIR / "install.sh"
INSTALL_COMMON_SH = SCRIPTS_DIR / "lib" / "install-common.sh"
SERVICE_PLIST = SCRIPTS_DIR / "system" / "kiro-gateway.plist"
SERVICE_UNIT = SCRIPTS_DIR / "system" / "kiro-gateway.service"


@pytest.fixture
def temp_install_dir(tmp_path: Path) -> Path:
    """
    A scratch directory the installer can lay out into. The installer normally
    lives under ~/Library/Application Support or ~/.local/share, so tests use
    this directory to avoid touching the user's home.
    """
    target = tmp_path / "install-root"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _build_tarball(archive_root_name: str, members: dict[str, str]) -> bytes:
    """
    Build a deterministic tar.gz in memory with the given archive root and
    members. `members` maps relative paths (e.g. "kiro-gateway-2.5.0/main.py")
    to file contents. Empty strings become directories.
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel_path, content in members.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(name=rel_path)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def fake_tarball() -> bytes:
    """
    A tarball shaped like the published release asset.
        kiro-gateway-2.5.0/
            main.py
            kiro/__init__.py
            requirements.txt
            LICENSE
            .git/HEAD
            tests/test_smoke.py
            docs/README.md
            .github/workflows/ci.yml
    """
    members = {
        f"kiro-gateway-2.5.0/main.py": textwrap.dedent(
            """\
            import json
            import os
            import sys
            from pathlib import Path

            marker = os.getenv("STARTUP_MARKER")
            if marker:
                Path(marker).write_text(json.dumps({
                    "cwd": os.getcwd(),
                    "script": str(Path(sys.argv[0]).resolve()),
                    "env_file": os.getenv("KIRO_ENV_FILE"),
                    "credentials": os.getenv("ACCOUNTS_CONFIG_FILE"),
                }))
            else:
                print("hello")
            """
        ),
        f"kiro-gateway-2.5.0/VERSION": "2.5.0\n",
        f"kiro-gateway-2.5.0/kiro/__init__.py": "",
        f"kiro-gateway-2.5.0/requirements.txt": "",
        f"kiro-gateway-2.5.0/LICENSE": "MIT License\n",
        f"kiro-gateway-2.5.0/scripts/kiro-gateway": (
            SCRIPTS_DIR / "kiro-gateway"
        ).read_text(),
        f"kiro-gateway-2.5.0/scripts/lib/install-common.sh": (
            SCRIPTS_DIR / "lib" / "install-common.sh"
        ).read_text(),
        f"kiro-gateway-2.5.0/scripts/system/kiro-gateway.service": (
            SCRIPTS_DIR / "system" / "kiro-gateway.service"
        ).read_text(),
        f"kiro-gateway-2.5.0/scripts/system/kiro-gateway.plist": (
            SCRIPTS_DIR / "system" / "kiro-gateway.plist"
        ).read_text(),
        f"kiro-gateway-2.5.0/.git/HEAD": "ref: refs/heads/main\n",
        f"kiro-gateway-2.5.0/tests/test_smoke.py": "def test_x(): pass\n",
        f"kiro-gateway-2.5.0/docs/README.md": "# docs\n",
        f"kiro-gateway-2.5.0/.github/workflows/ci.yml": "name: ci\n",
    }
    return _build_tarball("kiro-gateway-2.5.0", members)


@pytest.fixture
def stub_curl(tmp_path: Path, fake_tarball: bytes, monkeypatch: pytest.MonkeyPatch):
    """
    Replace `curl` on PATH with a fake shell script that:

    - For URLs containing `releases/latest`, prints a JSON body with
      `tag_name=v2.5.0`.
    - For URLs ending in `SHA256SUMS`, exits 22 (HTTP 404) and prints
      `No SHA256SUMS available`.
    - For URLs ending in `.tar.gz`, writes the fake tarball to the
      destination (-o).
    - For any other URL, exits 0 with empty body (used for the network
      preflight probe).

    The fixture returns a `calls.log` Path that records every invocation as
    `URL <newline> ARGS` so tests can inspect what the installer requested.
    """
    bin_dir = tmp_path / "stub-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    curl_log = tmp_path / "curl-calls.log"

    # Compute sha256 of the fake tarball so we can serve a valid SHA256SUMS
    # file when tests want to override the no-SHA256SUMS default.
    import hashlib

    tarball_sha = hashlib.sha256(fake_tarball).hexdigest()

    curl_script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        # Stub curl for tests.
        set -uo pipefail

        URL=""
        OUT=""
        WRITE_OUT=0
        while [[ $# -gt 0 ]]; do
          case "$1" in
            -o) OUT="$2"; shift 2 ;;
            -w) WRITE_OUT=1; shift ;;
            -sSL|-fsSL|-fsS|-sI|-I) shift ;;
            --proto|--tlsv1.2|--max-time|-*) shift 2 ;;
            http*://*) URL="$1"; shift ;;
            *) shift ;;
          esac
        done

        echo "URL=$URL" >> "{curl_log}"
        echo "OUT=$OUT" >> "{curl_log}"

        if [[ "$URL" == *"/releases/latest"* ]]; then
          printf '{{"tag_name":"v2.5.0","name":"v2.5.0"}}\n'
          exit 0
        fi

        if [[ "$URL" == *"/SHA256SUMS"* ]] || [[ "$URL" == *"SHA256SUMS"* ]]; then
          if [[ "${{STUB_SERVE_SHA256SUMS:-0}}" == "1" ]]; then
            printf '%s  %s\n' "{tarball_sha}" "kiro-gateway-2.5.0.tar.gz"
            exit 0
          fi
          # Default: 404 / no checksum asset available.
          exit 22
        fi

        if [[ "$URL" == *".tar.gz" ]]; then
          # Write the fake tarball to OUT. The test passes a path via
          # $STUB_TARBALL_PATH (set by stub_curl when available).
          if [[ -n "$OUT" ]]; then
            if [[ -n "${{STUB_TARBALL_PATH:-}}" ]] && [[ -f "${{STUB_TARBALL_PATH}}" ]]; then
              cp "${{STUB_TARBALL_PATH}}" "$OUT"
            else
              printf 'pretend-tarball-bytes' > "$OUT"
            fi
          fi
          exit 0
        fi

        # Network probe default: 200 OK.
        if [[ "$WRITE_OUT" == "1" ]]; then
          printf '200'
        fi
        exit 0
        """
    )

    curl_path = bin_dir / "curl"
    curl_path.write_text(curl_script)
    curl_path.chmod(0o755)

    # Also stub sha256sum so it can hash arbitrary files (delegate to the
    # real binary on PATH behind our stub bin).
    sha_path = bin_dir / "sha256sum"
    real_shasum = "/usr/bin/shasum"
    real_sha256sum = "/usr/bin/sha256sum"
    sha_path.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            # Stub sha256sum: delegate to the real binary if available,
            # otherwise emit a placeholder digest.
            if [[ -x "{real_shasum}" ]]; then
              "{real_shasum}" -a 256 "$@"
            elif [[ -x "{real_sha256sum}" ]]; then
              "{real_sha256sum}" "$@"
            else
              echo "{tarball_sha}  $1"
            fi
            """
        )
    )
    sha_path.chmod(0o755)

    # Route python3 to the test interpreter. This creates a real temporary
    # venv; requirements.txt is empty, so no network access is possible.
    py_path = bin_dir / "python3"
    py_path.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            exec "{sys.executable}" "$@"
            """
        )
    )
    py_path.chmod(0o755)

    # Also stub `launchctl` and `systemctl` so PR 2's
    # `render_and_install_service` step does not hit a real platform
    # service manager when the test does not opt into the dedicated
    # `stub_launchctl` / `stub_systemd_user` fixtures. These are
    # no-frills stubs: they accept any call and succeed. Tests that need
    # to inspect the call log MUST take the dedicated fixtures and put
    # their bin dir on PATH ahead of stub_curl.
    launchctl_default = bin_dir / "launchctl"
    launchctl_default.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            # Default stub launchctl: no logging, just succeed.
            if [[ "$1" == "list" ]]; then
              printf '%s\\n' "PID	Status	Label"
              printf '%s\\n' "-	0	com.jwadow.kiro-gateway"
              exit 0
            fi
            exit 0
            """
        )
    )
    launchctl_default.chmod(0o755)

    systemctl_default = bin_dir / "systemctl"
    systemctl_default.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env bash
            # Default stub systemctl: no logging, just succeed.
            if [[ "$1" == "--user" ]] && [[ "$2" == "show-environment" ]]; then
              echo "PATH=/usr/bin"
              exit 0
            fi
            if [[ "$1" == "--user" ]] && [[ "$2" == "is-active" ]]; then
              echo "inactive"
              exit 0
            fi
            if [[ "$1" == "--user" ]] && [[ "$2" == "daemon-reload" ]]; then
              exit 0
            fi
            exit 0
            """
        )
    )
    systemctl_default.chmod(0o755)

    # Prepend our bin_dir to PATH so the scripts pick up the stubs.
    new_path = f"{bin_dir}:{os.environ.get('PATH', '')}"
    monkeypatch.setenv("PATH", new_path)

    # Make the scripts find the stubs in subprocesses too.
    monkeypatch.setenv("STUB_BIN_DIR", str(bin_dir))
    monkeypatch.setenv("STUB_TARBALL_SHA256", tarball_sha)

    # Default tarball path; tests can override STUB_TARBALL_PATH.
    default_tarball = tmp_path / "kiro-gateway-2.5.0.tar.gz"
    default_tarball.write_bytes(fake_tarball)
    monkeypatch.setenv("STUB_TARBALL_PATH", str(default_tarball))

    return {
        "bin_dir": bin_dir,
        "calls_log": curl_log,
        "tarball_sha256": tarball_sha,
        "tarball_path": default_tarball,
    }


@pytest.fixture
def stub_platform(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest):
    """
    Parametrize-friendly platform stub. The test parameter must be either
    `darwin` or `linux`; we set UNAME_S so the script dispatches accordingly.
    """
    platform = request.param
    if platform not in ("darwin", "linux"):
        raise ValueError(f"unsupported stub_platform value: {platform}")

    monkeypatch.setenv("UNAME_S", "Darwin" if platform == "darwin" else "Linux")
    return platform


@pytest.fixture
def fake_github_api() -> dict:
    """
    Static snapshot of a fake GitHub /releases/latest response. Tests that
    need to override this can take this fixture and re-stub curl themselves.
    """
    return {
        "tag_name": "v2.5.0",
        "name": "v2.5.0",
        "assets": [],
    }


@pytest.fixture
def stub_launchctl(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Place a stub `launchctl` on PATH. PR 2 added `render_and_install_service`
    to the install flow, which calls `launchctl bootstrap` on every macOS
    install. Tests that drive the installer on macOS need this stub so the
    call does not try to hit a real launchd.

    Returns a dict with the bin dir and the log path.
    """
    bin_dir = tmp_path / "launchctl-stub-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log_path = tmp_path / "launchctl-calls.log"

    launchctl_script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        # Stub launchctl for install-script tests.
        set -uo pipefail
        echo "$@" >> "{log_path}"

        if [[ "$1" == "list" ]]; then
          printf '%s\\n' "PID	Status	Label"
          printf '%s\\n' "-	0	com.jwadow.kiro-gateway"
          exit 0
        fi

        if [[ "$1" == "print" ]]; then
          printf 'state = waiting\\n'
          exit 0
        fi

        if [[ "$1" == "bootstrap" ]] || [[ "$1" == "bootout" ]]; then
          exit 0
        fi

        exit 0
        """
    )
    lc_path = bin_dir / "launchctl"
    lc_path.write_text(launchctl_script)
    lc_path.chmod(0o755)

    new_path = f"{bin_dir}:{os.environ.get('PATH', '')}"
    monkeypatch.setenv("PATH", new_path)
    monkeypatch.setenv("STUB_LAUNCHCTL_LOG", str(log_path))

    return {"bin_dir": bin_dir, "log_path": log_path}


@pytest.fixture
def stub_systemd_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    Place a stub `systemctl` on PATH that:
    - returns 0 for `--user show-environment`
    - returns "inactive" for `--user is-active kiro-gateway`
    - returns 0 for `daemon-reload`

    Tests that drive the installer on Linux need this so the
    `preflight_systemd` and `load_service` branches succeed.
    """
    bin_dir = tmp_path / "systemd-stub-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    log_path = tmp_path / "systemctl-calls.log"

    systemctl_script = textwrap.dedent(
        f"""\
        #!/usr/bin/env bash
        # Stub systemctl for install-script tests.
        set -uo pipefail
        echo "$@" >> "{log_path}"

        if [[ "$1" == "--user" ]] && [[ "$2" == "is-active" ]]; then
          echo "inactive"
          exit 0
        fi

        if [[ "$1" == "--user" ]] && [[ "$2" == "status" ]]; then
          echo "kiro-gateway.service - Kiro Gateway"
          echo "   Active: inactive (dead)"
          exit 0
        fi

        if [[ "$1" == "--user" ]] && [[ "$2" == "show-environment" ]]; then
          echo "PATH=/usr/bin"
          exit 0
        fi

        if [[ "$1" == "--user" ]] && [[ "$2" == "daemon-reload" ]]; then
          exit 0
        fi

        exit 0
        """
    )
    systemctl_path = bin_dir / "systemctl"
    systemctl_path.write_text(systemctl_script)
    systemctl_path.chmod(0o755)

    new_path = f"{bin_dir}:{os.environ.get('PATH', '')}"
    monkeypatch.setenv("PATH", new_path)
    monkeypatch.setenv("STUB_SYSTEMCTL_LOG", str(log_path))

    return {"bin_dir": bin_dir, "log_path": log_path}


# Helper: derive a platform-friendly stat mode string for assertions.
def stat_mode(path: Path) -> str:
    """Return the octal mode of `path` as a string (e.g. '700')."""
    mode = path.stat().st_mode
    return oct(stat.S_IMODE(mode))[-3:]
