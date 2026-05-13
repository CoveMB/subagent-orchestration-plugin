#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "subagent_orchestration_gate.py"
INSTALLER = ROOT / "scripts" / "install_user.py"
UNINSTALLER = ROOT / "scripts" / "uninstall_user.py"
ORCHESTRATOR_SKILL = ROOT / "plugin" / "subagent-orchestrator" / "skills" / "subagent-orchestrator" / "SKILL.md"
USING_ORCHESTRATOR_SKILL = ROOT / "plugin" / "subagent-orchestrator" / "skills" / "using-subagent-orchestrator" / "SKILL.md"
BOUNDARY_SENTENCE = (
    "Respect all active user and repository instructions. This orchestration gate only affects execution shape; "
    "it does not override source-of-truth, citation, manuscript, safety, privacy, vendor, approval, or testing rules."
)


def run_payload(prompt: str) -> dict[str, object]:
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"prompt": prompt}),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(proc.stdout)


def run(prompt: str) -> str | None:
    data = run_payload(prompt)
    hook_output = data.get("hookSpecificOutput", {})
    assert isinstance(hook_output, dict), data
    return hook_output.get("additionalContext")


def run_installer(arguments: list[str], home: Path, app_home: Path) -> subprocess.CompletedProcess[str]:
    return run_user_script(INSTALLER, arguments, home, app_home)


def run_uninstaller(arguments: list[str], home: Path, app_home: Path) -> subprocess.CompletedProcess[str]:
    return run_user_script(UNINSTALLER, arguments, home, app_home)


def run_user_script(script: Path, arguments: list[str], home: Path, app_home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    env["CODEX_HOME"] = str(app_home)
    return subprocess.run(
        [sys.executable, "-B", str(script), *arguments],
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def assert_installer_ok(proc: subprocess.CompletedProcess[str]) -> None:
    assert proc.returncode == 0, proc.stderr + proc.stdout


def skill_path(home: Path, name: str) -> Path:
    return home / ".agents" / "skills" / name


def hook_path(app_home: Path) -> Path:
    return app_home / "hooks" / "subagent_orchestration_gate.py"


def config_path(app_home: Path) -> Path:
    return app_home / "config.toml"


def global_agents_path(app_home: Path) -> Path:
    return app_home / "AGENTS.md"


def plugin_path(app_home: Path) -> Path:
    return app_home / "plugins" / "subagent-orchestrator"


def marketplace_path(home: Path) -> Path:
    return home / ".agents" / "plugins" / "marketplace.json"


def custom_agent_paths(app_home: Path) -> list[Path]:
    return sorted((app_home / "agents").glob("so_*.toml"))


def assert_skills_installed(home: Path) -> None:
    assert (skill_path(home, "subagent-orchestrator") / "SKILL.md").exists()
    assert (skill_path(home, "using-subagent-orchestrator") / "SKILL.md").exists()


def test_default_install_stages_skills_and_hook_without_activation() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        home = root / "home"
        app_home = root / "app"
        proc = run_installer([], home, app_home)
        assert_installer_ok(proc)
        assert_skills_installed(home)
        assert hook_path(app_home).exists()
        assert not config_path(app_home).exists()
        assert not global_agents_path(app_home).exists()
        assert not custom_agent_paths(app_home)
        assert not plugin_path(app_home).exists()
        assert not marketplace_path(home).exists()


def test_skills_only_skips_hook_and_activation_files() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        home = root / "home"
        app_home = root / "app"
        proc = run_installer(["--skills-only"], home, app_home)
        assert_installer_ok(proc)
        assert_skills_installed(home)
        assert not hook_path(app_home).exists()
        assert not config_path(app_home).exists()
        assert not global_agents_path(app_home).exists()
        assert not custom_agent_paths(app_home)
        assert not plugin_path(app_home).exists()


def test_config_patch_flags_are_rejected_without_touching_config() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        home = root / "home"
        app_home = root / "app"
        app_home.mkdir(parents=True)
        config = config_path(app_home)
        config.write_text("[features]\nexisting = true\n", encoding="utf-8")

        for flag in ["--patch-config", "--activate-gate"]:
            proc = run_installer([flag], home, app_home)
            assert proc.returncode != 0, proc.stdout
            assert "unrecognized arguments" in proc.stderr
            assert config.read_text(encoding="utf-8") == "[features]\nexisting = true\n"
            assert not hook_path(app_home).exists()


def test_with_hook_installs_hook_without_config_patch() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        home = root / "home"
        app_home = root / "app"
        proc = run_installer(["--with-hook"], home, app_home)
        assert_installer_ok(proc)
        assert_skills_installed(home)
        assert hook_path(app_home).exists()
        assert not config_path(app_home).exists()


def test_custom_agent_flag_is_not_part_of_user_installer() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        home = root / "home"
        app_home = root / "app"
        proc = run_installer(["--with-agents"], home, app_home)
        assert proc.returncode != 0, proc.stdout
        assert "unrecognized arguments" in proc.stderr
        assert not custom_agent_paths(app_home)


def test_global_agents_flag_is_not_part_of_user_installer() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        home = root / "home"
        app_home = root / "app"
        proc = run_installer(["--with-global-agents-md"], home, app_home)
        assert proc.returncode != 0, proc.stdout
        assert "unrecognized arguments" in proc.stderr
        assert not global_agents_path(app_home).exists()


def test_plugin_flag_is_not_part_of_user_installer() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        home = root / "home"
        app_home = root / "app"
        proc = run_installer(["--plugin"], home, app_home)
        assert proc.returncode != 0, proc.stdout
        assert "unrecognized arguments" in proc.stderr
        assert not plugin_path(app_home).exists()
        assert not marketplace_path(home).exists()
        assert not config_path(app_home).exists()


def test_dry_run_changes_nothing() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        home = root / "home"
        app_home = root / "app"
        proc = run_installer(["--dry-run"], home, app_home)
        assert_installer_ok(proc)
        assert "would install skill" in proc.stdout
        assert not home.exists()
        assert not app_home.exists()


def test_default_install_preserves_existing_config() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        home = root / "home"
        app_home = root / "app"
        app_home.mkdir(parents=True)
        config = app_home / "config.toml"
        config.write_text("[agents]\nmax_threads_backup = 99\n", encoding="utf-8")
        proc = run_installer([], home, app_home)
        assert_installer_ok(proc)
        assert config.read_text(encoding="utf-8") == "[agents]\nmax_threads_backup = 99\n"
        assert not config.with_suffix(".toml.bak").exists()


def test_uninstall_removes_owned_config_guidance_and_marketplace() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        home = root / "home"
        app_home = root / "app"
        install_proc = run_installer([], home, app_home)
        assert_installer_ok(install_proc)

        config = app_home / "config.toml"
        config.write_text(
            "[[hooks.UserPromptSubmit]]\n"
            "[[hooks.UserPromptSubmit.hooks]]\n"
            "type = \"command\"\n"
            "command = \"python3 ~/.codex/hooks/subagent_orchestration_gate.py\"\n"
            "timeout = 5\n",
            encoding="utf-8",
        )
        agents_file = app_home / "AGENTS.md"
        agents_file.write_text(
            (ROOT / "snippets" / "AGENTS.subagent-orchestration.md").read_text(encoding="utf-8").strip() + "\n",
            encoding="utf-8",
        )
        agents_dir = app_home / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "so_mapper.toml").write_text("name = \"so_mapper\"\n", encoding="utf-8")
        marketplace_file = marketplace_path(home)
        marketplace_file.parent.mkdir(parents=True)
        marketplace_file.write_text(
            json.dumps(
                {
                    "plugins": [
                        {"name": "subagent-orchestrator"},
                        {"name": "other-plugin"},
                    ]
                }
            )
            + "\n",
            encoding="utf-8",
        )

        uninstall_proc = run_uninstaller([], home, app_home)
        assert_installer_ok(uninstall_proc)
        config_text = (app_home / "config.toml").read_text(encoding="utf-8")
        agents_text = (app_home / "AGENTS.md").read_text(encoding="utf-8")
        marketplace = json.loads((home / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8"))
        assert "subagent_orchestration_gate.py" not in config_text
        assert "Subagent orchestration gate" not in agents_text
        assert all(plugin.get("name") != "subagent-orchestrator" for plugin in marketplace["plugins"])
        assert not list((app_home / "agents").glob("so_*.toml"))


def test_orchestrator_skill_has_execution_runbook() -> None:
    text = ORCHESTRATOR_SKILL.read_text(encoding="utf-8")
    required_sections = [
        "## Execution Runbook",
        "### Spawn Template",
        "### Agent Task Templates",
        "### Fallback When Custom Agents Are Unavailable",
    ]
    missing_sections = [section for section in required_sections if section not in text]
    assert not missing_sections, missing_sections


def test_skills_treat_bounded_delegation_as_authorized() -> None:
    for path in [ORCHESTRATOR_SKILL, USING_ORCHESTRATOR_SKILL]:
        text = path.read_text(encoding="utf-8").lower()
        assert "standing authorization" in text, path
        assert "do not ask for separate authorization" in text, path
        assert "clear boundaries" in text, path
    orchestrator_text = ORCHESTRATOR_SKILL.read_text(encoding="utf-8").lower()
    assert "ask before code changes unless" not in orchestrator_text
    assert "ask before code changes only if" in orchestrator_text


def test_skills_define_host_project_boundary() -> None:
    for path in [ORCHESTRATOR_SKILL, USING_ORCHESTRATOR_SKILL]:
        text = path.read_text(encoding="utf-8").lower()
        assert "execution-shape helper" in text, path
        assert "host repository rules win" in text, path


def test_classifier_respects_opt_out_variants() -> None:
    cases = [
        "Don't orchestrate. Debug the flaky auth regression.",
        "Dont use subagents. Review this patch.",
        "Do not use orchestration. Audit security risk.",
    ]
    for prompt in cases:
        context = run(prompt)
        assert context is not None, prompt
        assert "skip" in context.lower(), (prompt, context)


def test_classifier_preserves_conditional_orchestration() -> None:
    context = run("Review the branch. No subagent orchestration unless useful.")
    assert context is not None, context
    assert "check" in context.lower(), context
    assert BOUNDARY_SENTENCE in context
    assert "do not ask the user whether orchestration is preferable" in context.lower()
    assert "do not ask for separate authorization before bounded delegation" in context.lower()
    assert "decide internally" in context.lower()
    assert "do not override any existing orchestration, routing, bootstrap, skill-selection, or agent-management framework" in context.lower()
    assert "complement or fallback" in context.lower()


def test_classifier_detects_broad_investigations() -> None:
    cases = [
        "Find why checkout fails across frontend and backend and propose a fix.",
        "Investigate the CI failure spanning API and web tests.",
    ]
    for prompt in cases:
        context = run(prompt)
        assert context is not None, prompt
        assert "use-subagent-orchestrator" in context.lower(), (prompt, context)
        assert BOUNDARY_SENTENCE in context
        assert "prefer single-thread or sequential-plan" in context.lower(), context
        assert "bounded independent parallel tracks" in context.lower(), context
        assert "standing authorization" in context.lower(), context


def test_classifier_stays_silent_for_default_and_simple_prompts() -> None:
    cases = [
        "What does this repository do?",
        "Rename this variable in one file.",
        "Draft a short note for the changelog.",
    ]
    for prompt in cases:
        data = run_payload(prompt)
        hook_output = data.get("hookSpecificOutput", {})
        assert isinstance(hook_output, dict), data
        assert "additionalContext" not in hook_output, (prompt, data)


def test_classifier_guards_custom_agent_prompts() -> None:
    cases = [
        "You are so_mapper. Review src/auth.ts and return findings.",
        "Bounded subagent task for so_reviewer: audit this patch.",
    ]
    for prompt in cases:
        context = run(prompt)
        assert context is not None, prompt
        assert "skip recursive" in context.lower(), (prompt, context)


def test_toml_snippets_parse() -> None:
    for path in sorted((ROOT / "snippets").glob("*.toml")):
        tomllib.loads(path.read_text(encoding="utf-8"))


def test_hook_config_snippets_stay_quiet() -> None:
    for path in sorted((ROOT / "snippets").glob("config.hooks.*.toml")):
        assert "statusMessage" not in path.read_text(encoding="utf-8"), path


def test_json_files_parse() -> None:
    for path in sorted(ROOT.rglob("*.json")):
        if ".git" not in path.parts:
            json.loads(path.read_text(encoding="utf-8"))


def test_custom_agent_configs_are_valid() -> None:
    required_keys = {"name", "description", "model_reasoning_effort", "sandbox_mode", "nickname_candidates", "developer_instructions"}
    for path in sorted((ROOT / "custom-agents").glob("*.toml")):
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        missing_keys = required_keys - data.keys()
        assert not missing_keys, (path, missing_keys)
        assert data["sandbox_mode"] in {"read-only", "workspace-write"}, path


def test_repo_marketplace_paths_exist() -> None:
    marketplace = json.loads((ROOT / "marketplace" / "repo-marketplace.json").read_text(encoding="utf-8"))
    for plugin in marketplace["plugins"]:
        source = plugin["source"]
        if source["source"] == "local":
            assert (ROOT / source["path"]).exists(), source["path"]


def test_testing_agents_split_read_only_and_reproducer_roles() -> None:
    tester = tomllib.loads((ROOT / "custom-agents" / "so_tester.toml").read_text(encoding="utf-8"))
    reproducer = tomllib.loads((ROOT / "custom-agents" / "so_reproducer.toml").read_text(encoding="utf-8"))
    assert tester["sandbox_mode"] == "read-only"
    assert reproducer["sandbox_mode"] == "workspace-write"


def test_implementer_agent_has_workspace_safety_contract() -> None:
    implementer = tomllib.loads((ROOT / "custom-agents" / "so_implementer.toml").read_text(encoding="utf-8"))
    instructions = implementer["developer_instructions"].lower()
    assert "do not revert unrelated edits" in instructions
    assert "write scope" in instructions


def test_gitignore_excludes_generated_files() -> None:
    patterns = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".DS_Store" in patterns
    assert "__pycache__/" in patterns


def main() -> int:
    test_default_install_stages_skills_and_hook_without_activation()
    test_skills_only_skips_hook_and_activation_files()
    test_config_patch_flags_are_rejected_without_touching_config()
    test_with_hook_installs_hook_without_config_patch()
    test_custom_agent_flag_is_not_part_of_user_installer()
    test_global_agents_flag_is_not_part_of_user_installer()
    test_plugin_flag_is_not_part_of_user_installer()
    test_dry_run_changes_nothing()
    test_default_install_preserves_existing_config()
    test_uninstall_removes_owned_config_guidance_and_marketplace()
    test_orchestrator_skill_has_execution_runbook()
    test_skills_treat_bounded_delegation_as_authorized()
    test_skills_define_host_project_boundary()
    test_classifier_respects_opt_out_variants()
    test_classifier_preserves_conditional_orchestration()
    test_classifier_detects_broad_investigations()
    test_classifier_stays_silent_for_default_and_simple_prompts()
    test_classifier_guards_custom_agent_prompts()
    test_toml_snippets_parse()
    test_hook_config_snippets_stay_quiet()
    test_json_files_parse()
    test_custom_agent_configs_are_valid()
    test_repo_marketplace_paths_exist()
    test_testing_agents_split_read_only_and_reproducer_roles()
    test_implementer_agent_has_workspace_safety_contract()
    test_gitignore_excludes_generated_files()

    cases = [
        ("Debug a flaky multi-file auth regression and propose tests.", "use-subagent-orchestrator"),
        ("Rename this variable in one file.", ""),
        ("Do not use subagents. Debug the flaky auth regression linearly.", "skip"),
        ("You are a subagent. Review src/auth.ts and return findings.", "skip recursive"),
    ]
    for prompt, expected in cases:
        context = run(prompt)
        print("PROMPT:", prompt)
        print("CONTEXT:", context.splitlines()[0] if context else "<silent>")
        if expected:
            assert context is not None, prompt
            assert expected.lower() in context.lower(), (expected, context)
        else:
            assert context is None, (prompt, context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
