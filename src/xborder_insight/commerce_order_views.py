"""Read-only seller projections. Frozen order lines are the only product source.

Delivery is deliberately separate from every seller order/state projection.
Timeline fallbacks read existing ledger records; they never backfill history.
"""
from copy import deepcopy
import json

from . import commerce as c
from .security.roles import Forbidden


def recipient_summary(address):
    if not address:
        return None
    name = address.get('recipient') or ''
    return {'recipient_masked': name[:1] + '**' if name else None,
            'country': address.get('country'), 'state': address.get('state')}


def seller_order(order):
    result = deepcopy(order)
    result['recipient_summary'] = recipient_summary(result.get('snapshot', {}).get('address'))
    result.pop('address', None)
    if 'snapshot' in result:
        result['snapshot'].pop('address', None)
    # A guest order token is a bearer credential, not seller display data.
    for key in ('token', 'request_key', 'fingerprint'):
        result.pop(key, None)
    result['currency'] = result.get('snapshot', {}).get('currency') or 'USD'
    result['data_kind'] = 'simulation'
    return result


def delivery(conn, tenant, identity, role):
    # Check ownership before permission so a cross-tenant ID stays a 404.
    order = c.row(conn, 'commerce_orders', identity, tenant)
    if role not in ('owner', 'operator'):
        raise Forbidden('完整收货信息仅供 owner/operator 查看')
    return {'order_id': identity, 'address': order['snapshot'].get('address'),
            'source': 'order_snapshot', 'data_kind': 'simulation'}


def detail(conn, tenant, identity, role):
    with c.read_snapshot(conn):
        order = c.row(conn, 'commerce_orders', identity, tenant)
        result = seller_order(order)
        audit = [dict(row) for row in conn.execute(
            "SELECT id,action,actor_display,created_at FROM commerce_audit WHERE tenant=? AND object_id=? AND action LIKE 'order.%' ORDER BY created_at,id",
            (tenant, identity))]
        ledger = {row['action']: row['at'] for row in conn.execute(
            'SELECT action,MIN(created_at) AS at FROM commerce_ledger WHERE tenant=? AND order_id=? GROUP BY action',
            (tenant, identity))}
        timeline = []
        stages = [('created', 'reserve'), ('paid', 'paid'), ('shipped', 'shipped'),
                  ('completed', 'completed'), ('cancelled', 'cancelled'), ('refunded', 'refunded')]
        times = {}
        for stage, ledger_action in stages:
            action = 'order.' + stage
            event = next((row for row in audit if row['action'] == action), None)
            at = event['created_at'] if event else ledger.get(ledger_action)
            if stage == 'created' and at is None:
                at = order['created_at']
            times[stage + '_at'] = at
            if at is not None:
                timeline.append({'kind': action, 'at': at,
                                 'actor': event['actor_display'] if event else None,
                                 'source': 'audit' if event else ('order_record' if stage == 'created' and ledger_action not in ledger else 'inventory_ledger'),
                                 'data_kind': 'simulation'})
        refunds = [dict(row) for row in conn.execute(
            'SELECT id,status,reason,review_note,created_at,reviewed_at FROM commerce_refunds WHERE tenant=? AND order_id=? ORDER BY created_at,id',
            (tenant, identity))]
        for refund in refunds:
            for action, timestamp in [('requested', refund['created_at']), (refund['status'], refund['reviewed_at'])]:
                if timestamp is None:
                    continue
                # The refund row proves an application/review; execution remains
                # the independent order.refunded event above.
                timeline.append({'kind': 'refund.' + action, 'at': timestamp, 'actor': None,
                                 'source': 'refund_record', 'data_kind': 'simulation'})
        rank = {'order.created': 0, 'order.paid': 1, 'refund.requested': 2,
                'refund.rejected': 3, 'order.shipped': 4, 'order.completed': 5,
                'refund.approved': 6, 'order.cancelled': 7, 'order.refunded': 8}
        timeline.sort(key=lambda event: (event['at'], rank.get(event['kind'], 9)))
        payments = [dict(row) for row in conn.execute(
            'SELECT id AS reference,kind,created_at FROM commerce_events WHERE tenant=? AND order_id=? ORDER BY created_at,id',
            (tenant, identity))]
        pricing = order['snapshot'].get('payment_pricing') or {}
        subtotal = sum(item['unit_price_cents'] * item['quantity'] for item in order['items'])
        decisions = [item['snapshot'].get('decision', {}) for item in order['items']]
        cost=conn.execute('SELECT snapshot,created_at FROM commerce_refund_costs WHERE order_id=?',(identity,)).fetchone()
        result['refund_cost_record'] = {'snapshot':json.loads(cost['snapshot']),'created_at':cost['created_at']} if cost else None
        result['display'] = {
            'source': 'immutable_order_snapshot', 'can_view_delivery': role in ('owner', 'operator'),
            'amounts': {'items_subtotal_cents': subtotal, 'order_total_cents': order['amount_cents'],
                        'discount_cents': None, 'buyer_shipping_cents': None, 'tax_cents': None,
                        'shipping_included': bool(decisions) and all(d.get('shipping_policy') == 'seller-paid shipping included in price' for d in decisions),
                        'tax_policy': 'not_collected_in_demo',
                        'recorded_payment_fee_cents': pricing.get('fee_cents'),
                        'recorded_logistics_cost_cents': order['actual_logistics_cents'],
                        'refunded_cents': order['amount_cents'] if order['status'] == 'refunded' else None},
            'payment': {'status': 'simulated_refunded' if order['status'] == 'refunded' else ('simulated_paid' if payments else ('unpaid' if order['status'] in ('pending', 'cancelled') else 'not_recorded')),
                        'events': payments, 'execution_kind': 'simulation'},
            'fulfilment': {'status': 'simulated_completed' if times['completed_at'] is not None else ('simulated_shipped' if times['shipped_at'] is not None else ('not_shipped' if order['status'] in ('pending', 'paid', 'cancelled') else 'not_recorded')),
                            'tracking': order['tracking'], 'execution_kind': 'simulation',
                            'carrier': None, 'estimated_delivery_at': None, 'signed_by': None},
            'timestamps': times | {'last_recorded_at': max([order['created_at']] + [event['at'] for event in timeline])},
            'timeline': timeline, 'refunds': refunds,
            'timeline_note': '仅显示已记录的事件；旧订单可来自库存流水，未补造执行者或时间。同秒事件仅按业务阶段展示。'
        }
        return result
