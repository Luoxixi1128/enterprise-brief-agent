const agentDrafts=new Map(),confirmationDrafts=new Map();
function agentReadable(value){
 if(value==null)return '尚未填写';
 if(typeof value!=='object')return String(value);
 if(Array.isArray(value))return value.map(agentReadable).join('\n\n');
 const labels={industry_l1:'大行业',industry_l2:'细分行业',role_l1:'大岗位',role_l2:'细分岗位',name:'名称',detail:'要求',requirement:'提供内容',required:'是否必填',example:'示例',company_check:'评分时看什么',anchor_1:'1分',anchor_3:'3分',anchor_5:'5分',check:'检查方法',topic:'确认事项',question:'待确认内容',count:'样例组数',minimum_count:'最少组数',real:'已有真实样例',label:'格式',location_prompt:'保存位置'};
 return Object.entries(value).filter(([k])=>labels[k]||['稳定性','可迁移性','安全性','效率'].includes(k)).map(([k,v])=>(labels[k]||k)+'：'+(typeof v==='boolean'?(v?'是':'否'):agentReadable(v))).join('\n');
}
function currentFiles(t){const files=new Map();for(const e of t.exports.filter(x=>x.revision===t.revision))for(const f of e.files)files.set(f.kind,{...f,exportId:e.id});return [...files.values()];}
function hasUnsavedInput(t){return !!agentDrafts.get(t.id)?.trim()||[...confirmationDrafts.keys()].some(k=>k.startsWith(t.id+':'));}
function canConfirmBrief(t){return !!t.brief&&!t.busy&&!uploadingTasks.has(t.id)&&!t.pending_update&&!t.questions?.length&&!t.validation?.length&&!hasUnsavedInput(t)&&(t.agent?.stale||!['paused','blocked','waiting'].includes(t.agent?.status));}
function preferredTaskTab(){return 'materials';}
function sourceList(t){return t.sources.map(s=>`<div class="file-item"><span class="file-icon">${E(s.name.split('.').pop().toUpperCase())}</span><div class="file-info"><strong>${E(s.name)}</strong><small>${s.role==='reference'?'参考材料':'需求材料'}</small></div><div class="file-actions">${btn('查看','source',`data-id="${s.id}"`,'ghost')}<a href="/api/tasks/${t.id}/files/${s.id}">下载</a></div></div>`).join('');}
function agentComposer(t){
 const a=t.agent||{},q=t.questions||[],locked=t.busy||uploadingTasks.has(t.id),disabled=locked?'disabled':'',paused=['paused','blocked'].includes(a.status),text=agentDrafts.get(t.id)||'';
 return `<section class="panel request-panel" id="request-panel"><h2>提交需求</h2><p class="muted">${t.brief?'补充材料、修改要求或确认答案，提交后同步任务书与待确认事项。':'上传原始材料，或直接说明需求，提交后生成任务书。'}</p>
 <label class="upload-zone requirement-dropzone ${locked?'is-disabled':''}" id="requirement-dropzone" for="agent-file" role="button" tabindex="${locked?'-1':'0'}" aria-disabled="${locked}" aria-label="上传需求材料，支持拖入文件"><span class="upload-symbol" aria-hidden="true">↥</span><strong>点击上传，或将文件拖入这里</strong><p>Word / PDF / Excel / MD / TXT / CSV · 每份不超过 4MB</p><small>${locked?'当前操作完成后可继续上传':'可分次添加材料，已上传的文件会保留在下方'}</small></label><input id="agent-file" type="file" multiple accept=".docx,.pdf,.xlsx,.md,.txt,.csv" hidden ${disabled}>
 ${t.sources.length?`<div class="submitted-files"><h3>已上传材料 · ${t.sources.length} 份</h3>${sourceList(t)}</div>`:''}
 ${q.length?`<div class="confirm-card"><h3>需要补充的信息</h3>${q.map((x,i)=>`<p><strong>${i+1}. ${E(x.question)}</strong><br><span class="muted">${E(x.reason||'')}</span></p>`).join('')}</div>`:''}
 <label for="agent-text">${q.length?'回答与补充信息':'需求说明、补充信息或修改意见'}</label><textarea id="agent-text" ${disabled} placeholder="${t.brief?'例如：输入要求太多，请只保留必需项，其余内容保持不变。':'说明使用者、要完成的工作，或补充文件里没有写清的信息。'}">${E(text)}</textarea>
 <div class="toolbar">${btn(locked?(t.busy?(t.brief?'正在更新…':'正在生成…'):'正在上传…'):q.length?'提交回答':paused&&!text.trim()?'继续生成':t.brief?'提交并更新任务书':'生成任务书','agent-run',disabled,'primary')}</div>
 ${t.notes.length?`<details class="source-notes"><summary>需求说明与补充记录（${t.notes.length}）</summary>${t.notes.slice().reverse().map(n=>`<div class="note"><small>${date(n.at)}</small><p>${E(n.text)}</p></div>`).join('')}</details>`:''}</section>`;
}
function bindAgentComposer(){
 $('#agent-text')?.addEventListener('input',e=>{agentDrafts.set(state.task.id,e.target.value);const b=$('[data-action="agent-run"]');if(b)b.textContent=state.task.questions?.length?'提交回答':!e.target.value.trim()&&['paused','blocked'].includes(state.task.agent?.status)?'继续生成':state.task.brief?'提交并更新任务书':'生成任务书';refreshReviewAction();});
 $('#agent-file')?.addEventListener('change',e=>uploadFiles(e.target.files));
 const zone=$('#requirement-dropzone');if(!zone)return;
 zone.addEventListener('keydown',e=>{if(['Enter',' '].includes(e.key)){e.preventDefault();if(!state.task.busy&&!uploadingTasks.has(state.task.id))$('#agent-file').click();}});
 zone.addEventListener('dragover',e=>{e.preventDefault();if(!state.task.busy&&!uploadingTasks.has(state.task.id)){e.dataTransfer.dropEffect='copy';zone.classList.add('drag-over');}});
 zone.addEventListener('dragleave',()=>zone.classList.remove('drag-over'));
 zone.addEventListener('drop',e=>{e.preventDefault();zone.classList.remove('drag-over');if(!state.task.busy&&!uploadingTasks.has(state.task.id))uploadFiles(e.dataTransfer.files);});
}
function refreshReviewAction(){const b=$('[data-action="agent-confirm"]');if(b)b.disabled=!canConfirmBrief(state.task);const hint=$('#unsaved-hint');if(hint)hint.hidden=!hasUnsavedInput(state.task);}
function agentProgress(t){
 const a=t.agent||{},q=t.questions||[],paused=['paused','blocked'].includes(a.status);
 const message=t.busy?(a.message||'正在整理任务书，请稍候。'):q.length?'有必要信息待补充，请回答后继续。':paused?(t.error||a.message||'进度已保存，可稍后继续。'):t.pending_update?'有新材料或修改尚未写入任务书，请提交后再确认。':t.error||'';
 if(!message)return '';
 const recovery=/402|401|余额|额度|密钥|尚未配置|调用次数/.test(message)?'网站服务暂时不可用或达到用量上限，请稍后继续。':'可补充修改说明后重新提交，或点击继续生成。';
 return `<section class="flow-status ${paused||t.error?'flow-blocked':''}" role="status"><div><strong>${t.busy?(t.brief?'正在更新任务书':'正在生成任务书'):paused||t.error?'已暂停':'待补充'}</strong><p>${E(message)}</p>${paused?`<p class="small muted">材料与已完成的步骤已保存。${recovery}</p>`:''}</div>${t.busy?btn(a.pause_requested?'正在暂停…':'暂停','agent-pause',a.pause_requested?'disabled':'','secondary'):''}</section>`;
}
function agentChanges(t){
 const a=t.agent||{},shown=['taxonomy','scenario','purpose','inputs','rules','outputs','objective','kr2_2','kr2_3','sample','output_options','confirmations'];
 const changes=!a.stale&&a.original?.brief?(a.changes||[]).filter(c=>shown.includes(c.field)):[];
 return changes.length?`<details class="panel change-summary"><summary>本次修改：${E(changes.map(c=>c.label).join('、'))}</summary>${changes.map(c=>`<details class="agent-diff"><summary>${E(c.label)}</summary><div class="agent-diff-grid"><div><h4>修改前</h4><pre>${E(agentReadable(c.before))}</pre></div><div><h4>修改后</h4><pre>${E(agentReadable(c.after))}</pre></div></div></details>`).join('')}</details>`:'';
}
function processHistory(t){
 const calls=t.agent?.calls||[],known=calls.reduce((s,c)=>s+(Number(c.usage?.total_tokens)||0),0);
 return `<aside class="process-history" aria-label="处理记录"><h2>处理记录</h2>${calls.length?`<p class="small muted">${calls.length} 次模型请求 · 已返回 ${known.toLocaleString()} tokens${calls.some(c=>c.usage?.total_tokens==null)?' · 部分用量未返回':''}</p>`:''}<div class="process-scroll" tabindex="0" role="region" aria-label="处理记录列表"><div class="timeline">${t.events.length?t.events.slice().reverse().map(e=>`<div><p>${E(e.text.replace('Agent 开始连续处理','开始整理任务书'))}</p><small>${date(e.at)}</small></div>`).join(''):'<p class="muted">提交需求后，处理进度会显示在这里。</p>'}</div></div></aside>`;
}
async function agentAction(name){
 if(name==='agent-edit'){state.tab='materials';renderTask();$('#agent-text')?.focus();$('#request-panel')?.scrollIntoView({block:'start'});return;}
 if(name==='agent-confirmations'){state.tab='confirmations';renderTask();window.scrollTo(0,0);return;}
 if(name==='agent-run'){
  const text=$('#agent-text')?.value||'',tid=state.task.id;
  try{await taskAction('agent-run',{text,resume:!text.trim(),reply_to:state.task.questions?.length?state.task.agent?.id:undefined});agentDrafts.delete(tid);renderTask();toast(state.task.busy?(state.task.brief?'正在更新任务书':'正在生成任务书'):'需求已保存，请查看页面提示');}
  catch(e){state.task=await api('/tasks/'+tid);renderTask();throw e;}return;
 }
 if(name==='agent-pause'){await taskAction('agent-pause');toast('当前请求结束后暂停，进度会保留');return;}
 if(name==='agent-confirm'){toast('正在生成文件');await taskAction('agent-confirm');state.tab='versions';renderTask();window.scrollTo(0,0);toast('文件已生成，可以下载');return;}
}
