"""Fictional records for disposable benchmark and recovery databases only."""
import sys
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from xborder_insight import commerce as c, supplier_simulation as s, profit_comparisons as pc, metric_scenarios as ms, buyers as b
from xborder_insight.procurement_api import SavedScenario
from xborder_insight.db import migrate
from xborder_insight.db.connection import connect


def seed(path,orders=10,include_buyer=False,benchmark_buyers=0):
    conn=connect(path);migrate.upgrade(conn)
    with c.transaction(conn):
        candidate=c.create_candidate(conn,'local',c.Candidate(name='SIM / Operations fixture',dataset='synthetic',theme_id='ops'),
                                     {'data_kind':'simulation','evidence':['Fictional operations fixture, not market research.']})
        cid=candidate['id'];quotes=[]
        for scenario in ('standard','delayed'):
            case=s.create(conn,'local',cid,scenario)
            for target in ('rfq_sent','quoted'):case=s.advance(conn,'local',case['id'],target,case['version'])
            quotes.append(case['id'])
        loss=ms.save(conn,'local',SavedScenario(candidate_id=cid,metric_id='simulated-sku-returns-10pct-v1',amount_cents=2000,
            usage='simulated_item_loss_scenario',assumption_note='Fictional loss per return; operational test only.'),'ops-loss')
        baseline={'price_cents':3000,'cny_per_usd':'7','logistics_cents':500,'payment_bps':300,'payment_fixed_cents':30,
                  'aftersales_cents':200,'aftersales_scenario_id':loss['id'],'acquisition_cents':300,'risk':'clear',
                  'source_note':'Fictional operational fixture; no verified business costs.'}
        compared=pc.save(conn,'local',pc.Comparison(candidate_id=cid,quote_ids=quotes,baseline=baseline,
            stress={'price_cents':2500,'cny_per_usd':'6','logistics_cents':800},note='Fictional operations stress test.'),'ops-comparison')
        option=compared['snapshot']['options'][0]
        decision=c.decide(conn,'local',cid,c.Assumptions(**(option['evaluation']['assumptions']|{'comparison_id':compared['id'],'comparison_option':option['key']})))
        product=c.draft(conn,'local',decision['id']);c.add_stock(conn,'local',product['id'],1000);c.publish(conn,'local',product['id'])
        for index in range(orders):
            order=c.checkout(conn,'local','seed-'+str(index),c.Checkout(product_id=product['id'],quantity=1))
            c.transition(conn,'local',order['id'],'cancelled')
        race_decision=c.decide(conn,'local',cid,c.Assumptions(**option['evaluation']['assumptions']))
        race=c.draft(conn,'local',race_decision['id']);c.add_stock(conn,'local',race['id'],3);c.publish(conn,'local',race['id'])
        result={'candidate_id':cid,'comparison_id':compared['id'],'scenario_id':loss['id'],
                'decision_id':decision['id'],'product_id':product['id'],'race_product_id':race['id']}
        result['benchmark_buyers']=[]
        for index in range(benchmark_buyers):
            token=b.register(conn,'local',b.Credentials(email=f'benchmark-{index}@example.test',password='fictional-benchmark-pass'))
            user=b.session(conn,'local',token)
            address=b.add_address(conn,user,b.Address(recipient='Fictional Benchmark Buyer',line1='123 Example Street',city='Seattle',state='WA',postal_code='98101'))
            result['benchmark_buyers'].append({'token':token,'csrf':user['csrf'],'address_id':address['id']})
        if include_buyer:
            token=b.register(conn,'local',b.Credentials(email='recovery-fixture@example.test',password='fictional-recovery-pass'))
            user=b.session(conn,'local',token)
            address=b.add_address(conn,user,b.Address(recipient='Fictional Recovery Buyer',line1='123 Example Street',city='Seattle',state='WA',postal_code='98101'))
            b.set_cart(conn,user,b.CartItem(product_id=product['id'],quantity=1))
            order=b.checkout_cart(conn,user,'recovery-buyer-order',b.CartCheckout(address_id=address['id']))
            c.pay(conn,'local',order['id'],c.Payment(event_id='recovery-payment',amount_cents=3000))
            c.transition(conn,'local',order['id'],'shipped',c.Shipment(tracking='SIM-RECOVERY-001',actual_logistics_cents=550))
            c.transition(conn,'local',order['id'],'completed')
            result['buyer_id']=user['id'];result['buyer_order_id']=order['id']
    conn.close()
    return result
