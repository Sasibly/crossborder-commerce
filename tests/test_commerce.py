"""Business invariants of the combined slice, including real file concurrency."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from xborder_insight import api, commerce as c
from xborder_insight.db import migrate
from xborder_insight.db.connection import connect


def assumptions(**overrides):
    values = dict(price_cents=3000,purchase_cny_cents=7000,cny_per_usd='7',logistics_cents=500,
                  payment_bps=300,payment_fixed_cents=30,aftersales_cents=100,acquisition_cents=300,
                  risk='clear',source_note='synthetic demo')
    return c.Assumptions(**(values|overrides))


def product(conn,tenant='local',stock=3):
    candidate = c.create_candidate(conn,tenant,c.Candidate(name='Storage box',dataset='demo',theme_id='theme'),{'evidence':['Loose lid']})
    decision = c.decide(conn,tenant,candidate['id'],assumptions())
    result = c.draft(conn,tenant,decision['id'])
    c.add_stock(conn,tenant,result['id'],stock)
    return c.publish(conn,tenant,result['id'])


def test_math_and_unknown():
    result=c.evaluate(assumptions())
    assert result['unit_profit_cents']==980  # 3000 - 1000 - 120 - 500 - 100 - 300
    assert result['procurement_usd_cents']==1000
    assert c.evaluate(assumptions(logistics_cents=None))['conclusion']=='NEED_MORE_INFO'
    assert c.evaluate(assumptions(risk='unknown'))['conclusion']=='NEED_MORE_INFO'
    assert c.evaluate(assumptions(risk='blocked'))['conclusion']=='NO_GO'
    assert c.evaluate(assumptions(price_cents=100))['conclusion']=='NO_GO'
    with pytest.raises(ValidationError):
        assumptions(cny_per_usd='NaN')
    with pytest.raises(ValidationError):
        assumptions(channel='AMAZON_FBA')


def test_snapshot_and_draft_replay(conn):
    p=product(conn)
    original=p['snapshot']
    decision_id=p['decision_id']
    candidate_id=original['candidate']['id']
    c.decide(conn,'local',candidate_id,assumptions(price_cents=4000))
    assert c.draft(conn,'local',decision_id)['id']==p['id']
    assert c.row(conn,'commerce_decisions',decision_id,'local')['snapshot']==original
    with pytest.raises(c.NotFound):
        c.draft(conn,'other',decision_id)


def test_order_payment_review_and_refund(conn):
    p=product(conn)
    body=c.Checkout(product_id=p['id'],quantity=2)
    order=c.checkout(conn,'local','same-key',body)
    assert c.checkout(conn,'local','same-key',body)['id']==order['id']
    with pytest.raises(c.IdempotencyConflict):
        c.checkout(conn,'local','same-key',c.Checkout(product_id=p['id'],quantity=1))
    with pytest.raises(c.InputInvalid):
        c.pay(conn,'local',order['id'],c.Payment(event_id='bad',amount_cents=1))
    event=c.Payment(event_id='success',amount_cents=6000)
    c.pay(conn,'local',order['id'],event)
    c.pay(conn,'local',order['id'],event)
    assert c.row(conn,'commerce_products',p['id'],'local')['reserved']==0
    c.transition(conn,'local',order['id'],'shipped',c.Shipment(tracking='demo',actual_logistics_cents=1200))
    c.transition(conn,'local',order['id'],'completed')
    review=c.review(conn,'local')[0]
    assert review['predicted_profit_cents']==1960
    assert review['recorded_contribution_cents']==1790
    assert review['difference_cents']==-170  # per-order fixed fee saves 30 cents
    c.transition(conn,'local',order['id'],'refunded')
    assert c.row(conn,'commerce_products',p['id'],'local')['stock']==1
    assert c.review(conn,'local')[0]['recorded_contribution_cents'] is None


def test_cancel_expire_and_unshipped_refund(conn):
    p=product(conn)
    body=c.Checkout(product_id=p['id'],quantity=1)
    order=c.checkout(conn,'local','expire',body)
    assert c.expire(conn,'local',order['expires_at'])==1
    assert c.expire(conn,'local',order['expires_at'])==0
    with pytest.raises(c.InvalidStateTransition):
        c.pay(conn,'local',order['id'],c.Payment(event_id='late',amount_cents=3000))
    order=c.checkout(conn,'local','refund',body)
    c.pay(conn,'local',order['id'],c.Payment(event_id='paid',amount_cents=3000))
    c.transition(conn,'local',order['id'],'refunded')
    c.transition(conn,'local',order['id'],'refunded')
    assert c.row(conn,'commerce_products',p['id'],'local')['stock']==3
    assert c.row(conn,'commerce_products',p['id'],'local')['reserved']==0


def test_concurrent_last_items(tmp_path):
    path=tmp_path/'concurrent.sqlite3'
    db=connect(path);migrate.upgrade(db);p=product(db,stock=3);db.close()
    def attempt(i):
        db=connect(path)
        try:
            c.checkout(db,'local',str(i),c.Checkout(product_id=p['id'],quantity=1))
            return True
        except c.InvalidStateTransition:
            return False
        finally:
            db.close()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results=list(pool.map(attempt,range(12)))
    assert sum(results)==3
    db=connect(path)
    after=c.row(db,'commerce_products',p['id'],'local')
    assert after['stock']==0 and after['reserved']==3
    assert db.execute("SELECT SUM(stock_delta) FROM commerce_ledger WHERE product_id=?",(p['id'],)).fetchone()[0]==0
    db.close()


def test_http_full_chain_and_buyer_privacy(monkeypatch,tmp_path):
    monkeypatch.setenv("COMMERCE_LEGACY_GUEST_CHECKOUT","true")  # explicit compatibility coverage
    path=tmp_path/'http.sqlite3';db=connect(path);migrate.upgrade(db);db.close()
    monkeypatch.setattr(api,'DB_FILE',path)
    with TestClient(api.app) as client:
        report=client.get('/v1/commerce/evidence/pet_fountain').json()
        assert report['themes']
        candidate=client.post('/v1/commerce/candidates',json={'name':'Quiet fountain','dataset':'pet_fountain','theme_id':report['themes'][0]['theme_id'],'evidence_fingerprint':report['evidence_fingerprint']}).json()
        response=client.post(f"/v1/commerce/candidates/{candidate['id']}/decisions",json=assumptions().model_dump(mode='json'))
        assert response.status_code==200,response.text
        decision=response.json()
        p=client.post(f"/v1/commerce/decisions/{decision['id']}/draft").json()
        client.post(f"/v1/commerce/products/{p['id']}/stock",json={'quantity':2})
        client.post(f"/v1/commerce/products/{p['id']}/publish")
        catalog=client.get('/shop/api/products').json()
        assert 'snapshot' not in catalog[0] and 'decision_id' not in catalog[0]
        order=client.post('/shop/api/orders',headers={'Idempotency-Key':'browser'},json={'product_id':p['id'],'quantity':1}).json()
        assert 'snapshot' not in order
        assert client.get('/shop/api/orders/'+order['id']).status_code==404
        assert client.get('/shop/api/orders/'+order['id'],headers={'Authorization':'Bearer '+order['token']}).status_code==200
        assert client.post(f"/v1/commerce/orders/{order['id']}/pay",json={'event_id':'http-pay','amount_cents':3000}).status_code==200
        assert client.post(f"/v1/commerce/orders/{order['id']}/ship",json={'tracking':'DEMO','actual_logistics_cents':550}).status_code==200
        assert client.post(f"/v1/commerce/orders/{order['id']}/complete").status_code==200
        assert client.get('/v1/commerce/review').json()[0]['difference_cents']==-50
        assert client.get('/workbench').status_code==200
        assert client.get('/shop').status_code==200


def test_commerce_roundtrip(empty_conn):
    assert migrate.roundtrip(empty_conn)['ok']


def test_authentication_and_tenant_isolation(monkeypatch,tmp_path):
    from dataclasses import replace
    from xborder_insight.security import keys
    path=tmp_path/'auth.sqlite3';db=connect(path);migrate.upgrade(db)
    p=product(db,tenant='owner')
    owner,_=keys.create(db,tenant_id='owner',rpm_limit=100)
    other,_=keys.create(db,tenant_id='other',rpm_limit=100)
    db.close()
    monkeypatch.setattr(api,'DB_FILE',path)
    monkeypatch.setattr(api,'settings',replace(api.settings,auth_required=True,jobs_worker_enabled=False))
    with TestClient(api.app) as client:
        assert client.get('/v1/commerce/state').status_code==401
        assert client.get('/v1/commerce/state',headers={'Authorization':'Bearer '+owner}).json()['products'][0]['id']==p['id']
        assert client.get('/v1/commerce/state',headers={'Authorization':'Bearer '+other}).json()['products']==[]
        assert client.post(f"/v1/commerce/products/{p['id']}/stock",headers={'Authorization':'Bearer '+other},json={'quantity':1}).status_code==404
        assert client.get('/shop/api/products').json()==[]  # public shop is tenant local


def test_payment_conflicts_and_shipment_rollback(conn):
    p=product(conn)
    order=c.checkout(conn,'local','pay',c.Checkout(product_id=p['id'],quantity=1))
    with pytest.raises(c.InvalidStateTransition):
        c.transition(conn,'local',order['id'],'shipped',c.Shipment(tracking='bad',actual_logistics_cents=1))
    assert c.row(conn,'commerce_orders',order['id'],'local')['status']=='pending'
    event=c.Payment(event_id='event',amount_cents=3000)
    c.pay(conn,'local',order['id'],event)
    with pytest.raises(c.IdempotencyConflict):
        c.pay(conn,'local',order['id'],c.Payment(event_id='event',amount_cents=1))
    with pytest.raises(c.InputInvalid):
        c.transition(conn,'local',order['id'],'shipped')
    assert c.row(conn,'commerce_orders',order['id'],'local')['status']=='paid'
    assert conn.execute("SELECT COUNT(*) FROM commerce_ledger WHERE order_id=? AND action='shipped'",(order['id'],)).fetchone()[0]==0
