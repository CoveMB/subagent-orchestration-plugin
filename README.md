# Subagent Orchestration for Codex

This starter kit gives Codex a quiet, compatibility-oriented orchestration gate:

- every prompt is classified internally, while simple/default prompts stay completely silent,
- existing orchestration, routing, bootstrap, skill-selection, and agent-management frameworks take priority,
- simple prompts stay single-threaded,
- complex prompts can receive a quiet hint to use `subagent-orchestrator` only as a complement or fallback,
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
3. **UserPromptSubmit hook**: stays silent for simple/default prompts and injects only a quiet compatibility hint for complex prompts.

A plugin can package the skills. The user installer copies only the direct skill folders and a dormant hook file; hook registration remains a manual config step.

## Boundary model

- **Plugin-level boundary**: this plugin is an execution-shape helper only. It can help choose `single-thread`, `sequential-plan`, or `parallel-subagents`; it does not decide truth, evidence, citations, approvals, vendor trust, or test sufficiency.
- **Host-repo boundary**: domain-specific user instructions, repository `AGENTS.md`, local scripts, audit requirements, and source-of-truth rules win over plugin guidance. When host repository rules are stricter, host repository rules win.
- **Hook boundary**: the hook only injects guidance. It does not enforce truth, validate sources, authorize edits, satisfy citations, replace tests, or bypass safety/privacy/vendor/approval rules.
- **Installer boundary**: the user installer never writes `CODEX_HOME/config.toml` or `CODEX_HOME/AGENTS.md`. It stages skills and a dormant hook only.

## Default install: skills plus dormant hook

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
- hook script to `CODEX_HOME/hooks` (`~/.codex/hooks` by default).

The default install does **not** activate the always-on prompt gate. It does not patch `CODEX_HOME/config.toml`, does not append `CODEX_HOME/AGENTS.md`, does not copy custom agents, and does not register plugin packaging. The staged hook file is dormant unless config explicitly points at it.

`--with-hook` (`-WithHook` in PowerShell) is accepted as an explicit spelling of the default hook staging behavior.

Preview the install without writing files:

```bash
./install.sh --dry-run
```

PowerShell:

```powershell
./install.ps1 -DryRun
```

## Strict skill-only install

Use this when you do not want even a dormant hook file copied:

```bash
./install.sh --skills-only
```

PowerShell:

```powershell
./install.ps1 -SkillsOnly
```

## Manual hook activation

The `UserPromptSubmit` hook is broad behavior: once registered, it runs for every prompt using that `CODEX_HOME`. Enable it deliberately by manually merging one of `snippets/config.hooks.*.toml` into your config.

The installer will not write this block for you:

```toml
[features]
codex_hooks = true

[[hooks.UserPromptSubmit]]
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = "<your-python> <your-home>/.codex/hooks/subagent_orchestration_gate.py"
timeout = 5
```

Manual activation only; the install script does not patch config.

## Manual invocation

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

Copy them manually into `~/.codex/agents` or `.codex/agents` only when you want these custom agent profiles available.

## Smoke test the hook

```bash
python3 tests/test_hook.py
```

Expected:

- debugging prompt => `use-subagent-orchestrator`,
- rename prompt => silent hook output,
- user opt-out => `skip`,
- child-agent prompt => `skip recursive`.

## Safety notes

- Keep `max_depth = 1` if you manually merge `snippets/config.subagents.toml`.
- Prefer read-only subagents first.
- Do not let multiple agents edit the same files unless they are in isolated worktrees.
- Treat the hook as a quiet hint, not an enforcement boundary.
- Respect user opt-outs.
- Repository-specific `AGENTS.md` files and source-of-truth project rules remain higher authority than this global guidance.
- Do not make this kit compete with Superpowers, Recursive Mode, or other orchestration/routing/bootstrap systems.
