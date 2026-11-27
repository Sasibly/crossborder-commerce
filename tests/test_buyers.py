"""Ownership, multi-item atomicity, CSRF, refunds, migration and expiry checks."""
import asyncio
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from xborder_insight import api, buyers as b, commerce as c
from xborder_insight.commerce_worker import serve, sweep
from xborder_insight.db import migrate
from xborder_insight.db.connection import connect
from xborder_insight.errors import Unauthorized
from test_commerce import product

ADDRESS=dict(recipient='Demo Buyer',line1='123 Example Street',line2='',city='Seattle',state='WA',postal_code='98101')
CREDS=dict(email='demo@example.test',password='fictional-password-42')


@pytest.fixture
def shop(tmp_path,monkeypatch):
    path=tmp_path/'buyers.sqlite3'
    db=connect(path);migrate.upgrade(db)
    products=[product(db,stock=5),product(db,stock=5)]
    db.close()
    monkeypatch.setattr(api,'DB_FILE',path)
    with TestClient(api.app) as client:
        yield client,path,products


def signup(client,email=CREDS['email']):
    r=client.post('/shop/api/account/register',json=CREDS|{'email':email})
    assert r.status_code==200,r.text
    return {'X-CSRF-Token':r.json()['csrf']}


def populate(client,products,headers):
    address=client.post('/shop/api/addresses',json=ADDRESS,headers=headers).json()
    for p in products:
        assert client.post('/shop/api/cart',json={'product_id':p['id'],'quantity':2},headers=headers).status_code==200
    return address


def test_password_and_session_security(conn):
    token=b.register(conn,'local',b.Credentials(**CREDS))
    record=conn.execute('SELECT * FROM commerce_buyers').fetchone()
    assert CREDS['password'] not in record['password_hash']
    assert b.password_matches(CREDS['password'],record['password_hash'])
    session=conn.execute('SELECT * FROM commerce_sessions').fetchone()
    assert session['token_hash']!=token and session['token_hash']==b.digest(token)
    with pytest.raises(Unauthorized):
        b.login(conn,'local',b.Credentials(**(CREDS|{'password':'wrong-password'})))
    with pytest.raises(Unauthorized):
        b.session(conn,'other',token)
    conn.execute('UPDATE commerce_sessions SET expires_at=0')
    with pytest.raises(Unauthorized):
        b.session(conn,'local',token)


def test_cookie_csrf_login_logout(shop):
    client,path,products=shop
    response=client.post('/shop/api/account/register',json=CREDS)
    cookie=response.headers['set-cookie'].lower()
    assert 'httponly' in cookie and 'samesite=lax' in cookie and 'path=/shop' in cookie
    headers={'X-CSRF-Token':response.json()['csrf']}
    assert client.post('/shop/api/addresses',json=ADDRESS).status_code==401
    assert client.post('/shop/api/addresses',json=ADDRESS,headers=headers|{'Origin':'https://evil.example'}).status_code==401
    assert client.post('/shop/api/addresses',json=ADDRESS,headers=headers).status_code==200
    assert client.post('/shop/api/account/logout',headers=headers).status_code==200
    assert client.get('/shop/api/account/me').status_code==401
    assert client.post('/shop/api/account/login',json=CREDS).status_code==200
    assert client.get('/shop/api/account/me').json()['email']==CREDS['email']


def test_multi_order_snapshots_replay_and_privacy(shop):
    client,path,products=shop
    headers=signup(client)
    address=populate(client,products,headers)
    checkout_headers=headers|{'Idempotency-Key':'multi'}
    result=client.post('/shop/api/checkout',json={'address_id':address['id']},headers=checkout_headers)
    assert result.status_code==200,result.text
    order=result.json()
    assert order['quantity']==4 and len(order['items'])==2 and order['amount_cents']==12000
    assert 'snapshot' not in order and 'token' not in order
    assert client.get('/shop/api/cart').json()==[]
    replay=client.post('/shop/api/checkout',json={'address_id':address['id']},headers=checkout_headers)
    assert replay.json()['id']==order['id']
    db=connect(path)
    db.execute('UPDATE commerce_addresses SET address_json=? WHERE id=?',(c.dump(ADDRESS|{'city':'Changed'}),address['id']))
    db.execute('UPDATE commerce_products SET price_cents=4000')
    db.close()
    own=client.get('/shop/api/my/orders/'+order['id']).json()
    assert own['address']['city']=='Seattle'
    assert all(i['unit_price_cents']==3000 for i in own['items'])
    assert client.get('/shop/api/orders/'+order['id']).status_code==404
    assert client.post(f"/shop/api/my/orders/{order['id']}/cancel",headers=headers).status_code==200
    db=connect(path)
    assert all(c.row(db,'commerce_products',p['id'],'local')['stock']==5 for p in products)
    db.close()


def test_cart_atomic_rollback_and_owner_boundaries(shop):
    client,path,products=shop
    headers=signup(client)
    address=populate(client,products,headers)
    db=connect(path);db.execute('UPDATE commerce_products SET stock=1 WHERE id=?',(products[1]['id'],));db.close()
    r=client.post('/shop/api/checkout',json={'address_id':address['id']},headers=headers|{'Idempotency-Key':'fail'})
    assert r.status_code==409
    assert len(client.get('/shop/api/cart').json())==2
    db=connect(path)
    assert c.row(db,'commerce_products',products[0]['id'],'local')['stock']==5
    assert all(c.row(db,'commerce_products',p['id'],'local')['reserved']==0 for p in products)
    assert db.execute('SELECT COUNT(*) FROM commerce_orders').fetchone()[0]==0
    db.close()
    with TestClient(api.app) as other:
        other_headers=signup(other,'other@example.test')
        assert other.get('/shop/api/addresses').json()==[]
        assert other.get('/shop/api/cart').json()==[]
        assert other.post('/shop/api/checkout',json={'address_id':address['id']},headers=other_headers|{'Idempotency-Key':'stolen'}).status_code==404


def test_buyer_cannot_read_cancel_or_refund_other_order(shop):
    client,path,products=shop
    headers=signup(client)
    address=populate(client,products[:1],headers)
    order=client.post('/shop/api/checkout',json={'address_id':address['id']},headers=headers|{'Idempotency-Key':'owner'}).json()
    with TestClient(api.app) as other:
        other_headers=signup(other,'other@example.test')
        assert other.get('/shop/api/my/orders').json()==[]
        assert other.get('/shop/api/my/orders/'+order['id']).status_code==404
        assert other.post('/shop/api/my/orders/'+order['id']+'/cancel',headers=other_headers).status_code==404
        assert other.post('/shop/api/my/orders/'+order['id']+'/refund',json={'reason':'Other account'},headers=other_headers).status_code==404


@pytest.mark.parametrize('shipped',[False,True])
def test_reviewed_multi_refund_and_loss(shop,shipped):
    client,path,products=shop
    headers=signup(client)
    address=populate(client,products,headers)
    order=client.post('/shop/api/checkout',json={'address_id':address['id']},headers=headers|{'Idempotency-Key':'refund'}).json()
    oid=order['id']
    assert client.post(f'/shop/api/my/orders/{oid}/refund',json={'reason':'Pending unpaid'},headers=headers).status_code==409
    assert client.post(f'/shop/api/my/orders/{oid}/pay',json={},headers=headers).status_code==200
    if shipped:
        client.post(f'/v1/commerce/orders/{oid}/ship',json={'tracking':'DEMO','actual_logistics_cents':2100})
        client.post(f'/v1/commerce/orders/{oid}/complete')
        report=client.get('/v1/commerce/review').json()[0]
        assert report['predicted_profit_cents']==3920 and report['recorded_contribution_cents']==3910
    refund=client.post(f'/shop/api/my/orders/{oid}/refund',json={'reason':'Demo product issue'},headers=headers).json()
    assert client.get('/shop/api/my/orders/'+oid).json()['status']==('completed' if shipped else 'paid')
    assert client.post(f"/v1/commerce/refunds/{refund['id']}/review",json={'approve':True,'note':'Demo refund approved'}).status_code==200
    assert client.get('/shop/api/my/refunds').json()[0]['status']=='approved'
    assert client.post(f"/v1/commerce/refunds/{refund['id']}/review",json={'approve':True,'note':'Repeated approval'}).status_code==200
    assert client.get('/v1/commerce/review').json()[0]['recorded_contribution_cents'] is None
    costs=dict(procurement_loss_cents=100,logistics_loss_cents=200,payment_loss_cents=120,other_loss_cents=300,note='Demo net losses')
    assert client.post('/v1/commerce/refund-costs/'+oid,json=costs).status_code==200
    assert client.get('/v1/commerce/review').json()[0]['recorded_contribution_cents']==-720
    assert client.post('/v1/commerce/refund-costs/'+oid,json=costs|{'other_loss_cents':301}).status_code==409
    db=connect(path)
    assert all(c.row(db,'commerce_products',p['id'],'local')['stock']==(3 if shipped else 5) for p in products)
    db.close()


def test_rejection_is_final_and_does_not_refund(shop):
    client,path,products=shop;headers=signup(client);address=populate(client,products[:1],headers)
    order=client.post('/shop/api/checkout',json={'address_id':address['id']},headers=headers|{'Idempotency-Key':'reject'}).json()
    client.post(f"/shop/api/my/orders/{order['id']}/pay",json={},headers=headers)
    refund=client.post(f"/shop/api/my/orders/{order['id']}/refund",json={'reason':'Refund requested'},headers=headers).json()
    endpoint=f"/v1/commerce/refunds/{refund['id']}/review"
    assert client.post(endpoint,json={'approve':False,'note':'Demo rejected'}).status_code==200
    assert client.post(endpoint,json={'approve':True,'note':'Changed mind'}).status_code==409
    assert client.get('/shop/api/my/orders/'+order['id']).json()['status']=='paid'


def test_auth_rate_limit(shop):
    client,path,products=shop
    for i in range(10):
        assert client.post('/shop/api/account/login',json=CREDS).status_code==401
    r=client.post('/shop/api/account/login',json=CREDS)
    assert r.status_code==429 and r.headers['retry-after']=='60'


def test_buyer_payment_uses_order_snapshot_and_is_idempotent(shop):
    client,path,products=shop
    headers=signup(client);address=populate(client,products,headers)
    order=client.post('/shop/api/checkout',json={'address_id':address['id']},headers=headers|{'Idempotency-Key':'buyer-pay'}).json()
    endpoint=f"/shop/api/my/orders/{order['id']}/pay"
    db=connect(path)
    snapshot=c.row(db,'commerce_orders',order['id'],'local')['snapshot']
    db.execute('UPDATE commerce_products SET price_cents=9999');db.close()
    for _ in range(2):
        paid=client.post(endpoint,json={},headers=headers)
        assert paid.status_code==200,paid.text
        assert paid.json()['status']=='paid' and paid.json()['amount_cents']==12000
        assert 'token' not in paid.json() and 'snapshot' not in paid.json()
    db=connect(path)
    assert c.row(db,'commerce_orders',order['id'],'local')['snapshot']==snapshot
    assert db.execute('SELECT COUNT(*) FROM commerce_events WHERE order_id=?',(order['id'],)).fetchone()[0]==1
    audit=db.execute("SELECT actor_id FROM commerce_audit WHERE action='order.paid' AND object_id=?",(order['id'],)).fetchall()
    assert len(audit)==1 and audit[0]['actor_id']==client.get('/shop/api/account/me').json()['id']
    assert all(c.row(db,'commerce_products',p['id'],'local')['reserved']==0 for p in products)
    assert all(c.row(db,'commerce_products',p['id'],'local')['stock']==3 for p in products)
    db.close()


def test_buyer_payment_requires_owner_session_csrf_and_server_amount(shop):
    client,path,products=shop
    headers=signup(client);address=populate(client,products[:1],headers)
    order=client.post('/shop/api/checkout',json={'address_id':address['id']},headers=headers|{'Idempotency-Key':'pay-boundaries'}).json()
    endpoint=f"/shop/api/my/orders/{order['id']}/pay"
    assert client.post(endpoint,json={}).status_code==401
    assert client.post(endpoint,json={},headers=headers|{'Origin':'https://evil.example'}).status_code==401
    for field,value in [('amount_cents',1),('currency','CNY'),('event_id','forged'),('status','paid')]:
        assert client.post(endpoint,json={field:value},headers=headers).status_code==422
    with TestClient(api.app) as other:
        assert other.post(endpoint,json={}).status_code==401
        other_headers=signup(other,'cannot-pay-other@example.test')
        assert other.post(endpoint,json={},headers=other_headers).status_code==404
    db=connect(path)
    db.execute('UPDATE commerce_orders SET tenant=? WHERE id=?',('other',order['id']));db.close()
    assert client.post(endpoint,json={},headers=headers).status_code==404


@pytest.mark.parametrize('state',['cancelled','expired'])
def test_buyer_payment_rejects_cancelled_or_expired_order_without_writes(shop,state):
    client,path,products=shop
    headers=signup(client);address=populate(client,products[:1],headers)
    order=client.post('/shop/api/checkout',json={'address_id':address['id']},headers=headers|{'Idempotency-Key':'pay-state'}).json()
    db=connect(path)
    if state=='expired':db.execute('UPDATE commerce_orders SET expires_at=0 WHERE id=?',(order['id'],))
    else:c.transition(db,'local',order['id'],'cancelled')
    before=c.row(db,'commerce_products',products[0]['id'],'local');db.close()
    assert client.post(f"/shop/api/my/orders/{order['id']}/pay",json={},headers=headers).status_code==409
    db=connect(path)
    assert c.row(db,'commerce_products',products[0]['id'],'local')==before
    assert db.execute('SELECT COUNT(*) FROM commerce_events').fetchone()[0]==0
    db.close()


def test_buyer_payment_failure_rolls_back_and_can_retry(shop,monkeypatch):
    client,path,products=shop
    headers=signup(client);address=populate(client,products[:1],headers)
    order=client.post('/shop/api/checkout',json={'address_id':address['id']},headers=headers|{'Idempotency-Key':'pay-atomic'}).json()
    record=c.record
    def fail(*args,**kwargs):
        if args[2]=='order.paid':raise RuntimeError('simulated audit failure')
        return record(*args,**kwargs)
    monkeypatch.setattr(c,'record',fail)
    endpoint=f"/shop/api/my/orders/{order['id']}/pay"
    with pytest.raises(RuntimeError,match='simulated audit failure'):
        client.post(endpoint,json={},headers=headers)
    db=connect(path)
    assert c.row(db,'commerce_orders',order['id'],'local')['status']=='pending'
    assert c.row(db,'commerce_products',products[0]['id'],'local')['reserved']==2
    assert db.execute('SELECT COUNT(*) FROM commerce_events').fetchone()[0]==0
    db.close();monkeypatch.setattr(c,'record',record)
    assert client.post(endpoint,json={},headers=headers).json()['status']=='paid'


def test_buyer_payment_unavailable_outside_mock_mode(shop,monkeypatch):
    from types import SimpleNamespace
    from xborder_insight import buyers_api
    client,path,products=shop
    headers=signup(client);address=populate(client,products[:1],headers)
    order=client.post('/shop/api/checkout',json={'address_id':address['id']},headers=headers|{'Idempotency-Key':'mock-only'}).json()
    monkeypatch.setattr(buyers_api,'settings',SimpleNamespace(is_mock=False))
    assert client.post(f"/shop/api/my/orders/{order['id']}/pay",json={},headers=headers).status_code==409
    assert client.get('/shop/api/my/orders/'+order['id']).json()['status']=='pending'


@pytest.mark.parametrize('race',['pay','cancel'])
def test_concurrent_buyer_payment_replay_or_cancel_has_one_final_outcome(shop,race):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    client,path,products=shop
    headers=signup(client);address=populate(client,products[:1],headers)
    order=client.post('/shop/api/checkout',json={'address_id':address['id']},headers=headers|{'Idempotency-Key':'payment-race'}).json()
    barrier=Barrier(2)
    def post(action):
        barrier.wait(timeout=5)
        return client.post(f"/shop/api/my/orders/{order['id']}/{action}",json={},headers=headers)
    with ThreadPoolExecutor(max_workers=2) as pool:
        a=pool.submit(post,'pay');b=pool.submit(post,race)
        responses=[a.result(timeout=15),b.result(timeout=15)]
    assert all(response.status_code in (200,409) for response in responses)
    db=connect(path);saved=c.row(db,'commerce_orders',order['id'],'local')
    inventory=c.row(db,'commerce_products',products[0]['id'],'local')
    events=db.execute('SELECT COUNT(*) FROM commerce_events WHERE order_id=?',(order['id'],)).fetchone()[0]
    assert inventory['reserved']==0
    if saved['status']=='paid':assert events==1 and inventory['stock']==3
    else:assert race=='cancel' and saved['status']=='cancelled' and events==0 and inventory['stock']==5
    if race=='pay':assert saved['status']=='paid' and all(r.status_code==200 for r in responses)
    db.close()


def test_legacy_order_backfill_and_downgrade_guard(tmp_path):
    db=connect(tmp_path/'upgrade.sqlite3');migrate.upgrade(db,target=18)
    # v18 order exists before multi-line schema is added.
    import json
    snapshot={'unit_price_cents':3000,'product_title':'Legacy','decision_id':'legacy','decision':{'unit_profit_cents':980}}
    db.execute("INSERT INTO commerce_candidates VALUES('c','local','Legacy','{}',0)")
    db.execute("INSERT INTO commerce_decisions VALUES('d','local','c','{}',0)")
    db.execute("INSERT INTO commerce_products(id,tenant,decision_id,title,price_cents,snapshot,created_at) VALUES('p','local','d','Legacy',3000,'{}',0)")
    db.execute("INSERT INTO commerce_orders(id,tenant,product_id,token,request_key,fingerprint,quantity,amount_cents,status,snapshot,created_at,expires_at) VALUES('o','local','p','t','k','f',2,6000,'completed',?,0,0)",(json.dumps(snapshot),))
    migrate.upgrade(db)
    assert c.row(db,'commerce_orders','o','local')['items'][0]['quantity']==2
    migrate.downgrade(db,target=18);migrate.upgrade(db)
    assert db.execute('SELECT COUNT(*) FROM commerce_order_items').fetchone()[0]==1
    buyer_token=b.register(db,'local',b.Credentials(**CREDS));buyer=b.session(db,'local',buyer_token)
    db.execute('UPDATE commerce_orders SET buyer_id=?',(buyer['id'],))
    with pytest.raises(ValueError):
        migrate.downgrade(db,target=18)
    # Migration batches commit each version: v20 can roll back before v19 refuses.
    assert migrate.current_version(db)==19
    db.close()


def test_background_expiry_without_http_request(tmp_path):
    path=tmp_path/'worker.sqlite3';db=connect(path);migrate.upgrade(db);p=product(db)
    order=c.checkout(db,'local','worker',c.Checkout(product_id=p['id'],quantity=2))
    db.execute('UPDATE commerce_orders SET expires_at=0 WHERE id=?',(order['id'],));db.close()
    @contextmanager
    def session():
        conn=connect(path)
        try: yield conn
        finally: conn.close()
    async def exercise():
        stop=asyncio.Event()
        task=asyncio.create_task(serve(session,stop,interval=.02))
        try:
            async with asyncio.timeout(3):
                while True:
                    with session() as conn:
                        if c.row(conn,'commerce_orders',order['id'],'local')['status']=='cancelled':
                            break
                    await asyncio.sleep(.02)
        finally:
            stop.set();await task
    asyncio.run(exercise())
    with session() as conn:
        after=c.row(conn,'commerce_products',p['id'],'local')
        assert after['stock']==3 and after['reserved']==0
    assert sweep(session)==0
