# Project Plan Map

## 1. Project Goal

Crypto13 Research Sandbox is a local/remote-safe research system for validating hypotheses and future adaptive architecture without real orders, real Binance trading keys, production DB writes, or automatic production changes.

The practical end state is online paper validation: public Binance candles -> signal candidates -> hypothesis evaluation -> virtual trades -> leaderboard -> human decision support.

## 2. What Is Done

- Journal replay mode exists.
- Old production journal compatibility exists for the uploaded closed-trades CSV.
- Historical candles were downloaded and coverage checked.
- RR replay and old-sample reports exist.
- Hypothesis registry and runner exist.
- Session normalization is fixed (`EU -> EUROPE`, `EU_US -> OVERLAP`).
- Hypothesis coverage audit exists.
- Research Pack 2 exists for old-sample research only.
- Public Binance kline client exists.
- Paper broker and portfolio primitives exist.
- Simplified live research polling exists.
- Telegram read-only/control panel exists with buttons.
- Safety guard blocks production/real/testnet order paths.

## 3. Where We Are Now

Status: **between old-sample research and Live Paper MVP**.

Old-history research should stop expanding. The next work should make the sandbox validate hypotheses prospectively on current market data.

Current readiness: **PARTIAL**.

The main blocker is paper lifecycle completeness in live mode: open virtual positions must be updated against each new closed candle, closed on TP/SL, persisted, and reported.

## 4. Next 3 Tasks

1. **Task 5B — Live Paper Lifecycle MVP**
   - Wire closed-candle loop to paper broker TP/SL tracking.
   - Persist open positions and closed paper trades.
   - Add restart-safe state loading.
   - Produce CLI live status and basic leaderboard.

2. **Task 5C — Candidate Adapter Boundary**
   - Decide and implement one safe candidate source:
     - placeholder LONG-only candle adapter, or
     - production candidate export import, or
     - production-like sandbox builder.
   - Keep source metadata explicit.

3. **Task 5D — Telegram Live Reporting**
   - Expose live status, open positions, closed trades, latest leaderboard, and final stop report through Telegram buttons.
   - Keep Telegram read-only/control-only.

## 5. Explicitly Stopped

- Expanding old-history research.
- Adding more hypothesis packs before live validation.
- Drawing production conclusions from the 98-trade old sample.
- Testnet/demo order work.
- GitHub/remote/deploy work until repo state is cleaned and user creates/approves remote.

## 6. Forbidden

- Modify `/Users/maksimmatveev/Desktop/Crypto13-main-4`.
- Connect Binance private/trading API.
- Add real orders.
- Add testnet orders without a separate explicit testnet task.
- Change production strategy, RR, TP, SL, leverage, risk, or filters.
- Store secrets in repo.
- Let sandbox automatically change production.

## 7. How Sandbox Will Help Production Later

1. Sandbox observes or imports production-like candidates.
2. It runs candidate decisions through hypotheses in paper mode.
3. It tracks virtual outcomes prospectively.
4. It builds evidence: winrate, PF, expectancy, drawdown, missed wins, blocked losses.
5. Human reviews evidence after enough trades.
6. If approved, a separate surgical production patch is written and tested.
7. Production never receives automatic changes from sandbox.
