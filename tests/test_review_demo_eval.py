"""Independent cases for partial-reference scoring and offline-only execution."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest

from xborder_insight import review_demo_eval as e

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/demo-evaluation/pet_fountain_comments.json'
RULES = ROOT / 'data/demo-evaluation/pet_fountain_rules.json'


def fixture():
    data = {'synthetic': True, 'annotator_type': 'simulated', 'category': '宠物饮水机',
            'comments': [{'comment_id': 'x', 'rating': 5, 'text': '没有漏水。暂未漏水。客服很慢。',
                          'synthetic': True, 'annotator_type': 'simulated', 'annotations': [
                              {'issue': '无漏水', 'sentiment': '正面', 'evidence': '没有漏水'},
                              {'issue': '无漏水', 'sentiment': '正面', 'evidence': '暂未漏水'},
                              {'issue': '客服慢', 'sentiment': '负面', 'evidence': '客服很慢'}]}]}
    rubric = {'schema_version': 'pet-demo-rubric-v1', 'category': 'pet_fountain',
              'reference_kind': 'developer_defined_demo_reference_not_human_gold',
              'rules': {'无漏水': {'disposition': 'mapped', 'label': 'leakage', 'reason': '否定故障'},
                        '客服慢': {'disposition': 'taxonomy_gap', 'reason': '服务未覆盖'}}}
    return data, rubric


def prediction(polarity='positive', evidence='没有漏水', label='leakage'):
    return {'label': label, 'polarity': polarity, 'evidence': evidence, 'confidence': .9}


def test_duplicate_annotations_and_predictions_count_once_and_preserve_evidence():
    data, rubric = fixture(); original = deepcopy(data)
    ref = e.prepare_reference(data, rubric)
    assert data == original and ref['raw_annotation_count'] == 3
    assert ref['scored_reference_units'] == 1
    assert ref['reviews'][0]['reference_units'][0]['evidences'] == ['暂未漏水', '没有漏水']
    result = e.score_predictions(ref, [{'review_id': 'x', 'status': 'parsed', 'points': [
        prediction(), prediction(evidence='暂未漏水')]}])
    assert result['metrics'] == {'tp': 1, 'fp': 0, 'fn': 0, 'precision': 1, 'recall': 1, 'f1': 1}
    assert result['counts']['duplicate_scoped_predictions'] == 1


def test_negated_failure_wrong_polarity_is_fp_and_fn_without_rating_override():
    data, rubric = fixture(); ref = e.prepare_reference(data, rubric)
    result = e.score_predictions(ref, [{'review_id': 'x', 'status': 'parsed', 'points': [prediction('negative')]}])
    assert result['metrics']['tp'] == 0 and result['metrics']['fp'] == result['metrics']['fn'] == 1
    assert result['reviews'][0]['nonnegative_controls'][0]['negative_false_alarm']


def test_missing_or_unparsed_prediction_remains_false_negative():
    data, rubric = fixture(); ref = e.prepare_reference(data, rubric)
    for rows in ([], [{'review_id': 'x', 'status': 'unparsed', 'points': []}]):
        result = e.score_predictions(ref, rows)
        assert result['metrics']['fn'] == 1 and result['counts']['unparsed_reviews'] == 1
        assert result['metrics']['precision'] is None and result['metrics']['f1'] == 0


def test_outside_reference_not_silently_scored_as_negative_truth():
    data, rubric = fixture(); ref = e.prepare_reference(data, rubric)
    result = e.score_predictions(ref, [{'review_id': 'x', 'status': 'parsed', 'points': [
        prediction(), prediction('negative', '客服很慢', 'charging_speed')]}])
    assert result['metrics']['tp'] == 1 and result['metrics']['fp'] == 0
    assert result['counts']['unscored_predictions'] == 1
    assert result['reviews'][0]['unscored_predictions'][0]['point']['label'] == 'charging_speed'


def test_invalid_evidence_cannot_earn_true_positive_and_valid_alternative_can():
    data, rubric = fixture(); ref = e.prepare_reference(data, rubric)
    bad = prediction(evidence='虚构原文')
    result = e.score_predictions(ref, [{'review_id': 'x', 'status': 'parsed', 'points': [bad]}])
    assert result['metrics']['fp'] == result['metrics']['fn'] == 1
    assert result['counts']['invalid_prediction_points'] == 1
    # A longer exact excerpt is valid; scoring does not require verbatim reference equality.
    result = e.score_predictions(ref, [{'review_id': 'x', 'status': 'parsed', 'points': [
        bad, prediction(evidence=data['comments'][0]['text'])]}])
    assert result['metrics']['tp'] == 1 and result['metrics']['fp'] == 0


def test_contradictory_reference_polarities_are_quarantined():
    data, rubric = fixture()
    data['comments'][0]['annotations'][1]['sentiment'] = '负面'
    ref = e.prepare_reference(data, rubric)
    assert ref['reviews'][0]['blocked_polarity_conflicts'] == ['leakage']
    assert ref['scored_reference_units'] == 0
    assert e.score_predictions(ref, [])['metrics']['f1'] is None


@pytest.mark.parametrize('change', ['real', 'mixed', 'duplicate', 'missing_rule', 'bad_evidence', 'unknown_label'])
def test_invalid_or_unmapped_source_rejected(change):
    data, rubric = fixture()
    if change == 'real': data['synthetic'] = False
    if change == 'mixed': data['category'] = '混合'
    if change == 'duplicate': data['comments'].append(deepcopy(data['comments'][0]))
    if change == 'missing_rule': del rubric['rules']['无漏水']
    if change == 'bad_evidence': data['comments'][0]['annotations'][0]['evidence'] = '虚构'
    if change == 'unknown_label': rubric['rules']['无漏水']['label'] = 'not-a-label'
    with pytest.raises(ValueError): e.prepare_reference(data, rubric)


def test_prediction_identity_mismatch_or_duplicates_rejected():
    data, rubric = fixture(); ref = e.prepare_reference(data, rubric)
    for ids in (['unknown'], ['x', 'x']):
        with pytest.raises(ValueError):
            e.score_predictions(ref, [{'review_id': identity, 'status': 'parsed', 'points': []} for identity in ids])


def test_hash_binding_detects_changed_demo_source(tmp_path):
    copy = tmp_path / 'changed.json'; copy.write_bytes(SOURCE.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='hash'): e.load_demo(copy, RULES)


@pytest.mark.parametrize('kind',['v1','v2'])
def test_offline_report_reproducible_and_no_network_factory(monkeypatch,kind):
    def forbidden(*args, **kwargs): raise AssertionError('No external client permitted')
    monkeypatch.setattr(httpx, 'AsyncClient', forbidden)
    monkeypatch.setenv('RUN_MODE', 'live')
    from xborder_insight import llm
    monkeypatch.setattr(llm, 'build_llm_client', forbidden)
    first = asyncio.run(e.run_demo(SOURCE, RULES,kind)); second = asyncio.run(e.run_demo(SOURCE, RULES,kind))
    assert first == second
    assert first['external_model_requests'] == first['database_writes'] == 0
    assert first['reference']['annotation_dispositions'] == {'mapped': 9, 'taxonomy_gap': 18, 'needs_review': 3}
    assert first['reference']['scored_reference_units'] == 9
    assert len(first['predictions']) == 10 and not first['eligible_for_real_quality_claims']
    assert '非真实评论' in e.render_text(first)
    assert json.loads(json.dumps(first)) == first
