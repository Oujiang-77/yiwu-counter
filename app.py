from __future__ import annotations
import argparse
import ctypes
import io
import json
import logging
import os
import secrets
import socket
import shutil
import sys
import threading
import time
import uuid
import webbrowser
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
import uvicorn
from fastapi import FastAPI,File,UploadFile,Request,HTTPException
from fastapi.responses import FileResponse,JSONResponse,RedirectResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from storage import Store,VERSION
from sheets import FIELDS,inspect_book,read_sheet,guess_mapping,preview_import,save_image,template_bytes,export_bytes
import recognition

DEFAULT_DATA_DIR_NAME = 'HuoYouShu'

def default_data_dir():
    return Path(os.environ.get('LOCALAPPDATA',str(Path.home()))) / DEFAULT_DATA_DIR_NAME

def choose_data_folder():
    """Show a native Windows folder picker for first-run data placement."""
    if os.name != 'nt':
        return None
    class BrowseInfo(ctypes.Structure):
        _fields_ = [
            ('hwndOwner', wintypes.HWND), ('pidlRoot', wintypes.LPVOID),
            ('pszDisplayName', wintypes.LPWSTR), ('lpszTitle', wintypes.LPCWSTR),
            ('ulFlags', wintypes.UINT), ('lpfn', wintypes.LPVOID),
            ('lParam', wintypes.LPARAM), ('iImage', ctypes.c_int),
        ]
    shell32 = ctypes.windll.shell32
    ole32 = ctypes.windll.ole32
    shell32.SHBrowseForFolderW.argtypes = [ctypes.POINTER(BrowseInfo)]
    shell32.SHBrowseForFolderW.restype = wintypes.LPVOID
    shell32.SHGetPathFromIDListW.argtypes = [wintypes.LPVOID,wintypes.LPWSTR]
    shell32.SHGetPathFromIDListW.restype = wintypes.BOOL
    ole32.CoTaskMemFree.argtypes = [wintypes.LPVOID]
    ole32.CoTaskMemFree.restype = None
    ole32.CoInitialize.argtypes = [wintypes.LPVOID]
    ole32.CoInitialize.restype = ctypes.c_long
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    display_name = ctypes.create_unicode_buffer(260)
    info = BrowseInfo(None, None, ctypes.cast(display_name,wintypes.LPWSTR), '请选择商品资料的文件存储位置', 0x0040, None, 0, 0)
    com_ready = ole32.CoInitialize(None) >= 0
    try:
        pidl = shell32.SHBrowseForFolderW(ctypes.byref(info))
        if not pidl:
            return None
        path = ctypes.create_unicode_buffer(32768)
        return Path(path.value) if shell32.SHGetPathFromIDListW(pidl, path) else None
    finally:
        if 'pidl' in locals() and pidl:
            ole32.CoTaskMemFree(pidl)
        if com_ready:
            ole32.CoUninitialize()

def resolve_data_dir(explicit=None):
    """Resolve the persistent data directory, prompting only on first run."""
    if explicit:
        return Path(explicit)
    default = default_data_dir()
    marker = default / 'data-location.json'
    if (default / 'counter.sqlite3').exists():
        return default
    if marker.exists():
        try:
            selected = Path(json.loads(marker.read_text('utf8')).get('path','')).expanduser()
            if selected:
                try:
                    selected.mkdir(parents=True,exist_ok=True)
                    return selected
                except OSError:
                    pass
        except (OSError,ValueError,TypeError):
            pass
    selected = choose_data_folder()
    root = selected or default
    try:
        default.mkdir(parents=True,exist_ok=True)
        marker.write_text(json.dumps({'path':str(root)},ensure_ascii=False),encoding='utf8')
    except OSError:
        pass
    return root

def copy_data_dir(source, target):
    source = Path(source).resolve()
    target = Path(target).resolve()
    if source == target:
        return
    if source in target.parents or target in source.parents:
        raise ValueError('新存储位置不能放在当前数据目录里面或包含当前数据目录')
    target.mkdir(parents=True,exist_ok=True)
    if any(target.iterdir()):
        raise ValueError('请选择空文件夹作为新的存储位置')
    for item in source.iterdir():
        if item.name in ('runtime.json','app.log','data-location.json'):
            continue
        destination = target / item.name
        if item.is_dir():
            shutil.copytree(item,destination)
        else:
            shutil.copy2(item,destination)

def make_app(data_dir,token=None):
    store=Store(data_dir);token=token or secrets.token_urlsafe(32)
    app=FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
    app.state.store=store;app.state.token=token;app.state.previews={}
    root=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    web=root/'web'

    @app.middleware('http')
    async def local_access(req,call_next):
        host=req.headers.get('host','').split(':')[0]
        if host not in ('127.0.0.1','localhost'):
            return JSONResponse({'detail':'仅允许本机访问'},status_code=403)
        origin=req.headers.get('origin')
        if origin and origin not in (f'http://{req.headers.get("host")}',):
            return JSONResponse({'detail':'访问来源无效'},status_code=403)
        public=req.url.path in ('/health','/') or req.url.path.startswith('/assets/')
        if not public and not secrets.compare_digest(req.cookies.get('counter_session',''),token):
            return JSONResponse({'detail':'会话失效，请重新双击程序打开'},status_code=401)
        if req.method in ('POST','PUT','DELETE') and req.headers.get('x-counter-request')!='1':
            return JSONResponse({'detail':'请求校验失败'},status_code=403)
        try:result=await call_next(req)
        except Exception:
            logging.exception('Unhandled request failure')
            return JSONResponse({'detail':'操作失败，请重试或查看本地日志'},status_code=500)
        result.headers['X-Content-Type-Options']='nosniff'
        result.headers['Cache-Control']='no-store'
        result.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        return result

    @app.exception_handler(ValueError)
    async def invalid(req,exc):return JSONResponse({'detail':str(exc)},status_code=400)

    @app.get('/health')
    def health():return {'application':'yiwu-counter','version':VERSION}

    @app.get('/')
    def index(request:Request,session:str=''):
        if session and secrets.compare_digest(session,token):
            r=RedirectResponse('/',status_code=303);r.set_cookie('counter_session',token,httponly=True,samesite='strict');return r
        if not secrets.compare_digest(request.cookies.get('counter_session',''),token):
            raise HTTPException(401,'请从“档口开单系统.exe”重新打开，当前浏览器没有本机会话。')
        return FileResponse(web/'index.html')

    app.mount('/assets',StaticFiles(directory=web),name='assets')

    @app.get('/api/state')
    def state():return {'products':store.products(),'draft':store.get_value('draft',{'selected':[],'quantities':{}}),'version':VERSION,'dataDir':str(store.root),'ocrAvailable':recognition.available()}

    @app.post('/api/data-location/select')
    def select_data_location():
        nonlocal store
        selected=choose_data_folder()
        if not selected:return {'cancelled':True,'dataDir':str(store.root)}
        target=Path(selected)
        if target.resolve()==store.root.resolve():return {'cancelled':False,'dataDir':str(store.root)}
        with store.lock:
            copy_data_dir(store.root,target)
            marker=default_data_dir()/'data-location.json'
            try:
                marker.parent.mkdir(parents=True,exist_ok=True)
                marker.write_text(json.dumps({'path':str(target)},ensure_ascii=False),encoding='utf8')
            except OSError:
                logging.exception('无法更新数据目录记忆文件')
            store=Store(target)
            app.state.store=store
        return {'cancelled':False,'dataDir':str(store.root)}

    @app.post('/api/products')
    def create(data:dict):return store.save_product(data)

    @app.put('/api/products/{pid}')
    def edit(pid:int,data:dict):return store.save_product(data,pid)

    @app.put('/api/draft')
    def draft(data:dict):
        ids={p['id'] for p in store.products()}
        selected=[]
        for v in data.get('selected',[]):
            if not isinstance(v,int):raise ValueError('草稿商品编号无效')
            if v in ids and v not in selected:selected.append(v)
        quantities=data.get('quantities',{})
        if not isinstance(quantities,dict) or len(quantities)>10000:raise ValueError('草稿格式无效')
        safe={str(pid):quantities.get(str(pid)) for pid in selected if isinstance(quantities.get(str(pid)),(int,float))}
        store.set_value('draft',{'selected':selected,'quantities':safe});return {'ok':True}

    async def upload_bytes(file,max_bytes=15*1024**2):
        raw=await file.read(max_bytes+1)
        if len(raw)>max_bytes:raise ValueError('文件超过允许大小')
        return raw

    @app.post('/api/images')
    async def upload_image(file:UploadFile=File(...)):
        raw=await upload_bytes(file)
        try:name=save_image(raw,store)
        except (Image.DecompressionBombError,OSError):raise ValueError('无法读取图片，请使用 JPG / PNG / WEBP')
        return {'image':name}

    @app.get('/api/images/{name}')
    def image(name:str):
        import re
        if not re.fullmatch(r'[a-f0-9]{32}\.jpg',name):raise HTTPException(404)
        p=store.root/'images'/name
        if not p.exists():raise HTTPException(404)
        return FileResponse(p)

    @app.get('/api/import-template')
    def template():
        from starlette.responses import Response
        return Response(template_bytes(),media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',headers={'Content-Disposition':"attachment; filename*=UTF-8''%E5%95%86%E5%93%81%E5%AF%BC%E5%85%A5%E6%A8%A1%E6%9D%BF.xlsx"})

    @app.post('/api/import/upload')
    async def upload_book(file:UploadFile=File(...)):
        suffix=Path(file.filename or '').suffix.lower()
        if suffix not in ('.xlsx','.xls'):raise ValueError('请选择 .xlsx 或 .xls 文件')
        raw=await upload_bytes(file,30*1024**2);batch=uuid.uuid4().hex
        p=store.root/'imports'/(batch+suffix);p.write_bytes(raw)
        try:names=inspect_book(p)
        except Exception:
            p.unlink(missing_ok=True);raise ValueError('表格无法读取，请确认未加密并另存为标准 Excel 文件')
        app.state.previews[batch]={'path':p,'names':names,'time':time.time()}
        return {'batch':batch,'sheets':names,'filename':file.filename,'fields':FIELDS}

    def get_batch(batch):
        item=app.state.previews.get(batch)
        if not item or time.time()-item['time']>3600:raise ValueError('导入会话已过期，请重新上传')
        return item

    @app.post('/api/import/preview')
    def preview(data:dict):
        b=get_batch(data.get('batch'))
        if data.get('sheet') not in b['names']:raise ValueError('工作表不存在')
        result=preview_import(store,b['path'],data)
        preview_id=uuid.uuid4().hex;b['preview']=result;b['previewId']=preview_id
        return dict(result,previewId=preview_id)

    @app.post('/api/import/commit')
    def commit(data:dict):
        b=get_batch(data.get('batch'))
        if data.get('previewId')!=b.get('previewId'):raise ValueError('预览已变化，请重新确认')
        valid=[r['data'] for r in b['preview']['rows'] if not r['error']]
        if not valid:raise ValueError('没有可以导入的行')
        with store.lock:
            count=store.commit_import(valid)
            app.state.previews.pop(data['batch'],None)
        return {'count':count}

    @app.post('/api/orders')
    def export(data:dict):
        with store.lock:
            items=store.order_items(data.get('items',[]));raw,extension=export_bytes(items,store,data.get('mode','single'))
            order_id=datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]
            name='报货单_'+order_id+extension;p=store.root/'exports'/name
            p.write_bytes(raw);store.save_order(order_id,items,name)
        return {'id':order_id,'filename':name,'url':'/api/exports/'+name}

    @app.get('/api/orders')
    def orders():return store.orders()

    @app.get('/api/exports/{name}')
    def get_export(name:str):
        if Path(name).name!=name or '/' in name or '\\' in name:raise HTTPException(404)
        p=store.root/'exports'/name
        if not p.is_file():raise HTTPException(404,'文件不存在，可能已从备份恢复；请重新开单导出')
        return FileResponse(p,filename=name)

    @app.post('/api/recognize')
    async def ocr(request:Request,file:UploadFile=File(...)):
        if not recognition.available():raise ValueError('离线识别组件未安装；请使用完整软件包或手动录入')
        raw=await upload_bytes(file)
        try:rotation=int(request.query_params.get('rotation',0))
        except ValueError:raise ValueError('旋转角度无效')
        if rotation not in (0,90,180,270):raise ValueError('旋转角度无效')
        from starlette.concurrency import run_in_threadpool
        return await run_in_threadpool(recognition.recognize,raw,rotation,store.products())

    @app.get('/api/backups')
    def backups():return store.backups()

    @app.post('/api/backups')
    def create_backup():return {'name':store.backup()}

    @app.post('/api/backups/restore')
    def restore(data:dict):
        if data.get('confirmation')!='恢复备份':raise ValueError('请输入“恢复备份”确认')
        name=store.restore(data.get('name',''));app.state.previews.clear();return {'safetyBackup':name}

    @app.get('/api/backups/{name}')
    def download_backup(name:str):
        if name not in {b['name'] for b in store.backups()}:raise HTTPException(404)
        return FileResponse(store.root/'backups'/name,filename=name)

    @app.post('/api/shutdown')
    def shutdown():
        if getattr(app.state,'server',None):
            threading.Timer(.7,lambda:setattr(app.state.server,'should_exit',True)).start()
        return {'ok':True}

    return app

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--data-dir');parser.add_argument('--port',type=int,default=0);parser.add_argument('--no-browser',action='store_true');args=parser.parse_args()
    root=resolve_data_dir(args.data_dir)
    root.mkdir(parents=True,exist_ok=True)
    logging.basicConfig(filename=root/'app.log',level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',encoding='utf8')
    runtime=root/'runtime.json'
    if runtime.exists():
        try:
            import urllib.request
            old=json.loads(runtime.read_text('utf8'))
            if old['url'].startswith('http://127.0.0.1:'):
                with urllib.request.urlopen(old['url']+'/health',timeout=1) as response:
                    health=json.load(response)
                if health.get('application')=='yiwu-counter':
                    if not args.no_browser:webbrowser.open(old['url']+'/?session='+old['token'])
                    return
        except Exception:pass
    app=make_app(root)
    app.state.store.daily_backup()
    sock=socket.socket();sock.bind(('127.0.0.1',args.port));sock.listen(128)
    port=sock.getsockname()[1];url=f'http://127.0.0.1:{port}'
    runtime.write_text(json.dumps({'url':url,'token':app.state.token,'pid':os.getpid()}),'utf8')
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=port,log_config=None,access_log=False));app.state.server=server
    if not args.no_browser:threading.Timer(1.3,lambda:webbrowser.open(url+'/?session='+app.state.token)).start()
    if sys.stdout:print('READY '+url,flush=True)
    try:server.run(sockets=[sock])
    finally:
        try:
            if json.loads(runtime.read_text('utf8')).get('pid')==os.getpid():runtime.unlink(missing_ok=True)
        except Exception:pass

if __name__=='__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    try:main()
    except Exception as e:
        logging.exception('Startup failed')
        if getattr(sys,'frozen',False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(0,'程序启动失败：'+str(e)+'\n请查看数据目录中的 app.log。','档口开单系统',16)
        else:raise
