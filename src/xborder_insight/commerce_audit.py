"""Audit writes share the business transaction; never store request bodies or secrets."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import time

from .db.connection import transaction

actor=ContextVar('commerce_actor',default=('system','system'))


@contextmanager
def actor_db(open_db,user):
    identity=(user['id'],'buyer:'+user['id'][:8]) if isinstance(user,dict) else (user.actor_id,user.key_prefix or 'local-demo')
    token=actor.set(identity)
    try:
        with open_db() as conn:
            yield conn  # domain services own transaction boundaries
    finally:
        actor.reset(token)


def record(conn,tenant,action,object_id,detail=None):
    identity,display=actor.get()
    conn.execute('INSERT INTO commerce_audit(tenant,actor_id,actor_display,action,object_id,detail,created_at) VALUES(?,?,?,?,?,?,?)',
                 (tenant,identity,display,action,object_id,json.dumps(detail or {},sort_keys=True),int(time.time())))


def page(conn,tenant,after=0,limit=50):
    rows=conn.execute('SELECT id,actor_display,action,object_id,detail,created_at FROM commerce_audit WHERE tenant=? AND id>? ORDER BY id LIMIT ?',
                      (tenant,after,limit)).fetchall()
    return [{'id':r['id'],'actor':r['actor_display'],'action':r['action'],'object_id':r['object_id'],
             'detail':json.loads(r['detail']),'created_at':r['created_at']} for r in rows]
