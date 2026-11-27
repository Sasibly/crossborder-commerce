"""Local annotation preparation/linting. No extractor, network client or commerce DB."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CATALOG_PATH = Path(__file__).resolve().parents[2] / 'data/review-annotation/pet_fountain_schema_v1.json'
POLARITIES = {'正面': 'positive', '负面': 'negative', '中性': 'neutral'}


def checksum(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def load_catalog(path=CATALOG_PATH):
    catalog = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if catalog['schema_version'] != 'pet-annotation-catalog-v1' or catalog['category'] != 'pet_fountain':
        raise ValueError('Unsupported annotation catalog')
    return catalog, 'pet-annotation-' + checksum(catalog)[:16]


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Evidence(Model):
    text: str = Field(min_length=1, max_length=4000)
    start: int = Field(ge=0, strict=True)
    end: int = Field(gt=0, strict=True)


class Approval(Model):
    reviewer_id: str = Field(min_length=1, max_length=100)
    reviewer_kind: Literal['human']
    reviewed_at: datetime
    rationale: str = Field(min_length=1, max_length=2000)
    payload_hash: str = Field(pattern=r'^[0-9a-f]{64}$')


class Annotation(Model):
    annotation_id: str = Field(min_length=1, max_length=160)
    source_index: int | None = Field(default=None, ge=0, strict=True)
    original_annotation: dict | None = None
    annotation_type: Literal['aspect', 'context'] = 'aspect'
    label: str | None = None
    polarity: Literal['positive', 'negative', 'neutral']
    assertion: Literal['observed', 'uncertain', 'reported', 'corrected', 'potential_risk'] = 'observed'
    evidence: Evidence
    status: Literal['draft', 'needs_review', 'approved', 'rejected'] = 'draft'
    review_reason: str = Field(min_length=1, max_length=2000)
    scope_note: str = Field(default='', max_length=1000)
    approval: Approval | None = None


class SourceBatch(Model):
    batch_id: str
    file_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    source_kind: Literal['synthetic_samples', 'user_provided_unverified']
    metadata: dict


class AnnotatedReview(Model):
    review_id: str = Field(min_length=1, max_length=100)
    body: str = Field(min_length=1, max_length=4000)
    rating: int | None = Field(default=None, ge=1, le=5, strict=True)
    source_batch_id: str
    source_format: Literal['demo_comments', 'holdout_cases', 'user_review']
    source_snapshot: dict
    source_snapshot_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    annotations: list[Annotation] = Field(default_factory=list, max_length=100)


class AnnotationDocument(Model):
    schema_version: Literal['pet-annotation-document-v1']
    catalog_version: str
    category: Literal['pet_fountain']
    data_kind: Literal['synthetic_samples', 'user_provided_unverified']
    reference_kind: Literal['annotation_draft_not_gold'] = 'annotation_draft_not_gold'
    model_transmission_authorization: Literal['requires_separate_chat_authorization'] = 'requires_separate_chat_authorization'
    source_batches: list[SourceBatch] = Field(min_length=1)
    reviews: list[AnnotatedReview] = Field(min_length=1, max_length=500)


def approval_payload_hash(annotation, catalog_version, source_snapshot_hash):
    payload = annotation.model_dump(mode='json', exclude={'status', 'review_reason', 'approval'})
    return checksum({'annotation': payload, 'catalog_version': catalog_version, 'source_snapshot_hash': source_snapshot_hash})


def lint_document(value, catalog_path=CATALOG_PATH):
    catalog, version = load_catalog(catalog_path)
    errors, queue, units, duplicate_units, warnings = [], [], {}, [], []
    try:
        doc = AnnotationDocument.model_validate(value)
    except ValidationError as exc:
        return {'status': 'invalid', 'errors': exc.errors(include_input=False, include_context=False, include_url=False),
                'eligible_for_real_quality_claims': False, 'external_model_requests': 0}
    def error(code, identity):errors.append({'code': code, 'identity': identity})
    if doc.catalog_version != version:error('catalog_version_mismatch', doc.catalog_version)
    batches = {s.batch_id: s for s in doc.source_batches}
    if len(batches) != len(doc.source_batches):error('duplicate_batch_id', 'source_batches')
    if any(s.source_kind == 'synthetic_samples' or s.metadata.get('synthetic') is True for s in doc.source_batches) and doc.data_kind != 'synthetic_samples':
        error('synthetic_source_cannot_be_promoted', 'data_kind')
    review_ids, annotation_ids = set(), set()
    statuses, domains, assertions = Counter(), Counter(), Counter()
    counts = Counter()
    for review in doc.reviews:
        if review.review_id in review_ids:error('duplicate_review_id', review.review_id)
        review_ids.add(review.review_id)
        if not review.body.strip():error('empty_review_body', review.review_id)
        if review.source_batch_id not in batches:error('unknown_source_batch', review.review_id)
        raw = review.source_snapshot
        if checksum(raw) != review.source_snapshot_hash:error('source_snapshot_hash_mismatch', review.review_id)
        body_field = 'body' if review.source_format == 'user_review' else 'text'
        id_field = {'user_review': 'review_id', 'demo_comments': 'comment_id', 'holdout_cases': 'id'}[review.source_format]
        if raw.get(body_field) != review.body or raw.get(id_field) != review.review_id or raw.get('rating') != review.rating:
            error('source_fields_changed', review.review_id)
        originals = raw.get('annotations' if review.source_format == 'demo_comments' else 'expected_annotations', [])
        if not isinstance(originals, list) or any(not isinstance(a, dict) for a in originals):
            error('invalid_source_annotation_snapshot', review.review_id)
            originals = []
        indexed = [a.source_index for a in review.annotations if a.source_index is not None]
        if sorted(indexed) != list(range(len(originals))):error('source_annotations_dropped_or_duplicated', review.review_id)
        if not review.annotations:counts['reviews_without_annotations'] += 1
        for annotation in review.annotations:
            identity = annotation.annotation_id
            counts['annotations'] += 1
            statuses[annotation.status] += 1; assertions[annotation.assertion] += 1
            if identity in annotation_ids:error('duplicate_annotation_id', identity)
            annotation_ids.add(identity)
            if annotation.source_index is not None:
                if annotation.source_index >= len(originals) or annotation.original_annotation != originals[annotation.source_index]:
                    error('original_annotation_changed', identity)
            elif annotation.original_annotation is not None:error('original_annotation_requires_index', identity)
            evidence = annotation.evidence
            if (not evidence.text.strip() or evidence.start >= evidence.end or evidence.end > len(review.body)
                    or evidence.end - evidence.start != len(evidence.text) or review.body[evidence.start:evidence.end] != evidence.text):
                error('evidence_span_mismatch', identity)
            if annotation.annotation_type == 'aspect':
                if annotation.label not in catalog['labels']:error('unknown_aspect_label', identity)
                else:
                    domain = catalog['labels'][annotation.label]['domain']; domains[domain] += 1
                    if annotation.label == 'product.safety_concern' and annotation.assertion != 'potential_risk':
                        error('potential_risk_cannot_be_asserted_as_accident', identity)
            elif (annotation.label is not None or annotation.assertion not in ('uncertain', 'reported', 'corrected')
                  or annotation.polarity != 'neutral'):
                error('context_is_not_an_aspect', identity)
            fingerprint = approval_payload_hash(annotation, version, review.source_snapshot_hash)
            if annotation.status in ('approved', 'rejected'):
                approval = annotation.approval
                if approval is None:error('review_decision_missing', identity)
                elif (not approval.reviewer_id.strip() or not approval.rationale.strip() or
                      approval.reviewed_at.utcoffset() is None or approval.payload_hash != fingerprint):
                    error('stale_or_incomplete_review_decision', identity)
            elif annotation.approval is not None:error('draft_has_stale_approval', identity)
            if annotation.status in ('draft', 'needs_review'):
                queue.append({'review_id': review.review_id, 'annotation_id': identity, 'label': annotation.label,
                              'status': annotation.status, 'reason': annotation.review_reason,
                              'current_payload_hash': fingerprint})
            if annotation.annotation_type == 'aspect':
                key = (review.review_id, annotation.label, annotation.polarity, annotation.assertion)
                if key in units:duplicate_units.append({'annotation_ids': [units[key], identity], 'unit': list(key)})
                else:units[key] = identity
        if review.rating is None:counts['reviews_without_ratings'] += 1
    for review in doc.reviews:
        states = {}
        for a in review.annotations:
            if a.annotation_type == 'aspect' and a.status != 'rejected':
                states.setdefault((a.label, a.assertion), set()).add(a.polarity)
        for (label, assertion), polarities in states.items():
            if len(polarities) > 1:
                warnings.append({'code': 'mixed_polarities_need_context_review', 'review_id': review.review_id, 'label': label})
                group = [a for a in review.annotations if a.label == label and a.assertion == assertion and a.status != 'rejected']
                if any(a.status == 'approved' and not a.scope_note.strip() for a in group):
                    error('approved_mixed_polarity_requires_scope', review.review_id)
    if doc.data_kind == 'user_provided_unverified':
        for batch in doc.source_batches:
            missing = [key for key in ('platform', 'product_reference', 'market', 'review_period', 'rights_note') if not batch.metadata.get(key)]
            if missing:warnings.append({'code': 'source_metadata_incomplete', 'batch_id': batch.batch_id, 'missing': missing})
    return {'status': 'invalid' if errors else 'draft_requires_review' if queue or counts['reviews_without_annotations'] else 'structurally_reviewed_not_verified_gold',
            'catalog_version': version, 'catalog_stage': catalog['stage'], 'review_count': len(doc.reviews),
            'counts': dict(counts), 'statuses': dict(statuses), 'domains': dict(domains), 'assertions': dict(assertions),
            'errors': errors, 'warnings': warnings, 'review_queue': queue, 'duplicate_units': duplicate_units,
            'unique_proposed_aspect_units': len(units), 'eligible_for_real_quality_claims': False,
            'approval_claim_scope': 'User-entered review metadata is not independently verified',
            'source_file_hash_checked_here': False, 'external_model_requests': 0, 'classifier_predictions': 0,
            'scoring_policy': 'No precision/recall/F1 or automatic gold export; changed taxonomy is not comparable to legacy references.'}


def prepare_demo_sources(demo_path, holdout_path, catalog_path=CATALOG_PATH):
    catalog, version = load_catalog(catalog_path)
    batches, reviews = [], []
    for batch_id, path, source_format, array_key in [('demo', demo_path, 'demo_comments', 'comments'),
                                                   ('fixed-regression', holdout_path, 'holdout_cases', 'cases')]:
        raw_bytes = Path(path).read_bytes(); data = json.loads(raw_bytes.decode('utf-8-sig'))
        if data.get('synthetic') is not True or data.get('annotator_type') != 'simulated':
            raise ValueError('Demo preparation only accepts declared synthetic/simulated sources')
        batches.append({'batch_id': batch_id, 'file_sha256': hashlib.sha256(raw_bytes).hexdigest(),
                        'source_kind': 'synthetic_samples', 'metadata': {k: v for k, v in data.items() if k != array_key}})
        for raw in data[array_key]:
            identity = raw['comment_id'] if source_format == 'demo_comments' else raw['id']
            annotations = []
            original_annotations = raw['annotations'] if source_format == 'demo_comments' else raw['expected_annotations']
            for index, original in enumerate(original_annotations):
                issue = original['issue'] if source_format == 'demo_comments' else original['canonical_issue']
                if issue not in catalog['source_aliases']:raise ValueError('Unmapped source issue requires an explicit draft decision')
                override = catalog['source_overrides'].get(f'{identity}:{index}', {})
                label = override.get('label', catalog['source_aliases'][issue])
                excerpt = original['evidence']; start = raw['text'].find(excerpt)
                if start < 0:raise ValueError('Source evidence is not a literal excerpt')
                reason = override.get('review_reason', '开发者拟议映射，原标注保留；需人工检查语义、边界和证据后才能作决定')
                annotations.append({'annotation_id': f'{batch_id}/{identity}/{index}', 'source_index': index,
                                    'original_annotation': deepcopy(original), 'annotation_type': override.get('annotation_type', 'aspect'),
                                    'label': label, 'polarity': POLARITIES[original['sentiment']],
                                    'assertion': override.get('assertion', 'observed'),
                                    'evidence': {'text': excerpt, 'start': start, 'end': start + len(excerpt)},
                                    'status': 'needs_review' if 'review_reason' in override else 'draft',
                                    'review_reason': reason, 'approval': None})
            reviews.append({'review_id': identity, 'body': raw['text'], 'rating': raw.get('rating'),
                            'source_batch_id': batch_id, 'source_format': source_format, 'source_snapshot': deepcopy(raw),
                            'source_snapshot_hash': checksum(raw), 'annotations': annotations})
    return {'schema_version': 'pet-annotation-document-v1', 'catalog_version': version,
            'category': 'pet_fountain', 'data_kind': 'synthetic_samples',
            'reference_kind': 'annotation_draft_not_gold',
            'model_transmission_authorization': 'requires_separate_chat_authorization',
            'source_batches': batches, 'reviews': reviews}


def prepare_user_reviews(value, file_sha256, catalog_path=CATALOG_PATH):
    """Local only: never turn a user-supplied realness claim into verified provenance."""
    if set(value) != {'category', 'data_kind', 'source_metadata', 'reviews'} or value['category'] != 'pet_fountain' or value['data_kind'] != 'user_provided_unverified':
        raise ValueError('Use the pet fountain unverified input template')
    _, version = load_catalog(catalog_path)
    reviews = []
    for raw in value['reviews']:
        if set(raw) != {'review_id', 'body', 'rating'}:raise ValueError('Review fields must be review_id, body, nullable rating')
        reviews.append({'review_id': raw['review_id'], 'body': raw['body'], 'rating': raw['rating'],
                        'source_batch_id': 'user-input', 'source_format': 'user_review', 'source_snapshot': raw,
                        'source_snapshot_hash': checksum(raw), 'annotations': []})
    return {'schema_version': 'pet-annotation-document-v1', 'catalog_version': version,
            'category': 'pet_fountain', 'data_kind': 'user_provided_unverified', 'reference_kind': 'annotation_draft_not_gold',
            'model_transmission_authorization': 'requires_separate_chat_authorization',
            'source_batches': [{'batch_id': 'user-input', 'file_sha256': file_sha256,
                                'source_kind': 'user_provided_unverified', 'metadata': value['source_metadata']}], 'reviews': reviews}


def render_guide(catalog, report):
    lines = ['宠物饮水机标注草案与本地检查', '这是标注规范草案，不是线上标签或模型预测；没有人工金标准自动升级。',
             '每条记录保留原文与原标注，修改拟议标签不会改写原始快照。',
             '评分缺失保持null，不从情绪推断星级。证据位置按Python Unicode字符索引计数，end不包含在区间内。',
             '产品、耗材、服务、整体体验分开；转述/不确定/归因纠正/潜在风险通过assertion记录。',
             '潜在风险不能记成已发生事故；喝水多、看起来干净不代表健康收益或安全检测。',
             'approved/rejected需要人工声明reviewer_id、带时区reviewed_at、rationale及当前payload_hash。',
             '拟议内容或来源快照改变后旧审批指纹失效；输入文件的人工身份和来源声明没有被本工具核实。',
             '待审队列含当前payload_hash；请先修改/检查拟议内容，再运行--lint获取新指纹，最后记录人工决定。',
             '合成数据永远不能成为真实准确率证据；旧固定反例与旧评分定义不回写。',
             '本工具不读取密钥、不打开业务数据库、不发起模型请求，也不会依照输入文件授予调用权限。', '',
             '检查摘要：' + json.dumps({k: report[k] for k in ('status', 'review_count', 'counts', 'statuses', 'domains')}, ensure_ascii=False), '', '标签边界：']
    lines.extend(f"{label} / {spec['name']}\n  包含：{spec['include']}\n  排除：{spec['exclude']}" for label, spec in catalog['labels'].items())
    return '\n'.join(lines)
