"""Tenant-bound keyset pagination and read-only business invariant checks."""
import base64
import json
from . import commerce as c

STATUSES={'pending','paid','shipped','completed','cancelled','refunded'}


def orders(conn,tenant,*,status=None,since=0,until=None,cursor=None,limit=30,view='full'):
    if status is not None and status not in STATUSES or not 0<=since<2**63 or until is not None and not since<until<2**63 or not 1<=limit<=100 or view not in ('full','summary'):
        raise c.InputInvalid('状态、时间范围或分页大小无效')
    filters={'tenant':tenant,'status':status,'since':since,'until':until}
    if view!='full':filters['view']=view
    scope=c.fingerprint(filters)
    last=(-1,'')
    ceiling=conn.execute('SELECT COALESCE(MAX(rowid),0) FROM commerce_orders WHERE tenant=?',(tenant,)).fetchone()[0]
    if cursor:
        try:
            if len(cursor)>1024: raise ValueError()
            token=json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if token['scope']!=scope or type(token['ceiling']) is not int or type(token['time']) is not int or not isinstance(token['id'],str):
                raise ValueError()
            ceiling=token['ceiling'];last=(token['time'],token['id'])
            if not 0<=ceiling<2**63 or not -1<=last[0]<2**63 or len(last[1])>64: raise ValueError()
        except (ValueError,KeyError,TypeError,UnicodeError):
            raise c.InputInvalid('分页游标无效或筛选条件已变化')
    sql='SELECT id,created_at FROM commerce_orders WHERE tenant=? AND rowid<=? AND created_at>=? AND (created_at>? OR (created_at=? AND id>?))'
    args=[tenant,ceiling,since,last[0],last[0],last[1]]
    if until is not None: sql+=' AND created_at<?';args.append(until)
    if status is not None: sql+=' AND status=?';args.append(status)
    rows=conn.execute(sql+' ORDER BY created_at,id LIMIT ?',[*args,limit+1]).fetchall()
    page=rows[:limit]
    next_cursor=None
    if len(rows)>limit:
        tail=page[-1]
        next_cursor=base64.urlsafe_b64encode(json.dumps({'scope':scope,'ceiling':ceiling,'time':tail['created_at'],'id':tail['id']}).encode()).decode()
    return {'items':page_rows(conn,tenant,page,view),'next_cursor':next_cursor}


def page_rows(conn,tenant,page,view):
    if not page:return []
    ids=[r['id'] for r in page];slots=','.join('?' for _ in ids)
    columns='*' if view=='full' else "id,status,quantity,amount_cents,tracking,expires_at,created_at,json_extract(snapshot,'$.address') AS address,EXISTS(SELECT 1 FROM commerce_refunds r WHERE r.order_id=commerce_orders.id AND r.status='requested') AS refund_pending"
    result={}
    for raw in conn.execute(f'SELECT {columns} FROM commerce_orders WHERE tenant=? AND id IN ({slots})',[tenant,*ids]):
        order=dict(raw)
        if view=='full':order['snapshot']=json.loads(order['snapshot'])
        else:
            from .commerce_order_views import recipient_summary
            address=json.loads(order.pop('address')) if order.get('address') else None
            order.pop('address',None)
            order['recipient_summary']=recipient_summary(address)
            order['currency']='USD';order['data_kind']='simulation'
        order['items']=[];result[order['id']]=order
    columns='i.*' if view=='full' else "i.order_id,i.product_id,i.quantity,i.unit_price_cents,json_extract(i.snapshot,'$.product_title') AS product_title,json_extract(i.snapshot,'$.decision_id') AS decision_id,json_extract(i.snapshot,'$.decision.assumptions.logistics_cents') AS assumed_logistics_cents"
    for raw in conn.execute(f'SELECT {columns} FROM commerce_order_items i JOIN commerce_orders o ON o.id=i.order_id WHERE o.tenant=? AND i.order_id IN ({slots}) ORDER BY i.product_id',[tenant,*ids]):
        item=dict(raw)
        if view=='full':item['snapshot']=json.loads(item['snapshot'])
        result[item['order_id']]['items'].append(item)
    return [result[identity] for identity in ids]


def integrity(conn,tenant):
    issues=[]
    products=c.listing(conn,'commerce_products',tenant)
    for p in products:
        sums=conn.execute('SELECT COALESCE(SUM(stock_delta),0),COALESCE(SUM(reserved_delta),0) FROM commerce_ledger WHERE tenant=? AND product_id=?',(tenant,p['id'])).fetchone()
        if (p['stock'],p['reserved'])!=tuple(sums):
            issues.append({'kind':'inventory_ledger_mismatch','id':p['id']})
        pending=conn.execute("SELECT COALESCE(SUM(i.quantity),0) FROM commerce_order_items i JOIN commerce_orders o ON o.id=i.order_id WHERE o.tenant=? AND i.product_id=? AND o.status='pending'",(tenant,p['id'])).fetchone()[0]
        if pending!=p['reserved']:
            issues.append({'kind':'reservation_mismatch','id':p['id']})
    orders_=c.listing(conn,'commerce_orders',tenant)
    for o in orders_:
        if not o['items'] or sum(i['quantity']*i['unit_price_cents'] for i in o['items'])!=o['amount_cents'] or sum(i['quantity'] for i in o['items'])!=o['quantity']:
            issues.append({'kind':'order_line_totals_mismatch','id':o['id']})
        for i in o['items']:
            p=conn.execute('SELECT tenant FROM commerce_products WHERE id=?',(i['product_id'],)).fetchone()
            if p is None or p['tenant']!=tenant:
                issues.append({'kind':'order_product_tenant_mismatch','id':o['id']})
        pricing=o['snapshot'].get('payment_pricing')
        if pricing and (sum(pricing['allocations'].values())!=pricing['fee_cents'] or set(pricing['allocations'])!={i['product_id'] for i in o['items']}):
            issues.append({'kind':'payment_fee_allocation_mismatch','id':o['id']})
    return {'ok':not issues,'checked_products':len(products),'checked_orders':len(orders_),'issues':issues,
            'note':'只读业务一致性检查，不自动修复，也不代替数据库完整性和外部支付对账。'}
