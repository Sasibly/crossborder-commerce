"""Prepare/lint local annotation drafts. Never extracts labels or calls models."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from xborder_insight.review_annotation import (
    CATALOG_PATH, AnnotationDocument, load_catalog, prepare_demo_sources,
    prepare_user_reviews, lint_document, render_guide,
)


def read_json(path):
    raw = path.read_bytes()
    if len(raw) > 2_000_000:raise ValueError('Local input exceeds 2MB; split it before checking')
    return json.loads(raw.decode('utf-8-sig')), hashlib.sha256(raw).hexdigest()


def write(path, value):
    with path.open('x', encoding='utf-8') as stream:
        if isinstance(value, str):stream.write(value)
        else:json.dump(value, stream, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--lint', type=Path, help='Check a prepared annotation document')
    action.add_argument('--prepare-reviews', type=Path, help='Prepare unverified raw review template locally')
    parser.add_argument('--catalog', type=Path, default=CATALOG_PATH)
    parser.add_argument('--report-dir', type=Path, default=ROOT / 'reports/review-annotation')
    args = parser.parse_args()
    catalog, _ = load_catalog(args.catalog)
    try:
        if args.lint:
            document, _ = read_json(args.lint)
        elif args.prepare_reviews:
            source, digest = read_json(args.prepare_reviews)
            document = prepare_user_reviews(source, digest, args.catalog)
        else:
            document = prepare_demo_sources(ROOT / 'data/demo-evaluation/pet_fountain_comments.json',
                                            ROOT / 'data/demo-evaluation/pet_fountain_holdout.json', args.catalog)
        report = lint_document(document, args.catalog)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        report = {'status': 'invalid', 'errors': [{'code': 'input_preparation_failed', 'kind': type(exc).__name__}],
                  'eligible_for_real_quality_claims': False, 'external_model_requests': 0}
        document = None
    directory = args.report_dir / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid4().hex[:8])
    directory.mkdir(parents=True, exist_ok=False)
    write(directory / 'validation-report.json', report)
    write(directory / 'label-catalog.json', catalog)
    write(directory / 'annotation-document.schema.json', AnnotationDocument.model_json_schema())
    if document is not None:write(directory / 'annotations-draft.json', document)
    if report['status'] != 'invalid':
        write(directory / 'review-queue.json', report['review_queue'])
        write(directory / 'annotation-guide.txt', render_guide(catalog, report))
    template = {'category': 'pet_fountain', 'data_kind': 'user_provided_unverified',
                'source_metadata': {'platform': None, 'product_reference': None, 'market': None,
                                    'review_period': None, 'rights_note': None}, 'reviews': []}
    write(directory / 'new-reviews-template.json', template)
    print(json.dumps({'status': report['status'], 'directory': str(directory.resolve()),
                      'review_count': report.get('review_count'), 'counts': report.get('counts'),
                      'statuses': report.get('statuses'), 'errors': report.get('errors'),
                      'external_model_requests': 0, 'eligible_for_real_quality_claims': False}, ensure_ascii=False, indent=2))
    return int(report['status'] == 'invalid')


if __name__ == '__main__':
    raise SystemExit(main())
