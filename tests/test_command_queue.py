import pytest

from src.command_queue import CommandQueue


def test_command_queue_accepts_safe_commands(tmp_path):
    queue = CommandQueue(tmp_path / "commands.jsonl")

    queued = queue.enqueue("RUN_HYPOTHESIS_REPLAY", requested_by="123")

    assert queued.command == "RUN_HYPOTHESIS_REPLAY"
    assert queue.read_all()[0].requested_by == "123"


def test_command_queue_accepts_only_safe_control_commands(tmp_path):
    queue = CommandQueue(tmp_path / "commands.jsonl")

    for command in [
        "START_LIVE_RESEARCH",
        "STOP_LIVE_RESEARCH",
        "RESTART_LIVE_RESEARCH",
        "RUN_HYPOTHESIS_REPLAY",
        "GENERATE_PAPER_REPORT",
    ]:
        assert queue.enqueue(command, requested_by="123").command == command


def test_command_queue_rejects_trading_commands(tmp_path):
    queue = CommandQueue(tmp_path / "commands.jsonl")

    with pytest.raises(ValueError, match="not allowed"):
        queue.enqueue("REAL_ORDER", requested_by="123")

    with pytest.raises(ValueError, match="not allowed"):
        queue.enqueue("TESTNET_ORDER", requested_by="123")
