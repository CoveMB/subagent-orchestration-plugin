# Try-it prompts

Use these after installing and restarting Codex.

## Explicit skill invocation

```text
$subagent-orchestrator
Evaluate this task first. Decide whether it should be single-thread, sequential-plan, or parallel-subagents, then proceed accordingly:

Find why the login flow flakes in CI and propose the minimal fix.
```

## Implicit trigger

```text
Find and fix the failing tests around the checkout flow. Use subagents only if the work decomposes cleanly.
```

## Review-style trigger

```text
Review this branch for correctness, security, missing tests, and behavior regressions. Use parallel subagents if valuable, synthesize conflicts before editing, and do not change files unless I ask.
```

## Minimal-task non-trigger

```text
Rename this variable in one file and keep the change minimal.
```
