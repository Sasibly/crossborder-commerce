/* Isolated headless Chrome check against the local mock app. No browser packages,
   user profile, model calls or business writes. Uses Chrome's testing protocol. */
import {spawn} from 'node:child_process';
import {mkdtemp,readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve,join} from 'node:path';
import assert from 'node:assert/strict';

const base='http://127.0.0.1:18031';
const folder=resolve(process.env.SELLER_BROWSER_REPORT_DIR||'reports/bugfix-20261127/browser');
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

 await send('Page.navigate',{url:base+'/workbench'});
 await until(()=>evaluate("document.getElementById('load-status-overview')?.textContent==='已更新'"),'overview');
 assert(!requests.some(r=>/\/orders|\/review-analyses|\/supplier-cases|\/audit|\/commerce\/review$/.test(r.url)));checks.push('Overview reads only shared state, identity and summary');
 await evaluate("document.querySelector('[name=source_note]').value='preserved QA draft'");
 for(const name of ['products','orders','insights','sourcing','analytics','sources','settings']){
   await evaluate(`location.hash='#${name}'`);
   await until(()=>evaluate(`document.getElementById('load-status-${name}')?.textContent==='已更新'`),name);
   checks.push(name+' loaded');
 }
 assert.equal(await evaluate("document.querySelector('[name=source_note]').value"),'preserved QA draft');
 const before=requests.length;await evaluate("location.hash='#orders'");await delay(300);assert.equal(requests.length,before);checks.push('Cached navigation preserves form and avoids reads');
 await screenshot('desktop-orders');
 // Inject only the review GET failure. Orders must remain independently readable.
 await evaluate("originalFetch=fetch;fetch=(url,options)=>String(url).endsWith('/commerce/review')?Promise.reject(Error('QA injected read failure')):originalFetch(url,options);location.hash='#analytics';");
 await evaluate("loadSellerModule('analytics',true)");
 assert(await evaluate("document.getElementById('load-status-analytics').textContent.includes('读取失败')"));
 await evaluate("loadSellerModule('orders',true)");assert.equal(await evaluate("document.getElementById('load-status-orders').textContent"),'已更新');
 await evaluate("fetch=originalFetch;loadSellerModule('analytics',true)");assert.equal(await evaluate("document.getElementById('load-status-analytics').textContent"),'已更新');checks.push('Injected failure isolated and module retry recovers');
 await send('Emulation.setDeviceMetricsOverride',{width:390,height:844,deviceScaleFactor:1,mobile:true});await evaluate("location.hash='#settings'");await delay(200);await screenshot('mobile-settings');
 assert(await evaluate('document.documentElement.scrollWidth<=innerWidth+1'));checks.push('Mobile fits viewport');
 assert.equal(errors.length,0,JSON.stringify(errors));assert(!requests.some(r=>r.method==='POST'));checks.push('Zero business writes and no browser exceptions');
 await writeFile(join(folder,'browser-check.json'),JSON.stringify({checks,requests,errors},null,2));console.log(JSON.stringify({passed:checks.length,errors}));
}finally{socket?.close();browser.kill()}
