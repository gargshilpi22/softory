"""Per-role permissions for unattended runs.

Claude Code gets a settings file per role: edits only in the role's own
paths (its lane, or its docs folder), the coordination and git commands every
role needs, the owner's extra commands, and nothing else. In ``-p`` mode a
tool that isn't allowed is refused, so a role can't wander. Codex has no path
rules; it runs in its workspace-write sandbox, and the gate's ``lane_paths``
check catches a diff outside the lane for either harness. Claude Code's own
sandbox and the secret paths come from ``containment``. Roles don't push or
fetch by default; the owner adds ``git push`` to ``permissions.allow_bash``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import containment
from .project import Project
from .runstate import state_dir

#: Paths each role writes besides lane code (boundaries.md, "Creates and edits").
ROLE_DOCS = {
    "greg": ["docs/product/**"],
    "darwin": ["docs/design/**"],
    "quinn": ["docs/adr/**", "docs/**"],
    "toby": ["docs/security/**"],
}
ROLE_LANES = {"jade": ["frontend"], "gold": ["backend", "infra"]}
SOFTORY_BASH = [
    ".agents/softory/bin/softory", ".agents/agentic-project-scaffold-lite/bin/coordination",
    "eval \"$(.agents/softory/bin/softory start",
]
COMMON_BASH = [
    *SOFTORY_BASH, "git status", "git diff", "git log", "git show", "git add",
    "git commit", "git switch", "git checkout -b", "git branch", "git rev-parse",
]
NEVER_EDIT = [".agents/**", ".coordination/**", ".claude/**", ".git/**", "AGENTS.md", "CLAUDE.md"]


def role_paths(charter: dict[str, Any], role: str) -> list[str] | None:
    """The paths a role may edit, or None when its lane paths aren't set (edits anywhere but softory's)."""
    lanes = charter.get("lanes") or {}
    paths = list(ROLE_DOCS.get(role, []))
    for lane in ROLE_LANES.get(role, []):
        globs = lanes.get(lane) or []
        if not globs:
            return None
        paths += globs
    return paths


def settings_for(project: Project, charter: dict[str, Any], role: str) -> dict[str, Any]:
    paths = role_paths(charter, role)
    # Claude Code matches path rules only as Edit(...), which covers Write too.
    edit = ["Edit", "Write"] if paths is None else [f"Edit(./{glob})" for glob in paths]
    extra = charter.get("permissions") or {}
    bash = [*COMMON_BASH, *([charter["verify"]["command"]] if charter["verify"].get("command") else []),
            *(extra.get("allow_bash") or [])]
    allow = ["Read", "Grep", "Glob", "TodoWrite", *edit, *(f"Bash({command} *)" for command in bash)]
    deny = [*(f"Edit(./{path})" for path in NEVER_EDIT), "Read(./.env*)",
            *(f"Bash({command} *)" for command in extra.get("deny_bash") or [])]
    contained = containment.claude_settings(project, SOFTORY_BASH)
    return {"permissions": {"defaultMode": "default", "allow": allow, "deny": [*deny, *contained["deny"]]},
            "sandbox": contained["sandbox"]}


def write_settings(project: Project, charter: dict[str, Any], role: str) -> Path:
    folder = state_dir(project) / "settings"
    folder.mkdir(exist_ok=True)
    path = folder / f"{role}.json"
    path.write_text(json.dumps(settings_for(project, charter, role), indent=2) + "\n", encoding="utf-8")
    return path


def unscoped(charter: dict[str, Any]) -> list[str]:
    """Roles that would edit anywhere because their lane paths aren't in the charter."""
    return [role for role in ROLE_LANES if role in charter["run"]["roles"] and role_paths(charter, role) is None]
