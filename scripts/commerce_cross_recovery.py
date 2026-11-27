"""Restore a Windows-generated fictional backup in an isolated Linux container."""
import argparse
import json
import platform
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from commerce_ops_fixtures import seed
from xborder_insight import commerce as c,buyers as b
from xborder_insight.commerce_ops import database_manifest
from xborder_insight.commerce_queries import integrity
from xborder_insight.db.backup import snapshot
from xborder_insight.db.connection import connect


def export_bundle(directory):
    fixture=seed(directory/'source.sqlite3',orders=10,include_buyer=True)
    snapshot(directory/'source.sqlite3',directory/'snapshot.sqlite3')
    meta={'source_os':platform.system(),'manifest':database_manifest(directory/'snapshot.sqlite3'),'fixture':fixture}
    (directory/'manifest.json').write_text(json.dumps(meta,ensure_ascii=False),encoding='utf-8')


def verify(directory):
    meta=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    with TemporaryDirectory(prefix='commerce-linux-recovery-') as temporary:
        temporary=Path(temporary)
        # The completed backup is a closed, consistent file; copy away from the RO mount.
        shutil.copyfile(directory/'snapshot.sqlite3',temporary/'source.sqlite3')
        snapshot(temporary/'source.sqlite3',temporary/'restored.sqlite3')
        restored=database_manifest(temporary/'restored.sqlite3')
        assert restored==meta['manifest'],'Cross-environment table content differs'
        conn=connect(temporary/'restored.sqlite3')
        try:
            fixture=meta['fixture'];order=c.row(conn,'commerce_orders',fixture['buyer_order_id'],'local')
            decision=order['items'][0]['snapshot']['decision']
            assert decision['comparison_reference']['comparison_id']==fixture['comparison_id']
            assert decision['aftersales_scenario']['result_cents']==200
            assert decision['returns_metric_reference']['source_kind']=='public_survey_estimate'
            token=b.login(conn,'local',b.Credentials(email='recovery-fixture@example.test',password='fictional-recovery-pass'))
            user=b.session(conn,'local',token);assert b.own_order(conn,user,order['id'])['status']=='completed'
            fresh=c.checkout(conn,'local','cross-environment',c.Checkout(product_id=fixture['product_id'],quantity=1))
            c.pay(conn,'local',fresh['id'],c.Payment(event_id='cross-environment-pay',amount_cents=3000))
            c.transition(conn,'local',fresh['id'],'refunded')
            checked=integrity(conn,'local');assert checked['ok']
        finally:conn.close()
        return {'status':'passed','fixture_data_kind':'simulation','measurement_kind':'observed_cross_environment_restore',
                'source_os':meta['source_os'],'destination_os':platform.system(),'schema_version':restored['schema_version'],
                'content_matches':True,'source_content_sha256':meta['manifest']['content_sha256'],
                'checks':['complete table content preserved','comparison and metric provenance preserved','buyer login and owned order preserved',
                          'new simulated checkout/payment/refund succeeds'],'integrity':checked,
                'scope':'Different OS/container on the same physical host; not independent-host disaster recovery or off-site backup storage.'}


def run(image):
    with TemporaryDirectory(prefix='commerce-cross-recovery-') as temporary:
        directory=Path(temporary);export_bundle(directory)
        command=['docker','run','--rm','--pull','never','--network','none','--read-only','--cap-drop','ALL',
                 '--security-opt','no-new-privileges:true','--tmpfs','/tmp:rw,noexec,nosuid,size=268435456',
                 '--mount','type=bind,source='+directory.as_posix()+',target=/bundle,readonly',
                 '--entrypoint','python',image,'scripts/commerce_cross_recovery.py','--verify-bundle','/bundle']
        result=subprocess.run(command,capture_output=True,text=True,encoding='utf-8',timeout=90)
        if result.returncode:raise RuntimeError('Cross-environment recovery failed: '+result.stderr[-1500:])
        return json.loads(result.stdout)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--verify-bundle',type=Path)
    parser.add_argument('--image',default='crossborder-commerce:local');parser.add_argument('--output',type=Path);args=parser.parse_args()
    if args.output and args.output.exists():raise FileExistsError('请保留旧报告并选择新文件名')
    report=verify(args.verify_bundle) if args.verify_bundle else run(args.image)
    if args.output:
        with args.output.open('x',encoding='utf-8') as target:json.dump(report,target,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False,indent=2))
