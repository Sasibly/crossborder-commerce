from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
import pytest
from xborder_insight.db.connection import connect,transaction,_WriteGate


def test_nested_rollback_releases_admission_and_different_db_is_independent(tmp_path):
    first=tmp_path/'first.sqlite3';second=tmp_path/'second.sqlite3'
    a=connect(first);b=connect(first);other=connect(second)
    a.execute('CREATE TABLE values_(value INTEGER)');other.execute('CREATE TABLE values_(value INTEGER)')
    with pytest.raises(ValueError):
        with transaction(a):
            with transaction(a):a.execute('INSERT INTO values_ VALUES(1)')
            with transaction(other):other.execute('INSERT INTO values_ VALUES(9)')
            raise ValueError('rollback')
    with transaction(b):b.execute('INSERT INTO values_ VALUES(2)')
    assert [r[0] for r in a.execute('SELECT value FROM values_')]==[2]
    assert other.execute('SELECT value FROM values_').fetchone()[0]==9
    a.close();b.close();other.close()


def test_expired_waiter_does_not_block_following_writer():
    gate=_WriteGate(timeout=.03)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with gate:
            def wait():
                with gate:return True
            future=pool.submit(wait)
            with pytest.raises(sqlite3.OperationalError):future.result(timeout=1)
        with gate:pass


def test_concurrent_transactions_commit_without_lost_updates(tmp_path):
    path=tmp_path/'concurrency.sqlite3';db=connect(path)
    db.execute('CREATE TABLE counter(value INTEGER)');db.execute('INSERT INTO counter VALUES(0)');db.close()
    barrier=threading.Barrier(8)
    def worker(_):
        conn=connect(path)
        try:
            barrier.wait(timeout=5)
            for _ in range(20):
                with transaction(conn):conn.execute('UPDATE counter SET value=value+1')
        finally:conn.close()
    with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(worker,range(8)))
    db=connect(path)
    assert db.execute('SELECT value FROM counter').fetchone()[0]==160
    db.close()


def test_interrupted_waiter_is_removed_before_future_writes(monkeypatch):
    gate=_WriteGate();original=gate.condition.wait_for
    def interrupted(*args,**kwargs):raise KeyboardInterrupt()
    monkeypatch.setattr(gate.condition,'wait_for',interrupted)
    with pytest.raises(KeyboardInterrupt):
        with gate:pass
    monkeypatch.setattr(gate.condition,'wait_for',original)
    with gate:pass
