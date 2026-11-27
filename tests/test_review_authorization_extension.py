"""A new grant must not reset, borrow, invalidate cache or expand original input."""
import asyncio
import pytest
from xborder_insight import review_analysis as r,commerce as c
from xborder_insight.errors import UpstreamError
from test_review_analysis import database,make_run
from test_review_analysis_performance import transport_fixture


def test_extension_preserves_old_cache_and_binds_new_reservations(database,monkeypatch):
    _,opened=database
    active=r.BUDGET_ID
    monkeypatch.setattr(r,'BUDGET_ID',r.LEGACY_BUDGET_ID)
    make_run(opened,'live');old=r.claim(opened)
    transport,_=transport_fixture(.001)
    asyncio.run(r.execute(opened,old,transport))
    with opened() as db:
        db.execute('UPDATE commerce_review_budgets SET requests_used=20')
        old_budget=dict(db.execute('SELECT * FROM commerce_review_budgets').fetchone())
        old_result=r.get(db,'local',old['id'])
    monkeypatch.setattr(r,'BUDGET_ID',active)
    assert make_run(opened,'live','cache-after-extension')['id']==old['id']
    with opened() as db:
        assert r.status(db)['requests_used']==0
        assert r.status(db)['authorization_history'][0]['requests_used']==20
        new=r.submit(db,'local',r.AnalysisRequest(dataset='pet_fountain',mode='live',force_refresh=True),'new-authorization')
    new=r.claim(opened)
    assert new['provenance']['budget_id']==active
    for _ in range(20):r.reserve_request(opened,new)
    with pytest.raises(UpstreamError):r.reserve_request(opened,new)
    with opened() as db:
        assert dict(db.execute('SELECT * FROM commerce_review_budgets WHERE id=?',(r.LEGACY_BUDGET_ID,)).fetchone())==old_budget
        assert r.get(db,'local',old['id'])==old_result
        assert r.status(db)['requests_used']==20
        assert sum(b['requests_used'] for b in r.status(db)['authorization_history'])==40


def test_old_running_task_cannot_spend_new_grant(database,monkeypatch):
    _,opened=database;active=r.BUDGET_ID
    monkeypatch.setattr(r,'BUDGET_ID',r.LEGACY_BUDGET_ID)
    make_run(opened,'live');old=r.claim(opened)
    with opened() as db:db.execute('UPDATE commerce_review_budgets SET requests_used=20')
    monkeypatch.setattr(r,'BUDGET_ID',active)
    with pytest.raises(UpstreamError):r.reserve_request(opened,old)
    with opened() as db:
        assert db.execute('SELECT COUNT(*) FROM commerce_review_budgets').fetchone()[0]==1
        assert r.status(db)['requests_used']==0


def test_extension_rejects_changed_original_input_and_tenant(database,monkeypatch):
    _,opened=database;active=r.BUDGET_ID
    monkeypatch.setattr(r,'BUDGET_ID',r.LEGACY_BUDGET_ID)
    make_run(opened,'live');old=r.claim(opened);r.recover(opened)
    monkeypatch.setattr(r,'BUDGET_ID',active)
    original=r.load_reviews
    monkeypatch.setattr(r,'load_reviews',lambda name:[item.model_copy(update={'body':'different input'}) for item in original(name)])
    with pytest.raises(c.IdempotencyConflict):make_run(opened,'live','changed')
    monkeypatch.setattr(r,'load_reviews',original)
    with opened() as db:
        with pytest.raises(c.IdempotencyConflict):r.submit(db,'other',r.AnalysisRequest(dataset='pet_fountain',mode='live',force_refresh=True),'other-tenant')
        assert db.execute('SELECT COUNT(*) FROM commerce_review_budgets').fetchone()[0]==1
