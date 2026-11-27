"""Independent LLM analysis and persistent, non-resettable trial authorization."""
import asyncio
from contextlib import contextmanager
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
import time
import httpx
import pytest
from xborder_insight import api, commerce as c, review_analysis as r
from xborder_insight.db import migrate
from xborder_insight.db.connection import connect
from xborder_insight.db.migrations import LATEST
from xborder_insight.schemas import Review
from xborder_insight.errors import FeatureDisabled, UpstreamError
from test_commerce import assumptions
from test_commerce_access import secured


@pytest.fixture
def database(tmp_path,monkeypatch):
    path=tmp_path/'review.sqlite3';db=connect(path);migrate.upgrade(db);db.close()
    monkeypatch.setattr(r,'model_config',lambda:r.ModelConfig('https://llm-test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1','FAKE-TEST-KEY'))
    @contextmanager
    def opened():
        db=connect(path)
        try:yield db
        finally:db.close()
    return path,opened


def make_run(opened,mode='baseline',key='review'):
    with opened() as db:return r.submit(db,'local',r.AnalysisRequest(dataset='pet_fountain',mode=mode),key)


def test_config_does_not_expose_key_or_accept_placeholder(tmp_path,monkeypatch):
    file=tmp_path/'private.env';file.write_text('REVIEW_LLM_BASE_URL=https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1\nREVIEW_LLM_API_KEY=FAKE-TEST-KEY',encoding='utf-8')
    monkeypatch.setenv('REVIEW_CONFIG_PATH',str(file))
    for name in ('REVIEW_LLM_API_KEY','REVIEW_LLM_MODEL','REVIEW_LLM_BASE_URL'):monkeypatch.delenv(name,raising=False)
    assert not r.model_config().ready
    assert 'FAKE-TEST-KEY' not in repr(r.model_config())
    for endpoint in ('http://llm-test.cn-beijing.maas.aliyuncs.com/compatible-mode/v1','https://example.com/compatible-mode/v1','https://llm-test.cn-beijing.maas.aliyuncs.com:bad/compatible-mode/v1'):
        assert not r.ModelConfig(endpoint,'test').ready


def test_baseline_saved_source_and_snapshot_immutability(database):
    path,opened=database;run=make_run(opened);asyncio.run(r.execute(opened,r.claim(opened)))
    with opened() as db:
        result=r.get(db,'local',run['id']);assert result['status'] in ('succeeded','partial')
        assert result['request_count']==0 and result['result']['review_count']==10
        assert result['provenance']['review_data_kind']=='synthetic_samples'
        assert db.execute('SELECT COUNT(*) FROM commerce_review_budgets').fetchone()[0]==0
        theme=result['result']['themes'][0]
        source=r.candidate_source(db,'local',run['id'],'pet_fountain',theme['theme_id'])
        candidate=c.create_candidate(db,'local',c.Candidate(name='SIM saved source',dataset='pet_fountain',theme_id=theme['theme_id'],analysis_id=run['id']),source)
        decision=c.decide(db,'local',candidate['id'],assumptions());product=c.draft(db,'local',decision['id'])
        assert product['snapshot']['candidate']['source_json']['analysis_id']==run['id']
        c.add_stock(db,'local',product['id'],1);c.publish(db,'local',product['id'])
        order=c.checkout(db,'local','saved-source-order',c.Checkout(product_id=product['id'],quantity=1))
        assert order['items'][0]['snapshot']['decision']['candidate']['source_json']['analysis_id']==run['id']
        with pytest.raises(c.NotFound):r.candidate_source(db,'other',run['id'],'pet_fountain',theme['theme_id'])
        with pytest.raises(c.InputInvalid):r.candidate_source(db,'local',run['id'],'air_purifier',theme['theme_id'])
        with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE commerce_review_analyses SET result=? WHERE id=?',('{}',run['id']))
        # The immutable review tables were introduced in schema26. New unrelated
        # migrations must not change the version this protection test crosses.
        with pytest.raises(ValueError):migrate.downgrade(db,25)


def test_submission_replay_scope_and_configuration(database,monkeypatch):
    path,opened=database;first=make_run(opened,'live');assert make_run(opened,'live')['id']==first['id']
    with opened() as db:
        with pytest.raises(c.IdempotencyConflict):r.submit(db,'local',r.AnalysisRequest(dataset='air_purifier'),'review')
        with pytest.raises(c.InvalidStateTransition):r.submit(db,'local',r.AnalysisRequest(dataset='pet_fountain',mode='live'),'second')
        with pytest.raises(c.InputInvalid):r.submit(db,'local',r.AnalysisRequest(dataset='air_purifier',mode='live'),'bad')
        with pytest.raises(c.InputInvalid):r.submit(db,'local',r.AnalysisRequest(dataset='pet_fountain',mode='live',reviews=[Review(review_id='r',asin='a',rating=2,body='noisy')]),'import')
    monkeypatch.setattr(r,'model_config',lambda:r.ModelConfig('',''))
    assert make_run(opened,'live')['id']==first['id']
    with pytest.raises(FeatureDisabled):make_run(opened,'live','missing-key')


def test_live_twenty_requests_include_network_retries(database):
    path,opened=database;make_run(opened,'live');run=r.claim(opened);attempts=[]
    def handler(request):
        payload=json.loads(request.content);attempts.append(payload)
        assert payload['enable_thinking'] is False and payload['model']=='qwen3.5-flash' and payload['max_tokens']==1024
        return httpx.Response(503,json={'error':'temporarily unavailable'})
    asyncio.run(r.execute(opened,run,httpx.MockTransport(handler)))
    with opened() as db:
        saved=r.get(db,'local',run['id']);assert saved['status']=='failed'
        assert len(attempts)==saved['request_count']==r.status(db)['requests_used']==20
        assert len(saved['result']['extractions'])==10
        with pytest.raises(c.InvalidStateTransition):r.submit(db,'local',r.AnalysisRequest(dataset='pet_fountain',mode='live'),'over-budget')
        with pytest.raises(sqlite3.IntegrityError):db.execute('UPDATE commerce_review_budgets SET requests_used=0')


def test_live_grounding_repair_and_usage(database):
    path,opened=database;make_run(opened,'live');run=r.claim(opened);requests=[]
    def handler(request):
        payload=json.loads(request.content);requests.append(payload)
        user=payload['messages'][-1]['content'];identity=user.split('REVIEW_ID: ')[1].split('\n')[0]
        points=[{'label':'noise','polarity':'negative','evidence':'HALLUCINATED EVIDENCE','confidence':.8}] if len(requests)==1 else []
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'review_id':identity,'is_relevant':bool(points),'points':points})},'finish_reason':'stop'}],'usage':{'prompt_tokens':10,'completion_tokens':5}})
    asyncio.run(r.execute(opened,run,httpx.MockTransport(handler)))
    with opened() as db:
        result=r.get(db,'local',run['id']);assert result['status']=='succeeded' and result['request_count']==11
        assert result['result']['repair_attempts']==1 and result['result']['prompt_tokens']==110
        assert all(row['extraction']['points']==[] for row in result['result']['extractions'])
        assert 'FAKE-TEST-KEY' not in c.dump(result)


def test_auth_failure_stops_requests_and_restart_never_repeats(database):
    path,opened=database;make_run(opened,'live');run=r.claim(opened);calls=[]
    def handler(request):calls.append(1);return httpx.Response(401,json={'error':'secret-echo-FAKE-TEST-KEY'})
    asyncio.run(r.execute(opened,run,httpx.MockTransport(handler)))
    with opened() as db:
        result=r.get(db,'local',run['id']);assert len(calls)==1 and result['request_count']==1
        assert 'FAKE-TEST-KEY' not in c.dump(result)
    second=make_run(opened,'live','retry-after-auth');r.claim(opened);r.recover(opened)
    with opened() as db:
        assert r.get(db,'local',second['id'])['error_code']=='interrupted_no_automatic_retry'
        assert r.status(db)['requests_used']==1
    assert r.claim(opened) is None


def test_atomic_budget_across_connections(database):
    path,opened=database;make_run(opened,'live');run=r.claim(opened)
    def reserve(_):
        try:r.reserve_request(opened,run);return True
        except UpstreamError:return False
    with ThreadPoolExecutor(max_workers=8) as executor:results=list(executor.map(reserve,range(30)))
    assert sum(results)==20
    with opened() as db:assert r.get(db,'local',run['id'])['request_count']==20


def test_import_formats_and_invalid_rows():
    body={'review_id':'x','asin':'a','rating':2,'title':'','body':'noisy pump'}
    for format,text in [('jsonl',json.dumps(body)),('csv','review_id,asin,rating,title,body\nx,a,2,,noisy pump')]:
        result=r.import_reviews(r.ImportRequest(format=format,text=text));assert result['count']==1 and result['reviews'][0]['rating']==2
    for text in ('bad-json',json.dumps(body)+'\n'+json.dumps(body),json.dumps(body|{'rating':9})):
        with pytest.raises(c.InputInvalid):r.import_reviews(r.ImportRequest(format='jsonl',text=text))


def test_api_permissions_and_candidate_reads_saved_result(secured,monkeypatch):
    client,path,p,auth=secured;monkeypatch.setattr(r,'model_config',lambda:r.ModelConfig('',''))
    assert client.get('/v1/commerce/review-analysis-config',headers=auth['viewer']).status_code==200
    body={'dataset':'pet_fountain','mode':'live'}
    for role in ('operator','viewer'):
        assert client.post('/v1/commerce/review-analyses',json=body,headers=auth[role]|{'Idempotency-Key':role}).status_code==403
    disabled=client.post('/v1/commerce/review-analyses',json=body,headers=auth['owner']|{'Idempotency-Key':'owner'})
    assert disabled.status_code==403 and disabled.json()['code']=='feature_disabled'
    body['mode']='baseline'
    assert client.post('/v1/commerce/review-analyses',json=body,headers=auth['owner']|{'Idempotency-Key':'cross','Origin':'https://other.example'}).status_code==401
    run=client.post('/v1/commerce/review-analyses',json=body,headers=auth['operator']|{'Idempotency-Key':'baseline'}).json()
    for _ in range(60):
        result=client.get('/v1/commerce/review-analyses/'+run['id'],headers=auth['operator']).json()
        if result['status'] in ('succeeded','partial','failed'):break
        time.sleep(.05)
    assert result['result']['themes']
    assert client.get('/v1/commerce/review-analyses/'+run['id'],headers=auth['other']).status_code==404
    assert client.get('/v1/commerce/review-analyses',headers=auth['other']).json()==[]
    async def forbidden(*args):raise AssertionError('must not recompute analysis')
    from xborder_insight import commerce_api
    monkeypatch.setattr(commerce_api,'evidence',forbidden)
    candidate=client.post('/v1/commerce/candidates',json={'name':'SIM saved source','dataset':'pet_fountain','theme_id':result['result']['themes'][0]['theme_id'],'analysis_id':run['id']},headers=auth['operator'])
    assert candidate.status_code==200,candidate.text
    assert candidate.json()['source_json']['analysis_id']==run['id']
