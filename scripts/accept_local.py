"""Single local-only delivery acceptance. Never invokes a live review model."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts')]
PROFILE = ROOT/'data/acceptance/local_demo_v1.json'
HEADINGS = ['1. 固定数据与验收范围','2. 自动测试、权限与缓存','3. 六品类分类回归','4. 买卖家闭环、备份与重启','5. 交付材料与完整性']


def save(path, value):
    with Path(path).open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)


def validate_profile(profile, root=ROOT):
    if profile['schema_version']!='local-demo-acceptance-v1':raise ValueError('Unsupported acceptance profile')
    scope=profile['scope']
    if (scope['deployment']!='local_machine_only' or scope['trade_mode']!='mock'
            or scope['canonical_port']!=8031 or scope['additional_live_model_calls_allowed'] is not False
            or scope['real_world_quality_claims'] is not False):raise ValueError('Acceptance scope expanded unexpectedly')
    for relative, expected in profile['files'].items():
        path=(root/relative).resolve()
        if not path.is_relative_to(root.resolve()) or path.suffix not in ('.json','.jsonl','.py'):
            raise ValueError('Invalid pinned file path')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('Frozen input/version changed: '+relative)
    from xborder_insight.taxonomy import LABEL_KEYS
    from xborder_insight.db.migrations import LATEST
    if set(profile['production_label_keys'])!=LABEL_KEYS:raise ValueError('Production taxonomy changed')
    # Preserve the frozen v1 input profile. Explicitly verify the sole additive
    # QA migration rather than silently replacing that historical schema value.
    extension=root/'src/xborder_insight/db/migrations/m0027_seller_requests.py'
    schema_ok=(scope['schema_version']==26 and LATEST==27 and
               hashlib.sha256(extension.read_bytes()).hexdigest()=='00c8f107dfacecc0a1c88d786476f888f4914710533456ba9be0486db495619f')
    if not schema_ok or profile['annotation_catalog_stage']!='annotation_draft_not_production_taxonomy':
        raise ValueError('Database or annotation scope changed')
    return {'status':'passed','pinned_files':len(profile['files']),'profile_sha256':hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest(),
            'scope':scope,'runtime_schema_version':LATEST,'schema_extension':'m0027_seller_requests',
            'reference_qualification':profile['reference_qualification']}


def parse_junit(path, profile):
    tree=ET.parse(path);cases=tree.findall('.//testcase')
    groups={name:0 for name in profile['required_unit_groups']};failed=[];allowed=[];unverified=[]
    for case in cases:
        module=case.get('classname','').split('.')[-1];name=case.get('name','')
        if module in groups:groups[module]+=1
        if case.find('failure') is not None or case.find('error') is not None:failed.append(module+'::'+name)
        skipped=case.find('skipped')
        if skipped is not None:
            if (module==profile['allowed_xfail']['module'] and name==profile['allowed_xfail']['name']
                    and skipped.get('type')=='pytest.xfail'):allowed.append(module+'::'+name)
            else:unverified.append(module+'::'+name)
    if not cases or failed or unverified or not all(groups.values()):
        raise RuntimeError('Test evidence incomplete or failed: '+str({'failed':failed,'unverified':unverified,'required_groups':groups}))
    return {'status':'passed','total':len(cases),'passed':len(cases)-len(allowed),'known_xfailed':allowed,
            'required_groups':groups,'junit':str(path),'all_required_groups_present':True}


def unit_checks(folder, profile):
    temp_root=(ROOT.parent/'tmp').resolve();temp_root.mkdir(exist_ok=True)
    scratch=temp_root/('accept-'+uuid4().hex)
    if scratch.exists() or not scratch.resolve().is_relative_to(temp_root):raise ValueError('Unsafe pytest scratch path')
    env=os.environ.copy();env.update(PYTHONUTF8='1',TEMP=str(temp_root),TMP=str(temp_root),
        RUN_MODE='mock',EMBEDDING_PROVIDER='hash',REVIEW_LLM_API_KEY='',REVIEW_LLM_BASE_URL='',
        REVIEW_CONFIG_PATH=str(folder/'disabled-review-config.env'))
    junit=folder/'tests.xml';log=folder/'tests.log'
    with log.open('x',encoding='utf-8') as stream:
        result=subprocess.run([sys.executable,'-m','pytest','-o','addopts=','-ra','--tb=short','-p','no:cacheprovider',
                              '--basetemp',str(scratch),'--junitxml',str(junit)],cwd=ROOT,env=env,
                              stdout=stream,stderr=subprocess.STDOUT,text=True,timeout=420)
    if result.returncode:raise RuntimeError('Unit/contract suite failed; see '+str(log))
    return parse_junit(junit,profile)


async def classify(profile, folder):
    from run_eval import load_gold,score
    from xborder_insight.llm import MockLLMClient
    from xborder_insight.offline_rules import OfflineRuleClient
    from xborder_insight.pipeline.extract import extract_many
    from xborder_insight.pipeline.ingest import load_reviews
    from xborder_insight.review_demo_eval import run_demo
    from xborder_insight.review_holdout_eval import run_holdout
    gold=load_gold();rows={}
    for dataset,expected in profile['categories'].items():
        reviews=load_reviews(dataset)
        client=OfflineRuleClient() if expected['rule']=='v2' else MockLLMClient()
        try:outcomes,stats=await extract_many(client,reviews,grounded=True)
        finally:await client.aclose()
        metrics=score(outcomes,gold)
        assert len(reviews)==expected['reviews'] and stats.parsed==expected['expected_parsed']
        assert {k:metrics[k] for k in ('tp','fp','fn')}==expected['expected_counts'],dataset+' count drift'
        assert metrics['error_cases']==expected['expected_error_cases'],dataset+' error-location drift'
        rows[dataset]={'status':'passed_fixed_regression','rule':expected['rule'],'analysis_support':expected['scope'],
                       'workflow_supported':True,'real_quality_claim_supported':False,'parsed':stats.parsed,
                       'metrics':metrics,'limitations':expected['limitation']}
    base=ROOT/'data/demo-evaluation'
    demo=await run_demo(base/'pet_fountain_comments.json',base/'pet_fountain_rules.json','v2')
    fixed=await run_holdout(base/'pet_fountain_holdout.json',base/'pet_fountain_holdout_rules.json',base/'pet_fountain_comments.json','v2')
    for name,result in [('demo',demo),('fixed_regression',fixed)]:
        assert {k:result['scoring']['metrics'][k] for k in ('tp','fp','fn')}==profile['pet_reference_expected'][name]
    result={'status':'passed','reference_kind':'synthetic/project-legacy reference, not verified human gold',
            'categories':rows,'pet_partial_references':{'demo':demo['scoring'],'fixed_regression':fixed['scoring']},
            'external_model_requests':0,'total_corpus_reviews':sum(r['metrics']['reviews'] for r in rows.values())}
    save(folder/'category-regression.json',result)
    return result


def qualified_reference(profile, folder):
    from xborder_insight.review_annotation import prepare_demo_sources
    from xborder_insight.review_annotation_prereview import apply_prereview
    base=ROOT/'data/demo-evaluation'
    source=prepare_demo_sources(base/'pet_fountain_comments.json',base/'pet_fountain_holdout.json')
    plan=json.loads((ROOT/'data/review-annotation/synthetic_ai_prereview_v1.json').read_text(encoding='utf-8'))
    _,review=apply_prereview(source,plan);ref=review['reference_candidate'];qualification=profile['reference_qualification']
    assert len(ref['units'])==qualification['ai_candidate_aspect_units']
    assert {p['annotation_id'] for p in ref['pending_human_items']}==set(qualification['excluded_annotation_ids'])
    assert not ref['eligible_for_real_quality_claims'] and ref['human_approved_annotations']==0
    result={'status':'passed_demo_qualification','counts':review['counts'],'exclusions':qualification['excluded_annotation_ids'],
            'candidate_kind':ref['reference_kind'],'human_approved':0,'scored_as_model_accuracy':False}
    save(folder/'reference-qualification.json',result)
    return result


def doc_checks(profile, root=ROOT):
    count=0
    for relative in profile['delivery_documents']:
        path=root/relative;text=path.read_text(encoding='utf-8')
        for link in re.findall(r'\]\(([^)]+)\)',text):
            if '://' in link or link.startswith('#'):continue
            if not (path.parent/link.split('#')[0]).exists():raise ValueError('Broken local documentation link in '+relative+': '+link)
            count+=1
    deploy=(root/'docs/LOCAL-DEPLOYMENT.md').read_text(encoding='utf-8')
    if 'schema26' not in deploy or 'accept-local.cmd' not in deploy:raise ValueError('Current delivery instructions missing')
    return {'status':'passed','documents':profile['delivery_documents'],'local_links_checked':count}


def execute_steps(callbacks, state, report_path):
    if len(callbacks)!=len(HEADINGS):raise ValueError('Exactly five acceptance stages are required')
    for heading, callback in zip(HEADINGS,callbacks):
        started=time.perf_counter()
        try:
            value=callback()
            state['sections'].append({'heading':heading,'status':'passed','elapsed_seconds':round(time.perf_counter()-started,3),'result':value})
        except Exception as exc:
            state['sections'].append({'heading':heading,'status':'failed','error_type':type(exc).__name__,'error':str(exc)[:2000]})
            state['sections'].extend({'heading':name,'status':'not_run'} for name in HEADINGS[len(state['sections']):])
            state['status']='failed'
            break
    else:state['status']='passed'
    # Unique report directory; this file is created once even after a failure.
    save(report_path,state)
    return state


def run(folder):
    import commerce_local as local
    from commerce_release_flow import run as flow
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=False)
    profile=json.loads(PROFILE.read_text(encoding='utf-8'))
    state={'schema_version':'local-acceptance-report-v1','status':'running','scope':profile['scope'],
           'verified_at_utc':datetime.now(timezone.utc).isoformat(),'sections':[],
           'report_path':str(folder/'report.json'),'external_model_requests_allowed':False}
    deployment={};budgets=[];original_tasks=[]
    def frozen():
        value=validate_profile(profile);value['annotation_qualification']=qualified_reference(profile,folder);return value
    def infrastructure_and_flow():
        import httpx
        status=local.inspect();local.ready(status['base_url'])
        if status['base_url']!='http://127.0.0.1:8031':raise ValueError('Canonical instance mismatch')
        with httpx.Client(base_url=status['base_url'],trust_env=False,timeout=10) as client:
            readiness=client.get('/ready').json()
            if readiness.get('auth')!='disabled':raise ValueError('Use the explicit local demo deployment')
            identity=client.get('/v1/commerce/me').json()
            if identity['tenant']!='local' or not identity['shop_matches_tenant']:raise ValueError('Seller/shop tenant mismatch')
            cfg=client.get('/v1/commerce/review-analysis-config').json();budgets.extend(cfg['authorization_history'])
            existing=client.get('/v1/commerce/review-analyses').json()
            if any(item['status'] in ('queued','running') for item in existing):
                raise ValueError('Analysis task active; preserve it and run acceptance after completion')
            for item in existing:
                original_tasks.append(client.get('/v1/commerce/review-analyses/'+item['id']).json())
        flow_evidence={}
        try:flow(status['base_url'],folder.name,flow_evidence)
        finally:save(folder/'seller-buyer-flow.json',flow_evidence)
        ops=local.verify(folder/'operations')
        if ops['status']!='passed':raise RuntimeError('Backup/restart acceptance failed')
        backup=next(c['result'] for c in ops['checks'] if c['name']=='current_deployment_backup_restore')
        assert backup['schema_version']==profile['scope']['schema_version']
        deployment.update(ops['deployment'])
        with httpx.Client(base_url=status['base_url'],trust_env=False,timeout=10) as client:
            assert client.get('/v1/commerce/review-analysis-config').json()['authorization_history']==budgets
            for old in original_tasks:assert client.get('/v1/commerce/review-analyses/'+old['id']).json()==old
            order_id=flow_evidence['order_id'];restarted=client.get('/v1/commerce/orders/'+order_id).json()
            assert restarted['status']=='refunded' and len(restarted['items'])==6
        return {'status':'passed','flow':flow_evidence,'operations':ops,'old_analysis_rows_preserved':len(original_tasks),
                'authorization_history_unchanged':True,'external_model_requests_added':0,'deployment':deployment}
    def materials():
        evidence=doc_checks(profile);validate_profile(profile)
        evidence.update(frozen_inputs_rechecked=True,support_matrix='category-regression.json',
                        data_scope='Demo acceptance only; real analysis quality and public release are outside this delivery.')
        return evidence
    callbacks=[frozen,lambda:unit_checks(folder,profile),lambda:asyncio.run(classify(profile,folder)),infrastructure_and_flow,materials]
    result=execute_steps(callbacks,state,folder/'report.json')
    lines=['CrossBorder 本机统一验收：'+result['status'],'范围：固定合成/项目既有数据、本机8031、模拟交易；无新增百炼请求。']
    for section in result['sections']:
        lines.append(section['heading']+'：'+section['status'])
        if section['status']=='failed':lines.append(section.get('error',''))
    if result['status']=='passed':
        lines+=['六品类交易链路通过；宠物饮水机使用V2，其他五类保持有限质量的V1基线。',
                '品类F1只用于固定数据回归，不是新数据效果保证；24标签/AI参考候选未作为生产标签或人工金标准。',
                '闭环新建虚构商品已下架，订单/分析等历史保留；备份恢复到新文件，未替换工作库。']
    (folder/'report.txt').write_text('\n'.join(lines),encoding='utf-8')
    return result


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir',type=Path,default=ROOT/'reports/local-acceptance')
    args=parser.parse_args()
    output=args.report_dir/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid4().hex[:8])
    result=run(output)
    print(json.dumps({'status':result['status'],'report':str(output/'report.json'),'text_report':str(output/'report.txt'),
                      'sections':[{'heading':x['heading'],'status':x['status']} for x in result['sections']]},ensure_ascii=False,indent=2))
    raise SystemExit(0 if result['status']=='passed' else 2)
