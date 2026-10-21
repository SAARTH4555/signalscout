#!/usr/bin/env bash
# Regenerate every committed result and the README's results section. Offline only: the live
# run (results/live.json) is a separate, deliberate step in docs/runbook.md.
set -euo pipefail
cd "$(dirname "$0")/.."

uv run signalscout run --offline --out data/offline --report results/run_offline.json >/dev/null
uv run python scripts/eval_roles.py --out results/roles.json >/dev/null
uv run signalscout clay-spec
uv run python scripts/render_readme.py
