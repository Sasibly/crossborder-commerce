"""Isolated database regressions: receipts, expiry, finance and old history."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from xborder_insight import commerce as c, buyers as b, commerce_order_views as views
from xborder_insight.db.connection import connect
from xborder_insight.db import migrate
from xborder_insight.seller_requests import execute
from test_commerce import product, assumptions
from test_commerce_access import secured

def test_stock_receipt_parallel_replay_conflict_and_atomic_failure(tmp_path):
    path=tmp_path/'receipts.db'
    db=connect(path);migrate.upgrade(db);p=product(db,stock=3);db.close()
    def add():
        conn=connect(path)
        try:return execute(conn,'local','stock/'+p['id'],'stable-key',{'quantity':2},lambda:c.add_stock(conn,'local',p['id'],2))
        finally:conn.close()
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda _:add(),range(4)))
    assert all(r==results[0] for r in results)
    db=connect(path)
    assert c.row(db,'commerce_products',p['id'],'local')['stock']==5
    with pytest.raises(c.IdempotencyConflict):execute(db,'local','stock/'+p['id'],'stable-key',{'quantity':4},lambda:None)
    def broken():
        c.add_stock(db,'local',p['id'],7)
        raise RuntimeError('after write')
    with pytest.raises(RuntimeError):execute(db,'local','stock/'+p['id'],'failed-key',{},broken)
    assert c.row(db,'commerce_products',p['id'],'local')['stock']==5
    assert not db.execute("SELECT 1 FROM commerce_seller_requests WHERE request_key='failed-key'").fetchone()
    db.close()

def test_seller_http_receipts_permissions(secured):
    client,path,p,auth=secured
    url='/v1/commerce/products/'+p['id']+'/stock'
    headers=auth['operator']|{'Idempotency-Key':'http-replay'}
    a=client.post(url,json={'quantity':2},headers=headers)
    assert a.status_code==200,a.text
    assert client.post(url,json={'quantity':2},headers=headers).json()==a.json()
    assert client.post(url,json={'quantity':3},headers=headers).status_code==409
    assert client.post(url,json={'quantity':2},headers=auth['viewer']).status_code==403

def test_expiry_releases_once_keeps_unexpired_and_rejects_payment(conn):
    p=product(conn,stock=5)
    old=c.checkout(conn,'local','expired',c.Checkout(product_id=p['id'],quantity=2))
    live=c.checkout(conn,'local','live',c.Checkout(product_id=p['id'],quantity=1))
    conn.execute('UPDATE commerce_orders SET expires_at=0 WHERE id=?',(old['id'],))
    with pytest.raises(c.InvalidStateTransition):c.pay(conn,'local',old['id'],c.Payment(event_id='late',amount_cents=old['amount_cents']))
    assert c.expire(conn,'local')==1
    assert c.expire(conn,'local')==0
    assert c.row(conn,'commerce_orders',live['id'],'local')['status']=='pending'
    assert c.row(conn,'commerce_products',p['id'],'local')['reserved']==1

def test_saved_refund_losses_are_recorded_only_and_immutable(conn):
    p=product(conn);order=c.checkout(conn,'local','refund',c.Checkout(product_id=p['id'],quantity=1))
    c.pay(conn,'local',order['id'],c.Payment(event_id='pay',amount_cents=order['amount_cents']))
    c.transition(conn,'local',order['id'],'refunded')
    body=b.RefundCosts(procurement_loss_cents=10,logistics_loss_cents=20,payment_loss_cents=30,other_loss_cents=0,note='test basis')
    saved=b.settle_refund(conn,'local',order['id'],body)
    assert b.settle_refund(conn,'local',order['id'],body)==saved
    detail=views.detail(conn,'local',order['id'],'owner')
    assert detail['refund_cost_record']['snapshot']['loss_cents']==60
    assert detail['refund_cost_record']['created_at']>0
    with pytest.raises(c.IdempotencyConflict):b.settle_refund(conn,'local',order['id'],body.model_copy(update={'other_loss_cents':1}))
    with pytest.raises(c.NotFound):views.detail(conn,'other',order['id'],'owner')

def test_old_analysis_and_comparison_remain_reachable_by_id(secured):
    from xborder_insight import review_analysis as r, profit_comparisons as pc
    from test_profit_comparisons import comparison_body
    client,path,p,auth=secured
    db=connect(path)
    runs=[r.submit(db,'local',r.AnalysisRequest(dataset='pet_fountain'),f'history-{i}') for i in range(31)]
    # Pin order without running any worker/model, preserving immutable completed rows.
    for i,run in enumerate(runs):db.execute('UPDATE commerce_review_analyses SET created_at=? WHERE id=?',(i+1,run['id']))
    body=comparison_body(db,p['snapshot']['candidate']['id'])
    comparisons=[pc.save(db,'local',body,f'comparison-{i}') for i in range(21)]
    db.close()
    old=runs[0]['id']
    assert old not in [row['id'] for row in client.get('/v1/commerce/review-analyses',headers=auth['owner']).json()]
    assert client.get('/v1/commerce/review-analyses/'+old,headers=auth['viewer']).status_code==200
    assert client.get('/v1/commerce/review-analyses/'+old,headers=auth['other']).status_code==404
    for item in comparisons:
        assert client.get('/v1/commerce/profit-comparisons/'+item['id'],headers=auth['viewer']).status_code==200
        assert client.get('/v1/commerce/profit-comparisons/'+item['id'],headers=auth['other']).status_code==404
