"""``softory setup``: the owner's one sitting, as a checklist softory checks."""

from __future__ import annotations

import shutil
from typing import Any

from . import charter as charters
from . import containment, perms, runner, verify
from .project import Project


def checklist(project: Project) -> dict[str, Any]:
    charter = charters.load(project)
    steps = []

    def step(name: str, done: bool, how: str) -> None:
        steps.append({"step": name, "done": bool(done), "how": "" if done else how})

    step("charter approved", charter.get("approved"),
         "Write your overrides to a file (start from `softory charter show`), then run "
         "`softory charter approve <file>` in a terminal.")
    step("vision written", charter.get("vision"), "Set `vision` in the charter: what Greg may plan without asking you.")
    step("tests command", charter["verify"]["command"],
         "Set `verify.command` (for example `npm test` or `pytest -q`), so the gate checks tests at each commit.")
    base = charter["git"]["base"]
    step("base branch", verify.git(project.root, "rev-parse", "--verify", "--quiet", base).returncode == 0,
         f"Set `git.base` to the branch work merges into; `{base}` doesn't exist here.")
    unscoped = perms.unscoped(charter)
    step("lane paths", not unscoped,
         f"Set `lanes` paths for {', '.join(unscoped)}, so Claude Code roles edit only their own lane.")
    limits = charter["budget"]
    step("spending caps", float(limits.get("usd_per_run") or 0) > 0 and float(limits.get("usd_per_role_per_day") or 0) > 0,
         "Set `budget.usd_per_run` and `budget.usd_per_role_per_day` above 0. softory run refuses to start without them.")
    unsafe = containment.problems(charter)
    step("safe to run unwatched", not unsafe, "; ".join(unsafe))
    step("paging", charter["paging"].get("command"),
         "Set `paging.command`, a shell command that reads $SOFTORY_TITLE and $SOFTORY_MESSAGE, for example "
         "`osascript -e \"display notification \\\"$SOFTORY_MESSAGE\\\" with title \\\"$SOFTORY_TITLE\\\"\"`, "
         "or a curl to a push service. Then test it with `softory digest --send`.")
    harnesses = {charters.model_for(charter, role, False)["harness"] for role in charter["run"]["roles"]}
    for name in sorted(harnesses):
        binary = charter["run"]["harnesses"][name][0]
        step(f"{name} installed", shutil.which(binary), f"Install `{binary}` and sign in, on this Mac.")
    step("branch protection", False,
         "Manual: protect the base branch on GitHub and require CI. softory can't check this from here.")
    plan = runner.schedule(project)
    step("schedule loaded", False, f"Manual, last: {plan['install_launchd']}")
    open_steps = [s for s in steps if not s["done"]]
    return {"done": len(steps) - len(open_steps), "of": len(steps), "steps": steps, "schedule": plan,
            "next": open_steps[0]["how"] if open_steps else "All set."}
