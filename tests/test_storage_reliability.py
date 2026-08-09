from __future__ import annotations

import csv
import errno
import json
import os
from collections import namedtuple
from hashlib import sha256

import pytest

from src.live_paper_storage import (
    ClosedTradesRollbackError,
    ClosedTradesSchemaError,
    LivePaperStorage,
)
from src.order_models import Position, Trade


def _trade(index: int, *, session_id: str = "research-20260809T000000000000Z-1234abcd") -> Trade:
    return Trade(
        trade_id=f"trade-{index}",
        hypothesis_id="baseline_rr15",
        symbol="BTCUSDT",
        timeframe="15m",
        direction="LONG",
        entry_time="2026-08-09T00:00:00+00:00",
        entry_price=100.0,
        tp=107.5,
        sl=95.0,
        rr_ratio=1.5,
        position_size_usdt=100.0,
        leverage=10.0,
        session_id=session_id,
        candidate_id=f"candidate-{index}",
        signal_id=f"signal-{index}",
        status="CLOSED",
        exit_time="2026-08-09T00:15:00+00:00",
        exit_price=107.5,
        result="win",
        r=1.5,
        pnl_usdt=150.0,
    )


def test_closed_trades_many_batches_are_append_only_and_deduplicated(monkeypatch, tmp_path):
    storage = LivePaperStorage(tmp_path)
    read_calls = 0
    original_read = storage._read_closed_rows

    def counted_read():
        nonlocal read_calls
        read_calls += 1
        return original_read()

    monkeypatch.setattr(storage, "_read_closed_rows", counted_read)
    first_batch = [_trade(index) for index in range(1000)]
    storage.append_closed_trades(first_batch)
    inode = storage.closed_trades_path.stat().st_ino

    for batch_index in range(1, 20):
        batch = [_trade(batch_index * 1000 + offset) for offset in range(1000)]
        storage.append_closed_trades(batch)
        storage.append_closed_trades(batch)

    with storage.closed_trades_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    header_line = storage.closed_trades_path.read_text(encoding="utf-8").splitlines()[0]

    assert len(rows) == 20_000
    assert len({row["signal_id"] for row in rows}) == 20_000
    assert storage.closed_trades_count() == 20_000
    assert storage.closed_trades_path.stat().st_ino == inode
    assert storage.closed_trades_path.with_suffix(".csv.tmp").exists() is False
    assert storage.closed_trades_path.read_text(encoding="utf-8").count(header_line) == 1
    assert read_calls == 1


def test_duplicate_is_rejected_across_storage_instances(tmp_path):
    first = LivePaperStorage(tmp_path)
    second = LivePaperStorage(tmp_path)
    trade = _trade(1)
    assert first.closed_trades_count() == 0
    assert second.closed_trades_count() == 0

    first.append_closed_trades([trade])
    second.append_closed_trades([trade])

    assert LivePaperStorage(tmp_path).closed_trades_count() == 1


def test_restart_reuses_one_csv_scan_for_ids_trades_and_count(monkeypatch, tmp_path):
    writer = LivePaperStorage(tmp_path)
    writer.append_closed_trades([_trade(index) for index in range(10)])
    restarted = LivePaperStorage(tmp_path)
    read_calls = 0
    original_read = restarted._read_closed_rows

    def counted_read():
        nonlocal read_calls
        read_calls += 1
        return original_read()

    monkeypatch.setattr(restarted, "_read_closed_rows", counted_read)

    assert len(restarted.closed_signal_ids()) == 10
    assert len(restarted.load_closed_trades()) == 10
    assert restarted.closed_trades_count() == 10
    assert read_calls == 1


def test_existing_reordered_schema_and_missing_final_newline_are_preserved(tmp_path):
    storage = LivePaperStorage(tmp_path)
    storage.append_closed_trades([_trade(1)])
    with storage.closed_trades_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        row = next(reader)
        original_fields = list(reader.fieldnames or [])
    fields = ["legacy_note", *reversed(original_fields)]
    values = {"legacy_note": "legacy", **row}
    storage.closed_trades_path.write_text(
        ",".join(fields) + "\r\n" + ",".join(str(values.get(field, "")) for field in fields),
        encoding="utf-8",
    )

    restarted = LivePaperStorage(tmp_path)
    restarted.append_closed_trades([_trade(2)])

    with restarted.closed_trades_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert reader.fieldnames == fields
    assert len(rows) == 2
    assert rows[0]["legacy_note"] == "legacy"
    assert rows[1]["legacy_note"] == ""


def test_schema_mismatch_fails_before_append_and_preserves_file(tmp_path):
    storage = LivePaperStorage(tmp_path)
    storage.append_closed_trades([_trade(1)])
    with storage.closed_trades_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        row = next(reader)
        fields = [field for field in (reader.fieldnames or []) if field != "session_id"]
    with storage.closed_trades_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in fields})
    original = storage.closed_trades_path.read_bytes()

    with pytest.raises(ClosedTradesSchemaError, match="schema mismatch"):
        LivePaperStorage(tmp_path).append_closed_trades([_trade(2)])

    assert storage.closed_trades_path.read_bytes() == original


def test_closed_identity_is_not_kept_as_unresolved_after_open_file_write_failure(tmp_path):
    storage = LivePaperStorage(tmp_path)
    trade = _trade(1)
    position_payload = {
        field: getattr(trade, field)
        for field in Position.__dataclass_fields__
    }
    position_payload["status"] = "OPEN"
    storage.open_positions_path.write_text(
        json.dumps([position_payload]),
        encoding="utf-8",
    )
    storage.append_closed_trades([trade])

    unresolved = storage.mark_open_positions_unresolved(
        closed_signal_ids=storage.closed_signal_ids()
    )

    assert unresolved == 0
    assert json.loads(storage.open_positions_path.read_text(encoding="utf-8")) == []
    assert storage.closed_trades_count() == 1


def test_partial_enospc_append_rolls_back_exact_original_file(monkeypatch, tmp_path):
    storage = LivePaperStorage(tmp_path)
    storage.append_closed_trades([_trade(1)])
    original = storage.closed_trades_path.read_bytes()
    original_inode = storage.closed_trades_path.stat().st_ino
    original_hash = sha256(original).hexdigest()
    real_write = os.write
    calls = 0

    def partial_then_enospc(descriptor, payload):
        nonlocal calls
        calls += 1
        if calls == 1:
            size = min(32, len(payload))
            return real_write(descriptor, payload[:size])
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr("src.live_paper_storage.os.write", partial_then_enospc)
    with pytest.raises(OSError) as exc_info:
        storage.append_closed_trades([_trade(2)])

    assert exc_info.value.errno == errno.ENOSPC
    assert storage.closed_trades_path.stat().st_ino == original_inode
    assert storage.closed_trades_path.read_bytes() == original
    assert sha256(storage.closed_trades_path.read_bytes()).hexdigest() == original_hash
    assert storage.closed_trades_count() == 1
    assert storage.closed_trades_path.with_suffix(".csv.tmp").exists() is False


def test_fsync_failure_rolls_back_and_allows_clean_retry(monkeypatch, tmp_path):
    storage = LivePaperStorage(tmp_path)
    storage.append_closed_trades([_trade(1)])
    original = storage.closed_trades_path.read_bytes()
    real_fsync = os.fsync
    calls = 0

    def fail_first_fsync(descriptor):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_fsync(descriptor)

    monkeypatch.setattr("src.live_paper_storage.os.fsync", fail_first_fsync)
    with pytest.raises(OSError):
        storage.append_closed_trades([_trade(2)])
    assert storage.closed_trades_path.read_bytes() == original

    monkeypatch.setattr("src.live_paper_storage.os.fsync", real_fsync)
    storage.append_closed_trades([_trade(2)])
    assert storage.closed_trades_count() == 2


def test_failed_append_does_not_poison_dedup_cache(monkeypatch, tmp_path):
    storage = LivePaperStorage(tmp_path)
    real_write = os.write
    monkeypatch.setattr(
        "src.live_paper_storage.os.write",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError(errno.ENOSPC, "No space left on device")
        ),
    )
    with pytest.raises(OSError):
        storage.append_closed_trades([_trade(1)])

    monkeypatch.setattr("src.live_paper_storage.os.write", real_write)
    storage.append_closed_trades([_trade(1)])
    assert storage.closed_trades_count() == 1


def test_rollback_failure_is_explicit(monkeypatch, tmp_path):
    storage = LivePaperStorage(tmp_path)
    storage.append_closed_trades([_trade(1)])
    monkeypatch.setattr(
        "src.live_paper_storage.os.write",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError(errno.ENOSPC, "No space left on device")
        ),
    )
    monkeypatch.setattr(
        "src.live_paper_storage.os.ftruncate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError(errno.EIO, "rollback failed")),
    )

    with pytest.raises(ClosedTradesRollbackError) as exc_info:
        storage.append_closed_trades([_trade(2)])

    assert exc_info.value.errno == errno.EIO


@pytest.mark.parametrize(
    ("used", "expected"),
    [(69, "normal"), (70, "warning"), (85, "high"), (95, "critical")],
)
def test_disk_usage_thresholds(monkeypatch, tmp_path, used, expected):
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(
        "src.live_paper_storage.shutil.disk_usage",
        lambda _path: Usage(100, used, 100 - used),
    )

    diagnostics = LivePaperStorage(tmp_path).diagnostics()

    assert diagnostics["storage_usage"]["level"] == expected
    assert diagnostics["storage_usage"]["used_percent"] == float(used)


def test_disk_usage_failure_is_non_fatal(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "src.live_paper_storage.shutil.disk_usage",
        lambda _path: (_ for _ in ()).throw(OSError("stats unavailable")),
    )

    diagnostics = LivePaperStorage(tmp_path).diagnostics()

    assert diagnostics["storage_usage"]["available"] is False
    assert diagnostics["storage_usage"]["level"] == "unknown"
