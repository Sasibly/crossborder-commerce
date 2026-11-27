"""Separate connection, domain query and JSON costs in a disposable fixture."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from commerce_ops_fixtures import seed
from xborder_insight import commerce_queries as q
from xborder_insight.commerce_ops import latency_summary
from xborder_insight.db.connection import connect


def run(view):
    with TemporaryDirectory(prefix='commerce-query-profile-') as directory:
        path=Path(directory)/'profile.sqlite3';seed(path,orders=1000)
        opened=[];queried=[];encoded=[];sizes=[];counts=[]
        for index in range(25):
            start=time.perf_counter();conn=connect(path);t1=time.perf_counter()
            statements=[];conn.set_trace_callback(statements.append)
            try:
                page=q.orders(conn,'local',**({'view':'summary'} if view=='summary' else {}))
                t2=time.perf_counter();payload=json.dumps(page,separators=(',',':')).encode();t3=time.perf_counter()
            finally:conn.close()
            if index>=5:
                opened.append((t1-start)*1000);queried.append((t2-t1)*1000);encoded.append((t3-t2)*1000)
                sizes.append(len(payload));counts.append(len(statements))
        def stats(values):return latency_summary(values,sum(values)/1000)
        return {'measurement_kind':'observed_local_query_profile','fixture_data_kind':'simulation','view':view,
                'orders':1000,'page_size':30,'samples':20,'connection':stats(opened),'query_and_projection':stats(queried),
                'json_encoding':stats(encoded),'payload_bytes':sizes[0],'sql_statements_per_page':counts[0],
                'scope':'Domain query and standard-library JSON encoding, not end-to-end HTTP latency.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--view',choices=['full','summary'],default='full')
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if args.output.exists():raise FileExistsError('请保留原始报告并使用新文件名')
    result=run(args.view)
    with args.output.open('x',encoding='utf-8') as target:json.dump(result,target,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=False,indent=2))
