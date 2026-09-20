"""Build the unified input form using the package's existing openpyxl dependency."""
import argparse
from pathlib import Path
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.utils import get_column_letter
from validate_brief import load_checked
FONT='冬青黑体简体中文 W3'

def literal(value):
    text=str(value)
    return "'"+text if text.startswith(('=','+','-','@')) else text

def build(d,output):
    out=Path(output)
    if out.exists():raise FileExistsError(f'输出已存在，请换版本名：{out}')
    count=d.get('sample',{}).get('count',3)
    wb=Workbook();ws=wb.active;ws.title='企业输入样例'
    headers=['输入','必填','怎么提供']+[f'输入样例{i+1}' for i in range(count)]+['填写示例']
    widths=[22,9,50]+[24]*count+[40];end=get_column_letter(len(headers))
    ws.append([literal(d['title']+'｜企业输入样例表')]);ws.merge_cells(f'A1:{end}1')
    ws.append(['请填写黄色列，提供1至3组输入样例。选填项可留空，由学生按说明准备；不填写密码、Cookie、验证码或密钥。']);ws.merge_cells(f'A2:{end}2')
    ws.append([literal(d.get('sample',{}).get('note','右侧示例仅说明填法。'))]);ws.merge_cells(f'A3:{end}3')
    ws.append(headers)
    for x in d['inputs']:
        how=x['requirement']
        if x.get('student_fallback'):how=how.rstrip('。；;')+'；企业未提供时，由学生'+x['student_fallback']
        if x.get('dependency_note'):how+='（'+x['dependency_note']+'）'
        ws.append([literal(x['name']),'必填' if x['required'] else '选填',literal(how)]+['']*count+[literal(x['example'])])
    for row in ws:
        for c in row:
            c.font=Font(name=FONT,size=10,color='17262B');c.alignment=Alignment(wrap_text=True,vertical='center')
    for i,width in enumerate(widths,1):ws.column_dimensions[get_column_letter(i)].width=width
    ws.row_dimensions[1].height=30;ws.row_dimensions[2].height=38;ws.row_dimensions[3].height=26;ws.row_dimensions[4].height=30
    ws['A1'].font=Font(name=FONT,size=16,bold=True,color='000000')
    for c in ws[4]:
        c.fill=PatternFill('solid',fgColor='075B60');c.font=Font(name=FONT,size=10,bold=True,color='FFFFFF');c.alignment=Alignment(horizontal='center',vertical='center')
    border=Side(style='thin',color='48AEC5')
    for ri,x in enumerate(d['inputs'],5):
        for ci,c in enumerate(ws[ri],1):
            c.border=Border(left=border,right=border,top=border,bottom=border)
            c.fill=PatternFill('solid',fgColor='FFF3CC' if 4<=ci<=3+count else 'E8F3F6' if ci==len(headers) else 'EEF7F8' if ri%2 else 'FFFFFF')
        ws.cell(ri,2).alignment=Alignment(horizontal='center',vertical='center')
        # Red bracketed dependencies are mandatory in Word; mirror emphasis in the workbook.
        if x.get('dependency_note'):ws.cell(ri,3).font=Font(name=FONT,size=10,color='C00000')
        lines=max(sum(max(1,(len(part)+int(widths[ci-1]/1.7)-1)//int(widths[ci-1]/1.7)) for part in str(c.value or '').split('\n')) for ci,c in enumerate(ws[ri],1))
        ws.row_dimensions[ri].height=max(55,lines*15+10)
    ws.freeze_panes='D5';ws.auto_filter.ref=f'A4:{end}{ws.max_row}'
    ws.print_title_rows='1:4';ws.sheet_view.showGridLines=False
    ws.page_setup.orientation='landscape';ws.page_setup.paperSize=ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr.fitToPage=True;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
    ws.print_area=f'A1:{end}{ws.max_row}'
    out.parent.mkdir(parents=True,exist_ok=True);wb.save(out);return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('data');p.add_argument('output');a=p.parse_args();print(build(load_checked(a.data),a.output))
