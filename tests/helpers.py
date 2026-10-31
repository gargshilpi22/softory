"""Shared fixtures: throwaway git projects with softory installed from local checkouts.

Set SOFTORY_SCAFFOLD_SRC and SOFTORY_TRACKER_SRC to checkouts at the pinned
commits. Without them the integration tests skip, so the unit tests still run.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SOFTORY = REPO / "bin" / "softory"
SCAFFOLD_SRC = os.environ.get("SOFTORY_SCAFFOLD_SRC")
TRACKER_SRC = os.environ.get("SOFTORY_TRACKER_SRC")
#: Optional: a checkout of the scaffold release before the pin, for the upgrade test.
PREVIOUS_SRC = os.environ.get("SOFTORY_SCAFFOLD_PREVIOUS_SRC")
PINNED = json.loads((REPO / "dependencies.json").read_text(encoding="utf-8"))["scaffold"]["version"]
COORDINATION = ".agents/agentic-project-scaffold-lite/bin/coordination"


def in_terminal(command: str) -> list[str]:
    """argv that runs a shell command under a pseudo-terminal, with BSD (macOS) or util-linux ``script``."""
    if sys.platform == "darwin":  # BSD script drops input that arrives before the child reads, so wait a moment
        return ["/bin/sh", "-c", f"(sleep 1; cat) | script -q /dev/null /bin/sh -c {shlex.quote(command)}"]
    return ["script", "-qec", command, "/dev/null"]


def run(args: list[str], cwd: Path, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    full_env = {k: v for k, v in os.environ.items() if k not in ("COORDINATION_SESSION", "SOFTORY_ROLE")}
    full_env.update(env or {})
    result = subprocess.run(args, cwd=cwd, env=full_env, capture_output=True, text=True, check=False)
    if check and result.returncode != 0:
        raise AssertionError(f"{args} failed ({result.returncode}):\n{result.stdout}\n{result.stderr}")
    return result


def git_project(files: dict[str, str] | None = None) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    """A committed git repo with the given files."""
    holder = tempfile.TemporaryDirectory(prefix="softory-test-")
    root = Path(holder.name)
    run(["git", "init", "-q"], root)
    for name, text in (files or {"README.md": "# app\n", ".gitignore": "node_modules/\n"}).items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    run(["git", "add", "-A"], root)
    run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], root)
    return holder, root


def install(root: Path, *extra: str) -> dict:
    """Install softory into ``root``. A first plain install into a project whose files
    an earlier test already installed into is copied from that result instead, since
    the installer gives the same output for the same files and that keeps the suite fast."""
    fresh = not extra and not (root / ".agents").exists() and not (root / ".coordination").exists()
    key = _files_key(root) if fresh else None
    if key in _TEMPLATES:
        template, result = _TEMPLATES[key]
        _copy_install(template, root)
        return {**result, "target": str(root)}
    result = json.loads(_install(root, *extra).stdout)
    if key is not None:
        template = Path(tempfile.mkdtemp(prefix="softory-template-", dir=_template_root()))
        _copy_install(root, template, git_dir=True)
        _TEMPLATES[key] = (template, result)
    return result


def _install(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return run([str(SOFTORY), "install", "--target", str(root), "--owner-name", "Tester",
                "--scaffold-src", SCAFFOLD_SRC or "", "--tracker-src", TRACKER_SRC or "", *extra], root)


_TEMPLATES: dict[str, tuple[Path, dict]] = {}
_TEMPLATE_ROOT: list[Path] = []


def _template_root() -> Path:
    if not _TEMPLATE_ROOT:
        _TEMPLATE_ROOT.append(Path(tempfile.mkdtemp(prefix="softory-templates-")))
        atexit.register(shutil.rmtree, _TEMPLATE_ROOT[0], True)
    return _TEMPLATE_ROOT[0]


def _files_key(root: Path) -> str:
    """The project's tracked files and their contents."""
    names = run(["git", "ls-files", "-z"], root).stdout.split("\0")
    digest = hashlib.sha256()
    for name in sorted(n for n in names if n):
        digest.update(name.encode() + b"\0" + (root / name).read_bytes() + b"\0")
    return digest.hexdigest()


def _copy_install(source: Path, target: Path, git_dir: bool = False) -> None:
    """Copy what the installer added: every untracked path, and the exclude block in .git."""
    tracked = {n.split("/")[0] for n in run(["git", "ls-files", "-z"], source).stdout.split("\0") if n} if git_dir else set()
    for entry in source.iterdir():
        if entry.name == ".git" or entry.name in tracked:
            continue
        if entry.is_dir() and not entry.is_symlink():
            shutil.copytree(entry, target / entry.name, symlinks=True)
        else:
            shutil.copy2(entry, target / entry.name, follow_symlinks=False)
    (target / ".git" / "info").mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / ".git" / "info" / "exclude", target / ".git" / "info" / "exclude")


def softory(root: Path, *args: str, env: dict[str, str] | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return run([str(root / ".agents/softory/bin/softory"), *args], root, env, check)


def coord(root: Path, *args: str, check: bool = True) -> dict:
    result = run([str(root / COORDINATION), *args], root, check=check)
    return json.loads(result.stdout or result.stderr)


def revision(root: Path, task_id: str) -> str:
    return str(coord(root, "task", "show", task_id)["data"]["revision"])


def git_status(root: Path) -> str:
    return run(["git", "status", "--porcelain", "--untracked-files=all"], root).stdout


needs_sources = unittest.skipUnless(
    SCAFFOLD_SRC and TRACKER_SRC, "set SOFTORY_SCAFFOLD_SRC and SOFTORY_TRACKER_SRC to run integration tests"
)
