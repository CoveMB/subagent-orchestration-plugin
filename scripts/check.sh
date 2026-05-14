#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 tests/test_hook.py
python3 tests/test_skills.py
python3 tests/test_evals.py
python3 tests/test_live_evals.py
python3 -m compileall -q hooks scripts tests
