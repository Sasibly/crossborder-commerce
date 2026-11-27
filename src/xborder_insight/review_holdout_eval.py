"""Fixed synthetic counterexample regression; source is visible, not a blind test."""
import hashlib
import json
import unicodedata
from pathlib import Path

from .llm import MockLLMClient
from .pipeline.extract import PROMPT_VERSION, extract_many
from .review_demo_eval import fingerprint, prepare_reference, score_predictions, render_text
from .schemas import Review
from .taxonomy import TAXONOMY_VERSION


def normalized_text(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def prepare_holdout(data, policy, rating=3):
    if (data.get('synthetic') is not True or data.get('annotator_type') != 'simulated'
            or data.get('split') != 'holdout_adversarial'
            or policy.get('schema_version') != 'pet-holdout-rubric-v1'
            or policy.get('reference_kind') != 'developer_defined_demo_reference_not_human_gold'
            or policy.get('category') != 'pet_fountain' or rating not in (1, 3, 5)
            or policy.get('rating_assumptions') != [1, 3, 5] or policy.get('primary_assumed_rating') != 3):
        raise ValueError('Only synthetic counterexamples and explicit rating assumptions are accepted')
    cases = data['cases']
    if not 1 <= len(cases) <= 100 or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Case IDs must be unique, with 1..100 local cases')
    if any('rating' in c for c in cases):
        raise ValueError('This source format has no actual ratings; do not silently replace them')
    comments, rules, seen_keys = [], {}, set()
    for case in cases:
        if case['expected_comment_label'] not in {'正面', '负面', '中性', '混合'}:
            raise ValueError('Unknown overall label')
        annotations = []
        for index, raw in enumerate(case['expected_annotations']):
            key = f"{case['id']}:{index}"
            rule = policy['rules'].get(key)
            if rule is None or rule['expected_canonical_issue'] != raw['canonical_issue']:
                raise ValueError('Every source annotation needs an exact explicit policy binding')
            seen_keys.add(key); rules[key] = rule
            annotations.append({'issue': key, 'sentiment': raw['sentiment'], 'evidence': raw['evidence']})
        comments.append({'comment_id': case['id'], 'rating': rating, 'text': case['text'],
                         'synthetic': True, 'annotator_type': 'simulated', 'annotations': annotations})
    if set(policy['rules']) != seen_keys:
        raise ValueError('Policy has orphan or missing annotation rules')
    # Local-only adaptation in <=10 chunks. Never loosens production live-input limits.
    converted = {'synthetic': True, 'annotator_type': 'simulated', 'category': '宠物饮水机'}
    rubric = {'schema_version': 'pet-demo-rubric-v1', 'category': 'pet_fountain',
              'reference_kind': policy['reference_kind'], 'rules': rules}
    result = {'reviews': [], 'annotation_dispositions': {}, 'raw_annotation_count': 0, 'scored_reference_units': 0}
    for offset in range(0, len(comments), 10):
        prepared = prepare_reference({**converted, 'comments': comments[offset:offset + 10]}, rubric)
        result['reviews'].extend(prepared['reviews'])
        for key, value in prepared['annotation_dispositions'].items():
            result['annotation_dispositions'][key] = result['annotation_dispositions'].get(key, 0) + value
        for key in ('raw_annotation_count', 'scored_reference_units'):
            result[key] += prepared[key]
    for entry, case in zip(result['reviews'], cases):
        entry['assumed_rating'] = rating
        entry['rating_provenance'] = 'evaluation_assumption_not_source_rating'
        entry['trap_type'] = case['trap_type']
        entry['source_original'] = case
        entry['expected_comment_label'] = case['expected_comment_label']
        for annotation, raw in zip(entry['annotations'], case['expected_annotations']):
            annotation['source_original'] = raw
            annotation['original']['issue'] = raw['canonical_issue']
    return result


async def run_holdout(source_path, policy_path, original_demo_path, client_kind='v1'):
    if client_kind not in ('v1','v2'):raise ValueError('Only offline v1/v2 clients are accepted')
    from .offline_rules import OfflineRuleClient
    raw = Path(source_path).read_bytes(); digest = hashlib.sha256(raw).hexdigest()
    data = json.loads(raw.decode('utf-8-sig'))
    policy = json.loads(Path(policy_path).read_text(encoding='utf-8-sig'))
    if policy.get('source_sha256') != digest:
        raise ValueError('Counterexample source hash differs from frozen rubric')
    original_raw = Path(original_demo_path).read_bytes()
    original = json.loads(original_raw.decode('utf-8-sig'))['comments']
    ids = {c['comment_id'] for c in original}
    texts = {normalized_text(c['text']) for c in original}
    overlap = {'review_ids': [c['id'] for c in data['cases'] if c['id'] in ids],
               'normalized_text_case_ids': [c['id'] for c in data['cases'] if normalized_text(c['text']) in texts],
               'comparison_scope': 'Original 10 uploaded demo comments only; absence of exact duplicates does not prove statistical independence'}
    internal_texts = {}
    for case in data['cases']:
        internal_texts.setdefault(normalized_text(case['text']), []).append(case['id'])
    repeated_text_ids = [group for group in internal_texts.values() if len(group) > 1]
    canonical_groups = {}
    for case in data['cases']:
        for index, annotation in enumerate(case['expected_annotations']):
            key = (case['id'], annotation['canonical_issue'], annotation['sentiment'])
            canonical_groups.setdefault(key, []).append(index)
    results = []
    # Predefined before observing scores; no choosing the best star rating or tuning rules.
    for rating in (1, 3, 5):
        reference = prepare_holdout(data, policy, rating)
        client = OfflineRuleClient() if client_kind=='v2' else MockLLMClient()
        try:
            outcomes, stats = await extract_many(client, [Review.model_validate(r['review']) for r in reference['reviews']],
                                                 concurrency=3, grounded=True)
        finally:
            await client.aclose()
        predictions = [{'review_id': o.review_id, 'status': 'parsed' if o.extraction else 'unparsed',
                        'error': o.error, 'points': [p.model_dump() for p in o.extraction.points] if o.extraction else []}
                       for o in outcomes]
        results.append({'assumed_rating': rating, 'reference': reference, 'predictions': predictions,
                        'scoring': score_predictions(reference, predictions),
                        'parsed': stats.parsed, 'local_mock_completions': stats.llm_calls})
    main = results[1]
    signatures = [{p['review_id']: sorted((point['label'], point['polarity']) for point in p['points'])
                   for p in run['predictions']} for run in results]
    changed = [c['id'] for c in data['cases'] if len({fingerprint(s[c['id']]) for s in signatures}) > 1]
    versions = {'source_sha256': digest, 'rubric_sha256': fingerprint(policy),
                'original_demo_sha256': hashlib.sha256(original_raw).hexdigest(),
                'baseline_source_sha256': hashlib.sha256(Path(__file__).with_name('offline_rules.py' if client_kind=='v2' else 'llm.py').read_bytes()).hexdigest(),
                'taxonomy_version': TAXONOMY_VERSION, 'prompt_version': PROMPT_VERSION,
                'evaluator_source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'scorer_source_sha256': hashlib.sha256(Path(__file__).with_name('review_demo_eval.py').read_bytes()).hexdigest()}
    report = {'measurement_kind': 'offline_fixed_synthetic_counterexample_regression',
              'client':client.name,'rule_version':getattr(client,'rule_version','mock-v1'),
              'reference_kind': policy['reference_kind'], 'eligible_for_real_quality_claims': False,
              'split_claim': data['split'], 'blind_test': False,
              'evaluation_policy': 'Developer-visible fixed regression; no fitting or rule changes based on this set',
              'source_original_metadata': {k: v for k, v in data.items() if k != 'cases'},
              'versions': versions, 'overlap_with_original_demo': overlap,
              'baseline_matches_prior_demo': all(versions.get(k) == v for k, v in policy['prior_baseline_versions'].items()),
              'prior_baseline_versions': policy['prior_baseline_versions'],
              'internal_duplicate_normalized_text_groups': repeated_text_ids,
              'source_canonical_units_after_dedup': len(canonical_groups),
              'source_repeated_canonical_units': [{'review_id': key[0], 'canonical_issue': key[1],
                                                   'sentiment': key[2], 'annotation_indices': indices}
                                                  for key, indices in canonical_groups.items() if len(indices) > 1],
              'primary_assumed_rating': 3, 'actual_ratings_provided': False,
              'reference': main['reference'], 'predictions': main['predictions'], 'scoring': main['scoring'],
              'rating_sensitivity': [{'assumed_rating': run['assumed_rating'], 'parsed': run['parsed'],
                                      'metrics': run['scoring']['metrics'], 'predictions': run['predictions']} for run in results],
              'rating_sensitive_case_ids': changed,
              'overall_comment_label_scored': False,
              'overall_label_scope': 'Source overall labels are preserved; the existing client emits aspects, not overall sentiment',
              'execution': {'cases': len(data['cases']), 'local_mock_completions': sum(r['local_mock_completions'] for r in results)},
              'external_model_requests': 0, 'database_writes': 0}
    report['reproducibility_digest'] = fingerprint(report)
    return report


def render_holdout_text(report):
    header = ['固定合成反例回归报告', '非真实评论；非盲测；不参与规则调参；未提供的星级不得当成真实评分。',
              '主报告假设3星，另固定运行1星和5星检查敏感性，不按最好成绩选择评分。',
              '整体评论情绪未评分；仅对明确映射的局部方面单元评分。',
              '旧集重复检查：' + json.dumps(report['overlap_with_original_demo'], ensure_ascii=False),
              '评分敏感案例：' + json.dumps(report['rating_sensitive_case_ids'], ensure_ascii=False),
              '是否保持上一阶段基线版本：' + str(report['baseline_matches_prior_demo']),
              '重复原标注维度（证据保留）：' + json.dumps(report['source_repeated_canonical_units'], ensure_ascii=False),
              '各假设局部指标：' + json.dumps([{k: r[k] for k in ('assumed_rating', 'metrics')} for r in report['rating_sensitivity']], ensure_ascii=False), '']
    overall = ['原始整体情绪（保留但不计分）：']
    overall.extend(r['review']['review_id'] + '：' + r['expected_comment_label'] + '；' + r['trap_type']
                   for r in report['reference']['reviews'])
    return '\n'.join(header + overall) + '\n\n' + render_text(report)
