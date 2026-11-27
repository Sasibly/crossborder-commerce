def up(conn):
    conn.execute('''CREATE TABLE commerce_metric_scenarios (
        id TEXT PRIMARY KEY,tenant TEXT NOT NULL,candidate_id TEXT NOT NULL REFERENCES commerce_candidates(id),
        request_key TEXT NOT NULL,fingerprint TEXT NOT NULL,snapshot TEXT NOT NULL,created_at INTEGER NOT NULL,
        UNIQUE(tenant,request_key))''')
    conn.execute('CREATE INDEX commerce_metric_scenario_candidate ON commerce_metric_scenarios(tenant,candidate_id,created_at)')
    for action in ('UPDATE','DELETE'):
        conn.execute(f"CREATE TRIGGER metric_scenario_no_{action.lower()} BEFORE {action} ON commerce_metric_scenarios BEGIN SELECT RAISE(ABORT,'scenario snapshots are immutable'); END")


def down(conn):
    if conn.execute('SELECT 1 FROM commerce_metric_scenarios LIMIT 1').fetchone():
        raise ValueError('已有指标场景快照，不能降级丢失来源记录；请先备份并迁出数据')
    conn.execute('DROP TABLE commerce_metric_scenarios')
