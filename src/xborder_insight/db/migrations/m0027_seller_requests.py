"""Atomic receipts for retryable seller creation and stock changes."""
def up(conn):
    conn.execute('''CREATE TABLE commerce_seller_requests (
        tenant TEXT NOT NULL, scope TEXT NOT NULL, request_key TEXT NOT NULL,
        fingerprint TEXT NOT NULL, response TEXT NOT NULL,
        PRIMARY KEY(tenant,scope,request_key))''')

def down(conn):
    if conn.execute('SELECT 1 FROM commerce_seller_requests LIMIT 1').fetchone():
        raise ValueError('已有卖家去重记录，不能降级丢失重试保护')
    conn.execute('DROP TABLE commerce_seller_requests')
