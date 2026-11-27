"""Replay recorded outputs with artificial latency. Never use a real model or key."""
import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime,timezone
import json
from pathlib import Path
import statistics
import sys
from tempfile import TemporaryDirectory
import time
from uuid import uuid4

import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from xborder_insight import review_analysis as r
from xborder_insight.db import migrate
from xborder_insight.db.connection import connect


async def measure(directory,recorded,concurrency,delay):
    path=Path(directory)/(str(uuid4())+'.sqlite3');db=connect(path);migrate.upgrade(db);db.close()
    @contextmanager
    def opened():
        db=connect(path)
        try:yield db
        finally:db.close()
    original_config,original_concurrency=r.model_config,r.CONCURRENCY
    state={'calls':0,'active':0,'peak':0}
    fixtures={row['review_id']:row['extraction'] for row in recorded['extractions']}
    async def handler(request):
        state['calls']+=1;state['active']+=1;state['peak']=max(state['peak'],state['active'])
        try:
            user=json.loads(request.content)['messages'][-1]['content']
            rid=user.split('REVIEW_ID: ')[1].split('\n')[0]
            await asyncio.sleep(delay)
            return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(fixtures[rid])}}]})
        finally:state['active']-=1
    try:
        r.CONCURRENCY=concurrency
        r.model_config=lambda:r.ModelConfig('https://llm-benchmark.cn-beijing.maas.aliyuncs.com/compatible-mode/v1','FAKE-NONNETWORK-KEY')
        with opened() as db:submitted=r.submit(db,'local',r.AnalysisRequest(dataset='pet_fountain',mode='live'),'benchmark')
        run=r.claim(opened);started=time.perf_counter()
        await r.execute(opened,run,httpx.MockTransport(handler))
        elapsed=(time.perf_counter()-started)*1000
        with opened() as db:
            saved=r.get(db,'local',submitted['id']);assert saved['status']=='succeeded'
            assert [row['extraction'] for row in saved['result']['extractions']]==[row['extraction'] for row in recorded['extractions']]
            start=time.perf_counter();cached=r.submit(db,'local',r.AnalysisRequest(dataset='pet_fountain',mode='live'),'repeat-click')
            cache_ms=(time.perf_counter()-start)*1000
            assert cached['id']==run['id'] and cached['reused_result'] and r.status(db)['requests_used']==10
        return {'concurrency':concurrency,'wall_ms':round(elapsed,3),'reused_result_ms':round(cache_ms,3),
                'mock_http_requests':state['calls'],'peak_in_flight':state['peak'],'parsed_count':saved['result']['parsed_count'],
                'timings':saved['result']['timings']}
    finally:r.model_config=original_config;r.CONCURRENCY=original_concurrency


async def main(args):
    recorded=json.loads(args.fixture.read_text(encoding='utf-8'))['result']
    with TemporaryDirectory(prefix='review-performance-') as directory:
        cases=[]
        for _ in range(args.repeats):
            for concurrency in (1,3):cases.append(await measure(directory,recorded,concurrency,args.delay_ms/1000))
    serial=statistics.median(case['wall_ms'] for case in cases if case['concurrency']==1)
    parallel=statistics.median(case['wall_ms'] for case in cases if case['concurrency']==3)
    result={'measurement_kind':'observed_local_replay_with_simulated_network_latency','real_model_requests':0,
            'verified_at_utc':datetime.now(timezone.utc).isoformat(),'review_count':10,'fixture':'recorded model extractions from synthetic pet_fountain reviews',
            'artificial_delay_per_request_ms':args.delay_ms,'repeats_per_configuration':args.repeats,'cases':cases,
            'median_serial_ms':serial,'median_concurrency3_ms':parallel,'wall_time_reduction_percent':round((1-parallel/serial)*100,2),
            'scope':'Scheduling comparison with identical recorded outputs and artificial latency, not a new Alibaba service latency or semantic-quality measurement.'}
    args.report_dir.mkdir(parents=True,exist_ok=True)
    path=args.report_dir/('review-performance-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]+'.json')
    with path.open('x',encoding='utf-8') as target:json.dump(result,target,ensure_ascii=False,indent=2)
    print(json.dumps(result|{'report_path':str(path.resolve())},ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture',type=Path,default=Path('docs/evidence/review-analysis-runs/qwen35-first-trial-78520694502f44ce8e4d728e8f469975.json'))
    parser.add_argument('--delay-ms',type=float,default=120)
    parser.add_argument('--repeats',type=int,default=3)
    parser.add_argument('--report-dir',type=Path,default=Path('docs/evidence/review-performance-runs'))
    args=parser.parse_args()
    if not 1<=args.repeats<=10 or not 0<args.delay_ms<=2000:parser.error('repeats=1..10; delay-ms=0..2000 (exclusive of zero)')
    asyncio.run(main(args))
