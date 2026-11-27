"""Run actual shop scripts with controlled payment responses."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for buyer UI')
def test_payment_button_pending_only_busy_retry_and_csrf():
    script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes={};const get=id=>nodes[id]??={id,value:'',textContent:'',innerHTML:'',disabled:false,hidden:false,style:{}};
const context=vm.createContext({document:{getElementById:get},window:{addEventListener(){}},console,setTimeout,clearTimeout,AbortController});
const html=fs.readFileSync('src/xborder_insight/commerce_shop_v2.html','utf8');
for(const match of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))vm.runInContext(match[1].replace(/init\(\);\s*$/,''),context);
const run=s=>vm.runInContext(s,context);
run(`user={id:'buyer',csrf:'buyer-csrf',email:'demo@example.test'};
 fixture={id:'order-1',status:'pending',amount_cents:3200,items:[],tracking:null};
 api=async path=>path==='/my/orders'?[fixture]:[];`);
await run('loadOrders()');
assert(get('orders').innerHTML.includes('data-pay-order="order-1"'));
assert(get('orders').innerHTML.includes('Pay $32.00 (simulated)'));
for(const status of ['paid','shipped','completed','cancelled','refunded']){
 run(`fixture.status='${status}'`);await run('loadOrders()');
 assert(!get('orders').innerHTML.includes('data-pay-order'));
}
// Execute the real API and busy handlers: only one request while in flight.
run(`api=${html.match(/async function api\([\s\S]*?\n/)[0].trim().replace('async function api','async function')};
 refreshBuyer=async()=>{};loadCatalog=async()=>{};requests=[];
 fetch=(url,options)=>{requests.push({url,options});return new Promise(resolve=>reply=resolve)};`);
context.button={disabled:false};
const first=run("payOrder('order-1',button)");assert(context.button.disabled);
await run("payOrder('order-1',button)");assert.equal(run('requests.length'),1);
assert.equal(run('requests[0].url'),'/shop/api/my/orders/order-1/pay');
assert.equal(run("requests[0].options.headers['X-CSRF-Token']"),'buyer-csrf');
assert.equal(run('requests[0].options.body'),'{}');
run(`reply({ok:false,status:500,json:async()=>({message:'Temporary failure'})})`);
for(let i=0;i<10;i++)await Promise.resolve();
assert.equal(run('requests[1].url'),'/shop/api/my/orders/order-1');
run(`reply({ok:true,status:200,json:async()=>({status:'pending'})})`);await first;
assert(!context.button.disabled);assert(get('message').textContent.includes('still pending'));
const retry=run("payOrder('order-1',button)");
run(`reply({ok:true,status:200,json:async()=>({status:'paid'})})`);await retry;
assert(!context.button.disabled);assert(get('message').textContent.includes('Simulated payment completed'));
// A successful submission is not reported as failed when subsequent display refresh fails.
run(`api=async()=>({status:'paid'});refreshBuyer=async()=>{throw Error('refresh unavailable')}`);
await run("payOrder('order-1',button)");
assert(get('message').textContent.includes('Simulated payment completed'));
assert(get('message').textContent.includes('page could not refresh'));
run(`api=async()=>({status:'refunded'});refreshBuyer=async()=>{}`);
await run("payOrder('order-1',button)");
assert(get('message').textContent.includes('already been refunded'));
assert(!get('message').textContent.includes('can now ship'));
// If the POST response was lost, reconcile using the owned order before suggesting a retry.
run(`api=async path=>{if(path.endsWith('/pay'))throw Error('lost response');return {status:'paid'}}`);
await run("payOrder('order-1',button)");assert(get('message').textContent.includes('Simulated payment completed'));
run(`api=async()=>{throw Error('offline')}`);
await run("payOrder('order-1',button)");assert(get('message').textContent.includes('result is unknown'));
assert(!fs.readFileSync('src/xborder_insight/commerce_seller.js','utf8').includes("mutate('/orders/${o.id}/pay'"));
'''
    result=subprocess.run(['node','--input-type=commonjs','-e','(async()=>{'+script+'})().catch(e=>{console.error(e);process.exit(1)})'],
                          cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,encoding='utf-8',timeout=20)
    assert result.returncode==0,result.stderr
