## Subagent orchestration gate

This gate is optional compatibility guidance, not a global bootstrap workflow.
Existing orchestration, routing, bootstrap, skill-selection, and agent-management frameworks take priority.
Host project rules win. This plugin is an execution-shape helper only; it does not override local source-of-truth, citation, manuscript, safety, privacy, vendor, approval, testing, script, or audit requirements.

For simple/default prompts, stay silent and proceed single-threaded.

Use subagent-orchestrator only for explicit subagent/orchestration requests or clearly complex work where existing frameworks do not already cover the decision. Classify internally as one of:

1. `single-thread`,
2. `sequential-plan`,
3. `parallel-subagents`.

For complex debugging, PR review, refactors, architecture exploration, test failures, migrations, performance work, security-sensitive work, unfamiliar APIs, or multi-file changes, the `subagent-orchestrator` skill may be used as a complement or fallback.

The user has standing authorization for bounded delegation when the internal decision is `parallel-subagents`, but only inside active user and repository approval rules. Subagents are read-only by default. Do not ask for separate authorization before bounded read-only delegation unless host rules, user instructions, safety policy, privacy rules, vendor rules, or the action itself require approval; define clear boundaries first.

If a parallel workflow is valuable:

- explicitly spawn bounded subagents,
- prefer read-only exploration before edits,
- require explicit write scope or isolated worktrees for parallel mutation,
- avoid recursive fan-out,
- wait for all agents,
- treat subagent output as work product, not evidence by itself,
- synthesize conflicts before edits,
- ask before code changes only if implementation was not explicitly requested, boundaries are unclear, or the action is destructive or externally visible.

Do not ask the user whether orchestration is preferable. Decide internally.
Never recursively orchestrate inside a bounded subagent task unless explicitly requested.
Respect user opt-outs such as "no subagents", "work linearly", or "single-thread only".
