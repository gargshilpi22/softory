"""Objective checks for the gate: the project's tests pass at the commit, and the diff stays in its lane.

``softory verify <ID>`` runs the charter's ``verify.command`` in a clean
worktree at the task's latest commit and records the result in a local
ledger. With a command set, the gate's ``verified`` check needs a passing
ledger entry for that commit, so "tests pass" is something softory saw,
not something an agent wrote. ``lane_paths`` fails when the commit's diff
touches paths outside the task's lane, unless Quinn accepted it as cross-lane.
Agents wrote the tests, so they run in ``containment``'s sandbox on macOS.
"""

from __future__ import annotations

import fnmatch
import json
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import containment
from .coordination import Coordination
from .errors import SoftoryError
from .gitlocal import git
from .project import Project
from .units import CODE_EVIDENCE, lane_of, tags_of, unit_of

CODE_UNITS = ("task", "bug")
_SHA = re.compile(r"\b([0-9a-f]{7,40})\b")
TAIL_LINES = 40


def ledger_path(project: Project) -> Path:
    return project.bundle / "run" / "verified.json"


def ledger(project: Project) -> dict[str, Any]:
    try:
        return json.loads(ledger_path(project).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def commit_of(root: Path, task: dict[str, Any]) -> str | None:
    """The full hash of the newest code evidence that names a commit this repository has."""
    for row in reversed(task.get("evidence") or []):
        if str(row.get("evidence_type", "")).lower() not in CODE_EVIDENCE:
            continue
        for candidate in reversed(_SHA.findall(str(row.get("uri", "")).lower())):
            found = git(root, "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}")
            if found.returncode == 0:
                return found.stdout.strip()
    return None


def run(project: Project, coord: Coordination, charter: dict[str, Any], task_id: str, actor: str,
        commit: str | None = None) -> dict[str, Any]:
    """Run the verify command at the task's commit in a throwaway worktree, and record what happened."""
    command = charter["verify"]["command"]
    if not command:
        raise SoftoryError("The charter sets no verify.command; the owner adds one with softory charter approve",
                           "configuration_error")
    task = coord.task(task_id)
    sha = commit or commit_of(project.root, task)
    if sha:
        resolved = git(project.root, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}")
        sha = resolved.stdout.strip() if resolved.returncode == 0 else None
    if not sha:
        raise SoftoryError(f"{task_id} has no commit evidence this repository knows; add one or pass --commit",
                           "not_found")
    place = Path(tempfile.mkdtemp(prefix="softory-verify-"))
    tree = place / "tree"
    added = git(project.root, "worktree", "add", "--detach", "--quiet", str(tree), sha)
    if added.returncode != 0:
        shutil.rmtree(place, ignore_errors=True)
        raise SoftoryError(f"git worktree add failed: {added.stderr.strip()[:300]}", "git_error")
    try:
        for shared in charter["verify"].get("share") or []:
            source = project.root / shared
            if source.exists() and not (tree / shared).exists():
                (tree / shared).parent.mkdir(parents=True, exist_ok=True)
                (tree / shared).symlink_to(source)
        started = datetime.now(timezone.utc)
        try:
            done = subprocess.run(containment.test_command(project, charter, command),  # noqa: S603 - owner's command
                                  cwd=tree, capture_output=True, text=True, check=False, env=containment.test_env(),
                                  timeout=float(charter["verify"]["timeout_minutes"]) * 60)
            code, output = done.returncode, done.stdout + done.stderr
        except subprocess.TimeoutExpired as error:
            code, output = 124, f"{error.stdout or ''}{error.stderr or ''}\n(timed out)"
    finally:
        git(project.root, "worktree", "remove", "--force", str(tree))
        shutil.rmtree(place, ignore_errors=True)
    passed = code == 0
    tail = "\n".join(str(output).splitlines()[-TAIL_LINES:])
    log = project.bundle / "run" / "verify" / f"{task_id}-{sha[:12]}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(str(output)[-200_000:], encoding="utf-8")
    sandboxed = containment.test_command(project, charter, command)[0] == containment.SANDBOX_EXEC
    entry = {"task": task_id, "passed": passed, "exit": code, "command": command, "sandboxed": sandboxed, "by": actor,
             "at": started.isoformat(timespec="seconds"),
             "seconds": round((datetime.now(timezone.utc) - started).total_seconds(), 1)}
    entries = ledger(project)
    entries[sha] = entry
    ledger_path(project).parent.mkdir(parents=True, exist_ok=True)
    ledger_path(project).write_text(json.dumps(entries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    coord.run("evidence", "add", "--task", task_id, "--uri", f"softory-verify:{'pass' if passed else 'fail'}:{sha}",
              "--type", "test", "--actor", actor)
    return {"task": task_id, "commit": sha, "passed": passed, "exit": code, "sandboxed": sandboxed, "log": str(log),
            "tail": tail}


def changed_files(root: Path, base: str, sha: str) -> list[str] | None:
    """Files the commit changes since it left ``base``, or None if git can't tell."""
    found = git(root, "diff", "--name-only", f"{base}...{sha}")
    if found.returncode != 0:
        return None
    return [line for line in found.stdout.splitlines() if line]


def tests_state(project: Project, charter: dict[str, Any], task: dict[str, Any], gates: dict[str, Any]) -> str:
    """'passed', 'failed', or 'not run' at the unit's commit; 'n/a' when the charter has no tests or it isn't code."""
    if not charter["verify"]["command"] or unit_of(task, gates) not in CODE_UNITS:
        return "n/a"
    entry = ledger(project).get(commit_of(project.root, task) or "")
    if not entry:
        return "not run"
    return "passed" if entry["passed"] else "failed"


def checks(project: Project, charter: dict[str, Any], task: dict[str, Any], unit: str | None,
           accepting: set[str]) -> list[dict[str, Any]]:
    """The gate's objective checks for a code unit. None apply until the charter configures them."""
    if unit not in CODE_UNITS:
        return []
    result = []
    command = charter["verify"]["command"]
    globs = (charter.get("lanes") or {}).get(lane_of(task) or "", [])
    if not command and not globs:
        return []
    sha = commit_of(project.root, task)
    if command:
        entry = ledger(project).get(sha or "")
        if not sha:
            result.append(_check("verified", False, "no commit evidence with a hash this repository has"))
        elif not entry:
            result.append(_check("verified", False, f"tests not run at {sha[:12]}: run softory verify {task['id']}"))
        else:
            result.append(_check("verified", entry["passed"],
                                 f"`{entry['command']}` {'passed' if entry['passed'] else 'failed'} at {sha[:12]} "
                                 f"({entry['at']})"))
    if globs:
        result.append(_lane_check(project, charter, task, sha, globs, accepting))
    return result


def _lane_check(project: Project, charter: dict[str, Any], task: dict[str, Any], sha: str | None,
                globs: list[str], accepting: set[str]) -> dict[str, Any]:
    if not sha:
        return _check("lane_paths", False, "no commit evidence to compare with the lane")
    files = changed_files(project.root, charter["git"]["base"], sha)
    if files is None:
        return _check("lane_paths", False, f"git can't diff {sha[:12]} against {charter['git']['base']}")
    allowed = [*globs, *(charter.get("shared_paths") or [])]
    outside = [f for f in files if not any(fnmatch.fnmatch(f, g) for g in allowed)]
    if not outside:
        return _check("lane_paths", True, f"{len(files)} changed file(s), all in lane:{lane_of(task)}")
    quinn = any((r.get("reviewer_id") or r.get("reviewer")) == "quinn" and r.get("decision") in accepting
                for r in task.get("reviews") or [])
    if "cross-lane" in tags_of(task) and quinn:
        return _check("lane_paths", True, f"cross-lane, accepted by quinn: {', '.join(outside[:5])}")
    return _check("lane_paths", False, f"outside lane:{lane_of(task)}: {', '.join(outside[:5])}"
                  + (f" and {len(outside) - 5} more" if len(outside) > 5 else "")
                  + ". Split the task, or tag it cross-lane and get Quinn's accepted review")


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"check": name, "pass": bool(passed), "detail": detail}
