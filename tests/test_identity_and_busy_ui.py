"""Delayed network responses cannot cross identities or release another operation."""
from pathlib import Path
import shutil
import subprocess

import pytest


HARNESS = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes={},buttons=[];
const get=id=>nodes[id]??={id,value:'',textContent:'',innerHTML:'',disabled:false,hidden:false,dataset:{},style:{},
 reset(){},setAttribute(){},removeAttribute(){},scrollIntoView(){}};
const context=vm.createContext({document:{getElementById:get,querySelectorAll:sel=>sel==='[data-buyer-action]'?buttons:[],querySelector:()=>null},
 window:{addEventListener(){}},console,setTimeout,clearTimeout,URLSearchParams,AbortController});
const run=s=>vm.runInContext(s,context);
function loadShop(){for(const match of fs.readFileSync('src/xborder_insight/commerce_shop_v2.html','utf8').matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))run(match[1].replace(/init\(\);\s*$/,''))}
function loadSeller(){run(fs.readFileSync('src/xborder_insight/commerce_seller.js','utf8'));
 for(const match of fs.readFileSync('src/xborder_insight/commerce_workbench.html','utf8').matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g))run(match[1].replace(/init\(\);\s*$/,''))}
'''


def execute(script):
    result=subprocess.run(['node','--input-type=commonjs','-e','(async()=>{'+HARNESS+script+'})().catch(e=>{console.error(e);process.exit(1)})'],
                          cwd=Path(__file__).resolve().parents[1],text=True,encoding='utf-8',capture_output=True,timeout=20)
    assert result.returncode==0,result.stderr


pytestmark=pytest.mark.skipif(not shutil.which('node'),reason='Node required for UI races')


def test_buyer_previous_identity_responses_and_401_cannot_restore_private_state():
    execute(r'''
loadShop();run(`setBuyerSession({id:'A',csrf:'csrf-A'});pending=[];fetch=(url,options)=>new Promise(resolve=>pending.push({url,options,resolve}));`);
const reads=Promise.allSettled([run('loadOrders()'),run('loadAddresses()'),run('refreshCart()')]);
run("setBuyerSession({id:'B',csrf:'csrf-B'})");
run(`for(const request of pending){const data=request.url.endsWith('/checkout-preview')?{items:[{title:'A-private-cart'}],cart_fingerprint:'A'}:request.url.endsWith('/my/refunds')?[]:[{id:'A-private',status:'paid',items:[],amount_cents:100,address:{line1:'A-private-street'},line1:'A-private-street'}];request.resolve({ok:true,json:async()=>data})}`);
assert((await reads).every(r=>r.status==='rejected'&&r.reason.stale));
assert(!get('orders').innerHTML.includes('A-private'));assert(!get('address').innerHTML.includes('A-private'));
assert.equal(run('cartItems.length'),0);assert.equal(run('user.id'),'B');
// Even a late authentication failure from A must not sign out B.
run(`pending=[];setBuyerSession({id:'A',csrf:'csrf-A'})`);context.refreshButton={id:'refresh',disabled:false};
const old=run("busy(refreshButton,()=>api('/addresses'))");
run("setBuyerSession({id:'B',csrf:'csrf-B'});pending[0].resolve({ok:false,status:401,json:async()=>({message:'A expired'})})");await old;
assert.equal(run('user.id'),'B');assert(!get('message').textContent.includes('A expired'));
// A -> B -> A must invalidate old requests too, even with the same user ID.
run('pending=[]');const same=run("api('/addresses')").catch(e=>e);
run("setBuyerSession({id:'A'});setBuyerSession({id:'B'});pending[0].resolve({ok:true,json:async()=>[]})");
assert((await same).stale);
''')


def test_buyer_busy_state_survives_other_operations_and_replaced_buttons():
    execute(r'''
loadShop();run("setBuyerSession({id:'A'});cartItems=[{status:'published',quantity:1,stock:5}]");
context.checkout=get('checkout');context.other={id:'refresh',disabled:false};
const checkout=run('busy(checkout,()=>new Promise(resolve=>releaseCheckout=resolve))');
assert(get('checkout').disabled);await run('busy(other,async()=>{})');assert(get('checkout').disabled);
run('updateCheckoutState()');assert(get('checkout').disabled);
run('releaseCheckout()');await checkout;assert(!get('checkout').disabled);
context.first={dataset:{buyerAction:'order-1'},disabled:false};buttons.push(context.first);
const payment=run('busy(first,()=>new Promise(resolve=>releasePayment=resolve))');
context.replacement={dataset:{buyerAction:'order-1'},disabled:false};buttons.push(context.replacement);
run('syncBuyerButtons()');assert(context.replacement.disabled);
run('submits=0');await run('busy(replacement,async()=>{submits++})');assert.equal(run('submits'),0);
run('releasePayment()');await payment;assert(!context.replacement.disabled);
// A late completion must not remove a new account's operation with the same key.
const old=run('busy(first,()=>new Promise(resolve=>releaseOld=resolve))');run("setBuyerSession({id:'B'})");
const current=run('busy(replacement,()=>new Promise(resolve=>releaseCurrent=resolve))');
run('releaseOld()');await old;assert(context.replacement.disabled);
run('releaseCurrent()');await current;assert(!context.replacement.disabled);
''')


def test_seller_old_key_cannot_restore_products_or_role_and_clears_review_data():
    execute(r'''
loadSeller();run(fs.readFileSync('src/xborder_insight/review_analysis.js','utf8'));
get('key').value='old-owner';
run(`state={candidates:[{id:'private-A'}],products:[],decisions:[]};reviewRun={id:'private-analysis'};importedReviews=[{body:'private-review'}];
 pending=[];fetch=(url,options)=>new Promise(resolve=>pending.push({url,options,resolve}));`);
const request=run("api('/v1/commerce/state')").catch(e=>e);
get('key').value='new-viewer';run('clearSellerIdentity()');
run("pending[0].resolve({ok:true,json:async()=>({products:[{title:'private-A'}]})})");assert((await request).stale);
assert.equal(run('state.candidates.length'),0);assert.equal(run('reviewRun'),null);assert.equal(run('importedReviews'),null);
// me has already returned, but audit is still pending when the Key changes.
run(`refreshSources=async()=>{};api=async path=>path.endsWith('/payment-policy')?{version:0}:path.endsWith('/me')?{role:'owner',actor:'old-owner'}:{status_counts:{}};
 loadAudit=()=>new Promise(resolve=>releaseAudit=resolve);`);
const management=run('refreshManagement()').catch(e=>e);
for(let i=0;i<8;i++)await Promise.resolve();
get('key').value='another-viewer';run('clearSellerIdentity();releaseAudit()');
assert((await management).stale);assert.equal(run('sellerRole'),'viewer');
assert(!get('seller-identity').textContent.includes('old-owner'));
''')
