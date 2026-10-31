"""Unattended runs: the charter, the runner, budgets and caps, the objective gate checks, and the digest."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime
from pathlib import Path

from tests.helpers import REPO, coord, git_project, in_terminal, install, needs_sources, revision, run, softory

sys.path.insert(0, str(REPO / "lib"))
from softory import charter as charters  # noqa: E402
from softory import containment, digest, perms  # noqa: E402
from softory.project import Project  # noqa: E402
import os  # noqa: E402
import shlex  # noqa: E402
import subprocess  # noqa: E402

from tests.test_workflow import failing, gate, start  # noqa: E402


def at_terminal(root: Path, *args: str) -> dict:
    """Run softory in a terminal, typing yes; the JSON result follows the prompt."""
    command = shlex.join([str(root / ".agents/softory/bin/softory"), *args])
    env = {k: v for k, v in os.environ.items() if k not in ("COORDINATION_SESSION", "SOFTORY_ROLE")}
    result = subprocess.run(in_terminal(command), input="yes\n", cwd=root, env=env,
                            capture_output=True, text=True, check=False)
    output = result.stdout.replace("\r", "").split("Type yes to approve: ")[-1]
    return json.loads(output[output.index("{"):])

DEFAULTS = json.loads((Path(__file__).resolve().parents[1] / "factory/governance/charter.json").read_text())
PROJECT = Project(Path("/tmp/softory-unit"))
#: A charter that is safe to run unwatched: lanes and spending caps set, and a stand-in for claude.
SAFE = {"lanes": {"frontend": ["web/**"], "backend": ["api/**"], "infra": ["infra/**"]},
        "budget": {"usd_per_run": 2, "usd_per_role_per_day": 20},
        "run": {"harnesses": {"claude": ["sh"], "codex": ["sh"]}}}


class CharterUnitTest(unittest.TestCase):
    def test_overrides_merge_and_unknown_keys_are_named(self) -> None:
        merged = charters.merge(DEFAULTS, {"budget": {"minutes_per_run": 10}, "lanes": {"frontend": ["web/**"]}})
        self.assertEqual(merged["budget"]["minutes_per_run"], 10)
        self.assertEqual(merged["budget"]["runs_per_role_per_day"], DEFAULTS["budget"]["runs_per_role_per_day"])
        self.assertEqual(charters.unknown_keys(DEFAULTS, {"budgte": 1, "lanes": {"mobile": []}}), ["budgte"])

    def test_budget_overrides_per_role(self) -> None:
        from softory.runstate import limits_for
        self.assertEqual(limits_for(DEFAULTS, "greg")["minutes_per_run"], 15)
        self.assertEqual(limits_for(DEFAULTS, "jade")["minutes_per_run"], 30)
        self.assertEqual(limits_for(DEFAULTS, "greg")["runs_per_role_per_day"], 24)
        self.assertEqual(charters.unknown_keys(DEFAULTS, {"budget": {"roles": {"quinn": {"minutes_per_run": 60}}}}), [])

    def test_escalation_switches_model(self) -> None:
        self.assertEqual(charters.model_for(DEFAULTS, "toby", False), {"harness": "codex", "model": "gpt-6-astra"})
        self.assertEqual(charters.model_for(DEFAULTS, "jade", True)["model"], "claude-opus-5-5")  # no escalation set
        cheap = charters.merge(DEFAULTS, {"models": {"gold": {"harness": "codex", "model": "gpt-6.1-sol",
                                                             "escalate": {"harness": "claude", "model": "claude-opus-5-5"}}}})
        self.assertEqual(charters.model_for(cheap, "gold", False)["model"], "gpt-6.1-sol")
        self.assertEqual(charters.model_for(cheap, "gold", True)["harness"], "claude")

    def test_claude_settings_keep_a_role_in_its_lane(self) -> None:
        charter = charters.merge(DEFAULTS, {"lanes": {"frontend": ["web/**"]}})
        allow = perms.settings_for(PROJECT, charter, "jade")["permissions"]["allow"]
        self.assertIn("Edit(./web/**)", allow)
        self.assertNotIn("Edit", allow)
        self.assertIn("Edit", perms.settings_for(PROJECT, charter, "gold")["permissions"]["allow"])  # backend paths not set
        self.assertEqual(perms.unscoped(charter), ["gold"])
        deny = perms.settings_for(PROJECT, charter, "jade")["permissions"]["deny"]
        self.assertIn("Edit(./.agents/**)", deny)

    def test_claude_settings_sandbox_bash_and_hide_credentials(self) -> None:
        settings = perms.settings_for(PROJECT, DEFAULTS, "jade")
        sandbox = settings["sandbox"]
        self.assertTrue(sandbox["enabled"] and sandbox["failIfUnavailable"])
        self.assertFalse(sandbox["allowUnsandboxedCommands"] or sandbox["autoAllowBashIfSandboxed"])
        self.assertEqual(sandbox["network"]["allowedDomains"], [])
        self.assertIn("~/.aws", sandbox["filesystem"]["denyRead"])
        self.assertIn(str(PROJECT.root.resolve() / ".coordination"), sandbox["filesystem"]["denyWrite"])
        self.assertIn(".agents/softory/bin/softory *", sandbox["excludedCommands"])
        self.assertIn("Read(~/.ssh/**)", settings["permissions"]["deny"])
        allow = settings["permissions"]["allow"]
        self.assertFalse([rule for rule in allow if rule.startswith(("Bash(git push", "Bash(git fetch"))])
        pushing = charters.merge(DEFAULTS, {"permissions": {"allow_bash": ["git push"]}})
        self.assertIn("Bash(git push *)", perms.settings_for(PROJECT, pushing, "jade")["permissions"]["allow"])

    def test_unwatched_runs_need_lanes_and_spending_caps(self) -> None:
        found = " ".join(containment.problems(DEFAULTS))
        self.assertIn("lanes paths for jade, gold", found)
        self.assertIn("usd_per_run", found)
        self.assertEqual(containment.problems(charters.merge(DEFAULTS, SAFE)), [])
        capped_low = charters.merge(DEFAULTS, {**SAFE, "budget": {"usd_per_run": 2, "usd_per_role_per_day": 20,
                                                                  "roles": {"toby": {"usd_per_run": 0}}}})
        self.assertIn("(for toby)", " ".join(containment.problems(capped_low)))

    def test_tests_run_without_credentials_or_the_internet(self) -> None:
        profile = containment.test_profile(PROJECT)
        self.assertIn(f'(subpath "{Path.home().resolve() / ".ssh"}")', profile)
        self.assertIn("(deny network-outbound)", profile)
        self.assertNotIn("(deny network-outbound)", containment.test_profile(PROJECT, network=True))
        command = containment.test_command(PROJECT, DEFAULTS, "true")
        self.assertEqual(command[-3:], ["/bin/sh", "-c", "true"])
        self.assertEqual(command[0] == containment.SANDBOX_EXEC, containment.can_sandbox_tests())
        off = charters.merge(DEFAULTS, {"verify": {"sandbox": False}})
        self.assertEqual(containment.test_command(PROJECT, off, "true"), ["/bin/sh", "-c", "true"])
        os.environ["AWS_SECRET_ACCESS_KEY"] = "x"
        self.addCleanup(os.environ.pop, "AWS_SECRET_ACCESS_KEY", None)
        self.assertNotIn("AWS_SECRET_ACCESS_KEY", containment.test_env())

    def test_claude_bash_rules_use_the_space_wildcard(self) -> None:
        allow = perms.settings_for(PROJECT, DEFAULTS, "jade")["permissions"]["allow"]
        self.assertTrue(all(rule.endswith(" *)") for rule in allow if rule.startswith("Bash(")))

    def test_usage_reads_each_harness_report(self) -> None:
        from softory import usage
        claude = json.dumps({"type": "result", "total_cost_usd": 0.1234567,
                             "usage": {"input_tokens": 10, "cache_creation_input_tokens": 5,
                                       "cache_read_input_tokens": 100, "output_tokens": 7}})
        self.assertEqual(usage.parse(claude, "claude-opus-5-5", DEFAULTS["prices"]),
                         {"input_tokens": 15, "cached_tokens": 100, "output_tokens": 7, "usd": 0.1235})
        codex = "\n".join([json.dumps({"type": "thread.started"}),
                           json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1_000_000,
                                       "cached_input_tokens": 400_000, "output_tokens": 100_000}})])
        found = usage.parse(codex, "gpt-6-astra", DEFAULTS["prices"])
        self.assertEqual((found["input_tokens"], found["cached_tokens"]), (600_000, 400_000))
        self.assertEqual(found["usd"], 6 + 0.4 + 5)
        self.assertTrue(found["usd_estimated"])
        self.assertEqual(usage.parse("plain text", "m", {}), {})

    def test_effort_follows_the_job_and_empty_flags_drop(self) -> None:
        from softory import runner, runprompt
        self.assertEqual(runprompt.job_of({"reasons": [{"why": "reviews waiting"}, {"why": "unread messages"}]}), "review")
        self.assertEqual(runprompt.job_of({"reasons": [{"why": "reviews waiting"}, {"why": "assigned work changed"}]}), "build")
        self.assertEqual(charters.effort_for(DEFAULTS, "toby", "review"), "medium")
        own = charters.merge(DEFAULTS, {"models": {"toby": {"effort": {"review": "high"}}}})
        self.assertEqual(charters.effort_for(own, "toby", "review"), "high")
        pick = {"harness": "codex", "model": "gpt-6-astra"}
        command = runner.harness_command(None, DEFAULTS, "toby", pick, "go", "high")
        self.assertIn('model_reasoning_effort="high"', command)
        self.assertNotIn("-c", runner.harness_command(None, DEFAULTS, "toby", pick, "go", ""))
        self.assertEqual(command[-1], "go")

    def test_quiet_hours_wrap_midnight(self) -> None:
        self.assertTrue(digest._quiet(datetime(2026, 1, 1, 23), [22, 8]))
        self.assertTrue(digest._quiet(datetime(2026, 1, 1, 3), [22, 8]))
        self.assertFalse(digest._quiet(datetime(2026, 1, 1, 9), [22, 8]))


@needs_sources
class UnattendedTest(unittest.TestCase):
    def setUp(self) -> None:
        self.holder, self.root = git_project({"README.md": "# app\n", "web/app.js": "1\n", "api/app.py": "1\n"})
        self.addCleanup(self.holder.cleanup)
        install(self.root)
        softory(self.root, "new", "story", "--title", "See today", "--actor", "greg")
        softory(self.root, "new", "task", "--parent", "STORY-1", "--lane", "frontend", "--title", "List", "--actor", "quinn")

    def approve(self, settings: dict) -> dict:
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps(settings))
        return at_terminal(self.root, "charter", "approve", str(path))

    def commit(self, name: str, text: str) -> str:
        (self.root / name).parent.mkdir(parents=True, exist_ok=True)
        (self.root / name).write_text(text)
        run(["git", "add", name], self.root)
        run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", name], self.root)
        return run(["git", "rev-parse", "HEAD"], self.root).stdout.strip()

    def build(self, task: str, builder: str, sha: str, review: bool = True) -> None:
        session = start(self.root, builder)["COORDINATION_SESSION"]
        coord(self.root, "--session", session, "task", "claim", task, "--agent", builder, "--if-revision", revision(self.root, task))
        coord(self.root, "evidence", "add", "--task", task, "--uri", f"commit:{sha}", "--type", "commit", "--actor", builder)
        coord(self.root, "--session", session, "task", "release", task, "--to", "review", "--actor", builder,
              "--if-revision", revision(self.root, task))
        if review:
            coord(self.root, "review", "add", "--id", f"REV-{task}-1", "--task", task, "--reviewer", "gold",
                  "--artifact", sha, "--scope", "t", "--decision", "accepted")
        softory(self.root, "end", "--session", session)

    def test_only_the_owner_approves_the_charter(self) -> None:
        path = self.root / ".git" / "charter.json"
        path.write_text(json.dumps({"verify": {"command": "true"}}))
        refused = softory(self.root, "charter", "approve", str(path), check=False)
        self.assertIn("owner_terminal_required", refused.stderr)
        approved = self.approve({"verify": {"command": "true"}})
        self.assertEqual(approved["charter"]["verify"]["command"], "true")
        self.assertTrue(coord(self.root, "decision", "show", approved["decision"])["ok"])
        shown = json.loads(softory(self.root, "charter", "show").stdout)
        self.assertEqual(shown["approved"]["decision"], approved["decision"])

    def test_gate_needs_tests_that_softory_ran_at_the_commit(self) -> None:
        self.approve({"verify": {"command": "test -f web/app.js"}, "lanes": {"frontend": ["web/**"]},
                      "git": {"base": "HEAD~1"}})
        sha = self.commit("web/list.js", "x\n")
        self.build("TASK-1", "jade", sha)
        self.assertEqual(failing(gate(self.root, "TASK-1", "jade")), {"verified"})
        coord(self.root, "evidence", "add", "--task", "TASK-1", "--uri", f"softory-verify:pass:{sha}", "--type", "test",
              "--actor", "jade")
        self.assertEqual(failing(gate(self.root, "TASK-1", "jade")), {"verified"})  # a row an agent wrote doesn't count
        result = json.loads(softory(self.root, "verify", "TASK-1", "--actor", "jade").stdout)
        self.assertTrue(result["passed"])
        self.assertTrue(gate(self.root, "TASK-1", "jade")["pass"])
        self.assertEqual(run(["git", "worktree", "list"], self.root).stdout.count("\n"), 1)  # throwaway tree removed

    def test_failing_tests_and_out_of_lane_files_fail_the_gate(self) -> None:
        self.approve({"verify": {"command": "false"}, "lanes": {"frontend": ["web/**"]}, "git": {"base": "HEAD~1"}})
        sha = self.commit("api/secret.py", "x\n")
        self.build("TASK-1", "jade", sha)
        failed = softory(self.root, "verify", "TASK-1", "--actor", "jade", check=False)
        self.assertEqual(failed.returncode, 3)
        report = gate(self.root, "TASK-1", "jade")
        self.assertEqual(failing(report), {"verified", "lane_paths"})
        lane = next(c for c in report["checks"] if c["check"] == "lane_paths")
        self.assertIn("api/secret.py", lane["detail"])

    def test_runner_starts_only_roles_with_work_and_respects_pause(self) -> None:
        plan = json.loads(softory(self.root, "run", "--dry-run").stdout)
        self.assertEqual(plan["started"], ["greg", "jade"])  # Greg owns STORY-1, Jade TASK-1; nobody else has work
        self.assertEqual(plan["skipped"]["toby"], "nothing pending")
        softory(self.root, "pause", "--role", "jade", "--reason", "upgrade")
        plan = json.loads(softory(self.root, "run", "--dry-run").stdout)
        self.assertEqual(plan["started"], ["greg"])
        self.assertIn("paused: upgrade", plan["skipped"]["jade"])
        pending = softory(self.root, "pending", "jade", check=False)
        self.assertEqual(pending.returncode, 3)
        self.assertIn("owner_terminal_required", softory(self.root, "resume", "--role", "jade", check=False).stderr)
        at_terminal(self.root, "resume", "--role", "jade")
        self.assertEqual(json.loads(softory(self.root, "run", "--dry-run").stdout)["started"], ["greg", "jade"])

    def test_an_unsafe_charter_starts_nobody(self) -> None:
        plan = json.loads(softory(self.root, "run").stdout)
        self.assertEqual(plan["started"], [])
        self.assertIn("refused", plan["skipped"]["jade"])
        self.assertIn("usd_per_run", " ".join(plan["refused"]))
        dry = json.loads(softory(self.root, "run", "--dry-run").stdout)
        self.assertEqual(dry["started"], ["greg", "jade"])  # what would start once it's safe
        self.assertTrue(dry["refused"])

    @unittest.skipUnless(containment.can_sandbox_tests(), "needs macOS sandbox-exec")
    def test_tests_cannot_write_softorys_state(self) -> None:
        forged = self.root / ".agents/softory/run/forged"
        self.approve({"verify": {"command": f"touch {forged}"}})
        sha = self.commit("web/a.js", "x\n")
        self.build("TASK-1", "jade", sha, review=False)
        result = json.loads(softory(self.root, "verify", "TASK-1", "--actor", "jade", check=False).stdout)
        self.assertEqual((result["passed"], result["sandboxed"]), (False, True))
        self.assertFalse(forged.exists())

    def test_a_run_is_logged_and_counts_against_the_budget(self) -> None:
        self.approve({"run": {"roles": ["jade"], "harnesses": {"fake": ["sh", "-c", "echo {model} > .git/ran-{role}"]}},
                      "models": {"jade": {"harness": "fake", "model": "m1", "escalate": None}},
                      "budget": {"runs_per_role_per_day": 1}})
        ran = json.loads(softory(self.root, "run-role", "jade").stdout)
        self.assertEqual((ran["exit"], ran["model"]), (0, "m1"))
        self.assertEqual((self.root / ".git/ran-jade").read_text().strip(), "m1")
        usage = json.loads(softory(self.root, "usage").stdout)
        self.assertTrue(usage["jade"]["over"])
        plan = json.loads(softory(self.root, "run", "--dry-run").stdout)
        self.assertIn("budget reached", plan["skipped"]["jade"])
        found = json.loads(softory(self.root, "digest").stdout)
        self.assertEqual([row["key"] for row in found["urgent"]], ["budget-jade"])

    def test_a_task_past_its_review_cap_stops_and_goes_to_the_owner(self) -> None:
        self.approve({"task_caps": {"review_rounds": 2, "escalate_model_after": 1}})
        sha = self.commit("web/a.js", "x\n")
        self.build("TASK-1", "jade", sha)
        coord(self.root, "review", "add", "--id", "REV-TASK-1-2", "--task", "TASK-1", "--reviewer", "gold",
              "--artifact", sha, "--scope", "t", "--decision", "changes_requested", "--required-changes", "x")
        once = json.loads(softory(self.root, "pending", "jade", "--since", "2000-01-01").stdout)
        self.assertEqual(once["escalate"], ["TASK-1"])
        coord(self.root, "review", "add", "--id", "REV-TASK-1-3", "--task", "TASK-1", "--reviewer", "gold",
              "--artifact", sha, "--scope", "t", "--decision", "changes_requested", "--required-changes", "x")
        capped = json.loads(softory(self.root, "pending", "jade", "--since", "2000-01-01", check=False).stdout)
        self.assertEqual(capped["capped"], ["TASK-1"])
        self.assertNotIn("TASK-1", json.dumps(capped["reasons"]))
        found = json.loads(softory(self.root, "digest").stdout)
        self.assertIn("cap-TASK-1", [row["key"] for row in found["digest"]])

    def test_digest_pages_a_gate_bypass_once(self) -> None:
        marker = self.root / ".git" / "pages"
        self.approve({"paging": {"command": f"echo \"$SOFTORY_TITLE\" >> {marker}", "quiet_hours": []}})
        session = start(self.root, "jade")["COORDINATION_SESSION"]
        coord(self.root, "evidence", "add", "--task", "TASK-1", "--uri", "x", "--type", "commit", "--actor", "jade")
        coord(self.root, "--session", session, "task", "claim", "TASK-1", "--agent", "jade", "--if-revision", revision(self.root, "TASK-1"))
        coord(self.root, "--session", session, "task", "release", "TASK-1", "--to", "review", "--actor", "jade",
              "--if-revision", revision(self.root, "TASK-1"))
        coord(self.root, "task", "status", "TASK-1", "done", "--actor", "jade", "--if-revision", revision(self.root, "TASK-1"))
        softory(self.root, "run", "--dry-run")  # a dry run pages nobody
        self.assertFalse(marker.exists())
        softory(self.root, "run")
        softory(self.root, "run")
        pages = marker.read_text().splitlines()
        self.assertEqual(pages.count("Softory: needs you now"), 1)

    def test_setup_lists_what_is_left(self) -> None:
        steps = json.loads(softory(self.root, "setup").stdout)
        self.assertFalse(next(s for s in steps["steps"] if s["step"] == "charter approved")["done"])
        self.assertTrue(Path(steps["schedule"]["launchd"]).is_file())

    def test_reviews_wait_for_passing_tests_and_a_batch(self) -> None:
        self.approve({"verify": {"command": "true"}, "review_batch": {"min": 1, "max_wait_minutes": 60}})
        sha = self.commit("web/b.js", "x\n")
        self.build("TASK-1", "jade", sha, review=False)
        builder = json.loads(softory(self.root, "pending", "jade", "--since", "2000-01-01", check=False).stdout)
        self.assertIn("tests not passed", json.dumps(builder["reasons"]))
        reviewers = [r for r in DEFAULTS["run"]["roles"] if r != "jade"]
        waiting = lambda: {r for r in reviewers if "reviews waiting" in json.dumps(json.loads(
            softory(self.root, "pending", r, "--since", "2000-01-01", check=False).stdout)["reasons"])}
        self.assertEqual(waiting(), set())
        softory(self.root, "verify", "TASK-1", "--actor", "jade")
        woken = waiting()
        self.assertTrue(woken)
        self.approve({"verify": {"command": "true"}, "review_batch": {"min": 3, "max_wait_minutes": 60}})
        self.assertEqual(waiting(), set())
        held = json.loads(softory(self.root, "pending", sorted(woken)[0], "--since", "2000-01-01", check=False).stdout)
        self.assertEqual(held["batching"]["ids"], ["TASK-1"])

    def test_a_run_gets_the_work_in_its_prompt_and_logs_tokens_and_effort(self) -> None:
        (self.root / ".git/report.json").write_text(json.dumps({"total_cost_usd": 0.5,
                                                                 "usage": {"input_tokens": 10, "output_tokens": 5}}))
        script = 'printf %s "$1" > .git/prompt; echo {effort} > .git/effort; cat .git/report.json'
        self.approve({"run": {"roles": ["jade"], "harnesses": {"fake": ["sh", "-c", script, "sh", "{prompt}"]}},
                      "models": {"jade": {"harness": "fake", "model": "m1", "escalate": None}}})
        ran = json.loads(softory(self.root, "run-role", "jade").stdout)
        self.assertEqual((ran["job"], ran["effort"], ran["usd"], ran["output_tokens"]), ("build", "high", 0.5, 5))
        self.assertEqual((self.root / ".git/effort").read_text().strip(), "high")
        prompt = (self.root / ".git/prompt").read_text()
        self.assertIn("TASK-1 [todo, parent STORY-1] List", prompt)
        self.assertLess(prompt.index("End with softory end"), prompt.index("Waiting for you"))
        self.assertEqual(json.loads(softory(self.root, "usage").stdout)["jade"]["usd"], 0.5)
