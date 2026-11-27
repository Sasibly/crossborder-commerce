def up(conn):
    conn.execute('''CREATE TABLE commerce_profit_comparisons (
        id TEXT PRIMARY KEY,tenant TEXT NOT NULL,candidate_id TEXT NOT NULL REFERENCES commerce_candidates(id),
        request_key TEXT NOT NULL,fingerprint TEXT NOT NULL,snapshot TEXT NOT NULL,created_at INTEGER NOT NULL,
        UNIQUE(tenant,request_key))''')
    conn.execute('CREATE INDEX commerce_profit_comparison_candidate ON commerce_profit_comparisons(tenant,candidate_id,created_at)')
    for action in ('UPDATE','DELETE'):
        conn.execute(f"CREATE TRIGGER profit_comparison_no_{action.lower()} BEFORE {action} ON commerce_profit_comparisons BEGIN SELECT RAISE(ABORT,'comparison snapshots are immutable'); END")


def down(conn):
    if conn.execute('SELECT 1 FROM commerce_profit_comparisons LIMIT 1').fetchone():
        raise ValueError('已有利润比较快照，不能降级丢失决策依据；请先备份并迁出数据')
    conn.execute('DROP TABLE commerce_profit_comparisons')
