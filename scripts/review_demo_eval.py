"""Run the confirmed synthetic pet fountain demonstration entirely offline."""
import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from xborder_insight.review_demo_eval import run_demo, render_text


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'data/demo-evaluation/pet_fountain_comments.json')
    parser.add_argument('--rubric', type=Path, default=ROOT / 'data/demo-evaluation/pet_fountain_rules.json')
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'reports/review-demo-eval')
    parser.add_argument('--rules',choices=('v1','v2'),default='v1')
    args = parser.parse_args()
    result = asyncio.run(run_demo(args.source, args.rubric,args.rules))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    target = args.report_dir / (stamp + '-' + uuid4().hex[:8])
    target.mkdir(parents=True, exist_ok=False)
    with (target / 'report.json').open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    with (target / 'report.txt').open('x', encoding='utf-8') as stream:
        stream.write(render_text(result))
    print(json.dumps({'status': 'completed_offline_demo', 'report_json': str((target / 'report.json').resolve()),
                      'report_text': str((target / 'report.txt').resolve()), 'execution': result['execution'],
                      'metrics_scope': result['scoring']['scope'], 'metrics': result['scoring']['metrics'],
                      'reproducibility_digest': result['reproducibility_digest'],
                      'external_model_requests': 0}, ensure_ascii=False, indent=2))
