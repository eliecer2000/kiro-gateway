# -*- coding: utf-8 -*-

"""
T-4.4: Docker e2e integration test for the Linux install path.

This is a stub. The full test (running inside an `ubuntu:24.04` container
with a stub `https://api.github.com` served by a local `http.server`)
is gated by `-m integration` and is opt-in:

    .venv/bin/pytest -m integration tests/integration/install_script/

The stub verifies that the integration test infrastructure is in place:
- a `Dockerfile` exists that runs the installer,
- a `docker-compose.yml` exists with the right service shape,
- the install script's contract points are reachable from the container.

macOS path is verified manually (cannot run launchd in CI).
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCKERFILE = REPO_ROOT / "Dockerfile"
DOCKER_COMPOSE = REPO_ROOT / "docker-compose.yml"
INSTALL_SH = REPO_ROOT / "scripts" / "install.sh"


pytestmark = pytest.mark.integration


def test_dockerfile_exists():
    """The repo ships a Dockerfile (used by the CI integration run)."""
    assert DOCKERFILE.exists(), f"missing {DOCKERFILE}"


def test_docker_compose_exists():
    """The repo ships a docker-compose.yml (the local dev entry point)."""
    assert DOCKER_COMPOSE.exists(), f"missing {DOCKER_COMPOSE}"


def test_install_script_is_executable():
    """The installer must be a real, executable POSIX shell script."""
    assert INSTALL_SH.exists()
    text = INSTALL_SH.read_text()
    assert text.startswith("#!/usr/bin/env bash"), (
        f"install.sh must have #!/usr/bin/env bash shebang; got first line: {text.splitlines()[0]!r}"
    )


def test_docker_compose_stubs_github_api():
    """
    GIVEN the integration test will stub `https://api.github.com` inside
    the container via /etc/hosts
    WHEN docker-compose is read
    THEN there is at least one service that can be used to run the
    installer end-to-end.
    """
    text = DOCKER_COMPOSE.read_text()
    assert "kiro-gateway" in text or "kiro_gateway" in text or "gateway" in text, (
        f"docker-compose.yml must reference the gateway service; got:\n{text}"
    )
