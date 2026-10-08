from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from src import multi_strategy_lifecycle as ml
from src import strategy_packages as sp
from src import package_shadow_runtime as psr
from src.live_paper_storage import ShadowJournal
from src.live_shadow import legacy_snapshot
from src.package_shadow_runtime import GuardedJournal


NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    original_popen = subprocess.Popen
    def forbidden(*args, **kwargs):
        raise AssertionError('Network and subprocesses are forbidden')
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr('src.live_shadow.subprocess.check_output', lambda *args, **kwargs: 'fixture-revision')
    return original_popen


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


class Runtimes:
    def __init__(self):
        self.lock = threading.Lock()
        self.started = []
        self.paths = []
        self.gates = {}
        self.fail = set()
        self.active = 0
        self.peak = 0

    def release(self, sid):
        with self.lock:
            self.gates.setdefault(sid, threading.Event()).set()

    def __call__(self, package, path, should_stop):
        owner = self
        sid = package['strategy_id']

        class Runtime:
            def run(self):
                with owner.lock:
                    gate = owner.gates.setdefault(sid, threading.Event())
                    owner.started.append(sid)
                    owner.paths.append(Path(path))
                    owner.active += 1
                    owner.peak = max(owner.peak, owner.active)
                try:
                    while not should_stop() and not gate.wait(0.005):
                        pass
                    if sid in owner.fail:
                        raise RuntimeError('synthetic failure: ' + sid)
                    return {'fixture_strategy': sid, 'positions': {'unresolved': {'entry_notional': '100'}}}
                finally:
                    with owner.lock:
                        owner.active -= 1
        return Runtime()


def eventually(predicate):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.005)
    assert predicate(), 'Timed out waiting for fixture state'


def states(lifecycle):
    return {row['session_id']: row['state'] for row in lifecycle.status()}


def wait_completed_worker(lifecycle, session_id):
    # SQLite completion precedes report fsync and actual thread termination.
    worker = lifecycle.workers[session_id]
    worker.join(timeout=5)
    assert not worker.is_alive(), 'Worker still finalizing'
    assert states(lifecycle)[session_id] == 'completed'


@pytest.fixture
def harness(tmp_path):
    clock = Clock()
    runtime = Runtimes()
    store = sp.PackageStore(tmp_path / 'packages.sqlite3')
    owners = []

    def approve(sid, seconds=3600, version='1'):
        package = sp.example_package(sid, version, (NOW + timedelta(seconds=seconds)).isoformat())
        store.upload(json.dumps(package))
        store.validate(sid, version, NOW)
        store.approve(sid, version, NOW)
        return package

    def owner(limit=2, root=None, factory=None):
        lifecycle = ml.Lifecycle(root or tmp_path / 'lifecycle', store.path, limit, factory or runtime, clock)
        owners.append(lifecycle)
        return lifecycle

    yield approve, owner, runtime, clock, store
    for lifecycle in reversed(owners):
        lifecycle.close()
    store.close()


def test_concurrency_fifo_and_independent_paths(harness):
    approve, owner, runtime, _, _ = harness
    lifecycle = owner()
    ids = []
    for sid in ['a', 'b', 'c', 'd']:
        approve(sid)
        ids.append(lifecycle.enqueue(sid, '1'))
    assert runtime.started == []
    assert [r['strategy_id'] for r in lifecycle.status()] == ['a', 'b', 'c', 'd']
    assert [r['seq'] for r in lifecycle.status()] == sorted(r['seq'] for r in lifecycle.status())
    lifecycle.tick()
    eventually(lambda: len(runtime.started) == 2)
    assert set(runtime.started) == {'a', 'b'}
    lifecycle.tick()
    assert states(lifecycle)[ids[2]] == states(lifecycle)[ids[3]] == 'queued'
    runtime.release('b')
    wait_completed_worker(lifecycle, ids[1])
    lifecycle.tick()
    eventually(lambda: 'c' in runtime.started)
    assert 'd' not in runtime.started
    runtime.release('a')
    wait_completed_worker(lifecycle, ids[0])
    lifecycle.tick()
    eventually(lambda: 'd' in runtime.started)
    assert runtime.peak == 2
    assert len(set(runtime.paths)) == 4
    assert {path.name for path in runtime.paths} == set(ids)
    assert all(path.parent == lifecycle.root / 'sessions' for path in runtime.paths)


def test_concurrent_enqueue_idempotent_and_versions_distinct(harness):
    approve, owner, runtime, _, _ = harness
    approve('a')
    approve('a', version='2')
    lifecycle = owner()
    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(lambda _: lifecycle.enqueue('a', '1'), range(16)))
    assert len(set(ids)) == 1
    assert lifecycle.enqueue('a', '2') != ids[0]
    assert len(lifecycle.status()) == 2
    assert not runtime.started


@pytest.mark.parametrize('status', ['uploaded', 'validated', 'rejected'])
def test_unapproved_package_never_enters_queue(harness, status):
    _, owner, runtime, _, store = harness
    package = sp.example_package('unapproved', '1', (NOW + timedelta(hours=1)).isoformat())
    store.upload(json.dumps(package))
    if status == 'validated':
        store.validate('unapproved', '1', NOW)
    elif status == 'rejected':
        store.reject('unapproved', '1', 'fixture rejection')
    lifecycle = owner()
    with pytest.raises(sp.PackageError, match='only approved'):
        lifecycle.enqueue('unapproved', '1')
    lifecycle.tick()
    assert lifecycle.status() == []
    assert runtime.started == []


def test_restart_preserves_fifo_queue_behind_recovered_worker(harness):
    approve, owner, runtime, _, _ = harness
    for name in ['a', 'b', 'c']:
        approve(name)
    first = owner(limit=1)
    ids = [first.enqueue(name, '1') for name in ['a', 'b', 'c']]
    first.tick()
    eventually(lambda: runtime.started == ['a'])
    first.close()
    second = owner(limit=1)
    assert [r['session_id'] for r in second.status()] == ids
    assert [r['state'] for r in second.status()] == ['paused', 'queued', 'queued']
    second.tick()
    eventually(lambda: runtime.started == ['a', 'a'])
    runtime.release('a')
    wait_completed_worker(second, ids[0])
    second.tick()
    eventually(lambda: runtime.started == ['a', 'a', 'b'])
    assert states(second)[ids[2]] == 'queued'
    runtime.release('b')
    wait_completed_worker(second, ids[1])
    second.tick()
    eventually(lambda: runtime.started == ['a', 'a', 'b', 'c'])
    assert runtime.peak == 1


def test_completed_state_precedes_worker_finalization(harness, monkeypatch):
    approve, owner, runtime, _, _ = harness
    for name in ['a', 'b']:
        approve(name)
    lifecycle = owner(limit=1)
    a, b = [lifecycle.enqueue(name, '1') for name in ['a', 'b']]
    finalizing = threading.Event()
    release = threading.Event()
    original_write = ml.write_json

    def held_report(path, value):
        if Path(path).name == 'REPORT.json' and Path(path).parent.name == a:
            finalizing.set()
            assert release.wait(5), 'Test did not release finalization'
        return original_write(path, value)

    monkeypatch.setattr(ml, 'write_json', held_report)
    try:
        lifecycle.tick()
        eventually(lambda: runtime.started == ['a'])
        runtime.release('a')
        assert finalizing.wait(5)
        assert states(lifecycle)[a] == 'completed'
        assert lifecycle.workers[a].is_alive()
        lifecycle.tick()
        assert states(lifecycle)[b] == 'queued'
        assert runtime.started == ['a']
    finally:
        release.set()
    wait_completed_worker(lifecycle, a)
    assert (lifecycle.root / 'sessions' / a / 'REPORT.json').is_file()
    lifecycle.tick()
    eventually(lambda: runtime.started == ['a', 'b'])
    assert runtime.peak == 1


@pytest.mark.parametrize('action,expected', [('stop', 'stopped'), ('failure', 'failed'), ('deadline', 'expired')])
def test_stop_failure_deadline_are_isolated(harness, action, expected):
    approve, owner, runtime, clock, _ = harness
    approve('a', seconds=10)
    approve('b')
    lifecycle = owner()
    a, b = lifecycle.enqueue('a', '1'), lifecycle.enqueue('b', '1')
    lifecycle.tick()
    eventually(lambda: len(runtime.started) == 2)
    if action == 'stop':
        lifecycle.stop(a)
    elif action == 'failure':
        runtime.fail.add('a')
        runtime.release('a')
    else:
        clock.now = NOW + timedelta(seconds=10)
    # No tick: workers must observe stop/deadline through their callback.
    eventually(lambda: states(lifecycle)[a] == expected)
    assert states(lifecycle)[b] == 'running'
    lifecycle.tick()
    eventually(lambda: (lifecycle.root / 'sessions' / a / 'REPORT.json').exists())
    report = json.loads((lifecycle.root / 'sessions' / a / 'REPORT.json').read_text())
    assert report['lifecycle_state'] == expected
    if action != 'failure':
        assert report['positions']['unresolved']['entry_notional'] == '100'
    else:
        assert report['error_type'] == 'RuntimeError'
        assert report['journal_preserved'] is True


@pytest.mark.parametrize('action,expected', [('stop', 'stopped'), ('deadline', 'expired')])
def test_queued_stop_or_expiry_never_launches(harness, action, expected):
    approve, owner, runtime, clock, _ = harness
    approve('a', seconds=10)
    lifecycle = owner()
    sid = lifecycle.enqueue('a', '1')
    if action == 'stop':
        lifecycle.stop(sid)
    else:
        clock.now = NOW + timedelta(seconds=10)
    lifecycle.tick()
    assert states(lifecycle)[sid] == expected
    assert runtime.started == []


@pytest.mark.parametrize('saved_state', ['paused', 'running'])
def test_recovery_keeps_session_identity_and_directory(harness, saved_state):
    approve, owner, runtime, _, _ = harness
    approve('a')
    first = owner()
    sid = first.enqueue('a', '1')
    first.tick()
    eventually(lambda: len(runtime.started) == 1)
    first.close()
    assert states(first)[sid] == 'paused'
    if saved_state == 'running':
        # Model a crash-persisted state using only this test's isolated registry.
        with first._db() as db:
            db.execute("UPDATE sessions SET state='running' WHERE session_id=?", (sid,))
    second = owner()
    assert len(runtime.started) == 1
    assert second.enqueue('a', '1') == sid
    second.tick()
    eventually(lambda: len(runtime.started) == 2)
    assert runtime.paths[0] == runtime.paths[1]
    runtime.release('a')
    eventually(lambda: states(second)[sid] == 'completed')
    second.close()
    third = owner()
    third.tick()
    assert len(runtime.started) == 2
    assert states(third)[sid] == 'completed'


def test_second_supervisor_rejected_until_close(harness):
    _, owner, _, _, _ = harness
    first = owner()
    with pytest.raises(BlockingIOError):
        owner()
    first.close()
    second = owner()
    assert second.status() == []


def test_lifecycle_restart_restores_journal_accounting_without_duplicate_entry(harness):
    approve, owner, _, clock, _ = harness
    approve('persisted')
    observations = []
    metadata = legacy_snapshot()

    class PersistentRuntime:
        def __init__(self, package, path, should_stop):
            self.package, self.path, self.should_stop = package, path, should_stop

        def run(self):
            journal = ShadowJournal(self.path / 'shadow.sqlite3', metadata)
            try:
                guard = GuardedJournal(journal, self.package, self.should_stop,
                                       lambda: int(clock().timestamp() * 1000))
                journal.transact('signal:one', 'signal', {}, lambda state: state['signals'].update({
                    'one': {'symbol': 'BTCUSDT'}}))

                def entry(state):
                    state['positions']['one'] = {'symbol': 'BTCUSDT', 'entry_notional': '100', 'entry_fee': '0.05'}
                    state['balance'] = '999.95'

                inserted = guard.transact('entry:one', 'model_entry', {'signal_id': 'one'}, entry)
                observations.append((inserted, journal.read()))
                while not self.should_stop():
                    time.sleep(0.005)
                return journal.read()
            finally:
                journal.close()

    first = owner(factory=PersistentRuntime)
    sid = first.enqueue('persisted', '1')
    first.tick()
    eventually(lambda: len(observations) == 1)
    first.close()
    assert states(first)[sid] == 'paused'
    second = owner(factory=PersistentRuntime)
    assert second.enqueue('persisted', '1') == sid
    second.tick()
    eventually(lambda: len(observations) == 2)
    assert [inserted for inserted, _ in observations] == [True, False]
    assert observations[0][1] == observations[1][1]
    assert observations[1][1]['balance'] == '999.95'
    assert observations[1][1]['positions']['one']['entry_fee'] == '0.05'
    second.stop(sid)
    eventually(lambda: states(second)[sid] == 'stopped')
    second.close()
    with sqlite3.connect(second.root / 'sessions' / sid / 'shadow.sqlite3') as db:
        assert db.execute("SELECT count(*) FROM events WHERE kind='model_entry'").fetchone()[0] == 1
    report = json.loads((second.root / 'sessions' / sid / 'REPORT.json').read_text())
    assert report['preserved_ledger']['balance'] == '999.95'
    assert report['preserved_ledger']['positions'] == observations[0][1]['positions']


@pytest.mark.parametrize('tamper', ['accepted_file', 'package_store', 'session_digest', 'validation'])
def test_recovery_tampering_fails_closed_and_does_not_block_peer(harness, monkeypatch, tamper):
    approve, owner, runtime, _, store = harness
    approve('a')
    approve('b')
    first = owner()
    a, b = first.enqueue('a', '1'), first.enqueue('b', '1')
    first.tick()
    eventually(lambda: len(runtime.started) == 2)
    first.close()
    if tamper == 'accepted_file':
        path = first.root / 'sessions' / a / 'accepted_package.json'
        path.write_text('{}')
    elif tamper == 'package_store':
        store.db.execute('DROP TRIGGER immutable_package')
        store.db.execute("UPDATE packages SET snapshot_digest='bad' WHERE strategy_id='a'")
    elif tamper == 'session_digest':
        with first._db() as db:
            db.execute('DROP TRIGGER immutable_session')
            db.execute("UPDATE sessions SET digest='bad' WHERE session_id=?", (a,))
    else:
        original = ml.validate_package

        def changed_contract(raw, now=None):
            if json.loads(raw)['strategy_id'] == 'a':
                raise sp.PackageError('synthetic contract change')
            return original(raw, now)
        monkeypatch.setattr(ml, 'validate_package', changed_contract)
    second = owner()
    second.tick()
    eventually(lambda: states(second)[a] == 'failed' and runtime.started.count('b') == 2)
    assert runtime.started.count('a') == 1
    assert states(second)[b] == 'running'


@pytest.fixture
def guarded(tmp_path):
    package = sp.example_package('guard', '1', (NOW + timedelta(seconds=10)).isoformat())
    journal = ShadowJournal(tmp_path / 'journal.sqlite3', legacy_snapshot())
    control = {'stop': False, 'ms': int(NOW.timestamp() * 1000)}
    guard = GuardedJournal(journal, package, lambda: control['stop'], lambda: control['ms'])
    yield guard, journal, control
    journal.close()


def enter(guard, sid):
    guard.transact('signal:' + sid, 'signal', {'signal_id': sid},
                   lambda state: state['signals'].update({sid: {'symbol': 'BTCUSDT'}}))
    return guard.transact('entry:' + sid, 'model_entry', {'signal_id': sid},
                          lambda state: state['positions'].update({sid: {'entry_notional': '100'}}))


def reject_without_mutation(guard, journal, sid, match):
    guard.transact('signal:' + sid, 'signal', {'signal_id': sid},
                   lambda state: state['signals'].update({sid: {'symbol': 'BTCUSDT'}}))
    before = journal.read()
    count = journal.db.execute('SELECT count(*) FROM events').fetchone()[0]
    with pytest.raises(ValueError, match=match):
        enter(guard, sid)
    assert journal.read() == before
    assert journal.db.execute('SELECT count(*) FROM events').fetchone()[0] == count
    assert not journal.db.in_transaction


def test_position_cap_is_checked_before_every_entry_and_releases(guarded):
    guard, journal, _ = guarded
    guard.package['safety_limits'].update(max_open_positions=2, max_total_notional_usdt='1000')
    assert enter(guard, 'a')
    assert enter(guard, 'b')
    reject_without_mutation(guard, journal, 'c', 'max_open_positions')
    journal.transact('close:a', 'model_exit', {}, lambda state: state['positions'].pop('a'))
    assert enter(guard, 'c')
    assert set(journal.read()['positions']) == {'b', 'c'}
    assert enter(guard, 'c') is False


def test_notional_cap_uses_actual_reserved_sum_and_exact_boundary(guarded):
    guard, journal, _ = guarded
    guard.package['safety_limits']['max_total_notional_usdt'] = '250'
    journal.transact('seed', 'fixture', {}, lambda state: state['positions'].update({'old': {'entry_notional': '150'}}))
    assert enter(guard, 'a')
    reject_without_mutation(guard, journal, 'b', 'max_total_notional')


@pytest.mark.parametrize('reason', ['stop', 'deadline'])
def test_stop_and_exact_deadline_rechecked_before_next_entry(guarded, reason):
    guard, journal, control = guarded
    assert enter(guard, 'a')
    if reason == 'stop':
        control['stop'] = True
    else:
        control['ms'] += 10000
    reject_without_mutation(guard, journal, 'b', 'stopped or deadline')
    # Risk-reducing journal operations remain possible after admission stops.
    assert guard.transact('close:a', 'model_exit', {}, lambda state: state['positions'].pop('a'))


@pytest.mark.parametrize('target', ['package', 'runtime'])
@pytest.mark.parametrize('field,value', [('paper_only', False), ('paper_only', 1), ('private_api', True), ('private_api', 0), ('real_orders', True), ('testnet_orders', True)])
def test_safety_flags_rechecked_with_exact_bool_identity(guarded, target, field, value):
    guard, journal, _ = guarded
    assert enter(guard, 'a')
    if target == 'package':
        guard.package['safety_limits'][field] = value
    else:
        journal.transact('unsafe', 'fixture', {}, lambda state: state['metadata']['safety'].update({field: value}))
    reject_without_mutation(guard, journal, 'b', 'unsafe|metadata changed')


@pytest.mark.parametrize('field,value', [('fee_rate', '0'), ('execution_penalty', '0'), ('latency_ms', 0), ('max_quote_age_ms', 99999), ('fixed_notional_usdt', '1')])
def test_runtime_metadata_tampering_blocks_next_entry(guarded, field, value):
    guard, journal, _ = guarded
    assert enter(guard, 'a')
    journal.transact('tamper', 'fixture', {}, lambda state: state['metadata'].update({field: value}))
    reject_without_mutation(guard, journal, 'b', 'metadata changed')


@pytest.mark.parametrize('field,value', [('fee_rate', '0'), ('adverse_slippage', '0'), ('latency_ms', 0), ('max_quote_age_ms', 99999), ('fixed_notional_usdt', '1')])
def test_package_execution_tampering_blocks_next_entry(guarded, field, value):
    guard, journal, _ = guarded
    assert enter(guard, 'a')
    guard.package['execution_model'][field] = value
    reject_without_mutation(guard, journal, 'b', 'execution mismatch')


@pytest.mark.parametrize('damage', ['missing', 'invalid_json', 'wrong_content'])
def test_terminal_report_repaired_from_registry_without_relaunch(harness, damage):
    approve, owner, runtime, _, _ = harness
    approve('a')
    lifecycle = owner()
    sid = lifecycle.enqueue('a', '1')
    runtime.release('a')
    lifecycle.tick()
    eventually(lambda: states(lifecycle)[sid] == 'completed')
    lifecycle.close()
    target = lifecycle.root / 'sessions' / sid / 'REPORT.json'
    expected = json.loads(lifecycle.status()[0]['report'])
    if damage == 'missing':
        target.unlink()
    else:
        target.write_text('{' if damage == 'invalid_json' else '{}')
    recovered = owner()
    recovered.tick()
    assert json.loads(target.read_text()) == expected
    assert states(recovered)[sid] == 'completed'
    assert runtime.started == ['a']


def test_persistence_failure_blocks_relaunch_and_leaves_peer_running(harness, monkeypatch):
    approve, owner, runtime, _, _ = harness
    approve('a')
    approve('b')
    lifecycle = owner()
    a, b = lifecycle.enqueue('a', '1'), lifecycle.enqueue('b', '1')
    lifecycle.tick()
    eventually(lambda: len(runtime.started) == 2)
    original = lifecycle._finish

    def broken_finish(sid, state, report):
        if sid == a:
            raise OSError('synthetic persistence failure')
        return original(sid, state, report)
    monkeypatch.setattr(lifecycle, '_finish', broken_finish)
    runtime.release('a')
    eventually(lambda: a in lifecycle.blockers)
    lifecycle.tick()
    row = next(row for row in lifecycle.status() if row['session_id'] == a)
    assert row['persistence_blocker'] == 'OSError'
    assert runtime.started.count('a') == 1
    assert states(lifecycle)[b] == 'running'


@pytest.fixture
def wrapper(tmp_path, monkeypatch):
    package = sp.example_package('wrapper', '1', (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat())
    engine_type = psr.PackageEngine
    created = []
    entries = []

    class Adapter:
        def __init__(self):
            self.state = {'last_sent': {}, 'cooldown_until_ms': 0}

        def dump_state(self):
            return self.state

        def restore_state(self, state):
            self.state = state

        def mark_sent(self, symbol, stamp):
            self.state['last_sent'][symbol] = stamp

    def build(path, metadata, approved, should_stop):
        engine = engine_type(path, metadata, approved, should_stop, adapter=Adapter(), client=object())
        created.append(engine)
        return engine

    def fixture_run(engine, **kwargs):
        assert kwargs == {'run_forever': True}
        try:
            marker = json.loads((engine.root / 'runtime_initialization.json').read_text())
            assert marker == {'package_sha256': sp.sha(sp.canonical(package)), 'phase': 'initialized'}
            assert isinstance(engine.execution.journal, GuardedJournal)
            journal = engine.execution.journal
            journal.transact('signal:synthetic', 'signal', {}, lambda state: state['signals'].update({
                'synthetic': {'symbol': 'BTCUSDT', 'context': {}, 'decision_ms': 1}}))
            result = journal.transact('entry:synthetic', 'model_entry', {'signal_id': 'synthetic'},
                                      lambda state: state['positions'].update({
                                          'synthetic': {'symbol': 'BTCUSDT', 'entry_notional': '100'}}))
            entries.append(result)
        finally:
            engine.close()

    monkeypatch.setattr(psr, 'PackageEngine', build)
    monkeypatch.setattr(engine_type, 'run', fixture_run)
    return package, tmp_path, created, entries


def test_real_package_engine_wrapper_recovery_preserves_position_and_dedup(wrapper):
    package, path, created, entries = wrapper
    first = psr.PackageShadowRuntime(package, path, lambda: False).run()
    second = psr.PackageShadowRuntime(package, path, lambda: False).run()
    assert entries == [True, False]
    assert len(created) == 2
    assert all(engine.closed for engine in created)
    assert first['signal_count'] == second['signal_count'] == 1
    assert first['positions']['synthetic']['entry_notional'] == second['positions']['synthetic']['entry_notional'] == '100'
    assert second['unresolved_positions_not_liquidated'] is True
    assert second['model_fills_only'] is True


@pytest.mark.parametrize('damage', ['missing_journal', 'missing_state', 'changed_snapshot', 'missing_marker', 'missing_snapshot'])
def test_wrapper_recovery_never_recreates_damaged_journal(wrapper, damage):
    package, path, created, _ = wrapper
    psr.PackageShadowRuntime(package, path, lambda: False).run()
    ledger = path / 'shadow.sqlite3'
    marker = path / 'runtime_initialization.json'
    assert json.loads(marker.read_text())['phase'] == 'initialized'
    if damage == 'missing_journal':
        ledger.unlink()
    elif damage == 'missing_marker':
        marker.unlink()
    elif damage == 'missing_snapshot':
        (path / 'config_snapshot.json').unlink()
    elif damage == 'missing_state':
        with sqlite3.connect(ledger) as db:
            db.execute('DELETE FROM state')
    else:
        target = path / 'config_snapshot.json'
        snapshot = json.loads(target.read_text())
        snapshot['fee_rate'] = '0'
        target.write_text(json.dumps(snapshot))
    with pytest.raises(ValueError, match='missing|snapshot mismatch'):
        psr.PackageShadowRuntime(package, path, lambda: False).run()
    assert len(created) == 1
    if damage == 'missing_journal':
        assert not ledger.exists()
    elif damage == 'missing_state':
        with sqlite3.connect(ledger) as db:
            assert db.execute('SELECT count(*) FROM state').fetchone()[0] == 0
    elif damage == 'missing_marker':
        assert not marker.exists()
    elif damage == 'missing_snapshot':
        assert not (path / 'config_snapshot.json').exists()


@pytest.mark.parametrize('crash_point', ['before_snapshot', 'before_engine'])
def test_first_initialization_crash_is_resumable_without_prior_strategy_run(wrapper, monkeypatch, crash_point):
    package, path, created, entries = wrapper
    with monkeypatch.context() as patch:
        if crash_point == 'before_snapshot':
            original_write = psr.write_json

            def fail_snapshot(target, value):
                if Path(target).name == 'config_snapshot.json':
                    raise OSError('synthetic first initialization crash')
                return original_write(target, value)
            patch.setattr(psr, 'write_json', fail_snapshot)
        else:
            def fail_constructor(*args, **kwargs):
                raise OSError('synthetic first initialization crash')
            patch.setattr(psr, 'PackageEngine', fail_constructor)
        with pytest.raises(OSError, match='first initialization crash'):
            psr.PackageShadowRuntime(package, path, lambda: False).run()
    marker = path / 'runtime_initialization.json'
    assert json.loads(marker.read_text()) == {
        'package_sha256': sp.sha(sp.canonical(package)), 'phase': 'initializing'}
    assert created == entries == []
    assert not (path / 'shadow.sqlite3').exists()
    assert (path / 'config_snapshot.json').exists() is (crash_point == 'before_engine')
    report = psr.PackageShadowRuntime(package, path, lambda: False).run()
    assert json.loads(marker.read_text())['phase'] == 'initialized'
    assert len(created) == 1
    assert entries == [True]
    assert report['signal_count'] == 1
    assert report['positions']['synthetic']['entry_notional'] == '100'


def test_hot_journal_recovery_rolls_back_uncommitted_state(wrapper, monkeypatch, offline):
    package, path, created, entries = wrapper
    before = psr.PackageShadowRuntime(package, path, lambda: False).run()
    ledger = path / 'shadow.sqlite3'
    db = sqlite3.connect(ledger)
    try:
        db.execute('CREATE TABLE crash_pages (id INTEGER PRIMARY KEY, payload BLOB)')
        db.executemany('INSERT INTO crash_pages VALUES (?, ?)', [(i, b'a' * 4096) for i in range(128)])
        db.commit()
    finally:
        db.close()
    script = '''
import json
import os
import sqlite3
import sys
db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute('PRAGMA journal_mode=DELETE')
db.execute('PRAGMA synchronous=FULL')
db.execute('PRAGMA cache_size=5')
db.execute('PRAGMA cache_spill=ON')
db.execute('BEGIN IMMEDIATE')
state = json.loads(db.execute('SELECT body FROM state WHERE id=1').fetchone()[0])
state['balance'] = '0'
state['positions'] = {}
db.execute('UPDATE state SET body=? WHERE id=1', (json.dumps(state),))
db.execute('UPDATE crash_pages SET payload=?', (b'b' * 4096,))
os._exit(0)
'''
    # Explicitly authorized exception: only this local SQLite crash fixture.
    with monkeypatch.context() as patch:
        patch.setattr(subprocess, 'Popen', offline)
        result = subprocess.run([sys.executable, '-c', script, str(ledger)],
                                capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    rollback = Path(str(ledger) + '-journal')
    assert rollback.is_file()
    assert rollback.stat().st_size > 512
    # Read-only access cannot perform the rollback; this proves the hot-journal fixture.
    db = sqlite3.connect(ledger.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        with pytest.raises(sqlite3.OperationalError, match='readonly|read-only'):
            db.execute('SELECT body FROM state WHERE id=1').fetchone()
    finally:
        db.close()
    after = psr.PackageShadowRuntime(package, path, lambda: False).run()
    assert len(created) == 2
    assert entries == [True, False]
    assert after['balance'] == before['balance']
    assert after['positions']['synthetic']['entry_notional'] == '100'
    assert after['signal_count'] == before['signal_count'] == 1
    db = sqlite3.connect(ledger)
    try:
        assert db.execute('PRAGMA integrity_check').fetchall() == [('ok',)]
        assert db.execute('SELECT count(*) FROM crash_pages WHERE payload=?', (b'a' * 4096,)).fetchone()[0] == 128
        assert db.execute("SELECT count(*) FROM events WHERE kind='model_entry'").fetchone()[0] == 1
    finally:
        db.close()
