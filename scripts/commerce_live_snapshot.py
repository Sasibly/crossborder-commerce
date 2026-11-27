"""Back up the current deployment, then restore to a NEW file and verify contents."""
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from xborder_insight.config import ROOT_DIR,settings
from xborder_insight.commerce_ops import database_manifest
from xborder_insight.db.backup import snapshot


def run():
    source=Path(settings.db_path)
    if not source.is_absolute():source=ROOT_DIR/source
    if not settings.is_mock:raise ValueError('本地验收仅允许mock部署')
    name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]
    directory=source.parent/'local-verification'/name
    directory.mkdir(parents=True,exist_ok=False)
    backup=directory/'backup.sqlite3';restored=directory/'restored.sqlite3'
    snapshot(source,backup)
    before=database_manifest(backup)
    snapshot(backup,restored)
    after=database_manifest(restored)
    if before!=after or after['integrity']!='ok' or after['foreign_key_violations']:
        raise RuntimeError('备份与新库恢复内容不一致')
    return {'status':'passed','measurement_kind':'observed_live_deployment_backup_restore',
            'fixture_data_kind':'simulation','source':str(source),'backup':str(backup),'restored':str(restored),
            'restore_target':'new_file','deployment_database_replaced':False,'content_matches':True,
            'schema_version':after['schema_version'],'table_rows':after['table_rows'],
            'content_sha256':after['content_sha256'],'integrity':after['integrity'],'foreign_key_violations':0,
            'scope':'Same-machine local deployment backup; restore comparison uses the captured snapshot, not a changing live DB.'}


if __name__=='__main__':print(json.dumps(run(),ensure_ascii=False,indent=2))
