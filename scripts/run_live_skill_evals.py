#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

from grade_skill_traces import grade, load_jsonl, validate_cases

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPTS = ROOT / "evals" / "skill_prompts.jsonl"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run live Codex skill eval prompts and grade captured JSONL traces.")
    parser.add_argument("--prompts", type=Path, default=DEFAULT_PROMPTS, help="Prompt corpus JSONL.")
    parser.add_argument("--traces", type=Path, required=True, help="Directory to write trace JSONL files.")
    parser.add_argument("--case", action="append", default=[], dest="case_ids", help="Prompt case id to run. Repeatable.")
    parser.add_argument("--codex-bin", default="codex", help="Codex executable path or command name.")
    parser.add_argument("--cwd", type=Path, default=ROOT, help="Working directory for live Codex runs.")
    parser.add_argument("--timeout", type=int, default=900, help="Per-case timeout in seconds.")
    parser.add_argument("--dry-run", action="store_true", help="Print selected commands without running Codex.")
    parser.add_argument("--no-grade", action="store_true", help="Capture traces without running the offline grader.")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing existing trace files.")
    return parser.parse_args()


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def selected_cases(cases: list[dict[str, Any]], case_ids: list[str]) -> list[dict[str, Any]]:
    if not case_ids:
        return cases

    cases_by_id = {case["id"]: case for case in cases}
    unknown_ids = [case_id for case_id in case_ids if case_id not in cases_by_id]
    if unknown_ids:
        raise ValueError("unknown case id: " + ", ".join(unknown_ids))
    return [cases_by_id[case_id] for case_id in case_ids]


def codex_command(codex_bin: str, prompt: str) -> list[str]:
    return [codex_bin, "exec", "--json", prompt]


def trace_path_for_case(traces_dir: Path, case_id: str) -> Path:
    if Path(case_id).name != case_id:
        raise ValueError(f"case id cannot be used as a trace filename: {case_id}")
    trace_path = (traces_dir / f"{case_id}.jsonl").resolve()
    if trace_path.parent != traces_dir.resolve():
        raise ValueError(f"case id cannot be used as a trace filename: {case_id}")
    return trace_path


def trace_paths_for_cases(traces_dir: Path, cases: list[dict[str, Any]]) -> list[Path]:
    return [trace_path_for_case(traces_dir, str(case["id"])) for case in cases]


def live_metadata_paths(traces_dir: Path) -> list[Path]:
    return [traces_dir / "selected_prompts.jsonl", traces_dir / "grade.json"]


def ensure_trace_targets_are_writable(traces_dir: Path, cases: list[dict[str, Any]], overwrite: bool) -> None:
    candidate_paths = trace_paths_for_cases(traces_dir, cases) + live_metadata_paths(traces_dir)
    existing_paths = [path for path in candidate_paths if path.exists()]
    if existing_paths and not overwrite:
        paths = ", ".join(str(path) for path in existing_paths)
        raise ValueError("trace files already exist; pass --overwrite to replace: " + paths)


def run_case(case: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    case_id = str(case["id"])
    command = codex_command(args.codex_bin, str(case["prompt"]))
    proc = subprocess.run(
        command,
        text=True,
        capture_output=True,
        cwd=args.cwd,
        timeout=args.timeout,
        check=False,
    )
    trace_path = trace_path_for_case(args.traces, case_id)
    trace_path.write_text(proc.stdout, encoding="utf-8")
    if proc.stderr:
        trace_path.with_suffix(".stderr.txt").write_text(proc.stderr, encoding="utf-8")
    return {
        "id": case_id,
        "command": command,
        "returncode": proc.returncode,
        "trace": str(trace_path),
        "stderr": bool(proc.stderr),
    }


def run_live_cases(cases: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    args.traces.mkdir(parents=True, exist_ok=True)
    ensure_trace_targets_are_writable(args.traces, cases, args.overwrite)
    return [run_case(case, args) for case in cases]


def dry_run_output(cases: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    return {
        "dry_run": True,
        "selected_cases": [case["id"] for case in cases],
        "commands": [codex_command(args.codex_bin, str(case["prompt"])) for case in cases],
    }


def live_result(cases: list[dict[str, Any]], run_results: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    selected_prompts_path = args.traces / "selected_prompts.jsonl"
    write_jsonl(selected_prompts_path, cases)
    failed_runs = [result for result in run_results if result["returncode"] != 0]
    result: dict[str, Any] = {
        "dry_run": False,
        "selected_cases": [case["id"] for case in cases],
        "summary": {
            "captured": len(run_results),
            "failed_runs": len(failed_runs),
        },
        "runs": run_results,
        "selected_prompts": str(selected_prompts_path),
    }
    if failed_runs or args.no_grade:
        return result

    grade_result = grade(selected_prompts_path, args.traces)
    grade_path = args.traces / "grade.json"
    write_json(grade_path, grade_result)
    result["grade"] = grade_result
    result["grade_path"] = str(grade_path)
    return result


def result_exit_code(result: dict[str, Any]) -> int:
    if result.get("dry_run") is True:
        return 0
    summary = result.get("summary", {})
    if isinstance(summary, dict) and summary.get("failed_runs"):
        return 1
    grade_result = result.get("grade")
    if isinstance(grade_result, dict) and grade_result.get("overall_pass") is False:
        return 1
    return 0


def main() -> int:
    args = parse_args()
    try:
        cases = load_jsonl(args.prompts)
        validate_cases(cases)
        cases_to_run = selected_cases(cases, args.case_ids)
        if args.dry_run:
            print(json.dumps(dry_run_output(cases_to_run, args), indent=2, sort_keys=True))
            return 0
        result = live_result(cases_to_run, run_live_cases(cases_to_run, args), args)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return result_exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
