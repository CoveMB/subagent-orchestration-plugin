#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "subagent_orchestration_gate.py"
PLUGIN_ROOT = ROOT / "plugin" / "subagent-orchestrator"
PLUGIN_MANIFEST = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"
SKILLS_ROOT = PLUGIN_ROOT / "skills"
ORCHESTRATOR_SKILL = SKILLS_ROOT / "subagent-orchestrator" / "SKILL.md"
USING_ORCHESTRATOR_SKILL = SKILLS_ROOT / "using-subagent-orchestrator" / "SKILL.md"
EXPECTED_SKILL_NAMES = {"subagent-orchestrator", "using-subagent-orchestrator"}
SKILL_FORWARD_SCENARIOS = [
    (
        "simple direct question",
        ORCHESTRATOR_SKILL,
        "What does this repository do?",
        [
            "`single-thread`",
            "the user asks a simple direct question",
            "parallelism would add more overhead than value",
        ],
    ),
    (
        "strictly sequential task",
        ORCHESTRATOR_SKILL,
        "Apply each migration step only after the previous step succeeds.",
        [
            "`sequential-plan`",
            "strictly sequential",
            "do not spawn subagents yet",
        ],
    ),
    (
        "debugging with separable tracks",
        ORCHESTRATOR_SKILL,
        "Debug a flaky multi-file auth regression and propose tests.",
        [
            "### debugging",
            "`so_mapper`",
            "`so_reproducer`",
            "`so_tester`",
            "`so_reviewer`",
            "observed failure mode",
            "likely root cause",
        ],
    ),
    (
        "branch review",
        ORCHESTRATOR_SKILL,
        "Review this branch for correctness, security, and missing tests.",
        [
            "### pr/branch review",
            "`so_mapper`",
            "`so_reviewer`",
            "`so_tester`",
            "real issues only",
        ],
    ),
    (
        "opt-out compatibility gate",
        USING_ORCHESTRATOR_SKILL,
        "No subagents. Review this patch linearly.",
        [
            "`skip` for tiny edits",
            "explicit user opt-out",
            "respect explicit user opt-outs",
        ],
    ),
    (
        "complex compatibility gate",
        USING_ORCHESTRATOR_SKILL,
        "Investigate failing API and web tests across modules.",
        [
            "`use-subagent-orchestrator` for complex debugging",
            "load and follow the `subagent-orchestrator` skill",
            "actual spawning is required",
        ],
    ),
]


def run_hook_context(prompt: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"prompt": prompt}),
        text=True,
        capture_output=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    return data["hookSpecificOutput"]["additionalContext"]


def assert_text_contains_all(text: str, required_terms: list[str], source: Path | str) -> None:
    missing_terms = [term for term in required_terms if term not in text]
    assert not missing_terms, (source, missing_terms)


def parse_skill_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    assert lines[0] == "---", path
    end_index = lines[1:].index("---") + 1
    frontmatter: dict[str, str] = {}
    for line in lines[1:end_index]:
        key, separator, value = line.partition(":")
        assert separator == ":", (path, line)
        frontmatter[key.strip()] = value.strip()
    return frontmatter


def test_skill_frontmatter_is_valid_and_discoverable() -> None:
    skill_paths = sorted(SKILLS_ROOT.glob("*/SKILL.md"))
    assert {path.parent.name for path in skill_paths} == EXPECTED_SKILL_NAMES

    for path in skill_paths:
        frontmatter = parse_skill_frontmatter(path)
        assert set(frontmatter) == {"name", "description"}, (path, frontmatter)
        assert frontmatter["name"] == path.parent.name, path
        assert len(frontmatter["description"]) >= 80, path
        assert "use" in frontmatter["description"].lower(), path


def test_plugin_manifest_skill_path_matches_skill_folders() -> None:
    manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    skills_path = PLUGIN_ROOT / manifest["skills"]
    assert skills_path.resolve() == SKILLS_ROOT.resolve()
    assert {path.name for path in skills_path.iterdir() if (path / "SKILL.md").exists()} == EXPECTED_SKILL_NAMES


def test_plugin_interface_respects_optional_helper_boundary() -> None:
    manifest = json.loads(PLUGIN_MANIFEST.read_text(encoding="utf-8"))
    interface = manifest["interface"]
    searchable_text = " ".join([
        manifest["description"],
        interface["shortDescription"],
        interface["longDescription"],
        *interface["defaultPrompt"],
    ]).lower()

    assert "optional" in searchable_text
    assert "evaluate every prompt" not in searchable_text
    assert "gate first" not in searchable_text
    assert "before work begins" not in searchable_text


def test_orchestrator_skill_has_execution_runbook() -> None:
    text = ORCHESTRATOR_SKILL.read_text(encoding="utf-8")
    assert_text_contains_all(
        text,
        [
            "## Execution Runbook",
            "### Spawn Template",
            "### Agent Task Templates",
            "### Fallback When Custom Agents Are Unavailable",
        ],
        ORCHESTRATOR_SKILL,
    )


def test_skills_define_decision_taxonomy_and_avoidance_contracts() -> None:
    orchestrator_text = ORCHESTRATOR_SKILL.read_text(encoding="utf-8").lower()
    using_text = USING_ORCHESTRATOR_SKILL.read_text(encoding="utf-8").lower()

    assert_text_contains_all(
        orchestrator_text,
        [
            "`single-thread`",
            "`sequential-plan`",
            "`parallel-subagents`",
            "spawn subagents when at least two are true",
            "avoid subagents when any are true",
            "the user asks a simple direct question",
            "the edit is tiny and obvious",
            "agents would compete to mutate the same files",
        ],
        ORCHESTRATOR_SKILL,
    )
    assert_text_contains_all(
        using_text,
        [
            "orchestration gate: skip | check | use-subagent-orchestrator",
            "`skip` for tiny edits",
            "`check` for moderate uncertainty",
            "`use-subagent-orchestrator` for complex debugging",
        ],
        USING_ORCHESTRATOR_SKILL,
    )


def test_skills_define_priority_and_negative_contracts() -> None:
    for path in [ORCHESTRATOR_SKILL, USING_ORCHESTRATOR_SKILL]:
        text = path.read_text(encoding="utf-8").lower()
        assert_text_contains_all(
            text,
            [
                "existing orchestration, routing, bootstrap, skill-selection, and agent-management frameworks take priority",
                "host repository rules win",
                "do not ask the user whether orchestration is preferable",
                "do not recursively",
                "subagent output is a work product",
            ],
            path,
        )


def test_orchestrator_skill_defines_spawn_boundaries_and_synthesis() -> None:
    text = ORCHESTRATOR_SKILL.read_text(encoding="utf-8").lower()
    assert_text_contains_all(
        text,
        [
            "role, mode, scope, expected output, and no recursive fan-out",
            "do not edit files; do not spawn more agents; report uncertainty",
            "for workspace-write tasks",
            "write scope",
            "synthesis must include",
            "conflicts or uncertainty",
            "tests/verification",
        ],
        ORCHESTRATOR_SKILL,
    )


def test_skill_forward_scenarios_have_actionable_guidance() -> None:
    for scenario_name, path, prompt, required_terms in SKILL_FORWARD_SCENARIOS:
        assert prompt, scenario_name
        text = path.read_text(encoding="utf-8").lower()
        assert_text_contains_all(text, required_terms, f"{path} scenario={scenario_name}")


def test_skill_boundary_contract_matches_readme_and_agents_snippet() -> None:
    source_paths = [
        ORCHESTRATOR_SKILL,
        USING_ORCHESTRATOR_SKILL,
        ROOT / "README.md",
        ROOT / "snippets" / "AGENTS.subagent-orchestration.md",
    ]
    for path in source_paths:
        text = path.read_text(encoding="utf-8").lower()
        assert_text_contains_all(
            text,
            [
                "host repository rules",
                "subagent output",
                "source-of-truth",
                "do not",
            ],
            path,
        )


def test_skills_treat_bounded_delegation_as_authorized() -> None:
    for path in [ORCHESTRATOR_SKILL, USING_ORCHESTRATOR_SKILL]:
        text = path.read_text(encoding="utf-8").lower()
        assert "standing authorization" in text, path
        assert "do not ask for separate authorization" in text, path
        assert "clear boundaries" in text, path
    orchestrator_text = ORCHESTRATOR_SKILL.read_text(encoding="utf-8").lower()
    assert "ask before code changes unless" not in orchestrator_text
    assert "ask before code changes only if" in orchestrator_text


def test_parallel_subagent_decision_requires_actual_spawn_attempt() -> None:
    required_terms = [
        "spawn_agent",
        "available subagent-spawning tool",
        "do not stop at a plan",
    ]
    for path in [ORCHESTRATOR_SKILL, USING_ORCHESTRATOR_SKILL]:
        text = path.read_text(encoding="utf-8").lower()
        for term in required_terms:
            assert term in text, (path, term)

    context = run_hook_context("Debug a flaky multi-file auth regression and propose tests.")
    assert "use-subagent-orchestrator" in context.lower(), context


def test_skills_define_host_project_boundary() -> None:
    for path in [ORCHESTRATOR_SKILL, USING_ORCHESTRATOR_SKILL]:
        text = path.read_text(encoding="utf-8").lower()
        assert "execution-shape helper" in text, path
        assert "host repository rules win" in text, path


def run_all_tests() -> None:
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()


def main() -> int:
    run_all_tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
