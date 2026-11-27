def up(conn):
    conn.execute('CREATE INDEX commerce_order_creation ON commerce_orders(tenant,created_at,id)')


def down(conn):
    conn.execute('DROP INDEX commerce_order_creation')
