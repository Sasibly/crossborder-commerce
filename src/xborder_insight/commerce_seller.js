let sourceRead=0,scenarioRead=0,comparisonRead=0,auditRead=0,auditAppend=null;
/* Seller views for multi-line orders and reviewed refunds. Values from API are escaped. */
function sellerBadge(value,label=value){
  const tones={pending:'warning',paid:'warning',requested:'warning',not_shipped:'warning',shipped:'info',simulated_shipped:'info',completed:'success',simulated_completed:'success',published:'success',approved:'success',refunded:'danger',rejected:'danger',cancelled:'neutral'};
  return `<span class="badge badge-${tones[value]||'neutral'}">${esc(label)}</span>`;
}
function toggleSellerSidebar(){
  const collapsed=document.querySelector('.workspace-shell').classList.toggle('nav-collapsed');
  $('sidebar-toggle').setAttribute('aria-expanded',String(!collapsed));
  $('sidebar-toggle').setAttribute('aria-label',collapsed?'展开侧边栏':'折叠侧边栏');
  $('sidebar-toggle').textContent=collapsed?'展开导航':'收起导航';
}
function searchSellerWorkspace(event){
  event.preventDefault();$('product-search').value=$('workspace-search').value;
  renderSellerProducts();openSellerModule('products','product-list');
}
function renderSellerSummary(summary){
  const counts=summary.status_counts||{},count=Object.values(counts).reduce((a,b)=>a+b,0);
  const cards=[['累计模拟收款',money(summary.gross_collected_cents),'累计口径 · 暂无历史对比'],['订单量',count+' 单','含全部现有订单状态'],['待处理发货',(counts.paid||0)+' 单','已支付 · 退款待审核订单暂停发货'],['成本完整的贡献合计',money(summary.complete_contribution_cents),summary.missing_cost_order_count+' 单成本待补全 · 暂不展示利润率']];
  return `<div class="kpi-grid">${cards.map(([label,value,note])=>`<article class="kpi-card"><p class="kpi-label">${label}</p><strong class="kpi-value">${value}</strong><p class="kpi-note">${note}</p></article>`).join('')}</div><div class="summary-secondary"><p>累计整单退款：<b>${money(summary.refunded_cents)}</b></p><p>退款后留存收款：<b>${money(summary.retained_receipts_cents)}</b></p><p>已知贡献小计：<b>${money(summary.known_contribution_cents)}</b></p><p>成本待补全：<b>${summary.missing_cost_order_count} 单</b></p></div><div class="status-strip">${Object.entries(counts).map(([key,value])=>sellerBadge(key,(ORDER_LABELS[key]||key)+' '+value)).join('')}</div>`;
}
const ORDER_LABELS={pending:'待支付',paid:'待发货',shipped:'已发货',completed:'已完成',cancelled:'已取消',refunded:'已退款'};
function orderTime(value){if(value==null)return '未记录';const date=new Date(value*1000);return Number.isNaN(date.getTime())?'未记录':date.toLocaleString()}
function orderMoney(value,currency='USD'){return value==null||!Number.isFinite(value)?'未记录':esc(new Intl.NumberFormat('zh-CN',{style:'currency',currency}).format(value/100))}
function orderItems(o){return (o.items||[]).map(i=>({...i,title:i.product_title??i.snapshot?.product_title??'未记录商品名称',decision:i.decision_id??i.snapshot?.decision_id}))}
function renderOrderActions(o){
  const shippingValues=o.items.map(i=>i.assumed_logistics_cents??i.snapshot?.decision?.assumptions?.logistics_cents);
  const shipping=shippingValues.every(v=>Number.isInteger(v)&&v>=0)?shippingValues.reduce((sum,value,index)=>sum+value*o.items[index].quantity,0):null;
  if(o.status==='paid'&&o.refund_pending)return '<p class="order-alert">退款申请待审核，暂停发货。<a href="#orders/buyer-refunds">前往处理售后 →</a></p>';
  return `${o.status==='pending'?`<p class="meta">等待买家在商城“Your orders”中完成模拟支付；卖家不代买家付款。</p><button class="secondary" onclick="mutate('/orders/${o.id}/cancel',{})">取消</button>`:''}${o.status==='paid'?`<div class="fields"><label>模拟运单号<input id="tracking-${o.id}" value="DEMO-${o.id.slice(0,8)}" maxlength="120"></label><label>本单物流成本（USD 分）<input id="shipping-${o.id}" type="number" min="0" step="1" required value="${shipping??''}"></label></div><p class="meta">运单号为本地模拟标识；物流成本预填自下单假设，确认后登记。未知成本请填写后再发货，明确无成本才填0。</p><button onclick="shipOrder('${o.id}')">模拟发货</button>`:''}${o.status==='shipped'?`<button onclick="mutate('/orders/${o.id}/complete',{})">标记已完成</button>`:''}${['paid','shipped','completed'].includes(o.status)?`<button data-seller-permission="finance" class="secondary" onclick="mutate('/orders/${o.id}/refund',{})">卖家主动整单退款</button>`:''}${o.status==='refunded'?'<p>展开订单详情核对已登记净损失或登记首版。</p>':''}`;
}
async function shipOrder(id){
  const raw=$('shipping-'+id).value.trim(),tracking=$('tracking-'+id).value.trim();
  if(!raw||!/^\d+$/.test(raw)||!Number.isSafeInteger(Number(raw))||!tracking){notify('请填写模拟运单号与非负整数物流成本（USD 分）；未知成本不能按0提交。');return}
  await mutate('/orders/'+id+'/ship',{tracking,actual_logistics_cents:Number(raw)});
}
function renderOrder(o){
  const items=orderItems(o),recipient=o.recipient_summary;
  const lines=items.slice(0,2).map(i=>`<div class="order-product"><b>${esc(i.title)}</b><span>× ${i.quantity} · ${orderMoney(i.unit_price_cents*i.quantity,o.currency)}</span><small class="meta">SKU ${esc(i.product_id)}</small></div>`).join('');
  const attention=o.refund_pending?'退款待审核':o.status==='paid'?'等待模拟发货':o.status==='pending'?'等待买家模拟支付':'';
  return `<article class="order-card" data-order-id="${esc(o.id)}"><div class="order-card-heading"><div><p class="meta">订单 ${esc(o.id)}</p><p class="meta">创建于 ${esc(orderTime(o.created_at))} · 浏览器本地时区</p></div><div>${sellerBadge(o.status,ORDER_LABELS[o.status]||o.status)} <span class="badge">模拟交易</span>${attention?`<span class="order-attention">${attention}</span>`:''}</div></div><div class="order-card-body"><div>${lines}${items.length>2?`<p class="meta">另有 ${items.length-2} 种商品，展开详情查看全部。</p>`:''}</div><div class="order-total"><strong>${orderMoney(o.amount_cents,o.currency)}</strong><span>${o.quantity} 件 · ${items.length} 种商品 · ${esc(o.currency||'USD')}</span><span class="meta">收件：${recipient?esc([recipient.recipient_masked,recipient.country,recipient.state].filter(Boolean).join(' · ')):'未提供'}</span></div></div><div class="order-actions">${renderOrderActions(o)}</div><details class="order-detail" ontoggle="loadOrderSource(this,'${o.id}')"><summary>查看订单详情 · 商品、金额、物流与时间线</summary><div data-order-detail>展开后按需加载；不会重新分析评论。</div></details></article>`;
}
function renderOrderDetail(o){
  const display=o.display,amounts=display.amounts,times=display.timestamps,payment=display.payment,fulfilment=display.fulfilment;
  const rows=orderItems(o).map(i=>`<tr><td>${esc(i.title)}</td><td class="meta">${esc(i.product_id)}</td><td>${i.quantity}</td><td>${orderMoney(i.unit_price_cents,o.currency)}</td><td>${orderMoney(i.unit_price_cents*i.quantity,o.currency)}</td><td class="meta">${esc(i.decision||'未记录')}</td></tr>`).join('');
  const refundLabels={requested:'待审核',approved:'已同意',rejected:'已拒绝'};
  const paymentLabels={simulated_paid:'模拟已支付',simulated_refunded:'模拟已退款',unpaid:'未支付',not_recorded:'未记录支付事件'};
  const fulfilmentLabels={simulated_shipped:'模拟已发货',simulated_completed:'卖家标记已完成',not_shipped:'未发货',not_recorded:'未记录发货事件'};
  const eventLabels={'order.created':'创建订单','order.paid':'模拟支付成功','order.shipped':'模拟发货','order.completed':'标记已完成','order.cancelled':'取消订单','order.refunded':'执行模拟整单退款','refund.requested':'买家申请退款','refund.approved':'同意退款申请','refund.rejected':'拒绝退款申请'};
  const timeline=display.timeline.map(event=>`<li><b>${esc(eventLabels[event.kind]||event.kind)}</b><time>${esc(orderTime(event.at))}</time><span class="meta">${event.source==='audit'?'操作审计':event.source==='inventory_ledger'?'历史库存流水':event.source==='refund_record'?'售后记录':'订单记录'} · ${event.actor?esc(event.actor):'执行者未记录'} · 模拟流程</span></li>`).join('');
  const refunds=display.refunds.map(r=>`<div class="item"><b>${refundLabels[r.status]||esc(r.status)}</b><p>${esc(r.reason)}</p><p class="meta">申请：${esc(orderTime(r.created_at))} · 审核：${esc(orderTime(r.reviewed_at))}</p><p>${esc(r.review_note||'审核说明未记录')}</p></div>`).join('')||'<p class="meta">无买家售后申请；卖家主动退款另见状态与时间线。</p>';
  return `<p class="meta">下单快照 · 商品名称、价格与决策保留成交时版本。所有支付、运单和履约均为本地模拟。</p><section class="order-detail-section"><h3>基本信息</h3><dl class="order-facts"><div><dt>平台订单号</dt><dd>${esc(o.id)}</dd></div><div><dt>商家 ID</dt><dd>${esc(o.tenant)}</dd></div><div><dt>买家标识</dt><dd>${esc(o.buyer_id||'未记录（可能为历史游客订单）')}</dd></div><div><dt>订单状态</dt><dd>${ORDER_LABELS[o.status]||esc(o.status)}</dd></div><div><dt>创建时间</dt><dd>${esc(orderTime(times.created_at))}</dd></div><div><dt>最近记录时间</dt><dd>${esc(orderTime(times.last_recorded_at))}</dd></div></dl></section><section class="order-detail-section"><h3>下单商品</h3><div class="tablewrap"><table><thead><tr><th>成交商品名称</th><th>SKU</th><th>数量</th><th>成交单价</th><th>商品小计</th><th>决策版本</th></tr></thead><tbody>${rows}</tbody></table></div></section><section class="order-detail-section"><h3>金额构成 · ${esc(o.currency)}</h3><dl class="order-facts"><div><dt>商品合计</dt><dd>${orderMoney(amounts.items_subtotal_cents,o.currency)}</dd></div><div><dt>订单总额</dt><dd>${orderMoney(amounts.order_total_cents,o.currency)}</dd></div><div><dt>买家运费</dt><dd>${amounts.shipping_included?'已含售价，卖家承担':orderMoney(amounts.buyer_shipping_cents,o.currency)}</dd></div><div><dt>税费</dt><dd>演示不代收；未记录税额</dd></div><div><dt>优惠金额</dt><dd>${orderMoney(amounts.discount_cents,o.currency)}</dd></div><div><dt>已执行模拟退款</dt><dd>${orderMoney(amounts.refunded_cents,o.currency)}</dd></div><div><dt>卖家支付费快照</dt><dd>${orderMoney(amounts.recorded_payment_fee_cents,o.currency)}</dd></div><div><dt>已登记物流成本</dt><dd>${orderMoney(amounts.recorded_logistics_cost_cents,o.currency)}</dd></div></dl><p class="meta">未记录与0金额分别显示。卖家成本不向买家重复收费，不用于重新计算已保存订单总额。</p></section><section class="order-detail-section"><h3>收货信息</h3><div id="delivery-${o.id}" data-delivery><p class="meta">列表与普通详情不包含完整地址。下方读取成交时收货快照，不读取当前地址簿。</p>${display.can_view_delivery?`<button class="secondary" onclick="loadOrderDelivery('${o.id}',this)">查看完整收货信息</button>`:'<p>当前只读角色不可查看完整收货信息；可联系店铺 owner/operator 处理履约。</p>'}</div></section><section class="order-detail-section"><h3>支付与模拟履约</h3><dl class="order-facts"><div><dt>支付状态</dt><dd>${esc(paymentLabels[payment.status]||payment.status)}</dd></div><div><dt>支付时间</dt><dd>${esc(orderTime(times.paid_at))}</dd></div><div><dt>物流状态</dt><dd>${sellerBadge(fulfilment.status,fulfilmentLabels[fulfilment.status]||fulfilment.status)}</dd></div><div><dt>本地模拟运单号</dt><dd>${esc(fulfilment.tracking||'未提供')}</dd></div><div><dt>发货时间</dt><dd>${esc(orderTime(times.shipped_at))}</dd></div><div><dt>完成时间</dt><dd>${esc(orderTime(times.completed_at))}</dd></div><div><dt>物流商 / 预计送达</dt><dd>未提供 / 未记录</dd></div><div><dt>实际签收信息</dt><dd>未记录；标记完成不代表承运商签收</dd></div></dl>${payment.events.map(event=>`<p class="meta">本地模拟支付事件号：${esc(event.reference)} · ${esc(orderTime(event.created_at))}</p>`).join('')||'<p class="meta">未记录支付事件号，不生成第三方交易号。</p>'}</section><section class="order-detail-section"><h3>售后与退款</h3>${refunds}${renderRefundCostRecord(o.refund_cost_record)}${o.status==='refunded'&&!o.refund_cost_record?refundCostForm(o.id):''}<a href="#orders/buyer-refunds">进入买家售后申请 →</a></section><section class="order-detail-section"><h3>订单时间线</h3><ol class="order-timeline">${timeline}</ol><p class="meta">${esc(display.timeline_note)} · 时间按浏览器本地时区显示。</p></section><details><summary>查看选品依据与脱敏订单快照</summary><pre>${esc(JSON.stringify(o.snapshot,null,2))}</pre></details>`;
}
async function loadOrderDelivery(id,button){
  const key=$('key').value,generation=sellerOrderAccessGeneration;button.disabled=true;
  try{
    const result=await api('/v1/commerce/orders/'+id+'/delivery');
    const target=$('delivery-'+id);if(key!==$('key').value||generation!==sellerOrderAccessGeneration||!target||target.isConnected===false)return;
    const a=result.address;
    target.innerHTML=a?`<dl class="order-facts"><div><dt>收件人</dt><dd>${esc(a.recipient||'未提供')}</dd></div><div><dt>电话</dt><dd>${esc(a.phone||'未提供')}</dd></div><div><dt>收货地址</dt><dd>${esc([a.line1,a.line2,a.city,a.state].filter(Boolean).join(', ')||'未提供')}</dd></div><div><dt>国家 / 邮编</dt><dd>${esc(a.country||'未提供')} / ${esc(a.postal_code||'未提供')}</dd></div></dl><p class="meta">下单地址快照 · 仅当前详情展示，不写入操作日志。</p>`:'<p>此订单未提供收货地址，不补造收件信息。</p>';
  }catch(e){notify(e.message)}finally{if(button.isConnected!==false)button.disabled=sellerRole==='viewer'}
}

function renderRefundCostRecord(record){if(!record)return '<p>尚未登记退款净损失；未记录金额不代表0。</p>';const s=record.snapshot;return '<h4>已登记退款净损失（首版不可覆盖）</h4><dl>'+[['procurement_loss_cents','货物净损失'],['logistics_loss_cents','物流净损失'],['payment_loss_cents','不可退支付费用'],['other_loss_cents','其他净损失']].map(([key,label])=>'<dt>'+label+'</dt><dd>'+orderMoney(s[key])+'</dd>').join('')+'</dl><p>合计：'+orderMoney(s.loss_cents)+'</p><p>依据：'+esc(s.note)+'</p><p>登记时间：'+esc(orderTime(record.created_at))+'</p>'}
function refundCostForm(id){
  const fields=[['procurement_loss_cents','货物净损失'],['logistics_loss_cents','物流净损失'],['payment_loss_cents','不可退支付费用'],['other_loss_cents','其他净损失（含获客等）']];
  return `<details><summary>登记退款净损失（USD 分）</summary><p class="meta">货物已退回可再次销售时，应扣除回收价值。明确无损失填 0；尚不清楚时不要提交。首版提交后不可覆盖。</p><form onsubmit="saveRefundCosts(event,'${id}')"><div class="fields">${fields.map(([name,label])=>`<label>${label}<input name="${name}" type="number" min="0" step="1" required></label>`).join('')}</div><label>核算依据<textarea name="note" minlength="3" maxlength="1000" required></textarea></label><button data-seller-permission="finance">保存净损失记录</button></form></details>`;
}

async function saveRefundCosts(event,id){
  event.preventDefault();const data=Object.fromEntries(new FormData(event.target));
  for(const name of Object.keys(data))if(name.endsWith('_cents'))data[name]=Number(data[name]);
  await mutate('/refund-costs/'+id,data);
}

async function refreshRefunds(){
  const requests=await api('/v1/commerce/refunds');
  $('refunds').innerHTML=requests.map(r=>`<div class="item"><span class="badge">${r.status}</span><p class="meta">订单 ${r.order_id}</p><p>${esc(r.reason)}</p><p class="meta">申请审核：${esc(r.status)} · 最终退款执行：${esc(r.execution_status)}${r.executed_at?' · '+esc(new Date(r.executed_at*1000).toLocaleString()):''}</p>${r.status==='requested'?`<label>审核说明<textarea id="review-note-${r.id}" minlength="3" maxlength="1000"></textarea></label><button data-seller-permission="finance" onclick="reviewRefund('${r.id}',true)">同意模拟整单退款</button><button data-seller-permission="finance" class="secondary" onclick="reviewRefund('${r.id}',false)">拒绝申请</button>`:`<p class="meta">${esc(r.review_note)}</p>`}</div>`).join('')||'<p>暂无买家售后申请。</p>';
}

async function reviewRefund(id,approve){
  await mutate('/refunds/'+id+'/review',{approve,note:$('review-note-'+id).value});
}

let auditCursor=0;
let orderCursor=null;
let orderQuery='';
let sellerRole='viewer';
let sellerOrderAccessGeneration=0;
let orderQueryGeneration=0;
let sellerKeyValue='';
function sellerKeyInput(){if($('key').value===sellerKeyValue)return;clearSellerIdentity()}
function sellerAccess(){return {generation:sellerOrderAccessGeneration,key:$('key').value}}
function checkSellerAccess(access){if(access.generation!==sellerOrderAccessGeneration||access.key!==$('key').value){const error=Error('');error.stale=true;throw error}}
function clearSellerIdentity(){
  sellerKeyValue=$('key').value;
  if($('header-store'))$('header-store').textContent='访问凭证已更改';
  if($('header-role'))$('header-role').textContent='访问设置';
  for(const dialog of document.querySelectorAll('dialog[open]'))dialog.close();
  sellerOrderAccessGeneration++;orderQueryGeneration++;sourceRead++;scenarioRead++;comparisonRead++;auditRead++;auditAppend=null;orderCursor=null;orderQuery='';auditCursor=0;
  state={candidates:[],decisions:[],products:[]};catalogCategories=[];policyVersion=0;sellerWrites.clear();sellerOperationLocks.clear();resetSellerModules();
  scenarioRows=[];scenarioRequest=null;scenarioCandidate='';comparisonRows=[];comparisonRequest=null;comparisonCandidate='';
  for(const id of ['integrity','orders','products','product-count','product-category-filter','decisions','candidate','refunds','audit','summary','review','catalog-stages','seller-identity','environment','supplier-cases','metric-scenarios','comparison-results','comparison-history','quote-selection','compare-quote-a','compare-quote-b'])if($(id))$(id).textContent='';
  setSellerCatalogStatus('identity_changed');
  for(const id of ['review-lookup','comparison-lookup','name','scenario-note','comparison-note','review-name','aftersales-scenario-id','comparison-id','comparison-option','policy-bps','policy-fixed'])if($(id))$(id).value='';
  $('assumptions')?.reset?.();clearAftersalesScenario();clearComparisonReference();
  if(typeof resetReviewIdentity==='function')resetReviewIdentity();
  $('orders').textContent='访问凭证已更改，请点击“刷新订单”重新加载。';
  $('order-more').disabled=true;sellerRole='viewer';setRoleButtons(sellerRole);updateSellerCandidateContext();
}
async function loadOrders(append=false){
  try{
    const access=sellerOrderAccessGeneration,key=$('key').value;
    if(!append)orderQueryGeneration++;
    const generation=orderQueryGeneration;
    let query=orderQuery;
    if(!append){
      const params=new URLSearchParams({limit:'30',view:'summary'});
      if($('order-status').value)params.set('status',$('order-status').value);
      for(const [id,name] of [['order-since','since'],['order-until','until']])if($(id).value)params.set(name,Math.floor(new Date($(id).value).getTime()/1000));
      query=params.toString();orderQuery=query;orderCursor=null;
    }
    const page=await api('/v1/commerce/orders?'+query+(append&&orderCursor?'&cursor='+encodeURIComponent(orderCursor):''));
    if(access!==sellerOrderAccessGeneration||key!==$('key').value||generation!==orderQueryGeneration)return;
    const html=page.items.map(renderOrder).join('');
    if(append)$('orders').insertAdjacentHTML('beforeend',html);else $('orders').innerHTML=html||'<p>当前筛选下没有订单。</p>';
    orderCursor=page.next_cursor;$('order-more').disabled=!orderCursor;
    setRoleButtons(sellerRole);
  }catch(e){notify(e.message);return false}
}
async function loadOrderSource(details,id){
  if(!details.open||details.dataset.loaded==='true'||details.dataset.loading==='true')return;
  details.dataset.loading='true';const key=$('key').value,generation=sellerOrderAccessGeneration,target=details.querySelector('[data-order-detail]');
  target.textContent='正在读取订单详情…';
  try{
    const order=await api('/v1/commerce/orders/'+id);
    if(key!==$('key').value||generation!==sellerOrderAccessGeneration||details.isConnected===false)return;
    target.innerHTML=renderOrderDetail(order);details.dataset.loaded='true';setRoleButtons(sellerRole);
  }catch(e){target.textContent='详情加载失败：'+e.message+'。收起后重新展开可重试。'}finally{details.dataset.loading='false'}
}
async function checkIntegrity(){
  try{$('integrity').textContent=JSON.stringify(await api('/v1/commerce/integrity'),null,2)}catch(e){notify(e.message)}
}
let policyVersion=0;
async function savePolicy(event){
  event.preventDefault();await mutate('/payment-policy',{bps:Number($('policy-bps').value),fixed_cents:Number($('policy-fixed').value),expected_version:policyVersion});
}
async function loadAudit(append=false){
  if(append&&auditAppend)return auditAppend;
  const access=sellerAccess(),request=append?auditRead:++auditRead,cursor=append?auditCursor:0;
  const pending=(async()=>{try{
    const page=await api('/v1/commerce/audit?after='+cursor+'&limit=50');checkSellerAccess(access);if(request!==auditRead)return false;
    const html=page.items.map(r=>`<tr><td>${esc(new Date(r.created_at*1000).toLocaleString())}</td><td>${esc(r.actor)}</td><td>${esc(r.action)}</td><td class="meta">${esc(r.object_id)}</td></tr>`).join('');
    if(append)$('audit').insertAdjacentHTML('beforeend',html);else $('audit').innerHTML=html||'<tr><td colspan="4">升级前操作不补造身份；新操作将在这里记录。</td></tr>';
    auditCursor=page.next_after;$('audit-more').disabled=page.items.length<50;return true;
  }catch(e){notify(e.message);return false}})();
  if(append)auditAppend=pending;try{return await pending}finally{if(auditAppend===pending)auditAppend=null}
}

async function refreshManagement(){
  const access=sellerAccess();
  await refreshSources();
  checkSellerAccess(access);
  const policy=await api('/v1/commerce/payment-policy');policyVersion=policy.version;
  $('policy-bps').value=policy.bps;$('policy-fixed').value=policy.fixed_cents;
  const [me,summary]=await Promise.all([api('/v1/commerce/me'),api('/v1/commerce/summary')]);
  $('seller-identity').textContent=`当前角色：${me.role} · ${me.authenticated?'已鉴权':'本地演示，未启用 Key 校验'} · ${me.actor}`;
  $('environment').textContent=`本机实例：${me.instance} · 当前卖家店铺：${me.tenant} · 商城店铺：${me.shop_tenant} · ${me.shop_matches_tenant?'店铺匹配':'店铺不匹配：当前卖家商品不会出现在此商城，请切换对应店铺 Key'}`;
  if(me.shop_matches_tenant){$('shop-link').href='/shop';$('shop-link').removeAttribute('aria-disabled')}else{$('shop-link').removeAttribute('href');$('shop-link').setAttribute('aria-disabled','true')}
  $('summary').innerHTML=renderSellerSummary(summary);
  if($('header-store'))$('header-store').textContent=me.tenant+' · '+me.shop_tenant;
  if($('header-role'))$('header-role').textContent='卖家 · '+me.role+' ↗';
  await loadAudit();
  checkSellerAccess(access);
  sellerRole=me.role;setRoleButtons(sellerRole);
  if(typeof refreshReviewAnalyses==='function')await refreshReviewAnalyses();
}

function setRoleButtons(role){
  for(const button of document.querySelectorAll('button')){
    const permission=button.dataset?.sellerPermission||'operate';
    if(!['audit-more','order-more'].includes(button.id))button.disabled=false;
    if(!sellerCan(permission,role))button.disabled=true;
  }
  if($('create-candidate'))$('create-candidate').disabled=role==='viewer'||!evidenceVersion||evidenceDataset!==$('dataset').value||!themes.length;
  if(typeof updateReviewButtons==='function')updateReviewButtons();
  if(typeof sellerOperationLocks!=='undefined'&&sellerOperationLocks.size)for(const button of document.querySelectorAll('button')){const handler=button.getAttribute?.('onclick')||button.form?.getAttribute?.('onsubmit')||'';for(const key of sellerOperationLocks.keys()){const action=key.split(':').slice(1).join(':');const path=action.startsWith('mutate:')?action.slice(7):null;if(path?handler.includes(path):handler.includes(action.split(':')[0]))button.disabled=true;}}
}
function sellerCan(permission,role=sellerRole){
  const roles={read:['owner','operator','viewer'],operate:['owner','operator'],finance:['owner'],delivery:['owner','operator']};
  return !!roles[permission]?.includes(role);
}

async function newSupplierCase(){
  await mutate('/supplier-cases',{candidate_id:$('candidate').value,scenario:$('supplier-scenario').value});
}
async function supplierTransition(id,target,version){
  await mutate('/supplier-cases/'+id+'/transition',{target,expected_version:version});
}
async function refreshSources(){
  const access=sellerAccess(),request=++sourceRead,cid=$('candidate').value;
  updateSellerCandidateContext();
  const [source,cases]=await Promise.all([api('/v1/commerce/business-metrics'),api('/v1/commerce/supplier-cases')]);
  checkSellerAccess(access);if(request!==sourceRead||cid!==$('candidate').value)return;
  const selected=$('returns-metric').value;
  $('returns-metric').innerHTML=source.metrics.map(m=>`<option value="${esc(m.id)}">${esc(m.name)} · ${(Number(m.value)*100).toFixed(1)}% · ${esc(m.source_kind)}</option>`).join('');
  if(source.metrics.some(m=>m.id===selected))$('returns-metric').value=selected;
  scenarioMetrics=source.metrics;
  const scenarioSelected=$('scenario-metric').value;
  $('scenario-metric').innerHTML=source.metrics.map(m=>`<option value="${esc(m.id)}">${esc(m.name)} · ${esc(m.source_kind)}</option>`).join('');
  if(source.metrics.some(m=>m.id===scenarioSelected))$('scenario-metric').value=scenarioSelected;
  scenarioMetricChanged();
  $('metric-catalog').innerHTML=source.metrics.map(m=>`<details><summary>${esc(m.name)} · ${(Number(m.value)*100).toFixed(1)}% · ${esc(m.source_kind)}</summary><p>${esc(m.period)} / ${esc(m.market)} / ${esc(m.channel)} / ${esc(m.basis)}</p><p>${esc(m.scope)}</p><p>${esc(m.methodology)}</p><p>${esc(m.assumptions)}</p>${m.source_url?`<a href="${esc(m.source_url)}" target="_blank" rel="noopener">查看原始发布来源</a>`:'<span class="badge">纯模拟，无外部统计来源</span>'}</details>`).join('');
  const matching=cases.filter(c=>c.candidate_id===cid);
  const selectedQuote=$('quote-selection').value;
  $('quote-selection').innerHTML='<option value="">手工模拟采购成本</option>'+matching.filter(c=>c.quote_available).map(c=>`<option value="${c.id}">SIM · ¥${(c.quote.purchase_cny_cents/100).toFixed(2)} · ${c.id.slice(0,8)}</option>`).join('');
  if(matching.some(c=>c.id===selectedQuote&&c.quote_available))$('quote-selection').value=selectedQuote;
  const labels={rfq_sent:'模拟发出询价',quoted:'模拟供应商返回报价',sample_requested:'模拟申请样品',sample_received:'模拟收到样品',accepted:'模拟接受方案',rejected:'模拟拒绝方案'};
  $('supplier-cases').innerHTML=matching.map(c=>`<div class="item"><b>${esc(c.supplier.name)}</b> <span class="badge">simulation · ${c.status} · v${c.version}</span><p class="meta">${c.id}</p>${c.quote_available?`<p>模拟采购 ¥${(c.quote.purchase_cny_cents/100).toFixed(2)}，MOQ ${c.quote.moq}，交期 ${c.quote.lead_days} 天</p>`:''}${c.allowed_transitions.map(t=>`<button onclick="supplierTransition('${c.id}','${t}',${c.version})">${labels[t]}</button>`).join('')}<details><summary>模拟流程历史</summary><pre>${esc(JSON.stringify(c.history,null,2))}</pre></details></div>`).join('')||'<p>当前候选尚无模拟供应商流程。</p>';
  setRoleButtons(sellerRole);
  await loadMetricScenarios();
  checkSellerAccess(access);if(request!==sourceRead||cid!==$('candidate').value)return;
  const available=matching.filter(c=>c.quote_available);
  for(const [id,index] of [['compare-quote-a',0],['compare-quote-b',1]]){
    const old=$(id).value;
    $(id).innerHTML='<option value="">请选择模拟报价</option>'+available.map(c=>`<option value="${c.id}">SIM · ¥${(c.quote.purchase_cny_cents/100).toFixed(2)} · MOQ ${c.quote.moq} · ${c.quote.lead_days} 天 · ${c.id.slice(0,8)}</option>`).join('');
    $(id).value=available.some(c=>c.id===old)?old:(available[index]?.id||'');
  }
  await loadProfitComparisons();
}

let scenarioMetrics=[],scenarioCandidate='',scenarioRows=[],scenarioRequest=null;
function scenarioMetricChanged(){
  const metric=scenarioMetrics.find(m=>m.id===$('scenario-metric').value);
  $('scenario-amount-label').textContent=metric?.allowed_usage==='simulated_item_loss_scenario'?'每次单件退货净损失假设（USD 分）':'场景销售额（USD 分）';
}
async function saveMetricScenario(event){
  event.preventDefault();
  const button=event.submitter;button.disabled=true;
  try{
    const metric=scenarioMetrics.find(m=>m.id===$('scenario-metric').value);
    const data={candidate_id:$('candidate').value,metric_id:metric.id,amount_cents:Number($('scenario-amount').value),usage:metric.allowed_usage,assumption_note:$('scenario-note').value};
    const fingerprint=JSON.stringify(data);
    if(!scenarioRequest||scenarioRequest.fingerprint!==fingerprint)scenarioRequest={fingerprint,key:crypto.randomUUID()};
    await api('/v1/commerce/metric-scenarios',data,{'Idempotency-Key':scenarioRequest.key});
    scenarioRequest=null;await loadMetricScenarios();notify('场景与指标版本已保存；未自动修改任何成本。');
  }catch(e){notify(e.message)}finally{button.disabled=sellerRole==='viewer'}
}
async function loadMetricScenarios(){
  const access=sellerAccess(),request=++scenarioRead,cid=$('candidate').value;
  if(scenarioCandidate!==cid){clearAftersalesScenario();scenarioCandidate=cid}
  if(!cid){$('metric-scenarios').textContent='先创建候选 SKU，再保存测算。';return}
  const rows=await api('/v1/commerce/metric-scenarios?candidate_id='+encodeURIComponent(cid));
  checkSellerAccess(access);if(request!==scenarioRead||$('candidate').value!==cid)return;
  scenarioRows=rows;
  $('metric-scenarios').innerHTML=rows.map(r=>{const s=r.snapshot;return `<div class="item"><b>${esc(s.metric_snapshot.name)}</b> <span class="badge">${esc(s.metric_snapshot.source_kind)}</span><p>${s.input_role==='sales_amount'?'销售额参照':'每次退货损失假设'} ${money(s.input_cents)} × ${(Number(s.metric_snapshot.value)*100).toFixed(1)}% = <b>${money(s.result_cents)}</b></p><p class="meta">${s.application==='reference_only'?'仅行业销售基准参照，不能采用为单件售后成本。':'模拟的每件期望损失，可显式采用为售后成本。'}</p><p>${esc(s.assumption_note)}</p>${s.application==='optional_simulated_aftersales_cost'?`<button onclick="useAftersalesScenario('${r.id}')">采用场景售后成本</button>`:''}<details><summary>查看完整来源与计算快照</summary><pre>${esc(JSON.stringify(s,null,2))}</pre></details></div>`}).join('')||'<p>当前候选尚无已保存场景。</p>';
  setRoleButtons(sellerRole);
}
function useAftersalesScenario(id){
  const row=scenarioRows.find(r=>r.id===id&&r.candidate_id===$('candidate').value);
  if(!row||row.snapshot.application!=='optional_simulated_aftersales_cost'){notify('请刷新当前候选的可用场景。');return}
  document.querySelector('[name=aftersales_cents]').value=row.snapshot.result_cents;
  $('aftersales-scenario-id').value=id;
  $('aftersales-scenario-label').textContent='已采用模拟场景：'+id.slice(0,8)+'；保存决策时会再次校验。';
  notify('已填入模拟场景售后成本，确认其他成本后再保存决策。');
  openSellerModule('sourcing','cost-evaluation');
}
function clearAftersalesScenario(){
  $('aftersales-scenario-id').value='';$('aftersales-scenario-label').textContent='未引用场景，售后成本按手工假设处理。';
}

let comparisonRows=[],comparisonCandidate='',comparisonRequest=null;
async function saveProfitComparison(event){
  event.preventDefault();const button=event.submitter;button.disabled=true;
  try{
    const baseline=readAssumptions();
    for(const name of ['purchase_cny_cents','supplier_quote_id','comparison_id','comparison_option'])baseline[name]=null;
    const data={candidate_id:$('candidate').value,quote_ids:[$('compare-quote-a').value,$('compare-quote-b').value],baseline,
      stress:{price_cents:Number($('stress-price').value),cny_per_usd:$('stress-fx').value,logistics_cents:Number($('stress-logistics').value)},note:$('comparison-note').value};
    const fingerprint=JSON.stringify(data);
    if(!comparisonRequest||comparisonRequest.fingerprint!==fingerprint)comparisonRequest={fingerprint,key:crypto.randomUUID()};
    const saved=await api('/v1/commerce/profit-comparisons',data,{'Idempotency-Key':comparisonRequest.key});
    comparisonRequest=null;await loadProfitComparisons(saved.id);
    notify('比较已保存。选择一行情景可填入成本表单，再保存新决策。');
  }catch(e){notify(e.message)}finally{button.disabled=sellerRole==='viewer'}
}
async function loadProfitComparisons(preferred=null){
  const access=sellerAccess(),request=++comparisonRead,cid=$('candidate').value;
  if(comparisonCandidate!==cid){clearComparisonReference();comparisonCandidate=cid;comparisonRows=[]}
  if(!cid){$('comparison-history').innerHTML='';$('comparison-results').textContent='先创建候选商品并获得两份模拟报价。';return}
  const rows=await api('/v1/commerce/profit-comparisons?candidate_id='+encodeURIComponent(cid));
  checkSellerAccess(access);if(request!==comparisonRead||$('candidate').value!==cid)return;
  const old=$('comparison-history').value;comparisonRows=rows;
  $('comparison-history').innerHTML=rows.map(r=>`<option value="${r.id}">${esc(new Date(r.created_at*1000).toLocaleString())} · ${r.id.slice(0,8)}</option>`).join('');
  const selected=preferred||old;
  if(rows.some(r=>r.id===selected))$('comparison-history').value=selected;
  showProfitComparison();
}
async function loadComparisonById(){const access=sellerAccess(),cid=$('candidate').value,id=$('comparison-lookup').value.trim();try{if(!/^[a-f0-9]{32}$/.test(id))throw Error('请输入完整的32位比较ID');const row=await api('/v1/commerce/profit-comparisons/'+id);checkSellerAccess(access);if(cid!==$('candidate').value)return;if(row.candidate_id!==cid)throw Error('比较不属于当前候选');comparisonRows=comparisonRows.filter(r=>r.id!==id).concat([row]);const option=document.createElement('option');option.value=id;option.textContent=id;$('comparison-history').appendChild(option);$('comparison-history').value=id;showProfitComparison()}catch(e){notify(e.message)}}
function showProfitComparison(){
  const row=comparisonRows.find(r=>r.id===$('comparison-history').value);
  if(!row){$('comparison-results').textContent='选择两份可用模拟报价并保存比较。基线采用“成本与风险评估”表单，采购金额分别取自两份报价。';return}
  const s=row.snapshot;
  const quotes=s.quotes.map((q,index)=>`<div class="item"><b>方案 ${index===0?'A':'B'} · ${q.case_id.slice(0,8)}</b> <span class="badge">simulation · v${q.case_version}</span><p>采购 ¥${(q.quote.purchase_cny_cents/100).toFixed(2)} / 件 · MOQ ${q.quote.moq} · 交期 ${q.quote.lead_days} 天</p><p class="meta">最低批量货值 ¥${(q.minimum_batch_purchase_cny_cents/100).toFixed(2)} ≈ ${money(q.minimum_batch_purchase_usd_cents)}（基线汇率；不含物流、支付、税费及其他成本）</p></div>`).join('');
  const rows=s.options.map(o=>{const a=o.evaluation.assumptions;return `<tr${o.case==='combined_stress'?' class="stress-row"':''}><td>${s.quotes[0].case_id===o.quote_id?'A':'B'}</td><th scope="row">${esc(o.label)}</th><td>${money(a.price_cents)}</td><td>${esc(a.cny_per_usd)}</td><td>${money(a.logistics_cents)}</td><td class="profit-number ${o.evaluation.unit_profit_cents<=0?'loss':''}">${money(o.evaluation.unit_profit_cents)}</td><td>${money(o.difference_from_baseline_cents)}</td><td>${esc(o.evaluation.conclusion)}</td><td><button class="secondary" onclick="useComparisonOption('${o.key}')">采用此情景</button></td></tr>`}).join('');
  $('comparison-results').innerHTML=`<p>${esc(s.note)}</p><div class="fields">${quotes}</div><div class="tablewrap"><table><caption>模拟每件贡献利润 · 相对各自报价基线的变化</caption><thead><tr><th>方案</th><th>情景</th><th>售价</th><th>CNY/USD</th><th>物流</th><th>每件贡献</th><th>较基线</th><th>演示结论</th><th>填入表单</th></tr></thead><tbody>${rows}</tbody></table></div><p class="meta">不是经营预测或置信区间，不自动接受报价。支付费沿用单件决策假设；销售额退货占比仅参考，售后与获客成本保持原假设。</p><details><summary>查看比较完整来源与输入</summary><pre>${esc(JSON.stringify(s,null,2))}</pre></details>`;
  setRoleButtons(sellerRole);
}
function useComparisonOption(key){
  const row=comparisonRows.find(r=>r.id===$('comparison-history').value&&r.candidate_id===$('candidate').value);
  const option=row?.snapshot.options.find(o=>o.key===key);
  if(!option){notify('请刷新当前候选的比较记录。');return}
  const a=option.evaluation.assumptions;
  if(!Array.from($('quote-selection').options).some(o=>o.value===a.supplier_quote_id)){notify('该模拟报价当前不可用，请重新生成比较。');return}
  const form=$('assumptions');
  for(const [name] of fields)form.elements.namedItem(name).value=a[name]??'';
  for(const name of ['risk','source_note','returns_metric_id','supplier_quote_id','aftersales_scenario_id'])form.elements.namedItem(name).value=a[name]??'';
  $('aftersales-scenario-label').textContent=a.aftersales_scenario_id?'沿用比较中的模拟售后场景：'+a.aftersales_scenario_id.slice(0,8):'未引用场景，售后成本按手工假设处理。';
  $('comparison-id').value=row.id;$('comparison-option').value=key;
  $('comparison-reference-label').textContent='已采用比较 '+row.id.slice(0,8)+' · '+option.label+'；保存时校验参数与报价版本。';
  notify('情景已填入成本表单。确认后点击“保存一次新决策”；不会修改旧版本。');
  openSellerModule('sourcing','cost-evaluation');
}
function clearComparisonReference(){
  $('comparison-id').value='';$('comparison-option').value='';$('comparison-reference-label').textContent='未引用比较，成本按当前表单假设处理。';
}

let catalogCategories=[],sellerCatalogStatus='loading';
const SELLER_CATALOG_MESSAGES={loading:'正在加载商品与品类…',identity_changed:'访问凭证已更改，商品与品类尚未重新加载。请点击“刷新商品与品类”。',error:'商品与品类加载失败，请点击“刷新商品与品类”重试。'};
function setSellerCatalogStatus(status){
  sellerCatalogStatus=status;
  const select=$('product-category-filter');select.disabled=status!=='ready';
  if(status!=='ready'){
    select.innerHTML=`<option value="">${esc(SELLER_CATALOG_MESSAGES[status])}</option>`;select.value='';
    $('product-count').textContent=SELLER_CATALOG_MESSAGES[status];
    $('products').textContent=SELLER_CATALOG_MESSAGES[status];
  }
}
async function refreshSellerCatalog(){
  const access=sellerAccess();await refresh();
  if(access.generation===sellerOrderAccessGeneration&&access.key===$('key').value&&sellerCatalogStatus==='ready')notify('商品与品类已重新加载。');
}
function showSellerProducts(publishedOnly=false){
  $('product-search').value='';
  $('product-category-filter').value='';
  $('product-status-filter').value=publishedOnly?'published':'';
  renderSellerProducts();
  openSellerModule('products','product-list');
}
function productCategoryId(product){
  const id=product.snapshot?.candidate?.source_json?.dataset;
  return catalogCategories.some(c=>c.id===id)?id:'other';
}
function renderSellerProducts(){
  if(sellerCatalogStatus!=='ready'){setSellerCatalogStatus(sellerCatalogStatus);return}
  const keyword=$('product-search').value.trim().toLocaleLowerCase();
  const status=$('product-status-filter').value,category=$('product-category-filter').value;
  const all=state.products||[];
  const rows=all.filter(p=>(!status||p.status===status)&&(!category||productCategoryId(p)===category)&&(!keyword||[p.title,p.id,productCategoryLabel(p),p.snapshot?.candidate?.source_json?.dataset].some(value=>String(value||'').toLocaleLowerCase().includes(keyword))));
  const filters=[keyword?'搜索“'+$('product-search').value.trim()+'”':'',status?(status==='published'?'已上架':'草稿 / 已下架'):'',category?productCategoryLabel({snapshot:{candidate:{source_json:{dataset:category}}}}):''].filter(Boolean);
  $('product-count').textContent=`显示 ${rows.length} / 共 ${all.length} 件商品；已上架 ${all.filter(p=>p.status==='published').length} 件。当前筛选：${filters.join('、')||'全部商品'}。草稿状态同时包含未上架和已下架商品。`;
  $('products').innerHTML=rows.map(renderSellerProduct).join('')||(all.length?'<p>没有符合筛选的商品，请调整关键词、状态或品类。</p>':'<p>通过评估后可生成草稿。</p>');
  setRoleButtons(sellerRole);
}
function renderSellerProduct(p){
  const options=state.decisions.filter(d=>d.candidate_id===p.snapshot.candidate.id&&d.id!==p.decision_id&&d.snapshot.conclusion==='GO'&&!state.products.some(product=>product.decision_id===d.id&&(product.stock||product.reserved||product.status==='published')));
  return `<article class="item product-row"><div class="product-thumb" role="img" aria-label="商品图片未提供"><svg viewBox="0 0 32 32" fill="none" stroke="currentColor" aria-hidden="true"><path d="m5 10 11-6 11 6-11 6ZM5 10v12l11 6 11-6V10M16 16v12M10 7l11 6"/></svg></div><div class="product-description"><p class="product-name">${esc(p.title)}</p><p class="meta">SKU ${esc(p.id)} · 品类：${esc(productCategoryLabel(p))}</p>${sellerBadge(p.status,p.status==='published'?'已上架':'草稿 / 已下架')}</div><div class="product-price">${money(p.price_cents)}<small>可售 ${p.stock} · 预留 ${p.reserved}</small></div><button class="secondary" data-seller-permission="read" onclick="this.focus();this.closest('.product-row').querySelector('dialog').showModal()">管理商品</button><dialog class="inventory-drawer" aria-labelledby="inventory-title-${esc(p.id)}"><div class="drawer-heading"><h3 id="inventory-title-${esc(p.id)}">库存与上架</h3><button type="button" class="secondary" data-seller-permission="read" onclick="this.closest('dialog').close()">关闭</button></div><p class="product-name">${esc(p.title)}</p><p class="meta">SKU ${esc(p.id)}</p><p>可售 ${p.stock} · 预留 ${p.reserved}</p><div class="drawer-section"><label>入库数量<input id="stock-${p.id}" type="number" min="1" value="10"></label><button class="secondary" onclick="mutate('/products/${p.id}/stock',{quantity:Number($('stock-${p.id}').value)})">确认入库</button>${p.status==='draft'?`<button onclick="mutate('/products/${p.id}/publish',{})">上架</button>`:`<button class="secondary" onclick="mutate('/products/${p.id}/unpublish',{})">下架</button><p class="meta">下架只停止新购买，已创建订单继续处理。</p>${options.length?`<label>替换为同候选的新决策<select id="replace-${p.id}">${options.map(d=>`<option value="${d.id}">${d.id.slice(0,8)} · ${money(d.snapshot.assumptions.price_cents)}</option>`).join('')}</select></label><p class="meta">将此商品可售库存转入新 SKU 并下架旧版本；有待支付预留时先处理订单。历史订单不变。</p><button onclick="mutate('/products/${p.id}/replace',{decision_id:$('replace-${p.id}').value})">替换上架版本</button>`:''}`}</div></dialog></article>`;
}
function productCategoryLabel(product){
  const category=catalogCategories.find(c=>c.id===productCategoryId(product));
  return category?[category.name_zh,category.name].filter(Boolean).join(' / '):'其他 / Other';
}
function renderCatalogStages(data){
  if(!Array.isArray(data.categories))throw Error('品类数据格式无效，请重新加载');
  catalogCategories=data.categories;
  const selected=$('product-category-filter').value;
  $('product-category-filter').innerHTML='<option value="">全部品类</option>'+data.categories.map(c=>{
    const products=(state.products||[]).filter(p=>productCategoryId(p)===c.id);
    return `<option value="${esc(c.id)}">${esc([c.name_zh,c.name].filter(Boolean).join(' / '))} · ${products.length} 件 / 已上架 ${products.filter(p=>p.status==='published').length} 件</option>`;
  }).join('');
  if(data.categories.some(c=>c.id===selected))$('product-category-filter').value=selected;
  $('catalog-stages').innerHTML=`<div class="tablewrap"><table><thead><tr><th>分析品类</th><th>候选 SKU</th><th>商品草稿</th><th>已上架 SKU</th><th>有货 SKU</th><th>操作</th></tr></thead><tbody>${data.categories.map(c=>`<tr><th scope="row">${esc(c.name_zh)}</th><td>${c.candidates}</td><td>${c.drafts}</td><td>${c.published}</td><td>${c.in_stock}</td><td>${c.id==='other'?'':`<button data-seller-permission="read" class="secondary" onclick="selectCatalogCategory('${c.id}')">查看该品类</button>`}</td></tr>`).join('')}</tbody></table></div>`;
  setSellerCatalogStatus('ready');
}
async function selectCatalogCategory(id,announce=true){
  const access=sellerAccess();
  try{
  if(!Array.from($('dataset').options).some(o=>o.value===id))return;
  $('dataset').value=id;
  const candidate=state.candidates?.find(c=>c.source_json.dataset===id);
  if(candidate){$('candidate').value=candidate.id;await refreshSources()}
  const category=catalogCategories.find(c=>c.id===id);
  $('name').value='改进款'+(category?.name_zh||id);
  await loadEvidence();
  checkSellerAccess(access);
  if(announce){notify('已选择'+(category?.name_zh||id)+'。创建候选和通过决策后，还需生成草稿、入库并上架，商城才会显示。');openSellerModule('insights','quick-opportunities')}
  }catch(e){notify(e.message)}
}

/* Navigation reads only the selected module; forms stay in place. */
let sellerWorkspaceReady=false;
function updateSellerCandidateContext(){
  const note=document.getElementById('candidate-context-note');
  if(!note)return;
  const selected=typeof state!=='undefined'?state.candidates?.find(c=>c.id===$('candidate').value):null;
  note.textContent=selected?'当前候选：'+selected.name+'。成本、模拟供应商、比较与场景测算均使用此候选。':'暂无候选商品。请先到“评论分析”建立候选，再填写成本。';
}
function sellerWorkspaceRoute(){
  const parts=location.hash.slice(1).split('/');
  const views=Array.from(document.querySelectorAll('[data-workspace-view]'));
  const view=views.find(node=>node.dataset.workspaceView===parts[0])||views.find(node=>node.dataset.workspaceView==='overview');
  const requested=parts.length===2?document.getElementById(parts[1]):null;
  const target=requested&&view?.contains(requested)&&requested.classList.contains('panel')?requested:null;
  return {views,view,target};
}
function renderSellerWorkspace(focus=false){
  if(!sellerWorkspaceReady)return;
  const {views,view,target}=sellerWorkspaceRoute();
  if(!view)return;
  const route='#'+view.dataset.workspaceView+(target?'/'+target.id:'');
  if(location.hash!==route)history.replaceState(null,'',location.pathname+location.search+route);
  for(const node of views)node.hidden=node!==view;
  for(const link of document.querySelectorAll('[data-workspace-link]')){
    if(link.dataset.workspaceLink===view.dataset.workspaceView)link.setAttribute('aria-current','page');
    else link.removeAttribute('aria-current');
  }
  for(const link of document.querySelectorAll('.section-nav a')){
    if(link.getAttribute('href')===route)link.setAttribute('aria-current','location');
    else link.removeAttribute('aria-current');
  }
  $('workspace-heading').textContent=view.dataset.title;
  $('workspace-breadcrumb').textContent=view.dataset.title;
  $('workspace-description').textContent=view.dataset.description;
  document.title=view.dataset.title+' · CrossBorder 卖家工作台';
  if(typeof loadSellerModule==='function')void loadSellerModule(view.dataset.workspaceView);
  if(focus){
    const heading=target?.querySelector('h2')||$('workspace-heading');
    heading.focus({preventScroll:true});heading.scrollIntoView({block:'start'});
    if(window.matchMedia('(max-width: 900px)').matches)$('workspace-menu').open=false;
  }else if(target)target.scrollIntoView({block:'start'});
}
function openSellerModule(view,section=''){
  if(!sellerWorkspaceReady)return;
  const route='#'+view+(section?'/'+section:'');
  if(location.hash===route)renderSellerWorkspace(true);else location.hash=route;
}
function initSellerWorkspace(){
  if(sellerWorkspaceReady||!document.querySelector('[data-workspace-view]'))return;
  sellerWorkspaceReady=true;
  for(const link of document.querySelectorAll('[data-workspace-link]')){link.dataset.short=link.textContent.trim().slice(0,1);link.setAttribute('title',link.textContent.trim())}
  sellerKeyValue=$('key')?.value||'';
  $('key')?.addEventListener?.('input',sellerKeyInput);
  const mobile=window.matchMedia('(max-width: 900px)');
  $('workspace-menu').open=!mobile.matches;
  mobile.addEventListener('change',event=>{$('workspace-menu').open=!event.matches});
  document.addEventListener('click',event=>{
    const link=event.target.closest('a');
    if(!link||event.defaultPrevented||event.button!==0||event.ctrlKey||event.metaKey||event.shiftKey||event.altKey)return;
    const href=link.getAttribute('href');
    if(link.classList.contains('skip-link')){event.preventDefault();$('workspace-heading').focus();return}
    if(href?.startsWith('#')&&href===location.hash){event.preventDefault();renderSellerWorkspace(true)}
  });
  window.addEventListener('hashchange',()=>renderSellerWorkspace(true));
  renderSellerWorkspace(false);
  updateSellerCandidateContext();
}
window.addEventListener('DOMContentLoaded',initSellerWorkspace);

// Guards are installed after the workbench helpers have initialized.
function installSellerWriteGuards(){for(const name of ['saveMetricScenario','saveProfitComparison']){if(name==='saveMetricScenario')saveMetricScenario=guardSellerOperation(name,saveMetricScenario);else saveProfitComparison=guardSellerOperation(name,saveProfitComparison)}if(typeof useReviewTheme==='function')useReviewTheme=guardSellerOperation('review-candidate',useReviewTheme)}
