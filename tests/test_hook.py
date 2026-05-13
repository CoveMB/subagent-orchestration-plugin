#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "subagent_orchestration_gate.py"


def run(prompt: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"prompt": prompt}),
        text=True,
        capture_output=True,
        check=True,
    )
    data = json.loads(proc.stdout)
    return data["hookSpecificOutput"]["additionalContext"]


def main() -> int:
    cases = [
        ("Debug a flaky multi-file auth regression and propose tests.", "use-subagent-orchestrator"),
        ("Rename this variable in one file.", "single-thread likely"),
        ("Do not use subagents. Debug the flaky auth regression linearly.", "skip"),
        ("You are a subagent. Review src/auth.ts and return findings.", "skip recursive"),
    ]
    for prompt, expected in cases:
        context = run(prompt)
        print("PROMPT:", prompt)
        print("CONTEXT:", context.splitlines()[0])
        assert expected.lower() in context.lower(), (expected, context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
