"""Idempotently seed fictional demo products and a buyer; never reset an existing password."""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from xborder_insight import buyers as b, commerce as c
from xborder_insight.commerce_api import evidence
from xborder_insight.db import migrate
from xborder_insight.db.connection import connect,transaction

DEMO_EMAIL='demo-buyer@example.test'
DEMO_PASSWORD='demo-pass-local-2026'

# All costs and risk-clear flags below are fictional walkthrough inputs.
# Tuple: name, category, USD price, CNY purchase, USD logistics/aftersales/acquisition (all cents).
DEMO_PRODUCTS=(
    ('DEMO / Quiet fountain','pet_fountain',3000,7000,500,100,300),
    ('DEMO / Easy-clean fountain','pet_fountain',3500,7000,500,100,300),
    ('DEMO / Compact air purifier','air_purifier',9900,21000,1500,500,1500),
    ('DEMO / Semi-automatic coffee machine','coffee_machine',14900,42000,2000,800,2000),
    ('DEMO / Electric kettle','electric_kettle',4500,7000,600,200,600),
    ('DEMO / Robot vacuum','robot_vacuum',19900,70000,2500,1000,2500),
    ('DEMO / Wireless charger','wireless_charger',2900,3500,400,100,400),
)


async def reports():
    categories=sorted({p[1] for p in DEMO_PRODUCTS})
    return dict(zip(categories,await asyncio.gather(*(evidence(category) for category in categories))))


def seed(path):
    source_reports=asyncio.run(reports())
    conn=connect(path)
    try:
        migrate.upgrade(conn)
        with transaction(conn):
            for name,category,price,purchase,logistics,aftersales,acquisition in DEMO_PRODUCTS:
                existing=conn.execute('''SELECT p.id FROM commerce_products p JOIN commerce_decisions d ON p.decision_id=d.id
                    JOIN commerce_candidates c ON d.candidate_id=c.id WHERE p.tenant='local' AND c.name=?''',(name,)).fetchone()
                if existing:
                    continue
                theme=source_reports[category]['themes'][0]
                candidate=c.create_candidate(conn,'local',c.Candidate(name=name,dataset=category,theme_id=theme['theme_id']),
                    {'theme':theme,'dataset':category,'data_kind':'synthetic_samples','analysis_mode':'offline_rule_baseline','demo_seed_version':'six-category-v1'})
                decision=c.decide(conn,'local',candidate['id'],c.Assumptions(price_cents=price,purchase_cny_cents=purchase,cny_per_usd='7',
                    logistics_cents=logistics,payment_bps=300,payment_fixed_cents=30,aftersales_cents=aftersales,acquisition_cents=acquisition,
                    risk='clear',source_note='Synthetic category demo costs and risk-clear walkthrough; no real supplier, market or compliance verification.'))
                product=c.draft(conn,'local',decision['id'])
                c.add_stock(conn,'local',product['id'],20)
                c.publish(conn,'local',product['id'])
            if not conn.execute("SELECT 1 FROM commerce_buyers WHERE tenant='local' AND email=?",(DEMO_EMAIL,)).fetchone():
                b.register(conn,'local',b.Credentials(email=DEMO_EMAIL,password=DEMO_PASSWORD))
        print('Demo seed ready. Buyer login and fictional password are documented in COMMERCE-README.md.')
    finally:
        conn.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=Path(__file__).resolve().parents[1]/'data'/'commerce.sqlite3')
    seed(parser.parse_args().db)
