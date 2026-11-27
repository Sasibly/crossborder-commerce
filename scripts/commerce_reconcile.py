"""Read-only invariant check; exits 2 on inconsistencies and never repairs data."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from xborder_insight.commerce_queries import integrity


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,default=Path(__file__).resolve().parents[1]/'data'/'commerce.sqlite3')
    parser.add_argument('--tenant',default='local')
    args=parser.parse_args()
    conn=sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro',uri=True,isolation_level=None)
    conn.row_factory=sqlite3.Row
    try:
        conn.execute('BEGIN')
        result=integrity(conn,args.tenant)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    finally:
        conn.close()
    raise SystemExit(0 if result['ok'] else 2)
