"""Read-only operational evidence and explicitly scoped preflight checks."""
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from pathlib import Path


def latency_summary(milliseconds,elapsed):
    values=sorted(milliseconds)
    if not values or elapsed<=0:
        raise ValueError('延迟样本和测量时长必须为正')
    def percentile(p):
        return round(values[max(0,math.ceil(len(values)*p)-1)],3)
    return {'samples':len(values),'elapsed_seconds':round(elapsed,3),
            'operations_per_second':round(len(values)/elapsed,2),
            'p50_ms':percentile(.5),'p95_ms':percentile(.95),'p99_ms':percentile(.99),
            'max_ms':round(values[-1],3),'percentile_method':'nearest_rank'}


def database_manifest(path):
    """Fingerprint table content in a consistent read transaction; never emit rows."""
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as conn:
        conn.execute('BEGIN')
        integrity=conn.execute('PRAGMA integrity_check').fetchone()[0]
        fk=conn.execute('PRAGMA foreign_key_check').fetchall()
        tables=conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        counts={};digest=hashlib.sha256()
        def encode(value):
            if isinstance(value,bytes):return {'blob_hex':value.hex()}
            raise TypeError(type(value).__name__)
        for (name,) in tables:
            quoted='"'+name.replace('"','""')+'"'
            columns=conn.execute('PRAGMA table_info('+quoted+')').fetchall()
            order=','.join('"'+r[1].replace('"','""')+'"' for r in columns)
            digest.update((name+'\n').encode())
            count=0
            for row in conn.execute('SELECT * FROM '+quoted+' ORDER BY '+order):
                digest.update(json.dumps(row,ensure_ascii=False,separators=(',',':'),default=encode).encode())
                digest.update(b'\n');count+=1
            counts[name]=count
        version=conn.execute('SELECT COALESCE(MAX(version),0) FROM schema_migrations').fetchone()[0]
        return {'integrity':integrity,'foreign_key_violations':len(fk),'schema_version':version,
                'table_rows':counts,'content_sha256':digest.hexdigest()}


def preflight(*,profile,schema_version,latest,auth_required,secure_cookies,sync_analysis,workers,simulation_only):
    checks=[{'id':'schema_current','passed':schema_version==latest},
            {'id':'single_worker','passed':workers==1},
            {'id':'simulation_only','passed':simulation_only}]
    if profile not in ('local','protected'):
        raise ValueError('未知部署检查模式')
    if profile=='protected':
        checks.extend([{'id':'seller_auth_required','passed':auth_required},
                       {'id':'secure_buyer_cookie','passed':secure_cookies},
                       {'id':'sync_analysis_disabled','passed':not sync_analysis}])
    return {'profile':profile,'status':'passed' if all(c['passed'] for c in checks) else 'blocked',
            'checks':checks,'public_release':'not_verified',
            'unverified':['HTTPS termination and proxy trust','off-machine backup recovery',
                          'target capacity and service-level objectives','public account abuse controls'],
            'scope':'Local configuration and schema checks only; not approval for public release.'}
