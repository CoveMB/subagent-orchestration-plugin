#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
python3 scripts/install_user.py --uninstall "$@"
