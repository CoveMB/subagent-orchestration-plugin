#!/usr/bin/env python3
"""Install the subagent orchestration starter kit.

Default behavior is conservative:
- user scope installs direct skills only
- user scope never patches CODEX_HOME/config.toml
- project scope writes only under the selected repository root
- project scope activates the gate only when --activate-gate is passed
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import tomllib
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
CODEX_HOME = Path(os.environ.get("CODEX_HOME", HOME / ".codex"))
PLUGIN_NAME = "subagent-orchestrator"
USING_SKILL_NAME = "using-subagent-orchestrator"
HOOK_FILE_NAME = "subagent_orchestration_gate.py"
PROJECT_MANIFEST_NAME = "subagent-orchestrator-install.json"
PROJECT_VENDOR_PATH = Path("vendor") / "subagent-orchestration-plugin"
MANAGED_CONFIG_START = "# BEGIN subagent-orchestrator project gate"
MANAGED_CONFIG_END = "# END subagent-orchestrator project gate"
MANAGED_AGENTS_START = "<!-- BEGIN subagent-orchestrator project guidance -->"
MANAGED_AGENTS_END = "<!-- END subagent-orchestrator project guidance -->"
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

PROJECT_AGENTS_SECTION = f"""
{MANAGED_AGENTS_START}
## Optional subagent orchestration

- This plugin is an execution-shape helper only.
- Host project rules win.
- Subagent output is not evidence.
- Keep subagents read-only by default.
- Do not invent sources, citekeys, page numbers, quotations, studies, or metadata.
- Do not install global hooks/config by default.
{MANAGED_AGENTS_END}
""".strip()


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


def install_user_skill(dry_run: bool) -> None:
    skills_src = ROOT / "plugin" / PLUGIN_NAME / "skills"
    skills_dst = HOME / ".agents" / "skills"
    for src in sorted(skills_src.iterdir()):
        if src.is_dir() and (src / "SKILL.md").exists():
            copytree_replace(src, skills_dst / src.name, dry_run, "skill")


def hook_destination() -> Path:
    return CODEX_HOME / "hooks" / HOOK_FILE_NAME


def install_user_hook(dry_run: bool) -> Path:
    dst = hook_destination()
    copy_file(ROOT / "hooks" / HOOK_FILE_NAME, dst, dry_run, "hook", executable=True)
    return dst


def activation_snippet_path() -> str:
    if os.name == "nt":
        return "snippets/config.hooks.windows.toml"
    return "snippets/config.hooks.posix.toml"


def print_user_activation_notice(should_install_hook: bool) -> None:
    print("config.toml was not modified.")
    if not should_install_hook:
        print("Hook not staged; run with --with-hook before manually activating the hook.")
        return
    print("Hook staged but not active.")
    print(f"Activation required: manually merge {activation_snippet_path()} into CODEX_HOME/config.toml.")


def resolved_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def is_inside(base: Path, path: Path) -> bool:
    base_path = resolved_path(base)
    target_path = resolved_path(path)
    return target_path == base_path or target_path.is_relative_to(base_path)


def ensure_inside_repo(repo_root: Path, path: Path) -> Path:
    target_path = resolved_path(path)
    if not is_inside(repo_root, target_path):
        raise ValueError(f"refusing to write outside repo root: {target_path}")
    return target_path


def repo_relative_path(repo_root: Path, path: Path) -> str:
    return ensure_inside_repo(repo_root, path).relative_to(resolved_path(repo_root)).as_posix()


def add_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def new_manifest(repo_root: Path) -> dict[str, Any]:
    return {
        "version": 1,
        "plugin": PLUGIN_NAME,
        "repo_root": str(resolved_path(repo_root)),
        "installed_paths": [],
        "created_paths": [],
        "backups": [],
        "config_values": {},
    }


def manifest_path(repo_root: Path) -> Path:
    return repo_root / ".codex" / PROJECT_MANIFEST_NAME


def load_project_manifest(repo_root: Path) -> dict[str, Any]:
    path = manifest_path(repo_root)
    if not path.exists():
        return new_manifest(repo_root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return new_manifest(repo_root)
    if data.get("plugin") != PLUGIN_NAME:
        return new_manifest(repo_root)
    for key, default_value in new_manifest(repo_root).items():
        data.setdefault(key, default_value)
    return data


def record_created_path(manifest: dict[str, Any], repo_root: Path, path: Path) -> None:
    add_unique(manifest["created_paths"], repo_relative_path(repo_root, path))


def record_installed_path(manifest: dict[str, Any], repo_root: Path, path: Path) -> None:
    add_unique(manifest["installed_paths"], repo_relative_path(repo_root, path))


def is_manifest_owned(manifest: dict[str, Any], repo_root: Path, path: Path) -> bool:
    relative_path = repo_relative_path(repo_root, path)
    return relative_path in manifest.get("created_paths", []) or relative_path in manifest.get("installed_paths", [])


def path_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def next_backup_path(path: Path) -> Path:
    first_backup = path.with_name(path.name + ".bak")
    if not path_exists(first_backup):
        return first_backup
    index = 1
    while True:
        candidate = path.with_name(f"{path.name}.bak.{index}")
        if not path_exists(candidate):
            return candidate
        index += 1


def backup_existing_path(
    path: Path,
    repo_root: Path,
    manifest: dict[str, Any],
    dry_run: bool,
    label: str,
) -> Path | None:
    if not path_exists(path):
        return None
    backup_path = next_backup_path(path)
    ensure_inside_repo(repo_root, backup_path)
    if dry_run:
        print(f"would back up existing {label}: {path} -> {backup_path}")
        return backup_path
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(backup_path))
    manifest["backups"].append({
        "path": repo_relative_path(repo_root, path),
        "backup_path": repo_relative_path(repo_root, backup_path),
    })
    print(f"backed up existing {label}: {path} -> {backup_path}")
    return backup_path


def remove_path(path: Path, dry_run: bool, label: str) -> None:
    if not path_exists(path):
        return
    if dry_run:
        print(f"would remove {label}: {path}")
        return
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)
    print(f"removed {label}: {path}")


def prepare_project_destination(
    path: Path,
    repo_root: Path,
    manifest: dict[str, Any],
    dry_run: bool,
    label: str,
) -> None:
    ensure_inside_repo(repo_root, path)
    if not path_exists(path):
        if not dry_run:
            record_created_path(manifest, repo_root, path)
        return
    if is_manifest_owned(manifest, repo_root, path):
        remove_path(path, dry_run, label)
        return
    backup_existing_path(path, repo_root, manifest, dry_run, label)


def copy_project_tree(
    src: Path,
    dst: Path,
    repo_root: Path,
    manifest: dict[str, Any],
    dry_run: bool,
    label: str,
) -> None:
    if dry_run:
        if path_exists(dst) and not is_manifest_owned(manifest, repo_root, dst):
            backup_existing_path(dst, repo_root, manifest, True, label)
        print(f"would copy {label}: {src} -> {dst}")
        return
    prepare_project_destination(dst, repo_root, manifest, False, label)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(*COPY_IGNORE_PATTERNS))
    record_installed_path(manifest, repo_root, dst)
    print(f"copied {label}: {dst}")


def link_project_tree(
    src: Path,
    dst: Path,
    repo_root: Path,
    manifest: dict[str, Any],
    dry_run: bool,
    label: str,
) -> bool:
    if dry_run:
        if path_exists(dst) and not is_manifest_owned(manifest, repo_root, dst):
            backup_existing_path(dst, repo_root, manifest, True, label)
        print(f"would symlink {label}: {dst} -> {src}")
        return True
    prepare_project_destination(dst, repo_root, manifest, False, label)
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(src, dst, target_is_directory=True)
    except OSError as exc:
        print(f"symlink failed for {label}; falling back to copy: {exc}")
        return False
    record_installed_path(manifest, repo_root, dst)
    print(f"symlinked {label}: {dst} -> {src}")
    return True


def write_project_text(
    path: Path,
    text: str,
    repo_root: Path,
    manifest: dict[str, Any],
    dry_run: bool,
    label: str,
    executable: bool = False,
    record_installed: bool = True,
) -> None:
    ensure_inside_repo(repo_root, path)
    if path.exists() and path.is_file() and path.read_text(encoding="utf-8") == text:
        if dry_run:
            print(f"would leave unchanged {label}: {path}")
        return
    if dry_run:
        if path_exists(path) and not is_manifest_owned(manifest, repo_root, path):
            backup_existing_path(path, repo_root, manifest, True, label)
        action = "patch" if path_exists(path) else "create"
        print(f"would {action} {label}: {path}")
        return
    prepare_project_destination(path, repo_root, manifest, False, label)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    if record_installed:
        record_installed_path(manifest, repo_root, path)
    print(f"wrote {label}: {path}")


def write_manifest(repo_root: Path, manifest: dict[str, Any], dry_run: bool) -> None:
    path = manifest_path(repo_root)
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if dry_run:
        print(f"would write install manifest: {path}")
        return
    ensure_inside_repo(repo_root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"wrote install manifest: {path}")


def detect_repo_root(repo_root_arg: str | None) -> Path:
    if repo_root_arg:
        repo_root = resolved_path(Path(repo_root_arg))
        if not repo_root.exists() or not repo_root.is_dir():
            raise SystemExit(f"error: --repo-root must point to an existing directory: {repo_root}")
        return repo_root
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise SystemExit("error: --scope project requires a git repository or --repo-root PATH")
    return resolved_path(Path(proc.stdout.strip()))


def validate_source_root(source_root: Path) -> None:
    required_paths = [
        source_root / "plugin" / PLUGIN_NAME / "skills" / PLUGIN_NAME / "SKILL.md",
        source_root / "plugin" / PLUGIN_NAME / "skills" / USING_SKILL_NAME / "SKILL.md",
        source_root / "hooks" / HOOK_FILE_NAME,
    ]
    missing_paths = [str(path) for path in required_paths if not path.exists()]
    if missing_paths:
        raise SystemExit("error: source plugin is missing required files: " + ", ".join(missing_paths))


def resolve_project_source_root(args: argparse.Namespace, repo_root: Path) -> Path:
    if not args.from_vendor:
        return ROOT
    source_root = resolved_path(Path(args.from_vendor))
    if not is_inside(repo_root, source_root):
        raise SystemExit("error: --from-vendor must point inside the project repo root")
    validate_source_root(source_root)
    return source_root


def project_config_block() -> str:
    return f"""
{MANAGED_CONFIG_START}
[[hooks.UserPromptSubmit]]
[[hooks.UserPromptSubmit.hooks]]
type = "command"
command = 'python3 "$(git rev-parse --show-toplevel)/.codex/hooks/{HOOK_FILE_NAME}"'
timeout = 5
statusMessage = "Evaluating subagent orchestration"
{MANAGED_CONFIG_END}
""".strip()


def remove_marked_block(text: str, start_marker: str, end_marker: str) -> str:
    start = text.find(start_marker)
    if start == -1:
        return text
    end = text.find(end_marker, start)
    if end == -1:
        return text
    end += len(end_marker)
    before = text[:start].rstrip()
    after = text[end:].lstrip("\n")
    pieces = [piece for piece in [before, after] if piece]
    return "\n\n".join(pieces) + ("\n" if pieces else "")


def table_header_name(line: str) -> str | None:
    stripped = line.strip()
    if not stripped.startswith("[") or not stripped.endswith("]"):
        return None
    if stripped.startswith("[[") and stripped.endswith("]]"):
        return stripped[2:-2].strip()
    return stripped[1:-1].strip()


def line_opens_toml_table(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("[") and stripped.endswith("]")


def find_table_bounds(lines: list[str], table_name: str) -> tuple[int, int] | None:
    start_index: int | None = None
    for index, line in enumerate(lines):
        if table_header_name(line) == table_name and line.strip() == f"[{table_name}]":
            start_index = index
            break
    if start_index is None:
        return None
    end_index = len(lines)
    for index in range(start_index + 1, len(lines)):
        if line_opens_toml_table(lines[index]):
            end_index = index
            break
    return start_index, end_index


def set_toml_table_key(text: str, table_name: str, key: str, value: str) -> str:
    lines = text.splitlines()
    bounds = find_table_bounds(lines, table_name)
    key_line = f"{key} = {value}"
    if bounds is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.extend([f"[{table_name}]", key_line])
        return "\n".join(lines).rstrip() + "\n"

    start_index, end_index = bounds
    for index in range(start_index + 1, end_index):
        stripped = lines[index].strip()
        if stripped.startswith("#"):
            continue
        if stripped.startswith(f"{key} ") or stripped.startswith(f"{key}="):
            lines[index] = key_line
            return "\n".join(lines).rstrip() + "\n"
    lines.insert(end_index, key_line)
    return "\n".join(lines).rstrip() + "\n"


def remove_toml_table_key(text: str, table_name: str, key: str) -> str:
    lines = text.splitlines()
    bounds = find_table_bounds(lines, table_name)
    if bounds is None:
        return text
    start_index, end_index = bounds
    output: list[str] = []
    for index, line in enumerate(lines):
        if start_index < index < end_index:
            stripped = line.strip()
            if not stripped.startswith("#") and (stripped.startswith(f"{key} ") or stripped.startswith(f"{key}=")):
                continue
        output.append(line)
    return "\n".join(output).rstrip() + "\n"


def has_non_table_toml_content(text: str) -> bool:
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or line_opens_toml_table(line):
            continue
        return True
    return False


def read_toml_value(text: str, table_name: str, key: str) -> dict[str, Any]:
    try:
        data = tomllib.loads(text) if text.strip() else {}
    except tomllib.TOMLDecodeError:
        return {"exists": False, "value": None}
    table = data.get(table_name)
    if isinstance(table, dict) and key in table:
        return {"exists": True, "value": table[key]}
    return {"exists": False, "value": None}


def toml_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        return json.dumps(value)
    raise ValueError(f"unsupported TOML value for restore: {value!r}")


def remember_config_value(
    manifest: dict[str, Any],
    text: str,
    table_name: str,
    key: str,
) -> None:
    manifest_key = f"{table_name}.{key}"
    if manifest_key not in manifest["config_values"]:
        manifest["config_values"][manifest_key] = read_toml_value(text, table_name, key)


def patch_project_config(repo_root: Path, manifest: dict[str, Any], dry_run: bool) -> None:
    path = repo_root / ".codex" / "config.toml"
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    remember_config_value(manifest, original, "features", "codex_hooks")
    remember_config_value(manifest, original, "agents", "max_threads")
    remember_config_value(manifest, original, "agents", "max_depth")

    updated = remove_marked_block(original, MANAGED_CONFIG_START, MANAGED_CONFIG_END)
    updated = set_toml_table_key(updated, "features", "codex_hooks", "true")
    updated = set_toml_table_key(updated, "agents", "max_threads", "4")
    updated = set_toml_table_key(updated, "agents", "max_depth", "1")
    updated = updated.rstrip() + "\n\n" + project_config_block() + "\n"

    if updated == original:
        return
    if dry_run:
        if path.exists():
            print(f"would back up existing project config: {path} -> {next_backup_path(path)}")
        print(f"would patch project config: {path}")
        return
    if path.exists():
        backup_existing_path(path, repo_root, manifest, False, "project config")
    else:
        record_created_path(manifest, repo_root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    print(f"patched project config: {path}")


def restore_project_config(repo_root: Path, manifest: dict[str, Any], dry_run: bool) -> None:
    path = repo_root / ".codex" / "config.toml"
    if not path.exists():
        return
    original = path.read_text(encoding="utf-8")
    updated = remove_marked_block(original, MANAGED_CONFIG_START, MANAGED_CONFIG_END)
    for manifest_key, stored_value in manifest.get("config_values", {}).items():
        table_name, key = manifest_key.split(".", 1)
        if stored_value.get("exists"):
            updated = set_toml_table_key(updated, table_name, key, toml_literal(stored_value["value"]))
        else:
            updated = remove_toml_table_key(updated, table_name, key)
    if not has_non_table_toml_content(updated) and repo_relative_path(repo_root, path) in manifest.get("created_paths", []):
        remove_path(path, dry_run, "project config")
        return
    if updated == original:
        return
    if dry_run:
        print(f"would patch project config during uninstall: {path}")
        return
    backup_existing_path(path, repo_root, manifest, False, "project config before uninstall")
    path.write_text(updated, encoding="utf-8")
    print(f"removed project config entries: {path}")


def project_hook_wrapper(relative_vendor_root: Path) -> str:
    relative_hook = (relative_vendor_root / "hooks" / HOOK_FILE_NAME).as_posix()
    return f'''#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RELATIVE_VENDOR_HOOK = {relative_hook!r}


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


def print_skip(reason: str) -> int:
    print(json.dumps({{
        "hookSpecificOutput": {{
            "hookEventName": "UserPromptSubmit",
            "result": "skip",
            "reason": reason,
        }}
    }}))
    return 0


def main() -> int:
    hook_path = find_repo_root() / RELATIVE_VENDOR_HOOK
    if not hook_path.exists():
        return print_skip(f"vendored subagent orchestration hook is missing: {{hook_path}}")
    proc = subprocess.run(
        ["python3", str(hook_path)],
        input=sys.stdin.read(),
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return print_skip("vendored subagent orchestration hook failed open")
    print(proc.stdout, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def install_project_hook(
    repo_root: Path,
    source_root: Path,
    manifest: dict[str, Any],
    dry_run: bool,
    uses_vendor: bool,
) -> None:
    dst = repo_root / ".codex" / "hooks" / HOOK_FILE_NAME
    if uses_vendor:
        relative_vendor_root = source_root.relative_to(resolved_path(repo_root))
        write_project_text(
            dst,
            project_hook_wrapper(relative_vendor_root),
            repo_root,
            manifest,
            dry_run,
            "project hook",
            executable=True,
        )
        return

    src = source_root / "hooks" / HOOK_FILE_NAME
    if dry_run:
        if path_exists(dst) and not is_manifest_owned(manifest, repo_root, dst):
            backup_existing_path(dst, repo_root, manifest, True, "project hook")
        print(f"would install project hook: {src} -> {dst}")
        return
    prepare_project_destination(dst, repo_root, manifest, False, "project hook")
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    record_installed_path(manifest, repo_root, dst)
    print(f"installed project hook: {dst}")


def install_project_skills(
    repo_root: Path,
    source_root: Path,
    manifest: dict[str, Any],
    dry_run: bool,
    link_skills: bool,
    copy_skills: bool,
) -> None:
    skills_src = source_root / "plugin" / PLUGIN_NAME / "skills"
    skills_dst = repo_root / ".agents" / "skills"
    can_link_skills = link_skills and is_inside(repo_root, source_root)
    if link_skills and not can_link_skills:
        print("Skill symlink target is outside repo root; copying project skills instead.")
    for skill_name in [USING_SKILL_NAME, PLUGIN_NAME]:
        src = skills_src / skill_name
        dst = skills_dst / skill_name
        if can_link_skills and not copy_skills:
            if link_project_tree(src, dst, repo_root, manifest, dry_run, "project skill"):
                continue
        copy_project_tree(src, dst, repo_root, manifest, dry_run, "project skill")


def install_project_agents(
    repo_root: Path,
    source_root: Path,
    manifest: dict[str, Any],
    dry_run: bool,
) -> None:
    agents_source_root = source_root / "custom-agents"
    if not agents_source_root.exists():
        agents_source_root = ROOT / "custom-agents"
    for src in sorted(agents_source_root.glob("*.toml")):
        dst = repo_root / ".codex" / "agents" / src.name
        if dry_run:
            if path_exists(dst) and not is_manifest_owned(manifest, repo_root, dst):
                backup_existing_path(dst, repo_root, manifest, True, "project agent")
            print(f"would copy project agent: {src} -> {dst}")
            continue
        prepare_project_destination(dst, repo_root, manifest, False, "project agent")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        record_installed_path(manifest, repo_root, dst)
        print(f"copied project agent: {dst}")


def marketplace_plugin_entry(repo_root: Path, source_root: Path) -> dict[str, Any]:
    if is_inside(repo_root, source_root):
        plugin_path = "./" + (source_root.relative_to(resolved_path(repo_root)) / "plugin" / PLUGIN_NAME).as_posix()
    else:
        plugin_path = "./" + (PROJECT_VENDOR_PATH / "plugin" / PLUGIN_NAME).as_posix()
    return {
        "name": PLUGIN_NAME,
        "source": {
            "source": "local",
            "path": plugin_path,
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    }


def default_marketplace() -> dict[str, Any]:
    return {
        "name": "local-repo-plugins",
        "interface": {"displayName": "Local Repo Plugins"},
        "plugins": [],
    }


def patch_project_marketplace(
    repo_root: Path,
    source_root: Path,
    manifest: dict[str, Any],
    dry_run: bool,
) -> None:
    path = repo_root / ".agents" / "plugins" / "marketplace.json"
    original_text = path.read_text(encoding="utf-8") if path.exists() else ""
    data = json.loads(original_text) if original_text.strip() else default_marketplace()
    plugins = data.setdefault("plugins", [])
    previous_plugin = next((plugin for plugin in plugins if plugin.get("name") == PLUGIN_NAME), None)
    if "marketplace_previous_plugin" not in manifest:
        manifest["marketplace_previous_plugin"] = previous_plugin

    entry = marketplace_plugin_entry(repo_root, source_root)
    updated_plugins = [plugin for plugin in plugins if plugin.get("name") != PLUGIN_NAME]
    updated_plugins.append(entry)
    data["plugins"] = updated_plugins
    updated_text = json.dumps(data, indent=2) + "\n"
    if updated_text == original_text:
        return
    if dry_run:
        if path.exists():
            print(f"would back up existing repo marketplace: {path} -> {next_backup_path(path)}")
        print(f"would patch repo marketplace: {path}")
        return
    if path.exists():
        backup_existing_path(path, repo_root, manifest, False, "repo marketplace")
    else:
        record_created_path(manifest, repo_root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated_text, encoding="utf-8")
    print(f"patched repo marketplace: {path}")


def restore_project_marketplace(repo_root: Path, manifest: dict[str, Any], dry_run: bool) -> None:
    path = repo_root / ".agents" / "plugins" / "marketplace.json"
    if not path.exists():
        return
    original_text = path.read_text(encoding="utf-8")
    data = json.loads(original_text) if original_text.strip() else default_marketplace()
    previous_plugin = manifest.get("marketplace_previous_plugin")
    plugins = [plugin for plugin in data.get("plugins", []) if plugin.get("name") != PLUGIN_NAME]
    if previous_plugin:
        plugins.append(previous_plugin)
    data["plugins"] = plugins
    updated_text = json.dumps(data, indent=2) + "\n"
    if not plugins and repo_relative_path(repo_root, path) in manifest.get("created_paths", []):
        remove_path(path, dry_run, "repo marketplace")
        return
    if updated_text == original_text:
        return
    if dry_run:
        print(f"would patch repo marketplace during uninstall: {path}")
        return
    backup_existing_path(path, repo_root, manifest, False, "repo marketplace before uninstall")
    path.write_text(updated_text, encoding="utf-8")
    print(f"removed repo marketplace entry: {path}")


def append_project_agents_md(repo_root: Path, manifest: dict[str, Any], dry_run: bool) -> None:
    path = repo_root / "AGENTS.md"
    original = path.read_text(encoding="utf-8") if path.exists() else ""
    without_existing = remove_marked_block(original, MANAGED_AGENTS_START, MANAGED_AGENTS_END)
    updated = without_existing.rstrip() + "\n\n" + PROJECT_AGENTS_SECTION + "\n"
    if updated == original:
        return
    if dry_run:
        if path.exists():
            print(f"would back up existing project AGENTS.md: {path} -> {next_backup_path(path)}")
        print(f"would append project AGENTS.md guidance: {path}")
        return
    if path.exists():
        backup_existing_path(path, repo_root, manifest, False, "project AGENTS.md")
    else:
        record_created_path(manifest, repo_root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8")
    print(f"appended project AGENTS.md guidance: {path}")


def remove_project_agents_md(repo_root: Path, manifest: dict[str, Any], dry_run: bool) -> None:
    path = repo_root / "AGENTS.md"
    if not path.exists():
        return
    original = path.read_text(encoding="utf-8")
    updated = remove_marked_block(original, MANAGED_AGENTS_START, MANAGED_AGENTS_END)
    if updated.strip() == "" and repo_relative_path(repo_root, path) in manifest.get("created_paths", []):
        remove_path(path, dry_run, "project AGENTS.md")
        return
    if updated == original:
        return
    if dry_run:
        print(f"would remove project AGENTS.md guidance: {path}")
        return
    backup_existing_path(path, repo_root, manifest, False, "project AGENTS.md before uninstall")
    path.write_text(updated, encoding="utf-8")
    print(f"removed project AGENTS.md guidance: {path}")


def remove_installed_project_paths(repo_root: Path, manifest: dict[str, Any], dry_run: bool) -> None:
    for relative_path in sorted(manifest.get("installed_paths", []), key=lambda value: value.count("/"), reverse=True):
        path = repo_root / relative_path
        remove_path(path, dry_run, "project install path")


def restore_backups(repo_root: Path, manifest: dict[str, Any], dry_run: bool) -> None:
    specially_patched_paths = {
        ".codex/config.toml",
        ".agents/plugins/marketplace.json",
        "AGENTS.md",
    }
    for backup in reversed(manifest.get("backups", [])):
        if backup["path"] in specially_patched_paths:
            continue
        path = repo_root / backup["path"]
        backup_path = repo_root / backup["backup_path"]
        if not path_exists(backup_path):
            continue
        if dry_run:
            print(f"would restore backup: {backup_path} -> {path}")
            continue
        remove_path(path, False, "current project install path")
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(backup_path), str(path))
        print(f"restored backup: {path}")


def remove_empty_parent_dirs(repo_root: Path, dry_run: bool) -> None:
    for relative_path in [
        Path(".codex") / "agents",
        Path(".codex") / "hooks",
        Path(".agents") / "skills",
        Path(".agents") / "plugins",
        Path(".codex"),
        Path(".agents"),
    ]:
        path = repo_root / relative_path
        if path.exists() and path.is_dir() and not any(path.iterdir()):
            if dry_run:
                print(f"would remove empty directory: {path}")
            else:
                path.rmdir()
                print(f"removed empty directory: {path}")


def uninstall_project(args: argparse.Namespace) -> int:
    repo_root = detect_repo_root(args.repo_root)
    manifest_file = manifest_path(repo_root)
    if not manifest_file.exists():
        print(f"no project install manifest found: {manifest_file}")
        return 0
    manifest = load_project_manifest(repo_root)
    restore_project_config(repo_root, manifest, args.dry_run)
    restore_project_marketplace(repo_root, manifest, args.dry_run)
    remove_project_agents_md(repo_root, manifest, args.dry_run)
    remove_installed_project_paths(repo_root, manifest, args.dry_run)
    restore_backups(repo_root, manifest, args.dry_run)
    if args.dry_run:
        print(f"would remove install manifest: {manifest_file}")
    else:
        manifest_file.unlink()
        print(f"removed install manifest: {manifest_file}")
    remove_empty_parent_dirs(repo_root, args.dry_run)
    return 0


def install_project(args: argparse.Namespace) -> int:
    repo_root = detect_repo_root(args.repo_root)
    source_root = resolve_project_source_root(args, repo_root)
    validate_source_root(source_root)
    manifest = load_project_manifest(repo_root)

    install_project_skills(repo_root, source_root, manifest, args.dry_run, args.link_skills, args.copy_skills)

    if args.activate_gate:
        install_project_hook(repo_root, source_root, manifest, args.dry_run, bool(args.from_vendor))
        patch_project_config(repo_root, manifest, args.dry_run)
    else:
        print("Project gate not activated; pass --activate-gate to patch .codex/config.toml.")

    if args.with_project_agents:
        install_project_agents(repo_root, source_root, manifest, args.dry_run)
    if args.with_repo_marketplace:
        patch_project_marketplace(repo_root, source_root, manifest, args.dry_run)
        print("Repo marketplace entry added. Caveat: plugin UI enable/disable state is stored in ~/.codex/config.toml.")
    if args.append_project_agents_md:
        append_project_agents_md(repo_root, manifest, args.dry_run)

    write_manifest(repo_root, manifest, args.dry_run)
    return 0


def install_user(args: argparse.Namespace) -> int:
    should_install_hook = args.with_hook
    install_user_skill(args.dry_run)
    if should_install_hook:
        install_user_hook(args.dry_run)
    print_user_activation_notice(should_install_hook)
    return 0


def add_project_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo-root", help="Repository root for --scope project. Defaults to git rev-parse --show-toplevel.")
    parser.add_argument("--from-vendor", help="Vendored plugin root inside the repository.")
    parser.add_argument("--available-only", action="store_true", help="Install repo-local skills without activating the prompt gate.")
    parser.add_argument("--activate-gate", action="store_true", help="Patch project .codex/config.toml and install the project hook.")
    parser.add_argument("--link-skills", action="store_true", help="Symlink repo-local skills to the vendored plugin when possible.")
    parser.add_argument("--copy-skills", action="store_true", help="Copy repo-local skills instead of symlinking them.")
    parser.add_argument("--with-project-agents", action="store_true", help="Copy custom agents into project .codex/agents.")
    parser.add_argument("--append-project-agents-md", action="store_true", help="Append optional project guidance to AGENTS.md.")
    parser.add_argument("--with-repo-marketplace", action="store_true", help="Add or update .agents/plugins/marketplace.json.")
    parser.add_argument("--uninstall", action="store_true", help="Uninstall project-scope files recorded in the manifest.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install subagent orchestration skills and hook files."
    )
    parser.add_argument("--scope", choices=("user", "project"), default="user", help="Install scope. Defaults to user.")
    parser.add_argument("--skills-only", action="store_true", help="User scope: install only direct skills. This is the default.")
    parser.add_argument("--with-hook", action="store_true", help="User scope: copy the dormant UserPromptSubmit hook script.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without modifying files.")
    add_project_arguments(parser)
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if args.skills_only and args.with_hook:
        parser.error("--skills-only cannot be combined with --with-hook")
    if args.link_skills and args.copy_skills:
        parser.error("--link-skills cannot be combined with --copy-skills")
    if args.available_only and args.activate_gate:
        parser.error("--available-only cannot be combined with --activate-gate")

    project_only_flags = [
        "--repo-root" if args.repo_root else "",
        "--from-vendor" if args.from_vendor else "",
        "--available-only" if args.available_only else "",
        "--activate-gate" if args.activate_gate else "",
        "--link-skills" if args.link_skills else "",
        "--copy-skills" if args.copy_skills else "",
        "--with-project-agents" if args.with_project_agents else "",
        "--append-project-agents-md" if args.append_project_agents_md else "",
        "--with-repo-marketplace" if args.with_repo_marketplace else "",
        "--uninstall" if args.uninstall else "",
    ]
    used_project_flags = [flag for flag in project_only_flags if flag]
    if args.scope != "project" and used_project_flags:
        parser.error(f"{used_project_flags[0]} requires --scope project")
    if args.scope == "project" and (args.skills_only or args.with_hook):
        parser.error("--skills-only and --with-hook are only valid with --scope user")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    validate_args(parser, args)
    if args.scope == "project":
        if args.uninstall:
            return uninstall_project(args)
        return install_project(args)
    return install_user(args)


if __name__ == "__main__":
    raise SystemExit(main())
