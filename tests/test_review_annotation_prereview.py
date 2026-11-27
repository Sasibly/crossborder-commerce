"""AI draft changes are complete, auditable and never human approvals."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from xborder_insight import review_annotation as a
from xborder_insight.review_annotation_prereview import apply_prereview

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def inputs():
    document = a.prepare_demo_sources(ROOT/'data/demo-evaluation/pet_fountain_comments.json',
                                      ROOT/'data/demo-evaluation/pet_fountain_holdout.json')
    plan = json.loads((ROOT/'data/review-annotation/synthetic_ai_prereview_v1.json').read_text(encoding='utf-8'))
    return document, plan


def test_all_fifty_five_reviewed_preserving_sources_and_no_human_approval(inputs):
    document, plan = inputs; before = deepcopy(document)
    output, report = apply_prereview(document, plan)
    assert document == before
    assert [r['source_snapshot'] for r in output['reviews']] == [r['source_snapshot'] for r in document['reviews']]
    assert [r['rating'] for r in output['reviews']] == [r['rating'] for r in document['reviews']]
    assert report['counts'] == {'reviewed_annotations':55,'decisions':{'retain':37,'needs_human':2,'revise':14,'context_only':2},
                               'candidate_reference_units':50,'context_items':2,'pending_human_items':2,'human_approved_annotations':0}
    assert all(a['approval'] is None and a['status'] in ('draft','needs_review') for r in output['reviews'] for a in r['annotations'])
    assert report['reviewer_kind'] == 'ai' and not report['eligible_for_real_quality_claims']
    assert report['validation']['errors'] == []
    assert report['validation']['statuses'] == {'draft':53,'needs_review':2}


def test_real_boundary_changes_and_context_only_exclusions(inputs):
    output, report = apply_prereview(*inputs)
    points = {a['annotation_id']:a for r in output['reviews'] for a in r['annotations']}
    assert points['fixed-regression/adv-003/0']['label'] == 'product.assembly_maintenance'
    corrected = points['fixed-regression/adv-010/0']
    assert corrected['annotation_type'] == 'context' and corrected['label'] is None
    assert corrected['assertion'] == 'corrected' and corrected['polarity'] == 'neutral'
    reference = report['reference_candidate']
    assert {p['annotation_id'] for p in reference['pending_human_items']} == {'demo/pf-syn-pet-001/2','demo/pf-syn-pet-002/1'}
    assert {c['annotation_id'] for c in reference['contexts']} == {'demo/pf-syn-pet-006/2','fixed-regression/adv-010/0'}
    included = {identity for unit in reference['units'] for identity in unit['annotation_ids']}
    assert 'demo/pf-syn-pet-001/2' not in included and 'fixed-regression/adv-010/0' not in included
    assert not reference['automatic_training_or_gold_export'] and not reference['eligible_for_real_quality_claims']


def test_multiple_evidences_merge_as_one_unit_and_day_night_remain_scoped(inputs):
    output, report = apply_prereview(*inputs)
    unit = next(u for u in report['reference_candidate']['units'] if u['review_id']=='pf-syn-pet-006')
    assert len(unit['annotation_ids']) == len(unit['evidences']) == 2
    scoped = [u for u in report['reference_candidate']['units'] if u['review_id']=='pf-syn-pet-003' and u['label']=='product.noise']
    assert len(scoped) == 2 and all(u['scope_notes'] for u in scoped)


@pytest.mark.parametrize('change', ['base','catalog','payload','missing','duplicate','unknown','human','naive_time','invalid_evidence'])
def test_stale_partial_forged_or_invalid_plan_fails_atomically(inputs,change):
    document, plan = inputs; before = deepcopy(document)
    if change=='base':plan['base_document_hash']='0'*64
    if change=='catalog':plan['catalog_version']='unknown'
    if change=='payload':plan['items'][0]['expected_payload_hash']='0'*64
    if change=='missing':plan['items'].pop()
    if change=='duplicate':plan['items'][-1]=deepcopy(plan['items'][0])
    if change=='unknown':plan['items'][0]['annotation_id']='unknown'
    if change=='human':plan['reviewer_kind']='human'
    if change=='naive_time':plan['reviewed_at']='2026-11-26T12:00:00'
    if change=='invalid_evidence':
        plan['items'][0].update(decision='revise',patch={'evidence':{'text':'不存在的引文','start':0,'end':6}})
    with pytest.raises(ValueError):apply_prereview(document,plan)
    assert document==before


@pytest.mark.parametrize('field', ['approval','status','original_annotation','source_index','model_transmission_authorization'])
def test_ai_patch_cannot_change_protected_fields(inputs,field):
    document, plan = inputs
    plan['items'][0].update(decision='revise',patch={field:'forged'})
    with pytest.raises(ValueError,match='proposed'):apply_prereview(document,plan)


def test_ai_cannot_overwrite_human_reviewed_record(inputs):
    from test_review_annotation import approve_first
    document,plan=inputs;approve_first(document)
    plan['base_document_hash']=a.checksum(a.AnnotationDocument.model_validate(document).model_dump(mode='json'))
    with pytest.raises(ValueError,match='human decision'):apply_prereview(document,plan)


def test_reproducible_and_no_network_or_database_clients(inputs,monkeypatch):
    import httpx
    import sqlite3
    def forbidden(*args,**kwargs):raise AssertionError('No external client or DB')
    monkeypatch.setattr(httpx,'AsyncClient',forbidden)
    monkeypatch.setattr(sqlite3,'connect',forbidden)
    first=apply_prereview(*inputs);second=apply_prereview(*inputs)
    assert first==second
    assert first[1]['external_model_requests']==first[1]['database_writes']==0
