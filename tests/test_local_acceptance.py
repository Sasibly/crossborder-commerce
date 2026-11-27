"""Release evidence cannot silently skip checks or expand local/demo scope."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import accept_local as a
from commerce_release_flow import validate_url


def profile():return json.loads((ROOT/'data/acceptance/local_demo_v1.json').read_text(encoding='utf-8'))


def test_fixed_profile_verifies_real_inputs_and_limits():
    p=profile();result=a.validate_profile(p)
    assert result['status']=='passed' and result['reference_qualification']['human_approved_annotations']==0
    assert len(p['categories'])==6 and sum(v['reviews'] for v in p['categories'].values())==200
    assert p['categories']['pet_fountain']['rule']=='v2'
    assert all(v['rule']=='v1' for k,v in p['categories'].items() if k!='pet_fountain')


@pytest.mark.parametrize('mutation',['network','port','hash','escape'])
def test_profile_drift_or_expanded_scope_fails(mutation):
    p=profile()
    if mutation=='network':p['scope']['additional_live_model_calls_allowed']=True
    if mutation=='port':p['scope']['canonical_port']=8027
    if mutation=='hash':p['files'][next(iter(p['files']))]='0'*64
    if mutation=='escape':p['files']['../not-allowed.json']='0'*64
    with pytest.raises(ValueError):a.validate_profile(p)


def make_junit(path,p,extra=''):
    cases=''.join(f'<testcase classname="tests.{name}" name="test_guard" />' for name in p['required_unit_groups'])
    cases+='<testcase classname="tests.test_polarity" name="test_known_gap_died_is_not_a_negative_cue"><skipped type="pytest.xfail" /></testcase>'
    path.write_text('<testsuites><testsuite>'+cases+extra+'</testsuite></testsuites>',encoding='utf-8')


def test_unit_evidence_lists_required_groups_and_known_legacy_xfail(tmp_path):
    p=profile();path=tmp_path/'test.xml';make_junit(path,p)
    result=a.parse_junit(path,p)
    assert result['all_required_groups_present'] and len(result['known_xfailed'])==1
    assert result['passed']==len(p['required_unit_groups'])


@pytest.mark.parametrize('extra',[
    '<testcase classname="tests.other" name="unverified"><skipped /></testcase>',
    '<testcase classname="tests.other" name="failed"><failure /></testcase>',
    '<testcase classname="tests.other" name="error"><error /></testcase>'])
def test_skipped_or_failed_checks_never_count_as_complete(tmp_path,extra):
    p=profile();path=tmp_path/'test.xml';make_junit(path,p,extra)
    with pytest.raises(RuntimeError):a.parse_junit(path,p)


def test_failure_records_not_run_stages_and_preserves_failure_report(tmp_path):
    calls=[]
    def ok():calls.append('ok');return {'status':'passed'}
    def fail():raise ValueError('intentional evidence failure')
    state={'status':'running','sections':[]};path=tmp_path/'report.json'
    result=a.execute_steps([ok,fail,ok,ok,ok],state,path)
    assert result['status']=='failed' and calls==['ok']
    assert [s['status'] for s in result['sections']]==['passed','failed','not_run','not_run','not_run']
    assert json.loads(path.read_text(encoding='utf-8'))['status']=='failed'


def test_missing_acceptance_callback_cannot_silently_pass(tmp_path):
    with pytest.raises(ValueError,match='five'):
        a.execute_steps([lambda:{}]*4,{'sections':[]},tmp_path/'report.json')


@pytest.mark.parametrize('url',['https://127.0.0.1:8031','http://example.com','http://user:pass@localhost:8031','http://localhost:8031/path','http://localhost:8031?redirect=evil'])
def test_http_workflow_refuses_remote_or_ambiguous_targets(url):
    with pytest.raises(ValueError):validate_url(url)


def test_canonical_loopback_target_is_accepted():
    validate_url('http://127.0.0.1:8031')
