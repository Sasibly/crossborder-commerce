"""Offline versioned sources; public estimates never become SKU observations."""
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
from .errors import InputInvalid


def catalog():
    return json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))['records']


def get(identity):
    for record in catalog():
        if record['id']==identity: return deepcopy(record)
    raise InputInvalid('指标版本不存在')


def scenario(identity,amount_cents,usage):
    if type(amount_cents) is not int or not 0<=amount_cents<=100_000_000_000:
        raise InputInvalid('场景金额必须为非负整数分')
    metric=get(identity)
    if metric['allowed_usage']!=usage:
        raise InputInvalid('指标口径与用途不符；行业销售占比不能当作 SKU 退货概率')
    value=int((Decimal(amount_cents)*Decimal(metric['value'])).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    return {'metric_snapshot':metric,'input_cents':amount_cents,'result_cents':value,'usage':usage,
            'result_kind':'benchmark_exposure' if usage=='sales_benchmark_only' else 'simulated_expected_loss',
            'note':'金额为用户场景输入，结果是推算而非项目实测；不自动改写决策成本。'}
