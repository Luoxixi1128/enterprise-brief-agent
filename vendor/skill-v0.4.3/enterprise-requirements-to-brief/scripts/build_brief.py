"""Build the screenshot-aligned v0.4 enterprise brief without overwriting files."""
import argparse
from pathlib import Path
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from validate_brief import load_checked, confirmations

FONT = '冬青黑体简体中文 W3'
TEAL, LIGHT, YELLOW, BORDER = '075B60', 'EEF7F8', 'FFF3CC', '48AEC5'
HEADINGS = ['01  场景', '02  学生交付物', '03  给 AI 什么？', '04  希望得到什么？', '05  目标O（Objective）', '06  KR（Key Results）评分表', '07  KR具体评分细则', '08  待企业确认汇总表']
KR_INTRO = 'KR 指用来验收任务的关键结果。KR1为交付内容，KR2为业务质量，KR3为 Skill 使用表现。三个KR分别计算均分。'
KR1_DIMENSIONS = [
 ('完整度', '检查约定的内容和功能是否齐全。4分为少量次要缺漏，2分为多项关键缺漏。', '基本未完成', '缺少一项关键内容或功能', '约定内容和功能齐全'),
 ('准确度', '核对信息、数量和功能结果。4分为轻微错误，2分为多处关键错误。', '主要结果错误或无法核对', '有一处影响使用的关键错误', '信息和功能结果符合要求'),
 ('格式规范', '检查约定格式、打开方式和内容呈现。4分为少量格式问题，2分为多处难以查看或操作。', '格式不符且无法正常使用', '能查看但仍需整理', '格式符合约定且能清楚查看和操作'),
]
QUALITY_SCALE = [('5 分','下方各维度的要求都做到，核对后没有发现问题。'),('4 分','主要要求都做到，只有小问题，不影响判断或使用。'),('3 分','有一处影响判断或使用的问题，改好后才能采用。'),('2 分','有多处问题影响判断或使用，需要较多检查和修改。'),('1 分','没有完成本项要求，或没有结果可供评分人核对。')]
USAGE_SCALE = [('5 分','完成约定的审核等人工步骤后，Skill 能稳定完成任务，换一组材料也能使用，无需额外修补。'),('4 分','整体可以使用，只需人工少量调整。'),('3 分','能完成任务，但关键内容或步骤仍需人工修改。'),('2 分','运行容易中断或出错，需要人工反复修补才能继续。'),('1 分','无法完成任务，或出现明显的数据安全、越权操作问题。')]

def set_font(run, size=10.5, bold=False, color='17262B'):
    run.font.name=FONT; run.font.size=Pt(size); run.font.bold=bold
    run.font.color.rgb=RGBColor.from_string(color)
    fonts=run._element.get_or_add_rPr().get_or_add_rFonts()
    for key in ('ascii','hAnsi','eastAsia','cs'): fonts.set(qn('w:'+key),FONT)

def clear_nonheading_markers(doc):
    """Only actual title paragraphs retain pagination/outline formatting markers."""
    for paragraph in doc.element.body.xpath('.//w:p'):
        pr=paragraph.get_or_add_pPr()
        styles=pr.findall(qn('w:pStyle'))
        style=styles[0].get(qn('w:val')) if styles else 'Normal'
        if style in ('Title', 'Heading1', 'Heading2', 'Heading3'):
            continue
        for tag in ('keepNext','keepLines','pageBreakBefore','outlineLvl','numPr'):
            for old in pr.findall(qn('w:'+tag)):pr.remove(old)
        for tag in ('keepNext','keepLines','pageBreakBefore'):
            el=OxmlElement('w:'+tag);el.set(qn('w:val'),'0');pr.append(el)
        el=OxmlElement('w:outlineLvl');el.set(qn('w:val'),'9');pr.append(el)
        num=OxmlElement('w:numPr');el=OxmlElement('w:numId');el.set(qn('w:val'),'0');num.append(el);pr.append(num)

class Writer:
    def __init__(self,title):
        self.doc=Document(); s=self.doc.sections[0]
        s.page_width,s.page_height=Cm(21.59),Cm(27.94)
        s.top_margin,s.bottom_margin=Cm(1.45),Cm(1.35)
        s.left_margin=s.right_margin=Cm(1.55)
        s.header_distance,s.footer_distance=Cm(.56),Cm(.61)
        for name in ('Normal','Title','Heading 1','Heading 2','Heading 3'):
            st=self.doc.styles[name]; st.font.name=FONT; st.font.size=Pt(10.5)
            st.paragraph_format.space_before=Pt(0); st.paragraph_format.space_after=Pt(0)
            st.paragraph_format.line_spacing=1.12
            st.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'),FONT)
        for el in self.doc.styles.element.xpath('.//w:pBdr'):
            el.getparent().remove(el)
        h=s.header.paragraphs[0]; h.alignment=WD_ALIGN_PARAGRAPH.RIGHT
        set_font(h.add_run('FDE X 企业任务书 ｜'+title),8,False,'A7B3B7')
        f=s.footer.paragraphs[0]; f.alignment=WD_ALIGN_PARAGRAPH.CENTER
        r=f.add_run(); set_font(r,8,False,'808080')
        fld=OxmlElement('w:fldSimple'); fld.set(qn('w:instr'),'PAGE'); r._r.addnext(fld)
    def gap(self):
        body=self.doc.element.body
        prev=body[-2] if len(body)>1 else None
        if prev is not None and prev.tag==qn('w:p') and not prev.xpath('.//w:t'): return
        # Spacer is body text: no heading/list or pagination marker in Word.
        p=self.doc.add_paragraph(style='Normal')
        p.paragraph_format.line_spacing=1
        p.paragraph_format.keep_with_next=False
        p.paragraph_format.keep_together=False
        p.paragraph_format.page_break_before=False
        pr=p._p.get_or_add_pPr()
        outline=OxmlElement('w:outlineLvl'); outline.set(qn('w:val'),'9'); pr.append(outline)
        num=OxmlElement('w:numPr'); num_id=OxmlElement('w:numId')
        num_id.set(qn('w:val'),'0'); num.append(num_id); pr.append(num)
        set_font(p.add_run(''),10.5)
    def para(self,text='',size=10.5,bold=False,color='17262B',style=None):
        p=self.doc.add_paragraph(style=style); set_font(p.add_run(text),size,bold,color)
        p.paragraph_format.keep_with_next=True
        return p
    def heading(self,text,level=1):
        if level==1:self.gap()
        p=self.para(text,15 if level==1 else 12.5,True,TEAL,'Heading '+str(level))
        p.paragraph_format.keep_with_next=True
        return p
    def table(self,heads,rows,ratios=None,pending=False,centers=()):
        prev=self.doc.element.body[-2]
        if prev.tag==qn('w:tbl'):self.gap()
        values=([heads] if heads else [])+rows
        ratios=ratios or [1]*len(values[0]); widths=[18.49*x/sum(ratios) for x in ratios]
        t=self.doc.add_table(rows=0,cols=len(widths)); t.autofit=False; t.alignment=WD_TABLE_ALIGNMENT.CENTER
        for col,width in zip(t.columns,widths):col.width=Cm(width)
        for ri,vals in enumerate(values):
            row=t.add_row(); trPr=row._tr.get_or_add_trPr(); trPr.append(OxmlElement('w:cantSplit'))
            is_head=bool(heads) and ri==0
            if is_head:trPr.append(OxmlElement('w:tblHeader'))
            for ci,(cell,value) in enumerate(zip(row.cells,vals)):
                cell.width=Cm(widths[ci]); cell.vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
                p=cell.paragraphs[0]; p.paragraph_format.line_spacing=1.12
                if heads and (heads[0]=='KR' or heads==['分数','统一评分标准']):
                    p.paragraph_format.keep_with_next=ri<len(values)-1
                p.alignment=WD_ALIGN_PARAGRAPH.CENTER if is_head or ci in centers else WD_ALIGN_PARAGRAPH.LEFT
                # Rich segments support red bracketed dependency notes without recoloring the field.
                segs=value if isinstance(value,list) else [(str(value),None)]
                for txt,color in segs:set_font(p.add_run(txt),9.2,is_head,color or ('000000' if pending else 'FFFFFF' if is_head else '17262B'))
                pr=cell._tc.get_or_add_tcPr(); shd=OxmlElement('w:shd')
                shd.set(qn('w:fill'),YELLOW if pending else TEAL if is_head else LIGHT if (ri-(1 if heads else 0))%2==0 else 'FFFFFF');pr.append(shd)
                borders=OxmlElement('w:tcBorders')
                for edge in ('top','left','bottom','right'):
                    e=OxmlElement('w:'+edge);e.set(qn('w:val'),'single');e.set(qn('w:sz'),'6');e.set(qn('w:color'),BORDER);borders.append(e)
                pr.append(borders);mar=OxmlElement('w:tcMar')
                for edge in ('top','bottom','left','right'):
                    e=OxmlElement('w:'+edge);e.set(qn('w:w'),'90' if edge in ('top','bottom') else '100');e.set(qn('w:type'),'dxa');mar.append(e)
                pr.append(mar)
        return t
    def pending(self,topic,text):
        t=self.table(None,[['待企业确认 '+topic,text]],[3,7],pending=True)
        for r in t.cell(0,0).paragraphs[0].runs:set_font(r,10.5,True,TEAL)
        return t

def build(d,output):
    out=Path(output)
    if out.exists():raise FileExistsError(f'输出已存在，请换版本名：{out}')
    w=Writer(d['title']);p=w.para(d['title'],25,True,'000000','Title');p.alignment=WD_ALIGN_PARAGRAPH.CENTER
    pending=confirmations(d)
    def local(section):
        if section=='07':
            grouped=[c for c in pending if c['id'] in ('C-RUBRIC','C-ISSUE')]
            if grouped:w.pending('评分细则','\n'.join(f"{i+1}. {c['question']} {c.get('answer','________________')}" for i,c in enumerate(grouped)))
        for c in pending:
            if c['section']==section and not (section=='07' and c['id'] in ('C-RUBRIC','C-ISSUE')):
                w.pending(c['topic'],c['question']+'\n'+c.get('answer','________________'))
    w.heading(HEADINGS[0]);tax=d['taxonomy']
    w.table(['大行业','细分行业','大岗位','细分岗位'],[[tax[k] for k in ('industry_l1','industry_l2','role_l1','role_l2')]],[1,1.4,1,1.4])
    p=w.para(d['scenario']);scope=d.get('scope_assessment',{})
    if any(scope.get(k) for k in ('complex','long_chain','long_cycle','agent_like','enterprise_dependency','original_enterprise_dependency')):
        set_font(p.add_run('（'+scope['note']+'；可供人工考虑的学生环节：'+scope['student_slice']+'；是否收敛由企业决定，本文仍按原任务范围编写）' if not d['task_fit'].get('scope_change_applied') else '（'+scope['note']+'；已按明确授权调整范围：'+scope['student_slice']+'）'),10.5,False,'C00000')
    local('01')
    w.heading(HEADINGS[1]);w.para('交付一个 Skill 压缩包。'+d['purpose']);local('02')
    w.heading(HEADINGS[2]);rows=[]
    for x in d['inputs']:
        req=x['requirement'];fallback=x.get('student_fallback','')
        if fallback:req=req.rstrip('。；;')+'；企业未提供时，由学生'+fallback
        segs=[(req,None)]
        if x.get('dependency_note'):segs.append(('（'+x['dependency_note']+'）','C00000'))
        rows.append([x['name'],'必填' if x['required'] else '选填',segs])
    w.table(['输入','必填','怎么提供'],rows,[2,1,7],centers=(1,));local('03')
    w.heading(HEADINGS[3]);w.table(['编号','输出组件','具体要求','短示例'],[[str(i+1),x['name'],x['detail'],x['example']] for i,x in enumerate(d['outputs'])],[.7,1.8,4.6,2.9],centers=(0,));local('04')
    w.heading(HEADINGS[4]);w.table(['目标'],[[d['objective']]]);local('05')
    n=len(d['outputs']);m=len(d['kr2_2']);k=len(d['kr2_3'])
    w.heading(HEADINGS[5]);w.para(KR_INTRO)
    w.table(['KR','评价对象','计算方法','均分'],[
        ['KR1 交付内容','完整度、准确度、格式规范',f'{n}项输出，每项3个分数；{n*3}个分数之和÷{n*3}','____'],
        ['KR2 业务质量','根据本任务设计的业务质量维度',f'{m}个维度得分之和÷{m}','____'],
        ['KR3 Skill 使用表现','稳定性、可迁移性、安全性、效率',f'{k}个维度得分之和÷{k}','____']],[1.7,3.5,3.8,1],centers=(3,));local('06')
    w.heading(HEADINGS[6]);w.heading('KR1｜交付内容｜1—5分评分',2)
    w.para(f'按第04部分的{n}项输出逐项评分，每项分别评完整度、准确度和格式规范；KR1均分＝{n*3}个分数之和÷{n*3}。')
    w.table(['维度','评分','1 至 5 分怎么评','1分','3分','5分'],[[name,'1 至 5 分',check,a1,a3,a5] for name,check,a1,a3,a5 in KR1_DIMENSIONS],[1, .8,3.3,1.5,1.7,1.7],centers=(1,))
    w.gap();w.heading(f'KR1 检查项（共{n}项）',3)
    w.table(['检查项','完整度 1 至 5 分','准确度 1 至 5 分','格式规范 1 至 5 分'],[[f'{i+1}. '+x['name'],'____','____','____'] for i,x in enumerate(d['outputs'])],[3.5,2.1,2.1,2.3],centers=(1,2,3))
    w.gap();w.heading('KR2｜业务质量｜1—5分评分',2)
    w.para(f'按下列{m}个维度分别打1—5分，KR2均分＝{m}个维度得分之和÷{m}。')
    w.table(['分数','统一评分标准'],QUALITY_SCALE,[1.3,8.7],centers=(0,))
    w.table(['评价维度','评分','评分时看什么','1分','3分','5分'],[[x['name'],'1 至 5 分',x['company_check'],x['anchor_1'],x['anchor_3'],x['anchor_5']] for x in d['kr2_2']],[1.6,.8,3.1,1.5,1.5,1.5],centers=(1,))
    w.gap();w.heading('KR3｜Skill 使用表现｜1—5分评分',2)
    w.para(f'每个维度直接打1—5分，KR3均分＝{k}个维度得分之和÷{k}。')
    w.table(['分数','统一评分标准'],USAGE_SCALE,[1.3,8.7],centers=(0,))
    rows=[]
    for name,x in d['kr2_3'].items():
        if isinstance(x,str):x={'check':x,'anchor_1':'无法完成本维度要求','anchor_3':'关键处需人工修改','anchor_5':'达到本维度约定要求'}
        rows.append([name,'1 至 5 分',x['check'],x['anchor_1'],x['anchor_3'],x['anchor_5']])
    w.table(['评价维度','评分','评分时看什么','1分','3分','5分'],rows,[1.2,.8,3.6,1.4,1.5,1.5],centers=(1,));local('07')
    w.heading(HEADINGS[7]);w.para('请企业在把任务交给学生前，逐项确认下表。')
    w.table(['确认事项','需要企业确认什么','企业填写'],[[f'{i+1}. '+c['topic'],c['question'],c.get('answer','________________')] for i,c in enumerate(pending)],[1.6,5,3.4],pending=True)
    w.gap();w.para('企业确认人 ____________    岗位 ____________    日期 ____________')
    clear_nonheading_markers(w.doc)
    out.parent.mkdir(parents=True,exist_ok=True);w.doc.save(out);return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('data');p.add_argument('output');a=p.parse_args()
    print(build(load_checked(a.data),a.output))
