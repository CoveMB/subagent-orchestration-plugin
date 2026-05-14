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


def load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def run_grader(prompts: Path, traces: Path) -> dict[str, object]:
    proc = subprocess.run(
        [sys.executable, str(GRADER), "--prompts", str(prompts), "--traces", str(traces)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert proc.returncode in {0, 1}, proc.stderr + proc.stdout
    return json.loads(proc.stdout)


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


def spawn_event() -> dict[str, object]:
    return {
        "type": "item.started",
        "item": {
            "type": "function_call",
            "name": "spawn_agent",
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
        assert isinstance(case.get("prompt"), str) and case["prompt"].strip(), case
        assert isinstance(case.get("rubric_ids"), list) and case["rubric_ids"], case


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
