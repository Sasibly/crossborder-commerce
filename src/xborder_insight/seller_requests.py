"""Persist a result in the same transaction as its effect, scoped by tenant/path."""
from . import commerce as c

def execute(conn, tenant, scope, key, payload, operation):
    # Optional for compatibility with existing local tooling; the UI always sends it.
    if key is None:
        return operation()
    if not 1 <= len(key) <= 128:
        raise c.InputInvalid('Idempotency-Key长度须为1–128')
    fingerprint = c.fingerprint(payload)
    with c.transaction(conn):
        old = conn.execute('SELECT fingerprint,response FROM commerce_seller_requests WHERE tenant=? AND scope=? AND request_key=?', (tenant,scope,key)).fetchone()
        if old:
            if old['fingerprint'] != fingerprint:
                raise c.IdempotencyConflict('请求标识已用于不同内容')
            return c.json.loads(old['response'])
        result = operation()
        conn.execute('INSERT INTO commerce_seller_requests VALUES(?,?,?,?,?)', (tenant,scope,key,fingerprint,c.dump(result)))
        return result
