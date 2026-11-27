"""Disposable loopback app for QA; never imports the deployment database."""
import os
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
path=Path('D:/Codex_Projects/tmp/qa-browser-20261127.db')
os.environ.update(DB_PATH=str(path),RUN_MODE='mock',EMBEDDING_PROVIDER='hash',REVIEW_LLM_API_KEY='',REVIEW_LLM_BASE_URL='',REVIEW_CONFIG_PATH='D:/Codex_Projects/tmp/disabled-review-config',JOBS_WORKER_ENABLED='false')
from xborder_insight.db.connection import connect
from xborder_insight.db import migrate
from xborder_insight import commerce as c
db=connect(path);migrate.upgrade(db)
if not db.execute('SELECT 1 FROM commerce_products').fetchone():
    candidate=c.create_candidate(db,'local',c.Candidate(name='QA demo',dataset='pet_fountain',theme_id='pump'),{'dataset':'pet_fountain','evidence':['simulation']})
    decision=c.decide(db,'local',candidate['id'],c.Assumptions(price_cents=3000,purchase_cny_cents=7000,cny_per_usd='7',logistics_cents=500,payment_bps=300,payment_fixed_cents=30,aftersales_cents=100,acquisition_cents=300,risk='clear',source_note='isolated simulation'))
    p=c.draft(db,'local',decision['id']);c.add_stock(db,'local',p['id'],5);c.publish(db,'local',p['id'])
db.close()
from xborder_insight.api import app
if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=18031)
