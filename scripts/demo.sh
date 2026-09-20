#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --frozen python -m sparkie.demo examples/meeting.jsonl --output output/meeting.json
