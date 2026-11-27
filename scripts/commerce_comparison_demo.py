"""Replay quote comparison through a simulated order in a disposable local DB."""
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fastapi.testclient import TestClient
from xborder_insight import api
from xborder_insight.db import migrate
from xborder_insight.db.connection import connect


def main():
    os.environ["COMMERCE_LEGACY_GUEST_CHECKOUT"]="true"  # disposable legacy demonstration only
    original_db,original_settings=api.DB_FILE,api.settings
    try:
        with TemporaryDirectory() as directory:
            path=Path(directory)/'comparison-demo.sqlite3'
            conn=connect(path);migrate.upgrade(conn);conn.close()
            api.DB_FILE=path
            api.settings=replace(api.settings,auth_required=False,jobs_worker_enabled=False,run_mode='mock',embedding_provider='hash')
            with TestClient(api.app) as client:
                def call(method,url,**kwargs):
                    response=client.request(method,url,**kwargs)
                    response.raise_for_status()
                    return response.json()
                def post(url,body,key=None):
                    return call('POST',url,json=body,headers={'Idempotency-Key':key} if key else {})
                report=call('GET','/v1/commerce/evidence/pet_fountain')
                candidate=post('/v1/commerce/candidates',{'name':'SIM / Comparison fountain','dataset':'pet_fountain','theme_id':report['themes'][0]['theme_id'],'evidence_fingerprint':report['evidence_fingerprint']})
                cid=candidate['id'];quotes=[]
                for scenario in ('standard','delayed'):
                    case=post('/v1/commerce/supplier-cases',{'candidate_id':cid,'scenario':scenario})
                    for target in ('rfq_sent','quoted'):
                        case=post('/v1/commerce/supplier-cases/'+case['id']+'/transition',{'target':target,'expected_version':case['version']})
                    quotes.append(case['id'])
                loss=post('/v1/commerce/metric-scenarios',{'candidate_id':cid,'metric_id':'simulated-sku-returns-10pct-v1','amount_cents':2000,
                    'usage':'simulated_item_loss_scenario','assumption_note':'Fictional $20 loss for a returned unit; not an observed SKU cost.'},'demo-loss')
                body={'candidate_id':cid,'quote_ids':quotes,
                      'baseline':{'price_cents':3000,'cny_per_usd':'7','logistics_cents':500,'payment_bps':300,'payment_fixed_cents':30,
                                  'aftersales_cents':200,'aftersales_scenario_id':loss['id'],'acquisition_cents':300,
                                  'risk':'clear','source_note':'Synthetic demo parameters, not verified business data.'},
                      'stress':{'price_cents':2500,'cny_per_usd':'6','logistics_cents':800},
                      'note':'Fictional price, exchange rate and logistics downside. No real supplier integration.'}
                saved=post('/v1/commerce/profit-comparisons',body,'demo-compare')
                assert post('/v1/commerce/profit-comparisons',body,'demo-compare')['id']==saved['id']
                options=saved['snapshot']['options']
                assert [options[i]['evaluation']['unit_profit_cents'] for i in (0,4,5,9)]==[880,-72,594,-405]
                def decide(option):
                    inputs=option['evaluation']['assumptions']|{'comparison_id':saved['id'],'comparison_option':option['key']}
                    return post('/v1/commerce/candidates/'+cid+'/decisions',inputs)
                pressure=decide(options[4]);assert pressure['snapshot']['conclusion']=='NO_GO'
                decision=decide(options[0]);assert decision['snapshot']['conclusion']=='GO'
                product=post('/v1/commerce/decisions/'+decision['id']+'/draft',{})
                post('/v1/commerce/products/'+product['id']+'/stock',{'quantity':3})
                post('/v1/commerce/products/'+product['id']+'/publish',{})
                order=post('/shop/api/orders',{'product_id':product['id'],'quantity':1},'demo-order')
                oid=order['id']
                payment={'event_id':'demo-comparison-pay','amount_cents':3000}
                post('/v1/commerce/orders/'+oid+'/pay',payment)
                post('/v1/commerce/orders/'+oid+'/pay',payment)
                post('/v1/commerce/orders/'+oid+'/ship',{'tracking':'SIM-COMPARE-001','actual_logistics_cents':550})
                post('/v1/commerce/orders/'+oid+'/complete',{})
                review=call('GET','/v1/commerce/review')[0]
                assert review['predicted_profit_cents']==880 and review['recorded_contribution_cents']==830 and review['difference_cents']==-50
                orders=call('GET','/v1/commerce/orders')['items']
                frozen=orders[0]['items'][0]['snapshot']['decision']
                assert frozen['comparison_reference']['comparison_id']==saved['id']
                assert frozen['aftersales_scenario']['result_cents']==200
                assert frozen['returns_metric_reference']['source_kind']=='public_survey_estimate'
                integrity=call('GET','/v1/commerce/integrity');assert integrity['ok']
                print(json.dumps({'status':'passed','data_kind':'simulation','quote_count':2,'scenario_count':10,
                                  'baseline_profit_cents':[880,594],'combined_pressure_profit_cents':[-72,-405],
                                  'predicted_contribution_cents':880,'recorded_contribution_cents':830,
                                  'difference_cents':-50,'comparison_preserved_in_order':True,'integrity':integrity},ensure_ascii=False,indent=2))
    finally:
        api.DB_FILE,api.settings=original_db,original_settings


if __name__=='__main__':
    main()
