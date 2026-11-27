from ..errors import AppError, InputInvalid


class Forbidden(AppError):
    code='forbidden'
    status_code=403


ROLES=('owner','operator','viewer')


def get(conn,key_hash):
    row=conn.execute('SELECT role FROM commerce_key_roles WHERE key_hash=?',(key_hash,)).fetchone()
    return row['role'] if row else 'owner'  # explicitly preserve legacy keys


def set_role(conn,key_hash,role):
    if role not in ROLES:
        raise InputInvalid('角色必须为 owner/operator/viewer')
    conn.execute('INSERT INTO commerce_key_roles VALUES(?,?) ON CONFLICT(key_hash) DO UPDATE SET role=excluded.role',(key_hash,role))


def authorize(role,method,path):
    if method in ('GET','HEAD','OPTIONS'):
        return
    if role=='viewer':
        raise Forbidden('只读角色不能执行写操作')
    financial=(path=='/v1/commerce/payment-policy' or '/refunds/' in path or '/refund-costs/' in path or
               path.startswith('/v1/commerce/orders/') and path.endswith(('/pay','/refund')))
    if role=='operator' and financial:
        raise Forbidden('此操作需要 owner 角色')
