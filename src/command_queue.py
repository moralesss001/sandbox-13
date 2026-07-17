from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


DEFAULT_COMMAND_QUEUE_PATH = Path("data/runtime/commands.jsonl")

ALLOWED_COMMANDS = {
    "START_LIVE_PAPER",
    "START_LIVE_RESEARCH",
    "STOP_LIVE_RESEARCH",
    "RESTART_LIVE_RESEARCH",
    "RUN_HYPOTHESIS_REPLAY",
    "GENERATE_PAPER_REPORT",
}
FORBIDDEN_FRAGMENTS = {"ORDER", "TRADE", "TESTNET_ORDER", "REAL_ORDER", "ENABLE_REAL", "ENABLE_TESTNET"}


@dataclass
class QueuedCommand:
    command: str
    requested_by: str
    payload: dict[str, Any] = field(default_factory=dict)
    command_id: str = field(default_factory=lambda: uuid4().hex)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    status: str = "queued"


class CommandQueue:
    def __init__(self, path: str | Path = DEFAULT_COMMAND_QUEUE_PATH):
        self.path = Path(path)

    def enqueue(self, command: str, requested_by: str, payload: dict[str, Any] | None = None) -> QueuedCommand:
        normalized = command.strip().upper()
        if normalized not in ALLOWED_COMMANDS or any(fragment in normalized for fragment in FORBIDDEN_FRAGMENTS):
            raise ValueError(f"Command is not allowed in Telegram control queue: {command}")
        queued = QueuedCommand(normalized, str(requested_by), payload or {})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(queued.__dict__, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        return queued

    def read_all(self) -> list[QueuedCommand]:
        if not self.path.exists():
            return []
        commands = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            data = json.loads(line)
            commands.append(QueuedCommand(**data))
        return commands
