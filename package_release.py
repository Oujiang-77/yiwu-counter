"""Package only the frozen program and user documentation, never development data."""
import hashlib
import importlib.metadata as metadata
import json
import shutil
import zipfile
from pathlib import Path

root=Path(__file__).resolve().parent
bundle=root/'dist'/'档口开单系统'
assert (bundle/'档口开单系统.exe').is_file()
shutil.copy2(root/'使用说明.txt',bundle/'使用说明.txt')
licenses=bundle/'第三方许可';licenses.mkdir(exist_ok=True)
inventory=[]
for dist in metadata.distributions():
    name=dist.metadata['Name'];version=dist.version
    inventory.append({'name':name,'version':version,'license':dist.metadata.get('License-Expression') or dist.metadata.get('License',''),'home':dist.metadata.get('Home-page','')})
    for file in dist.files or []:
        if 'license' not in str(file).lower() and 'copying' not in str(file).lower() and 'notice' not in str(file).lower():continue
        if file.suffix.lower() not in ('','.txt','.md','.rst'):continue
        source=Path(dist.locate_file(file))
        if source.is_file() and source.stat().st_size<2_000_000:
            dest=licenses/name/str(file).replace('../','').replace('..\\','')
            dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
(licenses/'dependencies.json').write_text(json.dumps(inventory,ensure_ascii=False,indent=2),'utf8')
output=root.parent/'outputs'/'档口开单系统-0.1.0-Windows-x64.zip'
output.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for p in sorted(bundle.rglob('*')):
        if p.is_file():z.write(p,Path(bundle.name)/p.relative_to(bundle))
digest=hashlib.sha256(output.read_bytes()).hexdigest()
output.with_suffix('.sha256.txt').write_text(digest+'  '+output.name+'\n','utf8')
print(json.dumps({'file':str(output),'bytes':output.stat().st_size,'sha256':digest},ensure_ascii=False))
