"""Commerce HTTP adapter; seller endpoints reuse existing principal and DB lifecycle."""
import os
from dataclasses import replace
from pathlib import Path

from fastapi import Depends, Header, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import commerce as c
from . import catalog_categories
from . import commerce_order_views as order_views
from .commerce_audit import actor_db, page as audit_page
from .config import settings
from .llm import build_llm_client
from .offline_rules import OfflineRuleClient, RULE_VERSION
from .pipeline.analyze import analyze_reviews
from .pipeline.ingest import load_reviews

SHOP_TENANT = os.getenv('SHOP_TENANT','local')


def seller_order_response(order):
    return JSONResponse(order_views.seller_order(order),headers={'Cache-Control':'no-store'})


def evidence_fingerprint(dataset,report):
    payload={'dataset':dataset,'themes':report['themes']}
    if report.get('offline_rule_version'):payload['offline_rule_version']=report['offline_rule_version']
    return c.fingerprint(payload)


async def evidence(dataset):
    # This bridge deliberately uses free offline baseline, even when main app is live.
    cfg = replace(settings,run_mode='mock',embedding_provider='hash',cluster_threshold=0.14)
    client = OfflineRuleClient() if dataset=='pet_fountain' else build_llm_client(cfg)
    try:
        result = await analyze_reviews(load_reviews(dataset),cfg,client,dataset,top_k=50)
        report=result.report.model_dump(mode='json')
        if dataset=='pet_fountain':report['offline_rule_version']=RULE_VERSION
        return report
    finally:
        await client.aclose()


from .seller_requests import execute as seller_request


def install(app, open_db, principal):
    app.mount('/commerce-assets/product-images',StaticFiles(directory=Path(__file__).parent/'static'/'product-images'),name='product-images')
    from .review_analysis_api import install as install_review_analysis
    install_review_analysis(app,open_db,principal)
    from .procurement_api import install as install_procurement
    install_procurement(app,open_db,principal)
    from . import commerce_queries as queries

    @app.get('/v1/commerce/catalog-stages',tags=['commerce'])
    def catalog_stages(user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            conn.execute('BEGIN')
            try:return catalog_categories.stages(c.listing(conn,'commerce_candidates',user.tenant_id),c.listing(conn,'commerce_products',user.tenant_id))
            finally:conn.execute('ROLLBACK')

    @app.get('/v1/commerce/orders',tags=['commerce'])
    def query_orders(status:str|None=None,since:int=0,until:int|None=None,cursor:str|None=None,limit:int=30,view:str='full',user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            conn.execute('BEGIN')
            try:
                result=queries.orders(conn,user.tenant_id,status=status,since=since,until=until,cursor=cursor,limit=limit,view=view)
                if view=='full':result['items']=[order_views.seller_order(order) for order in result['items']]
                return result
            finally:conn.execute('ROLLBACK')

    @app.get('/v1/commerce/orders/{identity}',tags=['commerce'])
    def order_detail(identity:str,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return order_views.detail(conn,user.tenant_id,identity,user.role)

    @app.get('/v1/commerce/orders/{identity}/delivery',tags=['commerce'])
    def order_delivery(identity:str,user=Depends(principal)):
        from fastapi.responses import JSONResponse
        with actor_db(open_db,user) as conn:
            return JSONResponse(order_views.delivery(conn,user.tenant_id,identity,user.role),headers={'Cache-Control':'no-store'})

    @app.get('/v1/commerce/integrity',tags=['commerce'])
    def integrity(user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            # A consistent read snapshot across all checks; no writer lock required.
            conn.execute('BEGIN')
            try: return queries.integrity(conn,user.tenant_id)
            finally: conn.execute('ROLLBACK')
    @app.get('/v1/commerce/payment-policy',tags=['commerce'])
    def get_policy(user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return c.payment_policy(conn,user.tenant_id)

    @app.post('/v1/commerce/payment-policy',tags=['commerce'])
    def set_policy(body:c.PaymentPolicy,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return c.save_payment_policy(conn,user.tenant_id,body)
    @app.get('/v1/commerce/me',tags=['commerce'])
    def me(request:Request,user=Depends(principal)):
        return {'tenant':user.tenant_id,'role':user.role,'actor':user.key_prefix or 'local-demo',
                'authenticated':user.authenticated,'shop_tenant':SHOP_TENANT,
                'shop_matches_tenant':user.tenant_id==SHOP_TENANT,'instance':request.url.netloc}

    @app.get('/shop/api/context',tags=['shop'])
    def shop_context(request:Request):
        return {'instance':request.url.netloc,'shop_tenant':SHOP_TENANT,'data_kind':'simulation'}

    @app.get('/v1/commerce/audit',tags=['commerce'])
    def audit(after:int=0,limit:int=50,user=Depends(principal)):
        if after<0 or not 1<=limit<=200:
            raise c.InputInvalid('after 必须非负，limit 为 1–200')
        with actor_db(open_db,user) as conn:
            rows=audit_page(conn,user.tenant_id,after,limit)
            return {'items':rows,'next_after':rows[-1]['id'] if rows else after}

    @app.get('/v1/commerce/summary',tags=['commerce'])
    def summary(user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return c.summary(conn,user.tenant_id)

    from .buyers_api import install as install_buyers
    install_buyers(app,open_db,principal,SHOP_TENANT,public_order)
    @app.get('/workbench',response_class=HTMLResponse,tags=['commerce'])
    def workbench():
        return HTMLResponse(Path(__file__).with_name('commerce_workbench.html').read_text(encoding='utf-8'))

    @app.get('/shop',response_class=HTMLResponse,tags=['commerce'])
    def shop():
        return HTMLResponse(Path(__file__).with_name('commerce_shop_v2.html').read_text(encoding='utf-8'))

    @app.get('/commerce-assets/seller.js',include_in_schema=False)
    def seller_assets():
        from fastapi.responses import Response
        return Response(Path(__file__).with_name('commerce_seller.js').read_text(encoding='utf-8'),media_type='application/javascript')

    @app.get('/v1/commerce/evidence/{dataset}',tags=['commerce'])
    async def get_evidence(dataset: str, user=Depends(principal)):
        report=await evidence(dataset)
        return {**report,'evidence_fingerprint':evidence_fingerprint(dataset,report)}

    @app.post('/v1/commerce/candidates',tags=['commerce'])
    async def candidate(body: c.Candidate,idempotency_key:str|None=Header(default=None,alias="Idempotency-Key"),user=Depends(principal)):
        if body.analysis_id:
            from .review_analysis import candidate_source
            with actor_db(open_db,user) as conn:
                with c.transaction(conn):
                    source=candidate_source(conn,user.tenant_id,body.analysis_id,body.dataset,body.theme_id)
                    return seller_request(conn,user.tenant_id,'candidates',idempotency_key,body.model_dump(mode='json'),lambda:c.create_candidate(conn,user.tenant_id,body,source))
        report = await evidence(body.dataset)
        if body.evidence_fingerprint!=evidence_fingerprint(body.dataset,report):
            raise c.IdempotencyConflict('分析品类或主题版本已变化，请重新加载评论机会')
        theme = next((t for t in report['themes'] if t['theme_id']==body.theme_id),None)
        if theme is None:
            raise c.InputInvalid('该评论主题不存在，请重新加载机会')
        source = {'dataset':body.dataset,'theme':theme,'data_kind':'synthetic_samples',
                  'analysis_mode':'offline_rule_baseline','evidence_fingerprint':body.evidence_fingerprint}
        if report.get('offline_rule_version'):source['offline_rule_version']=report['offline_rule_version']
        with actor_db(open_db,user) as conn:
            return seller_request(conn,user.tenant_id,'candidates',idempotency_key,body.model_dump(mode='json'),lambda:c.create_candidate(conn,user.tenant_id,body,source))

    @app.get('/v1/commerce/state',tags=['commerce'])
    def state(include_orders:bool=True,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            with c.read_snapshot(conn):
                result={name:c.listing(conn,'commerce_'+name,user.tenant_id)
                        for name in (('candidates','decisions','products','orders') if include_orders else ('candidates','decisions','products'))}
                if include_orders:result['orders']=[order_views.seller_order(order) for order in result['orders']]
                return result

    @app.post('/v1/commerce/candidates/{candidate_id}/decisions',tags=['commerce'])
    def decide(candidate_id:str,body:c.Assumptions,idempotency_key:str|None=Header(default=None,alias="Idempotency-Key"),user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return seller_request(conn,user.tenant_id,'decisions/'+candidate_id,idempotency_key,body.model_dump(mode='json'),lambda:c.decide(conn,user.tenant_id,candidate_id,body))

    @app.post('/v1/commerce/decisions/{decision_id}/draft',tags=['commerce'])
    def draft(decision_id:str,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return c.draft(conn,user.tenant_id,decision_id)

    @app.post('/v1/commerce/products/{product_id}/stock',tags=['commerce'])
    def stock(product_id:str,body:c.Stock,idempotency_key:str|None=Header(default=None,alias="Idempotency-Key"),user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return seller_request(conn,user.tenant_id,'stock/'+product_id,idempotency_key,body.model_dump(mode='json'),lambda:c.add_stock(conn,user.tenant_id,product_id,body.quantity))

    @app.post('/v1/commerce/products/{product_id}/publish',tags=['commerce'])
    def publish(product_id:str,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return c.publish(conn,user.tenant_id,product_id)

    @app.post('/v1/commerce/products/{product_id}/unpublish',tags=['commerce'])
    def unpublish(product_id:str,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return c.unpublish(conn,user.tenant_id,product_id)

    @app.post('/v1/commerce/products/{product_id}/replace',tags=['commerce'])
    def replace_product(product_id:str,body:c.Replacement,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return c.replace_product(conn,user.tenant_id,product_id,body.decision_id)

    @app.post('/v1/commerce/expire',tags=['commerce'])
    def expire(user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return {'expired':c.expire(conn,user.tenant_id)}

    @app.post('/v1/commerce/orders/{order_id}/pay',tags=['commerce'])
    def pay(order_id:str,body:c.Payment,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return seller_order_response(c.pay(conn,user.tenant_id,order_id,body))

    @app.post('/v1/commerce/orders/{order_id}/ship',tags=['commerce'])
    def ship(order_id:str,body:c.Shipment,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return seller_order_response(c.transition(conn,user.tenant_id,order_id,'shipped',body))

    @app.post('/v1/commerce/orders/{order_id}/{action}',tags=['commerce'])
    def action(order_id:str,action:str,user=Depends(principal)):
        target = {'complete':'completed','refund':'refunded','cancel':'cancelled'}.get(action)
        if target is None:
            raise c.NotFound('操作不存在')
        with actor_db(open_db,user) as conn:
            return seller_order_response(c.transition(conn,user.tenant_id,order_id,target))

    @app.get('/v1/commerce/review',tags=['commerce'])
    def review(user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return c.review(conn,user.tenant_id)

    @app.get('/shop/api/products',tags=['shop'])
    def catalog():
        with open_db() as conn:
            # Do not expose sourcing, costs, tenant records or decisions to buyers.
            with c.read_snapshot(conn):
                return [public_product(p) for p in c.listing(conn,'commerce_products',SHOP_TENANT) if p['status']=='published']

    @app.post('/shop/api/orders',tags=['shop'])
    def checkout(body:c.Checkout,request:Request,idempotency_key:str=Header(alias='Idempotency-Key')):
        if os.getenv('COMMERCE_LEGACY_GUEST_CHECKOUT','false').lower()!='true':
            raise c.InvalidStateTransition('游客下单接口已停用，请登录后使用购物车结算')
        if any(name.startswith('cb_buyer') for name in request.cookies):
            raise c.InvalidStateTransition('当前请求含买家会话，请使用账户购物车结算，不能创建游客订单')
        from .buyers import rate_limit
        with open_db() as conn:
            rate_limit(conn,'guest-checkout',request.client.host if request.client else 'local',limit=30)
            order = c.checkout(conn,SHOP_TENANT,idempotency_key,body)
            return public_order(order,include_token=True)

    @app.get('/shop/api/orders/{order_id}',tags=['shop'])
    def order(order_id:str,authorization:str=Header(default='')):
        with open_db() as conn:
            order = c.row(conn,'commerce_orders',order_id,SHOP_TENANT)
            import secrets
            if not secrets.compare_digest(authorization,'Bearer '+order['token']):
                raise c.NotFound('订单不存在')
            return public_order(order)


def public_product(p):
    category=catalog_categories.product_category(p)
    return {**{k:p[k] for k in ('id','title','price_cents','stock')},'category_id':category['id'],'category_name':category['name']}


def public_order(order,include_token=False):
    result = {k:order[k] for k in ('id','quantity','amount_cents','status','tracking','expires_at')}
    result['currency'] = 'USD'
    result['data_kind'] = 'simulation'
    result['items'] = [{'product_id':item['product_id'],'title':item['snapshot']['product_title'],
                        'quantity':item['quantity'],'unit_price_cents':item['unit_price_cents']} for item in order['items']]
    if include_token:
        result['token'] = order['token']
    return result
