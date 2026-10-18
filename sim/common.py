"""Shared helpers: SUMO location, subprocess wrapper, hashing and YAML loading."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SYNTHETIC_LABEL = "synthetic demand, uncalibrated"


def sumo_home() -> Path:
    """Return SUMO_HOME: the env var if set, else the eclipse-sumo wheel location."""
    env = os.environ.get("SUMO_HOME")
    if env and Path(env, "tools").is_dir():
        return Path(env)
    try:
        import sumo  # eclipse-sumo wheel

        return Path(sumo.__file__).resolve().parent
    except ImportError as exc:  # pragma: no cover - depends on install
        raise RuntimeError("SUMO not found: install eclipse-sumo or set SUMO_HOME") from exc


def sumo_bin(name: str) -> str:
    """Path to a SUMO binary (sumo, netconvert, duarouter, ...)."""
    candidate = sumo_home() / "bin" / name
    if candidate.exists():
        return str(candidate)
    found = shutil.which(name)
    if not found:
        raise RuntimeError(f"SUMO binary {name!r} not found")
    return found


def sumo_tool(relpath: str) -> Path:
    """Path to a script under $SUMO_HOME/tools."""
    path = sumo_home() / "tools" / relpath
    if not path.exists():
        raise RuntimeError(f"SUMO tool {relpath!r} not found under {path.parent}")
    return path


def sumo_env() -> dict[str, str]:
    env = dict(os.environ)
    env["SUMO_HOME"] = str(sumo_home())
    return env


def sumo_version() -> str:
    out = subprocess.run(
        [sumo_bin("sumo"), "--version"], capture_output=True, text=True, env=sumo_env()
    ).stdout
    for line in out.splitlines():
        if line.startswith("Eclipse SUMO"):
            return line.strip()
    return "unknown"


def run_cmd(cmd: list[str], log: Path | None = None) -> None:
    """Run a command from the repo root, output to `log` if given; raise on failure.

    Paths inside the repo are passed relative to the root so that tool headers written into
    outputs (SUMO records its options) do not depend on where the repo is checked out.
    """
    prefix = f"{REPO_ROOT}/"
    cmd = [str(c).replace(prefix, "") for c in cmd]
    cwd = REPO_ROOT
    printable = " ".join(cmd)
    if log is not None:
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("a") as fh:
            fh.write(f"$ {printable}\n")
            fh.flush()
            proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, cwd=cwd, env=sumo_env())
    else:
        proc = subprocess.run(cmd, cwd=cwd, env=sumo_env())
    if proc.returncode != 0:
        where = f" (see {log})" if log else ""
        raise RuntimeError(f"command failed with code {proc.returncode}{where}: {printable}")


def python_tool_cmd(relpath: str, *args: str) -> list[str]:
    """Command line for a SUMO python tool, run with the current interpreter."""
    return [sys.executable, str(sumo_tool(relpath)), *args]


def file_hash(path: Path, length: int = 16) -> str:
    """Streaming sha256 of a file, truncated to `length` hex chars."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:length]


def content_hash(path: Path, length: int = 16) -> str:
    """sha256 of an XML file ignoring comments (SUMO headers carry timestamps and paths)."""
    digest = hashlib.sha256()
    in_comment = False
    with Path(path).open("rb") as fh:
        for line in fh:
            stripped = line.strip()
            if not in_comment and stripped.startswith(b"<!--"):
                in_comment = True
            if in_comment:
                if stripped.endswith(b"-->"):
                    in_comment = False
                continue
            digest.update(line)
    return digest.hexdigest()[:length]


def config_hash(obj: Any, length: int = 16) -> str:
    blob = json.dumps(obj, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:length]


def load_yaml(path: Path) -> dict[str, Any]:
    with Path(path).open() as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a mapping at the top level")
    return data


def rel(path: Path) -> str:
    """Path relative to the repo root when possible (for logs and metadata)."""
    try:
        return str(Path(path).resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)
