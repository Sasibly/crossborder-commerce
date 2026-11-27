"""Development examples, authored separately from the frozen uploaded counterexamples."""
import asyncio
import json

import pytest
from xborder_insight.offline_rules import extract_points, OfflineRuleClient
from xborder_insight.pipeline.extract import extract_many
from xborder_insight.schemas import Review


CASES = [
    ('接缝没有出现漏水，放在书桌上正常使用。', 'leakage', 'positive'),
    ('没两天就开始漏水了。', 'leakage', 'negative'),
    ('没漏水才怪，下面全湿了。', 'leakage', 'negative'),
    ('缝隙渗水把桌布弄湿了。', 'leakage', 'negative'),
    ('No leaking during the weekend.', 'leakage', 'positive'),
    ('It is not noisy in the kitchen.', 'noise', 'positive'),
    ('The fan is quiet, but the motor died suddenly.', 'noise', 'positive'),
    ('The fan is quiet, but the motor died suddenly.', 'pump_life', 'negative'),
    ('充电器并不烫，插头兼容我的手机。', 'compatibility', 'neutral'),
    ('这个底座谈不上安静。', 'noise', 'negative'),
    ('底座静音，办公室里几乎注意不到。', 'noise', 'positive'),
    ('外壳持续嗡嗡响。', 'noise', 'negative'),
    ('清理转角很费力。', 'cleaning', 'negative'),
    ('拆洗只需一小会，非常方便。', 'cleaning', 'positive'),
    ('为了清理储水格需要拆开洗，过程很麻烦。', 'cleaning', 'negative'),
    ('The reservoir is easy to clean.', 'cleaning', 'positive'),
    ('The housing is hard to clean.', 'cleaning', 'negative'),
    ('听说接缝会漏水，我还没有试过。', 'leakage', 'neutral'),
    ('本来怀疑接头漏水，后来发现杯子打翻了。', 'leakage', 'neutral'),
    ('泵运行两周后彻底坏掉。', 'pump_life', 'negative'),
    ('这个出水流量很低。', 'charging_speed', 'negative'),
    ('This unit takes forever to charge.', 'charging_speed', 'negative'),
]


@pytest.mark.parametrize('text,label,expected', CASES)
def test_development_examples(text, label, expected):
    points = extract_points(text, rating=3)
    assert any(p['label'] == label and p['polarity'] == expected for p in points), points
    assert all(p['evidence'] in text for p in points)


@pytest.mark.parametrize('rating', [1, 3, 5])
def test_explicit_negation_and_cleaning_sentiment_override_stars(rating):
    assert next(p for p in extract_points('储水缝没有漏水', rating=rating) if p['label'] == 'leakage')['polarity'] == 'positive'
    assert next(p for p in extract_points('清理污渍特别费劲', rating=rating) if p['label'] == 'cleaning')['polarity'] == 'negative'


def test_nonfailures_and_service_speed_do_not_become_failed_pump_or_charging():
    assert not any(p['label'] == 'pump_life' for p in extract_points('水泵很安静'))
    assert not any(p['label'] == 'charging_speed' for p in extract_points('客服处理得很慢'))
    assert not any(p['label'] == 'pump_life' for p in extract_points('泵不是不工作，而是水流量很小'))


def test_contract_multiline_body_long_evidence_and_three_label_limit():
    review = Review(review_id='dev-long', asin='SYNTHETIC-DEV', rating=5,
                    body='前言' * 180 + '漏水了。\n清洗很困难，外壳裂了，泵坏掉了，还很吵。')
    outcomes, stats = asyncio.run(extract_many(OfflineRuleClient(), [review], grounded=True))
    assert stats.parsed == 1 and stats.repair_attempts == 0
    assert len(outcomes[0].extraction.points) <= 3
    assert all(p.evidence in review.body and len(p.evidence) <= 240 for p in outcomes[0].extraction.points)


def test_candidate_cannot_use_review_id_or_dataset_as_answer_key():
    async def run():
        client = OfflineRuleClient()
        replies = [json.loads((await client.complete('', f'REVIEW_ID: {rid}\nRATING: 3\nTITLE: \nBODY: 储水缝没有漏水')).content) for rid in ('dev-a', 'dev-b')]
        assert replies[0]['points'] == replies[1]['points']
    asyncio.run(run())


def test_aspect_only_in_title_keeps_exact_title_evidence():
    review = Review(review_id='dev-title', asin='SYNTHETIC-DEV', rating=2,
                    title='出水非常慢', body='早晨准备时间不够了。')
    out, stats = asyncio.run(extract_many(OfflineRuleClient(), [review], grounded=True))
    assert stats.parsed == 1 and stats.repair_attempts == 0
    assert out[0].extraction.points[0].evidence == review.title


def test_empty_title_does_not_consume_body_header_as_title_evidence():
    review = Review(review_id='dev-empty', asin='SYNTHETIC-DEV', rating=3, body='今天包装送到了。')
    out, stats = asyncio.run(extract_many(OfflineRuleClient(), [review], grounded=True))
    assert stats.parsed == 1 and not out[0].extraction.points
