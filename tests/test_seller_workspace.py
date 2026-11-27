"""Seller information architecture and navigation without business side effects."""
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / 'src/xborder_insight/commerce_workbench.html'


class Workspace(HTMLParser):
    def __init__(self):
        super().__init__()
        self.nodes = []
        self.stack = []
        self.feed(HTML.read_text(encoding='utf-8'))

    def handle_starttag(self, tag, attrs):
        node = {'tag': tag, 'attrs': dict(attrs), 'parents': [n['attrs'].get('id') for n in self.stack]}
        self.nodes.append(node)
        if tag not in {'meta', 'input', 'link', 'br', 'hr', 'img', 'wbr'}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]['tag'] == tag:
                del self.stack[i:]
                break


def test_all_original_tools_have_unique_business_locations():
    page = Workspace()
    ids = [n['attrs']['id'] for n in page.nodes if 'id' in n['attrs']]
    assert len(ids) == len(set(ids)), 'Cloned controls would submit ambiguous state'
    by_id = {n['attrs']['id']: n for n in page.nodes if 'id' in n['attrs']}
    expected = {
        'overview': ['summary', 'catalog-stages'],
        'products': ['products', 'decisions', 'product-search', 'product-status-filter', 'product-category-filter'],
        'orders': ['orders', 'refunds', 'order-status', 'order-since', 'order-until'],
        'insights': ['review-result', 'review-history', 'review-file', 'review-mode', 'review-force', 'dataset', 'theme', 'name', 'evidence'],
        'sourcing': ['candidate', 'assumptions', 'supplier-cases', 'supplier-scenario', 'metric-scenario-form', 'profit-comparison-form', 'quote-selection', 'comparison-history'],
        'analytics': ['review'],
        'sources': ['metric-catalog'],
        'settings': ['key', 'payment-policy', 'integrity', 'audit'],
    }
    for view, controls in expected.items():
        for control in controls:
            assert 'view-' + view in by_id[control]['parents'], control
    assert len([n for n in page.nodes if 'data-workspace-view' in n['attrs']]) == 8
    assert len([n for n in page.nodes if 'data-workspace-link' in n['attrs']]) == 8
    for node in page.nodes:
        if node['tag']=='button':assert node['attrs'].get('data-seller-permission') in {'read','operate','finance','delivery'}
    # The candidate selection is outside any form and shared by all sourcing tools.
    assert 'assumptions' not in by_id['candidate']['parents']
    assert by_id['order-status']['attrs']['id'] == 'order-status'


def test_all_workspace_links_resolve_inside_the_named_view():
    page = Workspace()
    by_id = {n['attrs']['id']: n for n in page.nodes if 'id' in n['attrs']}
    for node in page.nodes:
        href = node['attrs'].get('href', '')
        if not href.startswith('#') or href == '#workspace-heading':
            continue
        view, *target = href[1:].split('/')
        assert 'view-' + view in by_id, href
        if target:
            assert len(target) == 1
            assert 'view-' + view in by_id[target[0]]['parents'], href
    assert 'href="#orders/buyer-refunds"' in (ROOT/'src/xborder_insight/commerce_seller.js').read_text(encoding='utf-8')


@pytest.mark.skipif(not shutil.which('node'), reason='Node required for navigation behavior')
def test_deep_links_back_forward_focus_permissions_and_unsaved_inputs():
    page = Workspace()
    fixtures = json.dumps(page.nodes, ensure_ascii=False)
    script = r'''
const vm=require('vm'), fs=require('fs'), assert=require('assert');
const fixtures=FIXTURES, nodes={};
let focused=null, scrolled=null, mediaChange=null;
for(const row of fixtures){
  const attrs=row.attrs;
  const node={id:attrs.id,attrs:{...attrs},parents:row.parents,value:'',hidden:false,disabled:false,open:true,
    textContent:'',style:{},dataset:{},
    getAttribute(k){return this.attrs[k]??null},setAttribute(k,v){this.attrs[k]=v},removeAttribute(k){delete this.attrs[k]},
    focus(){focused=this.id},scrollIntoView(){scrolled=this.id},
    contains(other){return other.parents.includes(this.id)},
    querySelector(sel){return fixtures.filter(r=>r.parents.includes(this.id)).map(r=>nodes[r.attrs.id]).find(n=>n&&n.tag===sel)||null}
  };
  node.tag=row.tag;node.classList={contains:k=>(attrs.class||'').split(' ').includes(k)};
  for(const [key,val] of Object.entries(attrs))if(key.startsWith('data-'))node.dataset[key.slice(5).replace(/-([a-z])/g,(_,x)=>x.toUpperCase())]=val;
  if(node.id)nodes[node.id]=node;
  row.node=node;
}
const links=fixtures.filter(r=>'data-workspace-link' in r.attrs).map(r=>r.node);
const views=fixtures.filter(r=>'data-workspace-view' in r.attrs).map(r=>r.node);
const sublinks=fixtures.filter(r=>r.tag==='a'&&r.parents.some(p=>p&&p.startsWith('view-'))).map(r=>r.node);
const buttons=[{id:'save',textContent:'保存一次新决策',dataset:{sellerPermission:'operate'},disabled:false},{id:'query',textContent:'查询订单',dataset:{sellerPermission:'read'},disabled:false}];
const handlers={},document={title:'',getElementById:id=>nodes[id]||null,
 querySelector:s=>s==='[data-workspace-view]'?views[0]:null,
 querySelectorAll:s=>s==='[data-workspace-view]'?views:s==='[data-workspace-link]'?links:s==='.section-nav a'?sublinks:s==='button'?buttons:[],
 addEventListener:(name,fn)=>handlers[name]=fn};
const media={matches:false,addEventListener:(name,fn)=>mediaChange=fn};
const events={},location={pathname:'/workbench',search:'?category=pet_fountain',hash:'#orders/buyer-refunds'};
const history={replaceState(_a,_b,path){assert(path.startsWith('/workbench?category=pet_fountain'));location.hash=path.slice(path.indexOf('#'))}};
const context=vm.createContext({document,location,history,window:{matchMedia:()=>media,addEventListener:(name,fn)=>events[name]=fn},console,
 fetch(){throw Error('Navigation must not request business endpoints')}});
vm.runInContext(`const $=id=>document.getElementById(id);let state={candidates:[{id:'candidate-1',name:'Unsaved fixture'}]};let evidenceVersion='v',evidenceDataset='pet_fountain',themes=[{}];`,context);
nodes.candidate.value='candidate-1';nodes.dataset.value='pet_fountain';nodes['scenario-note'].value='unsaved input';
vm.runInContext(fs.readFileSync('src/xborder_insight/commerce_seller.js','utf8'),context);
events.DOMContentLoaded();
assert.equal(views.filter(v=>!v.hidden)[0].id,'view-orders');
assert.equal(links.find(a=>a.dataset.workspaceLink==='orders').attrs['aria-current'],'page');
assert.equal(document.title,'订单与售后 · CrossBorder 卖家工作台');
for(const view of views){location.hash='#'+view.dataset.workspaceView;events.hashchange();assert.equal(views.filter(v=>!v.hidden).length,1);assert(!view.hidden)}
// Browser back/forward replays location hashes, including section deep links.
for(const route of ['#sourcing/cost-evaluation','#orders/buyer-refunds','#sourcing/cost-evaluation']){location.hash=route;events.hashchange()}
assert.equal(focused,'cost-evaluation-title');assert.equal(scrolled,focused);
assert.equal(nodes.candidate.value,'candidate-1');assert.equal(nodes['scenario-note'].value,'unsaved input');
location.hash='#missing/does-not-exist';events.hashchange();assert.equal(location.hash,'#overview');
location.hash='#orders/product-list';events.hashchange();assert.equal(location.hash,'#orders');
media.matches=true;mediaChange({matches:true});assert(!nodes['workspace-menu'].open);
nodes['workspace-menu'].open=true;location.hash='#products';events.hashchange();assert(!nodes['workspace-menu'].open);
assert.equal(focused,'workspace-heading');
media.matches=false;mediaChange({matches:false});assert(nodes['workspace-menu'].open);
vm.runInContext("setRoleButtons('viewer')",context);
assert(buttons[0].disabled);assert(!buttons[1].disabled);
// Permissions follow stable metadata even when labels are changed or translated.
buttons[0].textContent='查询订单';buttons[1].textContent='保存计费假设';
vm.runInContext("setRoleButtons('viewer')",context);
assert(buttons[0].disabled);assert(!buttons[1].disabled);
buttons.push({id:'financial-test',dataset:{sellerPermission:'finance'},textContent:'Unrelated label',disabled:false});
vm.runInContext("setRoleButtons('operator')",context);assert(buttons[2].disabled);
vm.runInContext("setRoleButtons('owner')",context);assert(!buttons[2].disabled);
assert(links.every(link=>!link.disabled&&!('disabled' in link.attrs)));
// Re-clicking the active link still scrolls/focuses its workspace heading.
let prevented=false;handlers.click({target:{closest:()=>links.find(a=>a.dataset.workspaceLink==='products')},button:0,preventDefault(){prevented=true}});
assert(prevented);assert.equal(focused,'workspace-heading');
vm.runInContext(`
 const esc=value=>String(value).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
 const money=value=>'$'+(value/100).toFixed(2);
 sellerCatalogStatus='ready';catalogCategories=[{id:'pet_fountain',name_zh:'宠物饮水机',name:'Pet fountains'},{id:'air_purifier',name_zh:'空气净化器',name:'Air purifiers'}];
 state.decisions=[];
 state.products=[
  {id:'SKU-A',title:'Alpha fountain',status:'published',price_cents:100,stock:2,reserved:0,snapshot:{candidate:{id:'c1',source_json:{dataset:'pet_fountain'}}}},
  {id:'SKU-B',title:'Beta <draft>',status:'draft',price_cents:200,stock:0,reserved:0,snapshot:{candidate:{id:'c2',source_json:{dataset:'air_purifier'}}}}
 ];renderSellerProducts();`,context);
assert(nodes['product-count'].textContent.includes('显示 2 / 共 2'));
nodes['product-search'].value='pet fountains';vm.runInContext('renderSellerProducts()',context);
assert(nodes.products.innerHTML.includes('Alpha'));assert(!nodes.products.innerHTML.includes('Beta'));
// The store shortcut clears all unrelated filters; viewer can use these links too.
nodes['product-category-filter'].value='air_purifier';nodes['product-status-filter'].value='draft';
vm.runInContext('showSellerProducts(true)',context);
assert.equal(nodes['product-search'].value,'');assert.equal(nodes['product-category-filter'].value,'');
assert.equal(nodes['product-status-filter'].value,'published');
assert(nodes.products.innerHTML.includes('Alpha'));assert(!nodes.products.innerHTML.includes('Beta'));
vm.runInContext('showSellerProducts()',context);
assert(nodes['product-count'].textContent.includes('显示 2 / 共 2'));
assert(nodes.products.innerHTML.includes('Beta &lt;draft&gt;'));
nodes['product-search'].value='sku-a';vm.runInContext('renderSellerProducts()',context);
assert(nodes.products.innerHTML.includes('Alpha'));assert(!nodes.products.innerHTML.includes('Beta'));
nodes['product-search'].value='';nodes['product-status-filter'].value='draft';vm.runInContext('renderSellerProducts()',context);
assert(nodes.products.innerHTML.includes('Beta'));assert(!nodes.products.innerHTML.includes('Alpha'));
nodes['product-category-filter'].value='pet_fountain';vm.runInContext('renderSellerProducts()',context);
assert(nodes.products.innerHTML.includes('没有符合筛选')); // Combined filters.
nodes['product-status-filter'].value='';vm.runInContext('renderSellerProducts()',context);
assert(nodes.products.innerHTML.includes('Alpha'));assert(!nodes.products.innerHTML.includes('Beta'));
nodes['product-category-filter'].value='';vm.runInContext('renderSellerProducts()',context);
assert(nodes['product-count'].textContent.includes('显示 2 / 共 2'));
console.log('Navigation history, focus, mobile menu, permissions, unsaved state and combined product filters passed');
'''.replace('FIXTURES', fixtures)
    result = subprocess.run(['node', '-'], input=script, text=True, encoding='utf-8', capture_output=True, cwd=ROOT, timeout=20)
    assert result.returncode == 0, result.stderr
