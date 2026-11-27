"""Cookie sessions and synchronizer CSRF tokens for buyer-owned resources."""
import os
import secrets
from urllib.parse import urlsplit

from fastapi import Depends, Header, Request, Response

from . import buyers as b, commerce as c
from .errors import Unauthorized
from .commerce_audit import actor_db
from .config import settings

COOKIE='cb_buyer'


def cookie_name(request):
    port=request.url.port
    return COOKIE if port in (None,80,443) else f'{COOKIE}_{port}'


def session_token(request):
    token=request.cookies.get(cookie_name(request))
    # Only the canonical local instance can migrate its pre-isolation cookie.
    if not token and request.url.port==8031:token=request.cookies.get(COOKIE)
    return token


def set_session_cookie(response,request,token):
    response.set_cookie(cookie_name(request),token,max_age=b.SESSION_SECONDS,httponly=True,samesite='lax',
                        secure=os.getenv('COMMERCE_SECURE_COOKIES','false').lower()=='true',path='/shop')


def same_origin(request):
    origin=request.headers.get('origin')
    if origin:
        parsed=urlsplit(origin)
        if parsed.netloc!=request.url.netloc or parsed.scheme!=request.url.scheme:
            raise Unauthorized('请求来源不匹配')


def install(app,open_db,principal,tenant,public_order):
    def buyer(request:Request):
        with open_db() as conn:
            user=b.session(conn,tenant,session_token(request))
        if request.method not in ('GET','HEAD','OPTIONS'):
            same_origin(request)
            if not secrets.compare_digest(request.headers.get('x-csrf-token',''),user['csrf']):
                raise Unauthorized('请刷新页面后重试（CSRF 校验失败）')
        return user

    @app.post('/shop/api/account/register',tags=['buyer'])
    def register(body:b.Credentials,request:Request,response:Response):
        return authenticate('register',body,request,response)

    @app.post('/shop/api/account/login',tags=['buyer'])
    def login(body:b.Credentials,request:Request,response:Response):
        return authenticate('login',body,request,response)

    def authenticate(action,body,request,response):
        same_origin(request)
        peer=request.client.host if request.client else 'local'
        with open_db() as conn:
            b.rate_limit(conn,action,peer,limit=5 if action=='register' else 10)
            token=getattr(b,action)(conn,tenant,body)
            user=b.session(conn,tenant,token)
        set_session_cookie(response,request,token)
        return {'id':user['id'],'email':user['email'],'csrf':user['csrf']}

    @app.get('/shop/api/account/me',tags=['buyer'])
    def me(request:Request,response:Response,user=Depends(buyer)):
        if not request.cookies.get(cookie_name(request)):
            set_session_cookie(response,request,session_token(request))
        return {'id':user['id'],'email':user['email'],'csrf':user['csrf']}

    @app.post('/shop/api/account/logout',tags=['buyer'])
    def logout(request:Request,response:Response,user=Depends(buyer)):
        with open_db() as conn:
            conn.execute('DELETE FROM commerce_sessions WHERE token_hash=?',(b.digest(session_token(request) or ''),))
        response.delete_cookie(cookie_name(request),path='/shop')
        if request.url.port==8031:response.delete_cookie(COOKIE,path='/shop')
        return {'logged_out':True}

    @app.get('/shop/api/addresses',tags=['buyer'])
    def addresses(user=Depends(buyer)):
        with actor_db(open_db,user) as conn:
            return b.addresses(conn,user)

    @app.post('/shop/api/addresses',tags=['buyer'])
    def address(body:b.Address,user=Depends(buyer)):
        with actor_db(open_db,user) as conn:
            return b.add_address(conn,user,body)

    @app.get('/shop/api/cart',tags=['buyer'])
    def cart(user=Depends(buyer)):
        with actor_db(open_db,user) as conn:
            with c.read_snapshot(conn):return b.cart(conn,user)

    @app.get('/shop/api/checkout-preview',tags=['buyer'])
    def preview(user=Depends(buyer)):
        with actor_db(open_db,user) as conn:
            with c.read_snapshot(conn):
                items=b.cart(conn,user)
                return {'items':items,'cart_fingerprint':b.checkout_fingerprint(conn,user,items)}

    @app.post('/shop/api/cart',tags=['buyer'])
    def update_cart(body:b.CartItem,user=Depends(buyer)):
        with actor_db(open_db,user) as conn:
            return b.set_cart(conn,user,body)

    @app.post('/shop/api/checkout',tags=['buyer'])
    def checkout(body:b.CartCheckout,user=Depends(buyer),idempotency_key:str=Header(alias='Idempotency-Key')):
        with actor_db(open_db,user) as conn:
            b.rate_limit(conn,'buyer-checkout',user['id'],limit=30)
            return public_order(b.checkout_cart(conn,user,idempotency_key,body))

    def owned_public(order):
        return public_order(order) | {'address':order['snapshot'].get('address')}

    @app.get('/shop/api/my/orders',tags=['buyer'])
    def orders(user=Depends(buyer)):
        with actor_db(open_db,user) as conn:
            ids=conn.execute('SELECT id FROM commerce_orders WHERE buyer_id=? AND tenant=? ORDER BY created_at DESC,id',
                             (user['id'],tenant)).fetchall()
            return [owned_public(b.own_order(conn,user,r['id'])) for r in ids]

    @app.get('/shop/api/my/orders/{order_id}',tags=['buyer'])
    def order(order_id:str,user=Depends(buyer)):
        with actor_db(open_db,user) as conn:
            return owned_public(b.own_order(conn,user,order_id))

    @app.post('/shop/api/my/orders/{order_id}/cancel',tags=['buyer'])
    def cancel(order_id:str,user=Depends(buyer)):
        with actor_db(open_db,user) as conn:
            with c.transaction(conn):
                order=b.own_order(conn,user,order_id)
                if order['status'] not in ('pending','cancelled'):
                    raise c.InvalidStateTransition('仅待支付订单可取消')
                return owned_public(c.transition(conn,tenant,order_id,'cancelled'))

    @app.post('/shop/api/my/orders/{order_id}/pay',tags=['buyer'])
    def pay(order_id:str,body:b.SimulatedPayment,user=Depends(buyer)):
        if not settings.is_mock:
            raise c.InvalidStateTransition('模拟支付仅适用于本地模拟模式')
        with actor_db(open_db,user) as conn:
            return owned_public(b.simulate_payment(conn,user,order_id))

    @app.post('/shop/api/my/orders/{order_id}/refund',tags=['buyer'])
    def refund(order_id:str,body:b.RefundRequest,user=Depends(buyer)):
        with actor_db(open_db,user) as conn:
            return b.request_refund(conn,user,order_id,body)

    @app.get('/shop/api/my/refunds',tags=['buyer'])
    def refunds(user=Depends(buyer)):
        with actor_db(open_db,user) as conn:
            return b.refund_list(conn,tenant,user['id'])

    @app.get('/v1/commerce/refunds',tags=['commerce'])
    def refund_admin(user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return b.refund_list(conn,user.tenant_id)

    @app.post('/v1/commerce/refunds/{refund_id}/review',tags=['commerce'])
    def review_refund(refund_id:str,body:b.RefundReview,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return b.review_refund(conn,user.tenant_id,refund_id,body)

    @app.post('/v1/commerce/refund-costs/{order_id}',tags=['commerce'])
    def costs(order_id:str,body:b.RefundCosts,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return b.settle_refund(conn,user.tenant_id,order_id,body)
