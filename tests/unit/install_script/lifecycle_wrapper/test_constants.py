# -*- coding: utf-8 -*-

"""
T-4.1: Refactor pass — assert the centralized constants are wired
into both the install lib and the wrapper.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
LIB = REPO_ROOT / "scripts" / "lib" / "install-common.sh"
WRAPPER = REPO_ROOT / "scripts" / "kiro-gateway"


def test_lib_exposes_tunables():
    """
    GIVEN the install lib has been refactored to expose named constants
    WHEN the lib file is read
    THEN it defines MIN_DISK_MB, MIN_DISK_KIB, HEALTH_PROBE_TIMEOUT_S,
    UPDATE_HEALTH_POLL_TIMEOUT_S, HEALTH_PROBE_INTERVAL_S.
    """
    text = LIB.read_text()
    for name in (
        "MIN_DISK_MB=200",
        "MIN_DISK_KIB=",
        "HEALTH_PROBE_TIMEOUT_S=5",
        "UPDATE_HEALTH_POLL_TIMEOUT_S=10",
        "HEALTH_PROBE_INTERVAL_S=1",
    ):
        assert name in text, f"expected {name!r} in lib; missing"


def test_lib_preflight_disk_uses_constant():
    """GIVEN the lib's preflight_disk function
    THEN it references MIN_DISK_KIB and MIN_DISK_MB (not literal 200)."""
    text = LIB.read_text()
    # Find the function body and assert it uses the constant.
    assert "MIN_DISK_KIB" in text
    assert "MIN_DISK_MB" in text
    # The literal 200 inside preflight_disk should be gone.
    # Allow it elsewhere (e.g. magic numbers in error messages pre-refactor)
    # but the function itself should reference the constant.
    fn_match = re.search(r"preflight_disk\(\)\s*\{(.*?)\n\}", text, re.DOTALL)
    assert fn_match, "preflight_disk() not found in lib"
    body = fn_match.group(1)
    assert "MIN_DISK_KIB" in body, "preflight_disk should use MIN_DISK_KIB"


def test_wrapper_uses_update_constants():
    """GIVEN the wrapper's update health-poll loop
    THEN it uses UPDATE_HEALTH_POLL_TIMEOUT_S and HEALTH_PROBE_INTERVAL_S."""
    text = WRAPPER.read_text()
    assert "UPDATE_HEALTH_POLL_TIMEOUT_S" in text
    assert "HEALTH_PROBE_INTERVAL_S" in text
    assert "HEALTH_PROBE_TIMEOUT_S" in text
