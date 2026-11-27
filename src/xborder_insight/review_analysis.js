/* Persisted analysis is a source, independent from simulated trading. No key UI. */
let reviewConfig=null,importedReviews=null,reviewRun=null,reviewRequest=null,reviewSubmitting=false,reviewTimer=null,reviewGeneration=0,reviewPollStarted=0,reviewPollFailures=0;
function resetReviewIdentity(){
  clearTimeout(reviewTimer);reviewTimer=null;reviewGeneration++;
  reviewConfig=null;importedReviews=null;reviewRun=null;reviewRequest=null;reviewSubmitting=false;
  for(const id of ['review-history','review-result','review-run-status','review-theme','review-config','review-import-status'])if($(id))$(id).textContent='';
  if($('review-file'))$('review-file').value='';
}
function updateReviewButtons(){
  if(!$('review-submit'))return;
  const live=$('review-mode').value==='live';
  const force=!!$('review-force').checked;
  $('review-submit').disabled=reviewSubmitting||sellerRole==='viewer'||(live&&(sellerRole!=='owner'||(force&&(!reviewConfig?.configured||reviewConfig.requests_remaining<=0))));
  $('review-use-theme').disabled=sellerRole==='viewer'||!reviewRun?.result?.themes?.length||!['succeeded','partial'].includes(reviewRun.status);
  $('review-import-button').disabled=sellerRole==='viewer'||live;
  $('review-source').disabled=live;$('review-file').disabled=live;
  $('review-dataset').disabled=live;
  if(live){$('review-dataset').value='pet_fountain';$('review-source').value='samples'}
  $('review-mode-note').textContent=live?'相同输入优先复用已完成结果，不新增请求；需要新分析时，仅将原宠物饮水机模拟评论前10条发送到百炼。本次追加授权最多20次请求，包含重试；旧授权独立保留，重启不重置。':'离线规则分析不调用外部模型。可使用内置模拟评论或导入的最多10条评论。';
}
async function refreshReviewAnalyses(preferred,expectedGeneration){
  if(!$('review-history'))return;
  const [config,rows]=await Promise.all([api('/v1/commerce/review-analysis-config'),api('/v1/commerce/review-analyses')]);
  if(expectedGeneration!==undefined&&expectedGeneration!==reviewGeneration)return;
  reviewConfig=config;
  $('review-config').textContent=`${config.model} · ${config.configured?'本机凭证配置完整':'待填写本机私有凭证'} · ${config.budget_label||'当前授权'} · 真实请求 ${config.requests_used}/${config.request_limit} · 历史各授权累计${(config.authorization_history||[]).reduce((sum,b)=>sum+b.requests_used,0)}次 · 单批最多${config.review_limit}条 · 最多${config.concurrency||3}条并发 · 相同输入默认复用结果 · 聚类使用离线hash向量`;
  const old=preferred||$('review-history').value;
  $('review-history').innerHTML='<option value="">请选择已保存任务</option>'+rows.map(r=>`<option value="${r.id}">${esc(new Date(r.created_at*1000).toLocaleString())} · ${esc(r.dataset)} · ${r.mode==='live'?'真实模型':'离线规则'} · ${r.status} · ${r.request_count}次请求</option>`).join('');
  if(rows.some(r=>r.id===old))$('review-history').value=old;
  updateReviewButtons();
}
async function loadReviewById(){const id=$('review-lookup').value.trim();if(!/^[a-f0-9]{32}$/.test(id)){notify('请输入完整的32位任务ID');return}const select=$('review-history');const option=document.createElement('option');option.value=id;option.textContent=id;select.appendChild(option);select.value=id;await loadReviewAnalysis()}
async function importReviewFile(){
  const access=sellerAccess();
  try{
    const file=$('review-file').files[0];
    if(!file)throw Error('请选择JSONL或CSV评论文件');
    if(file.size>65000)throw Error('文件过大，请先裁剪到最多10条评论及65KB以内');
    const format=file.name.toLowerCase().endsWith('.csv')?'csv':'jsonl';
    const text=await file.text();checkSellerAccess(access);
    const result=await api('/v1/commerce/review-import',{format,text});
    importedReviews=result.reviews;$('review-source').value='import';
    $('review-import-status').textContent=`已校验${result.count}条导入评论，来源未核验；当前仅用于离线分析，不发送到百炼。`;
    reviewRequest=null;
  }catch(e){if(e.stale)return;importedReviews=null;notify(e.message)}
}
async function submitReviewAnalysis(){
  if(reviewSubmitting)return;
  const access=sellerAccess();
  reviewSubmitting=true;updateReviewButtons();
  try{
    const mode=$('review-mode').value;
    const body={dataset:mode==='live'?'pet_fountain':$('review-dataset').value,mode,force_refresh:!!$('review-force').checked};
    if(mode!=='live'&&$('review-source').value==='import'){
      if(!importedReviews)throw Error('请先选择文件并点击“校验导入评论”');
      body.reviews=importedReviews;
    }
    const fingerprint=JSON.stringify(body);
    if(!reviewRequest||reviewRequest.fingerprint!==fingerprint)reviewRequest={fingerprint,key:crypto.randomUUID()};
    const run=await api('/v1/commerce/review-analyses',body,{'Idempotency-Key':reviewRequest.key});
    reviewRequest=null;
    await refreshReviewAnalyses(run.id);await loadReviewAnalysis();
    notify(run.reused_result?'已复用同输入、同版本的完整结果，本次没有新增模型请求。':'分析任务已保存，最多3条并发；下方显示实际已完成条数。');
  }catch(e){notify(e.message)}finally{if(access.generation===sellerOrderAccessGeneration&&access.key===$('key').value){reviewSubmitting=false;updateReviewButtons()}}
}
async function loadReviewAnalysis(){
  clearTimeout(reviewTimer);reviewTimer=null;
  const generation=++reviewGeneration;reviewPollFailures=0;
  const id=$('review-history').value;
  if(!id){reviewRun=null;$('review-result').textContent='选择已保存任务查看结果。';updateReviewButtons();return}
  try{
    const run=await api('/v1/commerce/review-analyses/'+id);
    if($('review-history').value!==id||generation!==reviewGeneration)return;
    reviewRun=run;
    const p=run.provenance,result=run.result?.extractions?run.result:null;
    renderReviewProgress(run);
    if(run.provenance)$('review-run-status').textContent+=` · ${p.review_data_kind} · ${p.analysis_mode}`;
    $('review-theme').innerHTML=(result?.themes||[]).map(t=>`<option value="${t.theme_id}">${esc(t.display_name)} · ${esc(t.polarity)} · ${t.mention_count}次提及</option>`).join('');
    $('review-result').innerHTML=result?`<p>共${result.review_count}条，校验通过${result.parsed_count}条，解析成功率${(result.parse_success_rate*100).toFixed(1)}%。已返回响应报告Token：输入${result.prompt_tokens}，输出${result.completion_tokens}；失败请求也可能计费。</p><p class="meta">${esc(p.model)} · ${esc(p.prompt_version)} · ${esc(p.taxonomy_version)}。模型置信度未经概率校准；机会分数不代表真实需求。</p>${result.extractions.map(row=>`<details><summary>${esc(row.review_id)} · ${row.status} · ${row.attempts}轮</summary><p>${esc(row.input.body)}</p>${row.extraction?row.extraction.points.map(point=>`<p><b>${esc(point.label)}</b> · ${esc(point.polarity)} · 置信度${point.confidence}<br>“${esc(point.evidence)}”</p>`).join('')||'<p>没有归类标签。</p>':'<p>未通过校验，不作为有效评论参与机会聚合。</p>'}</details>`).join('')}`:'<p>任务尚无结果。刷新与查看详情不会再次调用模型。</p>';
    updateReviewButtons();
    if(['queued','running'].includes(run.status)){reviewPollStarted=Date.now();reviewTimer=setTimeout(()=>pollReviewProgress(id,generation),500)}
  }catch(e){notify(e.message)}
}
function renderReviewProgress(run){
  const progress=run.progress||run.result?.progress;
  $('review-run-status').textContent=`${run.status} · ${progress?'已完成'+progress.completed+'/'+progress.total+'条，校验通过'+progress.parsed+'条 · ':''}请求次数${run.request_count}${run.error_code?' · '+run.error_code:''}`;
}
async function pollReviewProgress(id,generation){
  try{
    const progress=await api('/v1/commerce/review-analyses/'+id+'/progress');
    if(generation!==reviewGeneration||$('review-history').value!==id)return;
    reviewPollFailures=0;renderReviewProgress(progress);
    if(['queued','running'].includes(progress.status))reviewTimer=setTimeout(()=>pollReviewProgress(id,generation),Date.now()-reviewPollStarted<5000?500:1500);
    else{await refreshReviewAnalyses(id,generation);if(generation===reviewGeneration)await loadReviewAnalysis()}
  }catch(e){if(e.stale||generation!==reviewGeneration||$('review-history').value!==id)return;reviewPollFailures++;if(reviewPollFailures<=3){notify('进度读取失败，正在重试（'+reviewPollFailures+'/3）');reviewTimer=setTimeout(()=>pollReviewProgress(id,generation),1000*2**(reviewPollFailures-1))}else{reviewTimer=null;notify('进度读取已暂停；点击查看详情恢复读取，不会重新提交分析。')}}
}
async function useReviewTheme(){
  const access=sellerAccess();
  try{
    if(!reviewRun||!['succeeded','partial'].includes(reviewRun.status))throw Error('请先选择可用分析结果');
    const name=$('review-name').value.trim();if(!name)throw Error('请填写候选名称');
    const created=await api('/v1/commerce/candidates',{name,dataset:reviewRun.dataset,theme_id:$('review-theme').value,analysis_id:reviewRun.id});
    if(!await refresh())throw Error('候选已保存，但页面读取失败，请重试读取，不要重复提交。');checkSellerAccess(access);$('candidate').value=created.id;await refreshSources();
    notify('已从保存的主题创建候选，未再次调用模型；请继续核对成本与风险，保存独立站决策。');
    openSellerModule('sourcing','cost-evaluation');
  }catch(e){notify(e.message)}
}
