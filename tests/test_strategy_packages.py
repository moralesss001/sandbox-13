from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import sqlite3

import pytest

from src import strategy_packages as sp


NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)


@pytest.fixture
def package():
    return sp.example_package('legacy', '1.0', '2026-10-05T10:21:48.811Z')


@pytest.fixture
def store(tmp_path):
    s = sp.PackageStore(tmp_path / 'packages.sqlite3')
    yield s
    s.close()


def test_valid_contract_no_strategy_import(package, monkeypatch):
    import builtins
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name in {'src.live_shadow', 'src.legacy_crypto13_shadow', 'src.main'}:
            raise AssertionError('strategy/runtime import forbidden')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    assert sp.validate_package(json.dumps(package), NOW) == package
    assert len(package['universe']) == 46


def test_multiple_independent_packages_and_versions(store, package):
    for sid, ver in [('legacy', '1.0'), ('legacy', '2.0'), ('independent', '1.0')]:
        store.upload(json.dumps(dict(package, strategy_id=sid, version=ver)))
    a = store.validate('legacy', '1.0', NOW)
    store.approve('legacy', '1.0', NOW)
    store.validate('independent', '1.0', NOW)
    store.approve('independent', '1.0', NOW)
    store.reject('legacy', '2.0', 'not selected')
    assert store.get('legacy', '1.0')['status'] == 'approved'
    assert store.get('independent', '1.0')['status'] == 'approved'
    assert store.get('legacy', '2.0')['status'] == 'rejected'
    assert len(store.list_packages()) == 3
    assert a['snapshot'] == package
    a['snapshot']['universe'].clear()
    assert len(store.get('legacy', '1.0')['snapshot']['universe']) == 46


def test_reopen_snapshot_and_duplicate(store, package):
    store.upload(json.dumps(package))
    store.validate('legacy', '1.0', NOW)
    with pytest.raises(sp.PackageError, match='Duplicate'):
        store.upload(json.dumps(dict(package, deadline='2030-01-01T00:00:00Z')))
    other = sp.PackageStore(store.path)
    try:
        assert other.get('legacy', '1.0')['snapshot'] == package
    finally:
        other.close()


@pytest.mark.parametrize('field,value', [
    ('adapter', 'os.system'), ('schema_version', True), ('schema_version', 2),
    ('universe', ['BTCUSDT']), ('frozen_parameters', {}), ('execution_model', {}),
    ('data_requirements', {}), ('hashes', {}), ('deadline', '2020-01-01T00:00:00Z'),
    ('deadline', '2030-01-01'), ('deadline', '2030-01-01T00:00:00+03:00'),
    ('strategy_id', '../escape'), ('version', ''), ('deadline', None),
])
def test_invalid_contract(package, field, value):
    package[field] = value
    with pytest.raises(sp.PackageError):
        sp.validate_package(json.dumps(package), NOW)


@pytest.mark.parametrize('key,value', [('real_orders', True), ('testnet_orders', True),
    ('private_api', True), ('paper_only', False), ('paper_only', 1),
    ('max_open_positions', True), ('max_open_positions', 11), ('max_total_notional_usdt', '100000')])
def test_safety(package, key, value):
    package['safety_limits'][key] = value
    with pytest.raises(sp.PackageError):
        sp.validate_package(json.dumps(package), NOW)


@pytest.mark.parametrize('raw', ['import os; os.system("echo fail")', 'PK\u0000', '[]',
    '{"strategy_id":"a","strategy_id":"b","version":"1"}',
    '{"strategy_id":"a","version":"1","x":NaN}', 'x' * (sp.MAX_BYTES + 1), b'\xff'],
    ids=['python', 'zip', 'array', 'duplicate-key', 'nan', 'oversize', 'encoding'])
def test_invalid_upload(store, raw):
    with pytest.raises(sp.PackageError):
        store.upload(raw)
    assert store.db.execute('SELECT count(*) FROM packages').fetchone()[0] == 0


def test_extra_code_field_rejected(package):
    package['python'] = 'raise RuntimeError()'
    with pytest.raises(sp.PackageError):
        sp.validate_package(json.dumps(package), NOW)


def test_approval_requires_validation_and_rechecks_deadline(store, package):
    store.upload(json.dumps(package))
    with pytest.raises(sp.PackageError, match='transition'):
        store.approve('legacy', '1.0', NOW)
    store.validate('legacy', '1.0', NOW)
    with pytest.raises(sp.PackageError, match='Deadline'):
        store.approve('legacy', '1.0', datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert store.get('legacy', '1.0')['status'] == 'validated'


def test_failed_validation_does_not_accept(store, package):
    package['adapter'] = 'unknown'
    store.upload(json.dumps(package))
    with pytest.raises(sp.PackageError):
        store.validate('legacy', '1.0', NOW)
    assert store.get('legacy', '1.0')['status'] == 'uploaded'
    assert store.get('legacy', '1.0')['snapshot'] is None
    store.reject('legacy', '1.0', 'unknown adapter')
    with pytest.raises(sp.PackageError):
        store.validate('legacy', '1.0', NOW)


def test_approval_rechecks_code_hash(store, package, monkeypatch):
    store.upload(json.dumps(package)); store.validate('legacy', '1.0', NOW)
    rules, hashes = sp.contract()
    hashes['code_sha256'] = '0' * 64
    monkeypatch.setattr(sp, 'contract', lambda: (rules, hashes))
    with pytest.raises(sp.PackageError, match='hashes'):
        store.approve('legacy', '1.0', NOW)


def test_sql_immutability_and_tamper_detection(store, package):
    store.upload(json.dumps(package)); store.validate('legacy', '1.0', NOW)
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("UPDATE packages SET payload='{}'")
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute("UPDATE packages SET snapshot='{}'")
    with pytest.raises(sqlite3.IntegrityError):
        store.db.execute('DELETE FROM packages')
    # Simulated out-of-band corruption, without modifying any real store.
    store.db.execute('DROP TRIGGER immutable_package')
    store.db.execute("UPDATE packages SET snapshot_digest='bad'")
    with pytest.raises(sp.PackageError, match='tampered'):
        store.get('legacy', '1.0')


def test_concurrent_duplicate_is_not_replaced(store, package):
    def upload(_):
        s = sp.PackageStore(store.path)
        try:
            s.upload(json.dumps(package))
            return 'saved'
        except sp.PackageError:
            return 'duplicate'
        finally:
            s.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(upload, range(2))) == ['duplicate', 'saved']


def test_concurrent_independent_validation(store, package):
    for sid in ['a', 'b']:
        store.upload(json.dumps(dict(package, strategy_id=sid)))
    def validate(sid):
        s = sp.PackageStore(store.path)
        try:
            return s.validate(sid, '1.0', NOW)['status']
        finally:
            s.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert list(pool.map(validate, ['a', 'b'])) == ['validated', 'validated']


def test_no_network_or_subprocess(store, package, monkeypatch):
    import socket
    import subprocess
    def forbidden(*args, **kwargs):
        raise AssertionError('No network or process launch allowed')
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    store.upload(json.dumps(package))
    store.validate('legacy', '1.0', NOW)
    store.approve('legacy', '1.0', NOW)


def test_frozen_bool_not_interchangeable_with_integer(package):
    package['frozen_parameters']['unclosed_candles'] = 1
    with pytest.raises(sp.PackageError, match='Frozen'):
        sp.validate_package(json.dumps(package), NOW)


def test_one_corrupted_package_does_not_prevent_other_read(store, package):
    for sid in ['a', 'b']:
        store.upload(json.dumps(dict(package, strategy_id=sid)))
        store.validate(sid, '1.0', NOW)
    store.db.execute('DROP TRIGGER immutable_package')
    store.db.execute("UPDATE packages SET snapshot_digest='bad' WHERE strategy_id='a'")
    with pytest.raises(sp.PackageError):
        store.approve('a', '1.0', NOW)
    assert store.approve('b', '1.0', NOW)['status'] == 'approved'
