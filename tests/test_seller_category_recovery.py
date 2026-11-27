"""A cleared or failed catalog is explicit and can recover without changing identity safety."""
from test_identity_and_busy_ui import execute, pytestmark


def test_category_noop_key_loading_failure_and_retry():
    execute(r'''
loadSeller();
run(`fixtureCategories={categories:[{id:'pet_fountain',name:'Pet fountains',name_zh:'宠物饮水机',candidates:1,drafts:0,published:1,in_stock:1}]};
 fixtureState={candidates:[],decisions:[],products:[{id:'p1',title:'Fountain',price_cents:100,status:'published',stock:2,reserved:0,snapshot:{candidate:{id:'c1',source_json:{dataset:'pet_fountain'}}}}]};
 state=fixtureState;renderCatalogStages(fixtureCategories);renderSellerProducts();`);
assert(!get('product-category-filter').disabled);
assert(get('product-category-filter').innerHTML.includes('Pet fountains'));
run('sellerKeyInput()'); // Same empty Key: no private state was invalidated.
assert.equal(run('state.products.length'),1);assert.equal(run('sellerCatalogStatus'),'ready');
get('key').value='new-key';run('sellerKeyInput();renderSellerProducts()');
assert.equal(run('state.products.length'),0);assert(get('product-category-filter').disabled);
assert(get('product-category-filter').innerHTML.includes('尚未重新加载'));
assert(get('product-count').textContent.includes('刷新商品与品类'));
assert(!get('product-count').textContent.includes('显示 0'));
run(`api=async path=>{if(path.includes('/catalog-stages'))throw Error('temporary failure');return fixtureState}`);
await run('refresh()');
assert.equal(run('sellerCatalogStatus'),'error');assert(get('product-category-filter').disabled);
assert(get('product-category-filter').innerHTML.includes('加载失败'));
run(`refreshSources=async()=>{};api=async path=>{
 if(path.includes('/state'))return fixtureState;
 if(path.includes('/catalog-stages'))return fixtureCategories;
 if(path.includes('/orders?')||path.includes('/audit?'))return {items:[],next_cursor:null,next_after:0};
 if(path.endsWith('/review')||path.endsWith('/refunds'))return [];
 if(path.endsWith('/me'))return {role:'viewer',actor:'viewer',tenant:'local',shop_tenant:'local',shop_matches_tenant:true};
 if(path.endsWith('/summary'))return {status_counts:{}};
 return {version:0,bps:300,fixed_cents:30};};`);
await run('refresh()');
assert.equal(run('sellerCatalogStatus'),'ready');assert(!get('product-category-filter').disabled);
assert(get('product-category-filter').innerHTML.includes('Pet fountains'));
assert(get('product-count').textContent.includes('显示 1 / 共 1'));
// A genuinely empty successful response remains distinct from failure/loading.
run('state={products:[],decisions:[]};renderCatalogStages({categories:[]});renderSellerProducts()');
assert(get('product-category-filter').innerHTML.includes('全部品类'));
assert(get('product-count').textContent.includes('显示 0 / 共 0'));
''')


def test_old_failed_catalog_request_does_not_replace_new_identity_message():
    execute(r'''
loadSeller();run('api=()=>new Promise((_resolve,reject)=>rejects=(typeof rejects===\'undefined\'?[]:rejects).concat(reject))');
const pending=run('refresh()');get('key').value='other';run('sellerKeyInput()');
run("rejects.forEach(reject=>reject(Error('old request failed')))");await pending;
assert.equal(run('sellerCatalogStatus'),'identity_changed');
assert(get('product-category-filter').innerHTML.includes('尚未重新加载'));
assert(!get('product-category-filter').innerHTML.includes('加载失败'));
''')
