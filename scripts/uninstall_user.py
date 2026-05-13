#!/usr/bin/env python3
"""Uninstall files and owned config entries installed by this starter kit.

The uninstaller removes copied skill/custom-agent/hook/plugin files, the AGENTS
snippet, hook config blocks that reference this hook, and the local marketplace
entry.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
CODEX_HOME = Path(os.environ.get("CODEX_HOME", HOME / ".codex"))
PLUGIN_NAME = "subagent-orchestrator"
HOOK_FILE_NAME = "subagent_orchestration_gate.py"


def backup(path: Path) -> Path:
    backup_path = path.with_suffix(path.suffix + ".bak")
    shutil.copy2(path, backup_path)
    return backup_path


def installed_paths() -> list[Path]:
    paths = [
        HOME / ".agents" / "skills" / PLUGIN_NAME,
        HOME / ".agents" / "skills" / "using-subagent-orchestrator",
        CODEX_HOME / "hooks" / HOOK_FILE_NAME,
        CODEX_HOME / "plugins" / PLUGIN_NAME,
    ]
    agent_paths = sorted((ROOT / "custom-agents").glob("*.toml"))
    return paths + [CODEX_HOME / "agents" / path.name for path in agent_paths]


def remove_path(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
        print(f"removed directory: {path}")
    elif path.exists():
        path.unlink()
        print(f"removed file: {path}")
    else:
        print(f"not found: {path}")


def line_opens_table(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def is_hook_block_boundary(line: str, is_first_line: bool) -> bool:
    stripped = line.strip()
    if not line_opens_table(line):
        return False
    if is_first_line:
        return False
    return stripped not in {"[[hooks.UserPromptSubmit.hooks]]"}


def block_references_hook(block: list[str]) -> bool:
    return any(HOOK_FILE_NAME in line and not line.lstrip().startswith("#") for line in block)


def remove_hook_config_block(text: str) -> str:
    lines = text.splitlines(True)
    output: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index].strip() != "[[hooks.UserPromptSubmit]]":
            output.append(lines[index])
            index += 1
            continue

        block: list[str] = []
        while index < len(lines):
            is_first_line = not block
            if block and is_hook_block_boundary(lines[index], is_first_line):
                break
            block.append(lines[index])
            index += 1

        if not block_references_hook(block):
            output.extend(block)

    return "".join(output)


def remove_config_entries() -> None:
    config = CODEX_HOME / "config.toml"
    if not config.exists():
        print(f"not found: {config}")
        return
    original = config.read_text(encoding="utf-8")
    updated = remove_hook_config_block(original)
    if updated == original:
        print(f"no owned hook config found: {config}")
        return
    backup_path = backup(config)
    config.write_text(updated, encoding="utf-8")
    print(f"removed owned hook config from: {config} (backup: {backup_path})")


def remove_agents_guidance() -> None:
    agents_file = CODEX_HOME / "AGENTS.md"
    if not agents_file.exists():
        print(f"not found: {agents_file}")
        return
    snippet = (ROOT / "snippets" / "AGENTS.subagent-orchestration.md").read_text(encoding="utf-8").strip()
    original = agents_file.read_text(encoding="utf-8")
    updated = original.replace(snippet, "").strip() + "\n"
    if updated == original:
        print(f"no owned AGENTS guidance found: {agents_file}")
        return
    backup_path = backup(agents_file)
    agents_file.write_text(updated, encoding="utf-8")
    print(f"removed owned AGENTS guidance from: {agents_file} (backup: {backup_path})")


def remove_marketplace_entry() -> None:
    marketplace_path = HOME / ".agents" / "plugins" / "marketplace.json"
    if not marketplace_path.exists():
        print(f"not found: {marketplace_path}")
        return
    try:
        data = json.loads(marketplace_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"marketplace is not valid JSON; leaving unchanged: {marketplace_path}")
        return

    plugins = data.get("plugins", [])
    remaining_plugins = [plugin for plugin in plugins if plugin.get("name") != PLUGIN_NAME]
    if remaining_plugins == plugins:
        print(f"no owned marketplace entry found: {marketplace_path}")
        return
    data["plugins"] = remaining_plugins
    backup_path = backup(marketplace_path)
    marketplace_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"removed marketplace entry from: {marketplace_path} (backup: {backup_path})")


def main() -> int:
    for path in installed_paths():
        remove_path(path)
    remove_agents_guidance()
    remove_config_entries()
    remove_marketplace_entry()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
