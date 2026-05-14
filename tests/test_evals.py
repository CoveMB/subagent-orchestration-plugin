#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALS_ROOT = ROOT / "evals"
PROMPTS = EVALS_ROOT / "skill_prompts.jsonl"
GRADER = ROOT / "scripts" / "grade_skill_traces.py"
HOOK = ROOT / "hooks" / "subagent_orchestration_gate.py"
EXPECTED_DECISIONS = {
    "single-thread-default",
    "single-thread-likely",
    "orchestration-check",
    "use-subagent-orchestrator",
    "orchestration-opt-out",
    "recursion-guard",
}
REQUIRED_PROMPT_KEYS = {
    "id",
    "prompt",
    "expected_decision",
    "should_spawn",
    "must_not_spawn",
    "rubric_ids",
}
ALLOWED_PROMPT_KEYS = REQUIRED_PROMPT_KEYS | {
    "forbidden_command_terms",
    "host_rules_fixture",
    "max_command_count",
    "max_spawn_count",
    "expected_spawn_agents",
    "forbidden_tool_names",
    "requires_wait",
    "required_final_text_terms",
}


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def run_grader(prompts: Path, traces: Path, extra_args: list[str] | None = None) -> dict[str, object]:
    proc = subprocess.run(
        [sys.executable, str(GRADER), "--prompts", str(prompts), "--traces", str(traces), *(extra_args or [])],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode in {0, 1}, proc.stderr + proc.stdout
    return json.loads(proc.stdout)


def run_grader_process(prompts: Path, traces: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GRADER), "--prompts", str(prompts), "--traces", str(traces)],
        text=True,
        capture_output=True,
        check=False,
    )


def run_hook(prompt: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"prompt": prompt}),
        text=True,
        capture_output=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    return data["hookSpecificOutput"]["additionalContext"]


def hook_decision(prompt: str) -> str:
    context = run_hook(prompt)
    for line in context.splitlines():
        if line.startswith("Result: "):
            return line.removeprefix("Result: ")
    raise AssertionError(context)


def message_event(text: str) -> dict[str, object]:
    return {
        "type": "item.completed",
        "item": {
            "type": "message",
            "content": [{"type": "output_text", "text": text}],
        },
    }


def spawn_event(agent_type: str = "so_mapper") -> dict[str, object]:
    return {
        "type": "item.started",
        "item": {
            "type": "function_call",
            "name": "spawn_agent",
            "arguments": {"agent_type": agent_type},
        },
    }


def wait_event() -> dict[str, object]:
    return {
        "type": "item.started",
        "item": {
            "type": "function_call",
            "name": "wait_agent",
        },
    }


def command_event(command: str) -> dict[str, object]:
    return {
        "type": "item.completed",
        "item": {
            "type": "command_execution",
            "command": command,
        },
    }


def test_eval_prompt_set_is_balanced_and_explicit() -> None:
    cases = load_jsonl(PROMPTS)
    ids = [case["id"] for case in cases]
    decisions = {case["expected_decision"] for case in cases}

    assert len(cases) >= 12
    assert len(ids) == len(set(ids))
    assert EXPECTED_DECISIONS <= decisions
    assert any(case.get("should_spawn") is True for case in cases)
    assert any(case.get("must_not_spawn") is True for case in cases)
    assert any(case.get("host_rules_fixture") for case in cases)

    for case in cases:
        unknown_keys = set(case) - ALLOWED_PROMPT_KEYS
        missing_keys = REQUIRED_PROMPT_KEYS - set(case)
        assert not unknown_keys, case
        assert not missing_keys, case
        assert isinstance(case.get("prompt"), str) and case["prompt"].strip(), case
        assert case["expected_decision"] in EXPECTED_DECISIONS, case
        assert isinstance(case.get("should_spawn"), bool), case
        assert isinstance(case.get("must_not_spawn"), bool), case
        assert not (case["should_spawn"] and case["must_not_spawn"]), case
        assert isinstance(case.get("rubric_ids"), list) and case["rubric_ids"], case
        assert all(isinstance(rubric_id, str) and rubric_id for rubric_id in case["rubric_ids"]), case


def test_grader_rejects_invalid_prompt_rows() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        traces.mkdir()
        write_jsonl(
            prompts,
            [
                {
                    "id": "broken",
                    "prompt": "Debug this failure.",
                    "expected_decision": "not-a-decision",
                    "should_spawn": True,
                    "must_not_spawn": True,
                    "max_command_count": True,
                    "rubric_ids": ["decision"],
                    "extra": "ignored today",
                },
            ],
        )

        proc = run_grader_process(prompts, traces)

    assert proc.returncode == 2
    assert "invalid prompt corpus" in proc.stderr
    assert "unknown keys" in proc.stderr
    assert "invalid expected_decision" in proc.stderr
    assert "max_command_count must be a non-negative integer" in proc.stderr
    assert "should_spawn and must_not_spawn cannot both be true" in proc.stderr


def test_parallel_eval_cases_define_trace_contracts() -> None:
    for case in load_jsonl(PROMPTS):
        if case.get("should_spawn") is not True:
            continue
        assert isinstance(case.get("expected_spawn_agents"), list) and case["expected_spawn_agents"], case
        assert case.get("requires_wait") is True, case
        assert isinstance(case.get("required_final_text_terms"), list), case
        assert "Synthesis:" in case["required_final_text_terms"], case


def test_eval_prompt_set_matches_hook_classifier() -> None:
    for case in load_jsonl(PROMPTS):
        assert hook_decision(str(case["prompt"])) == case["expected_decision"], case


def test_eval_grader_scores_synthetic_traces() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        traces.mkdir()
        write_jsonl(
            prompts,
            [
                {
                    "id": "parallel-debug",
                    "prompt": "Debug a flaky regression across API and web tests.",
                    "expected_decision": "use-subagent-orchestrator",
                    "should_spawn": True,
                    "must_not_spawn": False,
                    "expected_spawn_agents": ["so_mapper"],
                    "requires_wait": True,
                    "required_final_text_terms": ["Synthesis:", "Tests/verification:"],
                    "rubric_ids": ["decision", "spawn"],
                },
                {
                    "id": "simple-rename",
                    "prompt": "Rename a local variable in one file.",
                    "expected_decision": "single-thread-likely",
                    "should_spawn": False,
                    "must_not_spawn": True,
                    "rubric_ids": ["decision", "no_spawn"],
                },
            ],
        )
        write_jsonl(
            traces / "parallel-debug.jsonl",
            [
                message_event("Subagent orchestration gate\nResult: use-subagent-orchestrator\nReason: Strong orchestration signals detected."),
                spawn_event(),
                wait_event(),
                message_event("Synthesis:\n- Tests/verification: run targeted checks."),
            ],
        )
        write_jsonl(
            traces / "simple-rename.jsonl",
            [
                message_event("Subagent orchestration gate\nResult: single-thread-likely\nReason: Simple-task signals detected."),
            ],
        )

        result = run_grader(prompts, traces)

    assert result["overall_pass"] is True
    assert result["summary"] == {"passed": 2, "failed": 0, "missing": 0}


def test_eval_grader_fails_missing_required_wait_after_spawn() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        traces.mkdir()
        write_jsonl(
            prompts,
            [
                {
                    "id": "parallel-debug",
                    "prompt": "Debug a flaky regression across API and web tests.",
                    "expected_decision": "use-subagent-orchestrator",
                    "should_spawn": True,
                    "must_not_spawn": False,
                    "expected_spawn_agents": ["so_mapper"],
                    "requires_wait": True,
                    "rubric_ids": ["decision", "spawn", "wait"],
                },
            ],
        )
        write_jsonl(
            traces / "parallel-debug.jsonl",
            [
                message_event("Subagent orchestration gate\nResult: use-subagent-orchestrator\nReason: Strong orchestration signals detected."),
                spawn_event("so_mapper"),
            ],
        )

        result = run_grader(prompts, traces)

    assert result["overall_pass"] is False
    assert result["cases"][0]["checks"]["wait_required"] is False


def test_eval_grader_requires_wait_after_final_spawn() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        traces.mkdir()
        write_jsonl(
            prompts,
            [
                {
                    "id": "parallel-debug",
                    "prompt": "Debug a flaky regression across API and web tests.",
                    "expected_decision": "use-subagent-orchestrator",
                    "should_spawn": True,
                    "must_not_spawn": False,
                    "expected_spawn_agents": ["so_mapper", "so_tester"],
                    "requires_wait": True,
                    "rubric_ids": ["decision", "spawn", "wait"],
                },
            ],
        )
        write_jsonl(
            traces / "parallel-debug.jsonl",
            [
                message_event("Subagent orchestration gate\nResult: use-subagent-orchestrator\nReason: Strong orchestration signals detected."),
                spawn_event("so_mapper"),
                wait_event(),
                spawn_event("so_tester"),
            ],
        )

        result = run_grader(prompts, traces)

    assert result["overall_pass"] is False
    assert result["cases"][0]["checks"]["wait_required"] is False


def test_eval_grader_fails_missing_expected_spawn_agent() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        traces.mkdir()
        write_jsonl(
            prompts,
            [
                {
                    "id": "parallel-debug",
                    "prompt": "Debug a flaky regression across API and web tests.",
                    "expected_decision": "use-subagent-orchestrator",
                    "should_spawn": True,
                    "must_not_spawn": False,
                    "expected_spawn_agents": ["so_mapper", "so_tester"],
                    "rubric_ids": ["decision", "spawn_agents"],
                },
            ],
        )
        write_jsonl(
            traces / "parallel-debug.jsonl",
            [
                message_event("Subagent orchestration gate\nResult: use-subagent-orchestrator\nReason: Strong orchestration signals detected."),
                spawn_event("so_mapper"),
            ],
        )

        result = run_grader(prompts, traces)

    assert result["overall_pass"] is False
    assert result["cases"][0]["checks"]["expected_spawn_agents"] is False


def test_eval_grader_fails_missing_required_final_text() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        traces.mkdir()
        write_jsonl(
            prompts,
            [
                {
                    "id": "parallel-debug",
                    "prompt": "Debug a flaky regression across API and web tests.",
                    "expected_decision": "use-subagent-orchestrator",
                    "should_spawn": True,
                    "must_not_spawn": False,
                    "required_final_text_terms": ["Synthesis:", "Tests/verification:"],
                    "rubric_ids": ["decision", "synthesis"],
                },
            ],
        )
        write_jsonl(
            traces / "parallel-debug.jsonl",
            [
                message_event("Subagent orchestration gate\nResult: use-subagent-orchestrator\nReason: Strong orchestration signals detected."),
                spawn_event("so_mapper"),
                wait_event(),
                message_event("Done."),
            ],
        )

        result = run_grader(prompts, traces)

    assert result["overall_pass"] is False
    assert result["cases"][0]["checks"]["required_final_text"] is False


def test_eval_grader_scores_realistic_fixture_traces() -> None:
    result = run_grader(PROMPTS, EVALS_ROOT / "trace_fixtures" / "pass")
    assert result["overall_pass"] is True


def test_eval_grader_fails_realistic_negative_fixture_traces() -> None:
    result = run_grader(PROMPTS, EVALS_ROOT / "trace_fixtures" / "fail")
    assert result["overall_pass"] is False
    failed_cases = {case["id"]: case for case in result["cases"] if case["passed"] is False}
    assert failed_cases["parallel-auth-debug"]["checks"]["wait_required"] is False
    assert failed_cases["parallel-security-architecture"]["checks"]["expected_spawn_agents"] is False
    assert failed_cases["host-rules-branch-review"]["checks"]["forbidden_commands"] is False


def test_trace_eval_schema_describes_grader_output() -> None:
    schema = json.loads((EVALS_ROOT / "trace_eval.schema.json").read_text(encoding="utf-8"))
    case_schema = schema["properties"]["cases"]["items"]
    case_properties = case_schema["properties"]
    check_properties = case_properties["checks"]["properties"]

    assert "command_count" in case_properties
    assert "spawn_count" in case_properties
    assert "spawned_agents" in case_properties
    assert case_properties["checks"]["additionalProperties"] is False
    for check_name in [
        "trace_exists",
        "decision",
        "spawn_required",
        "no_unwanted_spawn",
        "expected_spawn_agents",
        "forbidden_tool_names",
        "forbidden_commands",
        "command_budget",
        "spawn_budget",
        "wait_required",
        "required_final_text",
    ]:
        assert check_properties[check_name]["type"] == "boolean"


def test_eval_grader_fails_missing_required_spawn() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        traces.mkdir()
        write_jsonl(
            prompts,
            [
                {
                    "id": "parallel-debug",
                    "prompt": "Debug a flaky regression across API and web tests.",
                    "expected_decision": "use-subagent-orchestrator",
                    "should_spawn": True,
                    "must_not_spawn": False,
                    "rubric_ids": ["decision", "spawn"],
                },
            ],
        )
        write_jsonl(
            traces / "parallel-debug.jsonl",
            [
                message_event("Subagent orchestration gate\nResult: use-subagent-orchestrator\nReason: Strong orchestration signals detected."),
            ],
        )

        result = run_grader(prompts, traces)

    assert result["overall_pass"] is False
    assert result["summary"] == {"passed": 0, "failed": 1, "missing": 0}
    assert result["cases"][0]["checks"]["spawn_required"] is False


def test_eval_grader_fails_forbidden_external_command() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        traces.mkdir()
        write_jsonl(
            prompts,
            [
                {
                    "id": "host-rules-review",
                    "prompt": "Review branch without responding to GitHub comments.",
                    "expected_decision": "orchestration-check",
                    "should_spawn": False,
                    "must_not_spawn": True,
                    "forbidden_command_terms": ["gh pr comment"],
                    "rubric_ids": ["decision", "no_external_side_effects"],
                },
            ],
        )
        write_jsonl(
            traces / "host-rules-review.jsonl",
            [
                message_event("Subagent orchestration gate\nResult: orchestration-check\nReason: Moderate orchestration signals detected."),
                command_event("gh pr comment 123 --body reviewed"),
            ],
        )

        result = run_grader(prompts, traces)

    assert result["overall_pass"] is False
    assert result["cases"][0]["checks"]["forbidden_commands"] is False


def test_eval_grader_fails_command_budget_regression() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        traces.mkdir()
        write_jsonl(
            prompts,
            [
                {
                    "id": "simple-question",
                    "prompt": "What does this repository do?",
                    "expected_decision": "single-thread-likely",
                    "should_spawn": False,
                    "must_not_spawn": True,
                    "max_command_count": 0,
                    "rubric_ids": ["decision", "efficiency"],
                },
            ],
        )
        write_jsonl(
            traces / "simple-question.jsonl",
            [
                message_event("Subagent orchestration gate\nResult: single-thread-likely\nReason: Simple-task signals detected."),
                command_event("rg --files"),
            ],
        )

        result = run_grader(prompts, traces)

    assert result["overall_pass"] is False
    assert result["cases"][0]["checks"]["command_budget"] is False


def test_eval_grader_counts_command_start_and_completion_once() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        traces.mkdir()
        write_jsonl(
            prompts,
            [
                {
                    "id": "simple-question",
                    "prompt": "What does this repository do?",
                    "expected_decision": "single-thread-likely",
                    "should_spawn": False,
                    "must_not_spawn": True,
                    "max_command_count": 1,
                    "rubric_ids": ["decision", "efficiency"],
                },
            ],
        )
        write_jsonl(
            traces / "simple-question.jsonl",
            [
                message_event("Subagent orchestration gate\nResult: single-thread-likely\nReason: Simple-task signals detected."),
                {
                    "type": "item.started",
                    "item": {"id": "item_1", "type": "command_execution", "command": "rg --files"},
                },
                {
                    "type": "item.completed",
                    "item": {"id": "item_1", "type": "command_execution", "command": "rg --files"},
                },
            ],
        )

        result = run_grader(prompts, traces)

    assert result["overall_pass"] is True
    assert result["cases"][0]["checks"]["command_budget"] is True
    assert result["cases"][0]["command_count"] == 1


def test_eval_grader_live_profile_records_but_does_not_enforce_command_budget() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        traces.mkdir()
        write_jsonl(
            prompts,
            [
                {
                    "id": "simple-question",
                    "prompt": "What does this repository do?",
                    "expected_decision": "single-thread-likely",
                    "should_spawn": False,
                    "must_not_spawn": True,
                    "max_command_count": 0,
                    "rubric_ids": ["decision", "efficiency"],
                },
            ],
        )
        write_jsonl(
            traces / "simple-question.jsonl",
            [
                message_event("Subagent orchestration gate\nResult: single-thread-likely\nReason: Simple-task signals detected."),
                command_event("rg --files"),
            ],
        )

        result = run_grader(prompts, traces, ["--profile", "live"])

    assert result["overall_pass"] is True
    assert result["cases"][0]["checks"]["command_budget"] is True
    assert result["cases"][0]["command_count"] == 1


def test_eval_grader_is_offline_and_does_not_execute_agent_runs() -> None:
    text = GRADER.read_text(encoding="utf-8")
    assert "subprocess" not in text
    assert "codex exec" not in text


def run_all_tests() -> None:
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()


def main() -> int:
    run_all_tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
