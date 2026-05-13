from __future__ import annotations

import json
import tomllib
from typing import Any


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
