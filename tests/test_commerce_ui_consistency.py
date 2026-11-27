"""Execute actual page functions in Node with controlled DOM and network stubs."""
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which('node'),reason='Node required for page behavior regression')
def test_page_races_checkout_intents_and_sold_out_actions():
    script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert');
function page(name,seller=false){
  const nodes={};const get=id=>nodes[id]??=( {id,value:'',innerHTML:'',textContent:'',disabled:false,dataset:{},style:{},hidden:false,options:[],removeAttribute(){},setAttribute(){}} );
  const document={getElementById:get,querySelectorAll:()=>[get('create-candidate')],querySelector:()=>null};
  let uuid=0;
  const context=vm.createContext({document,window:{addEventListener(){}},location:{search:''},URLSearchParams,console,crypto:{randomUUID:()=>String(++uuid)},setTimeout});
  if(seller)vm.runInContext(fs.readFileSync('src/xborder_insight/commerce_seller.js','utf8'),context);
  const html=fs.readFileSync('src/xborder_insight/'+name,'utf8');
  for(const match of html.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)){
    const source=match[1].replace(/init\(\);\s*$/,'');
    vm.runInContext(source,context);
  }
  return {context,get,run:source=>vm.runInContext(source,context)};
}
(async()=>{
  const seller=page('commerce_workbench.html',true);seller.get('dataset').value='air_purifier';
  seller.run(`sellerRole='owner';pending={};api=path=>new Promise(resolve=>pending[path]=resolve);`);
  const old=seller.run('loadEvidence()');
  assert(seller.get('create-candidate').disabled);
  seller.get('dataset').value='coffee_machine';const current=seller.run('loadEvidence()');
  seller.run(`pending['/v1/commerce/evidence/coffee_machine']({evidence_fingerprint:'coffee-v2',themes:[{theme_id:'T01',display_name:'Coffee heat',mention_count:1,evidence:['Coffee']} ]})`);
  await current;assert(seller.get('theme').innerHTML.includes('Coffee heat'));
  seller.run(`pending['/v1/commerce/evidence/air_purifier']({evidence_fingerprint:'air-v1',themes:[{theme_id:'T01',display_name:'Air durability',mention_count:1,evidence:['Air']}]})`);
  await old;
  assert.equal(seller.run('evidenceDataset'),'coffee_machine');
  assert.equal(seller.run('evidenceVersion'),'coffee-v2');
  assert(!seller.get('theme').innerHTML.includes('Air durability'));
  assert(!seller.get('create-candidate').disabled);
  const shop=page('commerce_shop_v2.html');
  shop.run(`catalogProducts=[{id:'soldout',title:'SIM zero',category_id:'air',category_name:'Air',stock:0,price_cents:100}];renderCatalog();`);
  assert(shop.get('products').innerHTML.includes('Temporarily out of stock'));
  assert(/<button[^>]* disabled onclick="addToCart/.test(shop.get('products').innerHTML));
  shop.get('address').value='address-a';
  shop.run(`user={csrf:'csrf'};cartItems=[{status:'published',quantity:1,stock:5}];cartFingerprint='cart-a';calls=[];refreshBuyer=async()=>{};loadCatalog=async()=>{};api=async(path,body,key)=>{calls.push({path,body,key});if(calls.length<=2)throw Error('lost response');return {id:'order'};};`);
  await shop.get('checkout').onclick({currentTarget:shop.get('checkout')});
  await shop.get('checkout').onclick({currentTarget:shop.get('checkout')});
  assert.equal(shop.run('calls[0].key'),shop.run('calls[1].key'));
  shop.run(`cartFingerprint='cart-b';cartItems[0].quantity=2;`);
  await shop.get('checkout').onclick({currentTarget:shop.get('checkout')});
  assert.notEqual(shop.run('calls[1].key'),shop.run('calls[2].key'));
  assert.equal(shop.run('calls[2].body.cart_fingerprint'),'cart-b');
  // Independent review mode must not display an imported source while sending samples.
  vm.runInContext(fs.readFileSync('src/xborder_insight/review_analysis.js','utf8'),seller.context);
  seller.get('review-mode').value='live';seller.get('review-source').value='import';
  seller.run("reviewConfig={configured:true,requests_remaining:10};updateReviewButtons()");
  assert.equal(seller.get('review-source').value,'samples');
  assert.equal(seller.get('review-dataset').value,'pet_fountain');
  assert(seller.get('review-file').disabled);
  seller.run("reviewConfig.requests_remaining=0;updateReviewButtons()");
  assert(!seller.get('review-submit').disabled); // Stored results remain reusable after budget exhaustion.
  seller.get('review-force').checked=true;seller.run('updateReviewButtons()');
  assert(seller.get('review-submit').disabled);
  seller.get('review-force').checked=false;
  seller.get('review-history').value='old-run';
  seller.run("reviewGeneration=7;api=()=>new Promise(resolve=>resolveProgress=resolve)");
  const pendingPoll=seller.run("pollReviewProgress('old-run',7)");
  seller.get('review-history').value='new-run';seller.run('reviewGeneration=8');
  seller.run("resolveProgress({status:'running',request_count:999,progress:{completed:9,parsed:9,total:10}})");
  await pendingPoll;assert(!seller.get('review-run-status').textContent.includes('999'));
  seller.run("sellerRole='viewer';updateReviewButtons()");
  assert(seller.get('review-submit').disabled);
  console.log('Page race, sold-out and checkout intent regressions passed');
})().catch(e=>{console.error(e);process.exit(1)});
'''
    result=subprocess.run(['node','-'],input=script,text=True,capture_output=True,timeout=20)
    assert result.returncode==0,result.stderr
