---
name: using-subagent-orchestrator
description: Use when starting any Codex conversation or task to decide whether the subagent-orchestrator skill should be applied before work. This is a lightweight bootstrap skill similar to Superpowers using-superpowers: it checks whether orchestration, process, or subagent skills should be used before substantive action. Skip when already running as a dispatched subagent, when the user explicitly requested no orchestration, or when the task is obviously tiny.
---

# Using Subagent Orchestrator

This skill is a lightweight bootstrap gate. Its job is to decide whether to load and follow `subagent-orchestrator` before work begins.

It must **not** force parallel agents by default. It only forces the evaluation.

## Priority

User instructions are highest priority. If the user explicitly says not to use subagents, not to orchestrate, or to work linearly, obey that.

If this session is already a bounded dispatched subagent task, do not recursively orchestrate unless the parent explicitly asked for it.

## First step

Before substantive work, briefly classify the prompt:

```text
Orchestration gate: skip | check | use-subagent-orchestrator
Reason: <one sentence>
```

Use:

- `skip` for tiny edits, simple Q&A, direct one-file tasks, or explicit user opt-out.
- `check` for moderate uncertainty where a short local evaluation is enough.
- `use-subagent-orchestrator` for complex debugging, multi-file work, PR review, refactors, migrations, architecture exploration, performance/security work, broad tests, unfamiliar APIs, or tasks with separable research/review/testing tracks.

## If `use-subagent-orchestrator`

Load and follow the `subagent-orchestrator` skill before any code changes or broad tool work.

The desired result is one of:

- `single-thread`
- `sequential-plan`
- `parallel-subagents`

Only spawn subagents when the evaluation shows real value.

## If `check`

Do a short inline evaluation using the same categories. Do not load extra ceremony unless the task decomposes cleanly.

## Red flags

Stop and evaluate before continuing when you notice:

- multiple possible root causes,
- multiple independent files/subsystems,
- separate research, testing, review, or implementation tracks,
- noisy logs or broad searches,
- security/performance/regression risks,
- external API or version-specific behavior,
- unclear requirements likely to benefit from separate design/review.

## Avoidance rules

Do not use orchestration when:

- coordination overhead would exceed value,
- agents would edit the same files without worktree isolation,
- the task is strictly sequential,
- the user wants a quick direct answer,
- you cannot define bounded subagent jobs with clear outputs.
