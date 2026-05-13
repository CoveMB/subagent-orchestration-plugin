#!/usr/bin/env python3
"""
UserPromptSubmit hook for Codex.

Quiet compatibility behavior:
- Every submitted prompt is classified before output is chosen.
- Every successful classification returns a result and reason in additionalContext.
- Simple/default prompts emit only classification metadata, without orchestration guidance.
- The hook does not spawn subagents by itself.
- For complex prompts, it injects a quiet hint that complements existing
  orchestration, routing, bootstrap, skill-selection, and agent-management
  frameworks instead of competing with them.

Codex hook docs: UserPromptSubmit receives JSON on stdin with a `prompt` field and
can return JSON with hookSpecificOutput.additionalContext.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SignalSet:
    label: str
    weight: int
    patterns: tuple[str, ...]


CUSTOM_AGENT_NAMES = (
    "so_mapper",
    "so_reviewer",
    "so_tester",
    "so_reproducer",
    "so_docs_researcher",
    "so_designer",
    "so_implementer",
)
CUSTOM_AGENT_PATTERN = "(?:" + "|".join(re.escape(name) for name in CUSTOM_AGENT_NAMES) + ")"
SURFACE_TERM_PATTERN = r"(?:frontend|backend|api|web|server|client|database|db|service)s?"


def count_signals(text: str, signals: Iterable[SignalSet]) -> tuple[int, list[str]]:
    score = 0
    hits: list[str] = []
    for group in signals:
        for pattern in group.patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                score += group.weight
                hits.append(group.label)
                break
    return score, hits


OPTOUT_SIGNALS = (
    SignalSet("explicit user opt-out", 99, (
        r"\bdo not use sub[- ]?agents?\b",
        r"\bdon['’]?t use sub[- ]?agents?\b",
        r"\bdont use sub[- ]?agents?\b",
        r"\bno sub[- ]?agents?\b",
        r"\bwithout sub[- ]?agents?\b",
        r"\bno orchestrat(?:ion|e)\b",
        r"\bdon['’]?t orchestrat(?:e|ion)\b",
        r"\bdont orchestrat(?:e|ion)\b",
        r"\bdo not orchestrat(?:e|ion)\b",
        r"\bdo not use orchestrat(?:ion|e)\b",
        r"\bwork linearly\b",
        r"\blinear execution\b",
        r"\bsingle[- ]?thread(?:ed)? only\b",
    )),
)

RECURSION_GUARD_SIGNALS = (
    SignalSet("child-agent recursion guard", 99, (
        r"\bdispatched as (?:a )?sub[- ]?agent\b",
        r"\byou are a sub[- ]?agent\b",
        rf"\byou are {CUSTOM_AGENT_PATTERN}\b",
        r"\bbounded sub[- ]?agent task\b",
        rf"\btask for {CUSTOM_AGENT_PATTERN}\b",
        r"\bparent agent\b.*\basked\b",
    )),
)

CONDITIONAL_ORCHESTRATION_SIGNALS = (
    SignalSet("conditional orchestration", 4, (
        r"\b(?:sub[- ]?agents?|orchestrat(?:ion|e))\b.*\bunless (?:useful|valuable|needed|necessary|helpful)\b",
        r"\b(?:use|spawn|run)\b.*\b(?:sub[- ]?agents?|parallel agents?)\b.*\bonly if (?:useful|valuable|needed|necessary|helpful)\b",
        r"\b(?:sub[- ]?agents?|parallel agents?|orchestrat(?:ion|e))\b.*\bonly if (?:useful|valuable|needed|necessary|helpful)\b",
    )),
)

COMPLEX_SIGNALS = (
    SignalSet("debugging/root-cause", 3, (r"\bdebug\b", r"\binvestigat(?:e|ion)\b", r"root cause", r"\bfail(?:s|ed|ing|ure)?\b", r"flaky", r"regression", r"race condition", r"\bcrash(?:es|ed|ing)?\b", r"\berrors?\b")),
    SignalSet("review/audit", 3, (r"\breview\b", r"audit", r"security", r"threat", r"vulnerability", r"risk")),
    SignalSet("architecture/refactor", 3, (r"architecture", r"refactor", r"migration", r"rewrite", r"large change", r"multi[- ]?file", r"multi[- ]?module", r"multi[- ]?service")),
    SignalSet("multi-surface scope", 3, (
        rf"\bacross\b.*\b{SURFACE_TERM_PATTERN}\b",
        rf"\b{SURFACE_TERM_PATTERN}\b.*\band\b.*\b{SURFACE_TERM_PATTERN}\b",
        rf"\bspanning\b.*\b{SURFACE_TERM_PATTERN}\b",
    )),
    SignalSet("tests/verification", 2, (r"\btests?\b", r"coverage", r"verify", r"reproduce", r"benchmark", r"performance", r"\bci\b")),
    SignalSet("research/docs", 2, (r"docs?", r"documentation", r"api", r"version", r"latest", r"framework", r"library")),
    SignalSet("comparison/options", 2, (r"compare", r"options", r"trade[- ]?offs?", r"alternatives?", r"approaches?")),
    SignalSet("explicit subagents", 5, (r"sub[- ]?agents?", r"parallel agents?", r"orchestrat", r"delegate", r"split .*agents?")),
)

SIMPLE_SIGNALS = (
    SignalSet("simple question", 2, (r"^\s*(what|why|how)\b", r"explain", r"summari[sz]e")),
    SignalSet("tiny edit", 3, (r"typo", r"one[- ]?line", r"tiny", r"small", r"quick", r"rename")),
    SignalSet("direct ask", 1, (r"^\s*(give me|write|draft|compose)\b",)),
)

QUIET_COMPATIBILITY_RULES = """
Compatibility rules:
- Respect all active user and repository instructions.
- Do not ask the user whether orchestration is preferable; decide internally.
- The user has standing authorization for bounded delegation when the internal decision is parallel-subagents, but only inside active user and repository approval rules; do not ask for separate authorization before bounded delegation unless those rules or the action itself require approval.
- Do not override any existing orchestration, routing, bootstrap, skill-selection, or agent-management framework.
- Use subagent-orchestrator only as a complement or fallback.
- Prefer single-thread or sequential-plan unless bounded independent parallel tracks clearly add value.
- Require clear boundaries before spawning: role, mode, scope, expected output, and no recursive fan-out.
- Do not print a standard orchestration gate banner; mention orchestration only when it materially changes the work.
""".strip()

HOST_PROJECT_BOUNDARY_SENTENCE = "This orchestration gate only affects execution shape; it does not override repository source-of-truth, citation, manuscript, safety, privacy, vendor, approval, or testing rules."


def classify(prompt: str) -> tuple[str, str]:
    text = prompt.strip()

    optout_score, optout_hits = count_signals(text, OPTOUT_SIGNALS)
    conditional_score, conditional_hits = count_signals(text, CONDITIONAL_ORCHESTRATION_SIGNALS)
    if optout_score and not conditional_score:
        return (
            "orchestration-opt-out",
            "User explicitly requested no subagent orchestration: " + ", ".join(sorted(set(optout_hits))) + ".",
        )

    recursion_score, recursion_hits = count_signals(text, RECURSION_GUARD_SIGNALS)
    if recursion_score:
        return (
            "recursion-guard",
            "Prompt appears to be a bounded child-agent task: " + ", ".join(sorted(set(recursion_hits))) + ".",
        )

    if conditional_score:
        return (
            "orchestration-check",
            "User requested conditional orchestration: " + ", ".join(sorted(set(conditional_hits))) + ".",
        )

    complex_score, complex_hits = count_signals(text, COMPLEX_SIGNALS)
    simple_score, simple_hits = count_signals(text, SIMPLE_SIGNALS)

    if complex_score >= 5 and complex_score > simple_score + 1:
        return (
            "use-subagent-orchestrator",
            "Complexity signals: " + ", ".join(sorted(set(complex_hits))) + ".",
        )
    if complex_score >= 3:
        return (
            "orchestration-check",
            "Some complexity signals are present: " + ", ".join(sorted(set(complex_hits))) + ".",
        )
    if simple_score >= 2 and complex_score == 0:
        return (
            "single-thread-likely",
            "Simple-task signals: " + ", ".join(sorted(set(simple_hits))) + ".",
        )
    return ("single-thread-default", "No strong parallelization signals detected.")


def is_skip_decision(decision: str) -> bool:
    return decision in {"orchestration-opt-out", "recursion-guard"}


def format_result_context(decision: str, reason: str) -> str:
    lines = [
        f"\nSubagent orchestration gate result: {decision}.",
        f"Reason: {reason}",
    ]
    if not is_skip_decision(decision):
        lines.append(HOST_PROJECT_BOUNDARY_SENTENCE)
    return "\n".join(lines)


def build_context(decision: str, reason: str) -> str:
    result_context = format_result_context(decision, reason)

    if decision == "orchestration-opt-out":
        return result_context + "\nAction: skip orchestration. Respect the user's opt-out. Do not spawn subagents or force orchestration unless the user later reverses this instruction."

    if decision == "recursion-guard":
        return result_context + "\nAction: skip recursive orchestration. Treat this as a bounded subagent task. Do not spawn further subagents unless the parent explicitly requested nested delegation."

    if decision == "use-subagent-orchestrator":
        guidance = f"""

Subagent orchestration gate quiet hint.
Preliminary classification: use-subagent-orchestrator.

{QUIET_COMPATIBILITY_RULES}

If no higher-priority framework already covers this decision, the `subagent-orchestrator` skill may be used as a fallback. If skill activation is unavailable, follow this inline gate internally:
- classify the task as single-thread, sequential-plan, or parallel-subagents;
- spawn subagents only when the work decomposes cleanly into bounded independent tasks;
- prefer read-only mapper/reviewer/tester/docs agents before edit-capable agents;
- avoid recursive fan-out;
- wait for all agents;
- synthesize agreed facts, conflicts, files, risks, and tests before acting.
If parallelism is not actually useful after inspection, proceed single-threaded or with a sequential plan.
""".strip()
        return result_context + "\n\n" + guidance

    if decision == "orchestration-check":
        guidance = f"""

Subagent orchestration gate quiet hint: check.

{QUIET_COMPATIBILITY_RULES}

Evaluate internally whether the task is single-thread, sequential-plan, or parallel-subagents. Use subagents only if the task decomposes cleanly and coordination overhead is worth it.
""".strip()
        return result_context + "\n\n" + guidance

    return result_context


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:  # Fail open: hooks should not break normal Codex usage.
        print(json.dumps({"systemMessage": f"subagent orchestration hook could not parse input: {exc}"}))
        return 0

    prompt = str(payload.get("prompt", ""))
    decision, reason = classify(prompt)
    additional_context = build_context(decision, reason)
    hook_output = {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": additional_context,
    }

    print(json.dumps({
        "hookSpecificOutput": hook_output
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
