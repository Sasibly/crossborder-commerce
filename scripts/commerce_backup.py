"""Back up a live SQLite DB or restore its backup to a NEW database file."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from xborder_insight.db.backup import snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['backup','restore'])
    parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path)
    args=parser.parse_args()
    result=snapshot(args.source,args.destination)
    print(json.dumps({'action':args.action,**result},ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
