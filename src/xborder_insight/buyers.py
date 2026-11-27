"""Buyer identity and ownership. No plaintext passwords or session tokens in DB."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from uuid import uuid4

from pydantic import Field, field_validator

from . import commerce as c
from .db.connection import transaction
from .errors import Unauthorized

SESSION_SECONDS = 7 * 86400


class Credentials(c.Model):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=10, max_length=128)

    @field_validator('email')
    @classmethod
    def email_valid(cls, value):
        value = value.strip().lower()
        if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',value):
            raise ValueError('请输入有效邮箱')
        return value


class Address(c.Model):
    recipient: str = Field(min_length=1,max_length=100)
    line1: str = Field(min_length=1,max_length=180)
    line2: str = Field(default='',max_length=180)
    city: str = Field(min_length=1,max_length=100)
    state: str = Field(pattern=r'^[A-Z]{2}$')
    postal_code: str = Field(pattern=r'^\d{5}(-\d{4})?$')
    country: str = Field(default='US',pattern=r'^US$')

    @field_validator('recipient','line1','city')
    @classmethod
    def nonblank(cls,value):
        if not value.strip():
            raise ValueError('不能为空白')
        return value.strip()


class CartItem(c.Model):
    product_id: str
    quantity: int = Field(ge=0,le=20,strict=True)  # zero removes an item


class CartCheckout(c.Model):
    address_id: str = Field(min_length=1,max_length=64)
    cart_fingerprint: str | None = Field(default=None,pattern=r'^[a-f0-9]{64}$')


class RefundRequest(c.Model):
    reason: str = Field(min_length=3,max_length=1000)


class RefundReview(c.Model):
    approve: bool = Field(strict=True)
    note: str = Field(min_length=3,max_length=1000)


class RefundCosts(c.Model):
    procurement_loss_cents: int = Field(ge=0,le=100_000_000,strict=True)
    logistics_loss_cents: int = Field(ge=0,le=100_000_000,strict=True)
    payment_loss_cents: int = Field(ge=0,le=100_000_000,strict=True)
    other_loss_cents: int = Field(ge=0,le=100_000_000,strict=True)
    note: str = Field(min_length=3,max_length=1000)


class RateLimited(c.AppError):
    code='buyer_rate_limited'
    status_code=429
    headers={'Retry-After':'60'}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    derived = hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1,maxmem=64*1024*1024)
    return f'scrypt-v1${salt}${derived.hex()}'


def password_matches(password,encoded):
    _,salt,_ = encoded.split('$')
    return hmac.compare_digest(password_hash(password,salt),encoded)


DUMMY_PASSWORD_HASH = password_hash('dummy-password',salt='00'*16)


def rate_limit(conn, scope, peer, limit=10):
    now=int(time.time())
    bucket=digest(scope+':'+peer)
    with transaction(conn):
        conn.execute('DELETE FROM commerce_auth_attempts WHERE expires_at<=?',(now,))
        old=conn.execute('SELECT hits FROM commerce_auth_attempts WHERE bucket=?',(bucket,)).fetchone()
        if old and old['hits']>=limit:
            raise RateLimited('请求过于频繁，请稍后重试')
        conn.execute('INSERT INTO commerce_auth_attempts VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET hits=hits+1',(bucket,now+60))


def new_session(conn,buyer_id):
    conn.execute('DELETE FROM commerce_sessions WHERE expires_at<=?',(int(time.time()),))
    # Limit active sessions; revoke oldest when a buyer logs in repeatedly.
    conn.execute('''DELETE FROM commerce_sessions WHERE buyer_id=? AND token_hash NOT IN
                    (SELECT token_hash FROM commerce_sessions WHERE buyer_id=? ORDER BY expires_at DESC LIMIT 9)''',(buyer_id,buyer_id))
    token=secrets.token_urlsafe(32)
    csrf=secrets.token_urlsafe(32)
    conn.execute('INSERT INTO commerce_sessions VALUES(?,?,?,?)',(digest(token),buyer_id,csrf,int(time.time())+SESSION_SECONDS))
    return token


def register(conn,tenant,credentials):
    encoded=password_hash(credentials.password)
    with transaction(conn):
        if conn.execute('SELECT id FROM commerce_buyers WHERE tenant=? AND email=?',(tenant,credentials.email)).fetchone():
            raise c.InputInvalid('账号无法创建，请登录或使用其他邮箱')
        identity=uuid4().hex
        conn.execute('INSERT INTO commerce_buyers VALUES(?,?,?,?,?)',(identity,tenant,credentials.email,encoded,int(time.time())))
        return new_session(conn,identity)


def login(conn,tenant,credentials):
    record=conn.execute('SELECT * FROM commerce_buyers WHERE tenant=? AND email=?',(tenant,credentials.email)).fetchone()
    # Same expensive hash for unknown accounts, reducing timing-based enumeration.
    encoded=record['password_hash'] if record else DUMMY_PASSWORD_HASH
    matches=password_matches(credentials.password,encoded)
    if not record or not matches:
        raise Unauthorized('邮箱或密码错误')
    with transaction(conn):
        return new_session(conn,record['id'])


def session(conn,tenant,token):
    record=conn.execute('''SELECT b.id,b.email,b.tenant,s.csrf FROM commerce_sessions s
                           JOIN commerce_buyers b ON b.id=s.buyer_id
                           WHERE s.token_hash=? AND b.tenant=? AND s.expires_at>?''',
                        (digest(token or ''),tenant,int(time.time()))).fetchone()
    if record is None:
        raise Unauthorized('请先登录买家账号')
    return dict(record)


def addresses(conn,buyer):
    return [{'id':r['id'],**json.loads(r['address_json'])} for r in
            conn.execute('SELECT * FROM commerce_addresses WHERE buyer_id=? ORDER BY created_at,id',(buyer['id'],))]


def add_address(conn,buyer,body):
    with transaction(conn):
        if conn.execute('SELECT COUNT(*) FROM commerce_addresses WHERE buyer_id=?',(buyer['id'],)).fetchone()[0]>=20:
            raise c.InputInvalid('最多保存 20 个地址')
        identity=uuid4().hex
        conn.execute('INSERT INTO commerce_addresses VALUES(?,?,?,?)',(identity,buyer['id'],c.dump(body.model_dump()),int(time.time())))
    return {'id':identity,**body.model_dump()}


def cart(conn,buyer):
    result=[]
    for item in conn.execute('SELECT * FROM commerce_cart WHERE buyer_id=? ORDER BY product_id',(buyer['id'],)):
        product=c.row(conn,'commerce_products',item['product_id'],buyer['tenant'])
        result.append({'product_id':product['id'],'title':product['title'],'quantity':item['quantity'],
                       'price_cents':product['price_cents'],'stock':product['stock'],'status':product['status']})
    return result


def set_cart(conn,buyer,body):
    with transaction(conn):
        if body.quantity==0:
            conn.execute('DELETE FROM commerce_cart WHERE buyer_id=? AND product_id=?',(buyer['id'],body.product_id))
        else:
            product=c.row(conn,'commerce_products',body.product_id,buyer['tenant'])
            if product['status']!='published':
                raise c.InvalidStateTransition('商品未上架')
            if body.quantity>product['stock']:
                raise c.InvalidStateTransition('当前可售库存不足')
            existing=conn.execute('SELECT 1 FROM commerce_cart WHERE buyer_id=? AND product_id=?',(buyer['id'],body.product_id)).fetchone()
            if not existing and conn.execute('SELECT COUNT(*) FROM commerce_cart WHERE buyer_id=?',(buyer['id'],)).fetchone()[0]>=20:
                raise c.InputInvalid('购物车最多 20 种商品')
            conn.execute('INSERT INTO commerce_cart VALUES(?,?,?) ON CONFLICT(buyer_id,product_id) DO UPDATE SET quantity=excluded.quantity',
                         (buyer['id'],body.product_id,body.quantity))
        c.record(conn,buyer['tenant'],'cart.updated',buyer['id'],{'product_id':body.product_id,'quantity':body.quantity})
    return cart(conn,buyer)


def own_order(conn,buyer,order_id):
    order=c.row(conn,'commerce_orders',order_id,buyer['tenant'])
    if order['buyer_id']!=buyer['id']:
        raise c.NotFound('订单不存在')
    return order


class SimulatedPayment(c.Model):
    """No client-supplied amount, currency, outcome or event identity."""


def simulate_payment(conn,buyer,order_id):
    with transaction(conn):
        order=own_order(conn,buyer,order_id)
        return c.pay(conn,buyer['tenant'],order_id,c.Payment(
            event_id='buyer-mock-'+order_id,amount_cents=order['amount_cents'],currency='USD'))


def checkout_cart(conn,buyer,key,body):
    c.validate_key(key)
    scoped_key=buyer['id']+':'+key
    intent={'buyer_id':buyer['id'],'address_id':body.address_id,'operation':'cart-checkout'}
    if body.cart_fingerprint:intent['cart_fingerprint']=body.cart_fingerprint
    fp=c.fingerprint(intent)
    with transaction(conn):
        old=conn.execute('SELECT id,fingerprint FROM commerce_orders WHERE tenant=? AND request_key=?',(buyer['tenant'],scoped_key)).fetchone()
        if old:
            if old['fingerprint']!=fp:
                raise c.IdempotencyConflict('该结算请求已使用其他地址')
            previous=own_order(conn,buyer,old['id'])
            if not body.cart_fingerprint and cart(conn,buyer):
                raise c.IdempotencyConflict('购物车已有内容，请刷新并以新的结算意图提交')
            return previous
        address=conn.execute('SELECT address_json FROM commerce_addresses WHERE id=? AND buyer_id=?',(body.address_id,buyer['id'])).fetchone()
        if not address:
            raise c.NotFound('地址不存在')
        items=cart(conn,buyer)
        if body.cart_fingerprint and body.cart_fingerprint!=checkout_fingerprint(conn,buyer,items):
            raise c.IdempotencyConflict('购物车商品、价格或上架状态已变化，请刷新购物车后重新确认')
        if not items:
            raise c.InputInvalid('购物车为空')
        order=c.checkout_items(conn,buyer['tenant'],scoped_key,fp,
            [(item['product_id'],item['quantity']) for item in items],
            buyer_id=buyer['id'],address=json.loads(address['address_json']))
        conn.execute('DELETE FROM commerce_cart WHERE buyer_id=?',(buyer['id'],))
        return order


def checkout_fingerprint(conn,buyer,items):
    # Append-only audit sequence also distinguishes a new cart with identical contents.
    revision=conn.execute("SELECT COALESCE(MAX(id),0) FROM commerce_audit WHERE tenant=? AND action='cart.updated' AND object_id=?",(buyer['tenant'],buyer['id'])).fetchone()[0]
    lines=[{'product_id':i['product_id'],'quantity':i['quantity'],'price_cents':i['price_cents'],'status':i['status']} for i in sorted(items,key=lambda i:i['product_id'])]
    return c.fingerprint({'revision':revision,'items':lines})


def request_refund(conn,buyer,order_id,body):
    with transaction(conn):
        order=own_order(conn,buyer,order_id)
        old=conn.execute('SELECT * FROM commerce_refunds WHERE order_id=?',(order_id,)).fetchone()
        if old:
            return dict(old)
        if order['status'] not in ('paid','shipped','completed'):
            raise c.InvalidStateTransition('当前订单状态不可申请退款')
        identity=uuid4().hex
        conn.execute('INSERT INTO commerce_refunds(id,tenant,order_id,buyer_id,reason,status,created_at) VALUES(?,?,?,?,?,?,?)',
                     (identity,buyer['tenant'],order_id,buyer['id'],body.reason,'requested',int(time.time())))
        c.record(conn,buyer['tenant'],'refund.requested',identity,{'order_id':order_id})
    return dict(conn.execute('SELECT * FROM commerce_refunds WHERE id=?',(identity,)).fetchone())


def refund_list(conn,tenant,buyer_id=None):
    sql='SELECT * FROM commerce_refunds WHERE tenant=?'
    args=[tenant]
    if buyer_id:
        sql+=' AND buyer_id=?'; args.append(buyer_id)
    with c.read_snapshot(conn):
        result=[]
        for raw in conn.execute(sql+' ORDER BY created_at DESC,id',args):
            refund=dict(raw)
            order=c.row(conn,'commerce_orders',refund['order_id'],tenant)
            refund['order_status']=order['status']
            refund['execution_status']='refunded' if order['status']=='refunded' else 'not_refunded'
            event=conn.execute("SELECT created_at FROM commerce_audit WHERE tenant=? AND object_id=? AND action='order.refunded' ORDER BY id LIMIT 1",(tenant,order['id'])).fetchone()
            refund['executed_at']=event['created_at'] if event else None
            result.append(refund)
        return result


def review_refund(conn,tenant,refund_id,body):
    with transaction(conn):
        refund=c.row(conn,'commerce_refunds',refund_id,tenant)
        target='approved' if body.approve else 'rejected'
        if refund['status']!='requested':
            if refund['status']!=target:
                raise c.InvalidStateTransition('售后申请已处理，不能反向修改')
            return refund
        if body.approve:
            c.transition(conn,tenant,refund['order_id'],'refunded')
        conn.execute('UPDATE commerce_refunds SET status=?,review_note=?,reviewed_at=? WHERE id=?',
                     (target,body.note,int(time.time()),refund_id))
        c.record(conn,tenant,'refund.'+target,refund_id,{'order_id':refund['order_id']})
    return c.row(conn,'commerce_refunds',refund_id,tenant)


def settle_refund(conn,tenant,order_id,body):
    with transaction(conn):
        order=c.row(conn,'commerce_orders',order_id,tenant)
        if order['status']!='refunded':
            raise c.InvalidStateTransition('仅已退款订单可登记损失')
        snapshot=body.model_dump()
        snapshot['data_kind']='simulation'
        snapshot['loss_cents']=sum(value for key,value in body.model_dump().items() if key.endswith('_cents'))
        old=conn.execute('SELECT snapshot FROM commerce_refund_costs WHERE order_id=?',(order_id,)).fetchone()
        if old:
            if old['snapshot']!=c.dump(snapshot):
                raise c.IdempotencyConflict('损失已登记，首版不支持覆盖历史记录')
            return snapshot
        conn.execute('INSERT INTO commerce_refund_costs VALUES(?,?,?)',(order_id,c.dump(snapshot),int(time.time())))
        c.record(conn,tenant,'refund.loss_recorded',order_id,{'loss_cents':snapshot['loss_cents']})
    return snapshot
