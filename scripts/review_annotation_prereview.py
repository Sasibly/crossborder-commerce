"""Apply the versioned, fully enumerated AI review to an independent draft copy."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from xborder_insight.review_annotation import prepare_demo_sources
from xborder_insight.review_annotation_prereview import apply_prereview, render_report


def read_json(path):
    data = path.read_bytes()
    if len(data) > 2_000_000:raise ValueError('Input exceeds 2MB')
    return json.loads(data.decode('utf-8-sig'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--plan', type=Path, default=ROOT / 'data/review-annotation/synthetic_ai_prereview_v1.json')
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'reports/review-annotation-prereview')
    args = parser.parse_args()
    source = read_json(args.input) if args.input else prepare_demo_sources(
        ROOT / 'data/demo-evaluation/pet_fountain_comments.json', ROOT / 'data/demo-evaluation/pet_fountain_holdout.json')
    document, result = apply_prereview(source, read_json(args.plan))
    folder = args.report_dir / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    folder.mkdir(parents=True, exist_ok=False)
    files = {'annotations-prereviewed.json': document, 'prereview-report.json': result,
             'validation-report.json': result['validation'], 'change-audit.json': result['audit'],
             'ai-demo-reference-candidate.json': result['reference_candidate'],
             'pending-human-items.json': result['reference_candidate']['pending_human_items'],
             'prereview-report.txt': render_report(result)}
    for filename, value in files.items():
        with (folder / filename).open('x', encoding='utf-8') as stream:
            if isinstance(value, str):stream.write(value)
            else:json.dump(value, stream, ensure_ascii=False, indent=2)
    print(json.dumps({'status': 'ai_prereview_complete_human_approval_pending', 'directory': str(folder.resolve()),
                      'counts': result['counts'], 'external_model_requests': 0,
                      'eligible_for_real_quality_claims': False}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
