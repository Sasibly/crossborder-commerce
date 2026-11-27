"""Exercise local-only protected container controls; never print generated credentials."""
import json
from pathlib import Path
import secrets
import sys

import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from xborder_insight.config import ROOT_DIR,settings
from xborder_insight.db.connection import connect
from xborder_insight.security import keys


def main():
    if not settings.auth_required or not settings.is_mock:
        raise ValueError('仅允许鉴权开启的本地 mock 预部署环境')
    path=Path(settings.db_path)
    if not path.is_absolute():path=ROOT_DIR/path
    conn=connect(path);identities=[]
    try:
        owner,owner_row=keys.create(conn,tenant_id='local',label='ephemeral protected probe',rpm_limit=1000)
        identities.append(owner_row['key_hash'])
        viewer,viewer_row=keys.create(conn,tenant_id='local',label='ephemeral readonly probe',role='viewer',rpm_limit=1000)
        identities.append(viewer_row['key_hash'])
        with httpx.Client(base_url='http://127.0.0.1:'+str(settings.app_port),timeout=10,trust_env=False) as client:
            ready=client.get('/ready');ready.raise_for_status();assert ready.json()['auth']=='required'
            assert client.get('/v1/commerce/me').status_code==401
            assert client.get('/v1/commerce/me',headers={'Authorization':'Bearer '+owner}).json()['role']=='owner'
            assert client.get('/v1/commerce/me',headers={'Authorization':'Bearer '+viewer}).json()['role']=='viewer'
            assert client.post('/v1/commerce/candidates',headers={'Authorization':'Bearer '+viewer},json={}).status_code==403
            credentials={'email':'protected-'+secrets.token_hex(8)+'@example.test','password':secrets.token_urlsafe(24)}
            response=client.post('/shop/api/account/register',json=credentials);response.raise_for_status()
            cookie=response.headers.get('set-cookie','').lower()
            assert all(flag in cookie for flag in ('secure','httponly','samesite=lax'))
            assert client.post('/shop/api/account/login',json=credentials,headers={'Origin':'https://untrusted.example.test'}).status_code==401
        report={'status':'passed','data_kind':'simulation','checks':['missing seller key rejected',
            'owner/viewer identity enforced','viewer write rejected','Secure/HttpOnly/SameSite cookie flags',
            'cross-origin login rejected'],'scope':'HTTP inside the isolated container; TLS transport and public routing are not tested.',
            'probe_keys_revoked_on_exit':True}
    finally:
        for identity in identities:keys.revoke(conn,identity)
        conn.close()
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
