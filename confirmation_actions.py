"""Apply explicit composer answers through the same fields as the manual form."""
import hashlib
from core import clone, confirmation_rows, now, rubric_changed
from model import ModelError

CONTRACT_VERSION=2

def decisions(task, plan, message):
    """Normalize only answers grounded in this user turn; attachments are not consent."""
    rows={r['id']:r for r in confirmation_rows(task.get('brief') or {})} if task.get('brief') else {}
    def evidence(quote):
        if not isinstance(quote,str) or not quote.strip() or quote not in message:
            raise ModelError('确认答案缺少本轮用户原话，未写入确认。')
    result={}
    bulk=plan.get('confirm_all')
    if bulk:
        if not isinstance(bulk,dict):raise ModelError('批量确认格式错误。')
        evidence(bulk.get('quote'))
        for cid in rows:
            result[cid]={'id':cid,'text':'已确认','quote':bulk['quote'],'bulk':True}
        if 'C-RUBRIC' in result:result['C-RUBRIC']['approved']=True
    answers=plan.get('answers',[])
    if not isinstance(answers,list):raise ModelError('确认答案格式错误。')
    seen=set()
    for item in answers:
        if not isinstance(item,dict) or item.get('id') not in rows or item['id'] in seen:
            raise ModelError('确认事项不存在或重复，未写入确认。')
        evidence(item.get('quote'))
        if item.get('text')!=item['quote'] or len(item['text'])>4000:
            raise ModelError('确认答案必须保留本轮用户原话。')
        item={k:clone(v) for k,v in item.items() if k in ('id','text','quote','selection','new_format','approved')};cid=item['id'];seen.add(cid)
        if cid=='C-FORMAT':
            options=(task.get('brief') or {}).get('output_options',[])
            if 'selection' not in item or not isinstance(item['selection'],str):
                raise ModelError('输出格式的明确选择未识别，请说明需要的格式。')
            if item['selection'] and item['selection'] not in {o['id'] for o in options}:
                raise ModelError('输出格式选项不存在。')
            label=item.get('new_format')
            if label is not None:
                if item['selection'] or not isinstance(label,str) or not label.strip() or label not in item['quote']:
                    raise ModelError('新增输出格式需来自用户明确原话。')
                item['selection']='F-USER-'+hashlib.sha256(label.encode()).hexdigest()[:10]
                item['option']={'id':item['selection'],'label':label,'recommended':False}
        elif cid=='C-RUBRIC':
            if type(item.get('approved')) is not bool:raise ModelError('评分确认需明确同意或撤回。')
        elif any(k in item for k in ('selection','new_format','approved')):
            raise ModelError('确认答案包含无关控制字段。')
        result[cid]=item
    return list(result.values())

def apply_decisions(task, draft, actions):
    """Return staged answers and controls; the caller commits everything atomically."""
    answers=clone(task.get('answers') or {})
    if rubric_changed(task.get('brief'),draft):
        draft['rubric_approved']=False;answers.pop('C-RUBRIC',None)
    for item in actions:
        cid=item['id']
        # A blanket confirmation must not erase a previously supplied factual answer.
        if not item.get('bulk') or not answers.get(cid,{}).get('text','').strip():
            answers[cid]={'text':item['text'],'by':'用户明确回复','at':now(),'quote':item['quote']}
        if cid=='C-FORMAT' and 'selection' in item:
            if item.get('option'):
                options=draft.setdefault('output_options',[])
                if not any(o['id']==item['selection'] for o in options):
                    # Explicit new format replaces an unselected alternative if the list is full.
                    if len(options)>=3:
                        index=next((i for i in range(len(options)-1,-1,-1) if not options[i].get('recommended')),len(options)-1)
                        options.pop(index)
                    options.append(clone(item['option']))
            draft['selected_output']=item['selection']
        if cid=='C-RUBRIC' and 'approved' in item:draft['rubric_approved']=item['approved']
    draft['confirmation_answers']=answers
    return answers
