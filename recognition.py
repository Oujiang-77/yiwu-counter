"""Bundled offline OCR. Never sends images or product data to a remote service."""
import io
import re
import threading
from PIL import Image,ImageOps

_engine=None
_lock=threading.Lock()

def available():
    import importlib.util
    return importlib.util.find_spec('rapidocr_onnxruntime') is not None

def parse_lines(lines,products):
    rows=[]
    for line in lines:
        text=line['text'];upper=text.upper()
        # Only an exact bounded sales code may be auto-selected. Names are candidate-only.
        exact=[p for p in products if re.search(r'(?<![A-Z0-9])'+re.escape(p['code'].upper())+r'(?![A-Z0-9])',upper)]
        candidates=[p['id'] for p in products if p['name'] in text or p['factoryCode'].upper() in upper]
        match=re.search(r'(\d+(?:\.\d+)?)\s*(件|箱|个|只|PCS)(?![A-Z])',upper)
        quantity=float(match.group(1)) if match else 0
        unit=('件' if match.group(2) in ('件','箱') else '个') if match else ''
        if not exact and not candidates and not match:continue
        if not match and len(exact)==1:
            after=re.sub(re.escape(exact[0]['code'].upper()),'',upper).strip(' :：-—')
            if re.fullmatch(r'\d+',after):quantity=int(after)
        rows.append({'raw':text,'id':exact[0]['id'] if len(exact)==1 else 0,'quantity':quantity,'unit':unit,
                     'reviewed':False,'candidates':candidates,'confidence':line['confidence']})
    return rows

def recognize(data,rotation,products):
    global _engine
    import numpy as np
    from rapidocr_onnxruntime import RapidOCR
    with _lock:
        if _engine is None:
            _engine=RapidOCR(intra_op_num_threads=2,inter_op_num_threads=2)
        with Image.open(io.BytesIO(data)) as im:
            if im.width*im.height>40_000_000:raise ValueError('图片分辨率过大')
            im=ImageOps.exif_transpose(im).convert('RGB')
            if rotation:im=im.rotate(-rotation,expand=True)
            im.thumbnail((2400,2400))
            result,_=_engine(np.array(im)[:,:,::-1])
    cells=[]
    for box,text,score in result or []:
        x=min(p[0] for p in box);y=sum(p[1] for p in box)/4
        height=max(p[1] for p in box)-min(p[1] for p in box)
        cells.append(dict(x=x,y=y,height=height,text=text,score=float(score)))
    groups=[]
    for c in sorted(cells,key=lambda x:x['y']):
        target=next((g for g in groups if abs(g[0]['y']-c['y'])<max(g[0]['height'],c['height'])*.55),None)
        if target is None:groups.append([c])
        else:target.append(c)
    lines=[{'text':' '.join(c['text'] for c in sorted(g,key=lambda c:c['x'])),'confidence':round(min(c['score'] for c in g),3)} for g in groups]
    return {'lines':lines,'rows':parse_lines(lines,products),'engine':'RapidOCR · 本地 CPU','warning':'离线识别可能漏行或错字，尤其是倾斜和潦草手写单；请逐行对照原图确认，不能用识别结果直接下单。'}
