#!/usr/bin/env python3
"""
UserPromptSubmit hook for Codex.

Quiet compatibility behavior:
- Every submitted prompt is classified before output is chosen.
- Every successful classification returns a result and reason in additionalContext.
- All prompts emit only classification metadata, without orchestration guidance.
- The hook does not spawn subagents by itself.

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
FORMAL_REVIEW_TARGET_PATTERN = (
    r"(?:branch|pr|pull request|mr|merge request|diff|patch|code|changes?|commits?|"
    r"security|threat|vulnerabilit(?:y|ies)|risks?|architecture|implementation|modules?|"
    r"repositories|repo|files?|functions?|classes?|tests?)"
)
FORMAL_REVIEW_PATTERN = (
    rf"(?:\breview\b.{{0,80}}\b{FORMAL_REVIEW_TARGET_PATTERN}\b|"
    rf"\b{FORMAL_REVIEW_TARGET_PATTERN}\b.{{0,80}}\breview\b)"
)
OUTPUT_OR_STATUS_TERM_PATTERN = r"(?:status feedback|status sentences?|hook context|outputs?|results?|messages?|labels?)"
OUTPUT_QUALITY_TERM_PATTERN = (
    r"(?:professional|profesional|consistent|inconsistent|inconsistant|punctuation|"
    r"wording|tone|polish|grammar|style)"
)
RESULT_SWEEP_PATTERN = r"(?:all possible|every|each|all)\s+(?:results?|outputs?|status(?:es)?|messages?|cases?|variants?)"


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


def format_signal_hits(hits: Iterable[str]) -> str:
    return ", ".join(sorted(set(hits)))


def format_signal_reason(message: str, hits: Iterable[str]) -> str:
    signal_hits = format_signal_hits(hits)
    if not signal_hits:
        return message + "."
    return f"{message} ({signal_hits})."


OPTOUT_SIGNALS = (
    SignalSet("explicit user opt-out", 99, (
        r"\bdo not use sub[- ]?agents?\b",
        r"\bdon['’]?t use sub[- ]?agents?\b",
        r"\bdont use sub[- ]?agents?\b",
        r"\bno sub[- ]?agents?\b",
        r"\bwithout sub[- ]?agents?\b",
        r"\bno parallel agents?\b",
        r"\bwithout parallel agents?\b",
        r"\bno orchestrat(?:ion|e)\b",
        r"\bdon['’]?t orchestrat(?:e|ion)\b",
        r"\bdont orchestrat(?:e|ion)\b",
        r"\bdo not orchestrat(?:e|ion)\b",
        r"\bdo not use orchestrat(?:ion|e)\b",
        r"\bdon['’]?t use orchestrat(?:ion|e)\b",
        r"\bdont use orchestrat(?:ion|e)\b",
        r"\bwithout orchestrat(?:ion|e)\b",
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
    SignalSet("review/audit", 3, (FORMAL_REVIEW_PATTERN, r"audit", r"security", r"threat", r"vulnerabilit(?:y|ies)", r"\brisk\b")),
    SignalSet("output/status review", 3, (
        rf"\breview\b.{{0,80}}\b(?:status feedback|hook context|outputs?|results?|messages?|labels?)\b",
    )),
    SignalSet("output/status wording", 2, (
        rf"\b{OUTPUT_OR_STATUS_TERM_PATTERN}\b.{{0,80}}\b{OUTPUT_QUALITY_TERM_PATTERN}\b",
        rf"\b{OUTPUT_QUALITY_TERM_PATTERN}\b.{{0,80}}\b{OUTPUT_OR_STATUS_TERM_PATTERN}\b",
    )),
    SignalSet("exhaustive result sweep", 4, (
        rf"\b{RESULT_SWEEP_PATTERN}\b",
        rf"\breview\b.{{0,80}}\b{RESULT_SWEEP_PATTERN}\b",
    )),
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
            format_signal_reason("Explicit orchestration opt-out detected", optout_hits),
        )

    recursion_score, recursion_hits = count_signals(text, RECURSION_GUARD_SIGNALS)
    if recursion_score:
        return (
            "recursion-guard",
            format_signal_reason("Bounded child-agent task detected", recursion_hits),
        )

    if conditional_score:
        return (
            "orchestration-check",
            format_signal_reason("Conditional orchestration request detected", conditional_hits),
        )

    complex_score, complex_hits = count_signals(text, COMPLEX_SIGNALS)
    simple_score, simple_hits = count_signals(text, SIMPLE_SIGNALS)

    if complex_score >= 5 and complex_score > simple_score + 1:
        return (
            "use-subagent-orchestrator",
            format_signal_reason("Strong orchestration signals detected", complex_hits),
        )
    if complex_score >= 3:
        return (
            "orchestration-check",
            format_signal_reason("Moderate orchestration signals detected", complex_hits),
        )
    if simple_score >= 2 and complex_score <= 2:
        return (
            "single-thread-likely",
            format_signal_reason("Simple-task signals detected", simple_hits),
        )
    return ("single-thread-default", "No strong orchestration signals detected.")


def format_result_context(decision: str, reason: str) -> str:
    return "\n".join([
        "Subagent orchestration gate",
        f"Result: {decision}",
        f"Reason: {reason}",
    ])


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception as exc:  # Fail open: hooks should not break normal Codex usage.
        print(json.dumps({"systemMessage": f"subagent orchestration hook could not parse input: {exc}"}))
        return 0

    prompt = str(payload.get("prompt", ""))
    decision, reason = classify(prompt)
    additional_context = format_result_context(decision, reason)
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
