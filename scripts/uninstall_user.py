#!/usr/bin/env python3
"""Conservative uninstaller for files installed by this starter kit.
It removes copied skill/custom-agent/hook/plugin files. It does not edit config.toml or AGENTS.md automatically.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

HOME = Path.home()
CODEX_HOME = Path(os.environ.get("CODEX_HOME", HOME / ".codex"))

paths = [
    HOME / ".agents" / "skills" / "subagent-orchestrator",
    HOME / ".agents" / "skills" / "using-subagent-orchestrator",
    CODEX_HOME / "hooks" / "subagent_orchestration_gate.py",
    CODEX_HOME / "plugins" / "subagent-orchestrator",
]
for name in ["so_mapper.toml", "so_reviewer.toml", "so_tester.toml", "so_docs_researcher.toml", "so_designer.toml", "so_implementer.toml"]:
    paths.append(CODEX_HOME / "agents" / name)

for p in paths:
    if p.is_dir():
        shutil.rmtree(p)
        print(f"removed directory: {p}")
    elif p.exists():
        p.unlink()
        print(f"removed file: {p}")
    else:
        print(f"not found: {p}")

print("Manual cleanup still recommended:")
print(f"- remove the subagent orchestration gate section from {CODEX_HOME / 'AGENTS.md'} if desired")
print(f"- remove hook/config entries from {CODEX_HOME / 'config.toml'} if you added them")
print(f"- remove the marketplace entry from {HOME / '.agents' / 'plugins' / 'marketplace.json'} if you installed the plugin")
