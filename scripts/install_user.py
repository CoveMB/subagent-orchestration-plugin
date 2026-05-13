#!/usr/bin/env python3
"""Install the subagent orchestration starter kit for the current user.

Default behavior is conservative:
- installs the skills directly to ~/.agents/skills
- stages the UserPromptSubmit hook script in CODEX_HOME/hooks
- does not patch CODEX_HOME/config.toml
- does not append CODEX_HOME/AGENTS.md
- does not install custom agents
- does not install/register the local plugin packaging
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
CODEX_HOME = Path(os.environ.get("CODEX_HOME", HOME / ".codex"))
PLUGIN_NAME = "subagent-orchestrator"
HOOK_FILE_NAME = "subagent_orchestration_gate.py"
COPY_IGNORE_PATTERNS = (
    ".DS_Store",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".coverage",
    "coverage",
    "dist",
    "build",
    "*.egg-info",
    ".venv",
    "node_modules",
)


def copytree_replace(src: Path, dst: Path, dry_run: bool, label: str) -> None:
    if dry_run:
        print(f"would install {label}: {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*COPY_IGNORE_PATTERNS))
    print(f"installed {label}: {dst}")


def copy_file(src: Path, dst: Path, dry_run: bool, label: str, executable: bool = False) -> None:
    if dry_run:
        print(f"would install {label}: {dst}")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if executable:
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"installed {label}: {dst}")


def install_skill(dry_run: bool) -> None:
    skills_src = ROOT / "plugin" / PLUGIN_NAME / "skills"
    skills_dst = HOME / ".agents" / "skills"
    for src in sorted(skills_src.iterdir()):
        if src.is_dir() and (src / "SKILL.md").exists():
            dst = skills_dst / src.name
            copytree_replace(src, dst, dry_run, "skill")


def hook_destination() -> Path:
    return CODEX_HOME / "hooks" / HOOK_FILE_NAME


def install_hook(dry_run: bool) -> Path:
    dst = hook_destination()
    copy_file(ROOT / "hooks" / HOOK_FILE_NAME, dst, dry_run, "hook", executable=True)
    return dst


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Install subagent orchestration skills and hook files."
    )
    parser.add_argument("--skills-only", action="store_true", help="Install only direct skills; skip hook staging.")
    parser.add_argument("--with-hook", action="store_true", help="Copy the UserPromptSubmit hook script. This is already included by default.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned copies without modifying files.")
    args = parser.parse_args()

    if args.skills_only and args.with_hook:
        parser.error("--skills-only cannot be combined with --with-hook")

    should_install_hook = not args.skills_only

    install_skill(args.dry_run)
    if should_install_hook:
        install_hook(args.dry_run)

    print("config.toml not modified; register the hook manually if you want it active.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
