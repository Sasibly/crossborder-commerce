"""Check effective local configuration without printing keys or claiming public readiness."""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from xborder_insight.config import settings,ROOT_DIR
from xborder_insight.commerce_ops import database_manifest,preflight
from xborder_insight.db import migrate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile',choices=['local','protected'],default='protected')
    parser.add_argument('--workers',type=int,default=1,help='Declared worker count; verify actual command separately.')
    args=parser.parse_args()
    path=Path(settings.db_path)
    if not path.is_absolute():path=ROOT_DIR/path
    read_error=None
    try:
        manifest=database_manifest(path)
    except (OSError,sqlite3.Error) as exc:
        read_error=type(exc).__name__
        manifest={'schema_version':None,'integrity':'unavailable','foreign_key_violations':None}
    result=preflight(profile=args.profile,schema_version=manifest['schema_version'],latest=migrate.LATEST,
        auth_required=settings.auth_required,secure_cookies=os.getenv('COMMERCE_SECURE_COOKIES','false').lower()=='true',
        sync_analysis=settings.sync_analyze_enabled,workers=args.workers,
        simulation_only=settings.run_mode=='mock' and settings.embedding_provider=='hash')
    result['schema_version']=manifest['schema_version']
    result['checks'].append({'id':'database_readable','passed':read_error is None})
    if read_error:result['database_error_type']=read_error
    result['checks'].append({'id':'database_integrity','passed':manifest['integrity']=='ok' and manifest['foreign_key_violations']==0})
    if not result['checks'][-1]['passed']:result['status']='blocked'
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='passed' else 2


if __name__=='__main__':
    raise SystemExit(main())
