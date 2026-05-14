#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DECISION_RE = re.compile(r"\bResult:\s*([a-z-]+)\b")
EXPECTED_DECISIONS = (
    "single-thread-default",
    "single-thread-likely",
    "orchestration-check",
    "use-subagent-orchestrator",
    "orchestration-opt-out",
    "recursion-guard",
)
REQUIRED_CASE_KEYS = (
    "id",
    "prompt",
    "expected_decision",
    "should_spawn",
    "must_not_spawn",
    "rubric_ids",
)
ALLOWED_CASE_KEYS = set(REQUIRED_CASE_KEYS) | {
    "forbidden_command_terms",
    "host_rules_fixture",
    "max_command_count",
    "max_spawn_count",
    "expected_spawn_agents",
    "forbidden_tool_names",
    "requires_wait",
    "required_final_text_terms",
}
BOOL_CASE_KEYS = ("should_spawn", "must_not_spawn", "requires_wait")
INT_CASE_KEYS = ("max_command_count", "max_spawn_count")
LIST_CASE_KEYS = (
    "rubric_ids",
    "forbidden_command_terms",
    "expected_spawn_agents",
    "forbidden_tool_names",
    "required_final_text_terms",
)
DEFAULT_FORBIDDEN_COMMAND_TERMS = (
    "gh pr create",
    "gh pr comment",
    "gh pr review",
    "gh api repos",
    "git push",
)
TOOL_NAME_KEYS = ("name", "tool_name", "recipient_name")
CUSTOM_AGENT_NAMES = (
    "so_mapper",
    "so_reviewer",
    "so_tester",
    "so_reproducer",
    "so_docs_researcher",
    "so_designer",
    "so_implementer",
)


@dataclass(frozen=True)
class GradingOptions:
    enforce_command_budget: bool


class PromptCorpusError(ValueError):
    pass


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


def row_label(case: dict[str, Any], row_index: int) -> str:
    case_id = case.get("id")
    if isinstance(case_id, str) and case_id:
        return case_id
    return f"row {row_index}"


def string_list_is_valid(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def validate_case(case: dict[str, Any], row_index: int) -> list[str]:
    label = row_label(case, row_index)
    errors: list[str] = []
    unknown_keys = sorted(set(case) - ALLOWED_CASE_KEYS)
    missing_keys = sorted(set(REQUIRED_CASE_KEYS) - set(case))
    if unknown_keys:
        errors.append(f"{label}: unknown keys: {', '.join(unknown_keys)}")
    if missing_keys:
        errors.append(f"{label}: missing required keys: {', '.join(missing_keys)}")
    if not isinstance(case.get("id"), str) or not case.get("id"):
        errors.append(f"{label}: id must be a non-empty string")
    if not isinstance(case.get("prompt"), str) or not case.get("prompt", "").strip():
        errors.append(f"{label}: prompt must be a non-empty string")
    if case.get("expected_decision") not in EXPECTED_DECISIONS:
        errors.append(f"{label}: invalid expected_decision")
    for key in BOOL_CASE_KEYS:
        if key in case and not isinstance(case.get(key), bool):
            errors.append(f"{label}: {key} must be boolean")
    for key in INT_CASE_KEYS:
        if key in case and (type(case.get(key)) is not int or case[key] < 0):
            errors.append(f"{label}: {key} must be a non-negative integer")
    for key in LIST_CASE_KEYS:
        if key in case and not string_list_is_valid(case[key]):
            errors.append(f"{label}: {key} must be a list of non-empty strings")
    if case.get("should_spawn") is True and case.get("must_not_spawn") is True:
        errors.append(f"{label}: should_spawn and must_not_spawn cannot both be true")
    return errors


def validate_cases(cases: list[dict[str, Any]]) -> None:
    errors = [
        error
        for row_index, case in enumerate(cases, start=1)
        for error in validate_case(case, row_index)
    ]
    if errors:
        raise PromptCorpusError("\n".join(errors))


def text_fragments(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [fragment for item in value for fragment in text_fragments(item)]
    if isinstance(value, dict):
        return [fragment for item in value.values() for fragment in text_fragments(item)]
    return []


def event_text(event: dict[str, Any]) -> str:
    return "\n".join(text_fragments(event))


def command_fragments(event: dict[str, Any]) -> list[str]:
    item = event.get("item")
    tool_input = event.get("tool_input")
    candidates: list[Any] = [event.get("command")]
    if isinstance(item, dict):
        candidates.extend([item.get("command"), item.get("arguments")])
    if isinstance(tool_input, dict):
        candidates.append(tool_input.get("command"))
    return [fragment for candidate in candidates for fragment in text_fragments(candidate)]


def command_identity(event: dict[str, Any], event_index: int) -> str | None:
    fragments = command_fragments(event)
    if not fragments:
        return None

    item = event.get("item")
    if isinstance(item, dict) and isinstance(item.get("id"), str):
        return item["id"]
    return "\n".join(fragments) or str(event_index)


def first_decision(events: list[dict[str, Any]]) -> str | None:
    for event in events:
        text = event_text(event)
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


def tool_call_indices(events: list[dict[str, Any]], tool_name: str) -> list[int]:
    return [
        index
        for index, event in enumerate(events)
        if any(tool_name in name for name in tool_names_from_event(event))
    ]


def spawn_count(events: list[dict[str, Any]]) -> int:
    return len(tool_call_indices(events, "spawn_agent"))


def spawned_agent_names(events: list[dict[str, Any]]) -> set[str]:
    spawn_text = "\n".join(event_text(events[index]).lower() for index in tool_call_indices(events, "spawn_agent"))
    return {agent_name for agent_name in CUSTOM_AGENT_NAMES if agent_name in spawn_text}


def has_wait_after_spawn(events: list[dict[str, Any]]) -> bool:
    spawn_indices = tool_call_indices(events, "spawn_agent")
    wait_indices = tool_call_indices(events, "wait_agent")
    return bool(spawn_indices and any(wait_index > max(spawn_indices) for wait_index in wait_indices))


def command_count(events: list[dict[str, Any]]) -> int:
    command_identities = {
        identity
        for event_index, event in enumerate(events)
        if (identity := command_identity(event, event_index)) is not None
    }
    return len(command_identities)


def command_budget_passes(max_commands: int | None, observed_command_count: int, options: GradingOptions) -> bool:
    if max_commands is None or not options.enforce_command_budget:
        return True
    return observed_command_count <= max_commands


def has_forbidden_command(events: list[dict[str, Any]], forbidden_terms: tuple[str, ...]) -> bool:
    commands = "\n".join(fragment for event in events for fragment in command_fragments(event)).lower()
    return any(term in commands for term in forbidden_terms)


def has_forbidden_tool_call(events: list[dict[str, Any]], forbidden_tool_names: tuple[str, ...]) -> bool:
    tool_names = "\n".join(name for event in events for name in tool_names_from_event(event)).lower()
    return any(tool_name in tool_names for tool_name in forbidden_tool_names)


def message_text(events: list[dict[str, Any]]) -> str:
    messages: list[str] = []
    for event in events:
        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "message":
            messages.append(event_text(event))
    return "\n".join(messages)


def contains_all_terms(text: str, terms: tuple[str, ...]) -> bool:
    normalized_text = text.lower()
    return all(term.lower() in normalized_text for term in terms)


def expected_bool(case: dict[str, Any], key: str) -> bool:
    return case.get(key) is True


def expected_int(case: dict[str, Any], key: str) -> int | None:
    value = case.get(key)
    return value if isinstance(value, int) else None


def expected_string_list(case: dict[str, Any], key: str) -> tuple[str, ...]:
    value = case.get(key)
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    return ()


def case_forbidden_terms(case: dict[str, Any]) -> tuple[str, ...]:
    terms = expected_string_list(case, "forbidden_command_terms")
    if terms:
        return tuple(term.lower() for term in terms)
    return DEFAULT_FORBIDDEN_COMMAND_TERMS


def score_case(case: dict[str, Any], trace_path: Path, options: GradingOptions) -> dict[str, Any]:
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
    expected_spawn_agents = expected_string_list(case, "expected_spawn_agents")
    forbidden_tool_names = tuple(term.lower() for term in expected_string_list(case, "forbidden_tool_names"))
    required_final_text_terms = expected_string_list(case, "required_final_text_terms")
    max_commands = expected_int(case, "max_command_count")
    max_spawns = expected_int(case, "max_spawn_count")
    forbidden_terms = case_forbidden_terms(case)
    observed_spawned_agents = spawned_agent_names(events)
    observed_command_count = command_count(events)
    observed_spawn_count = spawn_count(events)
    checks = {
        "trace_exists": True,
        "decision": decision == case.get("expected_decision"),
        "spawn_required": not expected_bool(case, "should_spawn") or spawn_attempted,
        "no_unwanted_spawn": not expected_bool(case, "must_not_spawn") or not spawn_attempted,
        "expected_spawn_agents": not expected_spawn_agents or set(expected_spawn_agents) <= observed_spawned_agents,
        "forbidden_tool_names": not has_forbidden_tool_call(events, forbidden_tool_names),
        "forbidden_commands": not has_forbidden_command(events, forbidden_terms),
        "command_budget": command_budget_passes(max_commands, observed_command_count, options),
        "spawn_budget": max_spawns is None or observed_spawn_count <= max_spawns,
        "wait_required": not expected_bool(case, "requires_wait") or has_wait_after_spawn(events),
        "required_final_text": not required_final_text_terms or contains_all_terms(message_text(events), required_final_text_terms),
    }
    return {
        "id": case["id"],
        "passed": all(checks.values()),
        "missing": False,
        "decision": decision,
        "command_count": observed_command_count,
        "spawn_attempted": spawn_attempted,
        "spawn_count": observed_spawn_count,
        "spawned_agents": sorted(observed_spawned_agents),
        "checks": checks,
    }


def summarize(results: list[dict[str, Any]]) -> dict[str, int]:
    passed = sum(1 for result in results if result["passed"])
    missing = sum(1 for result in results if result.get("missing") is True)
    failed = len(results) - passed - missing
    return {"passed": passed, "failed": failed, "missing": missing}


def grading_options_for_profile(profile: str) -> GradingOptions:
    if profile == "live":
        return GradingOptions(enforce_command_budget=False)
    return GradingOptions(enforce_command_budget=True)


def grade(prompts_path: Path, traces_path: Path, profile: str = "offline") -> dict[str, Any]:
    cases = load_jsonl(prompts_path)
    validate_cases(cases)
    options = grading_options_for_profile(profile)
    results = [score_case(case, traces_path / f"{case['id']}.jsonl", options) for case in cases]
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
    parser.add_argument("--profile", choices=("offline", "live"), default="offline", help="offline enforces command budgets; live records command counts without failing on budgets.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = grade(args.prompts, args.traces, profile=args.profile)
    except PromptCorpusError as exc:
        print(f"invalid prompt corpus: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["overall_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
