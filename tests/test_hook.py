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


def run(prompt: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"prompt": prompt}),
        text=True,
        capture_output=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    return data["hookSpecificOutput"]["additionalContext"]


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


def test_default_install_activates_hook() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        proc = run_installer([], root / "home", root / "app")
        assert_installer_ok(proc)
        config = root / "app" / "config.toml"
        assert config.exists(), proc.stdout
        text = config.read_text(encoding="utf-8")
        assert "subagent_orchestration_gate.py" in text


def test_install_can_skip_config_patch() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        proc = run_installer(["--no-patch-config"], root / "home", root / "app")
        assert_installer_ok(proc)
        config = root / "app" / "config.toml"
        assert not config.exists()
        assert "config.toml not modified" in proc.stdout


def test_plugin_install_ignores_generated_files() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        proc = run_installer(["--plugin"], root / "home", root / "app")
        assert_installer_ok(proc)
        plugin_dir = root / "app" / "plugins" / "subagent-orchestrator"
        assert not list(plugin_dir.rglob(".DS_Store"))
        assert not list(plugin_dir.rglob("__pycache__"))


def test_config_patch_preserves_prefixed_keys() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        app_home = root / "app"
        app_home.mkdir(parents=True)
        config = app_home / "config.toml"
        config.write_text("[agents]\nmax_threads_backup = 99\n", encoding="utf-8")
        proc = run_installer([], root / "home", app_home)
        assert_installer_ok(proc)
        text = config.read_text(encoding="utf-8")
        assert "max_threads_backup = 99" in text
        assert "max_threads = 6" in text


def test_config_patch_ignores_hook_filename_in_comments() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        app_home = root / "app"
        app_home.mkdir(parents=True)
        config = app_home / "config.toml"
        config.write_text("# old subagent_orchestration_gate.py note\n", encoding="utf-8")
        proc = run_installer([], root / "home", app_home)
        assert_installer_ok(proc)
        text = config.read_text(encoding="utf-8")
        assert "command =" in text
        assert "subagent_orchestration_gate.py" in text


def test_uninstall_removes_owned_config_guidance_and_marketplace() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        home = root / "home"
        app_home = root / "app"
        install_proc = run_installer(["--plugin"], home, app_home)
        assert_installer_ok(install_proc)
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


def test_classifier_respects_opt_out_variants() -> None:
    cases = [
        "Don't orchestrate. Debug the flaky auth regression.",
        "Dont use subagents. Review this patch.",
        "Do not use orchestration. Audit security risk.",
    ]
    for prompt in cases:
        context = run(prompt)
        assert "skip" in context.lower(), (prompt, context)


def test_classifier_preserves_conditional_orchestration() -> None:
    context = run("Review the branch. No subagent orchestration unless useful.")
    assert "check" in context.lower(), context


def test_classifier_detects_broad_investigations() -> None:
    cases = [
        "Find why checkout fails across frontend and backend and propose a fix.",
        "Investigate the CI failure spanning API and web tests.",
    ]
    for prompt in cases:
        context = run(prompt)
        assert "use-subagent-orchestrator" in context.lower(), (prompt, context)


def test_classifier_guards_custom_agent_prompts() -> None:
    cases = [
        "You are so_mapper. Review src/auth.ts and return findings.",
        "Bounded subagent task for so_reviewer: audit this patch.",
    ]
    for prompt in cases:
        context = run(prompt)
        assert "skip recursive" in context.lower(), (prompt, context)


def test_toml_snippets_parse() -> None:
    for path in sorted((ROOT / "snippets").glob("*.toml")):
        tomllib.loads(path.read_text(encoding="utf-8"))


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
    test_default_install_activates_hook()
    test_install_can_skip_config_patch()
    test_plugin_install_ignores_generated_files()
    test_config_patch_preserves_prefixed_keys()
    test_config_patch_ignores_hook_filename_in_comments()
    test_uninstall_removes_owned_config_guidance_and_marketplace()
    test_orchestrator_skill_has_execution_runbook()
    test_classifier_respects_opt_out_variants()
    test_classifier_preserves_conditional_orchestration()
    test_classifier_detects_broad_investigations()
    test_classifier_guards_custom_agent_prompts()
    test_toml_snippets_parse()
    test_json_files_parse()
    test_custom_agent_configs_are_valid()
    test_repo_marketplace_paths_exist()
    test_testing_agents_split_read_only_and_reproducer_roles()
    test_implementer_agent_has_workspace_safety_contract()
    test_gitignore_excludes_generated_files()

    cases = [
        ("Debug a flaky multi-file auth regression and propose tests.", "use-subagent-orchestrator"),
        ("Rename this variable in one file.", "single-thread likely"),
        ("Do not use subagents. Debug the flaky auth regression linearly.", "skip"),
        ("You are a subagent. Review src/auth.ts and return findings.", "skip recursive"),
    ]
    for prompt, expected in cases:
        context = run(prompt)
        print("PROMPT:", prompt)
        print("CONTEXT:", context.splitlines()[0])
        assert expected.lower() in context.lower(), (expected, context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
