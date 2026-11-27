import pytest
from xborder_insight import commerce as c, supplier_simulation as s, business_metrics as m
from test_commerce import product, assumptions


def candidate(conn):
    p=product(conn)
    return p['snapshot']['candidate']['id']


def test_simulated_supplier_lifecycle_and_immutable_decision(conn):
    cid=candidate(conn)
    case=s.create(conn,'local',cid,'standard')
    assert case['data_kind']=='simulation' and not case['quote_available']
    with pytest.raises(c.InvalidStateTransition): s.advance(conn,'local',case['id'],'accepted',1)
    for target in ['rfq_sent','quoted']:
        case=s.advance(conn,'local',case['id'],target,case['version'])
    assert case['quote']['source']=='local_fixture_v1'
    decision=c.decide(conn,'local',cid,assumptions(supplier_quote_id=case['id']))
    assert decision['snapshot']['supplier_quote']['data_kind']=='simulation'
    assert decision['snapshot']['returns_metric_reference']['source_kind']=='public_survey_estimate'
    old=decision['snapshot']
    with pytest.raises(c.IdempotencyConflict): s.advance(conn,'local',case['id'],'accepted',1)
    for target in ['sample_requested','sample_received','accepted']:
        case=s.advance(conn,'local',case['id'],target,case['version'])
    assert all(h['data_kind']=='simulation' for h in case['history'])
    assert c.row(conn,'commerce_decisions',decision['id'],'local')['snapshot']==old
    with pytest.raises(c.NotFound): s.read(conn,'other',case['id'])


def test_metric_basis_separation_and_fallback():
    records=m.catalog()
    assert all(all(k in r for k in ('source_kind','scope','period','basis','assumptions','checked_at','publisher')) for r in records)
    real=m.scenario('nrf-us-online-returns-2025-v1',10000,'sales_benchmark_only')
    assert real['result_cents']==1930 and real['metric_snapshot']['period']=='2025'
    with pytest.raises(c.InputInvalid): m.scenario('nrf-us-online-returns-2025-v1',10000,'simulated_item_loss_scenario')
    fake=m.scenario('simulated-sku-returns-10pct-v1',1000,'simulated_item_loss_scenario')
    assert fake['result_cents']==100 and fake['metric_snapshot']['source_kind']=='simulation'
    with pytest.raises(c.InputInvalid): m.get('missing')


def test_quote_binding_and_supplier_inputs_cannot_be_real(conn):
    from xborder_insight.procurement_api import NewCase
    from pydantic import ValidationError
    with pytest.raises(ValidationError): NewCase(candidate_id='x',supplier_url='https://example.com')
    cid=candidate(conn);case=s.create(conn,'local',cid,'delayed')
    for target in ['rfq_sent','quoted']:case=s.advance(conn,'local',case['id'],target,case['version'])
    with pytest.raises(c.InputInvalid): c.decide(conn,'local',cid,assumptions(supplier_quote_id=case['id']))
    decision=c.decide(conn,'local',cid,assumptions(purchase_cny_cents=9000,supplier_quote_id=case['id']))
    assert decision['snapshot']['supplier_quote']['quote']['lead_days']==30
    assert decision['snapshot']['assumptions']['aftersales_cents']==100
