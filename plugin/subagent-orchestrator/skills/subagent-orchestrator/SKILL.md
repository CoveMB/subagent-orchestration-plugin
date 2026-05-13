---
name: subagent-orchestrator
description: Evaluate whether a Codex task should use single-thread execution, a sequential plan, or parallel subagents before work begins. Use for complex debugging, PR review, refactors, multi-file changes, architecture exploration, tests, security review, performance issues, unfamiliar APIs, docs/version verification, flaky failures, migrations, ambiguous implementation tasks, and prompts where parallel investigation could improve reliability or reduce context noise. Do not use for tiny edits, simple Q&A, one obvious single-file fixes, or strictly sequential tasks.
---

# Subagent Orchestrator

Use this skill before substantive work when the prompt may benefit from parallel delegation. It can be invoked directly, selected implicitly from its description, or reached through the `using-subagent-orchestrator` bootstrap skill / UserPromptSubmit hook.

The goal is not to spawn agents by default. The goal is to choose the smallest execution shape that is likely to improve correctness, evidence quality, speed, or context hygiene.

## Required first decision

Before substantive work, classify the task as exactly one of:

1. `single-thread`
   - The task is small, direct, low-uncertainty, or one-file/one-command obvious.
   - Parallelism would add more overhead than value.

2. `sequential-plan`
   - The task has multiple steps, but the steps depend on each other.
   - Make a concise plan and proceed linearly.
   - Do not spawn subagents yet.

3. `parallel-subagents`
   - The task can be decomposed into independent exploration, reproduction, test review, documentation verification, architecture mapping, implementation alternatives, or risk review.
   - Subagents are likely to reduce context pollution, improve evidence, or save wall-clock time.

## Spawn subagents when at least two are true

- Multi-file, multi-module, or multi-service change.
- Unknown code path or unfamiliar repository.
- Failure reproduction is separable from source inspection.
- Test discovery and result interpretation can happen independently.
- Documentation/API/version behavior may affect correctness.
- Security, correctness, performance, and implementation concerns can be reviewed separately.
- The task is likely to produce noisy logs or broad search output.
- There are multiple plausible approaches worth comparing.
- The user asks for review, audit, migration, refactor, architecture, performance, debugging, or root-cause analysis.

## Avoid subagents when any are true

- The user asks a simple direct question.
- The edit is tiny and obvious.
- The task needs one linear chain of work.
- Agents would compete to mutate the same files.
- The user asked for a quick answer.
- The repo state is dirty and isolation is unclear.
- You cannot define bounded jobs with clear outputs.

## Output before work

Always start non-trivial work with:

```text
Orchestration: single-thread | sequential-plan | parallel-subagents
Reason: <1-3 sentences>
Plan: <short plan>
```

If using subagents, include:

```text
Subagents:
- name: <agent name>
  role: <bounded role>
  mode: read-only | workspace-write
  task: <specific bounded task>
  expected output: <evidence format>
```

Then spawn the agents, wait for all results, and synthesize before acting.

## Execution Runbook

Use this order when the decision is `parallel-subagents`:

1. State the orchestration decision, reason, plan, and bounded subagents.
2. Spawn the smallest useful set of read-only agents first.
3. Give each agent one self-contained task, explicit mode, expected output, and no permission to fan out.
4. Keep implementation agents for later unless the user already requested code changes and write scopes are disjoint.
5. Continue local work only on non-overlapping context while agents run.
6. Wait for all agents that affect the next decision.
7. Synthesize agreed facts, conflicts, files, risks, and tests before any edits.
8. Ask before code changes unless the user clearly requested implementation.

### Spawn Template

```text
Spawn <agent-name>:
- mode: read-only | workspace-write
- scope: <files, subsystem, or question>
- task: <specific bounded task>
- constraints: do not edit files; do not spawn more agents; report uncertainty
- expected output: facts, file paths, evidence, risks, tests, confidence
```

For workspace-write tasks, add:

```text
- write scope: <exact files/modules>
- coordination: other agents may be working; do not revert unrelated edits
- verification: <targeted commands or manual checks>
```

### Agent Task Templates

- `so_mapper`: Map execution paths, affected files, call sites, dependencies, and likely change boundaries. Return evidence with file paths and uncertainty.
- `so_reviewer`: Review correctness, security, regressions, hidden coupling, and missing tests. Return only real findings with severity and recommended next action.
- `so_tester`: Identify targeted tests, expected failures, verification commands, and remaining coverage gaps. Run commands only when safe for a read-only workspace.
- `so_reproducer`: Reproduce failures, collect logs, and manage temporary scratch artifacts after read-only test planning narrows the scope.
- `so_docs_researcher`: Verify external API, framework, or version-specific behavior from authoritative sources. Separate documented facts from inference.
- `so_designer`: Compare implementation options, tradeoffs, migration risks, and testability. Recommend the smallest reversible plan.
- `so_implementer`: Apply one bounded patch after mapping/review narrows the change. Use only with explicit write scope and verification requirements.

### Fallback When Custom Agents Are Unavailable

If a named custom agent cannot be spawned, use the closest available read-only agent or perform that subtask locally. Preserve the same boundaries: one task, no recursive fan-out, explicit evidence, and synthesis before action. Do not fabricate agent results.

## Default patterns

### Debugging

Prefer read-only agents first:

- `explorer` or `so_mapper`: map relevant code paths and likely failure location.
- `so_reproducer`: reproduce the failure and collect logs, if safe.
- `so_tester`: identify targeted tests and missing test coverage.
- `so_reviewer`: inspect likely fix risks.

Synthesis must include:

- observed failure mode,
- evidence,
- likely root cause,
- minimal fix path,
- tests to run,
- uncertainty or conflicts.

### PR/branch review

Spawn:

- `so_mapper`: map changed files and execution paths.
- `so_reviewer`: correctness, security, regression, and missing-test risks.
- `so_tester`: test coverage and likely failing cases.
- `so_docs_researcher`: only if external API/framework/version behavior matters.

Synthesis must include real issues only, with severity, file paths, symbols, reproduction/evidence, and recommended next action.

### Refactor or migration

Spawn:

- `so_mapper`: affected APIs, call sites, dependencies, and boundaries.
- `so_reviewer`: hidden coupling, backwards compatibility, and behavior risks.
- `so_tester`: regression test plan and safety checks.
- `so_implementer`: only after mapping/risk review are summarized, unless the user explicitly requested parallel implementation attempts in isolated worktrees.

Synthesis must include phased implementation, files to change, migration risks, rollback plan, and tests.

### Feature implementation

Use subagents only when the feature is large or ambiguous:

- `so_mapper`: current architecture and extension points.
- `so_designer`: implementation options and tradeoffs.
- `so_tester`: acceptance and regression tests.
- `so_reviewer`: correctness and maintenance risks.

Then implement the smallest safe plan.

## Hard rules

- Prefer read-only subagents before edit-capable subagents.
- Keep each subagent bounded and independently useful.
- Give each subagent a clear return format.
- Do not recursively spawn subagents unless the user explicitly asks.
- Wait for all subagents before final synthesis.
- Do not silently merge conflicting findings.
- Do not make code changes until the orchestration decision is complete.
- Ask before code changes unless the user clearly requested implementation.
- When subagents are not worth it, say so briefly and continue single-threaded.

## Synthesis format after subagents

```text
Synthesis:
- Agreed facts:
- Conflicts or uncertainty:
- Recommended path:
- Files/symbols involved:
- Risks:
- Tests/verification:
- Next action:
```
