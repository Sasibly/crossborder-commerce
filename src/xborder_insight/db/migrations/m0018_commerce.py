"""Commerce vertical slice; snapshots are append-only at service boundary."""
import sqlite3

TABLES = {
    'commerce_candidates': '''CREATE TABLE commerce_candidates (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, name TEXT NOT NULL,
        source_json TEXT NOT NULL, created_at INTEGER NOT NULL)''',
    'commerce_decisions': '''CREATE TABLE commerce_decisions (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, candidate_id TEXT NOT NULL
        REFERENCES commerce_candidates(id), snapshot TEXT NOT NULL, created_at INTEGER NOT NULL)''',
    'commerce_products': '''CREATE TABLE commerce_products (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, decision_id TEXT NOT NULL UNIQUE
        REFERENCES commerce_decisions(id), title TEXT NOT NULL, price_cents INTEGER NOT NULL CHECK(price_cents>0),
        stock INTEGER NOT NULL DEFAULT 0 CHECK(stock>=0), reserved INTEGER NOT NULL DEFAULT 0 CHECK(reserved>=0),
        status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','published')),
        snapshot TEXT NOT NULL, created_at INTEGER NOT NULL)''',
    'commerce_orders': '''CREATE TABLE commerce_orders (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, product_id TEXT NOT NULL REFERENCES commerce_products(id),
        token TEXT NOT NULL UNIQUE, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
        quantity INTEGER NOT NULL CHECK(quantity>0), amount_cents INTEGER NOT NULL CHECK(amount_cents>0),
        status TEXT NOT NULL CHECK(status IN ('pending','paid','shipped','completed','cancelled','refunded')),
        snapshot TEXT NOT NULL, actual_logistics_cents INTEGER CHECK(actual_logistics_cents>=0),
        tracking TEXT, created_at INTEGER NOT NULL, expires_at INTEGER NOT NULL,
        UNIQUE(tenant,request_key))''',
    'commerce_events': '''CREATE TABLE commerce_events (
        id TEXT PRIMARY KEY, tenant TEXT NOT NULL, order_id TEXT NOT NULL REFERENCES commerce_orders(id),
        kind TEXT NOT NULL, fingerprint TEXT NOT NULL, created_at INTEGER NOT NULL)''',
    'commerce_ledger': '''CREATE TABLE commerce_ledger (
        id INTEGER PRIMARY KEY, tenant TEXT NOT NULL, product_id TEXT NOT NULL REFERENCES commerce_products(id),
        order_id TEXT REFERENCES commerce_orders(id), action TEXT NOT NULL,
        stock_delta INTEGER NOT NULL, reserved_delta INTEGER NOT NULL, created_at INTEGER NOT NULL)''',
}

def up(conn: sqlite3.Connection) -> None:
    for sql in TABLES.values():
        conn.execute(sql)
    conn.execute('CREATE INDEX commerce_orders_status ON commerce_orders(tenant,status,expires_at)')

def down(conn: sqlite3.Connection) -> None:
    for table in reversed(TABLES):
        conn.execute(f'DROP TABLE {table}')
