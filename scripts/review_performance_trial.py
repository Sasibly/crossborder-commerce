"""Explicitly authorized 2026-11-26 live trials, max 20 extra HTTP attempts.

Uses the deployed persisted budget; fixed idempotency keys prevent rerun spending.
Never reads credentials, creates products, resets counters or changes input.
"""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import statistics
import time
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

BUDGET='qwen35-pet-fountain-performance-20261126'
LEGACY='qwen35-pet-fountain-first-trial-20261125'


def run(url,directory):
    if urlsplit(url).hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('Loopback only')
    with httpx.Client(base_url=url,trust_env=False,timeout=20) as client:
        def request(method,path,body=None,key=None):
            response=client.request(method,path,json=body,headers={'Idempotency-Key':key} if key else {})
            if response.status_code!=200:raise RuntimeError(f'Local API failed: HTTP {response.status_code}; inspect saved task before retrying')
            return response.json()
        assert request('GET','/health')['run_mode']=='mock'
        before=request('GET','/v1/commerce/review-analysis-config')
        assert before['configured'] and before['model']=='qwen3.5-flash' and before['budget_id']==BUDGET
        assert before['request_limit']==20 and before['concurrency']==3
        legacy=next(b for b in before['authorization_history'] if b['id']==LEGACY)
        assert legacy['requests_used']==20
        saved=request('GET','/v1/commerce/review-analyses')
        old=[request('GET','/v1/commerce/review-analyses/'+r['id']) for r in saved if r['mode']=='live' and r['provenance']['budget_id']==LEGACY]
        assert len(old)==2 and all(r['result']['review_count']==10 for r in old)
        trials=[]
        for index in range(1,3):
            cfg=request('GET','/v1/commerce/review-analysis-config')
            if cfg['requests_remaining']<10:break  # Leave unused attempts rather than start an underfunded batch.
            started=time.perf_counter()
            task=request('POST','/v1/commerce/review-analyses',{'dataset':'pet_fountain','mode':'live','force_refresh':True},f'authorized-performance-20261126-round-{index}')
            assert task['provenance']['budget_id']==BUDGET and task['payload']==old[0]['payload']
            print(json.dumps({'round':index,'id':task['id'],'status':task['status']}),flush=True)
            deadline=time.monotonic()+750
            while task['status'] in ('queued','running'):
                if time.monotonic()>deadline:raise TimeoutError('Inspect stored task; no automatic resubmission')
                time.sleep(.5 if time.perf_counter()-started<5 else 1.5)
                task=request('GET','/v1/commerce/review-analyses/'+task['id'])
            trials.append({'analysis_id':task['id'],'observed_http_to_terminal_ms':round((time.perf_counter()-started)*1000,3),**task})
            print(json.dumps({'round':index,'status':task['status'],'requests':task['request_count'],'pipeline_ms':(task['result'] or {}).get('elapsed_ms')}),flush=True)
            if task['status']!='succeeded':break
        after=request('GET','/v1/commerce/review-analysis-config')
        assert next(b for b in after['authorization_history'] if b['id']==LEGACY)==legacy
        assert after['requests_used']<=20
        assert all(request('GET','/v1/commerce/review-analyses/'+r['id'])==r for r in old)
        baseline=[r['result']['elapsed_ms'] for r in old]
        elapsed=[t['result']['elapsed_ms'] for t in trials if t['status']=='succeeded']
        report={'measurement_kind':'observed_live_qwen_on_original_synthetic_reviews','verified_at_utc':datetime.now(timezone.utc).isoformat(),
                'budget_id':BUDGET,'authorization_limit':20,'requests_used_before':before['requests_used'],'requests_used_after':after['requests_used'],
                'real_http_attempts_added':after['requests_used']-before['requests_used'],'old_authorization_preserved':True,'old_results_preserved':True,
                'historical_serial_pipeline_ms':baseline,'new_concurrency3_pipeline_ms':elapsed,
                'historical_serial_median_ms':statistics.median(baseline),'new_pipeline_median_ms':statistics.median(elapsed) if elapsed else None,
                'reduction_vs_historical_median_percent':round((1-statistics.median(elapsed)/statistics.median(baseline))*100,2) if elapsed else None,
                'trials':trials,'authorization_history':after['authorization_history'],
                'scope':'Same original synthetic input and provider/model. Historical comparison across different times, small samples; not controlled provider latency benchmark or semantic accuracy evaluation.'}
        directory.mkdir(parents=True,exist_ok=True)
        path=directory/('live-performance-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]+'.json')
        with path.open('x',encoding='utf-8') as target:json.dump(report,target,ensure_ascii=False,indent=2)
        print(json.dumps({k:v for k,v in report.items() if k!='trials'}|{'report_path':str(path.resolve())},ensure_ascii=False,indent=2),flush=True)
        if not trials or any(t['status']!='succeeded' for t in trials):raise RuntimeError('Trial incomplete; inspect persisted results; do not automatically spend more')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8031')
    parser.add_argument('--report-dir',type=Path,default=Path('docs/evidence/review-performance-runs'))
    args=parser.parse_args();run(args.base_url,args.report_dir)
