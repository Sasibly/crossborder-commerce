"""Buyer ownership, carts, order lines and reviewed refunds; preserve v18 orders."""
import sqlite3
import json


def up(conn: sqlite3.Connection):
    statements = [
        '''CREATE TABLE commerce_buyers (
            id TEXT PRIMARY KEY, tenant TEXT NOT NULL, email TEXT NOT NULL,
            password_hash TEXT NOT NULL, created_at INTEGER NOT NULL,
            UNIQUE(tenant,email))''',
        '''CREATE TABLE commerce_sessions (
            token_hash TEXT PRIMARY KEY, buyer_id TEXT NOT NULL REFERENCES commerce_buyers(id),
            csrf TEXT NOT NULL, expires_at INTEGER NOT NULL)''',
        '''CREATE TABLE commerce_auth_attempts (
            bucket TEXT PRIMARY KEY, hits INTEGER NOT NULL, expires_at INTEGER NOT NULL)''',
        '''CREATE TABLE commerce_addresses (
            id TEXT PRIMARY KEY, buyer_id TEXT NOT NULL REFERENCES commerce_buyers(id),
            address_json TEXT NOT NULL, created_at INTEGER NOT NULL)''',
        '''CREATE TABLE commerce_cart (
            buyer_id TEXT NOT NULL REFERENCES commerce_buyers(id),
            product_id TEXT NOT NULL REFERENCES commerce_products(id),
            quantity INTEGER NOT NULL CHECK(quantity BETWEEN 1 AND 20),
            PRIMARY KEY(buyer_id,product_id))''',
        '''ALTER TABLE commerce_orders ADD COLUMN buyer_id TEXT REFERENCES commerce_buyers(id)''',
        '''CREATE INDEX commerce_orders_buyer ON commerce_orders(buyer_id,created_at)''',
        '''CREATE TABLE commerce_order_items (
            order_id TEXT NOT NULL REFERENCES commerce_orders(id),
            product_id TEXT NOT NULL REFERENCES commerce_products(id),
            quantity INTEGER NOT NULL CHECK(quantity>0), unit_price_cents INTEGER NOT NULL CHECK(unit_price_cents>0),
            snapshot TEXT NOT NULL, PRIMARY KEY(order_id,product_id))''',
        '''CREATE TABLE commerce_refunds (
            id TEXT PRIMARY KEY, tenant TEXT NOT NULL,
            order_id TEXT NOT NULL UNIQUE REFERENCES commerce_orders(id),
            buyer_id TEXT NOT NULL REFERENCES commerce_buyers(id),
            reason TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('requested','approved','rejected')),
            review_note TEXT, created_at INTEGER NOT NULL, reviewed_at INTEGER)''',
        '''CREATE TABLE commerce_refund_costs (
            order_id TEXT PRIMARY KEY REFERENCES commerce_orders(id),
            snapshot TEXT NOT NULL, created_at INTEGER NOT NULL)''',
    ]
    for sql in statements:
        conn.execute(sql)
    for order in conn.execute('SELECT * FROM commerce_orders').fetchall():
        snapshot = json.loads(order['snapshot'])
        conn.execute('INSERT INTO commerce_order_items VALUES(?,?,?,?,?)',
                     (order['id'],order['product_id'],order['quantity'],snapshot['unit_price_cents'],order['snapshot']))


def down(conn: sqlite3.Connection):
    if conn.execute('SELECT 1 FROM commerce_orders WHERE buyer_id IS NOT NULL LIMIT 1').fetchone() or conn.execute('SELECT 1 FROM commerce_order_items GROUP BY order_id HAVING COUNT(*)>1 LIMIT 1').fetchone():
        raise ValueError('已有买家订单或多商品订单，无法无损降级至 v18；请先备份并迁出相关数据')
    for table in ('commerce_refund_costs','commerce_refunds','commerce_order_items'):
        conn.execute(f'DROP TABLE {table}')
    conn.execute('DROP INDEX commerce_orders_buyer')
    conn.execute('ALTER TABLE commerce_orders DROP COLUMN buyer_id')
    for table in ('commerce_cart','commerce_addresses','commerce_auth_attempts','commerce_sessions','commerce_buyers'):
        conn.execute(f'DROP TABLE {table}')
