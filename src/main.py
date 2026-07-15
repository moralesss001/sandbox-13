from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
import yaml

from .binance_data import get_latest_klines, save_klines_csv
from .candidate_sources import CandidateSourceType
from .demo_report_builder import build_demo_report
from .execution_safety import validate_api_mode
from .hypothesis_runner import HypothesisRunner
from .live_research_engine import LiveResearchEngine
from .replay_engine import ReplayEngine
from .report_builder import build_report
from .run_all import run_all
from .runtime_status import RuntimeStatusStore
from .signal_adapter import signals_from_journal
from .telegram_bot import run_telegram_bot
from .telegram_control import TelegramControlPanel
from .testnet_broker import TestnetBroker


DEFAULT_CONFIG = Path("config/research_config.yaml")


def _load_config(path: str | Path = DEFAULT_CONFIG) -> dict:
    config_path = Path(path)
    if not config_path.exists():
        return {}
    return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crypto13 research sandbox CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    replay = subparsers.add_parser("replay", help="Run Journal Replay Mode")
    replay.add_argument("--file", required=True, help="Path to journal CSV")
    replay.add_argument("--tf", default="15m", help="Timeframe filter, default 15m")
    replay.add_argument("--out", default="data/reports", help="Report output directory")

    hypothesis = subparsers.add_parser("hypothesis-replay", help="Run hypothesis replay with paper portfolios")
    hypothesis.add_argument("--file", required=True, help="Path to journal CSV")
    hypothesis.add_argument("--tf", default="15m", help="Timeframe filter")
    hypothesis.add_argument("--out", default="data/demo_reports", help="Demo report output directory")

    live = subparsers.add_parser("live-research", help="Run safe paper live research polling")
    live.add_argument("--symbols", required=True, help="Comma-separated symbols, e.g. BTCUSDT,ETHUSDT")
    live.add_argument("--tf", default="15m", help="Timeframe")
    live.add_argument("--interval-sec", type=int, default=60, help="Polling interval")
    live.add_argument("--max-iterations", type=int, default=1, help="Safe smoke default is one iteration")
    live.add_argument("--run-forever", action="store_true", help="Run continuously for VPS paper research")
    live.add_argument(
        "--candidate-source",
        default=CandidateSourceType.SIMPLIFIED_PLACEHOLDER.value,
        choices=[
            CandidateSourceType.SIMPLIFIED_PLACEHOLDER.value,
            CandidateSourceType.PRODUCTION_LIKE_RAW.value,
        ],
        help="Live research candidate source",
    )
    live.add_argument("--out", default="data/demo_reports", help="Demo report output directory")

    fetch = subparsers.add_parser("fetch-klines", help="Fetch Binance Futures public klines")
    fetch.add_argument("--symbol", required=True)
    fetch.add_argument("--tf", default="15m")
    fetch.add_argument("--limit", type=int, default=500)
    fetch.add_argument("--out", default="data/live_market")

    paper_report = subparsers.add_parser("paper-report", help="Print latest paper portfolio snapshot")
    paper_report.add_argument("--file", default=None, help="Optional portfolio snapshot CSV")

    smoke = subparsers.add_parser("testnet-smoke", help="Verify testnet safety guard")
    smoke.add_argument("--symbol", required=True)
    smoke.add_argument("--tf", default="15m")
    smoke.add_argument("--confirm-testnet-order", action="store_true")

    telegram = subparsers.add_parser("telegram-bot", help="Run Telegram read-only control bot")
    telegram.add_argument("--once", action="store_true", help="Poll once for smoke tests")

    run_all_parser = subparsers.add_parser("run-all", help="Run Railway single-service sandbox supervisor")
    run_all_parser.add_argument("--dry-run", action="store_true", help="Print run-all plan and exit")

    subparsers.add_parser("status", help="Print runtime status")
    subparsers.add_parser("safety-status", help="Print safety status")
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    config = _load_config()
    safety_config = {"mode": config.get("api", {}).get("mode", "paper"), **config.get("safety", {})}
    validate_api_mode(safety_config)

    if args.command == "replay":
        replay_df, warnings = ReplayEngine().run(args.file, timeframe=args.tf)
        report_path = build_report(replay_df, warnings, out_dir=Path(args.out), source_file=args.file)
        print(f"Replay rows: {len(replay_df)}")
        print(f"Report created: {report_path}")
        if warnings:
            print("Warnings:")
            for warning in warnings:
                print(f"- {warning}")
    elif args.command == "hypothesis-replay":
        paper_cfg = config.get("paper_trading", {})
        signals, warnings = signals_from_journal(args.file, timeframe=args.tf)
        runner = HypothesisRunner(
            starting_balance_usdt=float(paper_cfg.get("starting_balance_usdt", 1000)),
            default_position_size_usdt=float(paper_cfg.get("default_position_size_usdt", 100)),
            leverage=float(paper_cfg.get("leverage", 10)),
            fee_rate=float(paper_cfg.get("fee_rate", 0.0004)),
            slippage_pct=float(paper_cfg.get("slippage_pct", 0.0005)),
            intrabar_policy=str(paper_cfg.get("intrabar_policy", "conservative")),
        )
        result = runner.run_replay(signals)
        report_path = build_demo_report(result, out_dir=args.out, source_file=args.file, signal_source="journal_replay")
        print(f"Signals replayed: {len(signals)}")
        print(f"Demo report created: {report_path}")
        if warnings:
            print("Warnings:")
            for warning in warnings:
                print(f"- {warning}")
    elif args.command == "live-research":
        symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
        engine = LiveResearchEngine(config)
        result = engine.run(
            symbols=symbols,
            timeframe=args.tf,
            interval_sec=args.interval_sec,
            max_iterations=args.max_iterations,
            run_forever=args.run_forever,
            candidate_source=args.candidate_source,
        )
        report_path = build_demo_report(
            result,
            out_dir=args.out,
            source_file="binance_public_rest",
            signal_source=result.get("signal_source", "research_simplified_live"),
        )
        engine.mark_latest_report(report_path)
        print(f"Live research iterations: {args.max_iterations}")
        print(f"Signal source: {result.get('signal_source')}")
        print(f"Demo report created: {report_path}")
    elif args.command == "fetch-klines":
        public_base_url = config.get("api", {}).get("public_base_url", "https://fapi.binance.com")
        df = get_latest_klines(args.symbol, args.tf, limit=args.limit, base_url=public_base_url)
        path = Path(args.out) / f"live_market_{datetime.now().strftime('%Y%m%d')}_{args.symbol.upper()}_{args.tf}.csv"
        saved = save_klines_csv(df, str(path))
        print(f"Klines fetched: {len(df)}")
        print(f"Saved: {saved}")
    elif args.command == "paper-report":
        snapshot = Path(args.file) if args.file else _latest_snapshot(Path("data/paper_portfolios"))
        if snapshot is None or not snapshot.exists():
            print("No paper portfolio snapshot found.")
            return
        df = pd.read_csv(snapshot)
        print(f"Paper portfolio snapshot: {snapshot}")
        print(df.to_markdown(index=False))
    elif args.command == "testnet-smoke":
        api_cfg = config.get("api", {})
        safety = config.get("safety", {})
        broker = TestnetBroker(
            base_url=api_cfg.get("testnet_base_url", "https://demo-fapi.binance.com"),
            allow_testnet_orders=bool(safety.get("allow_testnet_orders", False)),
            confirmed=args.confirm_testnet_order,
        )
        try:
            result = broker.place_testnet_order(symbol=args.symbol, timeframe=args.tf)
        except RuntimeError as exc:
            print(f"Testnet smoke blocked safely: {exc}")
            return
        print(result)
    elif args.command == "telegram-bot":
        try:
            run_telegram_bot(once=args.once)
        except RuntimeError as exc:
            print(f"Telegram bot blocked safely: {exc}")
            return
    elif args.command == "run-all":
        run_all(dry_run=args.dry_run)
    elif args.command == "status":
        print(TelegramControlPanel(status_store=RuntimeStatusStore()).status())
    elif args.command == "safety-status":
        print(TelegramControlPanel(status_store=RuntimeStatusStore()).safety())


def _latest_snapshot(root: Path) -> Path | None:
    if not root.exists():
        return None
    files = sorted(root.glob("portfolio_snapshots_*.csv"))
    return files[-1] if files else None


if __name__ == "__main__":
    main()
