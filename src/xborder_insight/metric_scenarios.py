"""Persist server-calculated scenarios; industry exposure cannot become SKU cost."""
import time
from uuid import uuid4
from . import commerce as c, business_metrics as metrics


def save(conn,tenant,body,key):
    c.validate_key(key)
    payload=body.model_dump()
    fingerprint=c.fingerprint(payload)
    with c.transaction(conn):
        c.row(conn,'commerce_candidates',body.candidate_id,tenant)
        existing=conn.execute('SELECT id,fingerprint FROM commerce_metric_scenarios WHERE tenant=? AND request_key=?',(tenant,key)).fetchone()
        if existing:
            if existing['fingerprint']!=fingerprint:
                raise c.IdempotencyConflict('该场景请求已使用其他参数')
            return c.row(conn,'commerce_metric_scenarios',existing['id'],tenant)
        result=metrics.scenario(body.metric_id,body.amount_cents,body.usage)
        result['input_role']='sales_amount' if body.usage=='sales_benchmark_only' else 'loss_per_returned_item'
        result['application']='reference_only' if body.usage=='sales_benchmark_only' else 'optional_simulated_aftersales_cost'
        result['assumption_note']=body.assumption_note
        result['execution_data_kind']='simulation'
        identity=uuid4().hex
        conn.execute('INSERT INTO commerce_metric_scenarios VALUES(?,?,?,?,?,?,?)',
                     (identity,tenant,body.candidate_id,key,fingerprint,c.dump(result),int(time.time())))
        c.record(conn,tenant,'metric_scenario.saved',identity,{'metric_id':body.metric_id,'usage':body.usage})
    return c.row(conn,'commerce_metric_scenarios',identity,tenant)


def cost_snapshot(conn,tenant,identity,candidate_id,cost):
    saved=c.row(conn,'commerce_metric_scenarios',identity,tenant)
    snapshot=saved['snapshot']
    if saved['candidate_id']!=candidate_id:
        raise c.InputInvalid('场景不属于当前候选商品')
    if snapshot['usage']!='simulated_item_loss_scenario' or snapshot['metric_snapshot']['basis']!='item_return_probability':
        raise c.InputInvalid('销售占比行业基准不能作为单件售后成本')
    if snapshot['result_cents']!=cost:
        raise c.InputInvalid('售后成本与选定场景结果不同，请重新选择场景或清除引用')
    return {'scenario_id':identity,**snapshot}
