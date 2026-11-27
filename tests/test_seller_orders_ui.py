"""Execute actual seller order UI with controlled network outcomes."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from xborder_insight import commerce as c, commerce_order_views as views
from test_commerce import product


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for order UI behavior')
def test_order_detail_escape_unknown_values_shipping_and_identity_races(conn):
    p = product(conn)
    conn.execute('UPDATE commerce_products SET title=? WHERE id=?', ('Snapshot <img src=x onerror=alert(1)>', p['id']))
    address = {'recipient': 'Secret Receiver', 'line1': 'Private Street', 'state': 'WA', 'country': 'US'}
    order = c.checkout_items(conn, 'local', 'ui-order', 'ui-fingerprint', [(p['id'], 1)], address=address)
    detail = views.detail(conn, 'local', order['id'], 'owner')
    script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes={};const get=id=>nodes[id]??={id,value:'',textContent:'',innerHTML:'',disabled:false,style:{},dataset:{},isConnected:true,removeAttribute(){},setAttribute(){}};
const document={getElementById:get,querySelectorAll:()=>[],querySelector:()=>null};
const context=vm.createContext({document,window:{addEventListener(){}},location:{search:''},URLSearchParams,console,setTimeout,clearTimeout});
vm.runInContext(fs.readFileSync('src/xborder_insight/commerce_seller.js','utf8'),context);
for(const match of fs.readFileSync('src/xborder_insight/commerce_workbench.html','utf8').matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))vm.runInContext(match[1].replace(/init\(\);\s*$/,''),context);
const run=source=>vm.runInContext(source,context);
run('fixture='+JSON.stringify(DETAIL));
const html=run('renderOrderDetail(fixture)');
assert(html.includes('Snapshot &lt;img'));assert(!html.includes('<img src=x'));
assert(!html.includes('Secret Receiver'));assert(!html.includes('Private Street'));
assert(html.includes('优惠金额</dt><dd>未记录'));assert(html.includes('已登记物流成本</dt><dd>未记录'));
assert(html.includes('本地模拟运单号'));assert(html.includes('未提供 / 未记录'));
run('fixture.display.can_view_delivery=false');assert(!run('renderOrderDetail(fixture)').includes('onclick="loadOrderDelivery'));
run("fixture.status='paid';fixture.refund_pending=true");
const pending=run('renderOrder(fixture)');assert(pending.includes('退款待审核'));assert(pending.includes('暂停发货'));assert(!pending.includes('onclick="shipOrder'));
run('mutations=[];mutate=async(path,body)=>mutations.push({path,body})');
get('tracking-id').value='SIM-TRACK';get('shipping-id').value='';await run("shipOrder('id')");assert.equal(run('mutations.length'),0);
get('shipping-id').value='0';await run("shipOrder('id')");assert.equal(run('mutations[0].body.actual_logistics_cents'),0);
for(const invalid of ['-1','1.5','abc']){get('shipping-id').value=invalid;await run("shipOrder('id')")}
assert.equal(run('mutations.length'),1);
// Access generation changes invalidate an old response even if the same key is entered again.
get('key').value='old-key';
run('api=()=>new Promise(resolve=>resolveDelivery=resolve)');
const button={disabled:false,isConnected:true};context.button=button;
const old=run("loadOrderDelivery('id',button)");
run('sellerOrderAccessGeneration++');
run("resolveDelivery({address:{recipient:'Must not appear',line1:'Forbidden'}})");await old;
assert(!get('delivery-id').innerHTML.includes('Must not appear'));
// Older filter requests cannot overwrite a later query.
run('pendingQueries=[];api=()=>new Promise(resolve=>pendingQueries.push(resolve))');
const first=run('loadOrders()');get('order-status').value='paid';const second=run('loadOrders()');
run('pendingQueries[1]({items:[],next_cursor:null})');await second;
const latest=get('orders').innerHTML;run('pendingQueries[0]({items:[fixture],next_cursor:null})');await first;
assert.equal(get('orders').innerHTML,latest);
// Closing and reopening retries failed detail loads; it does not submit a mutation.
const target={textContent:'',innerHTML:''},details={open:true,isConnected:true,dataset:{},querySelector:()=>target};context.details=details;
run("api=async()=>{throw Error('temporary')}");await run("loadOrderSource(details,'id')");
assert(target.textContent.includes('重新展开'));assert(!details.dataset.loaded);
run('api=async()=>fixture');await run("loadOrderSource(details,'id')");assert.equal(details.dataset.loaded,'true');
console.log('Snapshot escaping, unknown values, viewer delivery, shipping validation, identity/query races and detail retries passed');
'''.replace('DETAIL', json.dumps(detail, ensure_ascii=False))
    result = subprocess.run(['node', '--input-type=commonjs', '-e', '(async()=>{' + script + '})().catch(e=>{console.error(e);process.exit(1)})'],
                            cwd=Path(__file__).resolve().parents[1], text=True, encoding='utf-8', capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
