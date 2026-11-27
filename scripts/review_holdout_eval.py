"""Run frozen synthetic counterexample regression locally, without tuning or networking."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from xborder_insight.review_holdout_eval import run_holdout, render_holdout_text

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'data/demo-evaluation/pet_fountain_holdout.json')
    parser.add_argument('--rubric', type=Path, default=ROOT / 'data/demo-evaluation/pet_fountain_holdout_rules.json')
    parser.add_argument('--original-demo', type=Path, default=ROOT / 'data/demo-evaluation/pet_fountain_comments.json')
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'reports/review-holdout-eval')
    parser.add_argument('--rules',choices=('v1','v2'),default='v1')
    args = parser.parse_args()
    report = asyncio.run(run_holdout(args.source, args.rubric, args.original_demo,args.rules))
    target = args.report_dir / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    target.mkdir(parents=True, exist_ok=False)
    for name, content in [('report.json', json.dumps(report, ensure_ascii=False, indent=2)),
                          ('report.txt', render_holdout_text(report))]:
        with (target / name).open('x', encoding='utf-8') as stream: stream.write(content)
    print(json.dumps({'status': 'completed_offline_counterexample_regression', 'report_text': str((target / 'report.txt').resolve()),
                      'report_json': str((target / 'report.json').resolve()), 'execution': report['execution'],
                      'reference_dispositions': report['reference']['annotation_dispositions'],
                      'primary_scoped_metrics': report['scoring']['metrics'],
                      'rating_sensitive_cases': len(report['rating_sensitive_case_ids']),
                      'external_model_requests': 0}, ensure_ascii=False, indent=2))
