"""Seller-only review analysis; never accepts a model key from a web request."""
from fastapi import Depends, Header, Request
from fastapi.responses import Response
from pathlib import Path
from . import review_analysis as r
from . import commerce as c
from .commerce_audit import actor_db
from .buyers_api import same_origin
from .security.roles import Forbidden


def install(app,open_db,principal):
    @app.get('/commerce-assets/review-analysis.js',include_in_schema=False)
    def assets():
        return Response(Path(__file__).with_name('review_analysis.js').read_text(encoding='utf-8'),media_type='application/javascript')
    @app.get('/v1/commerce/review-analysis-config',tags=['review-analysis'])
    def configuration(user=Depends(principal)):
        with actor_db(open_db,user) as conn:return r.status(conn)

    @app.post('/v1/commerce/review-import',tags=['review-analysis'])
    def preview(body:r.ImportRequest,request:Request,user=Depends(principal)):
        same_origin(request)
        return r.import_reviews(body)

    @app.post('/v1/commerce/review-analyses',tags=['review-analysis'])
    def submit(body:r.AnalysisRequest,request:Request,idempotency_key:str=Header(alias='Idempotency-Key'),user=Depends(principal)):
        same_origin(request)
        if body.mode=='live' and user.role!='owner':raise Forbidden('真实模型调用需要owner角色')
        with actor_db(open_db,user) as conn:return r.submit(conn,user.tenant_id,body,idempotency_key)

    @app.get('/v1/commerce/review-analyses',tags=['review-analysis'])
    def listing(user=Depends(principal)):
        with actor_db(open_db,user) as conn:
            rows=conn.execute('''SELECT id,dataset,mode,status,request_count,created_at,finished_at,error_code,provenance
                FROM commerce_review_analyses WHERE tenant=? ORDER BY created_at DESC,id DESC LIMIT 30''',(user.tenant_id,)).fetchall()
            import json
            return [{**dict(row),'provenance':json.loads(row['provenance'])} for row in rows]

    @app.get('/v1/commerce/review-analyses/{identity}',tags=['review-analysis'])
    def detail(identity:str,user=Depends(principal)):
        with actor_db(open_db,user) as conn:return r.get(conn,user.tenant_id,identity)

    @app.get('/v1/commerce/review-analyses/{identity}/progress',tags=['review-analysis'])
    def progress(identity:str,user=Depends(principal)):
        with actor_db(open_db,user) as conn:return r.progress_view(conn,user.tenant_id,identity)
