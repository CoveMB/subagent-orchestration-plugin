#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

DECISION_RE = re.compile(r"\bResult:\s*([a-z-]+)\b")
DEFAULT_FORBIDDEN_COMMAND_TERMS = (
    "gh pr create",
    "gh pr comment",
    "gh api repos",
)
TOOL_NAME_KEYS = ("name", "tool_name", "recipient_name")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected JSON object")
        rows.append(value)
    return rows


def text_fragments(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [fragment for item in value for fragment in text_fragments(item)]
    if isinstance(value, dict):
        return [fragment for item in value.values() for fragment in text_fragments(item)]
    return []


def command_fragments(event: dict[str, Any]) -> list[str]:
    item = event.get("item")
    tool_input = event.get("tool_input")
    candidates: list[Any] = [event.get("command")]
    if isinstance(item, dict):
        candidates.extend([item.get("command"), item.get("arguments")])
    if isinstance(tool_input, dict):
        candidates.append(tool_input.get("command"))
    return [fragment for candidate in candidates for fragment in text_fragments(candidate)]


def first_decision(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        text = "\n".join(text_fragments(event))
        match = DECISION_RE.search(text)
        if match:
            return match.group(1)
    return None


def tool_names_from_event(event: dict[str, Any]) -> list[str]:
    item = event.get("item")
    candidates: list[Any] = [event.get(key) for key in TOOL_NAME_KEYS]
    if isinstance(item, dict):
        candidates.extend(item.get(key) for key in TOOL_NAME_KEYS)
    return [candidate for candidate in candidates if isinstance(candidate, str)]


def has_spawn_call(events: list[dict[str, Any]]) -> bool:
    return any("spawn_agent" in name for event in events for name in tool_names_from_event(event))


def command_count(events: list[dict[str, Any]]) -> int:
    return sum(1 for event in events if command_fragments(event))


def has_forbidden_command(events: list[dict[str, Any]], forbidden_terms: tuple[str, ...]) -> bool:
    commands = "\n".join(fragment for event in events for fragment in command_fragments(event)).lower()
    return any(term in commands for term in forbidden_terms)


def expected_bool(case: dict[str, Any], key: str) -> bool:
    return case.get(key) is True


def expected_int(case: dict[str, Any], key: str) -> int | None:
    value = case.get(key)
    return value if isinstance(value, int) else None


def case_forbidden_terms(case: dict[str, Any]) -> tuple[str, ...]:
    terms = case.get("forbidden_command_terms")
    if isinstance(terms, list) and all(isinstance(term, str) for term in terms):
        return tuple(term.lower() for term in terms)
    return DEFAULT_FORBIDDEN_COMMAND_TERMS


def score_case(case: dict[str, Any], trace_path: Path) -> dict[str, Any]:
    if not trace_path.exists():
        return {
            "id": case["id"],
            "passed": False,
            "missing": True,
            "checks": {"trace_exists": False},
        }

    events = load_jsonl(trace_path)
    decision = first_decision(events)
    spawn_attempted = has_spawn_call(events)
    max_commands = expected_int(case, "max_command_count")
    forbidden_terms = case_forbidden_terms(case)
    checks = {
        "trace_exists": True,
        "decision": decision == case.get("expected_decision"),
        "spawn_required": not expected_bool(case, "should_spawn") or spawn_attempted,
        "no_unwanted_spawn": not expected_bool(case, "must_not_spawn") or not spawn_attempted,
        "forbidden_commands": not has_forbidden_command(events, forbidden_terms),
        "command_budget": max_commands is None or command_count(events) <= max_commands,
    }
    return {
        "id": case["id"],
        "passed": all(checks.values()),
        "missing": False,
        "decision": decision,
        "spawn_attempted": spawn_attempted,
        "checks": checks,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, int]:
    passed = sum(1 for result in results if result["passed"])
    missing = sum(1 for result in results if result.get("missing") is True)
    failed = len(results) - passed - missing
    return {"passed": passed, "failed": failed, "missing": missing}


def grade(prompts_path: Path, traces_path: Path) -> dict[str, Any]:
    cases = load_jsonl(prompts_path)
    results = [score_case(case, traces_path / f"{case['id']}.jsonl") for case in cases]
    summary = summarize(results)
    return {
        "overall_pass": summary["failed"] == 0 and summary["missing"] == 0,
        "summary": summary,
        "cases": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grade subagent-orchestrator JSONL traces against eval prompt expectations.")
    parser.add_argument("--prompts", required=True, type=Path, help="Path to eval prompt JSONL.")
    parser.add_argument("--traces", required=True, type=Path, help="Directory containing one <id>.jsonl trace per prompt.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = grade(args.prompts, args.traces)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
