#!/usr/bin/env python3
"""
UserPromptSubmit hook for Codex.

Superpowers-like behavior:
- Every submitted prompt is classified before the model starts work.
- The hook does not spawn subagents by itself.
- It injects developer-context guidance so Codex either stays single-threaded,
  does a brief orchestration check, or uses the subagent-orchestrator skill.

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


def build_context(decision: str, reason: str) -> str:
    if decision == "orchestration-opt-out":
        return f"""
Subagent orchestration gate result: skip.
Reason: {reason}
Respect the user's opt-out. Do not spawn subagents or force orchestration unless the user later reverses this instruction.
""".strip()

    if decision == "recursion-guard":
        return f"""
Subagent orchestration gate result: skip recursive orchestration.
Reason: {reason}
Treat this as a bounded subagent task. Do not spawn further subagents unless the parent explicitly requested nested delegation.
""".strip()

    if decision == "use-subagent-orchestrator":
        return f"""
Subagent orchestration gate triggered before work.
Preliminary classification: use-subagent-orchestrator.
Reason: {reason}

Use or load the `subagent-orchestrator` skill if available. If skill activation is unavailable, follow this inline gate:
- classify the task as single-thread, sequential-plan, or parallel-subagents;
- spawn subagents only when the work decomposes cleanly into bounded independent tasks;
- prefer read-only mapper/reviewer/tester/docs agents before edit-capable agents;
- avoid recursive fan-out;
- wait for all agents;
- synthesize agreed facts, conflicts, files, risks, and tests before acting.
If parallelism is not actually useful after inspection, say so briefly and proceed single-threaded.
""".strip()

    if decision == "orchestration-check":
        return f"""
Subagent orchestration gate result: check.
Preliminary reason: {reason}
Before substantive work, briefly classify the task as single-thread, sequential-plan, or parallel-subagents. Use subagents only if the task decomposes cleanly and coordination overhead is worth it.
""".strip()

    if decision == "single-thread-likely":
        return f"""
Subagent orchestration gate result: single-thread likely.
Reason: {reason}
Do not spawn subagents unless hidden complexity appears after initial inspection.
""".strip()

    return """
Subagent orchestration gate result: single-thread default.
Default to single-thread execution unless hidden complexity appears. For non-trivial work, briefly evaluate whether single-thread, sequential-plan, or parallel-subagents is safest.
""".strip()


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:  # Fail open: hooks should not break normal Codex usage.
        print(json.dumps({"systemMessage": f"subagent orchestration hook could not parse input: {exc}"}))
        return 0

    prompt = str(payload.get("prompt", ""))
    decision, reason = classify(prompt)
    additional_context = build_context(decision, reason)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": additional_context,
        }
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
