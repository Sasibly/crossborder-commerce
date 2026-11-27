"""Deterministic offline end-to-end demo in a fresh temporary database."""
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fastapi.testclient import TestClient
from xborder_insight import api
from xborder_insight.db import migrate
from xborder_insight.db.connection import connect


def main():
    os.environ["COMMERCE_LEGACY_GUEST_CHECKOUT"]="true"  # disposable legacy demonstration only
    with TemporaryDirectory() as directory:
        path=Path(directory)/'demo.sqlite3'
        conn=connect(path);migrate.upgrade(conn);conn.close()
        api.DB_FILE=path
        with TestClient(api.app) as client:
            def call(method,path,**kwargs):
                response=client.request(method,path,**kwargs)
                response.raise_for_status()
                return response.json()
            report=call('GET','/v1/commerce/evidence/pet_fountain')
            candidate=call('POST','/v1/commerce/candidates',json={'name':'Quiet fountain','dataset':'pet_fountain','theme_id':report['themes'][0]['theme_id'],'evidence_fingerprint':report['evidence_fingerprint']})
            inputs=dict(price_cents=3000,purchase_cny_cents=7000,cny_per_usd='7',logistics_cents=500,payment_bps=300,payment_fixed_cents=30,aftersales_cents=100,acquisition_cents=300,risk='clear',source_note='Synthetic offline demo, not verified commercial data')
            decision=call('POST',f"/v1/commerce/candidates/{candidate['id']}/decisions",json=inputs)
            product=call('POST',f"/v1/commerce/decisions/{decision['id']}/draft")
            call('POST',f"/v1/commerce/products/{product['id']}/stock",json={'quantity':3})
            call('POST',f"/v1/commerce/products/{product['id']}/publish")
            order=call('POST','/shop/api/orders',headers={'Idempotency-Key':'demo'},json={'product_id':product['id'],'quantity':1})
            call('POST',f"/v1/commerce/orders/{order['id']}/pay",json={'event_id':'demo-pay','amount_cents':3000})
            call('POST',f"/v1/commerce/orders/{order['id']}/ship",json={'tracking':'DEMO-001','actual_logistics_cents':550})
            call('POST',f"/v1/commerce/orders/{order['id']}/complete")
            report=call('GET','/v1/commerce/review')
            assert report[0]['difference_cents']==-50
            print(json.dumps({'status':'passed','data_kind':'simulation','review':report},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
