"""Cross-view regression paths found by the independent consistency review."""
from concurrent.futures import ThreadPoolExecutor
import json

import pytest
from fastapi.testclient import TestClient

from xborder_insight import api, buyers as b, commerce as c, commerce_queries as q
from xborder_insight.db import migrate
from xborder_insight.db.connection import connect
from test_buyers import shop, signup, populate, ADDRESS, CREDS
from test_commerce import product, assumptions
from test_commerce_access import secured


def order_for_buyer(client,products):
    headers=signup(client);address=populate(client,products,headers)
    preview=client.get('/shop/api/checkout-preview').json()
    body={'address_id':address['id'],'cart_fingerprint':preview['cart_fingerprint']}
    key=headers|{'Idempotency-Key':'intent'}
    result=client.post('/shop/api/checkout',json=body,headers=key)
    assert result.status_code==200,result.text
    return headers,body,key,result.json()


def test_checkout_replay_does_not_consume_changed_cart(shop):
    client,path,products=shop
    headers,body,key,order=order_for_buyer(client,products)
    client.post('/shop/api/cart',json={'product_id':products[0]['id'],'quantity':1},headers=headers)
    # Replaying the ORIGINAL intent returns its order; it never consumes a new cart.
    assert client.post('/shop/api/checkout',json=body,headers=key).json()['id']==order['id']
    new=client.get('/shop/api/checkout-preview').json()
    changed=body|{'cart_fingerprint':new['cart_fingerprint']}
    assert client.post('/shop/api/checkout',json=changed,headers=key).status_code==409
    assert client.get('/shop/api/cart').json()[0]['quantity']==1
    result=client.post('/shop/api/checkout',json=changed,headers=headers|{'Idempotency-Key':'new-intent'})
    assert result.status_code==200 and result.json()['quantity']==1


@pytest.mark.parametrize('change',['quantity','price','unpublish'])
def test_stale_preview_rejects_entire_checkout(shop,change):
    client,path,products=shop;headers=signup(client);address=populate(client,products,headers)
    preview=client.get('/shop/api/checkout-preview').json()
    db=connect(path)
    if change=='quantity':
        client.post('/shop/api/cart',json={'product_id':products[0]['id'],'quantity':1},headers=headers)
    elif change=='price':db.execute('UPDATE commerce_products SET price_cents=4000 WHERE id=?',(products[0]['id'],))
    else:c.unpublish(db,'local',products[0]['id'])
    response=client.post('/shop/api/checkout',json={'address_id':address['id'],'cart_fingerprint':preview['cart_fingerprint']},headers=headers|{'Idempotency-Key':'stale'})
    assert response.status_code==409
    assert db.execute('SELECT COUNT(*) FROM commerce_orders').fetchone()[0]==0
    assert all(c.row(db,'commerce_products',p['id'],'local')['reserved']==0 for p in products)
    db.close()


def test_legacy_checkout_replay_rejects_new_cart(shop):
    client,path,products=shop;headers=signup(client);address=populate(client,products,headers)
    body={'address_id':address['id']};key=headers|{'Idempotency-Key':'legacy-cart'}
    assert client.post('/shop/api/checkout',json=body,headers=key).status_code==200
    assert client.post('/shop/api/checkout',json=body,headers=key).status_code==200
    client.post('/shop/api/cart',json={'product_id':products[0]['id'],'quantity':1},headers=headers)
    assert client.post('/shop/api/checkout',json=body,headers=key).status_code==409


def test_recreated_identical_cart_is_a_new_checkout_intent(shop):
    client,path,products=shop
    headers,body,key,order=order_for_buyer(client,products)
    for p in products:
        client.post('/shop/api/cart',json={'product_id':p['id'],'quantity':2},headers=headers).raise_for_status()
    preview=client.get('/shop/api/checkout-preview').json()
    assert preview['cart_fingerprint']!=body['cart_fingerprint']
    new_body=body|{'cart_fingerprint':preview['cart_fingerprint']}
    assert client.post('/shop/api/checkout',json=new_body,headers=key).status_code==409
    result=client.post('/shop/api/checkout',json=new_body,headers=headers|{'Idempotency-Key':'recreated-cart'})
    assert result.status_code==200 and result.json()['id']!=order['id']


def test_refund_review_and_execution_remain_distinct_and_shipping_pauses(shop):
    client,path,products=shop;headers,body,key,order=order_for_buyer(client,products);oid=order['id']
    client.post(f'/v1/commerce/orders/{oid}/pay',json={'event_id':'refund-review','amount_cents':order['amount_cents']}).raise_for_status()
    refund=client.post(f'/shop/api/my/orders/{oid}/refund',json={'reason':'Simulated refund reason'},headers=headers).json()
    ship={'tracking':'SIM','actual_logistics_cents':500}
    assert client.post(f'/v1/commerce/orders/{oid}/ship',json=ship).status_code==409
    summary=client.get('/v1/commerce/orders?view=summary').json()['items'][0]
    assert summary['refund_pending']==1
    client.post(f"/v1/commerce/refunds/{refund['id']}/review",json={'approve':False,'note':'Original rejection'}).raise_for_status()
    client.post(f'/v1/commerce/orders/{oid}/refund').raise_for_status()
    client.post(f'/v1/commerce/orders/{oid}/refund').raise_for_status()
    buyer=client.get('/shop/api/my/refunds').json()[0]
    seller=client.get('/v1/commerce/refunds').json()[0]
    assert buyer==seller
    assert buyer['status']=='rejected' and buyer['review_note']=='Original rejection'
    assert buyer['execution_status']=='refunded' and buyer['executed_at']
    db=connect(path)
    assert db.execute("SELECT COUNT(*) FROM commerce_audit WHERE action='order.refunded' AND object_id=?",(oid,)).fetchone()[0]==1
    assert q.integrity(db,'local')['ok'];db.close()


def test_shipping_allowed_after_rejection(shop):
    client,path,products=shop;headers,body,key,order=order_for_buyer(client,products);oid=order['id']
    client.post(f'/v1/commerce/orders/{oid}/pay',json={'event_id':'ship-review','amount_cents':order['amount_cents']}).raise_for_status()
    refund=client.post(f'/shop/api/my/orders/{oid}/refund',json={'reason':'Simulated refund reason'},headers=headers).json()
    client.post(f"/v1/commerce/refunds/{refund['id']}/review",json={'approve':False,'note':'Rejected before shipping'}).raise_for_status()
    assert client.post(f'/v1/commerce/orders/{oid}/ship',json={'tracking':'SIM','actual_logistics_cents':500}).status_code==200


def test_guest_write_disabled_and_cannot_silently_drop_buyer(shop,monkeypatch):
    client,path,products=shop;body={'product_id':products[0]['id'],'quantity':1};key={'Idempotency-Key':'guest'}
    monkeypatch.delenv('COMMERCE_LEGACY_GUEST_CHECKOUT',raising=False)
    assert client.post('/shop/api/orders',json=body,headers=key).status_code==409
    monkeypatch.setenv('COMMERCE_LEGACY_GUEST_CHECKOUT','true')
    signup(client)
    assert client.post('/shop/api/orders',json=body,headers=key).status_code==409
    db=connect(path);assert db.execute('SELECT COUNT(*) FROM commerce_orders').fetchone()[0]==0;db.close()


def test_evidence_bound_to_dataset_and_version(shop):
    client,path,products=shop
    air=client.get('/v1/commerce/evidence/air_purifier').json()
    coffee=client.get('/v1/commerce/evidence/coffee_machine').json()
    body={'name':'SIM review','dataset':'coffee_machine','theme_id':coffee['themes'][0]['theme_id'],'evidence_fingerprint':air['evidence_fingerprint']}
    assert client.post('/v1/commerce/candidates',json=body).status_code==409
    body['evidence_fingerprint']=coffee['evidence_fingerprint']
    response=client.post('/v1/commerce/candidates',json=body)
    assert response.status_code==200,response.text
    assert response.json()['source_json']['theme']==coffee['themes'][0]


def test_replacement_transfers_stock_once_and_preserves_paid_order(conn):
    p=product(conn,stock=5);order=c.checkout(conn,'local','before-replace',c.Checkout(product_id=p['id'],quantity=1))
    decision=c.decide(conn,'local',p['snapshot']['candidate']['id'],assumptions(price_cents=4000))
    with pytest.raises(c.InvalidStateTransition):c.replace_product(conn,'local',p['id'],decision['id'])
    assert conn.execute('SELECT COUNT(*) FROM commerce_products').fetchone()[0]==1
    c.pay(conn,'local',order['id'],c.Payment(event_id='before-replace-pay',amount_cents=3000))
    before=c.row(conn,'commerce_orders',order['id'],'local')
    new=c.replace_product(conn,'local',p['id'],decision['id'])
    assert c.replace_product(conn,'local',p['id'],decision['id'])==new
    old=c.row(conn,'commerce_products',p['id'],'local')
    assert (old['status'],old['stock'],new['status'],new['stock'],new['price_cents'])==('draft',0,'published',4,4000)
    assert old['snapshot']==p['snapshot']
    assert c.row(conn,'commerce_orders',order['id'],'local')==before
    assert q.integrity(conn,'local')['ok']


def test_replacement_wrong_candidate_and_tenant_rejected(conn):
    p=product(conn);other=product(conn)
    with pytest.raises(c.InputInvalid):c.replace_product(conn,'local',p['id'],other['decision_id'])
    with pytest.raises(c.NotFound):c.replace_product(conn,'other',p['id'],other['decision_id'])
    assert c.row(conn,'commerce_products',p['id'],'local')==p


def test_unpublish_hides_catalog_and_stale_cart_cannot_checkout(shop):
    client,path,products=shop;headers=signup(client);address=populate(client,products,headers);pid=products[0]['id']
    assert client.post(f'/v1/commerce/products/{pid}/unpublish').status_code==200
    assert pid not in {p['id'] for p in client.get('/shop/api/products').json()}
    assert next(i for i in client.get('/shop/api/cart').json() if i['product_id']==pid)['status']=='draft'
    assert client.post('/shop/api/checkout',json={'address_id':address['id']},headers=headers|{'Idempotency-Key':'hidden'}).status_code==409
    assert client.post(f'/v1/commerce/products/{pid}/publish').status_code==200


def test_tenant_identity_and_product_permissions(secured):
    client,path,p,auth=secured
    assert client.get('/v1/commerce/me',headers=auth['owner']).json()['shop_matches_tenant']
    assert not client.get('/v1/commerce/me',headers=auth['other']).json()['shop_matches_tenant']
    for action,body in [('unpublish',{}),('replace',{'decision_id':p['decision_id']})]:
        assert client.post(f"/v1/commerce/products/{p['id']}/{action}",json=body,headers=auth['viewer']).status_code==403
        assert client.post(f"/v1/commerce/products/{p['id']}/{action}",json=body,headers=auth['other']).status_code==404


def test_summary_consistent_while_another_connection_refunds(tmp_path,monkeypatch):
    path=tmp_path/'snapshot.sqlite3';db=connect(path);migrate.upgrade(db);p=product(db)
    order=c.checkout(db,'local','summary',c.Checkout(product_id=p['id'],quantity=1));oid=order['id']
    c.pay(db,'local',oid,c.Payment(event_id='summary-pay',amount_cents=3000))
    c.transition(db,'local',oid,'shipped',c.Shipment(tracking='SIM',actual_logistics_cents=500));c.transition(db,'local',oid,'completed')
    original=c._review
    def interleaved(conn,tenant,orders=None):
        writer=connect(path)
        c.transition(writer,tenant,oid,'refunded')
        b.settle_refund(writer,tenant,oid,b.RefundCosts(procurement_loss_cents=0,logistics_loss_cents=500,payment_loss_cents=120,other_loss_cents=300,note='Simulated costs'))
        writer.close()
        return original(conn,tenant,orders)
    monkeypatch.setattr(c,'_review',interleaved)
    result=c.summary(db,'local')
    assert result['status_counts']['completed']==1 and result['refunded_cents']==0
    assert result['known_contribution_cents']==980
    monkeypatch.setattr(c,'_review',original)
    result=c.summary(db,'local')
    assert result['status_counts']['refunded']==1 and result['refunded_cents']==3000
    assert result['known_contribution_cents']==-920;db.close()


def test_ports_use_separate_cookie_names_and_legacy_migration(shop):
    client,path,products=shop
    jars=[]
    for port in (8031,8027):
        with TestClient(api.app,base_url=f'http://127.0.0.1:{port}') as instance:
            response=instance.post('/shop/api/account/register',json=CREDS|{'email':f'port-{port}@example.test'})
            assert response.status_code==200
            assert f'cb_buyer_{port}=' in response.headers['set-cookie']
            jars.append(dict(instance.cookies))
            assert instance.get('/shop/api/account/me').status_code==200
    with TestClient(api.app,base_url='http://127.0.0.1:8027') as dev:
        dev.cookies.update(jars[0])
        assert dev.get('/shop/api/account/me').status_code==401
        dev.cookies.update(jars[1]);assert dev.get('/shop/api/account/me').status_code==200
    token=jars[0]['cb_buyer_8031']
    for port,expected in ((8031,200),(8027,401)):
        with TestClient(api.app,base_url=f'http://127.0.0.1:{port}') as instance:
            instance.cookies.set('cb_buyer',token,path='/shop')
            response=instance.get('/shop/api/account/me');assert response.status_code==expected
            if expected==200:
                assert 'cb_buyer_8031=' in response.headers['set-cookie']
                csrf=response.json()['csrf']
                instance.post('/shop/api/account/logout',json={},headers={'X-CSRF-Token':csrf}).raise_for_status()
                assert instance.get('/shop/api/account/me').status_code==401
