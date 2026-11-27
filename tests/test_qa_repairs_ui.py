"""Deterministic network faults and races for the independent QA report."""
from test_identity_and_busy_ui import execute

def test_seller_write_reentry_refresh_failure_and_identity_lock():
    execute(r'''
context.crypto=require('crypto');loadSeller();
run(`refresh=()=>new Promise(resolve=>releaseRead=resolve);calls=0;api=()=>new Promise(resolve=>{calls++;releaseWrite=resolve})`);
const first=run("mutate('/products/p/stock',{quantity:1})");
await run("mutate('/products/p/stock',{quantity:1})");assert.equal(run('calls'),1);
run('releaseWrite({})');for(let i=0;i<8;i++)await Promise.resolve();
await run("mutate('/products/p/stock',{quantity:1})");assert.equal(run('calls'),1);
run('releaseRead(false)');await first;assert(get('message').textContent.includes('已保存'));
assert(get('message').textContent.includes('读取失败'));
const old=run("mutate('/products/p/stock',{quantity:1})");const releaseOld=run('releaseWrite');
get('key').value='B';run('clearSellerIdentity()');
const next=run("mutate('/products/p/stock',{quantity:1})");
assert.equal(run('calls'),3);releaseOld({});for(let i=0;i<8;i++)await Promise.resolve();
run('releaseRead(true)');await old;assert.equal(run('sellerOperationLocks.size'),1);
run('releaseWrite({})');for(let i=0;i<8;i++)await Promise.resolve();run('releaseRead(true)');await next;
''')

def test_seller_finance_metadata_and_integrity_scrub():
    execute(r'''
loadSeller();const html=run("renderOrderActions({id:'o',status:'completed',items:[]})");
assert(html.includes('data-seller-permission="finance"'));
run("api=async()=>[{id:'r',status:'requested'}]");await run('refreshRefunds()');
assert(/data-seller-permission="finance"[^>]*onclick="reviewRefund\('r',false\)/.test(get('refunds').innerHTML));
get('integrity').textContent='A-private';run('policyVersion=8');get('key').value='B';run('clearSellerIdentity()');
assert.equal(get('integrity').textContent,'');assert.equal(run('policyVersion'),0);
''')

def test_buyer_independent_reads_and_session_retry():
    execute(r'''
loadShop();run("setBuyerSession({id:'A'});seen=[];refreshCart=async()=>{seen.push('cart');throw Error('cart failed')};loadAddresses=async()=>{seen.push('address')};loadOrders=async()=>{seen.push('orders')};loadCatalog=async()=>{seen.push('catalog');throw Error('catalog failed')}");
await run('refreshAll()').catch(()=>{});assert.deepEqual(Array.from(run('seen')).sort(),['address','cart','catalog','orders']);
run('seen=[]');await run("$('refresh-orders').onclick({currentTarget:$('refresh-orders')})");assert.deepEqual(Array.from(run('seen')),['orders']);
run("api=async()=>{const e=Error('server down');e.status=500;throw e}");await run('init()');
assert(get('auth-form').hidden);assert(get('identity').textContent.includes('Retry session'));
run("api=async path=>{if(path==='/account/me')return {id:'A',email:'A'};return {instance:'test',shop_tenant:'local'}};refreshAll=async()=>{}");
await run('init()');assert.equal(run('user.id'),'A');assert(!get('auth-form').hidden===false);
''')

def test_seller_modules_isolate_errors_retry_and_dataset_recovery():
    execute(r'''
context.location={hash:'#overview',search:'?category=pet_fountain'};loadSeller();
run(`sellerInitialized=true;loadSellerShared=async()=>{};calls=[];fail=true;loadSellerDatasets=async()=>{calls.push('datasets');if(fail)throw Error('datasets failed')};refreshReviewAnalyses=async()=>{calls.push('analyses')};loadOrders=async()=>{calls.push('orders')};refreshRefunds=async()=>{calls.push('refunds')};api=async path=>{calls.push(path);return {status_counts:{}}}`);
assert(await run("loadSellerModule('overview')"));assert(!run('calls').includes('orders'));
assert(!await run("loadSellerModule('insights')"));assert(run('calls').includes('analyses'));
run('fail=false');assert(await run("loadSellerModule('insights')"));
const count=run('calls.length');await run("loadSellerModule('insights')");assert.equal(run('calls.length'),count);
assert(await run("loadSellerModule('orders')"));assert(run('calls').includes('refunds'));
''')

def test_progress_retry_is_bounded_and_old_task_never_reschedules():
    execute(r'''
loadSeller();run(fs.readFileSync('src/xborder_insight/review_analysis.js','utf8'));
run(`scheduled=[];setTimeout=(fn,ms)=>{scheduled.push({fn,ms});return scheduled.length};clearTimeout=()=>{};api=async()=>{throw Error('offline')};reviewGeneration=7`);
get('review-history').value='task';
for(let i=0;i<4;i++)await run("pollReviewProgress('task',7)");
assert.deepEqual(Array.from(run('scheduled.map(s=>s.ms)')),[1000,2000,4000]);assert(get('message').textContent.includes('暂停'));
run('reviewGeneration=8');await run("pollReviewProgress('task',7)");assert.equal(run('scheduled.length'),3);
''')

def test_scenarios_latest_request_wins_even_A_B_A():
    execute(r'''
loadSeller();get('candidate').value='A';run('pending=[];api=()=>new Promise(resolve=>pending.push(resolve))');
const old=run('loadMetricScenarios()');get('candidate').value='B';const middle=run('loadMetricScenarios()');get('candidate').value='A';const latest=run('loadMetricScenarios()');
run('pending[2]([])');await latest;run("pending[0]([{id:'old-A',snapshot:{metric_snapshot:{},application:'reference_only'}}])");await old;
assert.equal(run('scenarioRows.length'),0);run('pending[1]([])');await middle;
''')

def test_audit_append_does_not_duplicate_cursor():
    execute(r'''
loadSeller();get('audit').insertAdjacentHTML=function(position,html){this.innerHTML+=html};
run('pending=[];api=()=>new Promise(resolve=>pending.push(resolve))');const a=run('loadAudit(true)'),b=run('loadAudit(true)');
assert.equal(run('pending.length'),1);run("pending[0]({items:[{id:1,action:'unique-row'}],next_after:1})");await Promise.all([a,b]);
assert.equal(get('audit').innerHTML.split('unique-row').length,2);
''')

def test_hanging_reads_and_writes_timeout_without_replay_and_keep_retry_key():
    execute(r'''
context.crypto=require('crypto');loadSeller();
run(`timers=[];setTimeout=(fn,ms)=>{timers.push({fn,ms});return timers.length};clearTimeout=()=>{};calls=[];fetch=(url,options)=>{calls.push(options);return new Promise(()=>{})}`);
const read=run("api('/v1/commerce/state')").catch(e=>e);assert.equal(run('timers[0].ms'),30000);run('timers[0].fn()');assert((await read).timeout);
const first=run("api('/v1/commerce/products/p/stock',{quantity:1})").catch(e=>e);assert.equal(run('timers[1].ms'),120000);run('timers[1].fn()');assert((await first).message.includes('未知'));
const key=run("calls[1].headers['Idempotency-Key']");
const retry=run("api('/v1/commerce/products/p/stock',{quantity:1})").catch(e=>e);assert.equal(run("calls[2].headers['Idempotency-Key']"),key);run('timers[2].fn()');await retry;
assert.equal(run('calls.length'),3);
''')
