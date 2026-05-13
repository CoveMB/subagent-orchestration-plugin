#!/usr/bin/env python3
"""Install the subagent orchestration starter kit into the current user's Codex config.

Default behavior installs and activates the prompt gate:
- installs the skills directly to ~/.agents/skills/subagent-orchestrator and ~/.agents/skills/using-subagent-orchestrator
- installs custom agents to ~/.codex/agents
- installs the UserPromptSubmit hook script to ~/.codex/hooks
- appends AGENTS guidance to ~/.codex/AGENTS.md if not already present
- safely patches ~/.codex/config.toml unless --no-patch-config is passed

Optional:
- --plugin installs the plugin folder and adds/updates a local personal marketplace
- --no-patch-config skips config changes
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
CODEX_HOME = Path(os.environ.get("CODEX_HOME", HOME / ".codex"))
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


def copytree_replace(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*COPY_IGNORE_PATTERNS))


def copy_file(src: Path, dst: Path, executable: bool = False) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if executable:
        dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def append_once(path: Path, marker: str, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if marker in existing:
        return False
    prefix = "\n\n" if existing and not existing.endswith("\n") else "\n"
    path.write_text(existing + prefix + text.strip() + "\n", encoding="utf-8")
    return True


def install_skill() -> None:
    skills_src = ROOT / "plugin" / "subagent-orchestrator" / "skills"
    skills_dst = HOME / ".agents" / "skills"
    skills_dst.mkdir(parents=True, exist_ok=True)
    for src in sorted(skills_src.iterdir()):
        if src.is_dir() and (src / "SKILL.md").exists():
            dst = skills_dst / src.name
            copytree_replace(src, dst)
            print(f"installed skill: {dst}")


def install_agents() -> None:
    agents_dir = CODEX_HOME / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    for src in (ROOT / "custom-agents").glob("*.toml"):
        copy_file(src, agents_dir / src.name)
        print(f"installed custom agent: {agents_dir / src.name}")


def install_hook() -> Path:
    dst = CODEX_HOME / "hooks" / "subagent_orchestration_gate.py"
    copy_file(ROOT / "hooks" / "subagent_orchestration_gate.py", dst, executable=True)
    print(f"installed hook: {dst}")
    return dst


def install_agents_md() -> None:
    snippet = (ROOT / "snippets" / "AGENTS.subagent-orchestration.md").read_text(encoding="utf-8")
    changed = append_once(CODEX_HOME / "AGENTS.md", "## Subagent orchestration gate", snippet)
    print(("updated" if changed else "already present") + f": {CODEX_HOME / 'AGENTS.md'}")


def install_plugin_marketplace() -> None:
    plugin_dst = CODEX_HOME / "plugins" / "subagent-orchestrator"
    copytree_replace(ROOT / "plugin" / "subagent-orchestrator", plugin_dst)
    print(f"installed plugin folder: {plugin_dst}")

    marketplace_path = HOME / ".agents" / "plugins" / "marketplace.json"
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)

    if marketplace_path.exists():
        try:
            data = json.loads(marketplace_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            backup = marketplace_path.with_suffix(".json.bak")
            shutil.copy2(marketplace_path, backup)
            print(f"existing marketplace was not valid JSON; backed up to {backup}")
            data = empty_marketplace()
    else:
        data = empty_marketplace()

    data.setdefault("name", "local-personal-codex-plugins")
    data.setdefault("interface", {"displayName": "Local Personal Codex Plugins"})
    plugins = data.setdefault("plugins", [])
    entry = {
        "name": "subagent-orchestrator",
        "source": {"source": "local", "path": "./.codex/plugins/subagent-orchestrator"},
        "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
        "category": "Productivity",
    }
    plugins[:] = [p for p in plugins if p.get("name") != "subagent-orchestrator"] + [entry]
    marketplace_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"updated marketplace: {marketplace_path}")


def empty_marketplace() -> dict[str, object]:
    return {
        "name": "local-personal-codex-plugins",
        "interface": {"displayName": "Local Personal Codex Plugins"},
        "plugins": [],
    }


def toml_quote(value: str) -> str:
    return json.dumps(value)


def has_table(lines: list[str], table: str) -> bool:
    needle = f"[{table}]"
    return any(line.strip() == needle for line in lines)


def is_exact_key_line(line: str, key: str) -> bool:
    return bool(re.match(rf"^\s*{re.escape(key)}\s*=", line))


def upsert_simple_key(lines: list[str], table: str, key: str, value: str) -> list[str]:
    table_header = f"[{table}]"
    if not has_table(lines, table):
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.extend([table_header + "\n", f"{key} = {value}\n"])
        return lines

    out: list[str] = []
    in_table = False
    inserted = False
    updated = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_table and not updated and not inserted:
                out.append(f"{key} = {value}\n")
                inserted = True
            in_table = stripped == table_header
        if in_table and is_exact_key_line(line, key):
            out.append(f"{key} = {value}\n")
            updated = True
        else:
            out.append(line)
    if in_table and not updated and not inserted:
        out.append(f"{key} = {value}\n")
    return out


def has_active_command_line(text: str, command_line: str) -> bool:
    return any(
        line.strip() == command_line and not line.lstrip().startswith("#")
        for line in text.splitlines()
    )


def patch_config(hook_path: Path) -> None:
    config = CODEX_HOME / "config.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    if config.exists():
        backup = config.with_suffix(".toml.bak")
        shutil.copy2(config, backup)
        print(f"backup created: {backup}")
        lines = config.read_text(encoding="utf-8").splitlines(True)
    else:
        lines = []

    lines = upsert_simple_key(lines, "features", "codex_hooks", "true")
    lines = upsert_simple_key(lines, "agents", "max_threads", "6")
    lines = upsert_simple_key(lines, "agents", "max_depth", "1")

    command = f"{sys.executable} {hook_path}"
    command_line = f"command = {toml_quote(command)}"
    hook_block = (
        "\n[[hooks.UserPromptSubmit]]\n"
        "[[hooks.UserPromptSubmit.hooks]]\n"
        "type = \"command\"\n"
        f"{command_line}\n"
        "timeout = 5\n"
        "statusMessage = \"Evaluating subagent orchestration\"\n"
    )
    text = "".join(lines)
    if not has_active_command_line(text, command_line):
        if text and not text.endswith("\n"):
            text += "\n"
        text += hook_block
    else:
        print("hook config already contains the active command; not appending duplicate hook block")

    config.write_text(text, encoding="utf-8")
    print(f"patched config: {config}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin", action="store_true", help="Also install the local plugin folder and personal marketplace entry.")
    parser.add_argument("--patch-config", action="store_true", help="Compatibility flag. Config patching is enabled by default.")
    parser.add_argument("--no-patch-config", action="store_true", help="Skip hook + subagent settings in ~/.codex/config.toml.")
    args = parser.parse_args()

    install_skill()
    install_agents()
    hook = install_hook()
    install_agents_md()
    if args.plugin:
        install_plugin_marketplace()
    if args.no_patch_config:
        print("config.toml not modified. See snippets/config.*.toml or run with --patch-config.")
    else:
        patch_config(hook)

    print("Restart Codex or start a new thread after installing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
