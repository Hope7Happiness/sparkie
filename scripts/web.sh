#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --frozen
npm --prefix frontend ci
exec npm --prefix frontend run dev
