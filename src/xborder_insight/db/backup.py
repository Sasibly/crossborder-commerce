"""Consistent SQLite online backup, including committed WAL data, without overwrite."""
from pathlib import Path
from contextlib import closing
import sqlite3


def snapshot(source, destination):
    source=Path(source).resolve()
    destination=Path(destination).resolve()
    if not source.is_file():
        raise FileNotFoundError(f'数据库不存在: {source}')
    if source==destination or destination.exists():
        raise FileExistsError('目标已存在；恢复只允许写入新的文件，避免覆盖工作库')
    destination.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation prevents two backup jobs from overwriting each other.
    with destination.open('xb'):
        pass
    try:
        with closing(sqlite3.connect(source.as_uri()+'?mode=ro',uri=True)) as src:
            if src.execute('PRAGMA quick_check').fetchone()[0]!='ok':
                raise ValueError('源数据库完整性检查失败')
            with closing(sqlite3.connect(destination)) as dst:
                src.backup(dst,pages=256,sleep=.01)
                if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or dst.execute('PRAGMA foreign_key_check').fetchone():
                    raise ValueError('备份完整性检查失败')
                tables=[r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
                counts={name:dst.execute('SELECT COUNT(*) FROM "'+name.replace('"','""')+'"').fetchone()[0] for name in tables}
        return {'source':str(source),'destination':str(destination),'integrity':'ok','rows':counts}
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
