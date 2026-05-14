#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RELATIVE_VENDOR_HOOK = __RELATIVE_VENDOR_HOOK__


def find_repo_root() -> Path:
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip())
    return Path(__file__).resolve().parents[2]


def print_system_message(message: str) -> int:
    print(json.dumps({"systemMessage": message}))
    return 0


def main() -> int:
    hook_path = find_repo_root() / RELATIVE_VENDOR_HOOK
    if not hook_path.exists():
        return print_system_message(f"vendored subagent orchestration hook is missing: {hook_path}")
    proc = subprocess.run(
        ["python3", str(hook_path)],
        input=sys.stdin.read(),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return print_system_message("vendored subagent orchestration hook failed open")
    print(proc.stdout, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
