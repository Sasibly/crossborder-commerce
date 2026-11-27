"""Bulk reads retain snapshot values and bound SELECT count as history grows."""
from xborder_insight import commerce as c
from test_commerce import product


def selects(conn,operation):
    statements=[];conn.set_trace_callback(statements.append)
    try:result=operation()
    finally:conn.set_trace_callback(None)
    return result,[sql for sql in statements if sql.lstrip().upper().startswith('SELECT')]


def test_order_listing_and_summary_queries_do_not_grow_per_order(conn):
    p=product(conn,stock=40)
    def create(index):
        order=c.checkout(conn,'local',str(index),c.Checkout(product_id=p['id'],quantity=1))
        c.pay(conn,'local',order['id'],c.Payment(event_id='batch-'+str(index),amount_cents=3000))
        return order
    original=create(0)
    _,small=selects(conn,lambda:c.summary(conn,'local'))
    for index in range(1,25):create(index)
    orders,listing_queries=selects(conn,lambda:c.listing(conn,'commerce_orders','local'))
    report,large=selects(conn,lambda:c.summary(conn,'local'))
    assert len(orders)==25 and len(listing_queries)==2
    assert len(large)==len(small)==3
    assert report['gross_collected_cents']==25*3000 and report['status_counts']['paid']==25
    assert next(o for o in orders if o['id']==original['id'])['snapshot']==original['snapshot']
    assert all(len(o['items'])==1 and o['items'][0]['unit_price_cents']==3000 for o in orders)
    assert c.listing(conn,'commerce_orders','other')==[]
