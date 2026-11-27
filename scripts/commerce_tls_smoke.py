"""Verify actual HTTPS sessions with an ephemeral CA trusted only by this client."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
from tempfile import TemporaryDirectory
import time

import httpx
from commerce_ops_fixtures import seed
from xborder_insight.config import ROOT_DIR
from xborder_insight.db.connection import connect
from xborder_insight.security import keys


def certificates(directory):
    executable=shutil.which('openssl')
    if not executable:raise RuntimeError('TLS演练需要已安装的OpenSSL；可在项目官方基础镜像容器内执行')
    def command(*args):
        subprocess.run([executable,*args],cwd=directory,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    command('req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj','/CN=Commerce Ephemeral Test CA',
            '-keyout','ca.key','-out','ca.pem','-addext','basicConstraints=critical,CA:TRUE','-addext','keyUsage=critical,keyCertSign,cRLSign')
    command('req','-new','-newkey','rsa:2048','-nodes','-subj','/CN=localhost','-keyout','server.key','-out','server.csr')
    (directory/'server.ext').write_text('basicConstraints=critical,CA:FALSE\nsubjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\nkeyUsage=digitalSignature,keyEncipherment\n',encoding='ascii')
    command('x509','-req','-in','server.csr','-CA','ca.pem','-CAkey','ca.key','-CAcreateserial','-days','1','-out','server.pem','-extfile','server.ext')
    for name in ('ca.key','server.key'):os.chmod(directory/name,0o600)


def run():
    with TemporaryDirectory(prefix='commerce-tls-') as temporary:
        directory=Path(temporary);certificates(directory);db=directory/'tls.sqlite3';fixture=seed(db,orders=0)
        conn=connect(db);owner,_=keys.create(conn,tenant_id='local',rpm_limit=1000)
        operator,_=keys.create(conn,tenant_id='local',role='operator',rpm_limit=1000);conn.close()
        with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        origin='https://127.0.0.1:'+str(port)
        env=os.environ|{'RUN_MODE':'mock','EMBEDDING_PROVIDER':'hash','AUTH_REQUIRED':'true','JOB_WORKER_ENABLED':'false',
                        'COMMERCE_SECURE_COOKIES':'true','DB_PATH':str(db),'SHOP_TENANT':'local','LOG_LEVEL':'WARNING'}
        context=ssl.create_default_context(cafile=str(directory/'ca.pem'))
        with (directory/'server.log').open('wb') as log:
            process=subprocess.Popen([sys.executable,'-m','uvicorn','xborder_insight.api:app','--app-dir','src','--host','127.0.0.1',
                '--port',str(port),'--workers','1','--no-access-log','--ssl-keyfile',str(directory/'server.key'),
                '--ssl-certfile',str(directory/'server.pem')],cwd=ROOT_DIR,env=env,stdout=log,stderr=log)
            try:
                with httpx.Client(base_url=origin,verify=context,trust_env=False,timeout=10) as buyer:
                    deadline=time.monotonic()+20
                    while True:
                        if process.poll() is not None:raise RuntimeError('TLS测试进程启动失败')
                        try:
                            buyer.get('/ready').raise_for_status()
                            products=buyer.get('/shop/api/products').json()
                            if not any(p['id']==fixture['product_id'] for p in products):raise RuntimeError('TLS服务身份不匹配')
                            break
                        except httpx.HTTPError:
                            if time.monotonic()>deadline:raise RuntimeError('TLS启动超时')
                            time.sleep(.1)
                    try:
                        with httpx.Client(base_url=origin,trust_env=False,timeout=5) as untrusted:untrusted.get('/health')
                    except httpx.ConnectError:untrusted_rejected=True
                    else:raise AssertionError('System trust unexpectedly accepted the ephemeral CA')
                    assert buyer.get('/v1/commerce/me').status_code==401
                    probe_env=env|{'COMMERCE_TLS_PORT':str(port),'COMMERCE_TLS_SERVER_NAME':'localhost','COMMERCE_TLS_TRUST_CA_FILE':str(directory/'ca.pem')}
                    subprocess.run([sys.executable,'scripts/commerce_tls_ready.py'],env=probe_env,cwd=ROOT_DIR,check=True,capture_output=True)
                    credentials={'email':'tls-'+secrets.token_hex(6)+'@example.test','password':secrets.token_urlsafe(24)}
                    response=buyer.post('/shop/api/account/register',json=credentials,headers={'Origin':origin});response.raise_for_status()
                    cookie=response.headers['set-cookie'].lower();assert all(s in cookie for s in ('secure','httponly','samesite=lax'))
                    csrf={'X-CSRF-Token':response.json()['csrf'],'Origin':origin}
                    assert buyer.get('/shop/api/account/me').status_code==200
                    assert buyer.post('/shop/api/cart',json={'product_id':fixture['product_id'],'quantity':1},headers={'Origin':origin}).status_code==401
                    buyer.post('/shop/api/cart',json={'product_id':fixture['product_id'],'quantity':1},headers=csrf).raise_for_status()
                    response=buyer.post('/shop/api/addresses',json={'recipient':'Fictional TLS Buyer','line1':'123 Example Street','city':'Seattle','state':'WA','postal_code':'98101'},headers=csrf);response.raise_for_status()
                    response=buyer.post('/shop/api/checkout',json={'address_id':response.json()['id']},headers=csrf|{'Idempotency-Key':'tls-checkout'});response.raise_for_status()
                    order=response.json();oid=order['id']
                    payment={'event_id':'tls-simulated-payment','amount_cents':order['amount_cents']}
                    assert buyer.post('/v1/commerce/orders/'+oid+'/pay',json=payment,headers={'Authorization':'Bearer '+operator}).status_code==403
                    owner_headers={'Authorization':'Bearer '+owner}
                    assert buyer.post('/shop/api/my/orders/'+oid+'/pay',json={}).status_code==401
                    assert buyer.post('/shop/api/my/orders/'+oid+'/pay',json={},headers=csrf|{'Origin':'https://untrusted.example.test'}).status_code==401
                    for _ in range(2):
                        paid=buyer.post('/shop/api/my/orders/'+oid+'/pay',json={},headers=csrf);paid.raise_for_status()
                        assert paid.json()['status']=='paid'
                    with httpx.Client(base_url=origin,verify=context,trust_env=False) as stranger:
                        assert stranger.post('/shop/api/my/orders/'+oid+'/pay',json={}).status_code==401
                        other=stranger.post('/shop/api/account/register',json={'email':'other-'+secrets.token_hex(6)+'@example.test','password':secrets.token_urlsafe(24)},headers={'Origin':origin})
                        other.raise_for_status()
                        assert stranger.post('/shop/api/my/orders/'+oid+'/pay',json={},headers={'X-CSRF-Token':other.json()['csrf'],'Origin':origin}).status_code==404
                    response=buyer.post('/shop/api/my/orders/'+oid+'/refund',json={'reason':'Fictional TLS refund test'},headers=csrf);response.raise_for_status()
                    review='/v1/commerce/refunds/'+response.json()['id']+'/review'
                    body={'approve':True,'note':'Mock unshipped refund through verified HTTPS'}
                    assert buyer.post(review,json=body,headers={'Authorization':'Bearer '+operator}).status_code==403
                    buyer.post(review,json=body,headers=owner_headers).raise_for_status()
                    assert buyer.get('/shop/api/my/orders/'+oid).json()['status']=='refunded'
                    assert buyer.post('/shop/api/account/login',json=credentials,headers={'Origin':'https://untrusted.example.test'}).status_code==401
                    buyer.post('/shop/api/account/logout',json={},headers=csrf).raise_for_status()
                    assert buyer.get('/shop/api/account/me').status_code==401
                    buyer.post('/shop/api/account/login',json=credentials,headers={'Origin':origin}).raise_for_status()
                    assert buyer.get('/shop/api/my/orders/'+oid).status_code==200
                    integrity=buyer.get('/v1/commerce/integrity',headers=owner_headers).json();assert integrity['ok']
                    return {'status':'passed','fixture_data_kind':'simulation','measurement_kind':'observed_local_verified_https',
                            'certificate_validation':'CA chain and hostname verification enabled; private CA trusted only by this HTTP client',
                            'untrusted_ca_rejected':untrusted_rejected,'checks':['Secure cookie sent over HTTPS','CSRF missing rejected',
                                'account login/logout and owned order access','operator payment and refund review rejected','buyer simulated payment replay and owner refund complete',
                                'cross-origin login rejected'],'integrity':integrity,'browser_validation':'not_run',
                            'public_release':'not_verified','scope':'Direct local uvicorn TLS; no system trust changes, public domain or reverse proxy validation.'}
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:process.wait(timeout=8)
                    except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path);args=parser.parse_args()
    if args.output and args.output.exists():raise FileExistsError('请保留旧报告并使用新的文件名')
    report=run()
    if args.output:
        with args.output.open('x',encoding='utf-8') as target:json.dump(report,target,ensure_ascii=False,indent=2)
    print(json.dumps(report,ensure_ascii=False,indent=2))
