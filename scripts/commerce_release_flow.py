"""Six-category seller/buyer HTTP acceptance, entirely fictional and loopback-only."""
import secrets
import time
from urllib.parse import urlsplit

import httpx


def validate_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1','localhost','::1')
            or parsed.username or parsed.password or parsed.path not in ('','/') or parsed.query or parsed.fragment):
        raise ValueError('Acceptance requires a plain loopback HTTP base URL')


def run(url, run_id, evidence):
    from seed_commerce import DEMO_PRODUCTS
    validate_url(url)
    products, analyses, decisions = [], {}, {}
    evidence.update(status='running', data_kind='simulation', run_id=run_id, created_product_ids=[], cleanup_failures=[])
    with httpx.Client(base_url=url, trust_env=False, timeout=20) as seller, httpx.Client(base_url=url, trust_env=False, timeout=20) as buyer:
        def call(client, method, path, body=None, headers=None, expected=200):
            response = client.request(method, path, json=body, headers=headers or {})
            if response.status_code != expected:raise RuntimeError(f'{method} {path}: HTTP {response.status_code}, expected {expected}')
            return response.json() if expected == 200 else None
        if call(seller,'GET','/health')['run_mode'] != 'mock':raise ValueError('Refusing a non-mock deployment')
        before_catalog = call(seller,'GET','/shop/api/products')
        cfg = call(seller,'GET','/v1/commerce/review-analysis-config')
        before_budget = cfg['authorization_history']
        if any(r['mode']=='live' and r['status'] in ('queued','running') for r in call(seller,'GET','/v1/commerce/review-analyses')):
            raise ValueError('A real model task is active; do not interrupt it')
        costs = {}
        for entry in DEMO_PRODUCTS:costs.setdefault(entry[1],entry)
        try:
            for category in sorted(costs):
                evidence['phase']='analysis_and_listing:'+category
                task = call(seller,'POST','/v1/commerce/review-analyses',{'dataset':category,'mode':'baseline'},
                            {'Idempotency-Key':run_id+'-analysis-'+category})
                deadline = time.monotonic()+60
                while task['status'] in ('queued','running'):
                    if time.monotonic()>deadline:raise TimeoutError('Offline analysis did not complete')
                    time.sleep(.5)
                    task = call(seller,'GET','/v1/commerce/review-analyses/'+task['id'])
                assert task['status']=='succeeded' and task['request_count']==0
                assert task['result']['review_count']==task['result']['parsed_count']==10
                assert task['provenance']['review_data_kind']=='synthetic_samples'
                if category=='pet_fountain':assert task['provenance']['offline_rule_version']==cfg['offline_rule_versions'][category]
                else:assert task['provenance']['model']=='mock-rules'
                reused = call(seller,'POST','/v1/commerce/review-analyses',{'dataset':category,'mode':'baseline'},
                              {'Idempotency-Key':run_id+'-reuse-'+category})
                assert reused['id']==task['id'] and reused.get('reused_result')
                analyses[category] = task['id']
                theme = next(t for t in task['result']['themes'] if t['polarity']=='negative')
                candidate = call(seller,'POST','/v1/commerce/candidates',{'dataset':category,'theme_id':theme['theme_id'],
                                  'analysis_id':task['id'],'name':'SIM / Acceptance '+category+' '+run_id[-8:]})
                _, _, price, purchase, logistics, aftersales, acquisition = costs[category]
                decision = call(seller,'POST',f"/v1/commerce/candidates/{candidate['id']}/decisions",dict(
                    price_cents=price,purchase_cny_cents=purchase,cny_per_usd='7',logistics_cents=logistics,
                    payment_bps=300,payment_fixed_cents=30,aftersales_cents=aftersales,acquisition_cents=acquisition,
                    risk='clear',source_note='Fictional local acceptance costs and demo risk flag; no real supplier/market/compliance verification.'))
                assert decision['snapshot']['conclusion']=='GO'
                product = call(seller,'POST',f"/v1/commerce/decisions/{decision['id']}/draft",{})
                products.append({'id':product['id'],'category':category,'price_cents':price,'decision_id':decision['id'],
                                 'analysis_id':task['id'],'logistics_cents':logistics})
                evidence['created_product_ids'].append(product['id'])
                decisions[product['id']] = decision['snapshot']
                call(seller,'POST',f"/v1/commerce/products/{product['id']}/stock",{'quantity':3})
                call(seller,'POST',f"/v1/commerce/products/{product['id']}/publish",{})
            catalog = {p['id']:p for p in call(seller,'GET','/shop/api/products')}
            evidence['phase']='seller_buyer_catalog_consistency'
            seller_products = {p['id']:p for p in call(seller,'GET','/v1/commerce/state?include_orders=false')['products']}
            for p in products:
                public = catalog[p['id']]
                assert (public['price_cents'], public['category_id'], public['stock'])==(p['price_cents'],p['category'],3)
                assert public['title']==seller_products[p['id']]['title']
                assert not {'snapshot','decision_id','tenant','reserved'} & set(public)
            user = call(buyer,'POST','/shop/api/account/register',{'email':'accept-'+secrets.token_hex(8)+'@example.test','password':secrets.token_urlsafe(24)})
            evidence['phase']='account_cart_checkout'
            csrf = {'X-CSRF-Token':user['csrf']}
            call(buyer,'POST','/shop/api/cart',{'product_id':products[0]['id'],'quantity':1},expected=401)
            address = call(buyer,'POST','/shop/api/addresses',dict(recipient='Fictional Acceptance Buyer',line1='123 Example Street',
                           city='Seattle',state='WA',postal_code='98101'),csrf)
            for product in products:call(buyer,'POST','/shop/api/cart',{'product_id':product['id'],'quantity':1},csrf)
            preview = call(buyer,'GET','/shop/api/checkout-preview')
            body = {'address_id':address['id'],'cart_fingerprint':preview['cart_fingerprint']}
            headers = csrf | {'Idempotency-Key':run_id+'-checkout'}
            order = call(buyer,'POST','/shop/api/checkout',body,headers); oid = order['id']
            evidence['order_id']=oid
            assert call(buyer,'POST','/shop/api/checkout',body,headers)['id']==oid
            assert len(order['items'])==6 and order['amount_cents']==sum(p['price_cents'] for p in products)
            lines = {i['product_id']:i for i in order['items']}
            for p in products:assert lines[p['id']]['unit_price_cents']==p['price_cents']
            for stage in ('pending','paid','shipped','completed','refunded'):
                evidence['phase']='order_status:'+stage
                if stage=='paid':
                    call(buyer,'POST',f'/shop/api/my/orders/{oid}/pay',{},csrf)
                    call(buyer,'POST',f'/shop/api/my/orders/{oid}/pay',{},csrf)
                elif stage=='shipped':
                    actual_shipping = sum(p['logistics_cents'] for p in products)+50
                    call(seller,'POST',f'/v1/commerce/orders/{oid}/ship',{'tracking':'SIM-'+run_id[-12:],'actual_logistics_cents':actual_shipping})
                elif stage=='completed':call(seller,'POST',f'/v1/commerce/orders/{oid}/complete',{})
                elif stage=='refunded':
                    refund=call(buyer,'POST',f'/shop/api/my/orders/{oid}/refund',{'reason':'Fictional acceptance return after completion'},csrf)
                    call(seller,'POST',f"/v1/commerce/refunds/{refund['id']}/review",{'approve':True,'note':'Local simulated refund approval'})
                    call(seller,'POST','/v1/commerce/refund-costs/'+oid,dict(procurement_loss_cents=1000,logistics_loss_cents=500,
                         payment_loss_cents=200,other_loss_cents=0,note='Explicit fictional net-loss scenario, not actual provider charges.'))
                own = call(buyer,'GET',f'/shop/api/my/orders/{oid}')
                full = call(seller,'GET',f'/v1/commerce/orders/{oid}')
                assert own['status']==full['status']==stage
                assert own['amount_cents']==full['amount_cents']==order['amount_cents']
                for item in full['items']:
                    snapshot=item['snapshot']['decision']; source=snapshot['candidate']['source_json']
                    assert source['analysis_id']==analyses[source['dataset']]
                    assert source['analysis_provenance']['supplier']=='simulation'
                    assert snapshot==decisions[item['product_id']]
                if stage=='completed':
                    fee=full['snapshot']['payment_pricing']['fee_cents']
                    cost=sum(d['procurement_usd_cents']+d['assumptions']['acquisition_cents']+d['assumptions']['aftersales_cents'] for d in decisions.values())
                    review=next(r for r in call(seller,'GET','/v1/commerce/review') if r['order_id']==oid)
                    assert review['recorded_contribution_cents']==full['amount_cents']-cost-fee-actual_shipping
            with httpx.Client(base_url=url,trust_env=False,timeout=20) as other:
                call(other,'POST','/shop/api/account/register',{'email':'accept-other-'+secrets.token_hex(8)+'@example.test','password':secrets.token_urlsafe(24)})
                call(other,'GET','/shop/api/my/orders/'+oid,expected=404)
            final = {p['id']:p for p in call(seller,'GET','/v1/commerce/state?include_orders=false')['products']}
            assert all(final[p['id']]['stock']==2 and final[p['id']]['reserved']==0 for p in products)
            review=next(r for r in call(seller,'GET','/v1/commerce/review') if r['order_id']==oid)
            assert review['recorded_contribution_cents']==-1700
            call(buyer,'POST','/shop/api/account/logout',{},csrf)
            evidence.update(status='flow_completed_pending_cleanup',analysis_ids=analyses,categories=sorted(analyses),order_lines=6,
                            amount_cents=order['amount_cents'],statuses_checked=['pending','paid','shipped','completed','refunded'],
                            checkout_and_payment_idempotency=True,source_and_money_snapshots_preserved=True,
                            seller_buyer_catalog_consistent=True,csrf_and_buyer_ownership_checked=True,
                            shipped_refund_no_inventory_restock=True,explicit_simulated_refund_loss_cents=1700,
                            external_model_requests_added=0)
        except Exception as exc:
            evidence.update(status='failed',error_type=type(exc).__name__)
            raise
        finally:
            for p in products:
                try:call(seller,'POST',f"/v1/commerce/products/{p['id']}/unpublish",{})
                except Exception as exc:evidence['cleanup_failures'].append({'product_id':p['id'],'error_type':type(exc).__name__})
            if evidence['cleanup_failures']:
                evidence['status']='failed'
                raise RuntimeError('Acceptance fixtures could not all be unpublished')
        after_catalog=call(seller,'GET','/shop/api/products')
        assert sorted(before_catalog,key=lambda p:p['id'])==sorted(after_catalog,key=lambda p:p['id'])
        assert call(seller,'GET','/v1/commerce/review-analysis-config')['authorization_history']==before_budget
        assert call(seller,'GET','/v1/commerce/integrity')['ok']
        evidence['original_catalog_preserved']=True
        evidence['fixture_products_unpublished']=len(products)
        evidence.update(status='passed',phase='complete')
    return evidence
