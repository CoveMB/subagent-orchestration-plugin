# Subagent Orchestration for Codex

This starter kit gives Codex a quiet, compatibility-oriented orchestration gate:

- every prompt is classified internally and receives compact result/reason metadata,
- existing orchestration, routing, bootstrap, skill-selection, and agent-management frameworks take priority,
- simple prompts stay single-threaded unless the user asks otherwise,
- complex prompts still receive only result/reason metadata,
- bounded delegation has standing authorization when the internal decision is `parallel-subagents`,
- parallel subagents are used only when they add real value.

It packages:

```text
plugin/subagent-orchestrator/
  .codex-plugin/plugin.json
  skills/using-subagent-orchestrator/SKILL.md
  skills/subagent-orchestrator/SKILL.md

hooks/subagent_orchestration_gate.py
custom-agents/*.toml
snippets/AGENTS.subagent-orchestration.md
snippets/config.subagents.toml
snippets/config.hooks.*.toml
marketplace/*.json
scripts/install_user.py
install.sh / install.ps1
```

## How this coexists with other workflows

Superpowers and other workflow systems should keep priority. This kit does not replace them and does not ask the user whether orchestration is preferable on every prompt.

For Codex, the quiet behavior comes from three layers together:

1. **Compatibility skill**: `using-subagent-orchestrator` exists for explicit or legacy checks.
2. **Orchestration skill**: `subagent-orchestrator` chooses `single-thread`, `sequential-plan`, or `parallel-subagents`.
3. **UserPromptSubmit hook**: always reports only a result and reason through valid `additionalContext`.

The hook does not spawn agents by itself or inject execution instructions. After the orchestration skill selects `parallel-subagents`, the assistant must call `spawn_agent` or the available subagent-spawning tool in that same turn after defining bounded roles. It should only fall back to sequential work when no spawning tool is available or higher-priority rules block spawning.

A plugin can package the skills. The installer supports user/global skill installation and project-scoped activation, but activation is always explicit.

## Boundary model

- **Plugin-level boundary**: this plugin is an execution-shape helper only. It can help choose `single-thread`, `sequential-plan`, or `parallel-subagents`; it does not decide truth, evidence, citations, approvals, vendor trust, or test sufficiency.
- **Host-repo boundary**: domain-specific user instructions, repository `AGENTS.md`, local scripts, audit requirements, and source-of-truth rules win over plugin guidance. When host repository rules are stricter, host repository rules win.
- **Subagent-output boundary**: subagent output is work product, not evidence by itself. Required tests, citations, source checks, approvals, and audit notes still need to be performed directly.
- **Hook boundary**: the hook only reports classification metadata. It does not enforce truth, validate sources, authorize edits, satisfy citations, replace tests, or bypass safety/privacy/vendor/approval rules.
- **Installer boundary**: user scope never writes `CODEX_HOME/config.toml` or `CODEX_HOME/AGENTS.md`. Project scope writes only under the selected repository root and never patches `~/.codex` or `~/.agents`.

## Four install modes

### 1. Manual skill-only use

macOS/Linux:

```bash
./install.sh
```

Windows PowerShell:

```powershell
./install.ps1
```

The default user-scope install copies only direct skills to `~/.agents/skills/`. It does not stage a hook, patch config, append guidance, install custom agents, or register plugin packaging.

Manual copy is also supported:

```bash
mkdir -p ~/.agents/skills
cp -R plugin/subagent-orchestrator/skills/* ~/.agents/skills/
```

Then use:

```text
$using-subagent-orchestrator evaluate this task first, then proceed.
```

or:

```text
$subagent-orchestrator choose single-thread, sequential-plan, or parallel-subagents before work.
```

### 2. User/global activation

Stage the hook in `CODEX_HOME/hooks` only when you want to manually activate it for that user profile:

```bash
./install.sh --with-hook
```

PowerShell:

```powershell
./install.ps1 -WithHook
```

The installer still does **not** patch `CODEX_HOME/config.toml`; merge one of `snippets/config.hooks.*.toml` manually when you want the hook active for that global Codex home.

The installer prints an activation reminder at the end:

```text
config.toml was not modified.
Hook staged but not active.
Activation required: manually merge snippets/config.hooks.posix.toml into CODEX_HOME/config.toml.
```

Preview the install without writing files:

```bash
./install.sh --dry-run
```

PowerShell:

```powershell
./install.ps1 -DryRun
```

Remove owned user-scope files and hook config entries:

```bash
./install.sh --uninstall
```

PowerShell:

```powershell
./install.ps1 -Uninstall
```

### 3. Project-scoped activation

Project scope writes only inside the repository root. It never writes `~/.codex`, never writes `~/.agents`, never patches `~/.codex/config.toml`, never appends `~/.codex/AGENTS.md`, never installs hooks globally, and never enables plugin state globally.

Activate the gate for Codex sessions opened from a trusted project:

```bash
./install.sh --scope project --activate-gate
```

PowerShell:

```powershell
./install.ps1 -Scope project -ActivateGate
```

This creates or updates repo-local files:

- `.codex/config.toml`
- `.codex/hooks/subagent_orchestration_gate.py`
- `.agents/skills/using-subagent-orchestrator`
- `.agents/skills/subagent-orchestrator`
- `.codex/subagent-orchestrator-install.json`

Optional project-only additions:

```bash
./install.sh --scope project --activate-gate --with-project-agents
./install.sh --scope project --with-repo-marketplace
./install.sh --scope project --append-project-agents-md
```

Project scope installs repo-local skills by default. Omit `--activate-gate` to make skills available without activating the prompt gate. Use `--dry-run` to print created, patched, copied, symlinked, and backed-up paths without changing files. Use project uninstall to remove manifest-owned activation files:

```bash
./install.sh --scope project --repo-root /path/to/repo --uninstall
```

Project-scoped activation affects only Codex sessions opened from that trusted project, because it uses project `.codex/config.toml`, project hooks, and repo-local skills.

### 4. Vendored project activation

If the plugin is vendored into a repository, prefer symlinked skills:

```bash
./vendor/subagent-orchestration-plugin/install.sh \
  --scope project \
  --repo-root "$(git rev-parse --show-toplevel)" \
  --from-vendor "$(git rev-parse --show-toplevel)/vendor/subagent-orchestration-plugin" \
  --activate-gate \
  --link-skills
```

This links:

```text
.agents/skills/using-subagent-orchestrator
  -> vendor/subagent-orchestration-plugin/plugin/subagent-orchestrator/skills/using-subagent-orchestrator

.agents/skills/subagent-orchestrator
  -> vendor/subagent-orchestration-plugin/plugin/subagent-orchestrator/skills/subagent-orchestrator
```

If symlinks fail, the installer falls back to copying. Omit `--link-skills` to use copies.

The repo marketplace option adds or updates `.agents/plugins/marketplace.json` with a local plugin path:

```json
{
  "name": "subagent-orchestrator",
  "source": {
    "source": "local",
    "path": "./vendor/subagent-orchestration-plugin/plugin/subagent-orchestrator"
  },
  "policy": {
    "installation": "AVAILABLE",
    "authentication": "ON_INSTALL"
  },
  "category": "Productivity"
}
```

Caveat: plugin UI enable/disable state is stored in `~/.codex/config.toml`, so strict project-only behavior should use repo-local skills and hooks rather than relying only on plugin installation.

## Project hook config

Project activation patches `.codex/config.toml` idempotently and preserves unrelated config:

```toml
[features]
codex_hooks = true

[agents]
max_threads = 4
max_depth = 1

[[hooks.UserPromptSubmit]]
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = 'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/subagent_orchestration_gate.py"'
timeout = 5
statusMessage = "Evaluating subagent orchestration"
```

Existing project config is backed up before modification. The project hook fails open if a vendored hook target is missing.

## Custom agents

Included custom agents:

- `so_mapper`: read-only code path and dependency mapper.
- `so_reviewer`: read-only correctness/security/test-risk reviewer.
- `so_tester`: read-only test and verification planner.
- `so_reproducer`: workspace-write failure reproducer.
- `so_docs_researcher`: docs/version behavior verifier.
- `so_designer`: compares implementation options and tradeoffs.
- `so_implementer`: bounded implementation agent.

Copy them manually into `~/.codex/agents` or `.codex/agents` only when you want these custom agent profiles available.

## Smoke test the hook

```bash
bash scripts/check.sh
```

Expected:

- debugging prompt => `use-subagent-orchestrator`,
- rename prompt => `single-thread-likely` with only result/reason metadata,
- user opt-out => `orchestration-opt-out`,
- child-agent prompt => `recursion-guard`.

## Skill evals

The fast check suite validates the eval assets and the offline trace grader, but it does not run live agent sessions.

The prompt corpus lives at `evals/skill_prompts.jsonl`. Each row defines the expected hook decision, whether a spawn attempt is required or forbidden, host-rule fixtures, command limits, and rubric ids. The set intentionally includes positive, negative, opt-out, child-agent, host-rule, and broad parallel-work cases.

To grade captured JSONL traces, place one trace per prompt id in a directory as `<id>.jsonl`, then run:

```bash
python3 scripts/grade_skill_traces.py --prompts evals/skill_prompts.jsonl --traces path/to/traces
```

The grader checks observed `Result:` metadata, spawn attempts, forbidden externally visible commands, and command-count budgets. It prints structured JSON compatible with `evals/trace_eval.schema.json`.

## Safety notes

- Keep `max_depth = 1` if you manually merge `snippets/config.subagents.toml`.
- Prefer read-only subagents first.
- Do not let multiple agents edit the same files unless they are in isolated worktrees.
- Treat the hook as classification metadata, not an enforcement boundary.
- Respect user opt-outs.
- Repository-specific `AGENTS.md` files and source-of-truth project rules remain higher authority than this global guidance.
- Do not make this kit compete with Superpowers, Recursive Mode, or other orchestration/routing/bootstrap systems.
