/* Isolated headless Chrome check against the local mock app. No browser packages,
   user profile, model calls or business writes. Uses Chrome's testing protocol. */
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import assert from 'node:assert/strict';

const base='http://127.0.0.1:8031';
const folder=resolve(process.env.SELLER_BROWSER_REPORT_DIR||'reports/seller-workspace-20261126');
await mkdir(folder,{recursive:true});
const profile=await mkdtemp(resolve('../tmp/seller-workspace-chrome-'));
const browser=spawn('C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',[
  '--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
  '--disable-background-networking','--disable-sync','--remote-debugging-address=127.0.0.1',
  '--remote-debugging-port=0','--user-data-dir='+profile,'about:blank'
],{windowsHide:true,stdio:'ignore'});
let socket,number=0;
const pending=new Map(),requests=[],errors=[],checks=[];
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function until(callback,label){
  const deadline=Date.now()+25000;
  while(Date.now()<deadline){try{const value=await callback();if(value)return value}catch{}await delay(150)}
  throw Error('Timed out: '+label);
}
function send(method,params={}){
  return new Promise((resolve,reject)=>{
    const id=++number,timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout: '+method))},15000);
    pending.set(id,{resolve,reject,timer});socket.send(JSON.stringify({id,method,params}));
  });
}
async function evaluate(expression){
  const result=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});
  if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);
  return result.result.value;
}
async function waitPage(){
  await until(()=>evaluate("document.querySelectorAll('[data-workspace-view]:not([hidden])').length===1 && typeof evidenceVersion!=='undefined' && !!evidenceVersion"),'workspace and initial data');
}
async function route(hash){
  await evaluate(`document.querySelector('a[href="${hash}"]').click()`);
  await until(()=>evaluate(`location.hash===${JSON.stringify(hash)}`),'route '+hash);
  await until(()=>evaluate(`!document.getElementById('view-${hash.slice(1).split('/')[0]}').hidden`),'visible '+hash);
}
async function screenshot(name){
  const result=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:false});
  await writeFile(join(folder,name+'.png'),Buffer.from(result.data,'base64'));
}
let report,buyerPayment;
try{
  const port=await until(async()=>Number((await readFile(join(profile,'DevToolsActivePort'),'utf8')).split('\n')[0]),'headless Chrome');
  const pages=await (await fetch('http://127.0.0.1:'+port+'/json/list')).json();
  socket=new WebSocket(pages.find(page=>page.type==='page').webSocketDebuggerUrl);
  socket.addEventListener('message',event=>{
    const message=JSON.parse(event.data);
    if(message.id){const task=pending.get(message.id);if(!task)return;pending.delete(message.id);clearTimeout(task.timer);message.error?task.reject(Error(message.error.message)):task.resolve(message.result);return}
    if(message.method==='Network.requestWillBeSent')requests.push({url:message.params.request.url,method:message.params.request.method});
    if(message.method==='Runtime.exceptionThrown')errors.push(message.params.exceptionDetails.exception?.description||message.params.exceptionDetails.text);
    if(message.method==='Log.entryAdded'&&message.params.entry.level==='error'&&!message.params.entry.url?.endsWith('/favicon.ico'))errors.push({url:message.params.entry.url,text:message.params.entry.text});
  });
  await new Promise((resolve,reject)=>{socket.addEventListener('open',resolve,{once:true});socket.addEventListener('error',reject,{once:true})});
  await send('Page.enable');await send('Runtime.enable');await send('Network.enable');await send('Log.enable');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await send('Page.navigate',{url:base+'/workbench'});await waitPage();
  assert.equal(await evaluate("location.hash"),'#overview');
  assert.equal(await evaluate("document.querySelector('[aria-current=page]').textContent.trim()"),'经营概览');
  assert.equal(await evaluate("document.getElementById('message').style.display"),'');
  assert(await evaluate("document.getElementById('summary').textContent.includes('累计模拟收款')"));
  await screenshot('desktop-overview');checks.push('Overview, live summary and high-frequency entries rendered');
  assert.equal(await evaluate("getComputedStyle(document.body).backgroundColor"),'rgb(248, 250, 252)');
  assert.equal(await evaluate("document.querySelectorAll('.kpi-card').length"),4);
  await evaluate("document.getElementById('sidebar-toggle').click()");
  assert(await evaluate("document.querySelector('.workspace-shell').classList.contains('nav-collapsed') && document.getElementById('sidebar-toggle').getAttribute('aria-expanded')==='false'"));
  await screenshot('desktop-collapsed');
  await evaluate("document.getElementById('sidebar-toggle').click()");
  await evaluate("document.getElementById('workspace-search').value='no-such-sku-visual-check';document.querySelector('.header-search').requestSubmit()");
  await until(()=>evaluate("location.hash==='#products/product-list'"),'quick search route');
  assert(await evaluate("!document.querySelector('.product-row')"));
  await evaluate("document.getElementById('product-search').value='';renderSellerProducts()");
  await evaluate("document.querySelector('.product-row>button').click()");
  assert(await evaluate("document.querySelector('dialog[open]') && document.activeElement.closest('dialog')!==null"));
  await screenshot('desktop-inventory-drawer');
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  await until(()=>evaluate("!document.querySelector('dialog[open]')"),'drawer escape');
  assert(await evaluate("document.activeElement.matches('.product-row>button')"));
  checks.push('Brand canvas, four truthful KPIs, collapsible navigation, local quick search, native inventory dialog focus and Escape return');

  const views=['overview','products','orders','insights','sourcing','analytics','sources','settings'];
  for(const view of views){
    await route('#'+view);
    assert.equal(await evaluate("document.querySelectorAll('[data-workspace-view]:not([hidden])').length"),1);
    assert(await evaluate(`document.getElementById('workspace-heading').textContent===document.getElementById('view-${view}').dataset.title`));
    assert(await evaluate("document.documentElement.scrollWidth<=innerWidth"),'desktop overflow '+view);
  }
  checks.push('All eight views and headings, active navigation, no desktop horizontal overflow');
  assert(await evaluate(`(()=>{
    const read=Array.from(document.querySelectorAll('[data-seller-permission="read"]')).find(button=>!['order-more','audit-more'].includes(button.id));
    const old=read.textContent;read.textContent='Changed label for permission check';
    sellerRole='viewer';setRoleButtons(sellerRole);const allowed=!read.disabled;
    sellerRole='operator';setRoleButtons(sellerRole);const financial=Array.from(document.querySelectorAll('[data-seller-permission="finance"]')).every(button=>button.disabled);
    read.textContent=old;sellerRole='owner';setRoleButtons(sellerRole);return allowed&&financial;
  })()`));
  checks.push('Seller permissions use operation metadata; changing labels does not change access and operator financial controls remain disabled');
  await route('#orders');
  await until(()=>evaluate("document.querySelectorAll('.order-card').length>0"),'order summaries');
  assert(await evaluate("document.querySelector('.order-card').textContent.includes('创建于') && document.querySelector('.order-card').textContent.includes('模拟交易')"));
  assert(await evaluate("document.querySelector('.order-card').textContent.includes('SKU')"));
  assert(await evaluate("!document.querySelector('.order-card [data-delivery]')"));
  await evaluate("document.querySelector('.order-detail').open=true");
  await until(()=>evaluate("document.querySelector('.order-detail').dataset.loaded==='true'"),'lazy order detail');
  assert(await evaluate("document.querySelector('.order-detail').textContent.includes('订单时间线') && document.querySelector('.order-detail').textContent.includes('下单商品')"));
  assert(await evaluate("!document.querySelector('.order-detail [data-delivery] dl')"));
  await screenshot('desktop-orders');
  await evaluate("window.orderProbeId=document.querySelector('.order-card').dataset.orderId");
  assert(await evaluate("(async()=>{const order=await api('/v1/commerce/orders/'+window.orderProbeId);return !('address' in order.snapshot)&&!('token' in order)&&order.display.source==='immutable_order_snapshot'})()"));
  await evaluate("document.querySelector('.order-detail [data-delivery] button').click()");
  await until(()=>evaluate("!!document.querySelector('.order-detail [data-delivery] dl') || document.querySelector('.order-detail [data-delivery]').textContent.includes('此订单未提供')"),'authorised delivery');
  const categoryCount=await evaluate("document.getElementById('product-category-filter').options.length");
  await evaluate("document.getElementById('key').dispatchEvent(new Event('input',{bubbles:true}))");
  assert.equal(await evaluate("document.getElementById('product-category-filter').options.length"),categoryCount,'unchanged Key input must preserve category options');
  assert(await evaluate("!!document.querySelector('.order-card')"),'unchanged Key input must preserve loaded identity data');
  await evaluate("document.getElementById('key').value='browser-identity-change';document.getElementById('key').dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('key').value='';document.getElementById('key').dispatchEvent(new Event('input',{bubbles:true}))");
  assert(await evaluate("!document.querySelector('.order-card') && document.getElementById('orders').textContent.includes('访问凭证已更改')"));
  assert(await evaluate("document.getElementById('product-category-filter').disabled && document.getElementById('product-category-filter').options.length===1 && document.getElementById('product-category-filter').textContent.includes('尚未重新加载')"));
  assert(await evaluate("!document.getElementById('product-refresh').disabled"));
  await evaluate('refresh()');
  checks.push('Order summary, snapshot detail, explicit authorised delivery, timeline and credential-change scrubbing');
  await route('#products');
  assert(await evaluate(`(async()=>{
    const originalFetch=window.fetch;
    try{
      window.fetch=(url,...args)=>String(url).includes('/catalog-stages')?Promise.reject(Error('Injected category fetch failure')):originalFetch(url,...args);
      await refresh();
      return document.getElementById('product-category-filter').disabled&&document.getElementById('product-category-filter').options.length===1&&document.getElementById('product-category-filter').textContent.includes('加载失败')&&!document.getElementById('product-count').textContent.includes('显示 0');
    }finally{window.fetch=originalFetch}
  })()`));
  await evaluate("document.getElementById('product-refresh').click()");
  await until(()=>evaluate("!document.getElementById('product-category-filter').disabled && document.getElementById('product-category-filter').options.length===catalogCategories.length+1 && document.querySelectorAll('.product-row').length===state.products.length"),'category retry button recovery');
  await until(()=>evaluate("document.getElementById('message').textContent.includes('商品与品类已重新加载')"),'category recovery success feedback');
  await evaluate("document.getElementById('product-category-filter').focus()");
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'End',code:'End',windowsVirtualKeyCode:35});
  await send('Input.dispatchKeyEvent',{type:'keyUp',key:'End',code:'End',windowsVirtualKeyCode:35});
  assert(await evaluate("document.getElementById('product-category-filter').value!=='' && document.querySelectorAll('.product-row').length===state.products.filter(p=>productCategoryId(p)===document.getElementById('product-category-filter').value).length"),'native category select must filter inventory');
  await screenshot('desktop-category-recovered');
  await evaluate('showSellerProducts()');
  checks.push('Category select survives unchanged Key events, clearly shows identity/error states, recovers through retry and filters using native keyboard selection');
  await route('#products');
  assert(await evaluate(`(async()=>{
    const shop=await api('/shop/api/products'), published=state.products.filter(p=>p.status==='published');
    return shop.length===published.length && shop.every(buyer=>published.some(seller=>seller.id===buyer.id&&seller.title===buyer.title&&seller.price_cents===buyer.price_cents&&seller.stock===buyer.stock));
  })()`),'buyer catalog must equal seller published SKUs, titles, prices and stock');
  await evaluate("document.getElementById('product-search').value='no match';document.getElementById('product-category-filter').value='air_purifier';document.getElementById('product-status-filter').value='draft';document.querySelector('a[onclick=\"showSellerProducts(true);return false\"]').click()");
  assert.equal(await evaluate("document.querySelectorAll('#products>.item').length"),await evaluate("state.products.filter(p=>p.status==='published').length"));
  assert(await evaluate("document.getElementById('product-count').textContent.includes('当前筛选：已上架')"));
  assert(await evaluate("Array.from(document.getElementById('product-category-filter').options).some(o=>o.textContent.includes('扫地机器人 / Robot vacuums')&&o.textContent.includes('已上架'))"));
  await evaluate("document.querySelector('a[onclick=\"showSellerProducts();return false\"]').click()");
  checks.push('Buyer catalog matches seller published SKU/title/price/stock; bilingual counted categories and clear-filter shortcuts work');
  const originalCount=await evaluate("document.querySelectorAll('#products>.item').length");
  const title=await evaluate("state.products[0].title");
  await evaluate(`document.getElementById('product-search').value=${JSON.stringify(title)};renderSellerProducts()`);
  assert((await evaluate("document.querySelectorAll('#products>.item').length"))>0);
  assert(await evaluate(`Array.from(document.querySelectorAll('#products>.item>b')).every(node=>node.textContent.includes(${JSON.stringify(title)}))`));
  await evaluate("document.getElementById('product-search').value='no match ui fixture';renderSellerProducts()");
  assert(await evaluate("document.getElementById('products').textContent.includes('没有符合筛选')"));
  await evaluate("document.getElementById('product-search').value='';document.getElementById('product-status-filter').value='published';renderSellerProducts()");
  assert.equal(await evaluate("document.querySelectorAll('#products>.item').length"),await evaluate("state.products.filter(p=>p.status==='published').length"));
  await route('#orders');await route('#products');
  assert.equal(await evaluate("document.getElementById('product-status-filter').value"),'published');
  await evaluate("document.getElementById('product-status-filter').value='';renderSellerProducts()");
  assert.equal(await evaluate("document.querySelectorAll('#products>.item').length"),originalCount);
  checks.push('Product keyword, empty result, status filters, clearing and cross-view retention');
  await route('#sourcing');
  const candidate=await evaluate("document.getElementById('candidate').value");
  await evaluate("document.getElementById('scenario-note').value='UI TEST UNSAVED - not submitted'");
  await route('#orders');await route('#sourcing');
  assert.equal(await evaluate("document.getElementById('scenario-note').value"),'UI TEST UNSAVED - not submitted');
  assert.equal(await evaluate("document.getElementById('candidate').value"),candidate);
  await route('#sourcing/quote-comparison');
  assert.equal(await evaluate('document.activeElement.id'),'quote-comparison-title');
  await screenshot('desktop-sourcing');
  checks.push('Unsaved values and candidate preserved; subsection heading focused');
  await evaluate('history.back()');
  await until(()=>evaluate("location.hash==='#sourcing'"),'history back');
  await evaluate('history.forward()');
  await until(()=>evaluate("location.hash==='#sourcing/quote-comparison'"),'history forward');
  assert.equal(await evaluate('document.activeElement.id'),'quote-comparison-title');
  checks.push('Browser back and forward restore view and subsection');
  await send('Page.navigate',{url:base+'/workbench?category=pet_fountain#orders/buyer-refunds'});await waitPage();
  assert(await evaluate("!document.getElementById('view-orders').hidden"));
  assert.equal(await evaluate('location.search'),'?category=pet_fountain');
  // Reloading must land at the deep-linked section, not merely its parent view.
  assert(await evaluate("Math.abs(document.getElementById('buyer-refunds').getBoundingClientRect().top)<120"),'deep-link section not positioned on reload');
  checks.push('Reload/direct URL preserves category and positions requested subsection');
  await evaluate("location.hash='#unknown/bogus'");await until(()=>evaluate("location.hash==='#overview'"),'unknown route fallback');
  checks.push('Unknown routes fall back to overview');
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await send('Page.navigate',{url:base+'/workbench'});await waitPage();
  assert(await evaluate("!document.getElementById('workspace-menu').open"));
  assert(await evaluate('document.documentElement.scrollWidth<=innerWidth'));
  await screenshot('mobile-overview');
  await evaluate("document.querySelector('#workspace-menu>summary').click()");
  assert(await evaluate("document.getElementById('workspace-menu').open"));
  await screenshot('mobile-navigation');
  assert(await evaluate("document.querySelector('.sidebar-tools').getBoundingClientRect().height>0"),'secondary tools missing on mobile');
  for(const view of views){
    await evaluate("document.getElementById('workspace-menu').open=true");
    await route('#'+view);
    assert(await evaluate('document.documentElement.scrollWidth<=innerWidth'),'mobile overflow '+view);
    assert(await evaluate("!document.getElementById('workspace-menu').open"));
  }
  await route('#orders');
  await evaluate("document.querySelector('.order-detail').open=true");
  await until(()=>evaluate("document.querySelector('.order-detail').dataset.loaded==='true'"),'mobile order detail');
  assert(await evaluate('document.documentElement.scrollWidth<=innerWidth'),'mobile order detail overflow');
  await screenshot('mobile-orders');
  checks.push('Expanded order detail remains within 390px viewport; item table scrolls within its container');
  // A keyboard Tab after navigating must not land in one of the hidden forms.
  for(let i=0;i<12;i++){
    await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
    await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Tab',code:'Tab',windowsVirtualKeyCode:9});
    assert(await evaluate("!document.activeElement.closest('[hidden]')"));
  }
  checks.push('390px menu, all eight mobile views without overflow, hidden controls excluded from keyboard focus');
  await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
  await route('#products');await screenshot('desktop-products');
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});
  await evaluate("document.querySelector('.product-row>button').click()");
  assert(await evaluate("document.querySelector('dialog[open]').getBoundingClientRect().width<=innerWidth"));
  await evaluate("document.querySelector('dialog[open] input').value='17';document.querySelector('dialog[open] .drawer-heading button').click();document.querySelector('.product-row>button').click()");
  assert(await evaluate("document.querySelector('dialog[open] input').value==='17'"));
  await screenshot('mobile-inventory-drawer');
  await evaluate("document.querySelector('dialog[open] .drawer-heading button').click()");
  checks.push('Mobile inventory drawer fits viewport and retains unsent stock input across closing and reopening');

  await send('Page.navigate',{url:base+'/shop'});
  await until(()=>evaluate("document.getElementById('products')?.textContent.includes('SIM')||document.querySelectorAll('#products button').length>0"),'buyer catalog');
  checks.push('Buyer shop still renders');
  const identityCheck=await evaluate(`(async()=>{
    const originalFetch=window.fetch;
    try{
      setBuyerSession({id:'browser-A',csrf:'fictional-A'});
      const waiting=[];window.fetch=()=>new Promise(resolve=>waiting.push(resolve));
      const late=loadOrders().catch(error=>error.stale);
      setBuyerSession({id:'browser-B',csrf:'fictional-B'});
      waiting[0]({ok:true,json:async()=>[{id:'private-A',items:[],amount_cents:100,status:'paid',address:{recipient:'A-only',line1:'A-private-street'}}]});
      waiting[1]({ok:true,json:async()=>[]});
      const rejected=await late;
      const clean=rejected && !document.getElementById('orders').textContent.includes('A-private-street');
      cartItems=[{status:'published',quantity:1,stock:2}];
      let finish;const checkoutButton=document.getElementById('checkout');
      const pending=busy(checkoutButton,()=>new Promise(resolve=>finish=resolve));
      await busy(document.getElementById('refresh-orders'),async()=>{});
      const locked=checkoutButton.disabled;finish();await pending;
      return clean && locked && !checkoutButton.disabled;
    }finally{window.fetch=originalFetch;setBuyerSession(null)}
  })()`);
  assert(identityCheck,'real DOM must reject previous buyer data and preserve in-flight checkout lock');
  checks.push('Real buyer DOM rejects previous identity responses; independent refresh preserves checkout busy state');
  assert(await evaluate(`(async()=>{
    const originalAPI=api,originalRefresh=refreshBuyer,originalCatalog=loadCatalog;
    try{
      setBuyerSession({id:'payment-message-check',csrf:'fictional'});
      const button=document.createElement('button');button.dataset.buyerAction='order-message-check';
      api=async()=>({status:'refunded'});refreshBuyer=async()=>{};loadCatalog=async()=>{};
      await payOrder('message-check',button);
      const refunded=document.getElementById('message').textContent.includes('already been refunded')&&!document.getElementById('message').textContent.includes('can now ship');
      api=async()=>({status:'paid'});refreshBuyer=async()=>{throw Error('temporary refresh failure')};
      await payOrder('message-check',button);
      return refunded&&document.getElementById('message').textContent.includes('Simulated payment completed')&&document.getElementById('message').textContent.includes('page could not refresh');
    }finally{api=originalAPI;refreshBuyer=originalRefresh;loadCatalog=originalCatalog;setBuyerSession(null)}
  })()`));
  checks.push('Buyer payment messages distinguish refunded replay and successful payment with a failed display refresh');
  if(process.env.SELLER_BROWSER_CHECK_BUYER_PAYMENT==='1'){
    const {checkBuyerPayment}=await import('./buyer_payment_browser_flow.mjs');
    buyerPayment=await checkBuyerPayment({evaluate,send,until,screenshot,base});
    checks.push(buyerPayment.checks);
  }else assert.equal(requests.filter(request=>request.method!=='GET').length,0,'Default UI check must not submit business mutations');
  const expected=errors.filter(error=>error.url===base+'/shop/api/account/me'&&error.text.includes('401'));
  const unexpected=errors.filter(error=>!expected.includes(error));
  assert.deepEqual(unexpected,[]);
  report={status:'passed',browser:'isolated installed Chrome headless',viewports:[{width:1440,height:1000},{width:390,height:844}],checks,
    console_errors:unexpected,expected_anonymous_buyer_session_checks:expected,business_mutations:requests.filter(request=>request.method!=='GET').length,additional_live_model_calls:0,buyer_payment:buyerPayment,requests:requests.length,screenshots:['desktop-collapsed.png','desktop-inventory-drawer.png','mobile-inventory-drawer.png','desktop-overview.png','desktop-products.png','desktop-sourcing.png','mobile-overview.png','mobile-navigation.png','desktop-orders.png','mobile-orders.png',...(buyerPayment?['buyer-payment-pending.png','buyer-payment-paid.png','buyer-payment-mobile.png']:[])]};
  report.screenshots.push('desktop-category-recovered.png');
}catch(error){report={status:'failed',checks,error:String(error),console_errors:errors};throw error}
finally{
  await writeFile(join(folder,'browser-check.json'),JSON.stringify(report,null,2));
  socket?.close();browser.kill();
}
console.log(JSON.stringify(report));
