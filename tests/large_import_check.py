"""Exercise real HTTP multipart upload and image import with a 272+ MiB workbook."""
import io
import json
import sys
import time
import zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from openpyxl import Workbook
from openpyxl.drawing.image import Image as XLImage
from PIL import Image

folder=Path('test-import-update');folder.mkdir(exist_ok=True)
w=Workbook();s=w.active
s.append(['厂家编码','商品名称','装箱数','出厂价'])
s.append(['001','大文件测试商品',12,3.5])
picture=io.BytesIO();Image.new('RGB',(40,40),'blue').save(picture,'PNG');picture.seek(0)
s.add_image(XLImage(picture),'E2')
fixture=folder/'fixture.xlsx';w.save(fixture)
large=folder/'large-272mb.xlsx'
with zipfile.ZipFile(fixture) as original,zipfile.ZipFile(large,'w',zipfile.ZIP_STORED) as z:
    for entry in original.infolist():z.writestr(entry,original.read(entry.filename))
    # Unused media models a large vendor workbook without requiring private data.
    with z.open('xl/media/size-fixture.bin','w',force_zip64=True) as target:
        for _ in range(272):target.write(b'\0'*1024**2)
runtime=json.loads((folder/'runtime.json').read_text('utf8'))
start=time.monotonic()
with httpx.Client(base_url=runtime['url'],timeout=180,follow_redirects=True,trust_env=False) as client:
    client.get('/?session='+runtime['token']);headers={'X-Counter-Request':'1'}
    with large.open('rb') as source:
        r=client.post('/api/import/upload',files={'file':(large.name,source)},headers=headers)
    r.raise_for_status();batch=r.json()['batch']
    config={'batch':batch,'sheet':'Sheet','prefix':'BIG','factory':'大文件测试厂','start':1}
    r=client.post('/api/import/preview',json=config,headers=headers);r.raise_for_status();first=r.json()
    assert first['valid']==1,first
    assert first['rows'][0]['data']['image'],first
    config['mapping']=first['mapping']
    r=client.post('/api/import/preview',json=config,headers=headers);r.raise_for_status()
    assert r.json()['rows'][0]['data']['image']==first['rows'][0]['data']['image']
print(json.dumps({'bytes':large.stat().st_size,'seconds':round(time.monotonic()-start,2),'valid':first['valid'],'image':True,'cache':True}))
