# Subagent Orchestration for Codex

This starter kit gives Codex a Superpowers-style orchestration gate:

- every prompt can be classified before work begins,
- simple prompts stay single-threaded,
- complex prompts can load the `subagent-orchestrator` skill,
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

## How this mirrors Superpowers

Superpowers has a bootstrap skill that is meant to run at conversation/task start and check whether other skills apply. This kit uses the same idea with `using-subagent-orchestrator`.

For Codex, the strongest always-on behavior comes from three layers together:

1. **Bootstrap skill**: `using-subagent-orchestrator` checks whether orchestration should be evaluated.
2. **Orchestration skill**: `subagent-orchestrator` chooses `single-thread`, `sequential-plan`, or `parallel-subagents`.
3. **UserPromptSubmit hook**: deterministically injects orchestration guidance before each prompt is processed.

A plugin can package the skills. The hook is installed separately into `~/.codex/hooks` and registered in `~/.codex/config.toml` for maximum reliability across Codex versions.

## Install and activate

macOS/Linux:

```bash
./install.sh
```

Windows PowerShell:

```powershell
./install.ps1
```

This installs:

- direct skills to `~/.agents/skills/`,
- custom agents to `~/.codex/agents`,
- hook script to `~/.codex/hooks`,
- AGENTS.md snippet to `~/.codex/AGENTS.md`,
- hook and subagent settings to `~/.codex/config.toml`.

The patcher creates a backup of `~/.codex/config.toml` first, then tries to add:

```toml
[features]
codex_hooks = true

[agents]
max_threads = 6
max_depth = 1

[[hooks.UserPromptSubmit]]
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = "<your-python> <your-home>/.codex/hooks/subagent_orchestration_gate.py"
timeout = 5
statusMessage = "Evaluating subagent orchestration"
```

To install files without changing config:

macOS/Linux:

```bash
./install.sh --no-patch-config
```

Windows PowerShell:

```powershell
./install.ps1 -NoPatchConfig
```

## Install as a local plugin too

macOS/Linux:

```bash
./install.sh --plugin
```

Windows PowerShell:

```powershell
./install.ps1 -Plugin
```

The plugin packaging makes the skills available through Codex's plugin system. The config-patched hook gives the always-on prompt gate by default.

## Manual skill-only install

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

## Custom agents

Included custom agents:

- `so_mapper`: read-only code path and dependency mapper.
- `so_reviewer`: read-only correctness/security/test-risk reviewer.
- `so_tester`: read-only test and verification planner.
- `so_reproducer`: workspace-write failure reproducer.
- `so_docs_researcher`: docs/version behavior verifier.
- `so_designer`: compares implementation options and tradeoffs.
- `so_implementer`: bounded implementation agent.

Copy them into `~/.codex/agents` or `.codex/agents`.

## Smoke test the hook

```bash
python3 tests/test_hook.py
```

Expected:

- debugging prompt => `use-subagent-orchestrator`,
- rename prompt => `single-thread likely`,
- user opt-out => `skip`,
- child-agent prompt => `skip recursive`.

## Safety notes

- Keep `max_depth = 1` unless you explicitly want recursive delegation.
- Prefer read-only subagents first.
- Do not let multiple agents edit the same files unless they are in isolated worktrees.
- Treat the hook as a strong nudge, not an enforcement boundary.
- Respect user opt-outs.
