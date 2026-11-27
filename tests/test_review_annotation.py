"""Proposal boundaries, draft review decisions and immutable source copies."""
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from xborder_insight import review_annotation as a
from xborder_insight.schemas import ExtractedPoint

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / 'data/demo-evaluation/pet_fountain_comments.json'
HOLDOUT = ROOT / 'data/demo-evaluation/pet_fountain_holdout.json'


@pytest.fixture
def document():
    return a.prepare_demo_sources(DEMO, HOLDOUT)


def annotation(document, review_id, index):
    return next(r for r in document['reviews'] if r['review_id'] == review_id)['annotations'][index]


def approve_first(document, **changes):
    review = document['reviews'][0]; original = review['annotations'][0]
    original.update(changes); original['status'] = 'approved'
    point = a.Annotation.model_validate(original)
    original['approval'] = {'reviewer_id': 'human-test-declaration', 'reviewer_kind': 'human',
                            'reviewed_at': datetime.now(timezone.utc).isoformat(), 'rationale': '人工测试声明，不作真实来源认证',
                            'payload_hash': a.approval_payload_hash(point, document['catalog_version'], review['source_snapshot_hash'])}


def test_all_sources_preserved_no_fabricated_ratings_and_no_automatic_approval(document):
    report = a.lint_document(document)
    assert report['errors'] == [] and report['status'] == 'draft_requires_review'
    assert report['review_count'] == 30 and report['counts']['annotations'] == 55
    assert report['counts']['reviews_without_ratings'] == 20
    assert report['statuses'] == {'draft': 49, 'needs_review': 6}
    assert len(report['review_queue']) == 55
    assert not report['eligible_for_real_quality_claims']
    assert report['external_model_requests'] == report['classifier_predictions'] == 0
    raw_demo = json.loads(DEMO.read_text(encoding='utf-8-sig'))
    raw_holdout = json.loads(HOLDOUT.read_text(encoding='utf-8-sig'))
    assert [r['source_snapshot'] for r in document['reviews']] == raw_demo['comments'] + raw_holdout['cases']


def test_product_consumable_service_and_uncertainty_boundaries(document):
    assert annotation(document, 'pf-syn-pet-001', 2)['label'] == 'service.customer_support'
    assert annotation(document, 'pf-syn-pet-008', 2)['label'] == 'consumable.filter_cost'
    assert annotation(document, 'adv-016', 0)['label'] == 'experience.price_value'
    assert annotation(document, 'adv-016', 0)['status'] == 'needs_review'
    assert annotation(document, 'adv-004', 0)['label'] == 'product.drinking_behavior'
    assert annotation(document, 'adv-005', 0)['label'] == 'product.general_reliability'
    uncertain = annotation(document, 'pf-syn-pet-006', 2)
    assert uncertain['annotation_type'] == 'context' and uncertain['label'] is None
    assert uncertain['assertion'] == 'uncertain'
    assert annotation(document, 'adv-014', 0)['assertion'] == 'reported'
    assert annotation(document, 'adv-011', 0)['assertion'] == 'corrected'


def test_coarse_cleaning_annotations_are_not_forced_into_one_dimension(document):
    first, second = [annotation(document, 'adv-019', i) for i in (0, 1)]
    assert first['label'] == 'product.residue_hygiene'
    assert second['label'] == 'product.assembly_maintenance'
    assert first['original_annotation'] != second['original_annotation']


@pytest.mark.parametrize('change,code', [
    ('evidence', 'evidence_span_mismatch'), ('offset', 'evidence_span_mismatch'),
    ('label', 'unknown_aspect_label'), ('body', 'source_fields_changed'),
    ('snapshot', 'source_snapshot_hash_mismatch'), ('original', 'original_annotation_changed'),
    ('drop', 'source_annotations_dropped_or_duplicated'), ('duplicate_id', 'duplicate_annotation_id'),
    ('promotion', 'synthetic_source_cannot_be_promoted'), ('risk', 'potential_risk_cannot_be_asserted_as_accident'),
    ('source_list_type', 'invalid_source_annotation_snapshot'), ('context', 'context_is_not_an_aspect'),
])
def test_lint_rejects_unsafe_or_inconsistent_annotation_edits(document, change, code):
    review = document['reviews'][0]; point = review['annotations'][0]
    if change == 'evidence': point['evidence']['text'] = '虚构原文'
    if change == 'offset': point['evidence']['end'] = len(review['body']) + 20
    if change == 'label': point['label'] = 'product.unlisted'
    if change == 'body': review['body'] += 'changed'
    if change == 'snapshot': review['source_snapshot']['text'] += 'changed'
    if change == 'original': point['original_annotation']['issue'] = 'changed'
    if change == 'drop': review['annotations'].pop()
    if change == 'duplicate_id': review['annotations'][1]['annotation_id'] = point['annotation_id']
    if change == 'promotion': document['data_kind'] = 'user_provided_unverified'
    if change == 'risk': annotation(document, 'pf-syn-pet-002', 1)['assertion'] = 'observed'
    if change == 'source_list_type': review['source_snapshot']['annotations'] = 42
    if change == 'context': annotation(document, 'pf-syn-pet-006', 2)['label'] = 'product.water_flow'
    report = a.lint_document(document)
    assert report['status'] == 'invalid'
    assert code in {e.get('code') for e in report['errors']}


def test_approval_requires_review_identity_time_and_current_payload(document):
    document['reviews'][0]['annotations'][0]['status'] = 'approved'
    assert 'review_decision_missing' in {e['code'] for e in a.lint_document(document)['errors']}
    approve_first(document)
    assert not a.lint_document(document)['errors']
    document['reviews'][0]['annotations'][0]['polarity'] = 'positive'
    report = a.lint_document(document)
    assert 'stale_or_incomplete_review_decision' in {e['code'] for e in report['errors']}
    assert not report['eligible_for_real_quality_claims']


def test_approved_metadata_never_promotes_synthetic_to_real_or_gold(document):
    approve_first(document)
    report = a.lint_document(document)
    assert report['statuses']['approved'] == 1 and report['status'] == 'draft_requires_review'
    assert not report['eligible_for_real_quality_claims']


def test_review_time_must_include_timezone(document):
    approve_first(document)
    document['reviews'][0]['annotations'][0]['approval']['reviewed_at'] = '2026-11-26T12:00:00'
    assert 'stale_or_incomplete_review_decision' in {e['code'] for e in a.lint_document(document)['errors']}


def test_duplicate_dimension_is_reported_without_dropping_original_points(document):
    report = a.lint_document(document)
    assert report['counts']['annotations'] == 55
    assert any('pf-syn-pet-006' in unit['unit'][0] for unit in report['duplicate_units'])
    assert len(next(r for r in document['reviews'] if r['review_id'] == 'pf-syn-pet-006')['annotations']) == 3


def test_lint_and_preparation_do_not_construct_network_or_database_clients(document, monkeypatch):
    import httpx
    import sqlite3
    def forbidden(*args, **kwargs):raise AssertionError('No model or database permitted')
    monkeypatch.setattr(httpx, 'AsyncClient', forbidden)
    monkeypatch.setattr(sqlite3, 'connect', forbidden)
    assert a.lint_document(document)['status'] == 'draft_requires_review'
    assert a.prepare_demo_sources(DEMO, HOLDOUT)['reviews'] == document['reviews']


def test_namespaced_draft_is_not_accepted_by_production_extraction_contract():
    with pytest.raises(ValueError):
        ExtractedPoint(label='product.leakage', evidence='漏水', polarity='negative')


def test_new_review_preparation_does_not_invent_star_or_source_rights():
    raw = {'category': 'pet_fountain', 'data_kind': 'user_provided_unverified',
           'source_metadata': {}, 'reviews': [{'review_id': 'external-unverified', 'body': '这是一条待核验评论。', 'rating': None}]}
    doc = a.prepare_user_reviews(raw, '0' * 64)
    report = a.lint_document(doc)
    assert report['errors'] == [] and report['counts']['reviews_without_ratings'] == 1
    assert report['counts']['reviews_without_annotations'] == 1
    assert report['warnings'][0]['code'] == 'source_metadata_incomplete'
    assert not report['eligible_for_real_quality_claims']
    assert doc['model_transmission_authorization'] == 'requires_separate_chat_authorization'


def test_document_cannot_grant_external_model_permissions(document):
    document['model_transmission_authorization'] = True
    report = a.lint_document(document)
    assert report['status'] == 'invalid'


def test_preparation_and_lint_are_deterministic_and_do_not_mutate_sources(document):
    before = deepcopy(document)
    assert a.prepare_demo_sources(DEMO, HOLDOUT) == document
    assert a.lint_document(document) == a.lint_document(document)
    assert document == before
    catalog, _ = a.load_catalog()
    assert len(catalog['labels']) == 24
    assert '不是线上标签' in a.render_guide(catalog, a.lint_document(document))
