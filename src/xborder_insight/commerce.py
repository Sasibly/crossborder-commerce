"""Single-shop demo commerce. Integer cents, immutable snapshots, explicit transactions.

All payment/fulfilment outcomes are simulated. No real tax determination or funds.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from contextlib import contextmanager
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .db.connection import transaction
from .errors import AppError, IdempotencyConflict, InvalidStateTransition, InputInvalid
from .commerce_audit import record


class NotFound(AppError):
    code = 'commerce_not_found'
    status_code = 404


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Candidate(Model):
    name: str = Field(min_length=1, max_length=160)
    dataset: str = Field(min_length=1, max_length=80)
    theme_id: str = Field(min_length=1, max_length=120)
    evidence_fingerprint: str | None = Field(default=None,pattern=r'^[a-f0-9]{64}$')
    analysis_id: str | None = Field(default=None,pattern=r'^[a-f0-9]{32}$')


class Replacement(Model):
    decision_id: str = Field(min_length=1,max_length=64)


class Assumptions(Model):
    market: Literal['US'] = 'US'
    channel: Literal['INDEPENDENT_STORE'] = 'INDEPENDENT_STORE'
    price_cents: int = Field(gt=0, le=100_000_000, strict=True)
    purchase_cny_cents: int | None = Field(default=None, ge=0, le=100_000_000, strict=True)
    cny_per_usd: Decimal | None = Field(default=None, ge=Decimal('0.0001'), le=100, max_digits=8, decimal_places=4)
    logistics_cents: int | None = Field(default=None, ge=0, le=100_000_000, strict=True)
    payment_bps: int | None = Field(default=None, ge=0, le=10000, strict=True)
    payment_fixed_cents: int | None = Field(default=None, ge=0, le=100_000, strict=True)
    aftersales_cents: int | None = Field(default=None, ge=0, le=100_000_000, strict=True)
    acquisition_cents: int | None = Field(default=None, ge=0, le=100_000_000, strict=True)
    risk: Literal['unknown','blocked','clear'] = 'unknown'
    source_note: str = Field(min_length=1, max_length=1000)
    returns_metric_id: str | None = 'nrf-us-online-returns-2025-v1'
    supplier_quote_id: str | None = None
    aftersales_scenario_id: str | None = None
    comparison_id: str | None = None
    comparison_option: str | None = None


class Stock(Model):
    quantity: int = Field(gt=0, le=100_000, strict=True)


class Checkout(Model):
    product_id: str
    quantity: int = Field(gt=0, le=20, strict=True)
    country: Literal['US'] = 'US'


class Payment(Model):
    event_id: str = Field(min_length=1, max_length=120)
    amount_cents: int = Field(gt=0, strict=True)
    currency: Literal['USD'] = 'USD'


class Shipment(Model):
    tracking: str = Field(min_length=1, max_length=120)
    actual_logistics_cents: int = Field(ge=0, le=100_000_000, strict=True)


class PaymentPolicy(Model):
    bps: int = Field(ge=0,le=10000,strict=True)
    fixed_cents: int = Field(ge=0,le=100_000,strict=True)
    expected_version: int = Field(ge=0,strict=True)


def payment_policy(conn,tenant):
    row=conn.execute('SELECT bps,fixed_cents,version FROM commerce_payment_policy WHERE tenant=?',(tenant,)).fetchone()
    return dict(row) if row else {'bps':300,'fixed_cents':30,'version':0}


def save_payment_policy(conn,tenant,body):
    with transaction(conn):
        old=payment_policy(conn,tenant)
        if body.expected_version!=old['version']:
            raise IdempotencyConflict('费用配置已变更，请刷新后重试')
        conn.execute('INSERT INTO commerce_payment_policy VALUES(?,?,?,?) ON CONFLICT(tenant) DO UPDATE SET bps=excluded.bps,fixed_cents=excluded.fixed_cents,version=excluded.version',
                     (tenant,body.bps,body.fixed_cents,old['version']+1))
        record(conn,tenant,'payment_policy.updated',tenant,{'version':old['version']+1})
    return payment_policy(conn,tenant)


def allocate_fee(lines,total):
    """Largest remainder allocation: exact integer sum and stable product-id tie-break."""
    gross=[line['unit_price_cents']*line['quantity'] for line in lines]
    denominator=sum(gross)
    amounts=[total*value//denominator for value in gross]
    ranked=sorted(range(len(lines)),key=lambda i:(-(total*gross[i]%denominator),lines[i]['product_id']))
    for i in ranked[:total-sum(amounts)]:
        amounts[i]+=1
    return amounts


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',',':'))


def fingerprint(value):
    return hashlib.sha256(dump(value).encode()).hexdigest()


def cents(value):
    return int(Decimal(value).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def evaluate(a: Assumptions):
    snapshot = a.model_dump(mode='json')
    missing = [key for key,value in snapshot.items() if value is None and key not in ('returns_metric_id','supplier_quote_id','aftersales_scenario_id','comparison_id','comparison_option')]
    profit = None
    procurement = None
    fee = None
    if not missing:
        procurement = cents(Decimal(a.purchase_cny_cents) / a.cny_per_usd)
        fee = cents(Decimal(a.price_cents) * a.payment_bps / 10000) + a.payment_fixed_cents
        profit = a.price_cents - procurement - fee - a.logistics_cents - a.aftersales_cents - a.acquisition_cents
    # GO is a demo gate, not a legal or market-demand conclusion.
    conclusion = 'NEED_MORE_INFO'
    if a.risk == 'blocked' or (profit is not None and profit <= 0):
        conclusion = 'NO_GO'
    elif not missing and a.risk == 'clear':
        conclusion = 'GO'
    return {'assumptions':snapshot, 'missing':missing, 'conclusion':conclusion,
            'procurement_usd_cents':procurement, 'payment_fee_cents':fee,
            'unit_profit_cents':profit, 'rule_version':'store-demo-v1',
            'data_kind':'simulation', 'tax_policy':'not collected in demo; not a tax determination',
            'shipping_policy':'seller-paid shipping included in price'}


def row(conn, table, identity, tenant):
    # table names are internal constants, never request input.
    found = conn.execute(f'SELECT * FROM {table} WHERE id=? AND tenant=?', (identity,tenant)).fetchone()
    if found is None:
        raise NotFound('记录不存在')
    result = dict(found)
    for key in ('snapshot','source_json'):
        if key in result:
            result[key] = json.loads(result[key])
    if table == 'commerce_orders':
        result['items'] = [dict(item) | {'snapshot':json.loads(item['snapshot'])} for item in
                           conn.execute('SELECT * FROM commerce_order_items WHERE order_id=? ORDER BY product_id',(identity,))]
    return result


def listing(conn, table, tenant):
    with read_snapshot(conn):
        results=[]
        for found in conn.execute(f'SELECT * FROM {table} WHERE tenant=? ORDER BY created_at DESC,id',(tenant,)):
            result=dict(found)
            for key in ('snapshot','source_json'):
                if key in result:result[key]=json.loads(result[key])
            results.append(result)
        if table=='commerce_orders':
            orders={order['id']:order for order in results}
            for order in results:order['items']=[]
            for item in conn.execute('SELECT i.* FROM commerce_order_items i JOIN commerce_orders o ON o.id=i.order_id WHERE o.tenant=? ORDER BY i.order_id,i.product_id',(tenant,)):
                value=dict(item);value['snapshot']=json.loads(value['snapshot'])
                orders[value['order_id']]['items'].append(value)
        return results


def create_candidate(conn, tenant, body: Candidate, source):
    identity = uuid4().hex
    with transaction(conn):
        conn.execute('INSERT INTO commerce_candidates VALUES(?,?,?,?,?)',
                     (identity,tenant,body.name,dump(source),int(time.time())))
        record(conn,tenant,'candidate.created',identity)
    return row(conn,'commerce_candidates',identity,tenant)


def decide(conn, tenant, candidate_id, body: Assumptions):
    with transaction(conn):
        candidate = row(conn,'commerce_candidates',candidate_id,tenant)
        snapshot = evaluate(body)
        from . import business_metrics, supplier_simulation
        snapshot['data_provenance']={'supplier':'simulation','transaction_execution':'simulation',
                                     'cost_inputs':'simulation_assumptions','aftersales_cents':'explicit_scenario_assumption'}
        if body.returns_metric_id:
            snapshot['returns_metric_reference']=business_metrics.get(body.returns_metric_id)
            snapshot['returns_metric_application']='reference_only; does not overwrite aftersales_cents or SKU return probability'
        if body.aftersales_scenario_id:
            from .metric_scenarios import cost_snapshot
            snapshot['aftersales_scenario']=cost_snapshot(conn,tenant,body.aftersales_scenario_id,candidate_id,body.aftersales_cents)
            snapshot['data_provenance']['aftersales_cents']='scenario_estimate_from_simulated_item_probability'
        if body.supplier_quote_id:
            quote=supplier_simulation.quote_snapshot(conn,tenant,body.supplier_quote_id,candidate_id)
            if quote['quote']['purchase_cny_cents']!=body.purchase_cny_cents:
                raise InputInvalid('采用模拟报价时，采购成本须与该报价一致')
            snapshot['supplier_quote']=quote
        if bool(body.comparison_id)!=bool(body.comparison_option):
            raise InputInvalid('比较记录与方案标识须同时填写或同时清除')
        if body.comparison_id:
            from .profit_comparisons import decision_reference
            snapshot['comparison_reference']=decision_reference(conn,tenant,candidate_id,body)
            snapshot['data_provenance']['cost_inputs']='explicitly_selected_simulated_comparison'
        snapshot['candidate'] = candidate
        identity = uuid4().hex
        conn.execute('INSERT INTO commerce_decisions VALUES(?,?,?,?,?)',
                     (identity,tenant,candidate_id,dump(snapshot),int(time.time())))
        record(conn,tenant,'decision.created',identity,{'conclusion':snapshot['conclusion']})
    return row(conn,'commerce_decisions',identity,tenant)


def draft(conn, tenant, decision_id):
    with transaction(conn):
        decision = row(conn,'commerce_decisions',decision_id,tenant)
        snapshot = decision['snapshot']
        if snapshot['conclusion'] != 'GO':
            raise InvalidStateTransition('仅独立站 GO 决策可生成草稿')
        previous = conn.execute('SELECT id FROM commerce_products WHERE decision_id=? AND tenant=?',
                                (decision_id,tenant)).fetchone()
        if previous:
            return row(conn,'commerce_products',previous['id'],tenant)
        identity = uuid4().hex
        conn.execute('INSERT INTO commerce_products(id,tenant,decision_id,title,price_cents,snapshot,created_at) VALUES(?,?,?,?,?,?,?)',
                     (identity,tenant,decision_id,snapshot['candidate']['name'],snapshot['assumptions']['price_cents'],dump(snapshot),int(time.time())))
        record(conn,tenant,'product.drafted',identity,{'decision_id':decision_id})
    return row(conn,'commerce_products',identity,tenant)


def ledger(conn, tenant, product_id, order_id, action, stock, reserved):
    conn.execute('INSERT INTO commerce_ledger(tenant,product_id,order_id,action,stock_delta,reserved_delta,created_at) VALUES(?,?,?,?,?,?,?)',
                 (tenant,product_id,order_id,action,stock,reserved,int(time.time())))
    record(conn,tenant,'inventory.'+action,order_id or product_id,
           {'product_id':product_id,'stock_delta':stock,'reserved_delta':reserved})


def add_stock(conn, tenant, product_id, quantity):
    with transaction(conn):
        row(conn,'commerce_products',product_id,tenant)
        conn.execute('UPDATE commerce_products SET stock=stock+? WHERE id=? AND tenant=?',(quantity,product_id,tenant))
        ledger(conn,tenant,product_id,None,'receipt',quantity,0)
    return row(conn,'commerce_products',product_id,tenant)


def publish(conn, tenant, product_id):
    with transaction(conn):
        product = row(conn,'commerce_products',product_id,tenant)
        if product['stock'] <= 0:
            raise InvalidStateTransition('请先入库再上架')
        conn.execute("UPDATE commerce_products SET status='published' WHERE id=? AND tenant=?",(product_id,tenant))
        if product['status']!='published':
            record(conn,tenant,'product.published',product_id)
    return row(conn,'commerce_products',product_id,tenant)


def unpublish(conn,tenant,product_id):
    with transaction(conn):
        product=row(conn,'commerce_products',product_id,tenant)
        if product['status']=='published':
            conn.execute("UPDATE commerce_products SET status='draft' WHERE id=? AND tenant=?",(product_id,tenant))
            record(conn,tenant,'product.unpublished',product_id)
    return row(conn,'commerce_products',product_id,tenant)


def replace_product(conn,tenant,product_id,decision_id):
    """Explicitly replace a listing; transfer only available stock, never old snapshots."""
    with transaction(conn):
        old=row(conn,'commerce_products',product_id,tenant)
        decision=row(conn,'commerce_decisions',decision_id,tenant)
        if old['snapshot']['candidate']['id']!=decision['candidate_id']:
            raise InputInvalid('替换决策必须属于同一候选商品')
        if decision_id==old['decision_id']:
            raise InputInvalid('请选择不同的新决策版本')
        new=draft(conn,tenant,decision_id)
        if old['status']=='draft' and old['stock']==0 and new['status']=='published':
            # Only an exact recorded replacement is a replay, not an unrelated published SKU.
            event=conn.execute("SELECT 1 FROM commerce_audit WHERE tenant=? AND action='product.replaced' AND object_id=? AND json_extract(detail,'$.new_product_id')=?",(tenant,product_id,new['id'])).fetchone()
            if event:return new
        if old['status']!='published' or old['reserved'] or old['stock']<=0:
            raise InvalidStateTransition('仅可替换有可售库存、无待支付预留的已上架商品；请先处理待支付订单')
        if new['status']!='draft' or new['stock'] or new['reserved']:
            raise InvalidStateTransition('新版本须为尚未入库的草稿，避免合并不同库存')
        quantity=old['stock']
        unpublish(conn,tenant,product_id)
        conn.execute('UPDATE commerce_products SET stock=0 WHERE id=?',(product_id,))
        ledger(conn,tenant,product_id,None,'replacement_out',-quantity,0)
        add_stock(conn,tenant,new['id'],quantity)
        publish(conn,tenant,new['id'])
        record(conn,tenant,'product.replaced',product_id,{'new_product_id':new['id'],'quantity':quantity})
    return row(conn,'commerce_products',new['id'],tenant)


def expire(conn, tenant, now=None):
    now = int(time.time()) if now is None else now
    with transaction(conn):
        orders = conn.execute("SELECT id FROM commerce_orders WHERE tenant=? AND status='pending' AND expires_at<=?",(tenant,now)).fetchall()
        for order in orders:
            transition(conn,tenant,order['id'],'cancelled')
    return len(orders)


def validate_key(key):
    if not key or len(key)>120:
        raise InputInvalid('需要长度 1–120 的 Idempotency-Key')


def checkout(conn, tenant, key, body: Checkout):
    validate_key(key)
    fp = fingerprint(body.model_dump())
    return checkout_items(conn,tenant,key,fp,[(body.product_id,body.quantity)])


def checkout_items(conn,tenant,key,fp,items,*,buyer_id=None,address=None):
    """All line reservations, order creation and cart clearing share one transaction."""
    if not items or len(items)>20 or len({p for p,q in items})!=len(items):
        raise InputInvalid('订单需要 1–20 种不同商品')
    with transaction(conn):
        expire(conn,tenant)
        previous = conn.execute('SELECT * FROM commerce_orders WHERE tenant=? AND request_key=?',(tenant,key)).fetchone()
        if previous:
            if previous['fingerprint'] != fp:
                raise IdempotencyConflict('幂等键已用于不同的下单参数')
            return row(conn,'commerce_orders',previous['id'],tenant)
        lines=[]
        for product_id,quantity in sorted(items):
            if type(quantity) is not int or not 1<=quantity<=20:
                raise InputInvalid('商品数量必须为 1–20 的整数')
            product=row(conn,'commerce_products',product_id,tenant)
            changed=conn.execute("UPDATE commerce_products SET stock=stock-?,reserved=reserved+? WHERE id=? AND tenant=? AND status='published' AND stock>=?",
                                 (quantity,quantity,product_id,tenant,quantity)).rowcount
            if not changed:
                raise InvalidStateTransition('商品未上架或库存不足，整单未创建')
            lines.append({'product_id':product_id,'quantity':quantity,'unit_price_cents':product['price_cents'],
                          'snapshot':{'product_title':product['title'],'decision_id':product['decision_id'],
                                      'unit_price_cents':product['price_cents'],'decision':product['snapshot']}})
        identity = uuid4().hex
        now = int(time.time())
        # v18 representative fields retained for old clients; items is authoritative.
        snapshot=lines[0]['snapshot'] | {'country':'US','currency':'USD','data_kind':'simulation',
                   'address':address,'line_count':len(lines)}
        policy=payment_policy(conn,tenant)
        fee=cents(Decimal(sum(i['quantity']*i['unit_price_cents'] for i in lines))*policy['bps']/10000)+policy['fixed_cents']
        snapshot['payment_pricing']={'rule':'per-transaction-v1','policy':policy,'fee_cents':fee,
                                     'allocations':dict(zip([i['product_id'] for i in lines],allocate_fee(lines,fee)))}
        conn.execute('INSERT INTO commerce_orders(id,tenant,product_id,token,request_key,fingerprint,quantity,amount_cents,status,snapshot,created_at,expires_at,buyer_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                     (identity,tenant,lines[0]['product_id'],secrets.token_urlsafe(32),key,fp,sum(q for p,q in items),
                      sum(item['quantity']*item['unit_price_cents'] for item in lines),'pending',dump(snapshot),now,now+900,buyer_id))
        for item in lines:
            conn.execute('INSERT INTO commerce_order_items VALUES(?,?,?,?,?)',
                         (identity,item['product_id'],item['quantity'],item['unit_price_cents'],dump(item['snapshot'])))
            ledger(conn,tenant,item['product_id'],identity,'reserve',-item['quantity'],item['quantity'])
        record(conn,tenant,'order.created',identity,{'execution_kind':'simulation'})
    return row(conn,'commerce_orders',identity,tenant)


def transition(conn, tenant, order_id, target, shipment=None):
    allowed = {'pending':{'cancelled','paid'}, 'paid':{'shipped','refunded'},
               'shipped':{'completed','refunded'}, 'completed':{'refunded'}}
    with transaction(conn):
        order = row(conn,'commerce_orders',order_id,tenant)
        if order['status'] == target:
            return order
        if target not in allowed.get(order['status'],set()):
            raise InvalidStateTransition(f"不允许 {order['status']} → {target}")
        if target == 'paid' and order['expires_at'] <= int(time.time()):
            raise InvalidStateTransition('订单已超时，请执行超时清理')
        if target=='shipped' and conn.execute("SELECT 1 FROM commerce_refunds WHERE order_id=? AND status='requested'",(order_id,)).fetchone():
            raise InvalidStateTransition('退款申请审核中，请先处理退款申请再发货')
        for item in order['items']:
            stock, reserved = 0, 0
            if order['status'] == 'pending':
                reserved = -item['quantity']
                if target == 'cancelled':
                    stock = item['quantity']
            if order['status'] == 'paid' and target == 'refunded':
                stock = item['quantity']
            if stock or reserved:
                conn.execute('UPDATE commerce_products SET stock=stock+?,reserved=reserved+? WHERE id=? AND tenant=?',
                             (stock,reserved,item['product_id'],tenant))
            ledger(conn,tenant,item['product_id'],order_id,target,stock,reserved)
        if target == 'shipped':
            if shipment is None:
                raise InputInvalid('需要物流单号和实际物流成本')
            conn.execute('UPDATE commerce_orders SET tracking=?,actual_logistics_cents=? WHERE id=? AND tenant=?',
                         (shipment.tracking,shipment.actual_logistics_cents,order_id,tenant))
        conn.execute('UPDATE commerce_orders SET status=? WHERE id=? AND tenant=?',(target,order_id,tenant))
        if target != 'refunded':
            record(conn,tenant,'order.'+target,order_id,{'previous_order_status':order['status'],'execution_kind':'simulation'})
        if target == 'refunded':
            record(conn,tenant,'order.refunded',order_id,{'previous_order_status':order['status'],'execution_kind':'simulation'})
            conn.execute("UPDATE commerce_refunds SET status='approved',review_note='卖家已执行整单退款',reviewed_at=? WHERE order_id=? AND status='requested'",(int(time.time()),order_id))
    return row(conn,'commerce_orders',order_id,tenant)


def pay(conn, tenant, order_id, event: Payment):
    fp = fingerprint({'order_id':order_id, **event.model_dump()})
    with transaction(conn):
        order = row(conn,'commerce_orders',order_id,tenant)
        old = conn.execute('SELECT * FROM commerce_events WHERE id=?',(event.event_id,)).fetchone()
        if old:
            if old['tenant'] != tenant or old['fingerprint'] != fp:
                raise IdempotencyConflict('支付事件 ID 已用于不同事件')
            return order
        if order['amount_cents'] != event.amount_cents:
            raise InputInvalid('支付金额与订单不符')
        if order['status'] != 'pending':
            raise InvalidStateTransition('订单不再接受新的支付事件')
        result = transition(conn,tenant,order_id,'paid')
        conn.execute('INSERT INTO commerce_events VALUES(?,?,?,?,?,?)',
                     (event.event_id,tenant,order_id,'mock_payment',fp,int(time.time())))
    return result


@contextmanager
def read_snapshot(conn):
    nested=conn.in_transaction
    if not nested:conn.execute('BEGIN')
    try:yield conn
    finally:
        if not nested:conn.execute('ROLLBACK')


def review(conn,tenant):
    with read_snapshot(conn):return _review(conn,tenant)


def _review(conn, tenant, orders=None):
    results = []
    if orders is None:orders=listing(conn,'commerce_orders',tenant)
    losses={r['order_id']:json.loads(r['snapshot']) for r in conn.execute('SELECT r.order_id,r.snapshot FROM commerce_refund_costs r JOIN commerce_orders o ON o.id=r.order_id WHERE o.tenant=?',(tenant,))}
    for order in orders:
        predicted=sum(item['snapshot']['decision']['unit_profit_cents']*item['quantity'] for item in order['items'])
        actual = None
        if order['status'] == 'completed' and order['actual_logistics_cents'] is not None:
            cost=0
            for item in order['items']:
                d=item['snapshot']['decision']
                cost+=(d['procurement_usd_cents']+d['payment_fee_cents']+d['assumptions']['acquisition_cents']+d['assumptions']['aftersales_cents'])*item['quantity']
            pricing=order['snapshot'].get('payment_pricing')
            if pricing:
                legacy_fee=sum(i['snapshot']['decision']['payment_fee_cents']*i['quantity'] for i in order['items'])
                cost+=pricing['fee_cents']-legacy_fee
            actual = order['amount_cents'] - cost - order['actual_logistics_cents']
        if order['status']=='refunded':
            loss=losses.get(order['id'])
            if loss:actual=-loss['loss_cents']
        results.append({'order_id':order['id'],'decision_id':order['snapshot']['decision_id'],
                        'decision_ids':[item['snapshot']['decision_id'] for item in order['items']],
                        'status':order['status'], 'predicted_profit_cents':predicted,
                        'recorded_contribution_cents':actual,
                        'difference_cents':None if actual is None else actual-predicted,
                        'data_kind':'simulation',
                        'note':'已完成单：物流为记录值，其他成本仍为假设；退款单：登记完整损失后按负贡献计入，否则待补全'})
    return results


def summary(conn,tenant):
    with read_snapshot(conn):return _summary(conn,tenant)


def _summary(conn,tenant):
    """Current-state cohort totals; incomplete costs never silently become zero."""
    orders=listing(conn,'commerce_orders',tenant)
    results=_review(conn,tenant,orders)
    counts={status:sum(o['status']==status for o in orders) for status in
            ('pending','paid','shipped','completed','cancelled','refunded')}
    gross=sum(o['amount_cents'] for o in orders if o['status'] in ('paid','shipped','completed','refunded'))
    refunded=sum(o['amount_cents'] for o in orders if o['status']=='refunded')
    eligible=[r for r in results if r['status'] in ('completed','refunded')]
    missing=sum(r['recorded_contribution_cents'] is None for r in eligible)
    known=sum(r['recorded_contribution_cents'] for r in eligible if r['recorded_contribution_cents'] is not None)
    return {'data_kind':'simulation','currency':'USD','status_counts':counts,
            'gross_collected_cents':gross,'refunded_cents':refunded,'retained_receipts_cents':gross-refunded,
            'known_contribution_cents':known,'missing_cost_order_count':missing,
            'complete_contribution_cents':None if missing else known,
            'note':'累计订单按当前状态统计，非会计期间现金流。贡献仅含完成/退款单；已知小计不代表成本完整。'}
