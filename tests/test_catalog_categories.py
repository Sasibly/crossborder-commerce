import importlib.util
import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from xborder_insight import api,commerce as c,catalog_categories as catalog
from xborder_insight.db import migrate
from xborder_insight.db.connection import connect
from test_commerce import assumptions,product
from test_commerce_access import secured


def candidate(conn,tenant='local'):
    return c.create_candidate(conn,tenant,c.Candidate(name='Category SKU',dataset='air_purifier',theme_id='T1'),
                              {'dataset':'air_purifier','evidence':['Synthetic category fixture']})


def test_analysis_candidate_draft_and_publication_are_separate(tmp_path,monkeypatch):
    path=tmp_path/'catalog.sqlite3';conn=connect(path);migrate.upgrade(conn)
    monkeypatch.setattr(api,'DB_FILE',path)
    with TestClient(api.app) as client:
        assert client.get('/shop/api/products').json()==[]
        stage=client.get('/v1/commerce/catalog-stages').json()['categories']
        assert len(stage)==6 and all(r['published']==0 and r['candidates']==0 for r in stage)
        cid=candidate(conn)['id']
        blocked=c.decide(conn,'local',cid,assumptions(risk='unknown'))
        with pytest.raises(c.InvalidStateTransition):c.draft(conn,'local',blocked['id'])
        good=c.decide(conn,'local',cid,assumptions())
        draft=c.draft(conn,'local',good['id'])
        assert client.get('/shop/api/products').json()==[]
        row=client.get('/v1/commerce/catalog-stages').json()['categories'][0]
        assert (row['candidates'],row['drafts'],row['published'])==(1,1,0)
        c.add_stock(conn,'local',draft['id'],2)
        assert client.get('/shop/api/products').json()==[]
        c.publish(conn,'local',draft['id'])
        products=client.get('/shop/api/products').json()
        assert len(products)==1 and products[0]['category_id']=='air_purifier'
        assert products[0]['category_name']=='Air purifiers'
        assert set(products[0])=={'id','title','price_cents','stock','category_id','category_name'}
        row=client.get('/v1/commerce/catalog-stages').json()['categories'][0]
        assert (row['drafts'],row['published'],row['in_stock'])==(0,1,1)
    conn.close()


def test_stage_counts_and_public_catalog_respect_tenant(secured):
    client,path,p,auth=secured
    db=connect(path)
    cid=candidate(db,'other')['id']
    decision=c.decide(db,'other',cid,assumptions());draft=c.draft(db,'other',decision['id'])
    c.add_stock(db,'other',draft['id'],1);c.publish(db,'other',draft['id']);db.close()
    local=client.get('/v1/commerce/catalog-stages',headers=auth['viewer']).json()['categories']
    other=client.get('/v1/commerce/catalog-stages',headers=auth['other']).json()['categories']
    assert local[0]['published']==0 and other[0]['published']==1
    assert draft['id'] not in {p['id'] for p in client.get('/shop/api/products').json()}
    assert client.get('/v1/commerce/catalog-stages').status_code==401


def test_unknown_category_is_not_promoted_to_analysis_taxonomy(conn):
    p=product(conn)
    assert catalog.product_category(p)['id']=='other'
    assert catalog.from_source({'dataset':'<untrusted>'})==catalog.OTHER
    result=catalog.stages(c.listing(conn,'commerce_candidates','local'),[p])
    assert result['categories'][-1]['id']=='other' and result['categories'][-1]['published']==1


def test_all_category_seeds_are_idempotent_and_preserve_existing_orders(tmp_path,monkeypatch):
    scripts=Path(__file__).resolve().parents[1]/'scripts';monkeypatch.syspath_prepend(str(scripts))
    spec=importlib.util.spec_from_file_location('six_category_seed',scripts/'seed_commerce.py')
    seed=importlib.util.module_from_spec(spec);spec.loader.exec_module(seed)
    path=tmp_path/'seed.sqlite3';seed.seed(path);db=connect(path)
    products=c.listing(db,'commerce_products','local')
    assert len(products)==7
    assert {catalog.product_category(p)['id'] for p in products}=={v['id'] for v in catalog.CATEGORIES}
    assert all(p['status']=='published' and p['snapshot']['conclusion']=='GO' for p in products)
    assert all(p['snapshot']['data_kind']=='simulation' for p in products)
    original=products[0]
    order=c.checkout(db,'local','before-reseed',c.Checkout(product_id=original['id'],quantity=2))
    before_product=c.row(db,'commerce_products',original['id'],'local')
    before_order=c.row(db,'commerce_orders',order['id'],'local')
    password=db.execute('SELECT password_hash FROM commerce_buyers').fetchone()[0]
    db.close();seed.seed(path);db=connect(path)
    assert len(c.listing(db,'commerce_products','local'))==7
    assert c.row(db,'commerce_products',original['id'],'local')==before_product
    assert c.row(db,'commerce_orders',order['id'],'local')==before_order
    assert db.execute('SELECT password_hash FROM commerce_buyers').fetchone()[0]==password
    assert all(catalog.product_category(p)['id'] in {v['id'] for v in catalog.CATEGORIES} for p in c.listing(db,'commerce_products','local'))
    db.close()
