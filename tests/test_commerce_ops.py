import importlib.util
from pathlib import Path
import sqlite3
import json
import os
import subprocess
import sys

import pytest
from xborder_insight.commerce_ops import latency_summary,database_manifest,preflight
from xborder_insight.db import migrate
from xborder_insight.db.connection import connect


def test_latency_nearest_rank_and_journey_denominator():
    result=latency_summary([40,10,30,20],2)
    assert result['p50_ms']==20 and result['p95_ms']==40 and result['p99_ms']==40
    assert result['operations_per_second']==2 and result['samples']==4
    with pytest.raises(ValueError):latency_summary([],1)
    with pytest.raises(ValueError):latency_summary([1],0)


def test_manifest_includes_wal_and_does_not_emit_row_content(tmp_path):
    path=tmp_path/'ops.sqlite3';db=connect(path);migrate.upgrade(db)
    db.execute("INSERT INTO commerce_candidates VALUES('secret-id','local','private fixture','{}',1)")
    before=database_manifest(path)
    assert before['integrity']=='ok' and before['schema_version']==migrate.LATEST
    assert before['table_rows']['commerce_candidates']==1
    assert 'private fixture' not in str(before) and 'secret-id' not in str(before)
    db.execute("UPDATE commerce_candidates SET name='changed' WHERE id='secret-id'")
    assert database_manifest(path)['content_sha256']!=before['content_sha256']
    db.close()
    with pytest.raises(sqlite3.OperationalError):database_manifest(tmp_path/'missing.sqlite3')
    assert not (tmp_path/'missing.sqlite3').exists()


def test_preflight_fails_closed_for_exposure_controls_and_old_schema():
    values=dict(profile='protected',schema_version=25,latest=25,auth_required=True,secure_cookies=True,
                sync_analysis=False,workers=1,simulation_only=True)
    ready=preflight(**values)
    assert ready['status']=='passed' and ready['public_release']=='not_verified'
    for key,value in [('schema_version',24),('auth_required',False),('secure_cookies',False),
                      ('sync_analysis',True),('workers',2),('simulation_only',False)]:
        assert preflight(**(values|{key:value}))['status']=='blocked'
    with pytest.raises(ValueError):preflight(**(values|{'profile':'unknown'}))


def test_complete_recovery_drill_keeps_source_unchanged(tmp_path,monkeypatch):
    scripts=Path(__file__).resolve().parents[1]/'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec=importlib.util.spec_from_file_location('commerce_restore_drill',scripts/'commerce_restore_drill.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    report=module.run()
    assert report['source_unchanged'] and report['committed_wal_included']
    assert report['source_manifest']['table_rows']['commerce_profit_comparisons']==1
    assert report['source_manifest']['table_rows']['commerce_orders']==11
    assert report['integrity']['ok']


def test_preflight_cli_missing_db_blocks_without_creating_file_or_leaking_env(tmp_path):
    root=Path(__file__).resolve().parents[1];path=tmp_path/'absent.sqlite3'
    env=os.environ|{'DB_PATH':str(path),'RUN_MODE':'mock','EMBEDDING_PROVIDER':'hash','AUTH_REQUIRED':'false',
                    'LLM_API_KEY':'test-sentinel-never-print','PYTHONUTF8':'1'}
    result=subprocess.run([sys.executable,str(root/'scripts/commerce_preflight.py'),'--profile','protected'],
                          env=env,cwd=root,capture_output=True,text=True,encoding='utf-8',timeout=15)
    assert result.returncode==2,result.stderr
    report=json.loads(result.stdout)
    assert report['status']=='blocked' and not path.exists()
    assert any(c['id']=='database_readable' and not c['passed'] for c in report['checks'])
    assert 'test-sentinel-never-print' not in result.stdout+result.stderr
