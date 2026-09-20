from __future__ import annotations
import io
import re
import uuid
import zipfile
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.drawing.image import Image as XLImage
from PIL import Image, ImageOps
from storage import validate_product

FIELDS={'code':'销售编码','factoryCode':'厂家编码','name':'商品名称','factory':'厂家名称','area':'厂家地区','size':'尺寸','battery':'电池容量','charger':'充电头 / 接口','pack':'装箱数','inner':'中包数','volume':'单件体积','price':'出厂价','min':'起订件数','cat':'分类','notes':'备注'}
ALIASES={'code':['销售编码','自定义编码','商家编码'],'factoryCode':['厂家编码','货号','型号','产品编码'],'name':['商品名称','产品名称','品名','名称'],'factory':['厂家名称','厂家','供应商'],'area':['厂家地区','地区','产地'],'size':['尺寸','产品尺寸','规格'],'battery':['电池容量','电池'],'charger':['充电头 / 接口','充电头','接口'],'pack':['装箱数','装箱数量','每箱数量','箱规'],'inner':['中包数','中包数量'],'volume':['单件体积','体积','每箱体积'],'price':['出厂价','单价','价格'],'min':['起订件数','起订量'],'cat':['分类','类别'],'notes':['备注']}

def clean_header(s):
    return re.sub(r'[\s\(（].*','',str(s).strip()).lower()

def save_image(data,store):
    if len(data)>15*1024**2:raise ValueError('图片超过 15 MB')
    with Image.open(io.BytesIO(data)) as im:
        if im.width*im.height>40_000_000:raise ValueError('图片分辨率过大')
        im=ImageOps.exif_transpose(im).convert('RGB')
        im.thumbnail((1800,1800))
        name=uuid.uuid4().hex+'.jpg'
        im.save(store.root/'images'/name,quality=88)
    return name

def inspect_book(path):
    if path.suffix=='.xls':
        import xlrd
        book=xlrd.open_workbook(path)
        return book.sheet_names()
    with zipfile.ZipFile(path) as z:
        if sum(i.file_size for i in z.infolist())>200*1024**2:raise ValueError('表格展开后过大，请拆分后导入')
    b=load_workbook(path,read_only=True,data_only=True)
    names=b.sheetnames;b.close();return names

def read_sheet(path,sheet,header_row,store):
    if not 1<=header_row<=50:raise ValueError('表头行须在第 1～50 行')
    pics={};warnings=[]
    if path.suffix=='.xls':
        import xlrd
        b=xlrd.open_workbook(path);s=b.sheet_by_name(sheet)
        if s.nrows>10001:raise ValueError('每次最多导入 10000 行，请拆分文件')
        vals=[[int(v) if isinstance(v,float) and v.is_integer() else v for v in s.row_values(i)] for i in range(s.nrows)]
        warnings.append('旧版 .xls 仅导入文字与数值，商品图片请另行上传。')
    else:
        b=load_workbook(path,data_only=True)
        s=b[sheet]
        if s.max_row>10001 or s.max_column>100:raise ValueError('表格最多 10000 条数据、100 列，请删除多余空行列或拆分文件')
        vals=[]
        for row in s:
            line=[]
            for c in row:
                v=c.value
                if isinstance(v,(int,float)) and re.fullmatch('0{2,}',c.number_format or ''):
                    v=str(int(v)).zfill(len(c.number_format))
                line.append(v)
            vals.append(line)
        for im in s._images:
            try:
                row=im.anchor._from.row+1
                if row in pics:warnings.append(f'第 {row} 行有多张图片，仅使用第一张。');continue
                pics[row]=save_image(im._data(),store)
            except Exception:warnings.append('部分嵌入图片无法对应商品行，请导入后补充。')
        b.close()
    if len(vals)<header_row:raise ValueError('表头行超出工作表范围')
    heads=[str(v or '').strip() for v in vals[header_row-1]]
    return heads,[(i+1,vals[i]) for i in range(header_row,len(vals)) if any(v is not None and str(v).strip() for v in vals[i])],pics,warnings

def guess_mapping(headers):
    mapping={}
    for key,names in ALIASES.items():
        for i,h in enumerate(headers):
            if clean_header(h) in [clean_header(n) for n in names]:mapping[key]=i;break
    return mapping

def preview_import(store,path,config):
    sheet=str(config['sheet']);header=int(config.get('header',1))
    heads,raw,pics,warnings=read_sheet(path,sheet,header,store)
    mapping=config.get('mapping') or guess_mapping(heads)
    indices=[int(v) for v in mapping.values() if v is not None and str(v)!='']
    if len(indices)!=len(set(indices)):raise ValueError('同一列不能映射到多个字段')
    existing=store.products();codes={p['code'] for p in existing};factory_codes={(p['factory'],p['factoryCode'].upper()) for p in existing}
    result=[];prefix=str(config.get('prefix') or '').strip().upper()
    if prefix and not re.fullmatch(r'[A-Z0-9]{1,12}',prefix):raise ValueError('销售编码前缀仅支持 1～12 位字母或数字')
    try:start=int(config.get('start') or 1)
    except (ValueError,TypeError):raise ValueError('起始序号无效')
    if start<1:raise ValueError('起始序号须大于 0')
    for seq,(number,values) in enumerate(raw):
        data={}
        for key in FIELDS:
            idx=mapping.get(key)
            if idx is not None and str(idx)!='':
                idx=int(idx)
                if idx<0 or idx>=len(heads):raise ValueError('列映射超出范围')
                val=values[idx] if idx<len(values) else None
                if isinstance(val,float) and val.is_integer():val=int(val)
                data[key]='' if val is None else val
        if not data.get('code') and prefix:data['code']=f'{prefix}-{start+seq:02d}'
        if not data.get('factory'):data['factory']=config.get('factory','')
        for k,v in {'inner':1,'min':1,'volume':0,'cat':'日用百货'}.items():
            if data.get(k) in (None,''):data[k]=v
        data['image']=pics.get(number,'')
        error=''
        try:
            data=validate_product(data)
            pair=(data['factory'],data['factoryCode'].upper())
            if data['code'] in codes:raise ValueError('销售编码与已有商品或本批次其他行重复')
            if pair in factory_codes:raise ValueError('同厂家货号已存在，默认跳过；更新请编辑原商品')
            codes.add(data['code']);factory_codes.add(pair)
        except (ValueError,TypeError) as e:error=str(e)
        result.append({'row':number,'data':data,'error':error})
    return {'headers':heads,'mapping':mapping,'rows':result,'warnings':warnings,'valid':sum(not r['error'] for r in result),'total':len(result)}

def literal(cell,value):
    cell.value=value
    if isinstance(value,str):cell.data_type='s'

def style_sheet(ws,header):
    for c in ws[header]:c.font=Font(name='Microsoft YaHei',bold=True,color='FFFFFF');c.fill=PatternFill('solid',fgColor='3566EC');c.alignment=Alignment(vertical='center',wrap_text=True)
    ws.row_dimensions[header].height=30
    ws.freeze_panes=f'A{header+1}'
    for col in range(1,ws.max_column+1):ws.column_dimensions[ws.cell(1,col).column_letter].width=19
    ws.column_dimensions['A'].width=28
    ws.sheet_properties.pageSetUpPr.fitToPage=True
    ws.page_setup.orientation='landscape';ws.page_setup.paperSize=ws.PAPERSIZE_A4;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0

def template_bytes():
    w=Workbook();s=w.active;s.title='商品导入模板'
    s.append(list(FIELDS.values()));style_sheet(s,1)
    note=w.create_sheet('填写说明');notes=['在商品导入模板工作表填写数据，第一行是表头。','必填：销售编码（或导入时生成）、厂家编码、商品名称、厂家名称（或导入时统一填写）、装箱数、出厂价。','销售编码和厂家编码建议设置为文本，保留前导零。','默认：起订件数 1，中包数 1，未填写单件体积按 0 处理；提交前请核对。','出厂价单位：元/个；装箱数：个/件；中包数：个/中包；体积：m³/件。','图片：插入普通图片并放到对应商品行；复杂 WPS 图片公式可能需要手动补图。']
    for n in notes:note.append([n])
    note.column_dimensions['A'].width=100
    out=io.BytesIO();w.save(out);return out.getvalue()

def workbook_bytes(items,store):
    book=Workbook();book.remove(book.active);groups=defaultdict(list)
    for p in items:groups[p['factory']].append(p)
    for index,(factory,ps) in enumerate(groups.items()):
        title=re.sub(r'[\\/*?:\[\]]','_',factory)[:25] or '厂家'
        if title in book.sheetnames:title+=f'_{index+1}'
        ws=book.create_sheet(title)
        ws.append(['厂家报货单',factory]);ws.append(['开单说明','1 件 = 1 箱；金额按出厂价计算，不含运费。'])
        headers=['商品名称','图片','销售编码','厂家编码','厂家名称','厂家地区','尺寸','电池容量','充电头 / 接口','装箱数','中包数','件数','总数量','出厂价','金额','单件体积','总体积','起订件数','备注']
        ws.append(headers)
        for j,p in enumerate(ps,4):
            values=[p['name'],'',p['code'],p['factoryCode'],p['factory'],p['area'],p['size'],p['battery'],p['charger'],p['pack'],p['inner'],p['quantity'],p['units'],p['price'],float(p['amount']),p['volume'],float(p['totalVolume']),p['min'],p.get('notes','')]
            for k,v in enumerate(values,1):literal(ws.cell(j,k),v);ws.cell(j,k).alignment=Alignment(vertical='center',wrap_text=True)
            ws.row_dimensions[j].height=54
            if p.get('image'):
                imagepath=store.root/'images'/p['image']
                if imagepath.exists():
                    im=XLImage(imagepath);scale=min(68/im.width,68/im.height);im.width*=scale;im.height*=scale;ws.add_image(im,f'B{j}')
            for k in (14,15):ws.cell(j,k).number_format='0.00'
            for k in (16,17):ws.cell(j,k).number_format='0.000000'
        row=ws.max_row+1;ws.cell(row,1,'合计')
        for c in ('L','M','O','Q'):ws[f'{c}{row}']=f'=SUM({c}4:{c}{row-1})'
        ws.auto_filter.ref=f'A3:S{row-1}';style_sheet(ws,3)
        ws.column_dimensions['B'].width=13;ws.print_title_rows='1:3'
        # Treat user-supplied names as literal text, including leading '='.
        literal(ws['B1'],factory)
    out=io.BytesIO();book.save(out);return out.getvalue()

def export_bytes(items,store,mode):
    if mode=='single':return workbook_bytes(items,store),'.xlsx'
    if mode!='multiple':raise ValueError('导出方式无效')
    groups=defaultdict(list)
    for p in items:groups[p['factory']].append(p)
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        for i,(f,ps) in enumerate(groups.items(),1):
            name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',f)[:70]
            z.writestr(f'{i}_{name}_报货单.xlsx',workbook_bytes(ps,store))
    return out.getvalue(),'.zip'
