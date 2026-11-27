import sqlite3


def up(conn: sqlite3.Connection):
    conn.execute('''CREATE TABLE commerce_key_roles (
        key_hash TEXT PRIMARY KEY REFERENCES api_keys(key_hash),
        role TEXT NOT NULL CHECK(role IN ('owner','operator','viewer')))''')
    conn.execute('''CREATE TABLE commerce_audit (
        id INTEGER PRIMARY KEY, tenant TEXT NOT NULL, actor_id TEXT NOT NULL,
        actor_display TEXT NOT NULL, action TEXT NOT NULL, object_id TEXT NOT NULL,
        detail TEXT NOT NULL, created_at INTEGER NOT NULL)''')
    conn.execute('CREATE INDEX commerce_audit_tenant ON commerce_audit(tenant,id)')
    for action in ('UPDATE','DELETE'):
        conn.execute(f"CREATE TRIGGER commerce_audit_no_{action.lower()} BEFORE {action} ON commerce_audit BEGIN SELECT RAISE(ABORT,'audit is append-only'); END")


def down(conn: sqlite3.Connection):
    if conn.execute("SELECT 1 FROM commerce_key_roles r JOIN api_keys k USING(key_hash) WHERE r.role!='owner' AND k.revoked_at IS NULL LIMIT 1").fetchone():
        raise ValueError('存在有效受限角色 Key，降级会扩大权限；请先迁出或吊销这些 Key')
    conn.execute('DROP TABLE commerce_audit')
    conn.execute('DROP TABLE commerce_key_roles')
