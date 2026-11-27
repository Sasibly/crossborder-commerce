"""Offline synthetic demonstration only. Never constructs a network/model factory."""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from .llm import MockLLMClient
from .pipeline.extract import PROMPT_VERSION, extract_many
from .schemas import ExtractedPoint, Review
from .taxonomy import LABEL_KEYS, TAXONOMY_VERSION

POLARITIES = {'负面': 'negative', '正面': 'positive', '中性': 'neutral'}
DISPOSITIONS = {'mapped', 'taxonomy_gap', 'needs_review'}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def prepare_reference(data, rubric):
    if (data.get('synthetic') is not True or data.get('annotator_type') != 'simulated'
            or data.get('category') != '宠物饮水机' or rubric.get('category') != 'pet_fountain'
            or rubric.get('schema_version') != 'pet-demo-rubric-v1'
            or rubric.get('reference_kind') != 'developer_defined_demo_reference_not_human_gold'):
        raise ValueError('Only the confirmed synthetic pet fountain demo and demo rubric are accepted')
    comments = data['comments']
    if not 1 <= len(comments) <= 10:
        raise ValueError('Demo requires 1..10 comments')
    prepared, ids, counts = [], set(), Counter()
    for row in comments:
        if row.get('synthetic') is not True or row.get('annotator_type') != 'simulated':
            raise ValueError('Every comment must declare synthetic/simulated provenance')
        review = Review(review_id=row['comment_id'], rating=row['rating'], body=row['text'],
                        asin='SYNTHETIC-DEMO-PET', lang='zh-CN')
        if review.review_id in ids:
            raise ValueError('Duplicate review ID')
        ids.add(review.review_id)
        if not row['annotations']:
            raise ValueError('Missing demo annotations must not silently become empty reference')
        groups, annotations = defaultdict(list), []
        for index, raw in enumerate(row['annotations']):
            rule = rubric['rules'].get(raw['issue'])
            if not rule or rule.get('disposition') not in DISPOSITIONS or not rule.get('reason'):
                raise ValueError('Every annotation needs an explicit rubric disposition')
            if raw['sentiment'] not in POLARITIES or not raw['evidence'].strip() or raw['evidence'] not in review.body:
                raise ValueError('Annotation polarity/evidence is invalid')
            disposition = rule['disposition']
            counts[disposition] += 1
            item = {'index': index, 'original': dict(raw), **rule}
            annotations.append(item)
            if disposition == 'mapped':
                if rule.get('label') not in LABEL_KEYS:
                    raise ValueError('Mapped label is outside the production taxonomy')
                groups[(rule['label'], POLARITIES[raw['sentiment']])].append(item)
        # Contradictory reference polarities require adjudication, not arbitrary overwriting.
        conflicts = sorted(label for label in {label for label, _ in groups}
                           if sum(key[0] == label for key in groups) > 1)
        units = [{'label': label, 'polarity': polarity,
                  'evidences': sorted({a['original']['evidence'] for a in items}),
                  'annotation_indices': [a['index'] for a in items]}
                 for (label, polarity), items in sorted(groups.items()) if label not in conflicts]
        prepared.append({'review': review.model_dump(), 'annotations': annotations,
                         'reference_units': units, 'blocked_polarity_conflicts': conflicts})
    return {'reviews': prepared, 'annotation_dispositions': dict(counts),
            'raw_annotation_count': sum(counts.values()),
            'scored_reference_units': sum(len(r['reference_units']) for r in prepared)}


def load_demo(source_path, rubric_path):
    raw = Path(source_path).read_bytes()
    rubric = json.loads(Path(rubric_path).read_text(encoding='utf-8-sig'))
    digest = hashlib.sha256(raw).hexdigest()
    if rubric.get('source_sha256') != digest:
        raise ValueError('Source hash differs from the versioned demo rubric')
    data = json.loads(raw.decode('utf-8-sig'))
    return prepare_reference(data, rubric), rubric, digest


def _metrics(tp, fp, fn):
    return {'tp': tp, 'fp': fp, 'fn': fn,
            'precision': round(tp / (tp + fp), 4) if tp + fp else None,
            'recall': round(tp / (tp + fn), 4) if tp + fn else None,
            'f1': round(2 * tp / (2 * tp + fp + fn), 4) if 2 * tp + fp + fn else None}


def score_predictions(reference, predictions):
    known = {r['review']['review_id'] for r in reference['reviews']}
    by_id = {}
    for row in predictions:
        if row['review_id'] not in known or row['review_id'] in by_id:
            raise ValueError('Prediction IDs must be unique and belong to this dataset')
        by_id[row['review_id']] = row
    totals, details = Counter(), []
    for entry in reference['reviews']:
        review = entry['review']; rid = review['review_id']
        row = by_id.get(rid, {'review_id': rid, 'status': 'missing', 'points': []})
        truth = {(u['label'], u['polarity']) for u in entry['reference_units']}
        scope = {label for label, _ in truth}
        valid, invalid, observed = set(), set(), set()
        errors, outside = [], []
        for index, raw in enumerate(row['points']):
            totals['raw_predictions'] += 1
            key = (raw.get('label'), raw.get('polarity'))
            try:
                point = ExtractedPoint.model_validate(raw)
                if not point.evidence.strip() or point.evidence not in review['body']:
                    raise ValueError('Evidence is not an exact nonempty body excerpt')
                grounded = True
            except (ValueError, TypeError):
                grounded = False
                errors.append({'index': index, 'reason': 'contract_or_literal_evidence_failed'})
            if key[0] not in scope:
                outside.append({'point': raw, 'reason': 'outside_explicit_reference_cells'})
                continue
            if key in observed:
                totals['duplicate_scoped_predictions'] += 1
            observed.add(key)
            (valid if grounded else invalid).add(key)
        # Multiple excerpts for one label/polarity count once; a valid excerpt takes precedence.
        invalid -= valid
        tp, fp, fn = len(valid & truth), len(valid - truth) + len(invalid), len(truth - valid)
        totals.update(tp=tp, fp=fp, fn=fn, unscored_predictions=len(outside),
                      invalid_prediction_points=len(errors), unparsed_reviews=int(row['status'] != 'parsed'))
        controls = [{'label': label, 'expected': polarity,
                     'negative_false_alarm': (label, 'negative') in observed,
                     'matched': (label, polarity) in valid}
                    for label, polarity in sorted(truth) if polarity != 'negative']
        details.append({'review_id': rid, 'prediction_status': row['status'],
                        'scored_labels': sorted(scope), 'metrics': _metrics(tp, fp, fn),
                        'missing': [list(k) for k in sorted(truth - valid)],
                        'extra': [list(k) for k in sorted((valid - truth) | invalid)],
                        'nonnegative_controls': controls, 'validation_errors': errors,
                        'unscored_predictions': outside})
    return {'unit': '(review_id, label, polarity) within explicitly mapped review/label cells only',
            'scope': 'Partial synthetic developer reference; not whole-review precision/recall or human gold',
            'metrics': _metrics(totals['tp'], totals['fp'], totals['fn']),
            'counts': dict(totals), 'reviews': details}


async def run_demo(source_path, rubric_path, client_kind='v1'):
    reference, rubric, source_digest = load_demo(source_path, rubric_path)
    reviews = [Review.model_validate(r['review']) for r in reference['reviews']]
    # Deliberately bypass settings and build_llm_client. Live settings cannot enable networking here.
    if client_kind not in ('v1','v2'):raise ValueError('Only offline v1/v2 clients are accepted')
    from .offline_rules import OfflineRuleClient
    client = OfflineRuleClient() if client_kind=='v2' else MockLLMClient()
    try:
        outcomes, stats = await extract_many(client, reviews, concurrency=3, grounded=True)
    finally:
        await client.aclose()
    predictions = [{'review_id': o.review_id, 'status': 'parsed' if o.extraction else 'unparsed',
                    'error': o.error, 'points': [p.model_dump() for p in o.extraction.points] if o.extraction else []}
                   for o in outcomes]
    scored = score_predictions(reference, predictions)
    versions = {'source_sha256': source_digest, 'rubric_sha256': fingerprint(rubric),
                'taxonomy_version': TAXONOMY_VERSION, 'prompt_version': PROMPT_VERSION,
                'baseline_source_sha256': hashlib.sha256(Path(__file__).with_name('offline_rules.py' if client_kind=='v2' else 'llm.py').read_bytes()).hexdigest(),
                'evaluator_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return {'measurement_kind': 'offline_rule_baseline_on_synthetic_demo',
            'reference_kind': rubric['reference_kind'], 'eligible_for_real_quality_claims': False,
            'external_model_requests': 0, 'database_writes': 0, 'client': client.name,
            'rule_version':getattr(client,'rule_version','mock-v1'),
            'versions': versions, 'reference': reference, 'predictions': predictions, 'scoring': scored,
            'execution': {'reviews': len(reviews), 'parsed': stats.parsed,
                          'local_mock_completions': stats.llm_calls, 'repair_attempts': stats.repair_attempts},
            'reproducibility_digest': fingerprint({'versions': versions, 'reference': reference,
                                                  'predictions': predictions, 'scoring': scored})}


def render_text(report):
    reference = report['reference']; scored = report['scoring']
    lines = ['宠物饮水机合成演示评测', '仅离线规则基线；非真实评论、非人工金标准、非百炼模型效果。',
             f"客户端：{report.get('client','mock-rules')}；版本：{report.get('rule_version','mock-v1')}",
             '仅评价显式映射的评论/标签单元；范围外预测单独列出，不记作漏报或误报。',
             '证据检查只验证原文包含关系，不证明语义正确；不强求与参考证据字符串完全相同。',
             f"样本数：{len(reference['reviews'])}；原标注数：{reference['raw_annotation_count']}",
             f"标注处理：{json.dumps(reference['annotation_dispositions'], ensure_ascii=False)}",
             f"去重及冲突隔离后参考单元：{reference['scored_reference_units']}",
             f"局部演示指标：{json.dumps(scored['metrics'], ensure_ascii=False)}",
             f"诊断计数：{json.dumps(scored['counts'], ensure_ascii=False)}",
             f"复现指纹：{report['reproducibility_digest']}", '']
    for ref, result in zip(reference['reviews'], scored['reviews']):
        lines += [ref['review']['review_id'], ref['review']['body'],
                  '参考单元：' + json.dumps(ref['reference_units'], ensure_ascii=False),
                  '结果：' + json.dumps(result, ensure_ascii=False), '标注处置：']
        lines.extend(f"  {a['original']['issue']} => {a['disposition']} {a.get('label', '')}：{a['reason']}"
                     for a in ref['annotations'])
        lines.append('')
    return '\n'.join(lines)
