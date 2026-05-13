#!/usr/bin/env python3
from __future__ import annotations

from install_user import uninstall_user


def main() -> int:
    return uninstall_user(False)


if __name__ == "__main__":
    raise SystemExit(main())
