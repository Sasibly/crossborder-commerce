import pytest
from xborder_insight import commerce as c, commerce_queries as q
from test_commerce import product


def test_pagination_equal_timestamps_concurrent_inserts_and_tenant_scope(conn):
    p=product(conn,stock=20)
    for i in range(5): c.checkout(conn,'local',str(i),c.Checkout(product_id=p['id'],quantity=1))
    conn.execute('UPDATE commerce_orders SET created_at=100')
    first=q.orders(conn,'local',limit=2,since=100,until=101)
    assert len(first['items'])==2
    c.checkout(conn,'local','late',c.Checkout(product_id=p['id'],quantity=1))
    conn.execute("UPDATE commerce_orders SET created_at=100 WHERE request_key='late'")
    seen=[i['id'] for i in first['items']];cursor=first['next_cursor']
    while cursor:
        page=q.orders(conn,'local',limit=2,since=100,until=101,cursor=cursor)
        seen.extend(i['id'] for i in page['items']);cursor=page['next_cursor']
    assert len(seen)==len(set(seen))==5
    with pytest.raises(c.InputInvalid): q.orders(conn,'other',cursor=first['next_cursor'],since=100,until=101)
    with pytest.raises(c.InputInvalid): q.orders(conn,'local',cursor='broken')
    with pytest.raises(c.InputInvalid): q.orders(conn,'local',since=101,until=100)
    assert q.orders(conn,'local',since=0,until=100)['items']==[]


def test_read_only_invariant_checks_detect_corruption(conn):
    p=product(conn);o=c.checkout(conn,'local','check',c.Checkout(product_id=p['id'],quantity=1))
    assert q.integrity(conn,'local')['ok']
    changes=conn.total_changes
    assert q.integrity(conn,'local')['ok'] and conn.total_changes==changes
    conn.execute('UPDATE commerce_products SET stock=stock+1 WHERE id=?',(p['id'],))
    conn.execute('UPDATE commerce_orders SET amount_cents=amount_cents+1 WHERE id=?',(o['id'],))
    kinds={i['kind'] for i in q.integrity(conn,'local')['issues']}
    assert 'inventory_ledger_mismatch' in kinds and 'order_line_totals_mismatch' in kinds
    assert q.integrity(conn,'other')['issues']==[]


def test_summary_projection_batch_count_and_full_compatibility(conn):
    import json
    p=product(conn,stock=40)
    for index in range(31):c.checkout(conn,'local',str(index),c.Checkout(product_id=p['id'],quantity=1))
    statements=[];conn.set_trace_callback(statements.append)
    full=q.orders(conn,'local',limit=30)
    conn.set_trace_callback(None)
    assert len(statements)==4
    assert full['items'][0]==c.row(conn,'commerce_orders',full['items'][0]['id'],'local')
    summary=q.orders(conn,'local',limit=30,view='summary')
    first=summary['items'][0];original=full['items'][0]
    assert first['id']==original['id'] and first['amount_cents']==original['amount_cents']
    assert first['items'][0]['decision_id']==original['items'][0]['snapshot']['decision_id']
    assert 'snapshot' not in first and 'token' not in first and 'fingerprint' not in first
    assert 'snapshot' not in first['items'][0]
    assert len(json.dumps(summary))<len(json.dumps(full))//2
    with pytest.raises(c.InputInvalid):q.orders(conn,'local',cursor=summary['next_cursor'])
    with pytest.raises(c.InputInvalid):q.orders(conn,'local',view='invalid')


def test_expiry_uses_pending_only_index_and_preserves_stock(conn):
    p=product(conn,stock=40)
    for index in range(30):
        o=c.checkout(conn,'local',str(index),c.Checkout(product_id=p['id'],quantity=1))
        c.transition(conn,'local',o['id'],'cancelled')
    pending=c.checkout(conn,'local','pending',c.Checkout(product_id=p['id'],quantity=1))
    plan=conn.execute("EXPLAIN QUERY PLAN SELECT id FROM commerce_orders WHERE tenant=? AND status='pending' AND expires_at<=?",('local',pending['expires_at'])).fetchall()
    assert any('commerce_orders_status' in row[3] for row in plan)
    assert c.expire(conn,'local',pending['expires_at'])==1
    assert c.row(conn,'commerce_products',p['id'],'local')['stock']==40
    assert q.integrity(conn,'local')['ok']
