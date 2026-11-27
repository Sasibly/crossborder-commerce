import sqlite3
import pytest
from pydantic import ValidationError

from xborder_insight import commerce as c, supplier_simulation as s, profit_comparisons as pc
from xborder_insight.db import migrate
from test_commerce import product, assumptions
from test_commerce_access import secured


def quote(conn,cid,scenario='standard'):
    case=s.create(conn,'local',cid,scenario)
    for target in ('rfq_sent','quoted'):
        case=s.advance(conn,'local',case['id'],target,case['version'])
    return case


def comparison_body(conn,cid=None,**changes):
    cid=cid or product(conn)['snapshot']['candidate']['id']
    quotes=[quote(conn,cid),quote(conn,cid,'delayed')]
    base=assumptions(aftersales_cents=200).model_dump(mode='json')
    base.update(purchase_cny_cents=None)
    return pc.Comparison(**({'candidate_id':cid,'quote_ids':[q['id'] for q in quotes],
                            'baseline':base,'stress':{'price_cents':2500,'cny_per_usd':'6','logistics_cents':800},
                            'note':'Fictional baseline and downside; not observed performance.'}|changes))


def selected(saved,index=0):
    option=saved['snapshot']['options'][index]
    return c.Assumptions(**(option['evaluation']['assumptions']|{'comparison_id':saved['id'],'comparison_option':option['key']}))


def test_manual_math_single_factor_and_combined_stress(conn):
    body=comparison_body(conn);saved=pc.save(conn,'local',body,'math')
    snapshot=saved['snapshot'];options=snapshot['options']
    assert [o['evaluation']['unit_profit_cents'] for o in options[:5]]==[880,395,713,580,-72]
    assert options[5]['evaluation']['unit_profit_cents']==594
    assert options[9]['evaluation']['unit_profit_cents']==-405
    assert options[4]['difference_from_baseline_cents']==-952
    assert options[4]['evaluation']['conclusion']=='NO_GO'
    assert snapshot['quotes'][0]['minimum_batch_purchase_cny_cents']==700000
    assert snapshot['quotes'][0]['minimum_batch_purchase_usd_cents']==100000
    assert snapshot['quotes'][1]['quote']['moq']==200
    assert snapshot['quotes'][1]['quote']['lead_days']==30
    assert snapshot['returns_metric_reference']['basis']=='sales_share'
    assert snapshot['options'][0]['evaluation']['assumptions']['aftersales_cents']==200
    assert all(q['data_kind']=='simulation' for q in snapshot['quotes'])


def test_half_up_cents_and_whole_batch_conversion(conn):
    body=comparison_body(conn)
    values=body.model_dump(mode='json')
    values['baseline'].update(price_cents=3333,cny_per_usd='6.4')
    saved=pc.save(conn,'local',pc.Comparison(**values),'rounding')
    evaluated=saved['snapshot']['options'][0]['evaluation']
    assert evaluated['procurement_usd_cents']==1094
    assert evaluated['payment_fee_cents']==130
    assert evaluated['unit_profit_cents']==1109
    assert saved['snapshot']['quotes'][0]['minimum_batch_purchase_usd_cents']==109375


def test_idempotency_immutability_and_guarded_downgrade(conn):
    body=comparison_body(conn);saved=pc.save(conn,'local',body,'retry')
    assert pc.save(conn,'local',body,'retry')['id']==saved['id']
    with pytest.raises(c.IdempotencyConflict):
        pc.save(conn,'local',body.model_copy(update={'note':'Changed assumption'}),'retry')
    for command in ('UPDATE commerce_profit_comparisons SET snapshot=\'{}\'', 'DELETE FROM commerce_profit_comparisons'):
        with pytest.raises(sqlite3.IntegrityError):conn.execute(command)
    with pytest.raises(ValueError,match='利润比较快照'):migrate.downgrade(conn,24)
    # Empty newer migrations may roll back before v25 refuses to discard its data.
    assert migrate.current_version(conn)==25


def test_unknown_costs_quote_scope_and_invalid_pressure(conn):
    body=comparison_body(conn)
    for missing in ('logistics_cents','aftersales_cents','acquisition_cents','cny_per_usd','payment_bps'):
        values=body.model_dump(mode='json');values['baseline'][missing]=None
        with pytest.raises(c.InputInvalid,match='补全成本'):pc.save(conn,'local',pc.Comparison(**values),missing)
    values=body.model_dump(mode='json');values['quote_ids']=[body.quote_ids[0]]*2
    with pytest.raises(ValidationError):pc.Comparison(**values)
    values=body.model_dump(mode='json');values['stress']['cny_per_usd']='8'
    with pytest.raises(c.InputInvalid,match='压力'):pc.save(conn,'local',pc.Comparison(**values),'upside')
    values=body.model_dump(mode='json');values['stress'].update(price_cents=3000,cny_per_usd='7',logistics_cents=500)
    with pytest.raises(c.InputInvalid,match='不利变化'):pc.save(conn,'local',pc.Comparison(**values),'identical')
    other=product(conn)['snapshot']['candidate']['id']
    values=body.model_dump(mode='json');values['candidate_id']=other
    with pytest.raises(c.InputInvalid):pc.save(conn,'local',pc.Comparison(**values),'wrong-candidate')
    with pytest.raises(c.NotFound):pc.save(conn,'other',body,'wrong-tenant')
    s.advance(conn,'local',body.quote_ids[0],'rejected',3)
    with pytest.raises(c.InputInvalid):pc.save(conn,'local',body,'rejected')


def test_adoption_is_explicit_exact_and_preserves_historical_snapshots(conn):
    body=comparison_body(conn);saved=pc.save(conn,'local',body,'adopt');cid=body.candidate_id
    assert not conn.execute('SELECT 1 FROM commerce_decisions WHERE snapshot LIKE ?',('%'+saved['id']+'%',)).fetchone()
    inputs=selected(saved);decision=c.decide(conn,'local',cid,inputs)
    assert decision['snapshot']['comparison_reference']['selected_option']['evaluation']['unit_profit_cents']==880
    p=c.draft(conn,'local',decision['id']);c.add_stock(conn,'local',p['id'],1)
    c.publish(conn,'local',p['id'])
    order=c.checkout(conn,'local','old-comparison-order',c.Checkout(product_id=p['id'],quantity=1))
    old_snapshot=decision['snapshot']
    for changes in ({'price_cents':3001},{'cny_per_usd':'7.1'},{'logistics_cents':501},{'aftersales_cents':201},
                    {'risk':'unknown'},{'source_note':'changed'},{'comparison_option':'unknown'}):
        altered=c.Assumptions(**(inputs.model_dump(mode='json')|changes))
        with pytest.raises(c.InputInvalid):c.decide(conn,'local',cid,altered)
    with pytest.raises(c.InputInvalid):c.decide(conn,'local',cid,inputs.model_copy(update={'comparison_option':None}))
    other=product(conn)['snapshot']['candidate']['id']
    with pytest.raises(c.InputInvalid):c.decide(conn,'local',other,inputs)
    s.advance(conn,'local',body.quote_ids[0],'accepted',3)
    with pytest.raises(c.IdempotencyConflict,match='流程已变化'):c.decide(conn,'local',cid,inputs)
    assert pc.save(conn,'local',body,'adopt')['snapshot']==saved['snapshot']
    assert c.row(conn,'commerce_decisions',decision['id'],'local')['snapshot']==old_snapshot
    assert c.row(conn,'commerce_products',p['id'],'local')['snapshot']==old_snapshot
    assert c.row(conn,'commerce_orders',order['id'],'local')['items'][0]['snapshot']['decision']==old_snapshot
    pressure=c.decide(conn,'local',cid,selected(saved,9))
    assert pressure['snapshot']['conclusion']=='NO_GO'
    with pytest.raises(c.InvalidStateTransition):c.draft(conn,'local',pressure['id'])


def test_aftersales_source_and_metric_catalog_drift(conn,monkeypatch):
    from xborder_insight import metric_scenarios as ms,business_metrics as metrics
    from xborder_insight.procurement_api import SavedScenario
    body=comparison_body(conn)
    loss=ms.save(conn,'local',SavedScenario(candidate_id=body.candidate_id,metric_id='simulated-sku-returns-10pct-v1',
                                         amount_cents=2000,usage='simulated_item_loss_scenario',assumption_note='Fictional loss.'),'loss')
    values=body.model_dump(mode='json');values['baseline']['aftersales_scenario_id']=loss['id']
    saved=pc.save(conn,'local',pc.Comparison(**values),'metric')
    assert saved['snapshot']['aftersales_scenario']['metric_snapshot']['source_kind']=='simulation'
    decision=c.decide(conn,'local',body.candidate_id,selected(saved))
    assert decision['snapshot']['aftersales_scenario']['result_cents']==200
    old_get=metrics.get
    monkeypatch.setattr(metrics,'get',lambda key:old_get(key)|{'value':'0.20'})
    with pytest.raises(c.IdempotencyConflict,match='指标版本'):c.decide(conn,'local',body.candidate_id,selected(saved))
    assert c.row(conn,'commerce_profit_comparisons',saved['id'],'local')['snapshot']['returns_metric_reference']['value']=='0.193'


def test_audit_failure_rolls_back_comparison(conn):
    body=comparison_body(conn)
    conn.execute("CREATE TRIGGER fail_comparison_audit BEFORE INSERT ON commerce_audit WHEN NEW.action='profit_comparison.saved' BEGIN SELECT RAISE(ABORT,'injected'); END")
    with pytest.raises(sqlite3.IntegrityError):pc.save(conn,'local',body,'rollback')
    assert conn.execute('SELECT COUNT(*) FROM commerce_profit_comparisons').fetchone()[0]==0


def test_http_permissions_and_tenant_isolation(secured):
    from xborder_insight.db.connection import connect
    client,path,p,auth=secured
    db=connect(path);body=comparison_body(db,p['snapshot']['candidate']['id']);db.close()
    url='/v1/commerce/profit-comparisons';payload=body.model_dump(mode='json')
    assert client.post(url,json=payload,headers=auth['viewer']|{'Idempotency-Key':'viewer'}).status_code==403
    assert client.post(url,json=payload,headers=auth['operator']).status_code==422
    r=client.post(url,json=payload,headers=auth['operator']|{'Idempotency-Key':'http'})
    assert r.status_code==200,r.text
    saved=r.json()
    assert client.get(url+'/'+saved['id'],headers=auth['viewer']).json()['id']==saved['id']
    assert client.get(url+'/'+saved['id'],headers=auth['other']).status_code==404
    assert client.get(url,params={'candidate_id':body.candidate_id},headers=auth['viewer']).json()[0]['id']==saved['id']
    assert client.get(url,params={'candidate_id':body.candidate_id},headers=auth['other']).status_code==404
    decision=client.post('/v1/commerce/candidates/'+body.candidate_id+'/decisions',json=selected(saved).model_dump(mode='json'),headers=auth['operator'])
    assert decision.status_code==200,decision.text
    assert decision.json()['snapshot']['comparison_reference']['comparison_id']==saved['id']
