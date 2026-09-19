#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHONPATH=src python3 -m sparkie.demo examples/meeting.jsonl --output output/meeting.json
