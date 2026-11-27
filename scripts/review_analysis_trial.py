"""Run the explicitly authorized first Qwen trial through the deployed app budget."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx


def run(url,directory):
    if urlsplit(url).hostname not in ('127.0.0.1','localhost','::1'):raise ValueError('Loopback only')
    with httpx.Client(base_url=url,trust_env=False,timeout=20) as client:
        def request(method,path,body=None,key=None):
            response=client.request(method,path,json=body,headers={'Idempotency-Key':key} if key else {})
            response.raise_for_status();return response.json()
        assert request('GET','/health')['run_mode']=='mock'
        config=request('GET','/v1/commerce/review-analysis-config')
        if not config['configured']:raise ValueError('Private model configuration is incomplete; no model request made')
        run=request('POST','/v1/commerce/review-analyses',{'dataset':'pet_fountain','mode':'live'},'authorized-first-qwen35-pet-fountain-10-reviews')
        print(json.dumps({'analysis_id':run['id'],'status':run['status'],'request_count':run['request_count']}),flush=True)
        deadline=time.monotonic()+750
        while run['status'] in ('queued','running'):
            if time.monotonic()>deadline:raise TimeoutError('Local polling stopped; inspect the saved task before rerunning')
            time.sleep(2)
            run=request('GET','/v1/commerce/review-analyses/'+run['id'])
            print(json.dumps({'status':run['status'],'request_count':run['request_count']}),flush=True)
        config=request('GET','/v1/commerce/review-analysis-config')
        report={'measurement_kind':'observed_live_model_on_synthetic_reviews','fixture_data_kind':'synthetic_samples',
                'verified_at_utc':datetime.now(timezone.utc).isoformat(),'analysis_id':run['id'],'status':run['status'],
                'provenance':run['provenance'],'request_count':run['request_count'],'authorization_requests_used':config['requests_used'],
                'authorization_request_limit':20,'result':run['result'],'error_code':run['error_code'],
                'scope':'No real supplier, payment, fulfilment or market-demand validation; model confidence is not calibrated probability.'}
        assert config['requests_used']<=20
        if run['result']:
            assert run['result']['review_count']==10
            themes=run['result']['themes']
            negative=next((theme for theme in themes if theme['polarity']=='negative'),None)
            if negative:
                existing=request('GET','/v1/commerce/state?include_orders=false')
                candidate=next((candidate for candidate in existing['candidates'] if candidate['source_json'].get('analysis_id')==run['id']),None)
                if candidate is None:
                    candidate=request('POST','/v1/commerce/candidates',{'name':'SIM / 百炼评论联调饮水机','dataset':'pet_fountain','theme_id':negative['theme_id'],'analysis_id':run['id']})
                    decision=request('POST',f"/v1/commerce/candidates/{candidate['id']}/decisions",dict(price_cents=3500,purchase_cny_cents=7000,cny_per_usd='7',logistics_cents=500,payment_bps=300,payment_fixed_cents=30,aftersales_cents=100,acquisition_cents=300,risk='clear',source_note='本地模拟联调成本与风险确认。真实模型仅分析构造评论，无真实供应商、市场需求或合规核验。'))
                    product=request('POST',f"/v1/commerce/decisions/{decision['id']}/draft",{})
                    report['draft_product_id']=product['id']
                report['candidate_id']=candidate['id']
                after=request('GET','/v1/commerce/review-analysis-config')
                assert after['requests_used']==config['requests_used'],'Candidate creation unexpectedly called the model'
                report['candidate_creation_extra_requests']=0
        directory.mkdir(parents=True,exist_ok=True)
        path=directory/('qwen35-first-trial-'+run['id']+'.json')
        if path.exists():
            # Preserve the first observed report; no second submission or budget reset.
            print(json.dumps({'report_already_exists':str(path.resolve())},ensure_ascii=False),flush=True)
        else:
            with path.open('x',encoding='utf-8') as target:json.dump(report,target,ensure_ascii=False,indent=2)
        print(json.dumps({k:v for k,v in report.items() if k not in ('result','provenance')},ensure_ascii=False,indent=2),flush=True)
        print(str(path.resolve()),flush=True)
        if run['status']=='failed':raise RuntimeError('Model trial failed; see saved task and remaining authorization before any retry')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url',default='http://127.0.0.1:8031')
    parser.add_argument('--report-dir',type=Path,default=Path('docs/evidence/review-analysis-runs'))
    args=parser.parse_args();run(args.base_url,args.report_dir)
