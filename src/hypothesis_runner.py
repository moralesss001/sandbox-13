from __future__ import annotations

import csv
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .hypothesis_registry import HypothesisRegistry
from .order_models import HypothesisDecisionType, SignalCandidate, ensure_candidate_id, hypothesis_signal_id
from .paper_broker import PaperBroker
from .portfolio import PaperPortfolio


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _plain(item) for key, item in asdict(value).items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    return value


class HypothesisRunner:
    def __init__(
        self,
        registry: HypothesisRegistry | None = None,
        starting_balance_usdt: float = 1000.0,
        default_position_size_usdt: float = 100.0,
        leverage: float = 10.0,
        fee_rate: float = 0.0004,
        slippage_pct: float = 0.0005,
        intrabar_policy: str = "conservative",
        data_root: str | Path = "data",
        known_closed_signal_ids: set[str] | None = None,
        session_id: str | None = None,
    ):
        self.registry = registry or HypothesisRegistry()
        self.portfolios = {
            hypothesis.hypothesis_id: PaperPortfolio(hypothesis.hypothesis_id, starting_balance_usdt)
            for hypothesis in self.registry.enabled()
        }
        self.brokers = {
            hypothesis_id: PaperBroker(
                portfolio,
                position_size_usdt=default_position_size_usdt,
                leverage=leverage,
                fee_rate=fee_rate,
                slippage_pct=slippage_pct,
                intrabar_policy=intrabar_policy,
                known_closed_signal_ids=known_closed_signal_ids,
            )
            for hypothesis_id, portfolio in self.portfolios.items()
        }
        self.data_root = Path(data_root)
        self.session_id = session_id
        self.events: list[dict[str, Any]] = self._load_session_events() if session_id else []

    def process_signal(self, signal: SignalCandidate, close_from_history: bool = False) -> None:
        candidate_id = ensure_candidate_id(signal)
        for hypothesis in self.registry.enabled():
            decision = hypothesis.decide(signal)
            event = {
                "timestamp": datetime.now().isoformat(timespec="seconds"),
                "session_id": signal.session_id or self.session_id,
                "hypothesis_id": hypothesis.hypothesis_id,
                "candidate_id": candidate_id,
                "signal_id": hypothesis_signal_id(candidate_id, hypothesis.hypothesis_id),
                "symbol": signal.symbol,
                "timeframe": signal.timeframe,
                "decision": decision.decision,
                "block_reason": decision.block_reason or "",
                "signal_source": signal.signal_source,
                "candidate_source": signal.candidate_source,
                "candidate_source_version": signal.candidate_source_version,
                "is_placeholder": signal.is_placeholder,
                "edge_conclusions_allowed": signal.edge_conclusions_allowed,
                "direction_support": signal.direction_support,
                "market_phase": signal.market_phase,
                "session": signal.session,
                "setup_type": signal.setup_type,
                "rsi": signal.rsi,
                "atr_pct": signal.atr_pct,
                "production_signal_id": signal.production_signal_id,
                "entry": signal.entry,
                "sl": signal.sl,
                "tp": signal.tp,
                "rr_ratio": signal.rr_ratio,
                "risk_distance": signal.risk_distance,
                "reward_distance": signal.reward_distance,
                "actual_rr": signal.actual_rr,
                "sl_pct": signal.sl_pct,
                "score": signal.score,
                "pattern": signal.pattern,
                "supertrend_dir": signal.supertrend_dir,
                "macd": signal.macd,
                "volume": signal.volume,
                "trend_htf": signal.trend_htf,
                "market_mode_pre": signal.market_mode_pre,
                "market_mode_post": signal.market_mode_post,
                "production_would_allow": signal.production_would_allow,
                "production_block_reasons": "|".join(signal.production_block_reasons),
                "shadow_gate_block_reasons": "|".join(signal.shadow_gate_block_reasons),
                "historical_result": signal.result or "",
            }
            self.events.append(event)
            if decision.decision == HypothesisDecisionType.BLOCK.value:
                continue
            size_multiplier = 0.5 if decision.decision == HypothesisDecisionType.REDUCE_RISK.value else 1.0
            broker = self.brokers[hypothesis.hypothesis_id]
            broker.open_position(signal, size_multiplier=size_multiplier * decision.size_multiplier)
            if close_from_history:
                self._close_latest_from_history(broker, signal)

    def run_replay(self, signals: list[SignalCandidate]) -> dict[str, Any]:
        for signal in signals:
            self.process_signal(signal, close_from_history=True)
        paths = self.save_artifacts()
        return {
            "portfolios": self.portfolios,
            "events": self.events,
            "metrics": self.metrics(),
            "paths": paths,
            "signal_source": "journal_replay",
        }

    def metrics(self) -> dict[str, dict[str, Any]]:
        baseline = self.portfolios.get("baseline_rr15")
        baseline_net = baseline.net_R if baseline else 0.0
        metrics: dict[str, dict[str, Any]] = {}
        for hypothesis_id, portfolio in self.portfolios.items():
            item = portfolio.metrics(baseline_net_R=baseline_net)
            if self.session_id:
                item["session_id"] = self.session_id
            item["trades_blocked"] = sum(
                1
                for event in self.events
                if event["hypothesis_id"] == hypothesis_id and event["decision"] == HypothesisDecisionType.BLOCK.value
            )
            item["blocked_losses"] = self._blocked_count(hypothesis_id, "loss")
            item["missed_wins"] = self._blocked_count(hypothesis_id, "win")
            metrics[hypothesis_id] = item
        return metrics

    def save_artifacts(self) -> dict[str, str]:
        if self.session_id:
            paths = {
                "paper_trades": str(self.data_root / "reports" / "paper_trades_snapshot.csv"),
                "paper_portfolios": str(self.data_root / "reports" / "portfolio_snapshot.csv"),
                "hypothesis_events": str(self.data_root / "events" / "hypothesis_events.csv"),
            }
        else:
            date = datetime.now().strftime("%Y%m%d")
            paths = {
                "paper_trades": str(self.data_root / "paper_trades" / f"paper_trades_{date}.csv"),
                "paper_portfolios": str(self.data_root / "paper_portfolios" / f"portfolio_snapshots_{date}.csv"),
                "hypothesis_events": str(self.data_root / "hypothesis_events" / f"hypothesis_events_{date}.csv"),
            }
        if self.session_id:
            self._write_session_events(paths["hypothesis_events"], self.events)
        else:
            self._write_rows(paths["hypothesis_events"], self.events)

        trade_rows = []
        for portfolio in self.portfolios.values():
            trade_rows.extend(_plain(trade) for trade in portfolio.closed_trades)
        self._write_rows(paths["paper_trades"], trade_rows)
        self._write_rows(paths["paper_portfolios"], list(self.metrics().values()))
        return paths

    def _close_latest_from_history(self, broker: PaperBroker, signal: SignalCandidate) -> None:
        if not broker.portfolio.open_positions:
            return
        position = broker.portfolio.open_positions[-1]
        result = str(signal.result or "").lower()
        if result == "win":
            broker.close_position(position, reason="TP_REPLAY", exit_price=position.tp)
        elif result == "loss":
            broker.close_position(position, reason="SL_REPLAY", exit_price=position.sl)

    def _blocked_count(self, hypothesis_id: str, result: str) -> int:
        count = 0
        for event in self.events:
            if event["hypothesis_id"] != hypothesis_id or event["decision"] != HypothesisDecisionType.BLOCK.value:
                continue
            raw_result = str(event.get("historical_result", "")).lower()
            if raw_result == result:
                count += 1
        return count

    def _write_rows(self, path: str, rows: list[dict[str, Any]]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            target.write_text("", encoding="utf-8")
            return
        rows = [self._serialize_row(row) for row in rows]
        fields = sorted({key for row in rows for key in row.keys()})
        with target.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def _serialize_row(self, row: dict[str, Any]) -> dict[str, Any]:
        for key in ["production_block_reasons", "shadow_gate_block_reasons"]:
            value = row.get(key)
            if isinstance(value, list):
                row[key] = "|".join(str(item) for item in value)
        if isinstance(row.get("shadow_gates"), list):
            row["shadow_gates"] = json.dumps(row["shadow_gates"], ensure_ascii=False, sort_keys=True)
        return row

    def _write_session_events(self, path: str, rows: list[dict[str, Any]]) -> None:
        target = Path(path)
        existing: list[dict[str, Any]] = []
        if target.exists() and target.stat().st_size:
            with target.open("r", encoding="utf-8", newline="") as handle:
                existing = list(csv.DictReader(handle))
        identities = {
            (str(row.get("candidate_id") or ""), str(row.get("hypothesis_id") or ""))
            for row in existing
        }
        additions = []
        for row in rows:
            identity = (
                str(row.get("candidate_id") or ""),
                str(row.get("hypothesis_id") or ""),
            )
            if identity in identities:
                continue
            identities.add(identity)
            additions.append(row)
        self._write_rows(path, [*existing, *additions])

    def _load_session_events(self) -> list[dict[str, Any]]:
        target = self.data_root / "events" / "hypothesis_events.csv"
        if not target.exists() or not target.stat().st_size:
            return []
        with target.open("r", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return [
            row
            for row in rows
            if not row.get("session_id") or row.get("session_id") == self.session_id
        ]
