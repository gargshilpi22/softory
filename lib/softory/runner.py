"""The runner: wake each role when it has work, inside the owner's budget.

``softory run`` is one tick, meant for launchd or cron every few minutes. For
each role in the charter it skips the role if it is paused, already running,
over today's budget, or has nothing pending (no model call), and otherwise
starts ``softory run-role <role>`` in the background. It starts nobody while
``containment.problems`` finds the charter unsafe to run unwatched. That wrapper picks the
model, runs the harness with a time limit, and logs the run, which is what
the budget counts. Nothing here edits the database.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
from typing import Any

from . import charter as charters
from . import containment, digest, perms, runprompt, usage, watch
from .runstate import budget, is_paused, limits_for, now, state_dir
from .coordination import Coordination
from .errors import SoftoryError
from .project import Project


# ---- one tick ---------------------------------------------------------------------------------

def tick(project: Project, coord: Coordination, dry_run: bool = False) -> dict[str, Any]:
    charter = charters.load(project)
    report: dict[str, Any] = {"at": now().isoformat(timespec="seconds"), "started": [], "skipped": {}}
    if not dry_run:
        report["paged"] = digest.page_due(project, coord, charter)
    unsafe = containment.problems(charter)
    if unsafe:
        report["refused"] = unsafe
    for role in charter["run"]["roles"]:
        why = is_paused(project, role)
        if why:
            report["skipped"][role] = f"paused: {why}"
            continue
        if running(project, role):
            report["skipped"][role] = "already running"
            continue
        use = budget(project, charter, role)
        if use["over"]:
            report["skipped"][role] = f"budget reached today ({use['runs']} runs, {use['minutes']} min)"
            continue
        wanted = watch.pending(project, coord, role)
        if not wanted["pending"]:
            report["skipped"][role] = "nothing pending" if not wanted["running"] else "a session is active"
            continue
        if unsafe and not dry_run:
            report["skipped"][role] = "refused: the charter isn't safe to run unwatched; see refused"
            continue
        if not dry_run:
            spawn(project, role)
        report["started"].append(role)
    return report


def running(project: Project, role: str) -> bool:
    pid_file = state_dir(project) / f"{role}.pid"
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        pid_file.unlink(missing_ok=True)
        return False


def spawn(project: Project, role: str) -> None:
    logs = state_dir(project) / "logs"
    logs.mkdir(exist_ok=True)
    out = (logs / f"{role}-{now().strftime('%Y%m%dT%H%M%SZ')}.log").open("w", encoding="utf-8")
    subprocess.Popen([sys.executable, str(project.bundle / "bin" / "softory"), "run-role", role],  # noqa: S603
                     cwd=project.root, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                     start_new_session=True, env=_clean_env())


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in ("COORDINATION_SESSION", "SOFTORY_ROLE")}


# ---- one role's run ---------------------------------------------------------------------------

def run_role(project: Project, coord: Coordination, role: str) -> dict[str, Any]:
    """Run one role once: build a short prompt from what is pending, run its harness, and log the run."""
    charter = charters.load(project)
    wanted = watch.pending(project, coord, role)
    if not wanted["pending"]:
        return {"role": role, "ran": False, "why": "nothing pending"}
    escalated = bool(wanted.get("escalate"))
    pick = charters.model_for(charter, role, escalated)
    job = runprompt.job_of(wanted)
    effort = charters.effort_for(charter, role, job)
    limits = limits_for(charter, role)
    text = runprompt.build(project, coord, charter, role, pick, wanted, job)
    command = harness_command(project, charter, role, pick, text, effort, limits.get("usd_per_run") or 0)
    pid_file = state_dir(project) / f"{role}.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    started = now()
    logs = state_dir(project) / "logs"
    logs.mkdir(exist_ok=True)
    out_path = logs / f"{role}-{started.strftime('%Y%m%dT%H%M%SZ')}.out"
    try:
        with out_path.open("w", encoding="utf-8") as out:
            child = subprocess.Popen(command, cwd=project.root, env=_clean_env(), start_new_session=True,  # noqa: S603
                                     stdout=out, stdin=subprocess.DEVNULL)
            try:
                code = child.wait(timeout=float(limits["minutes_per_run"]) * 60)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                code = 124
    except FileNotFoundError as error:
        code = 127
        print(f"softory: {error}", file=sys.stderr)
    finally:
        pid_file.unlink(missing_ok=True)
    spent = usage.parse(out_path.read_text(encoding="utf-8", errors="replace") if out_path.is_file() else "",
                        pick["model"], charter.get("prices") or {})
    row = {"role": role, "started": started.isoformat(timespec="seconds"), "harness": pick["harness"],
           "model": pick["model"], "escalated": escalated, "job": job, "effort": effort, "exit": code,
           "minutes": round((now() - started).total_seconds() / 60, 2), **spent,
           "prompt_chars": len(text), "reasons": [r["why"] for r in wanted["reasons"]]}
    with (state_dir(project) / "runs.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(row) + "\n")
    return {"ran": True, **row}


def harness_command(project: Project, charter: dict[str, Any], role: str, pick: dict[str, str],
                    text: str, effort: str = "", usd_per_run: float = 0) -> list[str]:
    """The harness's template with values filled in. A flag whose value comes out empty is left out."""
    template = charter["run"]["harnesses"].get(pick["harness"])
    if not template:
        raise SoftoryError(f"run.harnesses has no command for {pick['harness']}", "configuration_error")
    settings = perms.write_settings(project, charter, role) if pick["harness"] == "claude" else ""
    values = {"prompt": text, "model": pick["model"], "settings": str(settings), "role": role, "effort": effort,
              "usd_per_run": f"{float(usd_per_run):g}" if float(usd_per_run or 0) > 0 else ""}
    command: list[str] = []
    for part in template:
        filled = part.format(**values)
        empty = "{" in part and all(not values[k] for k in values if "{" + k + "}" in part)
        if empty:
            if command and command[-1].startswith("-"):
                command.pop()  # the flag that named the empty value
            continue
        command.append(filled)
    return command


def schedule(project: Project, minutes: int = 5) -> dict[str, Any]:
    """A launchd job and a cron line that run one tick every few minutes. The owner installs one."""
    label = f"dev.softory.{project.root.name.lower()}"
    binary = project.bundle / "bin" / "softory"
    log = state_dir(project) / "runner.log"
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key><array><string>{binary}</string><string>run</string></array>
  <key>WorkingDirectory</key><string>{project.root}</string>
  <key>StartInterval</key><integer>{minutes * 60}</integer>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>{os.environ.get('PATH', '/usr/bin:/bin')}</string></dict>
</dict></plist>
"""
    path = state_dir(project) / f"{label}.plist"
    path.write_text(plist, encoding="utf-8")
    return {
        "launchd": str(path),
        "install_launchd": f"cp {path} ~/Library/LaunchAgents/ && launchctl load ~/Library/LaunchAgents/{label}.plist",
        "cron": f"*/{minutes} * * * * cd {project.root} && {binary} run >> {log} 2>&1",
    }
