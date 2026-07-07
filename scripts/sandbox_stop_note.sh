#!/usr/bin/env bash
set -euo pipefail

cat <<'EOF'
Sandbox stop guidance:
1. Prefer Telegram /live_stop.
2. Confirm data/runtime/runtime_status.json updates.
3. Preserve data/paper_trades/open_positions.json and data/paper_trades/closed_trades.csv.
4. Do not stop or modify production Crypto13.
EOF
