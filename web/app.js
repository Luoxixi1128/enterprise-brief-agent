const $=s=>document.querySelector(s), main=$('#main'), dialog=$('#dialog');
const E=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const token=$('meta[name="workspace-token"]').content;
const uploadingTasks=new Set();
let state={tasks:[],cases:[],status:null,task:null,tab:'agent',route:'tasks'},editState=null,poll=null;
const date=s=>s?new Date(s).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'';
function toast(s,bad=false){const el=$('#toast');el.textContent=s;el.style.background=bad?'#984b40':'#171614';el.style.display='block';clearTimeout(el.timer);el.timer=setTimeout(()=>el.style.display='none',6000)}
async function api(path,body){const opts=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Workspace-Token':token},body:JSON.stringify(body)};let res;try{res=await fetch('/api'+path,opts)}catch{throw Error('暂时无法连接网站，请检查网络后刷新页面。')}const data=await res.json();if(!res.ok)throw Error(data.error||'请求失败');return data}
function displayStatus(s){return ({'待审核':'待确认','内部已审核':'已确认','可发布':'已确认'})[s]||s}
function pill(s){s=displayStatus(s);const cls=/失败|中断/.test(s)?'red':s==='已确认'||s==='已发布'?'green':/正在/.test(s)?'blue':/待确认|待补充|待更新/.test(s)?'amber':s==='待上传'?'purple':'subtle';return `<span class="pill ${cls}"><i class="status-dot"></i>${E(s)}</span>`}
function heading(title,desc='',actions=''){return `<div class="page-heading"><div><div class="eyebrow">FDE X / REQUIREMENTS</div><h1>${E(title)}</h1><p class="muted">${E(desc)}</p></div><div class="heading-actions">${actions}</div></div>`}
function btn(text,action,extra='',cls=''){return `<button class="${cls}" data-action="${action}" ${extra}>${text}</button>`}
function modal(title,body,footer='',wide=false){dialog.classList.toggle('dialog-wide',wide);$('#dialog-content').innerHTML=`<div class="dialog-head"><h2>${E(title)}</h2>${btn('×','close','aria-label="关闭"')}</div><div class="dialog-body">${body}</div>${footer?`<div class="toolbar">${footer}</div>`:''}`;dialog.showModal()}
function raw(text){modal('材料内容',`<pre>${E(text)}</pre>`,'',true)}
async function refreshStatus(){state.status=await api('/status')}
async function route(){clearTimeout(poll);window.scrollTo(0,0);const hash=location.hash.slice(1)||'tasks';try{await refreshStatus();state.tasks=await api('/tasks');$('#task-count').textContent=state.tasks.length;state.route=hash.split('/')[0];document.querySelectorAll('[data-route]').forEach(b=>b.classList.toggle('active',b.dataset.route===state.route||b.dataset.route==='tasks'&&state.route==='task'));if(state.route==='task'){state.task=await api('/tasks/'+hash.split('/')[1]);if(state.task.redirected_from)history.replaceState(null,'','#task/'+state.task.id);renderTask();}else if(state.route==='cases'){state.cases=await api('/cases');renderCases();}else if(state.route==='settings')renderSettings();else if(state.route==='releases')await renderReleases();else renderTasks();}catch(e){$('#breadcrumb').textContent='连接异常';main.innerHTML=`<section class="panel"><h2>工作台暂时无法加载</h2><div class="error-box">${E(e.message)}</div><p class="muted">连接异常不代表已保存的任务被删除。网络恢复后，再重新连接。</p>${btn('重新连接','reload-page','','primary')}</section>`}}
function renderTasks(){
 $('#breadcrumb').textContent='我的任务';
 const all=state.tasks, pending=all.filter(t=>displayStatus(t.status)==='待确认').length,done=all.filter(t=>t.status==='内部已审核').length;
 main.innerHTML=heading('把企业的模糊需求整理成可执行的任务','上传原始材料，补齐关键信息，确认后生成任务书。',btn('＋ 新建任务','new','','primary'))+`<div class="stats"><div class="stat"><span>全部任务</span><strong>${all.length}</strong></div><div class="stat"><span>待确认</span><strong>${pending}</strong></div><div class="stat"><span>已确认</span><strong>${done}</strong></div></div><section class="panel"><div class="panel-head"><h2>任务列表</h2><div class="list-tools">${btn('已删除任务','trash','','ghost')}<input id="task-search" class="search" placeholder="搜索任务或企业" aria-label="搜索任务或企业"></div></div><div id="task-list"></div></section>${!state.status.model.ready?`<div class="quiet-banner"><span>○</span><span>模型尚未连接。可以先整理材料、编辑已有任务书，待网站服务恢复后继续。</span>${btn('查看接入说明','settings')}</div>`:''}<section class="panel workspace-info-panel"><h2>你的独立工作区</h2><p>任务保存在云端，使用同一个浏览器可继续处理。请允许网站保存必要 Cookie；清除 Cookie、更换浏览器或连续90天未访问后，将无法找回原工作区。</p><p class="small muted">提交的材料会交给网站配置的模型服务进行分析。仅上传你有权处理的资料，重要结果请及时下载留存。${btn('查看使用说明','settings','','ghost')}</p></section>`;
 renderTaskRows(all);$('#task-search').addEventListener('input',e=>renderTaskRows(all.filter(t=>(t.title+t.company).toLowerCase().includes(e.target.value.toLowerCase()))));
}
function renderTaskRows(tasks){$('#task-list').innerHTML=tasks.length?`<div class="table-wrap"><table><thead><tr><th>任务名称</th><th>状态</th><th>材料</th><th>最近更新</th><th></th></tr></thead><tbody>${tasks.map(t=>`<tr><td class="title-cell">${E(t.title)}<small>${E(t.company||'未填写企业')}</small></td><td>${pill(t.status)}</td><td>${t.source_count} 份</td><td class="muted">${date(t.updated_at)}</td><td class="table-actions">${btn('打开任务 →','open',`data-id="${t.id}"`,'ghost')}${btn('删除','delete-task',`data-id="${t.id}"`,'ghost danger')}</td></tr>`).join('')}</tbody></table></div>`:`<div class="empty"><div class="empty-mark">▤</div><h2>${state.tasks.length?'没有匹配的任务':'开始整理第一份企业需求'}</h2><p>新建任务并上传材料，或直接写下需求，生成后审阅并下载文件。</p>${btn('＋ 新建任务','new','','primary')}</div>`}
function renderCases(){location.hash='tasks';}
async function showTrash(){const rows=await api('/trash');modal('已删除任务',`<p class="muted small">删除后保留原始材料、任务书和历史版本，可随时恢复。</p>${rows.length?rows.map(t=>`<div class="version-item"><div><strong>${E(t.title)}</strong><small>${E(t.company||'未填写企业')}${t.duplicate_of?' · 历史重复记录（材料与版本保留）':''}</small></div>${btn(t.duplicate_of?'打开或恢复已有任务':'恢复任务','undelete',`data-id="${t.id}"`)}</div>`).join(''):'<div class="empty">暂无已删除任务</div>'}`,btn('关闭','close'),true)}
function renderSettings(){
 $('#breadcrumb').textContent='使用说明';
 main.innerHTML=heading('使用说明','上传需求 → 查看任务书 → 补充确认 → 下载文件')+`<section class="panel"><h2>模型服务</h2><p>${state.status.model.ready?'网站已配置统一模型服务，你无需填写 API 密钥。':'网站暂未连接模型服务，请稍后再试。'}</p><h2>任务保存</h2><p>此浏览器拥有独立的云端工作区。相同浏览器中的其他使用者也能访问这个工作区，因此请使用自己的设备。</p><p>工作区依靠必要 Cookie 识别，连续90天未访问、清除 Cookie 或更换浏览器后无法找回；当前不支持账号登录和跨设备恢复。重要文件请及时下载留存。</p><h2>材料处理</h2><p>上传文件和补充说明会保存在托管服务器；点击生成或更新后，相关内容会发送给网站配置的模型接口。仅上传你有权处理的资料。运营者可维护服务器上的数据，工作区隔离不代表端到端加密。</p><p>“删除任务”会移入回收列表，材料与历史版本仍保留。当前公测版不提供永久删除入口。</p><h2>公测用量</h2><p>每个工作区最多20个任务，每个任务最多8份材料，单文件不超过4MB；每天最多${state.status.limits.daily_calls}次模型请求（按 UTC 日期重置）。一次完整处理通常需要多次请求。网站还有总调用与并发上限，达到上限时会保存进度并提示稍后继续。</p><p>模型生成的任务书需要你审阅后确认，再生成 Word 任务书和 Excel 输入样例表。第08节的输出格式描述业务任务的交付要求，不改变本产品的 Word / Excel 导出类型。</p></section>`;
}
function renderTask(){
 clearTimeout(poll);const t=state.task;$('#breadcrumb').textContent='我的任务';
 if(state.tab==='agent')state.tab=preferredTaskTab(t);
 const busy=t.busy?'disabled':'';
 main.innerHTML=`<div class="task-return">${btn('← 返回我的任务','tasks','','ghost')}<span>材料与进度保存在此浏览器的独立云端工作区</span>${btn('删除任务','delete-task',`data-id="${t.id}" ${busy}`,'ghost danger')}</div>`+heading(t.title,t.company||'企业需求拆解',pill(t.status))+`<nav class="task-steps" aria-label="任务步骤">${[['materials','提交需求','上传材料与修改意见'],['brief','任务书','查看正文，审阅并确认'],['confirmations','待确认事项','填写企业已明确的答案'],['versions','下载文件','获取任务书与输入样例表']].map(([k,n,h],i)=>`<button class="task-step ${state.tab===k?'active':''}" data-action="tab" data-id="${k}" ${state.tab===k?'aria-current="step"':''}><span class="step-number">${i+1}</span><span><strong>${n}</strong><small>${h}</small></span></button>`).join('')}</nav>${agentProgress(t)}<div id="task-content" class="task-workspace"></div>`;
 if(state.tab==='materials')renderMaterials();else if(state.tab==='brief')renderBrief();else if(state.tab==='confirmations')renderConfirmations();else renderVersions();
 bindAgentComposer();bindConfirmationDrafts();refreshReviewAction();
 if(t.busy)poll=setTimeout(async()=>{try{const fresh=await api('/tasks/'+t.id);if(location.hash==='#task/'+t.id&&state.task?.id===t.id){state.task=fresh;if(!fresh.busy){if(fresh.questions?.length)state.tab='materials';else if(fresh.brief&&state.tab==='materials')state.tab='brief';}renderTask();}}catch(e){toast(e.message,true)}},2000);
}
function renderMaterials(){
 const t=state.task;
 $('#task-content').innerHTML=`<div class="submission-layout"><div class="submission-main">${agentComposer(t)}</div>${processHistory(t)}</div>`;
}
async function uploadFiles(files){
 const tid=state.task.id;if(state.task.busy||uploadingTasks.has(tid)||!files?.length)return;
 uploadingTasks.add(tid);const batch=Array.from(files);let saved=0,failures=[];renderTask();
 try{for(const f of batch){
  if(f.size>12e6){failures.push(f.name+' 超过4MB');continue;}
  try{const data=await new Promise((resolve,reject)=>{const r=new FileReader();r.onload=()=>resolve(r.result.split(',')[1]);r.onerror=()=>reject(new Error('文件读取失败'));r.readAsDataURL(f)});const fresh=await api('/tasks/'+tid+'/upload',{name:f.name,data});if(state.task?.id===tid)state.task=fresh;saved++;}catch(e){failures.push(f.name+'：'+e.message);}
 }}finally{uploadingTasks.delete(tid);if(location.hash==='#task/'+tid&&state.task?.id===tid)renderTask();}
 toast([saved?`已保存 ${saved} 份材料，提交后${state.task?.brief?'更新':'生成'}任务书`:'',...failures].filter(Boolean).join('；'),!!failures.length);
}
function section(n,title,content,edit=''){return `<section class="section"><div class="section-title"><span>${n}</span><h2>${title}</h2>${edit?btn('编辑','edit',`data-id="${edit}"`):''}</div>${content}${/^(0[1-7])$/.test(n)?confirmationPreview(state.task.confirmations.filter(c=>c.section===n&&c.recorded)):""}</section>`}
function table(headers,rows){return `<div class="table-wrap"><table class="doc-table"><thead><tr>${headers.map(h=>`<th>${E(h)}</th>`).join('')}</tr></thead><tbody>${rows.map(r=>`<tr>${r.map(v=>`<td>${v}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`}
function confirmationPreview(rows){
 if(!rows.length)return '';
 const answer=c=>{const saved=state.task.answers[c.id]?.text||'';
  if(c.id==='C-FORMAT'){const selected=state.task.brief.output_options.find(o=>o.id===state.task.brief.selected_output);return [selected?'已选定：'+selected.label:'',saved].filter(Boolean).join('\n')||'待确认';}
  return c.recorded?(c.answer||saved):'待确认';};
 return `<div class="confirmation-preview">${table(['待确认事项','需要确认的内容','企业确认信息'],rows.map(c=>[E(c.topic),E(c.question),`<span class="confirmation-answer">${E(answer(c))}</span>`]))}</div>`;
}
function scoringTables(d,r){
 const dimensions=(items)=>table(['评价维度','评分','评分时看什么','1分','3分','5分'],items);
 return `<div class="rubric-block"><h3>KR1｜交付内容</h3><p class="muted">按第04部分的 ${d.outputs.length} 项输出逐项评分，每项分别评完整度、准确度和格式规范；KR1均分＝${d.outputs.length*3} 个分数之和 ÷ ${d.outputs.length*3}。</p>
 ${table(['维度','评分','1至5分怎么评','1分','3分','5分'],r.kr1_dimensions.map(([name,check,a1,a3,a5])=>[E(name),'1至5分',E(check),E(a1),E(a3),E(a5)]))}
 <h4>KR1 检查项（共 ${d.outputs.length} 项）</h4>${table(['检查项','完整度 1至5分','准确度 1至5分','格式规范 1至5分'],d.outputs.map((x,i)=>[`${i+1}. ${E(x.name)}`,'____','____','____']))}</div>
 <div class="rubric-block"><h3>KR2｜业务质量</h3><p class="muted">按下列${d.kr2_2.length}个维度分别打1—5分，KR2均分＝${d.kr2_2.length}个维度得分之和÷${d.kr2_2.length}。</p>
 ${table(['分数','统一评分标准'],r.quality_scale.map(row=>row.map(E)))}
 ${dimensions(d.kr2_2.map(x=>[E(x.name),'1至5分',E(x.company_check),E(x.anchor_1),E(x.anchor_3),E(x.anchor_5)]))}</div>
 <div class="rubric-block"><h3>KR3｜Skill 使用表现</h3><p class="muted">每个维度直接打1—5分，KR3均分＝4个维度得分之和÷4。</p>
 ${table(['分数','统一评分标准'],r.usage_scale.map(row=>row.map(E)))}
 ${dimensions(Object.entries(d.kr2_3).map(([name,x])=>[E(name),'1至5分',E(x.check),E(x.anchor_1),E(x.anchor_3),E(x.anchor_5)]))}</div>`;
}
function renderBrief(){
 const t=state.task,d=t.brief;
 if(!d){$('#task-content').innerHTML=`<div class="panel empty"><h2>任务书尚未生成</h2><p>先提交原始需求；生成后会在这里显示正文，供你审阅和修改。</p>${btn('去提交需求','tab','data-id="materials"','primary')}</div>`;return;}
 const scope=d.scope_assessment,err=t.validation;
 const unrecorded=t.confirmations.filter(c=>!c.recorded).length;
 const taxonomy=table(['大行业','细分行业','大岗位','细分岗位'],[['industry_l1','industry_l2','role_l1','role_l2'].map(k=>E(d.taxonomy[k]))]);
 $('#task-content').innerHTML=`${agentChanges(t)}<article class="panel brief-review">${err.length?`<div class="error-box">${err.map(E).join('<br>')}</div>`:''}
 <div class="panel-head"><div><h2>任务书预览</h2><p class="muted small">核对以下正文。需要调整可提出修改；确认无误后，在文末生成文件。</p></div>${btn('提出修改','agent-edit',t.busy?'disabled':'','secondary')}</div>
 ${t.quality_review?.length?`<div class="warning-note"><strong>以下内容仍需核对</strong>${t.quality_review.map(x=>`<p>${E(x.problem)}<br>${E(x.fix)}</p>`).join('')}</div>`:''}
 ${section('01','场景',`${taxonomy}<p class="doc-copy">${E(d.scenario)}</p>${Object.values(scope).some(v=>v===true)?`<div class="warning-note">${E(scope.note)}<br>可供考虑的学生环节：${E(scope.student_slice)}</div>`:''}`,'basics')}
 ${section('02','学生交付物',`<p class="doc-copy">交付一个 Skill 压缩包。${E(d.purpose)}</p>`,'basics')}
 ${section('03','给 AI 什么？',table(['输入','必填','怎么提供'],d.inputs.map(x=>[E(x.name),x.required?'必填':'选填',(x.owner==='student'?'由团队自行准备。':'')+E(x.requirement)+(x.dependency_note?`<div class="warning-note">${E(x.dependency_note)}</div>`:'')])),'inputs')}
 ${d.rules?.length?section('↳','数据处理规则',table(['规则','要求'],d.rules.map(x=>[E(x.name),E(x.detail)])),'rules'):''}
 ${section('04','希望得到什么？',table(['输出组件','具体要求','短示例'],d.outputs.map(x=>[E(x.name),E(x.detail),E(x.example)])),'outputs')}
 ${section('05','目标O（Objective）',`<p class="doc-copy">${E(d.objective)}</p>`,'basics')}
 ${section('06','KR（Key Results）评分表','<p class="doc-copy">KR 指用来验收任务的关键结果。KR1为交付内容，KR2为业务质量，KR3为 Skill 使用表现。三个KR分别计算均分。</p>'+table(['KR','评价对象','计算方法','均分'],[['KR1 交付内容','完整度、准确度、格式规范',`${d.outputs.length}项输出，每项3个分数；${d.outputs.length*3}个分数之和 ÷ ${d.outputs.length*3}`,'____'],['KR2 业务质量','本任务的业务质量维度',`${d.kr2_2.length}个维度得分之和 ÷ ${d.kr2_2.length}`,'____'],['KR3 Skill 使用表现','稳定性、可迁移性、安全性、效率','4个维度得分之和 ÷ 4','____']]))}
 ${section('07','KR具体评分细则',scoringTables(d,t.rubric),'quality')}
 ${section('08','待确认事项',`<p class="muted small">共 ${t.confirmations.length} 项，${unrecorded} 项待确认。可在第 1 步提交确认答案，也可在第 3 步手动填写。</p>${confirmationPreview(t.confirmations)||'<p class="muted">暂无待确认事项。</p>'}${btn('填写待确认事项','agent-confirmations','','secondary')}`)}
 <footer class="review-finish" id="review-finish"><div><h3>确认这份任务书</h3><p class="muted small">${unrecorded?`还有 ${unrecorded} 项企业事项待确认，会原样保留在文件中。`:'企业确认信息已记录。'}这里确认的是当前稿件，不代表企业已同意所有事项。</p><p id="unsaved-hint" class="warning-note" ${hasUnsavedInput(t)?'':'hidden'}>有尚未提交的内容，请到“提交需求”或“待确认事项”提交后再生成文件。</p>${!canConfirmBrief(t)&&!hasUnsavedInput(t)?'<p class="warning-note">请先完成本次生成、回答必要问题或处理正文校验提示，再确认稿件。</p>':''}</div><div class="toolbar">${btn('提出修改','agent-edit',t.busy?'disabled':'','secondary')}${btn('确认并生成文件','agent-confirm',canConfirmBrief(t)?'':'disabled','primary')}</div></footer></article>`;
}
function renderConfirmations(){
 const t=state.task;
 $('#task-content').innerHTML=`<section class="panel"><h2>待确认事项</h2><p class="muted">填写企业已明确的答案，保存后同步到任务书；未明确的事项可以保留待确认。</p>${t.brief?confirmationFields():`<div class="empty"><h3>生成任务书后，会在这里列出待确认事项。</h3>${btn('去提交需求','tab','data-id="materials"','primary')}</div>`}</section>`;
}
function confirmationFields(){
 const t=state.task;
 return `<div class="confirmation-fields"><div class="panel-head"><h3>企业确认信息</h3>${btn('＋ 添加确认事项','confirmation-new',t.busy||!t.brief?'disabled':'','secondary')}</div>
 ${t.confirmations.length?t.confirmations.map(c=>`<article class="confirm-card"><div class="confirm-heading"><h3>${E(c.topic)} <span class="pill ${c.recorded?'green':'amber'}">${c.recorded?'已记录答案':'待确认'}</span></h3>${btn('删除','confirmation-delete',`data-id="${E(c.id)}" ${t.busy?'disabled':''}`,'ghost danger')}</div><p>${E(c.question)}</p>
 ${c.id==='C-FORMAT'?`<label for="answer-selection">企业选定的输出格式</label><select id="answer-selection" ${t.busy?'disabled':''}><option value="">尚未选定</option>${t.brief.output_options.map(o=>`<option value="${E(o.id)}" ${t.brief.selected_output===o.id?'selected':''}>${E(o.label)}</option>`).join('')}</select>`:''}
 ${c.id==='C-RUBRIC'?`<label class="checkbox"><input id="answer-approved" type="checkbox" ${t.brief.rubric_approved?'checked':''} ${t.busy?'disabled':''}>企业已明确同意当前评分规则</label>`:''}
 <p class="confirmation-sync-hint">${['C-FORMAT','C-RUBRIC'].includes(c.id)?'保存后直接同步到任务书，无需调用模型。':'提交答案后会检查并更新相关正文；未明确的内容可暂时留空。'}</p><label class="sr-only" for="answer-${E(c.id)}">${E(c.topic)}的答案</label><textarea id="answer-${E(c.id)}" placeholder="填写企业已明确的答案" ${t.busy?'disabled':''}>${E(t.answers[c.id]?.text||'')}</textarea><footer><span></span>${btn(['C-FORMAT','C-RUBRIC'].includes(c.id)?'保存确认信息':'提交答案并更新任务书','answer',`data-id="${E(c.id)}" ${t.busy?'disabled':''}`)}</footer></article>`).join(''):`<div class="empty"><h3>${t.brief?'暂无待企业确认事项，可按需添加。':'生成任务书后，可在这里管理确认事项。'}</h3></div>`}</div>`;
}
function bindConfirmationDrafts(){
 for(const c of state.task.confirmations){
  const key=state.task.id+':'+c.id,el=document.getElementById('answer-'+c.id);if(!el)continue;
  const sel=c.id==='C-FORMAT'?$('#answer-selection'):null,check=c.id==='C-RUBRIC'?$('#answer-approved'):null,saved=confirmationDrafts.get(key);
  if(saved){el.value=saved.text;if(sel)sel.value=saved.selection;if(check)check.checked=saved.approved;}
  const baseline={text:state.task.answers[c.id]?.text||'',selection:sel?state.task.brief.selected_output||'':undefined,approved:check?!!state.task.brief.rubric_approved:undefined};
  const save=()=>{const value={text:el.value,selection:sel?.value,approved:check?.checked};if(JSON.stringify(value)===JSON.stringify(baseline))confirmationDrafts.delete(key);else confirmationDrafts.set(key,value);refreshReviewAction();};
  el.addEventListener('input',save);sel?.addEventListener('change',save);check?.addEventListener('change',save);
 }
}
function renderVersions(){
 const t=state.task,files=currentFiles(t),currentIds=new Set(files.map(f=>f.exportId)),old=t.exports.filter(e=>!currentIds.has(e.id));
 $('#task-content').innerHTML=`<section class="panel"><div class="panel-head"><h2>下载文件</h2>${btn('查看任务书','tab','data-id="brief"','secondary')}</div>${files.length?`<p class="muted">当前稿件的文件已生成。下载后请打开检查排版。</p><div class="download-grid">${files.map(f=>`<article class="download-card"><span class="export-format">${f.kind==='docx'?'WORD':'EXCEL'}</span><h3>${f.kind==='docx'?'企业任务书':'输入样例表'}</h3><p>${f.kind==='docx'?'已确认稿件的完整内容。':'供企业准备与填写输入样例。'}</p><a class="download-link" href="/api/tasks/${t.id}/files/${f.exportId}-${f.kind}">下载 ${f.kind==='docx'?'Word':'Excel'} ↓</a></article>`).join('')}</div>`:`<div class="empty"><h3>${t.brief?'当前稿件尚未生成文件':'还没有可下载的文件'}</h3><p>${t.brief?'请先审阅任务书，在正文末尾确认并生成文件。':'提交需求并生成任务书后，审阅确认即可下载。'}</p>${btn(t.brief?'去审阅任务书':'去提交需求','tab',`data-id="${t.brief?'brief':'materials'}"`,'primary')}</div>`}</section>
 <section class="panel history-panel"><h2>历史版本记录</h2><p class="small muted">共 ${t.versions.length} 个版本。恢复后会创建新稿，原记录仍保留。</p><div class="history-scroll" tabindex="0" role="region" aria-label="历史版本记录列表">${t.versions.length?t.versions.map(v=>`<div class="version-item"><div><strong>V${v.number} · ${E(v.label)}</strong><small>${date(v.created_at)}</small></div><div class="version-actions">${btn('查看 Word','version-open',`data-id="${v.id}" ${t.busy?'disabled':''}`,'secondary')}${btn('恢复此版本','restore',`data-id="${v.id}" ${t.busy?'disabled':''}`)}</div></div>`).join(''):'<p class="muted">暂无历史版本。</p>'}</div></section>
 <section class="panel history-panel"><h2>历史交付文件</h2><p class="small muted">以下文件来自历史稿件，当前稿件的文件在上方下载。</p><div class="history-scroll" tabindex="0" role="region" aria-label="历史交付文件列表">${old.length?old.slice().reverse().map(e=>`<article class="export-card"><strong>${e.version_number?'V'+e.version_number:'历史稿件'}</strong><p class="small muted">${date(e.created_at)}</p>${e.files.map(f=>`<a href="/api/tasks/${t.id}/files/${e.id}-${f.kind}">↓ ${f.kind==='docx'?'企业任务书 Word':'输入样例表 Excel'}</a>`).join('')}</article>`).join(''):'<p class="muted">暂无历史交付文件。</p>'}</div></section>`;
}
function field(label,key,value,type='textarea'){return `<label>${E(label)}</label>${type==='input'?`<input data-key="${key}" value="${E(value)}">`:`<textarea data-key="${key}">${E(value)}</textarea>`}`}
function editor(type){
 if(state.task.busy)return toast('任务正在运行，请稍后编辑',true);
 editState={type,data:structuredClone(state.task.brief)};drawEditor();
}
function drawEditor(){const {type,data:d}=editState;let body='',title='编辑任务书';
 if(type==='basics'){title='编辑场景、交付物与目标';body=`<div class="form-grid">${[['大行业','industry_l1'],['细分行业','industry_l2'],['大岗位','role_l1'],['细分岗位','role_l2']].map(([l,k])=>`<div>${field(l,'taxonomy.'+k,d.taxonomy[k],'input')}</div>`).join('')}</div>${field('场景','scenario',d.scenario)}${field('Skill 用途','purpose',d.purpose)}${field('目标 O','objective',d.objective)}`;}
 if(['inputs','outputs','rules','quality'].includes(type)){const k=type==='quality'?'kr2_2':type;title={inputs:'编辑企业输入',outputs:'编辑输出组件',rules:'编辑处理规则',quality:'编辑业务质量评分'}[type];const fields={inputs:[['输入名称','name'],['填写要求','requirement'],['填写示例','example'],['来源编号','source'],['企业依赖提示','dependency_note']],outputs:[['输出名称','name'],['具体要求','detail'],['短示例','example'],['来源编号','source']],rules:[['规则名称','name'],['完整规则或公式','detail'],['来源编号','source']],quality:[['评价维度','name'],['评分时看什么','company_check'],['1分表现','anchor_1'],['3分表现','anchor_3'],['5分表现','anchor_5'],['对应输入或输出编号（逗号分隔）','refs']]};body=`<p class="small muted">只修改需要调整的部分。删除输出时，请同步检查对应的业务质量评分引用。</p>${(d[k]||[]).map((x,i)=>`<div class="form-row" data-row="${i}"><h3>${E(x.id)}${btn('删除','editor-remove',`data-id="${i}"`,'ghost danger')}</h3>${fields[type].map(([l,f])=>field(l,k+'.'+i+'.'+f,Array.isArray(x[f])?x[f].join(', '):x[f],['name','source','refs'].includes(f)?'input':'textarea')).join('')}${type==='inputs'?`<label class="checkbox"><input type="checkbox" data-key="${k}.${i}.required" ${x.required?'checked':''}>必填输入</label>`:''}</div>`).join('')}${btn('＋ 增加一项','editor-add','','secondary')}`;}
 if(dialog.open)dialog.close();modal(title,body,btn('取消','close')+btn('保存修改','editor-save','','primary'),true);
}
function harvest(){document.querySelectorAll('#dialog [data-key]').forEach(el=>{const path=el.dataset.key.split('.');let o=editState.data;for(const k of path.slice(0,-1))o=o[k];const k=path.at(-1);o[k]=el.type==='checkbox'?el.checked:k==='refs'?el.value.split(/[,，]/).map(s=>s.trim()).filter(Boolean):el.value;});if(editState.type==='inputs')editState.data.inputs.forEach(x=>{if(x.owner!=='student')x.owner=x.required?'customer':'customer_optional'})}
async function taskAction(op,body={}){state.task=await api('/tasks/'+state.task.id+'/'+op,{revision:state.task.revision,...body});renderTask();return state.task}
async function action(name,id,el){
 if(name.startsWith('agent-'))return agentAction(name);
 if(name==='trash')return showTrash();
 if(name==='delete-task'){const t=state.tasks.find(t=>t.id===id)||(state.task?.id===id?state.task:null);if(!t)return;return modal('删除任务',`<p>将“${E(t.title)}”从任务列表移除？</p><p class="muted small">材料和历史版本会保留，可在“已删除任务”中恢复。</p>`,btn('取消','close')+btn('删除任务','delete-confirm',`data-id="${id}" data-revision="${t.revision}"`,'danger'));}
 if(name==='delete-confirm'){await api('/tasks/'+id+'/delete',{revision:Number(el.dataset.revision)});dialog.close();clearTimeout(poll);if(location.hash==='#tasks')await route();else location.hash='tasks';toast('任务已删除，可在已删除任务中恢复');return;}
 if(name==='undelete'){const t=await api('/tasks/'+id+'/undelete',{});dialog.close();state.tab='agent';location.hash='task/'+t.id;await route();toast(t.reused_existing?'已打开已有任务，未重复恢复':'任务已恢复');return;}
 if(name==='reload-page'){location.reload();return;}
 if(name==='close')return dialog.close();
 if(name==='new'){return modal('新建企业需求',`<label for="new-title">任务名称</label><input id="new-title" placeholder="例如：客户咨询内容整理" maxlength="120"><label for="new-company">企业名称 <small>选填</small></label><input id="new-company" placeholder="便于后续查找" maxlength="80">`,btn('取消','close')+btn('创建任务','create','','primary'));}
 if(name==='create'){const t=await api('/tasks',{title:$('#new-title').value,company:$('#new-company').value});dialog.close();state.tab='agent';location.hash='task/'+t.id;if(t.reused_existing)toast('同名企业任务已存在，已打开原任务');return;}
 if(['tasks','cases','settings'].includes(name)){location.hash=name;return;}
 if(name==='open'){state.tab='agent';location.hash='task/'+id;return;}
 if(name==='tab'){state.tab=id;renderTask();window.scrollTo(0,0);return;}
 if(name==='source'){const source=state.task.sources.find(s=>s.id===id);if(source)raw(source.text);return;}
 if(name==='note'){await taskAction('note',{text:$('#note-text').value,user_instruction:true});toast('补充说明已保存');return;}
 if(name==='run'){return agentAction('agent-run');} if(name==='legacy-run-disabled'){const text=$('#note-text')?.value||'',updating=!!state.task.brief;try{await taskAction('run',{update_text:text});toast((text.trim()?'已保存补充信息，':'')+(updating?'正在更新任务书':'正在拆解需求'));}catch(e){state.task=await api('/tasks/'+state.task.id);renderTask();if($('#note-text')&&!state.task.notes.some(n=>n.text===text.trim()))$('#note-text').value=text;throw e;}return;}
 if(name==='goto-settings'){dialog.close();location.hash='settings';return;}
 if(name==='refresh-status'){await refreshStatus();renderSettings();return;}
 if(name==='answer'){await taskAction('agent-answer',{id,text:document.getElementById('answer-'+id).value,...(id==='C-FORMAT'?{selection:$('#answer-selection').value}:{}),...(id==='C-RUBRIC'?{approved:$('#answer-approved').checked}:{})});toast(state.task.busy?'答案已保存，正在检查并更新相关正文':'确认信息已保存');confirmationDrafts.delete(state.task.id+':'+id);state.tab='confirmations';renderTask();document.getElementById('answer-'+id)?.scrollIntoView({block:'center'});return;}
 if(name==='review-finish'){$('#review-finish')?.scrollIntoView({block:'center'});return;}
 if(name==='review'){await taskAction('review');toast('当前版本已确认，可以导出');return;}
 if(name==='export'){toast('正在生成文件');await taskAction('export',{kind:id});toast('文件已生成，请下载后检查排版');return;}
 if(name==='version-open'){const res=await fetch('/api/tasks/'+state.task.id+'/version-open',{method:'POST',headers:{'Content-Type':'application/json','X-Workspace-Token':token},body:JSON.stringify({version:id})});if(!res.ok)throw Error((await res.json()).error||'下载失败');const url=URL.createObjectURL(await res.blob()),link=document.createElement('a');link.href=url;link.download='历史版本任务书.docx';link.click();setTimeout(()=>URL.revokeObjectURL(url),10000);return;}
 if(name==='confirmation-new'){modal('添加企业确认事项',`<label for="confirm-topic">事项标题</label><input id="confirm-topic" maxlength="80" placeholder="例如：企业提供材料的时间"><label for="confirm-question">需要企业确认什么</label><textarea id="confirm-question" maxlength="4000" placeholder="填写需要企业确认的问题"></textarea>`,btn('取消','close')+btn('添加','confirmation-add','','primary'));return;}
 if(name==='confirmation-add'){await taskAction('confirmation-add',{topic:$('#confirm-topic').value,question:$('#confirm-question').value});dialog.close();toast('已添加确认事项');return;}
 if(name==='confirmation-delete'){await taskAction('confirmation-delete',{id});confirmationDrafts.delete(state.task.id+':'+id);toast('已删除确认事项，历史版本仍保留');return;}
 if(name==='restore'){modal('恢复历史任务书',`<p>恢复后会创建一个新版本，旧版本和原始材料仍保留。恢复内容需要重新审核。</p>`,btn('取消','close')+btn('恢复','restore-confirm',`data-id="${id}"`,'primary'));return;}
 if(name==='restore-confirm'){await taskAction('restore',{version:id});dialog.close();state.tab='brief';renderTask();window.scrollTo(0,0);toast('已恢复为新版本，请重新审阅');return;}
 if(name==='edit')return editor(id);
 if(name==='json'){modal('完整任务数据',`<p class="muted small">用于核对来源、格式选项、评分锚点和内部规则。普通修改可使用各节“编辑”。</p><textarea id="json-editor" style="min-height:50vh;font-family:monospace">${E(JSON.stringify(state.task.brief,null,2))}</textarea>`,btn('关闭','close')+btn('保存完整数据','json-save','','secondary'),true);return;}
 if(name==='json-save'){let d;try{d=JSON.parse($('#json-editor').value)}catch{throw Error('JSON格式有误，请检查括号、引号和逗号。')}await taskAction('brief',{brief:d});dialog.close();toast('修改已保存为新版本');return;}
 if(name==='editor-save'){harvest();await taskAction('brief',{brief:editState.data});dialog.close();toast('修改已保存为新版本');return;}
 if(name==='editor-remove'){harvest();const k=editState.type==='quality'?'kr2_2':editState.type;editState.data[k].splice(Number(id),1);drawEditor();return;}
 if(name==='editor-add'){harvest();const type=editState.type,k=type==='quality'?'kr2_2':type,d=editState.data;d[k]??=[];let n=1,prefix={inputs:'I',outputs:'O',rules:'R',quality:'Q'}[type];const ids=new Set([...d.inputs,...d.outputs,...d.kr2_2,...(d.rules||[])].map(x=>x.id));while(ids.has(prefix+n))n++;let x={id:prefix+n,name:'',source:'proposal'};if(type==='inputs')Object.assign(x,{owner:'customer',required:true,requirement:'',example:''});if(type==='outputs')Object.assign(x,{detail:'',example:''});if(type==='rules')x.detail='';if(type==='quality')Object.assign(x,{basis:'建议标准，待企业确认',basis_type:'proposal',company_check:'',anchor_1:'',anchor_3:'',anchor_5:'',refs:[]});d[k].push(x);drawEditor();return;}
}
document.addEventListener('click',async e=>{const b=e.target.closest('[data-action]');if(!b||b.disabled)return;if(b.tagName==='A')e.preventDefault();const wasDisabled=b.disabled;b.disabled=true;try{await action(b.dataset.action,b.dataset.id,b)}catch(err){toast(err.message,true)}finally{b.disabled=wasDisabled}});
document.querySelectorAll('[data-route]').forEach(b=>b.addEventListener('click',()=>{if(location.hash.slice(1)===b.dataset.route)route();else location.hash=b.dataset.route}));$('#new-task').addEventListener('click',()=>action('new'));window.addEventListener('hashchange',route);route();

async function renderReleases(){
 const releases=await api('/releases');$('#breadcrumb').textContent='产品版本记录';
 main.innerHTML=heading('产品版本记录','从需求材料到任务书，再到支持对话修改与确认的 Agent。','<a class="button secondary" href="/api/releases/notes">下载迭代总览</a>')+releases.slice().reverse().map(r=>`<section class="panel release-card"><div class="panel-head"><h2>${E(r.version)} · ${E(r.title)}</h2>${pill(r.version===state.status.product_version?'当前版本':'历史版本')}</div><p class="small muted release-date"><time datetime="${E(r.completed_on)}">${E(r.completed_on)}</time></p><p>${E(r.summary)}</p><ul>${r.changes.map(c=>`<li>${E(c)}</li>`).join('')}</ul><p class="small muted">验证与边界：${E(r.validation)}</p></section>`).join('');
}
