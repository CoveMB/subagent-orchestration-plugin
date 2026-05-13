from __future__ import annotations

import fnmatch
import filecmp
import shutil
from pathlib import Path
from typing import Iterable


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


def backup_path(path: Path, dry_run: bool, label: str, move: bool = True) -> Path | None:
    if not path_exists(path):
        return None
    backup = next_backup_path(path)
    if dry_run:
        print(f"would back up existing {label}: {path} -> {backup}")
        return backup
    backup.parent.mkdir(parents=True, exist_ok=True)
    if move:
        shutil.move(str(path), str(backup))
    elif path.is_dir() and not path.is_symlink():
        shutil.copytree(path, backup)
    else:
        shutil.copy2(path, backup)
    print(f"backed up existing {label}: {path} -> {backup}")
    return backup


def names_match_ignored_patterns(path: Path, ignore_patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatch(part, pattern) for part in path.parts for pattern in ignore_patterns)


def comparable_files(root: Path, ignore_patterns: Iterable[str]) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        relative_path = path.relative_to(root)
        if names_match_ignored_patterns(relative_path, ignore_patterns):
            continue
        if path.is_file() and not path.is_symlink():
            files.append(relative_path)
    return files


def content_matches(src: Path, dst: Path, ignore_patterns: Iterable[str] = ()) -> bool:
    if not path_exists(src) or not path_exists(dst):
        return False
    if src.is_file() and dst.is_file() and not src.is_symlink() and not dst.is_symlink():
        return filecmp.cmp(src, dst, shallow=False)
    if src.is_dir() and dst.is_dir() and not src.is_symlink() and not dst.is_symlink():
        src_files = comparable_files(src, ignore_patterns)
        dst_files = comparable_files(dst, ignore_patterns)
        return src_files == dst_files and all(
            filecmp.cmp(src / relative_path, dst / relative_path, shallow=False)
            for relative_path in src_files
        )
    return False
