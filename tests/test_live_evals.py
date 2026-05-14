#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_RUNNER = ROOT / "scripts" / "run_live_skill_evals.py"


def write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def write_fake_codex(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from __future__ import annotations",
                "import json",
                "import sys",
                "prompt = sys.argv[-1]",
                "decision = 'single-thread-likely' if 'repository' in prompt else 'single-thread-default'",
                "event = {",
                "    'type': 'item.completed',",
                "    'item': {",
                "        'type': 'message',",
                "        'content': [{'type': 'output_text', 'text': f'Subagent orchestration gate\\nResult: {decision}\\nReason: Fake live trace.'}],",
                "    },",
                "}",
                "print(json.dumps(event))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | 0o111)


def write_command_heavy_fake_codex(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "#!/usr/bin/env python3",
                "from __future__ import annotations",
                "import json",
                "for index in range(6):",
                "    command = f'echo command-{index}'",
                "    event = {'type': 'item.completed', 'item': {'id': f'item_{index}', 'type': 'command_execution', 'command': command}}",
                "    print(json.dumps(event))",
                "event = {'type': 'item.completed', 'item': {'type': 'message', 'content': [{'type': 'output_text', 'text': 'done'}]}}",
                "print(json.dumps(event))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | 0o111)


def run_live_runner(arguments: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(LIVE_RUNNER), *arguments],
        text=True,
        capture_output=True,
        cwd=cwd,
        check=False,
    )


def prompt_rows() -> list[dict[str, object]]:
    return [
        {
            "id": "simple-repository-question",
            "prompt": "What does this repository do?",
            "expected_decision": "single-thread-likely",
            "should_spawn": False,
            "must_not_spawn": True,
            "rubric_ids": ["decision", "no_spawn"],
        },
        {
            "id": "default-changelog-note",
            "prompt": "Draft a short note for the changelog.",
            "expected_decision": "single-thread-default",
            "should_spawn": False,
            "must_not_spawn": True,
            "rubric_ids": ["decision", "no_spawn"],
        },
    ]


def test_live_runner_dry_run_does_not_create_trace_files() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        write_jsonl(prompts, prompt_rows())

        proc = run_live_runner(
            [
                "--prompts",
                str(prompts),
                "--traces",
                str(traces),
                "--case",
                "simple-repository-question",
                "--codex-bin",
                "fake-codex",
                "--codex-arg=--ignore-user-config",
                "--dry-run",
            ],
            ROOT,
        )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    output = json.loads(proc.stdout)
    assert output["dry_run"] is True
    assert output["selected_cases"] == ["simple-repository-question"]
    assert output["commands"][0][-4:] == ["exec", "--ignore-user-config", "--json", "What does this repository do?"]
    assert not traces.exists()


def test_live_runner_captures_filtered_trace_and_grades_it() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        fake_codex = root / "fake_codex.py"
        write_jsonl(prompts, prompt_rows())
        write_fake_codex(fake_codex)

        proc = run_live_runner(
            [
                "--prompts",
                str(prompts),
                "--traces",
                str(traces),
                "--case",
                "simple-repository-question",
                "--codex-bin",
                str(fake_codex),
            ],
            ROOT,
        )

        trace_path = traces / "simple-repository-question.jsonl"
        selected_prompts_path = traces / "selected_prompts.jsonl"
        grade_path = traces / "grade.json"
        trace_exists = trace_path.exists()
        selected_prompts_exists = selected_prompts_path.exists()
        grade_exists = grade_path.exists()
        unselected_trace_exists = (traces / "default-changelog-note.jsonl").exists()

    assert proc.returncode == 0, proc.stderr + proc.stdout
    result = json.loads(proc.stdout)
    assert result["grade"]["overall_pass"] is True
    assert result["summary"]["captured"] == 1
    assert trace_exists
    assert selected_prompts_exists
    assert grade_exists
    assert not unselected_trace_exists


def test_live_runner_records_local_hook_context_before_live_events() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        fake_codex = root / "fake_codex.py"
        write_jsonl(prompts, prompt_rows())
        write_fake_codex(fake_codex)

        proc = run_live_runner(
            [
                "--prompts",
                str(prompts),
                "--traces",
                str(traces),
                "--case",
                "simple-repository-question",
                "--codex-bin",
                str(fake_codex),
            ],
            ROOT,
        )

        trace_rows = [
            json.loads(line)
            for line in (traces / "simple-repository-question.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    assert proc.returncode == 0, proc.stderr + proc.stdout
    assert trace_rows[0]["type"] == "hook.context"
    assert "Result: single-thread-likely" in json.dumps(trace_rows[0])


def test_live_runner_uses_live_grading_profile_for_command_budget() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        fake_codex = root / "fake_codex.py"
        write_jsonl(prompts, prompt_rows())
        write_command_heavy_fake_codex(fake_codex)

        proc = run_live_runner(
            [
                "--prompts",
                str(prompts),
                "--traces",
                str(traces),
                "--case",
                "simple-repository-question",
                "--codex-bin",
                str(fake_codex),
            ],
            ROOT,
        )

    assert proc.returncode == 0, proc.stderr + proc.stdout
    result = json.loads(proc.stdout)
    assert result["grade"]["overall_pass"] is True
    assert result["grade"]["cases"][0]["command_count"] == 6
    assert result["grade"]["cases"][0]["checks"]["command_budget"] is True


def test_live_runner_rejects_unknown_case_filter() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        write_jsonl(prompts, prompt_rows())

        proc = run_live_runner(
            [
                "--prompts",
                str(prompts),
                "--traces",
                str(traces),
                "--case",
                "missing-case",
            ],
            ROOT,
        )

    assert proc.returncode == 2
    assert "unknown case id: missing-case" in proc.stderr


def test_live_runner_rejects_path_like_case_ids() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        write_jsonl(
            prompts,
            [
                {
                    "id": "nested/case",
                    "prompt": "What does this repository do?",
                    "expected_decision": "single-thread-likely",
                    "should_spawn": False,
                    "must_not_spawn": True,
                    "rubric_ids": ["decision", "no_spawn"],
                },
            ],
        )

        proc = run_live_runner(
            [
                "--prompts",
                str(prompts),
                "--traces",
                str(traces),
                "--case",
                "nested/case",
            ],
            ROOT,
        )

    assert proc.returncode == 2
    assert "case id cannot be used as a trace filename: nested/case" in proc.stderr


def test_live_runner_refuses_existing_outputs_without_overwrite() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        root = Path(temp_dir)
        prompts = root / "prompts.jsonl"
        traces = root / "traces"
        traces.mkdir()
        (traces / "selected_prompts.jsonl").write_text("{}\n", encoding="utf-8")
        write_jsonl(prompts, prompt_rows())

        proc = run_live_runner(
            [
                "--prompts",
                str(prompts),
                "--traces",
                str(traces),
                "--case",
                "simple-repository-question",
                "--codex-bin",
                "fake-codex",
            ],
            ROOT,
        )

    assert proc.returncode == 2
    assert "pass --overwrite" in proc.stderr


def test_live_runner_source_does_not_use_shell_execution() -> None:
    text = LIVE_RUNNER.read_text(encoding="utf-8")
    assert "shell=True" not in text
    assert "os.system" not in text


def run_all_tests() -> None:
    for name, value in sorted(globals().items()):
        if name.startswith("test_") and callable(value):
            value()


def main() -> int:
    run_all_tests()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
