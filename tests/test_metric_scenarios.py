import sqlite3
import pytest
from fastapi.testclient import TestClient
from xborder_insight import api, commerce as c, metric_scenarios as scenarios
from xborder_insight.procurement_api import SavedScenario
from xborder_insight.db import migrate
from xborder_insight.db.connection import connect
from test_commerce import product, assumptions


def saved_body(cid,**changes):
    return SavedScenario(**({'candidate_id':cid,'metric_id':'simulated-sku-returns-10pct-v1',
                             'amount_cents':1000,'usage':'simulated_item_loss_scenario',
                             'assumption_note':'Fictional loss per returned item, not an observed cost.'}|changes))


def test_saved_loss_application_idempotency_and_immutability(conn):
    p=product(conn);cid=p['snapshot']['candidate']['id'];body=saved_body(cid)
    saved=scenarios.save(conn,'local',body,'scenario')
    assert saved['snapshot']['result_cents']==100
    assert scenarios.save(conn,'local',body,'scenario')['id']==saved['id']
    with pytest.raises(c.IdempotencyConflict):
        scenarios.save(conn,'local',saved_body(cid,amount_cents=2000),'scenario')
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute('UPDATE commerce_metric_scenarios SET snapshot=? WHERE id=?',('{}',saved['id']))
    with pytest.raises(sqlite3.IntegrityError): conn.execute('DELETE FROM commerce_metric_scenarios')
    decision=c.decide(conn,'local',cid,assumptions(aftersales_scenario_id=saved['id']))
    assert decision['snapshot']['aftersales_scenario']['metric_snapshot']['source_kind']=='simulation'
    assert decision['snapshot']['returns_metric_reference']['source_kind']=='public_survey_estimate'
    assert decision['snapshot']['data_provenance']['aftersales_cents']=='scenario_estimate_from_simulated_item_probability'
    draft=c.draft(conn,'local',decision['id'])
    assert draft['snapshot']['aftersales_scenario']['scenario_id']==saved['id']


def test_public_exposure_is_not_a_sku_cost_and_amount_must_match(conn):
    cid=product(conn)['snapshot']['candidate']['id']
    public=scenarios.save(conn,'local',saved_body(cid,metric_id='nrf-us-online-returns-2025-v1',usage='sales_benchmark_only',amount_cents=10000),'public')
    assert public['snapshot']['result_cents']==1930 and public['snapshot']['application']=='reference_only'
    with pytest.raises(c.InputInvalid):
        c.decide(conn,'local',cid,assumptions(aftersales_cents=1930,aftersales_scenario_id=public['id']))
    simulated=scenarios.save(conn,'local',saved_body(cid),'simulated')
    with pytest.raises(c.InputInvalid):
        c.decide(conn,'local',cid,assumptions(aftersales_cents=101,aftersales_scenario_id=simulated['id']))
    other_cid=product(conn)['snapshot']['candidate']['id']
    with pytest.raises(c.InputInvalid):
        c.decide(conn,'local',other_cid,assumptions(aftersales_scenario_id=simulated['id']))
    with pytest.raises(c.NotFound):
        scenarios.cost_snapshot(conn,'other',simulated['id'],cid,100)


def test_catalog_updates_do_not_rewrite_saved_inputs(conn,monkeypatch):
    from xborder_insight import business_metrics as metrics
    cid=product(conn)['snapshot']['candidate']['id']
    saved=scenarios.save(conn,'local',saved_body(cid),'before-update')
    old_get=metrics.get
    monkeypatch.setattr(metrics,'get',lambda key:old_get(key)|{'value':'0.20'})
    after=scenarios.save(conn,'local',saved_body(cid),'after-update')
    assert after['snapshot']['result_cents']==200
    assert c.row(conn,'commerce_metric_scenarios',saved['id'],'local')['snapshot']['result_cents']==100
    snapshot=scenarios.cost_snapshot(conn,'local',saved['id'],cid,100)
    assert snapshot['metric_snapshot']['value']=='0.10'


def test_downgrade_preserves_saved_metric_sources(conn):
    cid=product(conn)['snapshot']['candidate']['id']
    saved=scenarios.save(conn,'local',saved_body(cid),'keep-source')
    with pytest.raises(ValueError,match='指标场景快照'):
        migrate.downgrade(conn,23)
    assert migrate.current_version(conn)==24
    assert c.row(conn,'commerce_metric_scenarios',saved['id'],'local')['snapshot']['result_cents']==100


def test_http_candidate_scope_and_decision_link(tmp_path,monkeypatch):
    path=tmp_path/'metric-scenarios.sqlite3';db=connect(path);migrate.upgrade(db)
    cid=product(db)['snapshot']['candidate']['id'];db.close();monkeypatch.setattr(api,'DB_FILE',path)
    with TestClient(api.app) as client:
        body=saved_body(cid).model_dump()
        r=client.post('/v1/commerce/metric-scenarios',json=body,headers={'Idempotency-Key':'http-scenario'})
        assert r.status_code==200,r.text
        saved=r.json()
        assert client.get('/v1/commerce/metric-scenarios',params={'candidate_id':cid}).json()[0]['id']==saved['id']
        decision=client.post(f'/v1/commerce/candidates/{cid}/decisions',json=assumptions(aftersales_scenario_id=saved['id']).model_dump(mode='json'))
        assert decision.status_code==200,decision.text
        assert decision.json()['snapshot']['aftersales_scenario']['input_role']=='loss_per_returned_item'
        assert client.get('/v1/commerce/metric-scenarios',params={'candidate_id':'missing'}).status_code==404
