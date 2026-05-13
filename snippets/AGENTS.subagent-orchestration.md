## Subagent orchestration gate

Before starting any task, run a lightweight orchestration gate.

Classify the task as one of:

1. `single-thread`,
2. `sequential-plan`,
3. `parallel-subagents`.

For simple tasks, proceed single-threaded without ceremony.

For complex debugging, PR review, refactors, architecture exploration, test failures, migrations, performance work, security-sensitive work, unfamiliar APIs, or multi-file changes, use the `using-subagent-orchestrator` bootstrap skill or the `subagent-orchestrator` skill.

If a parallel workflow is valuable:

- explicitly spawn bounded subagents,
- prefer read-only exploration before edits,
- avoid recursive fan-out,
- wait for all agents,
- synthesize conflicts before acting,
- ask before code changes unless implementation was explicitly requested.

Never recursively orchestrate inside a bounded subagent task unless explicitly requested.
Respect user opt-outs such as "no subagents", "work linearly", or "single-thread only".
