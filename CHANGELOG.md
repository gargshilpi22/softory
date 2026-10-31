# Changelog

## [Unreleased]

Safe to leave running. Unattended Claude Code runs can no longer read your credentials, reach the internet, or run without a spending cap.

- **Claude Code roles run in Claude Code's sandbox.** Each role's settings turn it on with no way out (`allowUnsandboxedCommands: false`): Bash has no network, and neither tools nor Bash can read credentials such as `~/.aws`, `~/.ssh`, and `~/.midway`. Bash can't write softory's state (`.agents`, `.coordination`, `.git/hooks`, `.git/config`). The softory and coordination CLIs run outside the sandbox, since they write the database. The run refuses to start if the sandbox is unavailable.
- **Roles no longer push or fetch by default.** Nothing in softory's workflow asked them to, and it was the one way out of the machine. Add `git push` to `permissions.allow_bash` to bring it back.
- **`softory verify` runs tests in a macOS sandbox.** Agents write the tests, so they now run under `sandbox-exec` with credentials unreadable, startup files (`~/.zshrc`, `~/Library/LaunchAgents`, ...) and softory's state unwritable, no internet beyond localhost, and no `AWS_*` and similar variables. `verify.network` and `verify.sandbox` loosen it. The ledger records whether a run was sandboxed.
- **`softory run` starts nobody while the charter is unsafe to leave alone**: lane paths missing for a Claude Code role, no dollar caps (`budget.usd_per_run` and `budget.usd_per_role_per_day`), or tests that can't be sandboxed. It says why in `refused`; `--dry-run` still shows who would start. `softory setup` lists the same.
- Path rules in the Claude Code settings are `Edit(...)` only. Claude Code ignores `Write(...)` path rules (`Edit` covers both), so the old `Write` rules did nothing.
- The tests that type at a terminal work on macOS as well as Linux.

## [0.4.1] - 2026-10-24

Less for every agent to read. Each run loaded 7k to 12k tokens of softory text before touching code, and about a third of it repeated itself. A run now loads 36% to 45% less (Jade 11.5k to 6.3k tokens, Greg 7.4k to 4.2k). No rule changed.

- **The instructions no longer repeat the scaffold's block.** Softory's rules and operating loop already say everything in it that applies to a softory role, so `AGENTS.md` and `CLAUDE.local.md` drop from 8.9 KB to 3.5 KB in a fresh project. A project that commits its own `AGENTS.md` with the block keeps it, as before.
- **The instructions and the operating loop say each thing once.** The rules are one-line musts; the commands live in the loop. The scaffold block's two guardrails, never opening the database directly and never putting secrets in a coordination record, are now in rule 3, and the loop keeps its "Never" list.
- **`softory-token-economy` is gone.** Most of it was advice the harnesses already give. Its four softory-specific lines are now at the end of the instructions. It also told agents to ask a question when criteria are unclear, which unattended runs must never wait on. Reinstalling removes the old skill folders.
- **Profiles hold identity, boundaries, and lanes; skills hold procedure.** Toby's threat-model, review, and severity sections, Quinn's task and architecture-review checklists, Darwin's handoff and design-review lists, Greg's ready and acceptance-review sections, and the engineers' loop were second copies of their skills or the operating loop. The "Why Claude/Codex" sections and the source lists moved out of what agents load: the reasoning is in [docs/models.md](docs/models.md), and the sources are in [docs/sources.md](docs/sources.md).
- **Jade loads `softory-design` only on `ui` tasks.**
- **Shorter skills.** `softory-code-quality` and `softory-testing` keep every rule and the rubric and drop the textbook explanations. `softory-code-review` drops the turnaround section, which a runner doesn't need.
- **Dead code removed.** `softory silent --notify` (the digest pages silent roles now), an unused constant, unused imports, and a second git wrapper and time parser. The README's cron recipe for `pending` and `silent` is gone, since `softory run` replaces it.
- Greg's roster entry no longer claims a UX copy review the RACI and boundaries don't give him.
- **Faster tests.** A plain install into the same files is copied from the first one, so the suite takes about 5 minutes instead of 8.6.

## [0.4.0] - 2026-10-24

Phase 1 of running unattended: the team works without the owner up to a pull request, and asks only for decisions that matter. The owner still merges and deploys.

- **Charter.** `factory/governance/charter.json` holds the defaults: vision, epic limits, budget, task caps, test command, lane paths, paging, harness commands, and a model per role. The owner overrides any of them once with `softory charter approve <file>` at a terminal; the overrides live in the hashed `local.json` and are recorded as a decision. `softory charter show` prints what is in force.
- **Runner.** `softory run` is one tick for launchd or cron. It starts a role only when `pending` says it has work, it's under today's budget, and it isn't paused or already running, and it pages what is due. `softory run-role` runs the harness with a time limit and logs each run to `.agents/softory/run/runs.jsonl`, which the budget counts. The prompt is a few lines naming what is waiting. `softory schedule` writes the launchd job.
- **Budget, caps, and a kill switch.** Daily runs and minutes per role, and minutes per run, with per-role overrides (`budget.roles`). Defaults: 24 runs and 120 minutes a day, 30 a run; Greg, Darwin, and Toby get shorter runs and 60 minutes a day. A task with `escalate_model_after` rounds of requested changes runs on the role's stronger model; at `review_rounds` it drops out of `pending` and goes to the owner. `softory pause` (anyone) and `softory resume` (owner, at a terminal); `pending` honours a pause too. `softory usage` shows today's use.
- **Tests and lanes in the gate.** `softory verify <ID>` runs the charter's `verify.command` at the unit's newest commit in a throwaway worktree and keeps the result in softory's own ledger. With a command set, a task or bug needs a pass there (`verified`); an evidence row an agent writes doesn't count. With lane paths set, `lane_paths` fails a diff outside the lane unless the task is tagged `cross-lane` and Quinn accepted it. Both checks are off until the charter sets them, and both are waivable by the owner.
- **Digest and paging.** `softory digest` lists what needs the owner: proposals, escalations to the owner, capped tasks, unread messages, silent and paused roles, and budget warnings. A unit closed without the gate, or a role over budget, pages at once (once a day each, outside quiet hours); the rest goes in one daily digest, to the owner's inbox and through `paging.command`.
- **Permissions per role.** Claude Code roles run with a generated settings file: edits only in their lane's paths or their docs folder, the coordination and git commands they need, and never softory's or the database's files.
- **Builders hear about requested changes.** `pending` now wakes a builder whose task in review got a "changes requested", instead of waiting for a message.
- **Models from role-fit benchmarks.** Darwin, Quinn, Jade, and Gold default to Claude Opus 5.5, which leads Terminal-Bench 4.0 (64.8%) and the WebDev Arena (1807). Toby and Greg default to Codex with GPT-6 Astra, which leads SEC-Bench Pro (85.4%) and ties Opus on CWE-bench (68% to 67%). A cheaper Sol setup with escalation is documented for tight budgets. [docs/models.md](docs/models.md) has the sources.
- **Less wasted work per run.** Reviewers aren't woken until `softory verify` passed at the commit (the builder is woken to fix the tests instead), and wake in batches: at `review_batch.min` waiting reviews (2) or after `review_batch.max_wait_minutes` (60), clearing all of them in one run. The prompt carries each waiting unit's title, acceptance criteria, requested changes, and changed files, with the fixed rules first so the prompt cache applies. Effort follows the job: `effort.review` (medium) for runs with only reviews, closes, or messages, `effort.build` (high) otherwise, with a per-role override.
- **Real tokens and cost.** Runs log input, cached, and output tokens and dollars from each harness's own report (`--output-format json` for Claude Code, `--json` for Codex; Codex dollars are estimated from `prices`). `softory usage` totals them. Optional `usd_per_run` and `usd_per_role_per_day` caps, off by default.
- Claude Code permission rules use the `Bash(cmd *)` form.
- **`softory setup`** checks the owner's one-time steps and says what is left.

## [0.3.1] - 2026-10-24

Moves to scaffold **1.4.1**, the schema-1 maintenance release that fixed fifteen of softory's gaps. The schema is unchanged, so Vault Radar's database needs no migration. [docs/gaps.md](docs/gaps.md) lists what 1.4.1 fixed and what softory now uses.

- **Pin.** `dependencies.json` pins scaffold `v1.4.1` (`9e534a6`). The installer accepts 1.4.1 or a later 1.x and still refuses 2.x, which the tracker can't read.
- **Upgrade with a backup.** Re-running the installer on a project with an older 1.x scaffold (Vault Radar runs 1.4.0) backs the database up with the project's current CLI first, to `.coordination/backups/pre-scaffold-1.4.1-<time>.sqlite3`, and reports the path as `scaffold_backup`. The backup is audited under the owner once the owner is registered. If it fails, the scaffold is left as it was. A project on a newer scaffold, 1.x or 2.x, is refused instead of silently downgraded. The README's upgrade steps say to pause scheduled roles first and how to restore.
- **Codex reads the current scaffold block.** When a project commits its own `AGENTS.md` with an older scaffold block (Vault Radar's still says `inbox mark-read --cursor HEAD`, which the CLI rejects), the generated `AGENTS.override.md` now carries the installed scaffold's block instead of copying the old one. The tracked file is untouched; `softory doctor` warns about it and says how to update it.
- **`triage` lists work closed outside softory**: done since install without softory's close or drop note, meaning someone ran `task status done` directly and the gate never saw it. None in Vault Radar's data.
- **No `.gitignore` edits.** The scaffold installer runs with `--no-gitignore`, replacing softory's snapshot and restore.
- **Latest review is really the latest.** Review lookups sort by `sequence`. `task show` still sorts reviews by second and then ID, so an accept (REV-9) and a request for changes (REV-10) in the same second read as "accepted"; softory now re-reads that task's reviews in recorded order, and the gate holds.
- **Closers don't become builders.** Claims made only to close or drop use `task claim --no-assign`, instead of adding the assignee and taking it back.
- **Rulings and proposals name who recorded them.** `softory ruling` and `softory propose` pass `--recorded-by`, so the audit row is written by the role, and the decision stays the owner's.
- `softory doctor` adds `warnings` from the scaffold's new filesystem report, such as FUSE leftovers beside the database. They never fail doctor.
- Softory ignores an inherited `COORDINATION_DB`; the project it runs in decides the database.
- The scaffold's strict `closure_policy` and `dependency_policy` stay off: they would refuse review records, dropped work, and stacked work. See S24.

## [0.3.0] - 2026-10-23

From the owner's eight points after a week in Vault Radar, and an independent review of 0.2.0. Don't install 0.2.0; install this.

- **Review records.** A review run kept as a task is a record of the reviewer's output. Its own verdicts never block it, nobody reviews it again unless a tag on it needs a reviewer its author isn't (a `security` record by Avery needs Toby's sign-off, unless Avery stands in for Toby), and a "changes requested" on it counts as handled once it names follow-up tasks that exist, or its reviewer later accepts. It must hold reports and no code, name what it reviewed, and not review its reviewer's own work. It closes from review, blocked, or todo. On a copy of Vault Radar's database from 2026-10-23, 28 of the 34 open review runs pass the gate after `adopt`. Five link to nothing they reviewed and need `--for` (three of those look like ordinary tasks, not review runs), and one holds on a product objection with no follow-up task.
- `softory adopt <ID> --unit review` reads what a run reviewed from its `informs` links, leaving out other review runs and the reviewer's own work. Only the run's reviewer or the owner may ask, a task with code evidence is refused, and nothing changes until the owner approves: `softory approve --all` takes every waiting adoption after one typed yes and records one decision for the batch. The prompt lists anything not tagged or named as a review run first, and stand-ins and waivers are never part of `--all`. Otherwise a builder could relabel their own unreviewed fix as a review and close it.
- **Named backups can't be gamed.** The backup reviewer applies only when the specialist alone built the work. Adding Toby as a co-assignee no longer moves the security review to Quinn. A role-wide stand-in for the specialist doesn't count on the specialist's own work; one scoped to that task does. (In Vault Radar, Avery's role-wide stand-in for Toby had silently become the reviewer of Toby's own threat model.)
- **Scoped stand-ins.** `softory standin add <agent> --for <roles> [--task IDs] [--until YYYY-MM-DD]`. Grants that name tasks apply only there, and an end date lapses on its own. `standin list` shows each grant and whether it's active; `standin remove <agent> [--for roles]` takes back some or all. Older `local.json` files still read.
- **Dropped work.** `softory drop <ID> --reason ... [--superseded-by ID]` closes a unit nobody will build, with a decision, evidence pointing to it, and `resolution:` tags. Droppers are in `gates.json`. `softory tree` shows `done: won't do` or `done: superseded by ...`.
- **Stacks.** `softory stack <bottom> ... <top>` groups work built on other unfinished work. `softory close <top> --stack` checks every member's gate with the other members counted as done, and closes them bottom first only if all pass. The coordination CLI has no transactions, so if a close call itself fails partway, softory stops and reports what it closed (`closed_before_error`).
- **Follow-ups don't block their source.** `softory new bug --from <ID>` links back with `informs`. `--blocks-source` keeps the 0.2.0 behaviour when it's needed.
- **Silent roles.** `softory silent [--hours 12] [--notify]` lists roles with work waiting and no session for that long, or ever, and messages the owner once a day per role. `triage` includes it. The README shows a launchd or cron line with a desktop notification.
- `softory pending` no longer strands work after a crashed run: any waiting work counts again once `--retry-hours` (default 4) pass without a run.
- **Owner rulings.** `softory ruling --title ... --decision ... --where ...` records a decision under the owner's name, marked "recorded by <role>" with the session and where the owner said it.
- **Owner approval.** `standin add|remove` and `softory approve [IDs | --all]` run only at a terminal, after a typed yes. Agents ask with `softory propose standin|waiver ... --why ...`, which records a proposed decision and grants nothing. A waiver lets one review check pass on one task, and the gate shows it.
- **Rules don't drift by accident.** The installer makes `gates.json`, the role files, softory's code, and `local.json` read-only and records their hashes. The gate fails closed (`config_intact`) and `doctor` names the file when one changes. This catches mistakes, not a determined agent: the hashes sit in `manifest.json`, and a terminal can be simulated.
- **CLI.** `softory inbox` lists unread messages with the number that marks exactly those read (`--mark-read N`); the operating-loop skill no longer says `--cursor HEAD`, which the scaffold rejects. `softory message <ID>` shows one message. `softory all <entity> list` follows every page past 500 rows, and the gate's review lookups page too.
- `triage` recognises `code-review` and `independent-review` tags as review runs, and suggests each run's adopt command.

## [0.2.0] - 2026-10-23

From two days of agents using softory in Vault Radar.

- `softory queue` lists `ready_to_close`: your tasks in review that pass the gate and that you may close. Sixteen such tasks sat unclosed in Vault Radar, EPIC-1 among them.
- Named backup reviewers: when the specialist a tag names built the work, the tag's `if_builder` reviewers review it. Quinn backs up Toby on `security`, `auth`, `data`, and `deps`; Jade or Gold back up Quinn on `arch`; the owner backs up Darwin on `ui`. The owner chose this on 2026-10-23.
- Review units: `softory new review --for <IDs>` keeps a review run as its own task. It closes once its reviewer has recorded a verdict on each reviewed task, with no tag reviews and no review of the review. `softory adopt <ID> --unit review --for <IDs>` converts an older review run.
- Follow-ups: `softory new bug --from <ID>` inherits the source's story and lane, tags `from:<ID>`, and makes an open source task wait for the fix.
- `softory pending [role]` exits 0 when a role has work and 3 when it doesn't, without starting a session, so a scheduler can skip idle runs.
- `softory triage` also lists older review runs to adopt, sessions silent for a day, and sessions started before the last install or upgrade.
- `softory tree` groups stories and bugs that aren't under an epic, and `softory new story` warns when there's no `--parent`.
- The instructions tell agents to file every new task through `softory new`, follow-ups with `--from`.

## [0.1.0] - 2026-10-21

First release.

- Six roles with decision, review, and work boundaries: Greg (Product Manager), Darwin (UX Designer), Quinn (Principal Engineer), Jade and Gold (Senior Software Engineers, frontend and backend/infra lanes), and Toby (Security Engineer).
- RACI matrix with one accountable role per activity, flex rules for allowed overlap, and escalation paths.
- Units of work: epic (project), story (feature), task (function), and bug (fix), with templates and flows.
- Nine skills: operating loop, code quality, testing, code review, secure coding, design, product spec, architecture, and token economy.
- `softory` CLI: `start`, `new`, `tree`, `adopt`, `queue`, `reviewers`, `gate`, `close`, `standin`, `triage`, `link`, `worktree`, `coord`, `end`, `feedback`, `roles`, `doctor`, `tracker`, `sync`, `skills`, `uninstall`.
- Installer that adds scaffold 1.4.0 (SQLite) and the tracker, registers the roles, and hides everything with `.git/info/exclude`.
- A catalog of recommended open-source skills, pulled at pinned commits.
- Git worktrees: `softory worktree add` and `softory link` symlink softory into a worktree, hidden by the shared exclude rules; `--share` links installed dependencies too; `softory coord` runs the coordination CLI against the main database from anywhere; `softory end` ends a session; the CLI finds the main checkout from any worktree.
- `softory feedback` lets agents log friction with softory itself to `.agents/softory/feedback.jsonl`, and the instructions ask them to.
- `softory triage` lists open tasks that already have an accepted review. `softory doctor` flags an `AGENTS.override.md` that is out of date. The installer reports an existing scaffold and refuses to downgrade a 2.x one, and `uninstall` leaves a scaffold the project had before softory.
- Joining a project that already has a team: `softory standin` for existing agents, a minimum `legacy` gate for tasks created before softory, `softory adopt` to move them into a story, and no repeated scaffold block when the project's `AGENTS.md` already has it.
