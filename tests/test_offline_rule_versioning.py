"""Version-aware caching and replay preserve old task meanings and live authorization."""
import asyncio
import json
import pytest
from xborder_insight import review_analysis as r,commerce_api
from test_review_analysis import database,make_run


def test_new_offline_version_invalidates_cache_without_overwriting_old_result(database,monkeypatch):
    _,opened=database
    first=make_run(opened);asyncio.run(r.execute(opened,r.claim(opened)))
    with opened() as db:old=r.get(db,'local',first['id'])
    assert old['provenance']['offline_rule_version']==r.RULE_VERSION
    assert old['result']['execution']['offline_rule_version']==r.RULE_VERSION
    assert make_run(opened,'baseline','reuse')['id']==first['id']
    monkeypatch.setattr(r,'RULE_VERSION','changed-offline-version')
    fresh=make_run(opened,'baseline','version-miss')
    assert fresh['id']!=first['id']
    with opened() as db:
        assert r.get(db,'local',first['id'])==old
        assert db.execute('SELECT COUNT(*) FROM commerce_review_budgets').fetchone()[0]==0


def test_legacy_queued_task_runs_legacy_and_unavailable_version_fails_explicitly(database):
    _,opened=database;task=make_run(opened)
    with opened() as db:
        p=dict(task['provenance']);p.pop('offline_rule_version');p['model']='mock-rules'
        db.execute('UPDATE commerce_review_analyses SET provenance=? WHERE id=?',(json.dumps(p),task['id']))
    asyncio.run(r.execute(opened,r.claim(opened)))
    with opened() as db:
        old=r.get(db,'local',task['id']);assert old['status']=='succeeded'
        assert 'offline_rule_version' not in old['result']['execution']
        fresh=r.submit(db,'local',r.AnalysisRequest(dataset='pet_fountain',force_refresh=True),'unknown')
        p=dict(fresh['provenance']);p['offline_rule_version']='unavailable-version'
        db.execute('UPDATE commerce_review_analyses SET provenance=? WHERE id=?',(json.dumps(p),fresh['id']))
    asyncio.run(r.execute(opened,r.claim(opened)))
    with opened() as db:
        assert r.get(db,'local',fresh['id'])['error_code']=='offline_rule_version_unavailable'


def test_live_provenance_and_other_category_remain_unchanged(database):
    _,opened=database
    live=make_run(opened,'live')
    assert live['provenance']['model']=='qwen3.5-flash' and 'offline_rule_version' not in live['provenance']
    with opened() as db:
        other=r.submit(db,'local',r.AnalysisRequest(dataset='coffee_machine'),'other')
        assert other['provenance']['model']=='mock-rules' and 'offline_rule_version' not in other['provenance']


def test_legacy_bridge_version_changes_fingerprint_and_names_selected_rules():
    report=asyncio.run(commerce_api.evidence('pet_fountain'))
    assert report['offline_rule_version']==r.RULE_VERSION
    assert commerce_api.evidence_fingerprint('pet_fountain',report)!=commerce_api.evidence_fingerprint('pet_fountain',{**report,'offline_rule_version':'older'})
    other=asyncio.run(commerce_api.evidence('coffee_machine'))
    assert 'offline_rule_version' not in other
