#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

SYMBOLS="${SYMBOLS:-BTCUSDT}"

exec ./.venv/bin/python -m src.main live-research \
  --symbols "$SYMBOLS" \
  --tf 15m \
  --candidate-source production_like_raw \
  --run-forever \
  --interval-sec 60
