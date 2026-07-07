# Safety Checklist

- [ ] Production folder not touched
- [ ] No real orders
- [ ] No testnet orders
- [ ] No Binance private API
- [ ] No `.env` committed
- [ ] No secrets committed
- [ ] `candidate_source=production_like_raw`
- [ ] `timeframe=15m`
- [ ] `direction=LONG_ONLY`
- [ ] `edge_conclusions_allowed=false`
- [ ] Runtime status safety flags checked
- [ ] Telegram `/source` checked
- [ ] Telegram `/live_status` checked
- [ ] Telegram `/gates` checked

## Required Runtime Safety Flags

- `public_data_only: true`
- `private_api_used: false`
- `real_orders_enabled: false`
- `testnet_orders_enabled: false`

If any safety flag differs, stop and investigate inside sandbox only.
