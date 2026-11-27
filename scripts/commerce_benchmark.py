"""Bounded real HTTP baseline against owned loopback processes and disposable DBs."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import hashlib
import json
from importlib.metadata import version
import os
from pathlib import Path
import platform
import socket
import sqlite3
import subprocess
import sys
from tempfile import TemporaryDirectory
import threading
import time
from urllib.parse import urlsplit

import httpx
from commerce_ops_fixtures import seed
from xborder_insight.commerce_ops import latency_summary
from xborder_insight.db.backup import snapshot

ROOT=Path(__file__).resolve().parents[1]


def launch(db,log):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    env=os.environ.copy()
    env.update(RUN_MODE='mock',EMBEDDING_PROVIDER='hash',AUTH_REQUIRED='false',JOB_WORKER_ENABLED='false',
               DB_PATH=str(db),SHOP_TENANT='local',COMMERCE_SECURE_COOKIES='false',COMMERCE_LEGACY_GUEST_CHECKOUT='true',LOG_LEVEL='WARNING',PYTHONUTF8='1')
    process=subprocess.Popen([sys.executable,'-m','uvicorn','xborder_insight.api:app','--app-dir','src',
                              '--host','127.0.0.1','--port',str(port),'--workers','1','--no-access-log'],
                             cwd=ROOT,env=env,stdout=log,stderr=log)
    return process,'http://127.0.0.1:'+str(port)


def measure(client,product,concurrency,samples,write,buyers,order_view='full'):
    statuses=Counter();lock=threading.Lock()
    def request(method,path,**kwargs):
        response=client.request(method,path,**kwargs)
        with lock:statuses[str(response.status_code)]+=1
        response.raise_for_status()
        return response.json()
    def operation(index):
        start=time.perf_counter();error=None
        try:
            if write:
                buyer=buyers[index]
                port=urlsplit(str(client.base_url)).port
                cookie='cb_buyer' if port in (None,80,443) else f'cb_buyer_{port}'
                headers={'Cookie':cookie+'='+buyer['token'],'X-CSRF-Token':buyer['csrf']}
                request('POST','/shop/api/cart',json={'product_id':product,'quantity':1},headers=headers)
                order=request('POST','/shop/api/checkout',json={'address_id':buyer['address_id']},
                              headers=headers|{'Idempotency-Key':f'bench-{concurrency}-{index}'})
                request('POST','/v1/commerce/orders/'+order['id']+'/cancel',json={})
            else:
                page=request('GET','/v1/commerce/orders?limit=30&view='+order_view)
                if len(page['items'])!=30:raise AssertionError('Unexpected page size')
        except Exception as exc:error=type(exc).__name__
        return (time.perf_counter()-start)*1000,error
    start=time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results=list(pool.map(operation,range(samples)))
    elapsed=time.perf_counter()-start
    summary=latency_summary([r[0] for r in results],elapsed)
    errors=Counter(r[1] for r in results if r[1])
    return {'workload':'buyer_cart_checkout_seller_cancel' if write else 'seller_order_page_30',
            'concurrency':concurrency,**summary,'http_requests':sum(statuses.values()),'http_statuses':dict(statuses),
            'errors':sum(errors.values()),'error_types':dict(errors),
            'latency_scope':'one buyer cart+checkout+seller cancel journey (3 sequential HTTP requests)' if write else 'one HTTP request'}


def race(client,product):
    barrier=threading.Barrier(12)
    def buy(index):
        barrier.wait(timeout=10)
        return client.post('/shop/api/orders',json={'product_id':product,'quantity':1},headers={'Idempotency-Key':'race-'+str(index)})
    with ThreadPoolExecutor(max_workers=12) as pool:responses=list(pool.map(buy,range(12)))
    statuses=Counter(r.status_code for r in responses)
    if statuses!={200:3,409:9}:raise AssertionError('Inventory race failed: '+str(statuses))
    for response in responses:
        if response.status_code==200:
            client.post('/v1/commerce/orders/'+response.json()['id']+'/cancel',json={}).raise_for_status()
    return {'requests':12,'available_units':3,'accepted':3,'sold_out':9,'expected_conflicts_excluded_from_latency_errors':True}


def run(orders=1000,samples=120,levels=(1,4,8),order_view='full'):
    if not 30<=orders<=10000 or not 20<=samples<=2000 or not levels or any(not 1<=n<=32 for n in levels):
        raise ValueError('订单范围30–10000，样本20–2000，并发1–32')
    report={'status':'passed','data_kind':'simulation','fixture_data_kind':'simulation',
            'measurement_kind':'observed_local_http_timings','measured_at_utc':datetime.now(timezone.utc).isoformat(),
            'transport':'real HTTP over loopback',
            'order_view':order_view,
            'workers':1,'initial_cancelled_orders_per_level':orders,'warmup_reads_per_level':5,
            'environment':{'os':platform.platform(),'python':platform.python_version(),'sqlite':sqlite3.sqlite_version,
                           'logical_cpu_count':os.cpu_count(),'packages':{name:version(name) for name in ('uvicorn','fastapi','httpx')}},
            'results':[],'integrity':[],'inventory_races':[],
            'limitations':['Closed-loop fixed-count samples, not sustained peak capacity or production QPS.',
                           'No TLS, seller auth, buyer password hashing, real payment or external provider latency in this workload.',
                           'Each write journey uses its own seeded buyer/session/address; existing rate limits remain enabled.',
                           'No public-market statistics are derived from these synthetic orders.',
                           'Each concurrency level starts from the same DB snapshot; its write journey runs after its read phase.']}
    digest=hashlib.sha256()
    for path in sorted((ROOT/'src').rglob('*')):
        if path.suffix in ('.py','.js','.html','.json'):
            digest.update(str(path.relative_to(ROOT)).encode());digest.update(path.read_bytes())
    report['source_sha256']=digest.hexdigest()
    report['harness_sha256']=hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('commerce_ops_fixtures.py').read_bytes()).hexdigest()
    with TemporaryDirectory(prefix='commerce-benchmark-') as directory:
        directory=Path(directory);template=directory/'template.sqlite3';fixture=seed(template,orders=orders,benchmark_buyers=samples)
        for level in levels:
            db=directory/f'level-{level}.sqlite3';snapshot(template,db)
            with (directory/f'level-{level}.log').open('w',encoding='utf-8') as log:
                process,url=launch(db,log)
                try:
                    with httpx.Client(base_url=url,timeout=15,trust_env=False,limits=httpx.Limits(max_connections=40,max_keepalive_connections=32)) as client:
                        deadline=time.monotonic()+20
                        while True:
                            if process.poll() is not None:raise RuntimeError('Owned benchmark server exited during startup')
                            try:
                                client.get('/ready').raise_for_status()
                                # Verify a unique fixture before any mutation; a port race fails closed.
                                products=client.get('/shop/api/products').json()
                                if not any(p['id']==fixture['product_id'] for p in products):raise RuntimeError('Server fixture identity mismatch')
                                break
                            except httpx.HTTPError:
                                if time.monotonic()>deadline:raise RuntimeError('Benchmark server startup timed out')
                                time.sleep(.1)
                        for _ in range(5):client.get('/v1/commerce/orders?limit=30&view='+order_view).raise_for_status()
                        for write in (False,True):
                            result=measure(client,fixture['product_id'],level,samples,write,fixture['benchmark_buyers'],order_view)
                            report['results'].append(result)
                            if result['errors']:report['status']='failed'
                        report['inventory_races'].append({'concurrency_level':level,**race(client,fixture['race_product_id'])})
                        integrity=client.get('/v1/commerce/integrity');integrity.raise_for_status()
                        result=integrity.json();report['integrity'].append(result)
                        if not result['ok']:report['status']='failed'
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:process.wait(timeout=8)
                        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--orders',type=int,default=1000)
    parser.add_argument('--samples',type=int,default=120)
    parser.add_argument('--concurrency',default='1,4,8')
    parser.add_argument('--order-view',choices=['full','summary'],default='full')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError('报告已存在；请换新文件名，保留旧测量结果')
    result=run(args.orders,args.samples,tuple(int(n) for n in args.concurrency.split(',')),args.order_view)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as target:json.dump(result,target,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='passed' else 2


if __name__=='__main__':
    raise SystemExit(main())
