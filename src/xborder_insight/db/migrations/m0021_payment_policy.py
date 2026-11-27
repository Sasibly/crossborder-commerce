def up(conn):
    conn.execute('''CREATE TABLE commerce_payment_policy (
        tenant TEXT PRIMARY KEY, bps INTEGER NOT NULL CHECK(bps BETWEEN 0 AND 10000),
        fixed_cents INTEGER NOT NULL CHECK(fixed_cents>=0),version INTEGER NOT NULL CHECK(version>0))''')


def down(conn):
    import json
    if conn.execute('SELECT 1 FROM commerce_payment_policy LIMIT 1').fetchone() or any('payment_pricing' in json.loads(row['snapshot']) for row in conn.execute('SELECT snapshot FROM commerce_orders')):
        raise ValueError('已有按笔计费订单或费用配置，不能降级到旧计费实现；请先备份并迁出数据')
    conn.execute('DROP TABLE commerce_payment_policy')
