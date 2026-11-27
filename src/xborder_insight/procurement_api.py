from typing import Literal
from fastapi import Depends, Header
from pydantic import Field
from . import commerce as c, business_metrics as metrics, supplier_simulation as suppliers
from .commerce_audit import actor_db


class NewCase(c.Model):
    candidate_id: str
    scenario: Literal['standard','delayed']='standard'


class Transition(c.Model):
    target: Literal['rfq_sent','quoted','sample_requested','sample_received','accepted','rejected']
    expected_version: int=Field(ge=1,strict=True)


class MetricScenario(c.Model):
    metric_id: str
    amount_cents: int=Field(ge=0,le=100_000_000_000,strict=True)
    usage: Literal['sales_benchmark_only','simulated_item_loss_scenario']


class SavedScenario(MetricScenario):
    candidate_id: str
    assumption_note: str=Field(min_length=3,max_length=1000)


from .seller_requests import execute as seller_request


def install(app,open_db,principal):
    from . import metric_scenarios
    from .profit_comparisons import Comparison, save as save_comparison

    @app.post('/v1/commerce/profit-comparisons',tags=['sources'])
    def compare(body:Comparison,idempotency_key:str=Header(alias='Idempotency-Key'),user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return save_comparison(conn,user.tenant_id,body,idempotency_key)

    @app.get('/v1/commerce/profit-comparisons',tags=['sources'])
    def comparisons(candidate_id:str,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            c.row(conn,'commerce_candidates',candidate_id,user.tenant_id)
            ids=conn.execute('SELECT id FROM commerce_profit_comparisons WHERE tenant=? AND candidate_id=? ORDER BY created_at DESC,id DESC LIMIT 20',(user.tenant_id,candidate_id)).fetchall()
            return [c.row(conn,'commerce_profit_comparisons',r['id'],user.tenant_id) for r in ids]

    @app.get('/v1/commerce/profit-comparisons/{identity}',tags=['sources'])
    def comparison(identity:str,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return c.row(conn,'commerce_profit_comparisons',identity,user.tenant_id)

    @app.post('/v1/commerce/metric-scenarios',tags=['sources'])
    def save_scenario(body:SavedScenario,idempotency_key:str=Header(alias='Idempotency-Key'),user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return metric_scenarios.save(conn,user.tenant_id,body,idempotency_key)

    @app.get('/v1/commerce/metric-scenarios',tags=['sources'])
    def scenarios(candidate_id:str,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            c.row(conn,'commerce_candidates',candidate_id,user.tenant_id)
            ids=conn.execute('SELECT id FROM commerce_metric_scenarios WHERE tenant=? AND candidate_id=? ORDER BY created_at DESC,id',(user.tenant_id,candidate_id)).fetchall()
            return [c.row(conn,'commerce_metric_scenarios',r['id'],user.tenant_id) for r in ids]
    @app.get('/v1/commerce/business-metrics',tags=['sources'])
    def catalog(user=Depends(principal)):
        return {'metrics':metrics.catalog(),'supplier_policy':'simulation_only'}

    @app.post('/v1/commerce/metric-scenario',tags=['sources'])
    def scenario(body:MetricScenario,user=Depends(principal)):
        return metrics.scenario(body.metric_id,body.amount_cents,body.usage)

    @app.get('/v1/commerce/supplier-cases',tags=['simulated-suppliers'])
    def cases(user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return [suppliers.read(conn,user.tenant_id,r['id']) for r in conn.execute('SELECT id FROM commerce_supplier_cases WHERE tenant=? ORDER BY created_at,id',(user.tenant_id,))]

    @app.post('/v1/commerce/supplier-cases',tags=['simulated-suppliers'])
    def new(body:NewCase,idempotency_key:str|None=Header(default=None,alias="Idempotency-Key"),user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return seller_request(conn,user.tenant_id,'supplier-cases',idempotency_key,body.model_dump(mode='json'),lambda:suppliers.create(conn,user.tenant_id,body.candidate_id,body.scenario))

    @app.post('/v1/commerce/supplier-cases/{identity}/transition',tags=['simulated-suppliers'])
    def transition(identity:str,body:Transition,user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            return suppliers.advance(conn,user.tenant_id,identity,body.target,body.expected_version)
