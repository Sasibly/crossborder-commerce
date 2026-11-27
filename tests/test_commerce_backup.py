import sqlite3
import pytest
from xborder_insight.db.backup import snapshot
from xborder_insight.db.connection import connect
from xborder_insight.db import migrate


def test_online_backup_and_restore_contains_wal(tmp_path):
    path=tmp_path/'live.sqlite3'
    conn=connect(path);migrate.upgrade(conn)
    conn.execute("INSERT INTO commerce_candidates VALUES('demo','local','Committed WAL','{}',0)")
    backup=tmp_path/'backup.sqlite3'
    report=snapshot(path,backup)
    assert report['rows']['commerce_candidates']==1
    restore=tmp_path/'restored.sqlite3'
    assert snapshot(backup,restore)['rows']==report['rows']
    restored=connect(restore)
    assert restored.execute('SELECT name FROM commerce_candidates').fetchone()[0]=='Committed WAL'
    from xborder_insight.db.migrations import LATEST
    assert migrate.current_version(restored)==LATEST
    restored.close();conn.close()
    # Windows refuses renaming a file if snapshot() leaked its sqlite handle.
    moved=tmp_path/'moved-backup.sqlite3'
    backup.rename(moved);moved.rename(backup)
    with pytest.raises(FileExistsError):
        snapshot(backup,path)
    with pytest.raises(FileExistsError):
        snapshot(backup,backup)


def test_backup_missing_and_corrupt_do_not_leave_destination(tmp_path):
    target=tmp_path/'copy.sqlite3'
    with pytest.raises(FileNotFoundError):
        snapshot(tmp_path/'missing',target)
    assert not target.exists()
    corrupt=tmp_path/'broken.sqlite3';corrupt.write_text('not a database')
    with pytest.raises(sqlite3.DatabaseError):
        snapshot(corrupt,target)
    assert not target.exists()
