"""Freeze a development-tested candidate, compare V1/V2 offline, preserve all reports."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
from run_eval import score, load_gold, discover_datasets
from xborder_insight.llm import MockLLMClient
from xborder_insight.offline_rules import OfflineRuleClient, RULE_VERSION
from xborder_insight.pipeline.extract import extract_many
from xborder_insight.pipeline.ingest import load_reviews
from xborder_insight.review_demo_eval import run_demo, render_text
from xborder_insight.review_holdout_eval import run_holdout, render_holdout_text, normalized_text


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def compare(directory):
    directory.mkdir(parents=True, exist_ok=False)
    rule_path = ROOT / 'src/xborder_insight/offline_rules.py'
    dev_path = ROOT / 'tests/test_offline_rules_v2.py'
    data_path = ROOT / 'data/demo-evaluation'
    # Persist before evaluating uploaded counterexamples; never edit candidate based on their scores.
    freeze = {'frozen_at_utc': datetime.now(timezone.utc).isoformat(), 'rule_version': RULE_VERSION,
              'candidate_sha256': digest(rule_path), 'development_tests_sha256': digest(dev_path),
              'deployment_scope': 'pet_fountain_only', 'external_model_requests': 0,
              'source_hashes': {str(p.relative_to(ROOT)): digest(p) for p in
                                sorted((ROOT / 'data/samples').glob('*.jsonl')) +
                                sorted(data_path.glob('*.json')) + [ROOT / 'data/eval/gold_labels.jsonl']}}
    with (directory / 'candidate-freeze.json').open('x', encoding='utf-8') as stream:
        json.dump(freeze, stream, ensure_ascii=False, indent=2)
    # Development examples are distinct strings, not alternate IDs for the uploaded examples.
    from test_offline_rules_v2 import CASES
    source_texts = {normalized_text(c['text']) for c in json.loads((data_path / 'pet_fountain_comments.json').read_text(encoding='utf-8-sig'))['comments']}
    source_texts.update(normalized_text(c['text']) for c in json.loads((data_path / 'pet_fountain_holdout.json').read_text(encoding='utf-8-sig'))['cases'])
    assert not any(normalized_text(text) in source_texts for text, _, _ in CASES)
    gold = load_gold(); corpus = {}; all_outcomes = {'v1': [], 'released_scope_v2': []}
    for dataset in discover_datasets():
        reviews = load_reviews(dataset); outputs = []
        for client in (MockLLMClient(), OfflineRuleClient() if dataset == 'pet_fountain' else MockLLMClient()):
            try:outcomes, stats = await extract_many(client, reviews, grounded=True)
            finally:await client.aclose()
            outputs.append((outcomes, {'metrics': score(outcomes, gold), 'parsed': stats.parsed,
                                       'client': client.name}))
        corpus[dataset] = {'v1': outputs[0][1], 'released_scope_v2': outputs[1][1]}
        for key, output in zip(all_outcomes, outputs):all_outcomes[key].extend(output[0])
    old_demo = await run_demo(data_path / 'pet_fountain_comments.json', data_path / 'pet_fountain_rules.json', 'v1')
    new_demo = await run_demo(data_path / 'pet_fountain_comments.json', data_path / 'pet_fountain_rules.json', 'v2')
    old_holdout = await run_holdout(data_path / 'pet_fountain_holdout.json', data_path / 'pet_fountain_holdout_rules.json', data_path / 'pet_fountain_comments.json', 'v1')
    new_holdout = await run_holdout(data_path / 'pet_fountain_holdout.json', data_path / 'pet_fountain_holdout_rules.json', data_path / 'pet_fountain_comments.json', 'v2')
    for name, report in [('demo-v1', old_demo), ('demo-v2', new_demo), ('fixed-regression-v1', old_holdout), ('fixed-regression-v2', new_holdout)]:
        with (directory / (name + '.json')).open('x', encoding='utf-8') as stream:json.dump(report, stream, ensure_ascii=False, indent=2)
        with (directory / (name + '.txt')).open('x', encoding='utf-8') as stream:stream.write(render_holdout_text(report) if 'holdout' in report.get('split_claim','') else render_text(report))
    overall = {key: score(value, gold) for key, value in all_outcomes.items()}
    gates = {'candidate_unchanged_after_freeze': digest(rule_path) == freeze['candidate_sha256'],
             'sources_and_reference_labels_unchanged': all(digest(ROOT / p) == value for p, value in freeze['source_hashes'].items()),
             'development_examples_not_exact_duplicates_of_uploaded_sets': True,
             'other_categories_identical': all(row['v1'] == row['released_scope_v2'] for d,row in corpus.items() if d != 'pet_fountain'),
             'pet_corpus_no_f1_regression': corpus['pet_fountain']['released_scope_v2']['metrics']['f1'] >= corpus['pet_fountain']['v1']['metrics']['f1'],
             'pet_corpus_no_parse_regression': corpus['pet_fountain']['released_scope_v2']['parsed'] >= corpus['pet_fountain']['v1']['parsed'],
             'overall_no_f1_regression': overall['released_scope_v2']['f1'] >= overall['v1']['f1'],
             'demo_no_scoped_regression': new_demo['scoring']['metrics']['f1'] >= old_demo['scoring']['metrics']['f1'],
             'fixed_regression_no_scoped_regression': new_holdout['scoring']['metrics']['f1'] >= old_holdout['scoring']['metrics']['f1']}
    summary = {'status': 'passed' if all(gates.values()) else 'failed', 'freeze': freeze, 'gates': gates,
               'corpus': corpus, 'overall': overall,
               'demo': {k: r['scoring']['metrics'] for k,r in [('v1',old_demo),('v2',new_demo)]},
               'fixed_regression': {k: {'metrics': r['scoring']['metrics'], 'rating_sensitive_case_ids':r['rating_sensitive_case_ids']} for k,r in [('v1',old_holdout),('v2',new_holdout)]},
               'external_model_requests': 0, 'database_writes': 0, 'blind_test': False,
               'scope': 'Synthetic development-visible regression; partial references are not real or whole-review accuracy.'}
    with (directory / 'comparison.json').open('x', encoding='utf-8') as stream:json.dump(summary, stream, ensure_ascii=False, indent=2)
    text = ['离线规则V1/V2比较；V2仅启用宠物饮水机。', '合成演示，非真实准确率，固定反例非盲测。',
            '门禁：' + json.dumps(gates, ensure_ascii=False),
            '原10条演示局部指标：' + json.dumps(summary['demo'], ensure_ascii=False),
            '20条固定反例局部指标：' + json.dumps(summary['fixed_regression'], ensure_ascii=False),
            '原200条语料总体：' + json.dumps({k: {m:v[m] for m in ('tp','fp','fn','precision','recall','f1')} for k,v in overall.items()}),
            '细节见同目录各版本逐条报告；17个标签缺口和2个待核对标注仍未解决。']
    (directory / 'comparison.txt').write_text('\n'.join(text), encoding='utf-8')
    print(json.dumps({'status':summary['status'],'directory':str(directory.resolve()),'rule_version':RULE_VERSION,
                      'gates':gates,'demo':summary['demo'],'fixed_regression':summary['fixed_regression']}, ensure_ascii=False, indent=2))
    if not all(gates.values()):raise RuntimeError('Candidate regression gates failed; do not deploy')


if __name__ == '__main__':
    # Import development fixtures without running tests; kept outside runtime app imports.
    sys.path.insert(0, str(ROOT / 'tests'))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'reports/offline-rules-comparison')
    args = parser.parse_args()
    folder = args.report_dir / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    asyncio.run(compare(folder))
