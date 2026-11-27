"""Counterexample ingestion must preserve split, ambiguity and rating assumptions."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path

import httpx
import pytest
from xborder_insight import review_holdout_eval as h

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data/demo-evaluation/pet_fountain_holdout.json'
RULES = ROOT / 'data/demo-evaluation/pet_fountain_holdout_rules.json'
ORIGINAL = ROOT / 'data/demo-evaluation/pet_fountain_comments.json'


def loaded():
    return json.loads(SOURCE.read_text(encoding='utf-8-sig')), json.loads(RULES.read_text(encoding='utf-8'))


def test_all_twenty_cases_and_raw_annotations_preserved_without_mutating_source():
    data, policy = loaded(); saved = deepcopy(data)
    reference = h.prepare_holdout(data, policy)
    assert data == saved and len(reference['reviews']) == 20
    assert reference['raw_annotation_count'] == 25
    assert reference['annotation_dispositions'] == {'taxonomy_gap': 17, 'needs_review': 2, 'mapped': 6}
    assert reference['scored_reference_units'] == 6
    assert [r['source_original'] for r in reference['reviews']] == data['cases']
    assert all(r['rating_provenance'] == 'evaluation_assumption_not_source_rating' for r in reference['reviews'])


def test_price_and_component_ambiguity_never_promoted_to_pump_or_filter_truth():
    data, policy = loaded(); ref = h.prepare_holdout(data, policy)
    for identity in ('adv-005', 'adv-016'):
        case = next(r for r in ref['reviews'] if r['review']['review_id'] == identity)
        assert case['annotations'][0]['disposition'] == 'needs_review'
        assert not case['reference_units']
    failed_pump = next(r for r in ref['reviews'] if r['review']['review_id'] == 'adv-012')
    assert failed_pump['reference_units'][0]['label'] == 'pump_life'


@pytest.mark.parametrize('change', ['real', 'wrong_split', 'duplicate_across_chunks', 'missing_rule', 'false_evidence', 'rating'])
def test_source_scope_and_binding_fail_closed(change):
    data, policy = loaded()
    if change == 'real': data['synthetic'] = False
    if change == 'wrong_split': data['split'] = 'training'
    if change == 'duplicate_across_chunks': data['cases'][15]['id'] = data['cases'][0]['id']
    if change == 'missing_rule': del policy['rules']['adv-001:0']
    if change == 'false_evidence': data['cases'][0]['expected_annotations'][0]['evidence'] = '虚构证据'
    if change == 'rating': data['cases'][0]['rating'] = 1
    with pytest.raises(ValueError): h.prepare_holdout(data, policy)


def test_changed_source_hash_rejected_before_execution(tmp_path):
    changed = tmp_path / 'changed.json'; changed.write_bytes(SOURCE.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='hash'):
        asyncio.run(h.run_holdout(changed, RULES, ORIGINAL))


@pytest.mark.parametrize('kind',['v1','v2'])
def test_network_disabled_repeated_report_identical_and_rating_sensitivity_explicit(monkeypatch,kind):
    def forbidden(*args, **kwargs): raise AssertionError('No external clients allowed')
    monkeypatch.setattr(httpx, 'AsyncClient', forbidden)
    monkeypatch.setenv('RUN_MODE', 'live')
    from xborder_insight import llm
    monkeypatch.setattr(llm, 'build_llm_client', forbidden)
    first = asyncio.run(h.run_holdout(SOURCE, RULES, ORIGINAL,kind))
    second = asyncio.run(h.run_holdout(SOURCE, RULES, ORIGINAL,kind))
    assert first == second
    assert first['external_model_requests'] == first['database_writes'] == 0
    assert first['primary_assumed_rating'] == 3 and not first['actual_ratings_provided']
    assert [r['assumed_rating'] for r in first['rating_sensitivity']] == [1, 3, 5]
    assert not first['blind_test'] and not first['overall_comment_label_scored']
    assert not first['eligible_for_real_quality_claims']
    assert '非盲测' in h.render_holdout_text(first)


def test_original_demo_overlap_normalizes_spacing_and_punctuation(tmp_path):
    original = json.loads(ORIGINAL.read_text(encoding='utf-8-sig'))
    data, _ = loaded()
    original['comments'][0]['comment_id'] = data['cases'][0]['id']
    original['comments'][0]['text'] = '  ' + data['cases'][0]['text'].replace('，', ', ') + '\n'
    path = tmp_path / 'original.json'; path.write_text(json.dumps(original), encoding='utf-8')
    report = asyncio.run(h.run_holdout(SOURCE, RULES, path))
    assert data['cases'][0]['id'] in report['overlap_with_original_demo']['review_ids']
    assert data['cases'][0]['id'] in report['overlap_with_original_demo']['normalized_text_case_ids']
