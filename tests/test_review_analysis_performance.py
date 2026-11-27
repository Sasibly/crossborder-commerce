"""Bounded scheduling, cache validity and cheap progress without external requests."""
import asyncio
from dataclasses import replace
import json
import sqlite3

import httpx
import pytest
from xborder_insight import commerce as c,review_analysis as r
from xborder_insight.errors import FeatureDisabled
from test_review_analysis import database,make_run


def transport_fixture(delay=.02):
    state={'active':0,'peak':0,'calls':0}
    async def handler(request):
        state['calls']+=1;state['active']+=1;state['peak']=max(state['peak'],state['active'])
        try:
            user=json.loads(request.content)['messages'][-1]['content']
            rid=user.split('REVIEW_ID: ')[1].split('\n')[0]
            # Deliberately vary duration so gather must retain the input ordering.
            await asyncio.sleep(delay*(1+int(rid[-1],36)%3))
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'review_id':rid,'is_relevant':False,'points':[]})}}]})
        finally:state['active']-=1
    return httpx.MockTransport(handler),state


def test_bounded_overlap_order_progress_and_timings(database,monkeypatch):
    path,opened=database;make_run(opened,'live');run=r.claim(opened)
    transport,state=transport_fixture()
    seen=[]
    original=r.progress_view
    async def operation():
        task=asyncio.create_task(r.execute(opened,run,transport))
        while not task.done():
            await asyncio.sleep(.01)
            with opened() as db:seen.append(original(db,'local',run['id']))
        await task
    asyncio.run(operation())
    with opened() as db:
        result=r.get(db,'local',run['id'])
        assert result['status']=='succeeded' and state['calls']==10 and state['peak']==3
        assert [v['review_id'] for v in result['result']['extractions']]==[v['review_id'] for v in run['payload']['reviews']]
        progress=[v['progress']['completed'] for v in seen if v['progress']]
        assert progress==sorted(progress) and any(0<p<10 for p in progress)
        assert all('payload' not in v and 'result' not in v for v in seen)
        assert result['result']['execution']['concurrency']==3
        assert len(result['result']['request_attempts'])==10
        assert result['result']['timings']['extraction_ms']>0
        assert result['result']['timings']['request_reservation_ms']>=0


def test_success_reused_without_key_or_remaining_budget_force_explicit(database,monkeypatch):
    path,opened=database;make_run(opened,'live');run=r.claim(opened);transport,state=transport_fixture(.001)
    asyncio.run(r.execute(opened,run,transport))
    with opened() as db:
        db.execute('UPDATE commerce_review_budgets SET requests_used=20')
        previous=r.get(db,'local',run['id'])
    monkeypatch.setattr(r,'model_config',lambda:r.ModelConfig('',''))
    reused=make_run(opened,'live','different-click')
    assert reused['id']==run['id'] and reused['reused_result']
    assert r.claim(opened) is None and state['calls']==10
    with opened() as db:
        assert r.status(db)['requests_used']==20
        assert r.get(db,'local',run['id'])==previous
        with pytest.raises(FeatureDisabled):r.submit(db,'local',r.AnalysisRequest(dataset='pet_fountain',mode='live',force_refresh=True),'explicit-new')


def test_cache_requires_same_input_scope_and_processing_version(database,monkeypatch):
    path,opened=database;make_run(opened,'baseline');run=r.claim(opened);asyncio.run(r.execute(opened,run))
    cached=make_run(opened,'baseline','cache');assert cached['id']==run['id']
    monkeypatch.setattr(r,'PROMPT_VERSION','different-prompt')
    other=make_run(opened,'baseline','new-version');assert other['id']!=run['id'] and other['status']=='queued'
    with opened() as db:
        changed=r.submit(db,'local',r.AnalysisRequest(dataset='pet_fountain',reviews=[r.Review(review_id='import-1',asin='a',rating=2,body='Noisy pump')]),'different-input')
        assert changed['id']!=run['id']
        tenant=r.submit(db,'other',r.AnalysisRequest(dataset='pet_fountain'),'other')
        assert tenant['id']!=run['id']
        refresh=r.submit(db,'local',r.AnalysisRequest(dataset='pet_fountain',force_refresh=True),'refresh')
        assert refresh['id']!=run['id']
        with pytest.raises(c.IdempotencyConflict):r.submit(db,'local',r.AnalysisRequest(dataset='pet_fountain'),'refresh')


def test_lightweight_progress_remains_tenant_bound(database):
    path,opened=database;run=make_run(opened)
    with opened() as db:
        with pytest.raises(c.NotFound):r.progress_view(db,'other',run['id'])
        view=r.progress_view(db,'local',run['id'])
        assert view['status']=='queued' and view['progress'] is None
        assert len(json.dumps(view))<500
