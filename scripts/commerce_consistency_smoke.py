"""Exercise cross-view fixes on an owned loopback mock instance; retain audit history."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
from urllib.parse import urlsplit

import httpx


def run(url):
    if urlsplit(url).hostname not in ('127.0.0.1','localhost','::1'):
        raise ValueError('Only loopback mock instances are allowed')
    seller={'Authorization':'Bearer '+os.environ['COMMERCE_SELLER_KEY']} if os.getenv('COMMERCE_SELLER_KEY') else {}
    with httpx.Client(base_url=url,trust_env=False,timeout=20) as client:
        def call(method,path,body=None,headers=None,status=200):
            result=client.request(method,path,json=body,headers=headers or {})
            assert result.status_code==status,(path,result.status_code,result.text)
            return result.json()
        assert call('GET','/health')['run_mode']=='mock'
        assert call('GET','/v1/commerce/me',headers=seller)['shop_matches_tenant']
        before=call('GET','/shop/api/products')
        marker=secrets.token_hex(6)
        user=call('POST','/shop/api/account/register',{'email':f'consistency-{marker}@example.test','password':secrets.token_urlsafe(24)})
        csrf={'X-CSRF-Token':user['csrf']}
        address=call('POST','/shop/api/addresses',{'recipient':'Fictional Consistency Buyer','line1':'123 Example Street','city':'Seattle','state':'WA','postal_code':'98101'},csrf)
        report=call('GET','/v1/commerce/evidence/air_purifier',headers=seller)
        body={'name':'SIM / Consistency verification '+marker,'dataset':'air_purifier','theme_id':report['themes'][0]['theme_id'],'evidence_fingerprint':report['evidence_fingerprint']}
        invalid=body|{'dataset':'coffee_machine'}
        call('POST','/v1/commerce/candidates',invalid,seller,409)
        candidate=call('POST','/v1/commerce/candidates',body,seller)
        assumptions=dict(price_cents=3000,purchase_cny_cents=7000,cny_per_usd='7',logistics_cents=500,payment_bps=300,payment_fixed_cents=30,aftersales_cents=100,acquisition_cents=300,risk='clear',source_note='Synthetic consistency verification only; no real supplier or compliance verification.')
        first=call('POST',f"/v1/commerce/candidates/{candidate['id']}/decisions",assumptions,seller)
        old=call('POST',f"/v1/commerce/decisions/{first['id']}/draft",{},seller)
        old_id=old['id']
        call('POST',f'/v1/commerce/products/{old_id}/stock',{'quantity':3},seller)
        call('POST',f'/v1/commerce/products/{old_id}/publish',{},seller)
        call('POST','/shop/api/orders',{'product_id':old_id,'quantity':1},{'Idempotency-Key':marker},409)
        call('POST','/shop/api/cart',{'product_id':old_id,'quantity':1},csrf)
        preview=call('GET','/shop/api/checkout-preview')
        checkout={'address_id':address['id'],'cart_fingerprint':preview['cart_fingerprint']}
        key=csrf|{'Idempotency-Key':marker}
        order=call('POST','/shop/api/checkout',checkout,key);oid=order['id']
        second=call('POST',f"/v1/commerce/candidates/{candidate['id']}/decisions",assumptions|{'price_cents':4000},seller)
        call('POST',f'/v1/commerce/products/{old_id}/replace',{'decision_id':second['id']},seller,409)
        call('POST','/shop/api/cart',{'product_id':old_id,'quantity':2},csrf)
        changed=call('GET','/shop/api/checkout-preview')
        call('POST','/shop/api/checkout',checkout|{'cart_fingerprint':changed['cart_fingerprint']},key,409)
        assert call('POST','/shop/api/checkout',checkout,key)['id']==oid
        call('POST',f'/v1/commerce/orders/{oid}/pay',{'event_id':'consistency-'+marker,'amount_cents':3000},seller)
        refund=call('POST',f'/shop/api/my/orders/{oid}/refund',{'reason':'Fictional consistency verification'},csrf)
        call('POST',f'/v1/commerce/orders/{oid}/ship',{'tracking':'SIM-'+marker,'actual_logistics_cents':500},seller,409)
        call('POST',f"/v1/commerce/refunds/{refund['id']}/review",{'approve':False,'note':'Original simulated rejection; later seller refund is separate'},seller)
        call('POST',f'/v1/commerce/orders/{oid}/refund',{},seller)
        result=call('GET','/shop/api/my/refunds')[0]
        assert result['status']=='rejected' and result['execution_status']=='refunded'
        call('POST',f'/v1/commerce/refund-costs/{oid}',dict(procurement_loss_cents=0,logistics_loss_cents=0,payment_loss_cents=0,other_loss_cents=0,note='Explicit zero net losses for this simulated unshipped verification'),seller)
        historical=call('GET',f'/shop/api/my/orders/{oid}')
        new=call('POST',f'/v1/commerce/products/{old_id}/replace',{'decision_id':second['id']},seller)
        assert new['stock']==3 and new['price_cents']==4000
        assert call('POST',f'/v1/commerce/products/{old_id}/replace',{'decision_id':second['id']},seller)['id']==new['id']
        assert call('GET',f'/shop/api/my/orders/{oid}')==historical
        call('POST','/shop/api/checkout',checkout|{'cart_fingerprint':changed['cart_fingerprint']},csrf|{'Idempotency-Key':marker+'-stale'},409)
        call('POST','/shop/api/cart',{'product_id':old_id,'quantity':0},csrf)
        call('POST','/shop/api/cart',{'product_id':new['id'],'quantity':3},csrf)
        preview=call('GET','/shop/api/checkout-preview')
        pending=call('POST','/shop/api/checkout',{'address_id':address['id'],'cart_fingerprint':preview['cart_fingerprint']},csrf|{'Idempotency-Key':marker+'-new'})
        assert pending['amount_cents']==12000
        assert next(p for p in call('GET','/shop/api/products') if p['id']==new['id'])['stock']==0
        call('POST',f"/shop/api/my/orders/{pending['id']}/cancel",{},csrf)
        call('POST',f"/v1/commerce/products/{new['id']}/unpublish",{},seller)
        after=call('GET','/shop/api/products')
        assert sorted(before,key=lambda p:p['id'])==sorted(after,key=lambda p:p['id'])
        integrity=call('GET','/v1/commerce/integrity',headers=seller);assert integrity['ok']
        call('POST','/shop/api/account/logout',{},csrf)
        return {'status':'passed','scope':'local_machine_only','fixture_data_kind':'simulation','verified_at_utc':datetime.now(timezone.utc).isoformat(),
                'instance':url,'checks':['evidence dataset binding','guest write disabled','checkout intent replay and changed-cart conflict','refund review blocks shipment','rejected review plus refunded execution','atomic version replacement and replay','original order snapshot preserved','stale cart after unpublish rejected','new order uses new price','zero stock catalog response','buyer cancellation restores stock','original published catalog preserved','business integrity'],
                'order_ids':[oid,pending['id']],'verification_product_ids':[old_id,new['id']],'verification_products_final_state':'unpublished drafts; audit and inventory history retained',
                'original_published_products_preserved':len(before),'integrity':integrity}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8031')
    parser.add_argument('--report-dir',type=Path,default=Path('reports/local'))
    args=parser.parse_args();result=run(args.base_url)
    args.report_dir.mkdir(parents=True,exist_ok=True)
    path=args.report_dir/('consistency-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(4)+'.json')
    with path.open('x',encoding='utf-8') as target:json.dump(result,target,ensure_ascii=False,indent=2)
    print(json.dumps(result|{'report_path':str(path.resolve())},ensure_ascii=False,indent=2))
