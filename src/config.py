from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class BinanceConfig(BaseModel):
    base_url: str = "https://fapi.binance.com"
    timeout_seconds: int = 10
    max_limit: int = 1500


class ResearchConfig(BaseModel):
    default_timeframe: str = Field(default_factory=lambda: os.getenv("RESEARCH_DEFAULT_TIMEFRAME", "15m"))
    report_dir: Path = Field(default_factory=lambda: Path(os.getenv("RESEARCH_REPORT_DIR", "data/reports")))
    shadow_log_dir: Path = Path("data/shadow_logs")
    binance: BinanceConfig = BinanceConfig()


def load_config(path: str | Path = "config/research_config.yaml") -> ResearchConfig:
    config_path = Path(path)
    if not config_path.exists():
        return ResearchConfig()

    with config_path.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}
    return ResearchConfig.model_validate(raw)
