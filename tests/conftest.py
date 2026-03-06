"""Pytest collection helpers for optional test dependencies."""

from __future__ import annotations

import importlib.util

collect_ignore: list[str] = []

_OPTIONAL_MATRIX_MODULES = ("nio", "mistune", "nh3")

if any(importlib.util.find_spec(name) is None for name in _OPTIONAL_MATRIX_MODULES):
    collect_ignore.append("test_matrix_channel.py")
