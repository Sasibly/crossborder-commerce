"""Two local quotes, bounded deterministic sensitivity cases, explicit adoption."""
import time
from decimal import Decimal
from uuid import uuid4

from pydantic import Field, model_validator

from . import commerce as c, business_metrics, supplier_simulation as suppliers
from .metric_scenarios import cost_snapshot


class Baseline(c.Assumptions):
    # Purchase costs come only from the two selected simulated quotes.
    purchase_cny_cents: None = None
    supplier_quote_id: None = None
    comparison_id: None = None
    comparison_option: None = None


class Stress(c.Model):
    price_cents: int = Field(gt=0,le=100_000_000,strict=True)
    cny_per_usd: Decimal = Field(ge=Decimal('0.0001'),le=100,max_digits=8,decimal_places=4)
    logistics_cents: int = Field(ge=0,le=100_000_000,strict=True)


class Comparison(c.Model):
    candidate_id: str
    quote_ids: list[str] = Field(min_length=2,max_length=2)
    baseline: Baseline
    stress: Stress
    note: str = Field(min_length=3,max_length=1000)

    @model_validator(mode='after')
    def distinct_quotes(self):
        if len(set(self.quote_ids))!=2:
            raise ValueError('请选择两份不同的模拟报价')
        if not self.note.strip():
            raise ValueError('请填写场景假设说明')
        return self


def save(conn,tenant,body:Comparison,key):
    c.validate_key(key)
    fingerprint=c.fingerprint(body.model_dump(mode='json'))
    with c.transaction(conn):
        c.row(conn,'commerce_candidates',body.candidate_id,tenant)
        existing=conn.execute('SELECT id,fingerprint FROM commerce_profit_comparisons WHERE tenant=? AND request_key=?',(tenant,key)).fetchone()
        if existing:
            if existing['fingerprint']!=fingerprint:
                raise c.IdempotencyConflict('比较请求已使用其他参数')
            return c.row(conn,'commerce_profit_comparisons',existing['id'],tenant)
        quotes=[suppliers.quote_snapshot(conn,tenant,q,body.candidate_id) for q in body.quote_ids]
        base=body.baseline.model_dump(mode='json')
        # Check missing costs with a real quote substituted, never interpret null as 0.
        missing=c.evaluate(c.Assumptions(**(base|{'purchase_cny_cents':quotes[0]['quote']['purchase_cny_cents']})))['missing']
        if missing:
            raise c.InputInvalid('比较前请补全成本：'+', '.join(missing))
        stress=body.stress
        if stress.price_cents>body.baseline.price_cents or stress.cny_per_usd>body.baseline.cny_per_usd or stress.logistics_cents<body.baseline.logistics_cents:
            raise c.InputInvalid('压力售价和 CNY/USD 不应高于基线，压力物流费不应低于基线')
        if (stress.price_cents,stress.cny_per_usd,stress.logistics_cents)==(body.baseline.price_cents,body.baseline.cny_per_usd,body.baseline.logistics_cents):
            raise c.InputInvalid('压力场景至少需要一项不利变化')
        metric=business_metrics.get(body.baseline.returns_metric_id) if body.baseline.returns_metric_id else None
        aftersales=cost_snapshot(conn,tenant,body.baseline.aftersales_scenario_id,body.candidate_id,body.baseline.aftersales_cents) if body.baseline.aftersales_scenario_id else None
        changes=[('baseline','基线',{}),('price_stress','仅售价下降',{'price_cents':stress.price_cents}),
                 ('fx_stress','仅汇率承压',{'cny_per_usd':str(stress.cny_per_usd)}),
                 ('logistics_stress','仅物流上涨',{'logistics_cents':stress.logistics_cents}),
                 ('combined_stress','综合压力',stress.model_dump(mode='json'))]
        options=[]
        for quote in quotes:
            baseline_profit=None
            for case,label,overrides in changes:
                inputs=c.Assumptions(**(base|overrides|{'purchase_cny_cents':quote['quote']['purchase_cny_cents'],'supplier_quote_id':quote['case_id']}))
                evaluated=c.evaluate(inputs)
                if case=='baseline': baseline_profit=evaluated['unit_profit_cents']
                options.append({'key':quote['case_id']+':'+case,'case':case,'label':label,
                                'quote_id':quote['case_id'],'evaluation':evaluated,
                                'difference_from_baseline_cents':evaluated['unit_profit_cents']-baseline_profit})
        snapshot={'rule_version':'quote-sensitivity-v1','data_kind':'simulation',
                  'candidate_id':body.candidate_id,'note':body.note,'baseline_inputs':base,
                  'stress_inputs':stress.model_dump(mode='json'),'quotes':quotes,'options':options,
                  'returns_metric_reference':metric,'returns_metric_application':'reference_only',
                  'aftersales_scenario':aftersales,
                  'limitations':['All supplier quotes, costs and workflows are simulated.',
                                 'MOQ and lead time are constraints, not automatically scored or accepted.',
                                 'Per-item contribution uses the saved decision fee assumptions; it is not an order settlement or accounting profit.',
                                 'Scenarios are hypothetical sensitivity inputs, not forecasts or confidence intervals.']}
        for quote in quotes:
            total=quote['quote']['purchase_cny_cents']*quote['quote']['moq']
            quote['minimum_batch_purchase_cny_cents']=total
            quote['minimum_batch_purchase_usd_cents']=c.cents(Decimal(total)/body.baseline.cny_per_usd)
        identity=uuid4().hex
        conn.execute('INSERT INTO commerce_profit_comparisons VALUES(?,?,?,?,?,?,?)',
                     (identity,tenant,body.candidate_id,key,fingerprint,c.dump(snapshot),int(time.time())))
        c.record(conn,tenant,'profit_comparison.saved',identity,{'candidate_id':body.candidate_id})
    return c.row(conn,'commerce_profit_comparisons',identity,tenant)


def decision_reference(conn,tenant,candidate_id,body:c.Assumptions):
    saved=c.row(conn,'commerce_profit_comparisons',body.comparison_id,tenant)
    if saved['candidate_id']!=candidate_id:
        raise c.InputInvalid('利润比较不属于当前候选商品')
    snapshot=saved['snapshot']
    option=next((o for o in snapshot['options'] if o['key']==body.comparison_option),None)
    if option is None:
        raise c.InputInvalid('比较方案不存在')
    expected=c.Assumptions(**option['evaluation']['assumptions'])
    submitted=body.model_copy(update={'comparison_id':None,'comparison_option':None})
    if submitted!=expected:
        raise c.InputInvalid('输入已偏离比较方案，请重新采用方案或清除比较引用')
    quote=next(q for q in snapshot['quotes'] if q['case_id']==option['quote_id'])
    current=suppliers.quote_snapshot(conn,tenant,quote['case_id'],candidate_id)
    if any(current[k]!=quote[k] for k in current):
        raise c.IdempotencyConflict('模拟报价流程已变化，请重新保存比较后采用')
    if body.returns_metric_id and business_metrics.get(body.returns_metric_id)!=snapshot['returns_metric_reference']:
        raise c.IdempotencyConflict('指标版本内容已变化，请重新保存比较后采用')
    return {'comparison_id':saved['id'],'option_key':option['key'],'note':snapshot['note'],
            'rule_version':snapshot['rule_version'],'data_kind':'simulation',
            'selected_option':option,'quote_snapshot':quote,'stress_inputs':snapshot['stress_inputs']}
