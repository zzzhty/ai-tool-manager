#!/usr/bin/env python3
"""Resolve paths owned by the oh-my-harness manager installation."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping


PRODUCT_NAME = "oh-my-harness"
MANAGER_HOME_ENV = "OH_MY_HARNESS_HOME"
MANAGER_ROOT_ENV = "OH_MY_HARNESS_ROOT"
MANAGER_PYTHON_ENV = "OH_MY_HARNESS_PYTHON"
MANAGER_TOOLING_PYTHON_ENV = "OH_MY_HARNESS_TOOLING_PYTHON"


def expand_path(raw: str | Path) -> Path:
    return Path(os.path.expandvars(str(raw))).expanduser()


def lexical_absolute(raw: str | Path) -> Path:
    """Return an absolute, normalized path without resolving links or aliases."""

    return Path(os.path.abspath(expand_path(raw)))


def manager_home(
    raw: str | Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    user_home: Path | None = None,
) -> Path:
    environment = os.environ if environ is None else environ
    selected = raw if raw is not None else environment.get(MANAGER_HOME_ENV)
    if selected is not None:
        if not str(selected).strip():
            raise ValueError(f"{MANAGER_HOME_ENV} must not be empty")
        resolved = expand_path(selected)
        if not resolved.is_absolute():
            raise ValueError(
                f"{MANAGER_HOME_ENV} must be an absolute path: {selected!r}"
            )
        return lexical_absolute(resolved)
    return lexical_absolute((user_home or Path.home()) / ".oh-my-harness")


def repo_path(home: Path) -> Path:
    return home / "repo"


def venv_path(home: Path) -> Path:
    return home / "venv"


def bin_path(home: Path) -> Path:
    return home / "bin"


def state_path(home: Path) -> Path:
    return home / "state"


def venv_python(path: Path) -> Path:
    if sys.platform == "win32":
        return path / "Scripts" / "python.exe"
    return path / "bin" / "python"
