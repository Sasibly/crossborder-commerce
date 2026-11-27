import pytest
from xborder_insight import commerce as c
from test_commerce import product


def test_transaction_fee_allocation_and_policy_snapshot(conn):
    a,b=product(conn),product(conn)
    order=c.checkout_items(conn,'local','fee','fp',[(a['id'],2),(b['id'],1)])
    pricing=order['snapshot']['payment_pricing']
    assert pricing['fee_cents']==300  # 9000 * 3% + 30, once per payment
    assert sum(pricing['allocations'].values())==300
    assert pricing['allocations'][a['id']]==200
    c.save_payment_policy(conn,'local',c.PaymentPolicy(bps=400,fixed_cents=50,expected_version=0))
    assert c.row(conn,'commerce_orders',order['id'],'local')['snapshot']['payment_pricing']==pricing
    assert c.payment_policy(conn,'other')['version']==0
    with pytest.raises(c.IdempotencyConflict):
        c.save_payment_policy(conn,'local',c.PaymentPolicy(bps=0,fixed_cents=0,expected_version=0))
    from xborder_insight.db import migrate
    with pytest.raises(ValueError):
        migrate.downgrade(conn,target=20)
    assert migrate.current_version(conn)==21  # v22 index rolls back; v21 data guard refuses


def test_rounding_allocations_are_stable_and_conserve_cents():
    lines=[{'product_id':s,'unit_price_cents':1,'quantity':1} for s in ['b','a','c']]
    assert c.allocate_fee(lines,2)==[1,1,0]
    assert c.allocate_fee(lines,0)==[0,0,0]


def test_legacy_fee_result_not_rewritten(conn):
    p=product(conn);o=c.checkout(conn,'local','legacy-fee',c.Checkout(product_id=p['id'],quantity=2))
    snapshot=o['snapshot'];snapshot.pop('payment_pricing')
    conn.execute('UPDATE commerce_orders SET snapshot=? WHERE id=?',(c.dump(snapshot),o['id']))
    c.pay(conn,'local',o['id'],c.Payment(event_id='pay',amount_cents=6000))
    c.transition(conn,'local',o['id'],'shipped',c.Shipment(tracking='mock',actual_logistics_cents=1000))
    c.transition(conn,'local',o['id'],'completed')
    assert c.review(conn,'local')[0]['recorded_contribution_cents']==1960
