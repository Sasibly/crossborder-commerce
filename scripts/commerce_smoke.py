"""HTTP smoke test against a loopback MOCK deployment; creates fictional demo data."""
import argparse
import json
import os
import secrets
from urllib.parse import urlsplit

import httpx


def run(base_url):
    if urlsplit(base_url).hostname not in ('localhost','127.0.0.1','::1'):
        raise ValueError('烟测仅允许本机模拟环境')
    seller_headers={}
    if os.getenv('COMMERCE_SELLER_KEY'):
        seller_headers['Authorization']='Bearer '+os.environ['COMMERCE_SELLER_KEY']
    with httpx.Client(base_url=base_url,timeout=15) as client:
        def request(method,path,body=None,headers=None):
            result=client.request(method,path,json=body,headers=headers or {})
            result.raise_for_status()
            return result.json()
        health=request('GET','/health')
        if health['run_mode']!='mock':
            raise ValueError('拒绝对非 mock 环境创建测试交易')
        request('GET','/ready')
        products=[p for p in request('GET','/shop/api/products') if p['stock']>=1][:2]
        if len(products)<2:
            raise ValueError('请先执行 seed_commerce.py，至少需要两种有库存商品')
        user=request('POST','/shop/api/account/register',{'email':f'smoke-{secrets.token_hex(8)}@example.test','password':secrets.token_urlsafe(24)})
        csrf={'X-CSRF-Token':user['csrf']}
        address=request('POST','/shop/api/addresses',dict(recipient='Smoke Buyer',line1='123 Example Street',city='Seattle',state='WA',postal_code='98101'),csrf)
        for p in products:
            request('POST','/shop/api/cart',{'product_id':p['id'],'quantity':1},csrf)
        checkout_headers=csrf|{'Idempotency-Key':'smoke-'+secrets.token_hex(8)}
        preview=request('GET','/shop/api/checkout-preview')
        checkout_body={'address_id':address['id'],'cart_fingerprint':preview['cart_fingerprint']}
        order=request('POST','/shop/api/checkout',checkout_body,checkout_headers)
        assert len(order['items'])==2
        assert request('POST','/shop/api/checkout',checkout_body,checkout_headers)['id']==order['id']
        request('POST',f"/shop/api/my/orders/{order['id']}/pay",{},csrf)
        request('POST',f"/shop/api/my/orders/{order['id']}/pay",{},csrf)
        refund=request('POST',f"/shop/api/my/orders/{order['id']}/refund",{'reason':'Smoke test full refund'},csrf)
        request('POST',f"/v1/commerce/refunds/{refund['id']}/review",{'approve':True,'note':'Smoke approved'},seller_headers)
        request('POST','/v1/commerce/refund-costs/'+order['id'],dict(procurement_loss_cents=0,logistics_loss_cents=0,
                payment_loss_cents=0,other_loss_cents=0,note='Mock unshipped transaction; explicitly recorded zero net losses'),seller_headers)
        assert request('GET','/shop/api/my/orders/'+order['id'])['status']=='refunded'
        report=next(r for r in request('GET','/v1/commerce/review',headers=seller_headers) if r['order_id']==order['id'])
        assert report['recorded_contribution_cents']==0
        after={p['id']:p for p in request('GET','/shop/api/products')}
        assert all(after[p['id']]['stock']==p['stock'] for p in products)
        request('POST','/shop/api/account/logout',{},csrf)
        print(json.dumps({'status':'passed','data_kind':'simulation','order_id':order['id'],
                           'line_count':2,'refund':'approved','inventory_restored':True},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8031')
    run(parser.parse_args().base_url)
