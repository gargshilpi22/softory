"""Keep unattended runs contained: secrets stay unread, nothing leaves the Mac, and runs refuse unsafe charters.

Claude Code roles get its sandbox in their settings file: Bash has no
network, can't read the owner's credentials, and can't write softory's
state. The softory and coordination CLIs run outside that sandbox, since
they write the database and are hash-checked. ``softory verify`` runs the
project's tests, which agents wrote, under macOS ``sandbox-exec`` with the
same secret paths denied and no network beyond localhost. ``problems`` is
what ``softory run`` checks before it starts anything.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any

from .charter import model_for
from .project import Project
from .runstate import limits_for

#: Home-relative paths that hold credentials. No agent tool or test reads them.
SECRETS = [".aws", ".ssh", ".gnupg", ".midway", ".config/gh", ".config/gcloud", ".azure", ".kube", ".docker",
           ".netrc", ".git-credentials", ".npmrc", ".pypirc", ".claude/.credentials.json", "Library/Keychains"]
#: Home-relative paths that run code or hold settings later. Tests never write them.
STARTUP = [".zshrc", ".zprofile", ".zshenv", ".zlogin", ".bashrc", ".bash_profile", ".profile", ".gitconfig",
           ".config/git", ".claude", ".claude.json", "Library/LaunchAgents"]
#: Project-relative paths that hold softory's rules and state, or that git runs.
STATE = [".agents", ".coordination", ".git/hooks", ".git/config", ".git/info"]
SANDBOX_EXEC = "/usr/bin/sandbox-exec"


def _home() -> Path:
    return Path(os.path.expanduser("~")).resolve()


# ---- Claude Code ------------------------------------------------------------------------------

def claude_settings(project: Project, unsandboxed: list[str]) -> dict[str, Any]:
    """The sandbox block and deny rules added to every Claude Code role's settings.

    ``unsandboxed`` are the command prefixes that run outside the sandbox: softory's own CLIs.
    """
    root = project.root.resolve()
    return {
        "deny": [f"{tool}(~/{path}{glob})" for path in SECRETS for tool in ("Read", "Edit") for glob in ("", "/**")],
        "sandbox": {
            "enabled": True,
            "failIfUnavailable": True,
            "autoAllowBashIfSandboxed": False,  # the allow list still decides which commands run
            "allowUnsandboxedCommands": False,
            "excludedCommands": [f"{command} *" for command in unsandboxed],
            "filesystem": {"denyRead": [f"~/{path}" for path in SECRETS],
                           "denyWrite": [str(root / path) for path in STATE]},
            "network": {"allowedDomains": []},
        },
    }


# ---- softory verify ---------------------------------------------------------------------------

def can_sandbox_tests() -> bool:
    return sys.platform == "darwin" and Path(SANDBOX_EXEC).is_file()


def _quote(path: Path) -> str:
    return '"' + str(path).replace("\\", "\\\\").replace('"', '\\"') + '"'


def test_profile(project: Project, network: bool = False) -> str:
    """A sandbox-exec profile: everything allowed except secrets, startup files, softory's state, and the internet."""
    home, root = _home(), project.root.resolve()
    secret = " ".join(f"(subpath {_quote(home / path)})" for path in SECRETS)
    startup = " ".join(f"(subpath {_quote(home / path)})" for path in STARTUP)
    state = " ".join(f"(subpath {_quote(root / path)})" for path in STATE)
    lines = ["(version 1)", "(allow default)",
             f"(deny file-read* file-write* {secret})",
             f"(deny file-write* {startup} {state})"]
    if not network:
        lines += ["(deny network-outbound)",
                  '(allow network-outbound (remote ip "localhost:*") (remote unix-socket))']
    return "\n".join(lines) + "\n"


def test_command(project: Project, charter: dict[str, Any], command: str) -> list[str]:
    """The argv that runs the owner's verify command: sandboxed where it can be, unless the owner turned it off."""
    shell = ["/bin/sh", "-c", command]
    settings = charter["verify"]
    if not settings.get("sandbox", True) or not can_sandbox_tests():
        return shell
    return [SANDBOX_EXEC, "-p", test_profile(project, bool(settings.get("network"))), *shell]


def test_env() -> dict[str, str]:
    """The environment for tests: no session, and no cloud credentials passed by variable."""
    drop = ("COORDINATION_SESSION", "SOFTORY_ROLE")
    return {k: v for k, v in os.environ.items()
            if k not in drop and not k.startswith(("AWS_", "AZURE_", "GOOGLE_", "GH_", "GITHUB_"))}


# ---- the runner's check -----------------------------------------------------------------------

def problems(charter: dict[str, Any]) -> list[str]:
    """Why the charter isn't safe to run without the owner watching. Empty means it is."""
    from . import perms  # perms imports this module

    found = []
    claude = [r for r in charter["run"]["roles"] if model_for(charter, r, False)["harness"] == "claude"]
    binary = (charter["run"]["harnesses"].get("claude") or ["claude"])[0]
    if claude and not shutil.which(binary):
        found.append("claude isn't installed on this Mac")
    unscoped = [r for r in perms.unscoped(charter) if r in claude]
    if unscoped:
        found.append(f"set lanes paths for {', '.join(unscoped)}, so they edit only their own lane")
    for role in ["", *charter["run"]["roles"]]:
        limits = limits_for(charter, role)
        if float(limits.get("usd_per_run") or 0) <= 0 or float(limits.get("usd_per_role_per_day") or 0) <= 0:
            found.append("set budget.usd_per_run and budget.usd_per_role_per_day above 0, so spending has a cap"
                         + (f" (for {role})" if role else ""))
            break
    verify = charter["verify"]
    if verify.get("command") and verify.get("sandbox", True) and not can_sandbox_tests():
        found.append("verify.command can't be sandboxed here (needs macOS sandbox-exec); "
                     "set verify.sandbox to false only if you accept tests running unsandboxed")
    return found
