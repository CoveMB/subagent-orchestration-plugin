from __future__ import annotations

import re

DECISION_RE = re.compile(r"\bResult:\s*([a-z-]+)\b")

EXPECTED_DECISIONS = (
    "single-thread-default",
    "single-thread-likely",
    "orchestration-check",
    "use-subagent-orchestrator",
    "orchestration-opt-out",
    "recursion-guard",
)

CUSTOM_AGENT_NAMES = (
    "so_mapper",
    "so_reviewer",
    "so_tester",
    "so_reproducer",
    "so_docs_researcher",
    "so_designer",
    "so_implementer",
)
