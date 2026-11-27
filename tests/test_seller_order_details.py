"""Snapshot truth, delivery minimisation and recorded-only order timelines."""
import json

import pytest

from xborder_insight import commerce as c, commerce_order_views as views, commerce_queries as q
from xborder_insight.db.connection import connect
from test_commerce import product
from test_commerce_access import secured


PRIVATE = {'recipient': 'Secret Receiver', 'phone': '+1-555-0109',
           'line1': '141 Private Road', 'line2': 'Suite Private', 'city': 'Private City',
           'state': 'WA', 'postal_code': '98101', 'country': 'US'}


def new_order(conn, product_id, key='order-details'):
    return c.checkout_items(conn, 'local', key, c.fingerprint(key), [(product_id, 2)], address=PRIVATE)


def test_summary_never_contains_full_delivery_and_uses_purchase_snapshot(conn):
    p = product(conn, stock=10)
    order = new_order(conn, p['id'])
    saved = order['snapshot']
    conn.execute('UPDATE commerce_products SET title=?,price_cents=? WHERE id=?', ('Changed current product', 9999, p['id']))
    result = q.orders(conn, 'local', view='summary')['items'][0]
    encoded = json.dumps(result)
    for field in ('recipient', 'phone', 'line1', 'line2', 'city', 'postal_code'):
        assert PRIVATE[field] not in encoded
    assert 'address' not in result
    assert result['recipient_summary'] == {'recipient_masked': 'S**', 'country': 'US', 'state': 'WA'}
    assert result['items'][0]['product_title'] == saved['product_title']
    assert result['items'][0]['unit_price_cents'] == 3000
    assert result['amount_cents'] == 6000
    assert c.row(conn, 'commerce_orders', order['id'], 'local')['snapshot'] == saved


def test_all_seller_read_paths_minimise_delivery_and_enforce_separate_permission(secured):
    client, path, p, auth = secured
    db = connect(path)
    order = new_order(db, p['id'])
    db.close()
    oid = order['id']
    for role in ('owner', 'operator', 'viewer'):
        for endpoint in ('/v1/commerce/state', '/v1/commerce/orders', '/v1/commerce/orders?view=summary', '/v1/commerce/orders/' + oid):
            response = client.get(endpoint, headers=auth[role])
            assert response.status_code == 200, response.text
            for secret in (PRIVATE['recipient'], PRIVATE['phone'], PRIVATE['line1'], PRIVATE['postal_code'], order['token']):
                assert secret not in response.text
        detail = client.get('/v1/commerce/orders/' + oid, headers=auth[role]).json()
        assert detail['display']['can_view_delivery'] == (role != 'viewer')
    endpoint = '/v1/commerce/orders/' + oid + '/delivery'
    for role in ('owner', 'operator'):
        response = client.get(endpoint, headers=auth[role])
        assert response.json()['address'] == PRIVATE
        assert response.json()['source'] == 'order_snapshot'
        assert response.headers['cache-control'] == 'no-store'
    assert client.get(endpoint, headers=auth['viewer']).status_code == 403
    assert client.get(endpoint, headers=auth['other']).status_code == 404
    assert client.get('/v1/commerce/orders/' + oid, headers=auth['other']).status_code == 404
    assert client.get(endpoint).status_code == 401


def test_recorded_timeline_is_atomic_idempotent_and_does_not_log_delivery(conn):
    p = product(conn, stock=10)
    order = new_order(conn, p['id'])
    payment = c.Payment(event_id='SIM-LOCAL-EVENT', amount_cents=6000)
    c.pay(conn, 'local', order['id'], payment)
    c.pay(conn, 'local', order['id'], payment)
    c.transition(conn, 'local', order['id'], 'shipped', c.Shipment(tracking='SIM-TRACK', actual_logistics_cents=0))
    c.transition(conn, 'local', order['id'], 'shipped', c.Shipment(tracking='SIM-TRACK', actual_logistics_cents=0))
    c.transition(conn, 'local', order['id'], 'completed')
    c.transition(conn, 'local', order['id'], 'refunded')
    c.transition(conn, 'local', order['id'], 'refunded')
    result = views.detail(conn, 'local', order['id'], 'owner')
    display = result['display']
    assert [event['kind'] for event in display['timeline']] == ['order.created', 'order.paid', 'order.shipped', 'order.completed', 'order.refunded']
    assert all(event['source'] == 'audit' and event['data_kind'] == 'simulation' for event in display['timeline'])
    assert display['payment']['events'][0]['reference'] == 'SIM-LOCAL-EVENT'
    assert display['fulfilment']['tracking'] == 'SIM-TRACK'
    assert display['amounts']['recorded_logistics_cost_cents'] == 0
    assert display['amounts']['discount_cents'] is None
    assert display['amounts']['tax_cents'] is None
    assert display['amounts']['refunded_cents'] == 6000
    audit = json.dumps([dict(row) for row in conn.execute('SELECT * FROM commerce_audit')])
    assert PRIVATE['recipient'] not in audit and PRIVATE['line1'] not in audit and PRIVATE['phone'] not in audit


def test_legacy_timeline_reads_existing_ledger_without_backfill(conn, monkeypatch):
    p = product(conn)
    with monkeypatch.context() as patch:
        patch.setattr(c, 'record', lambda *args, **kwargs: None)
        order = new_order(conn, p['id'])
        c.pay(conn, 'local', order['id'], c.Payment(event_id='legacy-payment', amount_cents=6000))
    before = conn.total_changes
    display = views.detail(conn, 'local', order['id'], 'viewer')['display']
    assert conn.total_changes == before
    assert [event['source'] for event in display['timeline']] == ['inventory_ledger', 'inventory_ledger']
    assert all(event['actor'] is None for event in display['timeline'])
    assert display['timestamps']['shipped_at'] is None
    assert display['amounts']['recorded_logistics_cost_cents'] is None
    assert display['fulfilment']['carrier'] is None
    assert display['fulfilment']['estimated_delivery_at'] is None


def test_missing_legacy_events_not_guessed_from_current_state(conn, monkeypatch):
    p = product(conn)
    order = new_order(conn, p['id'])
    conn.execute("UPDATE commerce_orders SET status='completed' WHERE id=?", (order['id'],))
    display = views.detail(conn, 'local', order['id'], 'owner')['display']
    assert display['timestamps']['completed_at'] is None
    assert display['payment']['status'] == 'not_recorded'
    assert display['fulfilment']['status'] == 'not_recorded'
    assert len(display['timeline']) == 1


def test_order_audit_failure_rolls_back_payment_stock_and_creation(conn):
    p = product(conn, stock=10)
    conn.execute("CREATE TRIGGER reject_order_audit BEFORE INSERT ON commerce_audit WHEN NEW.action='order.created' BEGIN SELECT RAISE(ABORT,'injected'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        new_order(conn, p['id'])
    assert c.row(conn, 'commerce_products', p['id'], 'local')['stock'] == 10
    assert conn.execute('SELECT COUNT(*) FROM commerce_orders').fetchone()[0] == 0
    conn.execute('DROP TRIGGER reject_order_audit')
    order = new_order(conn, p['id'])
    conn.execute("CREATE TRIGGER reject_paid_audit BEFORE INSERT ON commerce_audit WHEN NEW.action='order.paid' BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):
        c.pay(conn, 'local', order['id'], c.Payment(event_id='failed', amount_cents=6000))
    assert c.row(conn, 'commerce_orders', order['id'], 'local')['status'] == 'pending'
    assert conn.execute("SELECT COUNT(*) FROM commerce_events WHERE id='failed'").fetchone()[0] == 0
    assert q.integrity(conn, 'local')['ok']


@pytest.mark.parametrize('action',['pay','ship','complete','refund','cancel'])
def test_seller_write_responses_minimise_delivery_and_preserve_permissions(secured,action):
    client,path,p,auth=secured
    db=connect(path);order=new_order(db,p['id']);oid=order['id']
    if action not in ('pay','cancel'):
        c.pay(db,'local',oid,c.Payment(event_id='setup-payment',amount_cents=6000))
    if action=='complete':
        c.transition(db,'local',oid,'shipped',c.Shipment(tracking='SIM-TEST',actual_logistics_cents=0))
    db.close()
    endpoint=f'/v1/commerce/orders/{oid}/{action}'
    body={'event_id':'write-response-payment','amount_cents':6000} if action=='pay' else {'tracking':'SIM-TEST','actual_logistics_cents':0} if action=='ship' else {}
    assert client.post(endpoint,json=body,headers=auth['viewer']).status_code==403
    assert client.post(endpoint,json=body,headers=auth['other']).status_code==404
    role='owner' if action in ('pay','refund') else 'operator'
    if role=='owner':assert client.post(endpoint,json=body,headers=auth['operator']).status_code==403
    for _ in range(2):
        response=client.post(endpoint,json=body,headers=auth[role])
        assert response.status_code==200,response.text
        assert response.headers['cache-control']=='no-store'
        result=response.json()
        assert not {'token','request_key','fingerprint','address'} & result.keys()
        assert 'address' not in result['snapshot']
        assert result['amount_cents']==6000 and result['items'][0]['unit_price_cents']==3000
        for private in (PRIVATE['recipient'],PRIVATE['phone'],PRIVATE['line1'],PRIVATE['postal_code'],order['token']):
            assert private not in response.text
    db=connect(path)
    assert c.row(db,'commerce_orders',oid,'local')['snapshot']==order['snapshot']
    db.close()
    assert client.get(f'/v1/commerce/orders/{oid}/delivery',headers=auth[role]).json()['address']==PRIVATE
