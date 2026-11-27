"""Restore a new isolated DB and validate provenance, buyer ownership and a new order."""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

from commerce_ops_fixtures import seed
from xborder_insight import commerce as c,buyers as b
from xborder_insight.commerce_ops import database_manifest
from xborder_insight.db.backup import snapshot
from xborder_insight.db.connection import connect
from xborder_insight.commerce_queries import integrity


def run():
    with TemporaryDirectory(prefix='commerce-recovery-') as directory:
        directory=Path(directory);live=directory/'live.sqlite3';backup=directory/'backup.sqlite3';restored=directory/'restored.sqlite3'
        fixture=seed(live,orders=10,include_buyer=True)
        writer=connect(live)
        try:
            # Keep a writer open after a committed change so the backup must include WAL.
            c.create_candidate(writer,'local',c.Candidate(name='SIM / Committed WAL marker',dataset='synthetic',theme_id='wal'),{'data_kind':'simulation'})
            assert Path(str(live)+'-wal').is_file()
            before=database_manifest(live)
            start=time.perf_counter();snapshot(live,backup);backup_ms=(time.perf_counter()-start)*1000
            start=time.perf_counter();snapshot(backup,restored);restore_ms=(time.perf_counter()-start)*1000
            after=database_manifest(restored)
            assert before==after,'Restored content differs from committed source snapshot'
            conn=connect(restored)
            try:
                comparison=c.row(conn,'commerce_profit_comparisons',fixture['comparison_id'],'local')
                order=c.row(conn,'commerce_orders',fixture['buyer_order_id'],'local')
                frozen=order['items'][0]['snapshot']['decision']
                assert frozen['comparison_reference']['comparison_id']==comparison['id']
                assert frozen['aftersales_scenario']['result_cents']==200
                assert frozen['returns_metric_reference']['source_kind']=='public_survey_estimate'
                with c.transaction(conn):
                    token=b.login(conn,'local',b.Credentials(email='recovery-fixture@example.test',password='fictional-recovery-pass'))
                buyer=b.session(conn,'local',token)
                assert b.own_order(conn,buyer,order['id'])['status']=='completed'
                fresh=c.checkout(conn,'local','after-recovery',c.Checkout(product_id=fixture['product_id'],quantity=1))
                c.pay(conn,'local',fresh['id'],c.Payment(event_id='after-recovery-payment',amount_cents=3000))
                c.transition(conn,'local',fresh['id'],'refunded')
                checked=integrity(conn,'local');assert checked['ok']
            finally:conn.close()
            assert database_manifest(live)==before,'Recovery validation unexpectedly modified source DB'
            return {'status':'passed','data_kind':'simulation','fixture_data_kind':'simulation',
                    'measurement_kind':'observed_local_backup_and_restore','source_unchanged':True,'committed_wal_included':True,
                    'content_matches_before_post_restore_writes':True,'source_manifest':before,
                    'backup_ms':round(backup_ms,3),'restore_ms':round(restore_ms,3),
                    'recovery_scope':'local same-machine snapshot/restore only; not off-machine disaster recovery or a production RPO/RTO',
                    'checks':['all table row counts and content digests match','comparison/aftersales/public reference preserved',
                              'buyer password login and order ownership work','new checkout, mock payment and refund work',
                              'source not replaced or modified'],'integrity':checked}
        finally:writer.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():raise FileExistsError('请使用新的报告文件名')
    report=run();args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as target:json.dump(report,target,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
