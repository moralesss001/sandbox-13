from __future__ import annotations

from datetime import datetime
from pathlib import Path
from time import sleep


class LiveShadowEngine:
    def __init__(self, log_dir: str | Path = "data/shadow_logs"):
        self.log_dir = Path(log_dir)

    def run_once(self) -> Path:
        """Write a local virtual decision placeholder without trading."""
        self.log_dir.mkdir(parents=True, exist_ok=True)
        path = self.log_dir / f"shadow_{datetime.now().strftime('%Y%m%d')}.jsonl"
        path.open("a", encoding="utf-8").write(
            '{"event":"live_shadow_placeholder","trading":"disabled","orders_sent":false}\n'
        )
        return path

    def run_loop(self, interval_seconds: int = 60):
        """Local-only loop. Stops when the Mac/process stops."""
        while True:
            self.run_once()
            sleep(interval_seconds)
