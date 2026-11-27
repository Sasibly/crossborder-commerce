from dataclasses import replace
import sqlite3
import pytest
from fastapi.testclient import TestClient

from xborder_insight import api, commerce as c
from xborder_insight.db import migrate
from xborder_insight.db.connection import connect
from xborder_insight.security import keys
from test_commerce import product


@pytest.fixture
def secured(tmp_path,monkeypatch):
    monkeypatch.setenv('COMMERCE_LEGACY_GUEST_CHECKOUT','true')  # legacy endpoint permission tests
    path=tmp_path/'access.sqlite3';db=connect(path);migrate.upgrade(db)
    p=product(db)
    auth={role:{'Authorization':'Bearer '+keys.create(db,tenant_id='local',role=role,rpm_limit=1000)[0]}
          for role in ('owner','operator','viewer')}
    auth['other']={'Authorization':'Bearer '+keys.create(db,tenant_id='other',rpm_limit=1000)[0]}
    db.close()
    monkeypatch.setattr(api,'DB_FILE',path)
    monkeypatch.setattr(api,'settings',replace(api.settings,auth_required=True,jobs_worker_enabled=False))
    with TestClient(api.app) as client:
        yield client,path,p,auth


def test_roles_and_legacy_write_bypass(secured):
    client,path,p,auth=secured
    for role in ('owner','operator','viewer'):
        assert client.get('/v1/commerce/me',headers=auth[role]).json()['role']==role
    assert client.get('/v1/commerce/state',headers=auth['viewer']).status_code==200
    assert client.post(f"/v1/commerce/products/{p['id']}/stock",json={'quantity':1},headers=auth['viewer']).status_code==403
    assert client.post('/v1/jobs',json={'kind':'analyze','dataset':'pet_fountain'},headers=auth['viewer']).status_code==403
    assert client.post(f"/v1/commerce/products/{p['id']}/stock",json={'quantity':1},headers=auth['operator']).status_code==200
    order=client.post('/shop/api/orders',json={'product_id':p['id'],'quantity':1},headers={'Idempotency-Key':'role'}).json()
    oid=order['id']
    assert client.post('/v1/commerce/orders/'+oid+'/pay',json={'event_id':'pay','amount_cents':3000},headers=auth['operator']).status_code==403
    assert client.post('/v1/commerce/orders/'+oid+'/pay',json={'event_id':'pay','amount_cents':3000},headers=auth['owner']).status_code==200
    assert client.post('/v1/commerce/orders/'+oid+'/refund',headers=auth['operator']).status_code==403
    assert client.post('/v1/commerce/orders/'+oid+'/ship',json={'tracking':'demo','actual_logistics_cents':500},headers=auth['operator']).status_code==200
    assert client.post('/v1/commerce/refund-costs/'+oid,json={},headers=auth['operator']).status_code==403


def test_summary_and_order_detail_keep_tenant_and_role_boundaries(secured):
    client,path,p,auth=secured
    order=client.post('/shop/api/orders',json={'product_id':p['id'],'quantity':1},headers={'Idempotency-Key':'summary-detail'}).json()
    oid=order['id']
    response=client.get('/v1/commerce/orders?view=summary',headers=auth['viewer'])
    assert response.status_code==200 and response.json()['items'][0]['id']==oid
    assert 'snapshot' not in response.json()['items'][0]
    assert client.get('/v1/commerce/orders/'+oid,headers=auth['viewer']).json()['snapshot']['decision']['candidate']
    assert client.get('/v1/commerce/orders/'+oid,headers=auth['other']).status_code==404
    assert client.get('/v1/commerce/orders?view=summary',headers=auth['other']).json()['items']==[]
    assert client.get('/v1/commerce/orders?view=invalid',headers=auth['owner']).status_code==422


def test_audit_actor_tenant_immutability_and_rollback(secured):
    client,path,p,auth=secured
    assert client.post(f"/v1/commerce/products/{p['id']}/stock",json={'quantity':1},headers=auth['operator']).status_code==200
    page=client.get('/v1/commerce/audit?limit=2',headers=auth['viewer']).json()
    nextpage=client.get('/v1/commerce/audit?after='+str(page['next_after']),headers=auth['viewer']).json()
    assert all(r['id']>page['next_after'] for r in nextpage['items'])
    last=nextpage['items'][-1]
    assert last['action']=='inventory.receipt' and last['actor'].startswith('xb_')
    assert 'actor_id' not in last
    assert client.get('/v1/commerce/audit',headers=auth['other']).json()['items']==[]
    db=connect(path)
    before=db.execute('SELECT COUNT(*) FROM commerce_audit').fetchone()[0]
    # Inject an audit failure and require stock update to roll back too.
    db.execute("CREATE TRIGGER fail_audit BEFORE INSERT ON commerce_audit BEGIN SELECT RAISE(ABORT,'injected'); END")
    stock=c.row(db,'commerce_products',p['id'],'local')['stock']
    with pytest.raises(sqlite3.IntegrityError):
        c.add_stock(db,'local',p['id'],4)
    assert c.row(db,'commerce_products',p['id'],'local')['stock']==stock
    assert db.execute('SELECT COUNT(*) FROM commerce_audit').fetchone()[0]==before
    db.execute('DROP TRIGGER fail_audit')
    with pytest.raises(sqlite3.IntegrityError):
        db.execute('UPDATE commerce_audit SET action=action')
    with pytest.raises(sqlite3.IntegrityError):
        db.execute('DELETE FROM commerce_audit')
    with pytest.raises(ValueError):
        migrate.downgrade(db,target=19)
    db.close()


def test_summary_incomplete_costs_not_zero(conn):
    p=product(conn)
    order=c.checkout(conn,'local','summary',c.Checkout(product_id=p['id'],quantity=1))
    c.pay(conn,'local',order['id'],c.Payment(event_id='paid',amount_cents=3000))
    c.transition(conn,'local',order['id'],'refunded')
    result=c.summary(conn,'local')
    assert result['gross_collected_cents']==3000 and result['refunded_cents']==3000
    assert result['retained_receipts_cents']==0 and result['complete_contribution_cents'] is None
    assert result['known_contribution_cents']==0 and result['missing_cost_order_count']==1
    assert c.summary(conn,'other')['status_counts']['refunded']==0
