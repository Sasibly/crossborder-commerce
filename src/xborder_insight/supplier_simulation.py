"""Pure local simulator: no network, email, credentials or real supplier identity."""
import json
import time
from uuid import uuid4
from . import commerce as c

SCENARIOS={'standard':{'purchase_cny_cents':7000,'moq':100,'lead_days':14},
           'delayed':{'purchase_cny_cents':9000,'moq':200,'lead_days':30}}
ALLOWED={'draft':{'rfq_sent','rejected'},'rfq_sent':{'quoted','rejected'},
         'quoted':{'sample_requested','accepted','rejected'},'sample_requested':{'sample_received','rejected'},
         'sample_received':{'accepted','rejected'}}


def read(conn,tenant,identity):
    case=c.row(conn,'commerce_supplier_cases',identity,tenant)
    case['allowed_transitions']=sorted(ALLOWED.get(case['status'],set()))
    case['supplier']={'id':'SIM-SUP-001','name':'虚构供应商 Alpha','data_kind':'simulation'}
    case['quote']={'data_kind':'simulation','currency':'CNY','source':'local_fixture_v1',**SCENARIOS[case['scenario']]}
    case['quote_available']=case['status'] in ('quoted','sample_requested','sample_received','accepted')
    case['history']=[json.loads(r['payload']) for r in conn.execute('SELECT payload FROM commerce_supplier_events WHERE case_id=? ORDER BY version',(identity,))]
    return case


def event(conn,case):
    payload={'status':case['status'],'version':case['version'],'data_kind':'simulation',
             'interaction_kind':'simulated_supplier_response' if case['status'] in ('quoted','sample_received') else 'simulated_workflow_action','source':'local_fixture_v1'}
    conn.execute('INSERT INTO commerce_supplier_events VALUES(?,?,?,?)',(case['id'],case['version'],c.dump(payload),int(time.time())))
    c.record(conn,case['tenant'],'supplier.simulated.'+case['status'],case['id'],{'version':case['version']})


def create(conn,tenant,candidate_id,scenario):
    with c.transaction(conn):
        c.row(conn,'commerce_candidates',candidate_id,tenant)
        if scenario not in SCENARIOS: raise c.InputInvalid('模拟场景不存在')
        identity=uuid4().hex
        conn.execute('INSERT INTO commerce_supplier_cases VALUES(?,?,?,?,?,?,?,?)',(identity,tenant,candidate_id,scenario,'draft',1,'simulation',int(time.time())))
        event(conn,read(conn,tenant,identity))
    return read(conn,tenant,identity)


def advance(conn,tenant,identity,target,expected_version):
    with c.transaction(conn):
        case=read(conn,tenant,identity)
        if case['version']!=expected_version: raise c.IdempotencyConflict('模拟流程已变化，请刷新状态')
        if target not in ALLOWED.get(case['status'],set()): raise c.InvalidStateTransition('不允许的模拟供应商状态变化')
        conn.execute('UPDATE commerce_supplier_cases SET status=?,version=version+1 WHERE id=?',(target,identity))
        event(conn,read(conn,tenant,identity))
    return read(conn,tenant,identity)


def quote_snapshot(conn,tenant,identity,candidate_id):
    case=read(conn,tenant,identity)
    if case['candidate_id']!=candidate_id or not case['quote_available']: raise c.InputInvalid('模拟报价不属于该候选或尚不可用')
    return {'case_id':identity,'case_version':case['version'],'supplier':case['supplier'],'quote':case['quote'],'data_kind':'simulation'}
