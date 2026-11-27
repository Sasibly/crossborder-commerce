"""Apply an auditable AI draft review without changing human approval or source facts."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
from typing import Literal

from pydantic import Field

from .review_annotation import (
    Model, AnnotationDocument, approval_payload_hash, checksum, lint_document,
    CATALOG_PATH,
)

PATCH_FIELDS = {'annotation_type', 'label', 'polarity', 'assertion', 'evidence', 'scope_note'}


class ReviewItem(Model):
    annotation_id: str
    expected_payload_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    decision: Literal['retain', 'revise', 'context_only', 'needs_human']
    rationale: str = Field(min_length=1, max_length=2000)
    patch: dict = Field(default_factory=dict)


class ReviewPlan(Model):
    schema_version: Literal['annotation-ai-prereview-v1']
    reviewer_kind: Literal['ai']
    reviewer_id: str = Field(min_length=1)
    reviewed_at: datetime
    base_document_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    catalog_version: str
    items: list[ReviewItem] = Field(min_length=1)


def apply_prereview(value, proposal, catalog_path=CATALOG_PATH):
    original_report = lint_document(value, catalog_path)
    if original_report['status'] == 'invalid':raise ValueError('Source draft is invalid')
    document = AnnotationDocument.model_validate(value)
    plan = ReviewPlan.model_validate(proposal)
    if not plan.reviewer_id.strip() or plan.reviewed_at.utcoffset() is None:
        raise ValueError('AI identity and timezone-aware review time are required')
    normalized = document.model_dump(mode='json')
    if checksum(normalized) != plan.base_document_hash or document.catalog_version != plan.catalog_version:
        raise ValueError('Stale base document or catalog version')
    indexed = {a.annotation_id: (r, a) for r in document.reviews for a in r.annotations}
    requested = [item.annotation_id for item in plan.items]
    if len(set(requested)) != len(requested) or set(requested) != set(indexed):
        raise ValueError('Every annotation must have exactly one review item')
    # Validate the whole plan first. Partial/forged reviews must not produce an output document.
    for item in plan.items:
        review, point = indexed[item.annotation_id]
        if point.status not in ('draft', 'needs_review') or point.approval is not None:
            raise ValueError('AI review cannot overwrite a human decision')
        if item.expected_payload_hash != approval_payload_hash(point, document.catalog_version, review.source_snapshot_hash):
            raise ValueError('Stale annotation payload')
        if not item.rationale.strip() or set(item.patch) - PATCH_FIELDS:
            raise ValueError('Only proposed annotation fields may be patched')
        if item.decision == 'retain' and item.patch:
            raise ValueError('A retain decision cannot contain changes')
        if item.decision == 'revise' and not item.patch:
            raise ValueError('A revise decision needs a patch')
    output = deepcopy(normalized)
    output_index = {a['annotation_id']: (r, a) for r in output['reviews'] for a in r['annotations']}
    audit, decisions = [], Counter()
    for item in plan.items:
        review, point = output_index[item.annotation_id]
        before = deepcopy(point)
        point.update(deepcopy(item.patch))
        point['status'] = 'needs_review' if item.decision == 'needs_human' else 'draft'
        point['review_reason'] = 'AI预审，非人工审批：' + item.rationale
        if item.decision == 'context_only' and point['annotation_type'] != 'context':
            raise ValueError('Context-only decision requires a context annotation')
        decisions[item.decision] += 1
        audit.append({'annotation_id': item.annotation_id, 'decision': item.decision,
                      'rationale': item.rationale, 'before': before, 'after': deepcopy(point)})
    after_report = lint_document(output, catalog_path)
    if after_report['status'] == 'invalid':raise ValueError('Proposed output fails annotation lint')
    assert [r['source_snapshot'] for r in normalized['reviews']] == [r['source_snapshot'] for r in output['reviews']]
    contexts, pending, groups = [], [], {}
    for item in plan.items:
        review, point = output_index[item.annotation_id]
        if item.decision == 'needs_human':
            pending.append({'review_id': review['review_id'], 'body': review['body'], **deepcopy(point)})
        elif point['annotation_type'] == 'context':
            contexts.append({'review_id': review['review_id'], **deepcopy(point)})
        else:
            key = (review['review_id'], point['label'], point['polarity'], point['assertion'])
            unit = groups.setdefault(key, {'review_id': review['review_id'], 'body': review['body'],
                                          'label': point['label'], 'polarity': point['polarity'],
                                          'assertion': point['assertion'], 'annotation_ids': [],
                                          'evidences': [], 'scope_notes': []})
            unit['annotation_ids'].append(point['annotation_id'])
            if point['evidence'] not in unit['evidences']:unit['evidences'].append(deepcopy(point['evidence']))
            if point['scope_note'] and point['scope_note'] not in unit['scope_notes']:unit['scope_notes'].append(point['scope_note'])
    reference = {'reference_kind': 'ai_prereviewed_demo_candidate_not_human_gold',
                 'data_kind': output['data_kind'], 'catalog_version': output['catalog_version'],
                 'developer_visible': True, 'blind_test': False, 'human_approved_annotations': 0,
                 'eligible_for_real_quality_claims': False, 'automatic_training_or_gold_export': False,
                 'classifier_predictions': 0, 'units': list(groups.values()), 'contexts': contexts,
                 'pending_human_items': pending,
                 'scope': 'Only a versioned proposal for local annotation/contract development; not classifier accuracy or real demand evidence.'}
    result = {'schema_version': 'annotation-ai-prereview-result-v1', 'reviewer_kind': 'ai',
              'reviewer_id': plan.reviewer_id, 'reviewed_at': plan.reviewed_at.isoformat(),
              'base_document_hash': plan.base_document_hash, 'plan_hash': checksum(plan.model_dump(mode='json')),
              'output_document_hash': checksum(output), 'counts': {'reviewed_annotations': len(audit),
              'decisions': dict(decisions), 'candidate_reference_units': len(groups), 'context_items': len(contexts),
              'pending_human_items': len(pending), 'human_approved_annotations': 0},
              'validation': after_report, 'audit': audit, 'reference_candidate': reference,
              'eligible_for_real_quality_claims': False, 'external_model_requests': 0, 'database_writes': 0}
    return output, result


def render_report(result):
    lines = ['宠物饮水机全部标注AI预审', 'AI预审不是人工审批；未调用百炼、未改变线上标签或V2。',
             '原文、原标注、缺失评分和来源类型全部保留；修改在新草稿中，逐项记录before/after。',
             '候选参考仅供本地标注/契约开发，不能当作人审金标准、真实准确率或市场需求证据。',
             '摘要：' + str(result['counts']), '', '逐项预审：']
    for item in result['audit']:
        lines += [item['annotation_id'] + ' / ' + item['decision'], item['rationale'],
                  '  原拟议：' + str({k: item['before'][k] for k in ('label', 'polarity', 'assertion')}),
                  '  新拟议：' + str({k: item['after'][k] for k in ('label', 'polarity', 'assertion')}),
                  '  证据：' + item['after']['evidence']['text'], '']
    return '\n'.join(lines)
