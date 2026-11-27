"""Start, inspect, verify and stop the existing loopback-only Docker deployment."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import httpx

ROOT=Path(__file__).resolve().parents[1]
COMPOSE=['docker','compose','--project-directory',str(ROOT),'-f',str(ROOT/'compose.yaml'),'-p','crossborder-commerce']


def prepare_review_config():
    destination=ROOT/'.env.review-analysis'
    if destination.exists():
        if not destination.is_file():raise ValueError('.env.review-analysis必须是文件，请按评论分析说明配置')
        return
    template=ROOT/'.env.review-analysis.example'
    with destination.open('x',encoding='utf-8') as target:
        target.write(template.read_text(encoding='utf-8'))


def command(args,*,timeout=120):
    result=subprocess.run(args,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
    if result.returncode:
        raise RuntimeError('命令失败：'+' '.join(args[:5])+'\n'+(result.stderr or result.stdout)[-1800:])
    return result.stdout.strip()


def compose(*args,timeout=120):return command([*COMPOSE,*args],timeout=timeout)


def loopback_url(ports):
    for bindings in ports.values():
        for binding in bindings or []:
            if binding.get('HostIp') not in ('127.0.0.1','::1'):
                raise ValueError('本地部署工具拒绝操作非loopback端口映射')
    bindings=ports.get('8000/tcp') or []
    if not bindings:raise ValueError('应用没有可验证的本机端口映射')
    binding=bindings[0];port=int(binding['HostPort'])
    if not 1<=port<=65535:raise ValueError('端口无效')
    host='127.0.0.1' if binding['HostIp']=='127.0.0.1' else '[::1]'
    return 'http://'+host+':'+str(port)


def validate_config(config):
    services=config.get('services',{})
    for service in services.values():
        if service.get('network_mode')=='host':raise ValueError('本地入口不接受host网络模式')
        for port in service.get('ports',[]):
            if port.get('host_ip') not in ('127.0.0.1','::1'):raise ValueError('启动前检查：所有发布端口必须仅绑定本机')
    ports={}
    for port in services.get('app',{}).get('ports',[]):
        key=str(port['target'])+'/'+port.get('protocol','tcp')
        ports.setdefault(key,[]).append({'HostIp':port['host_ip'],'HostPort':str(port['published'])})
    return loopback_url(ports)


def inspect():
    cid=compose('ps','-q','app')
    if not cid:raise RuntimeError('应用未运行，请先执行 local-commerce.cmd start')
    template='{"state":{{json .State.Status}},"health":{{json .State.Health.Status}},"ports":{{json .NetworkSettings.Ports}},"image":{{json .Image}},"mounts":{{json .Mounts}}}'
    info=json.loads(command(['docker','inspect','--format',template,cid]))
    url=loopback_url(info['ports'])
    volumes=[m['Name'] for m in info['mounts'] if m.get('Type')=='volume' and m.get('Destination')=='/app/data']
    return {'state':info['state'],'health':info['health'],'base_url':url,'image':info['image'],'data_volumes':volumes,
            'workbench':url+'/workbench','shop':url+'/shop','scope':'local_machine_only','fixture_data_kind':'simulation'}


def ready(url,timeout=45):
    deadline=time.monotonic()+timeout
    with httpx.Client(base_url=url,timeout=3,trust_env=False) as client:
        while True:
            try:
                health=client.get('/health');health.raise_for_status()
                if health.json().get('run_mode')!='mock':raise ValueError('拒绝向非mock实例写入演示数据')
                response=client.get('/ready');response.raise_for_status()
                return response.json()
            except httpx.HTTPError:
                if time.monotonic()>=deadline:raise RuntimeError('本机应用就绪检查超时')
                time.sleep(.25)


def save_report(report,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    path=directory/('local-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8]+'.json')
    with path.open('x',encoding='utf-8') as target:json.dump(report,target,ensure_ascii=False,indent=2)
    return str(path.resolve())


def verify(directory):
    status=inspect();url=status['base_url'];readiness=ready(url)
    if readiness.get('auth')!='disabled':raise ValueError('此入口用于compose.yaml的本地演示；受保护配置请使用其独立预检')
    checks=[]
    preflight=json.loads(compose('exec','-T','app','python','scripts/commerce_preflight.py','--profile','local'))
    if preflight['status']!='passed':raise RuntimeError('本地配置检查失败')
    checks.append({'name':'local_configuration','result':preflight})
    # This exercises the real deployed listener, not an in-process TestClient.
    smoke=json.loads(compose('exec','-T','app','python','scripts/commerce_smoke.py','--base-url','http://127.0.0.1:8000'))
    checks.append({'name':'deployed_http_transaction','result':smoke})
    oid=smoke['order_id']
    with httpx.Client(base_url=url,timeout=10,trust_env=False) as client:
        before=client.get('/v1/commerce/orders/'+oid);before.raise_for_status();before=before.json()
        summary=client.get('/v1/commerce/orders?view=summary&limit=30');summary.raise_for_status()
        if not summary.json()['items']:raise RuntimeError('摘要订单列表为空')
        if any('snapshot' in row for row in summary.json()['items']):raise RuntimeError('摘要列表意外包含完整快照')
    backup=json.loads(compose('exec','-T','app','python','scripts/commerce_live_snapshot.py'))
    if backup['status']!='passed':raise RuntimeError('当前部署数据库恢复验证失败')
    checks.append({'name':'current_deployment_backup_restore','result':backup})
    compose('restart','--timeout','10','app')
    compose('up','-d','--no-build','--wait','--wait-timeout','45',timeout=60)
    ready(url)
    with httpx.Client(base_url=url,timeout=10,trust_env=False) as client:
        after=client.get('/v1/commerce/orders/'+oid);after.raise_for_status();after=after.json()
        if before!=after:raise RuntimeError('容器重启后订单内容发生变化')
        integrity=client.get('/v1/commerce/integrity');integrity.raise_for_status();integrity=integrity.json()
        if not integrity['ok']:raise RuntimeError('业务一致性检查存在异常')
    checks.append({'name':'controlled_restart_persistence','result':{'status':'passed','order_id':oid,
                   'order_status':after['status'],'line_count':len(after['items']),'full_order_preserved':True}})
    checks.append({'name':'business_integrity','result':integrity})
    result={'status':'passed','scope':'local_machine_only','fixture_data_kind':'simulation',
            'verified_at_utc':datetime.now(timezone.utc).isoformat(),'deployment':inspect(),'checks':checks,
            'notes':['Verification creates a fictional buyer/order and performs a controlled container restart.',
                     'Backup and restored DB remain in the existing local data volume; no working DB overwrite.',
                     'Public hosting, cloud/domain configuration and off-site disaster recovery are outside this acceptance scope.']}
    path=save_report(result,directory);result['report_path']=path
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['deploy','start','status','verify','stop','logs'])
    parser.add_argument('--skip-build',action='store_true')
    parser.add_argument('--base-image',default='mcr.microsoft.com/devcontainers/python:3.13')
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports/local')
    args=parser.parse_args()
    try:
        if args.action in ('start','deploy'):
            prepare_review_config()  # Empty credentials on first install; never overwrite a key.
            try:command(['docker','info','--format','{{.ServerVersion}}'],timeout=10)
            except (RuntimeError,subprocess.TimeoutExpired):command(['docker','desktop','start','--timeout','45'],timeout=55)
            validate_config(json.loads(compose('config','--format','json')))
            if not args.skip_build:compose('build','--build-arg','PYTHON_IMAGE='+args.base_image,timeout=600)
            compose('up','-d','--no-build','--wait','--wait-timeout','45',timeout=60)
            status=inspect();ready(status['base_url'])
            compose('exec','-T','app','python','scripts/seed_commerce.py')
            result={'status':'started',**inspect()}
            if args.action=='deploy':result=verify(args.report_dir)
        elif args.action=='status':
            result=inspect();result['readiness']=ready(result['base_url'])
        elif args.action=='verify':result=verify(args.report_dir)
        elif args.action=='stop':compose('stop','--timeout','10');result={'status':'stopped','data_volumes':'preserved'}
        else:print(compose('logs','--tail','60','app'));return 0
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,RuntimeError,subprocess.TimeoutExpired) as exc:
        print(json.dumps({'status':'failed','action':args.action,'error':str(exc)},ensure_ascii=False,indent=2))
        return 2


if __name__=='__main__':raise SystemExit(main())
